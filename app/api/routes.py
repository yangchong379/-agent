import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_db, get_llm, get_retriever, require_auth
from app.config import get_settings
from app.core.security import detect_prompt_injection, redact_pii, safe_text
from app.db.models import AuditLog, InterviewRun, InterviewTurn, JobRecord, ResumeRecord
from app.schemas.api import AnswerCreate, HealthResponse, InterviewCreate, JobCreate, ResumeCreate, ReviewCreate
from app.schemas.domain import AnswerEvaluation
from app.workflows.interview import (
    build_preparation_graph,
    create_final_report,
    create_followup,
    evaluate_answer,
    parse_resume,
)


router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", environment=settings.app_env, llm_provider=settings.llm_provider)


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


def _resume(db: Session, tenant_id: str, resource_id: str) -> ResumeRecord:
    record = db.scalar(
        select(ResumeRecord).where(
            ResumeRecord.id == resource_id, ResumeRecord.tenant_id == tenant_id
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="resume not found")
    return record


def _job(db: Session, tenant_id: str, resource_id: str) -> JobRecord:
    record = db.scalar(
        select(JobRecord).where(JobRecord.id == resource_id, JobRecord.tenant_id == tenant_id)
    )
    if not record:
        raise HTTPException(status_code=404, detail="job not found")
    return record


def _run(db: Session, tenant_id: str, resource_id: str, *, lock: bool = False) -> InterviewRun:
    statement = select(InterviewRun).where(
        InterviewRun.id == resource_id, InterviewRun.tenant_id == tenant_id
    )
    if lock:
        statement = statement.with_for_update()
    record = db.scalar(statement)
    if not record:
        raise HTTPException(status_code=404, detail="interview not found")
    return record


@router.post("/resumes", status_code=status.HTTP_201_CREATED, tags=["resumes"])
def create_resume(
    payload: ResumeCreate,
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    try:
        raw = safe_text(payload.resume_text, settings.max_resume_chars)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    redacted = redact_pii(raw)
    profile = parse_resume(get_llm(), redacted)
    record = ResumeRecord(
        tenant_id=auth.tenant_id,
        source_name=payload.source_name,
        redacted_text=redacted,
        profile_json=profile.model_dump_json(),
        injection_flag=detect_prompt_injection(raw),
    )
    db.add(record)
    db.flush()
    _audit(db, request, auth, "resume.created", "resume", record.id, {"consent": True})
    db.commit()
    return {
        "id": record.id,
        "created_at": record.created_at,
        "profile": profile.model_dump(),
        "prompt_injection_flag": record.injection_flag,
    }


@router.post("/jobs", status_code=status.HTTP_201_CREATED, tags=["jobs"])
def create_job(
    payload: JobCreate,
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    try:
        jd_text = safe_text(payload.jd_text, get_settings().max_jd_chars)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record = JobRecord(
        tenant_id=auth.tenant_id,
        title=payload.title,
        company=payload.company,
        city=payload.city,
        jd_text=redact_pii(jd_text),
        source_url=str(payload.source_url) if payload.source_url else None,
        source_type=payload.source_type,
        injection_flag=detect_prompt_injection(jd_text),
    )
    db.add(record)
    db.flush()
    _audit(db, request, auth, "job.created", "job", record.id, {"source_type": record.source_type})
    db.commit()
    return {
        "id": record.id,
        "created_at": record.created_at,
        "prompt_injection_flag": record.injection_flag,
    }


@router.post("/interviews", status_code=status.HTTP_201_CREATED, tags=["interviews"])
def create_interview(
    payload: InterviewCreate,
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    if payload.idempotency_key:
        existing = db.scalar(
            select(InterviewRun).where(
                InterviewRun.tenant_id == auth.tenant_id,
                InterviewRun.idempotency_key == payload.idempotency_key,
            )
        )
        if existing:
            return _run_response(existing)
    resume = _resume(db, auth.tenant_id, payload.resume_id)
    job = _job(db, auth.tenant_id, payload.job_id)
    graph = build_preparation_graph(get_llm(), get_retriever())
    result = graph.invoke({"resume_text": resume.redacted_text, "jd_text": job.jd_text})
    run = InterviewRun(
        tenant_id=auth.tenant_id,
        resume_id=resume.id,
        job_id=job.id,
        status="awaiting_initial_answer",
        analysis_json=json.dumps(result["job_analysis"], ensure_ascii=False),
        rag_context=result["evidence"],
        idempotency_key=payload.idempotency_key,
        max_turns=payload.max_turns,
    )
    run.turns.append(
        InterviewTurn(turn_no=1, question_json=json.dumps(result["question"], ensure_ascii=False))
    )
    db.add(run)
    db.flush()
    _audit(db, request, auth, "interview.created", "interview", run.id)
    db.commit()
    return _run_response(run)


@router.post("/interviews/{interview_id}/answers", tags=["interviews"])
def submit_answer(
    interview_id: str,
    payload: AnswerCreate,
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    run = _run(db, auth.tenant_id, interview_id, lock=True)
    if run.status not in {"awaiting_initial_answer", "awaiting_followup_answer"}:
        raise HTTPException(status_code=409, detail=f"interview status is {run.status}")
    turn = db.scalar(
        select(InterviewTurn)
        .where(InterviewTurn.run_id == run.id, InterviewTurn.answer_text.is_(None))
        .order_by(InterviewTurn.turn_no)
    )
    turn_no = turn.turn_no if turn else 0
    if not turn or turn.answer_text is not None:
        raise HTTPException(status_code=409, detail="current interview turn is not answerable")
    try:
        answer = safe_text(payload.answer, 20_000)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    answer = redact_pii(answer)
    question = json.loads(turn.question_json)
    evaluation = evaluate_answer(get_llm(), question, answer, run.rag_context)
    turn.answer_text = answer
    turn.evaluation_json = evaluation.model_dump_json()
    turn.answered_at = datetime.now(UTC)

    if turn_no < run.max_turns:
        history = [
            {
                "question": json.loads(item.question_json),
                "answer": item.answer_text,
                "evaluation": json.loads(item.evaluation_json) if item.evaluation_json else None,
            }
            for item in sorted(run.turns, key=lambda row: row.turn_no)
            if item.answer_text is not None
        ]
        followup = create_followup(get_llm(), question, answer, evaluation, history)
        run.turns.append(
            InterviewTurn(
                turn_no=turn_no + 1,
                question_json=json.dumps(
                    {
                        "question": followup.question,
                        "topic": "followup",
                        "difficulty": "medium",
                        "expected_points": followup.expected_points,
                        "evidence_ids": [],
                        "reason": followup.reason,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        run.status = "awaiting_followup_answer"
    else:
        completed_turns = list(
            db.scalars(
                select(InterviewTurn)
                .where(InterviewTurn.run_id == run.id)
                .order_by(InterviewTurn.turn_no)
            )
        )
        evaluations = [
            AnswerEvaluation.model_validate_json(item.evaluation_json)
            for item in completed_turns
            if item.evaluation_json
        ]
        report = create_final_report(
            get_llm(), evaluations[0], evaluations[1], evaluations[2:]
        )
        run.final_report_json = report.model_dump_json()
        run.overall_score = report.final_score
        run.status = "pending_human_review"
    _audit(
        db,
        request,
        auth,
        "interview.answer_submitted",
        "interview",
        run.id,
        {"turn_no": turn_no, "prompt_injection_flag": detect_prompt_injection(payload.answer)},
    )
    db.commit()
    return _run_response(run)


@router.post("/interviews/{interview_id}/review", tags=["interviews"])
def review_interview(
    interview_id: str,
    payload: ReviewCreate,
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    run = _run(db, auth.tenant_id, interview_id, lock=True)
    if run.status != "pending_human_review":
        raise HTTPException(status_code=409, detail="interview is not ready for human review")
    run.review_decision = payload.decision
    run.reviewer = payload.reviewer
    run.review_comment = payload.comment
    run.status = f"review_{payload.decision}"
    _audit(
        db,
        request,
        auth,
        "interview.human_reviewed",
        "interview",
        run.id,
        {"decision": payload.decision, "reviewer": payload.reviewer},
    )
    db.commit()
    return _run_response(run)


@router.get("/interviews/{interview_id}", tags=["interviews"])
def get_interview(
    interview_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    return _run_response(_run(db, auth.tenant_id, interview_id))


def _run_response(run: InterviewRun) -> dict:
    turns = sorted(run.turns, key=lambda item: item.turn_no)
    return {
        "id": run.id,
        "status": run.status,
        "resume_id": run.resume_id,
        "job_id": run.job_id,
        "max_turns": run.max_turns,
        "analysis": json.loads(run.analysis_json),
        "turns": [
            {
                "turn_no": turn.turn_no,
                "question": json.loads(turn.question_json),
                "answered": turn.answer_text is not None,
                "evaluation": json.loads(turn.evaluation_json) if turn.evaluation_json else None,
            }
            for turn in turns
        ],
        "final_report": json.loads(run.final_report_json) if run.final_report_json else None,
        "overall_score": run.overall_score,
        "review": {
            "decision": run.review_decision,
            "reviewer": run.reviewer,
            "comment": run.review_comment,
        }
        if run.review_decision
        else None,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }
