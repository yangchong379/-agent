import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_db, get_llm, require_auth
from app.core.security import detect_prompt_injection, redact_pii, safe_text
from app.db.models import (
    AuditLog,
    Conversation,
    ConversationMessage,
    JobRecord,
    ResumeRecord,
    UserMemory,
)
from app.schemas.api import ConversationCreate, MemoryCreate, MemoryUpdate, MessageCreate
from app.services.memory import memory_fingerprint, rank_memories, upsert_memory
from app.services.career_tools import classify_career_intent, rank_jobs
from app.workflows.coach import create_coach_reply, summarize_conversation


router = APIRouter()


def _conversation(
    db: Session, tenant_id: str, owner_id: str, conversation_id: str, *, lock: bool = False
):
    statement = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == tenant_id,
        Conversation.owner_id == owner_id,
    )
    if lock:
        statement = statement.with_for_update()
    record = db.scalar(statement)
    if not record:
        raise HTTPException(status_code=404, detail="conversation not found")
    return record


def _memory(db: Session, tenant_id: str, owner_id: str, memory_id: str) -> UserMemory:
    record = db.scalar(
        select(UserMemory).where(
            UserMemory.id == memory_id,
            UserMemory.tenant_id == tenant_id,
            UserMemory.owner_id == owner_id,
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="memory not found")
    return record


def _audit(
    db: Session,
    request: Request,
    auth: AuthContext,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            tenant_id=auth.tenant_id,
            request_id=request.state.request_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details_json=json.dumps(details or {}, ensure_ascii=False),
        )
    )


def _serialize_conversation(record: Conversation, include_messages: bool = True) -> dict:
    result = {
        "id": record.id,
        "title": record.title,
        "resume_id": record.resume_id,
        "job_id": record.job_id,
        "memory_enabled": record.memory_enabled,
        "summary": record.summary_text,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    if include_messages:
        result["messages"] = [
            {
                "id": item.id,
                "sequence_no": item.sequence_no,
                "role": item.role,
                "content": item.content,
                "created_at": item.created_at,
            }
            for item in sorted(record.messages, key=lambda message: message.sequence_no)
        ]
    return result


def _serialize_memory(record: UserMemory) -> dict:
    return {
        "id": record.id,
        "category": record.category,
        "content": record.content,
        "is_active": record.is_active,
        "source_conversation_id": record.source_conversation_id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


@router.post("/conversations", status_code=status.HTTP_201_CREATED, tags=["career-coach"])
def create_conversation(
    payload: ConversationCreate,
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    if payload.resume_id and not db.scalar(
        select(ResumeRecord.id).where(
            ResumeRecord.id == payload.resume_id, ResumeRecord.tenant_id == auth.tenant_id
        )
    ):
        raise HTTPException(status_code=404, detail="resume not found")
    if payload.job_id and not db.scalar(
        select(JobRecord.id).where(
            JobRecord.id == payload.job_id, JobRecord.tenant_id == auth.tenant_id
        )
    ):
        raise HTTPException(status_code=404, detail="job not found")
    record = Conversation(
        tenant_id=auth.tenant_id,
        owner_id=auth.user_id,
        title=payload.title,
        resume_id=payload.resume_id,
        job_id=payload.job_id,
        memory_enabled=payload.memory_enabled,
    )
    db.add(record)
    db.flush()
    _audit(db, request, auth, "conversation.created", "conversation", record.id)
    db.commit()
    return _serialize_conversation(record)


@router.get("/conversations", tags=["career-coach"])
def list_conversations(
    auth: AuthContext = Depends(require_auth), db: Session = Depends(get_db)
):
    records = db.scalars(
        select(Conversation)
        .where(
            Conversation.tenant_id == auth.tenant_id,
            Conversation.owner_id == auth.user_id,
        )
        .order_by(Conversation.updated_at.desc())
        .limit(100)
    )
    return [_serialize_conversation(item, include_messages=False) for item in records]


@router.get("/conversations/{conversation_id}", tags=["career-coach"])
def get_conversation(
    conversation_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    return _serialize_conversation(
        _conversation(db, auth.tenant_id, auth.user_id, conversation_id)
    )


@router.post("/conversations/{conversation_id}/messages", tags=["career-coach"])
def send_message(
    conversation_id: str,
    payload: MessageCreate,
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    conversation = _conversation(
        db, auth.tenant_id, auth.user_id, conversation_id, lock=True
    )
    try:
        user_content = redact_pii(safe_text(payload.content, 20_000))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ordered = sorted(conversation.messages, key=lambda item: item.sequence_no)
    sequence = ordered[-1].sequence_no + 1 if ordered else 1
    user_message = ConversationMessage(
        conversation_id=conversation.id,
        sequence_no=sequence,
        role="user",
        content=user_content,
    )
    db.add(user_message)
    db.flush()

    memory_records: list[UserMemory] = []
    if conversation.memory_enabled:
        active_memories = list(
            db.scalars(
                select(UserMemory).where(
                    UserMemory.tenant_id == auth.tenant_id,
                    UserMemory.owner_id == auth.user_id,
                    UserMemory.is_active.is_(True),
                )
            )
        )
        memory_records = rank_memories(active_memories, user_content)

    resume_context = None
    if conversation.resume_id is None:
        latest_resume = db.scalar(
            select(ResumeRecord)
            .where(ResumeRecord.tenant_id == auth.tenant_id)
            .order_by(ResumeRecord.created_at.desc())
            .limit(1)
        )
        if latest_resume:
            conversation.resume_id = latest_resume.id
    if conversation.resume_id:
        resume = db.scalar(
            select(ResumeRecord).where(
                ResumeRecord.id == conversation.resume_id,
                ResumeRecord.tenant_id == auth.tenant_id,
            )
        )
        if resume:
            resume_context = json.loads(resume.profile_json)

    job_context = None
    if conversation.job_id:
        job = db.scalar(
            select(JobRecord).where(
                JobRecord.id == conversation.job_id,
                JobRecord.tenant_id == auth.tenant_id,
            )
        )
        if job:
            job_context = {
                "title": job.title,
                "company": job.company,
                "city": job.city,
                "description": job.jd_text,
            }

    available_jobs = list(
        db.scalars(
            select(JobRecord)
            .where(JobRecord.tenant_id == auth.tenant_id)
            .order_by(JobRecord.created_at.desc())
            .limit(10)
        )
    )

    recent = [
        {"role": item.role, "content": item.content}
        for item in (ordered + [user_message])[-12:]
    ]
    raw_jobs = [
        {
            "id": item.id,
            "title": item.title,
            "company": item.company,
            "city": item.city,
            "description": item.jd_text[:2000],
        }
        for item in available_jobs
    ]
    intent = classify_career_intent(user_content)
    ranked_jobs = rank_jobs(resume_context, raw_jobs)
    reply = create_coach_reply(
        get_llm(),
        user_message=user_content,
        recent_messages=recent,
        summary=conversation.summary_text,
        memories=[
            {"category": item.category, "content": item.content} for item in memory_records
        ],
        resume_context=resume_context,
        job_context=job_context,
        available_jobs=ranked_jobs,
        tool_context={"intent": intent, "ranked_jobs": ranked_jobs},
    )
    assistant_message = ConversationMessage(
        conversation_id=conversation.id,
        sequence_no=sequence + 1,
        role="assistant",
        content=reply.reply,
    )
    db.add(assistant_message)

    stored_memories: list[UserMemory] = []
    if conversation.memory_enabled:
        for candidate in reply.memory_candidates:
            stored = upsert_memory(
                db,
                tenant_id=auth.tenant_id,
                owner_id=auth.user_id,
                category=candidate.category,
                content=redact_pii(candidate.content),
                source_conversation_id=conversation.id,
            )
            if stored:
                stored_memories.append(stored)

    complete_history = ordered + [user_message, assistant_message]
    if len(complete_history) > 16 and len(complete_history) % 8 == 2:
        conversation.summary_text = summarize_conversation(
            get_llm(),
            previous_summary=conversation.summary_text,
            messages=[
                {"role": item.role, "content": item.content} for item in complete_history[:-8]
            ],
        )
    conversation.updated_at = datetime.now(UTC)
    _audit(
        db,
        request,
        auth,
        "conversation.message_created",
        "conversation",
        conversation.id,
        {
            "sequence_no": sequence,
            "memory_count": len(stored_memories),
            "intent": intent,
            "prompt_injection_flag": detect_prompt_injection(payload.content),
        },
    )
    db.commit()
    db.refresh(assistant_message)
    return {
        "message": {
            "id": assistant_message.id,
            "sequence_no": assistant_message.sequence_no,
            "role": assistant_message.role,
            "content": assistant_message.content,
            "created_at": assistant_message.created_at,
        },
        "memories_saved": [_serialize_memory(item) for item in stored_memories],
    }


@router.get("/memories", tags=["memory"])
def list_memories(
    include_inactive: bool = False,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    statement = select(UserMemory).where(
        UserMemory.tenant_id == auth.tenant_id,
        UserMemory.owner_id == auth.user_id,
    )
    if not include_inactive:
        statement = statement.where(UserMemory.is_active.is_(True))
    records = db.scalars(statement.order_by(UserMemory.updated_at.desc()).limit(200))
    return [_serialize_memory(item) for item in records]


@router.post("/memories", status_code=status.HTTP_201_CREATED, tags=["memory"])
def create_memory(
    payload: MemoryCreate,
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    record = upsert_memory(
        db,
        tenant_id=auth.tenant_id,
        owner_id=auth.user_id,
        category=payload.category,
        content=payload.content,
    )
    if record is None:
        raise HTTPException(status_code=422, detail="sensitive or invalid memory is not allowed")
    db.flush()
    _audit(db, request, auth, "memory.created", "memory", record.id)
    db.commit()
    return _serialize_memory(record)


@router.patch("/memories/{memory_id}", tags=["memory"])
def update_memory(
    memory_id: str,
    payload: MemoryUpdate,
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    record = _memory(db, auth.tenant_id, auth.user_id, memory_id)
    if payload.category is not None:
        record.category = payload.category
    if payload.content is not None:
        updated = redact_pii(payload.content).strip()
        record.content = updated
    if payload.is_active is not None:
        record.is_active = payload.is_active
    record.fingerprint = memory_fingerprint(record.category, record.content)
    _audit(db, request, auth, "memory.updated", "memory", record.id)
    db.commit()
    return _serialize_memory(record)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["memory"])
def delete_memory(
    memory_id: str,
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    record = _memory(db, auth.tenant_id, auth.user_id, memory_id)
    _audit(db, request, auth, "memory.deleted", "memory", record.id)
    db.delete(record)
    db.commit()
    return None
