import httpx
import json
import secrets
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_db, require_auth
from app.api.routes import (
    _run,
    create_interview as api_create_interview,
    create_job as api_create_job,
    create_resume as api_create_resume,
    review_interview as api_review_interview,
    submit_answer as api_submit_answer,
)
from app.api.conversations import (
    create_conversation as api_create_conversation,
    delete_memory as api_delete_memory,
    send_message as api_send_message,
)
from app.config import get_settings
from app.db.models import Conversation, InterviewRun, JobRecord, ResumeRecord, UserMemory
from app.services.job_discovery import (
    DIRECTIONS,
    curated_jobs,
    recommend_directions,
    safe_job_url,
    search_haier_campus_jobs,
    search_jooble_jobs,
)
from app.services.qwen_job_search import search_qwen_jobs
from app.services.job_matching import compare_resume_job
from app.schemas.api import (
    AnswerCreate,
    ConversationCreate,
    InterviewCreate,
    JobCreate,
    MessageCreate,
    ResumeCreate,
    ReviewCreate,
)


router = APIRouter(prefix="/ui", include_in_schema=False)
templates = Jinja2Templates(directory="app/web/templates")
settings = get_settings()
serializer = URLSafeTimedSerializer(
    settings.app_api_key.get_secret_value(), salt="career-agent-ui-v1"
)

STATUS_LABELS = {
    "awaiting_initial_answer": "等待首次回答",
    "awaiting_followup_answer": "等待追问回答",
    "pending_human_review": "等待人工审核",
    "review_approved": "审核已通过",
    "review_rejected": "审核未通过",
}


def _session_tenant(request: Request) -> str | None:
    if request.session.get("authenticated") is not True:
        return None
    return request.session.get("tenant_id")


def _csrf(request: Request, submitted: str) -> None:
    expected = request.session.get("csrf", "")
    if not expected or not secrets.compare_digest(expected, submitted):
        raise HTTPException(status_code=403, detail="页面已过期，请刷新后重试")


def _dashboard_redirect(*, message: str = "", error: str = "") -> RedirectResponse:
    values = {"message": message, "error": error}
    query = urlencode({key: value for key, value in values.items() if value})
    return RedirectResponse(f"/ui/dashboard{f'?{query}' if query else ''}", status_code=303)


def _token(run_id: str, tenant_id: str, purpose: str) -> str:
    return serializer.dumps({"run_id": run_id, "tenant_id": tenant_id, "purpose": purpose})


def _token_data(token: str, purpose: str, max_age: int = 86_400) -> tuple[str, str]:
    try:
        data = serializer.loads(token, max_age=max_age)
    except SignatureExpired as exc:
        raise HTTPException(status_code=410, detail="邀请链接已过期") from exc
    except BadSignature as exc:
        raise HTTPException(status_code=404, detail="邀请链接无效") from exc
    if data.get("purpose") != purpose:
        raise HTTPException(status_code=404, detail="邀请链接无效")
    return data["run_id"], data["tenant_id"]


@router.get("", response_class=HTMLResponse)
def ui_home(request: Request):
    destination = "/ui/dashboard" if _session_tenant(request) else "/ui/login"
    return RedirectResponse(destination, status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if _session_tenant(request):
        return RedirectResponse("/ui/dashboard", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"error": request.query_params.get("error")}
    )


@router.post("/login")
def login(request: Request, api_key: str = Form(...), tenant_id: str = Form(...)):
    try:
        auth = require_auth(
            x_api_key=api_key, x_tenant_id=tenant_id, x_user_id="workspace-user"
        )
    except HTTPException:
        return RedirectResponse("/ui/login?error=API+Key或企业标识不正确", status_code=303)
    request.session.clear()
    request.session.update(
        {"authenticated": True, "tenant_id": auth.tenant_id, "csrf": secrets.token_urlsafe(32)}
    )
    return RedirectResponse("/ui/dashboard", status_code=303)


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    _csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/ui/login", status_code=303)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    tenant_id = _session_tenant(request)
    if not tenant_id:
        return RedirectResponse("/ui/login", status_code=303)
    resumes = list(
        db.scalars(
            select(ResumeRecord)
            .where(ResumeRecord.tenant_id == tenant_id)
            .order_by(ResumeRecord.created_at.desc())
            .limit(50)
        )
    )
    jobs = list(
        db.scalars(
            select(JobRecord)
            .where(JobRecord.tenant_id == tenant_id)
            .order_by(JobRecord.created_at.desc())
            .limit(50)
        )
    )
    runs = list(
        db.scalars(
            select(InterviewRun)
            .where(InterviewRun.tenant_id == tenant_id)
            .order_by(InterviewRun.created_at.desc())
            .limit(50)
        )
    )
    resume_map = {item.id: item for item in resumes}
    job_map = {item.id: item for item in jobs}
    run_cards = [
        {
            "status": STATUS_LABELS.get(item.status, item.status),
            "status_code": item.status,
            "score": round(item.overall_score) if item.overall_score is not None else None,
            "resume": resume_map.get(item.resume_id),
            "job": job_map.get(item.job_id),
            "candidate_token": _token(item.id, tenant_id, "candidate"),
            "review_token": _token(item.id, tenant_id, "review"),
            "created_at": item.created_at,
        }
        for item in runs
    ]
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "tenant_id": tenant_id,
            "csrf_token": request.session["csrf"],
            "resumes": resumes,
            "jobs": jobs,
            "runs": run_cards,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.get("/coach", response_class=HTMLResponse)
def coach_home(request: Request, resume_id: str = "", db: Session = Depends(get_db)):
    tenant_id = _session_tenant(request)
    if not tenant_id:
        return RedirectResponse("/ui/login", status_code=303)
    conversations = list(
        db.scalars(
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.owner_id == "workspace-user",
            )
            .order_by(Conversation.updated_at.desc())
        )
    )
    resumes = list(
        db.scalars(
            select(ResumeRecord)
            .where(ResumeRecord.tenant_id == tenant_id)
            .order_by(ResumeRecord.created_at.desc())
        )
    )
    selected_resume = next((item for item in resumes if item.id == resume_id), None)
    if selected_resume is None and resumes:
        selected_resume = resumes[0]
    directions = recommend_directions(selected_resume.redacted_text) if selected_resume else []
    jobs = list(db.scalars(select(JobRecord).where(JobRecord.tenant_id == tenant_id)))
    memories = list(
        db.scalars(
            select(UserMemory)
            .where(
                UserMemory.tenant_id == tenant_id,
                UserMemory.owner_id == "workspace-user",
                UserMemory.is_active.is_(True),
            )
            .order_by(UserMemory.updated_at.desc())
        )
    )
    return templates.TemplateResponse(
        request,
        "coach.html",
        {
            "conversations": conversations,
            "resumes": resumes,
            "selected_resume": selected_resume,
            "directions": directions,
            "jobs": jobs,
            "memories": memories,
            "csrf_token": request.session["csrf"],
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.get("/coach/jobs", response_class=HTMLResponse)
def coach_jobs(
    request: Request,
    resume_id: str,
    direction_id: str,
    location: str = "",
    use_qwen: bool = False,
    db: Session = Depends(get_db),
):
    tenant_id = _session_tenant(request)
    if not tenant_id:
        return RedirectResponse("/ui/login", status_code=303)
    resume = db.scalar(
        select(ResumeRecord).where(
            ResumeRecord.id == resume_id, ResumeRecord.tenant_id == tenant_id
        )
    )
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    direction = next(
        (item for item in recommend_directions(resume.redacted_text) if item["id"] == direction_id),
        None,
    )
    if not direction:
        raise HTTPException(status_code=404, detail="该简历没有这个推荐方向")

    location = location.strip()[:100]
    jobs: list[dict] = []
    notices: list[str] = []
    job_settings = get_settings()
    try:
        jobs.extend(search_haier_campus_jobs(direction_id=direction_id, location=location))
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        notices.append("海尔官方校招实时来源暂不可用；仍会展示已有的岗位快照。")

    if use_qwen:
        if not location:
            notices.append("千问联网扩展搜索需要填写目标城市。")
        elif not job_settings.dashscope_api_key:
            notices.append("未配置 DASHSCOPE_API_KEY，无法使用千问联网扩展搜索。")
        else:
            try:
                qwen_jobs = search_qwen_jobs(
                    api_key=job_settings.dashscope_api_key.get_secret_value(),
                    model="qwen-plus",
                    direction_id=direction_id,
                    query=direction["query"],
                    location=location,
                )
                jobs.extend(qwen_jobs)
            except (httpx.HTTPError, RuntimeError, ValueError, KeyError, TypeError):
                notices.append("千问联网扩展搜索暂不可用；仍会展示其他来源的岗位。")
            else:
                notices.append(
                    "千问联网搜索新增 " + str(len(qwen_jobs)) +
                    " 条经来源页核对的岗位；未通过职位页与城市核对的结果不会显示。"
                )

    if not location:
        notices.append("未指定城市：展示所有地区的相关岗位。Jooble 接口需要指定城市，本次未调用。")
    elif job_settings.jooble_api_key and job_settings.jooble_api_host:
        try:
            jobs.extend(search_jooble_jobs(
                api_key=job_settings.jooble_api_key.get_secret_value(),
                host=job_settings.jooble_api_host,
                query=direction["query"],
                location=location,
            ))
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            notices.append("实时职位源暂时不可用；下面如有岗位快照，请打开原始页面核实。")
    if not (job_settings.jooble_api_key and job_settings.jooble_api_host):
        notices.append("未配置跨企业的 Jooble 职位源；下方实时结果仅覆盖海尔官方校招，岗位快照及已保存岗位不代表现在仍有名额。")

    seen = {item["url"] for item in jobs}
    for item in curated_jobs(direction_id, location):
        if item["url"] not in seen:
            jobs.append(item)
            seen.add(item["url"])
    direction_terms = next(item.terms for item in DIRECTIONS if item.id == direction_id)
    saved_jobs = db.scalars(select(JobRecord).where(JobRecord.tenant_id == tenant_id))
    for item in saved_jobs:
        link = safe_job_url(item.source_url)
        searchable = f"{item.title} {item.jd_text}".lower()
        if not link or link in seen or not any(term.lower() in searchable for term in direction_terms):
            continue
        if location and item.city and location.lower() not in item.city.lower():
            continue
        jobs.append(
            {
                "title": item.title,
                "company": item.company,
                "location": item.city or "地点未注明",
                "snippet": item.jd_text[:500],
                "salary": "",
                "updated": "",
                "source": "已保存岗位（请核实是否仍在招）",
                "url": link,
            }
        )
        seen.add(link)
        if len(jobs) >= 10:
            break
    for item in jobs:
        item["save_token"] = (
            serializer.dumps({
                "purpose": "coach_job_import",
                "tenant_id": tenant_id,
                "resume_id": resume.id,
                "job": {
                    "title": item["title"][:200],
                    "company": item["company"][:200],
                    "city": item["location"][:100],
                    "jd_text": item["snippet"][:20_000],
                    "source_url": item["url"],
                },
            })
            if len(item["snippet"].strip()) >= 20 else None
        )
    return templates.TemplateResponse(
        request,
        "coach_jobs.html",
        {
            "resume": resume,
            "direction": direction,
            "location": location,
            "jobs": jobs,
            "notices": notices,
            "csrf_token": request.session["csrf"],
        },
    )


@router.post("/coach/jobs/save")
def coach_save_job(
    request: Request,
    job_token: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    tenant_id = _session_tenant(request)
    if not tenant_id:
        return RedirectResponse("/ui/login", status_code=303)
    _csrf(request, csrf_token)
    try:
        data = serializer.loads(job_token, max_age=1800)
    except SignatureExpired as exc:
        raise HTTPException(status_code=410, detail="岗位卡片已过期，请刷新结果页") from exc
    except BadSignature as exc:
        raise HTTPException(status_code=400, detail="岗位卡片无效") from exc
    if data.get("purpose") != "coach_job_import" or data.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=403, detail="岗位卡片不属于当前账号")
    resume_id = data.get("resume_id")
    resume = db.scalar(select(ResumeRecord).where(
        ResumeRecord.id == resume_id, ResumeRecord.tenant_id == tenant_id
    ))
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    snapshot = data.get("job") or {}
    link = safe_job_url(snapshot.get("source_url"))
    if not link:
        raise HTTPException(status_code=422, detail="岗位来源链接无效")
    existing = db.scalar(select(JobRecord).where(
        JobRecord.tenant_id == tenant_id, JobRecord.source_url == link
    ))
    if existing:
        job_id = existing.id
    else:
        try:
            payload = JobCreate(
                title=snapshot["title"], company=snapshot["company"],
                city=snapshot["city"], jd_text=snapshot["jd_text"],
                source_url=link, source_type="verified",
            )
            created = api_create_job(payload, request, AuthContext(tenant_id), db)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="岗位信息不完整，请刷新结果页") from exc
        job_id = created["id"]
    query = urlencode({"resume_id": resume_id, "job_id": job_id})
    return RedirectResponse(f"/ui/coach/match?{query}", status_code=303)


@router.get("/coach/match", response_class=HTMLResponse)
def coach_job_match(
    request: Request,
    resume_id: str,
    job_id: str,
    db: Session = Depends(get_db),
):
    tenant_id = _session_tenant(request)
    if not tenant_id:
        return RedirectResponse("/ui/login", status_code=303)
    resume = db.scalar(select(ResumeRecord).where(
        ResumeRecord.id == resume_id, ResumeRecord.tenant_id == tenant_id
    ))
    job = db.scalar(select(JobRecord).where(
        JobRecord.id == job_id, JobRecord.tenant_id == tenant_id
    ))
    if not resume or not job:
        raise HTTPException(status_code=404, detail="简历或岗位不存在")
    return templates.TemplateResponse(request, "coach_match.html", {
        "resume": resume,
        "job": job,
        "analysis": compare_resume_job(resume.redacted_text, job.jd_text),
        "csrf_token": request.session["csrf"],
    })


def _resume_upload_text(upload: UploadFile) -> str:
    raw = upload.file.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError("简历文件不能超过 5MB")
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix == ".pdf":
        from PyPDF2 import PdfReader

        reader = PdfReader(BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if suffix not in {".txt", ".md"}:
        raise ValueError("只支持 PDF、TXT 或 Markdown 简历")
    try:
        return raw.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        return raw.decode("gb18030").strip()


@router.post("/coach/resume")
def coach_resume_upload(
    request: Request,
    source_name: str = Form(""),
    resume_text: str = Form(""),
    resume_file: UploadFile | None = File(None),
    consent: bool = Form(False),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    tenant_id = _session_tenant(request)
    if not tenant_id:
        return RedirectResponse("/ui/login", status_code=303)
    _csrf(request, csrf_token)
    try:
        text = resume_text.strip()
        name = source_name.strip() or "my-resume.txt"
        if resume_file and resume_file.filename:
            text = _resume_upload_text(resume_file)
            name = source_name.strip() or Path(resume_file.filename).name
        api_create_resume(
            ResumeCreate(source_name=name, resume_text=text, consent=consent),
            request,
            AuthContext(tenant_id),
            db,
        )
    except (HTTPException, ValueError) as exc:
        query = urlencode({"error": str(getattr(exc, "detail", exc))})
        return RedirectResponse(f"/ui/coach?{query}", status_code=303)
    query = urlencode({"message": "简历已解析保存，新对话会自动使用这份简历"})
    return RedirectResponse(f"/ui/coach?{query}", status_code=303)


@router.post("/coach")
def coach_create(
    request: Request,
    title: str = Form("求职教练对话"),
    resume_id: str = Form(""),
    job_id: str = Form(""),
    memory_enabled: bool = Form(False),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    tenant_id = _session_tenant(request)
    if not tenant_id:
        return RedirectResponse("/ui/login", status_code=303)
    _csrf(request, csrf_token)
    try:
        created = api_create_conversation(
            ConversationCreate(
                title=title,
                resume_id=resume_id or None,
                job_id=job_id or None,
                memory_enabled=memory_enabled,
            ),
            request,
            AuthContext(tenant_id),
            db,
        )
    except (HTTPException, ValueError) as exc:
        query = urlencode({"error": str(getattr(exc, "detail", exc))})
        return RedirectResponse(f"/ui/coach?{query}", status_code=303)
    return RedirectResponse(f"/ui/coach/{created['id']}", status_code=303)


@router.get("/coach/{conversation_id}", response_class=HTMLResponse)
def coach_chat(conversation_id: str, request: Request, db: Session = Depends(get_db)):
    tenant_id = _session_tenant(request)
    if not tenant_id:
        return RedirectResponse("/ui/login", status_code=303)
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
            Conversation.owner_id == "workspace-user",
        )
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")
    linked_resume = None
    if conversation.resume_id:
        linked_resume = db.scalar(
            select(ResumeRecord).where(
                ResumeRecord.id == conversation.resume_id,
                ResumeRecord.tenant_id == tenant_id,
            )
        )
    linked_job = None
    if conversation.job_id:
        linked_job = db.scalar(
            select(JobRecord).where(
                JobRecord.id == conversation.job_id,
                JobRecord.tenant_id == tenant_id,
            )
        )
    memories = list(
        db.scalars(
            select(UserMemory)
            .where(
                UserMemory.tenant_id == tenant_id,
                UserMemory.owner_id == "workspace-user",
                UserMemory.is_active.is_(True),
            )
            .order_by(UserMemory.updated_at.desc())
        )
    )
    return templates.TemplateResponse(
        request,
        "coach_chat.html",
        {
            "conversation": conversation,
            "messages": sorted(conversation.messages, key=lambda item: item.sequence_no),
            "memories": memories,
            "linked_resume": linked_resume,
            "linked_job": linked_job,
            "csrf_token": request.session["csrf"],
            "error": request.query_params.get("error"),
        },
    )


@router.post("/coach/{conversation_id}/message")
def coach_message(
    conversation_id: str,
    request: Request,
    content: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    tenant_id = _session_tenant(request)
    if not tenant_id:
        return RedirectResponse("/ui/login", status_code=303)
    _csrf(request, csrf_token)
    try:
        api_send_message(
            conversation_id,
            MessageCreate(content=content),
            request,
            AuthContext(tenant_id),
            db,
        )
    except (HTTPException, ValueError) as exc:
        query = urlencode({"error": str(getattr(exc, "detail", exc))})
        return RedirectResponse(f"/ui/coach/{conversation_id}?{query}", status_code=303)
    return RedirectResponse(f"/ui/coach/{conversation_id}", status_code=303)


@router.post("/coach/{conversation_id}/memories/{memory_id}/delete")
def coach_memory_delete(
    conversation_id: str,
    memory_id: str,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    tenant_id = _session_tenant(request)
    if not tenant_id:
        return RedirectResponse("/ui/login", status_code=303)
    _csrf(request, csrf_token)
    api_delete_memory(memory_id, request, AuthContext(tenant_id), db)
    return RedirectResponse(f"/ui/coach/{conversation_id}", status_code=303)


@router.post("/resumes")
def create_resume_ui(
    request: Request,
    source_name: str = Form(...),
    resume_text: str = Form(...),
    consent: bool = Form(False),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    tenant_id = _session_tenant(request)
    if not tenant_id:
        return RedirectResponse("/ui/login", status_code=303)
    _csrf(request, csrf_token)
    try:
        api_create_resume(
            ResumeCreate(source_name=source_name, resume_text=resume_text, consent=consent),
            request,
            AuthContext(tenant_id),
            db,
        )
    except (HTTPException, ValueError) as exc:
        return _dashboard_redirect(error=str(getattr(exc, "detail", exc)))
    return _dashboard_redirect(message="简历解析并保存成功")


@router.post("/jobs")
def create_job_ui(
    request: Request,
    title: str = Form(...),
    company: str = Form(...),
    city: str = Form(""),
    jd_text: str = Form(...),
    source_url: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    tenant_id = _session_tenant(request)
    if not tenant_id:
        return RedirectResponse("/ui/login", status_code=303)
    _csrf(request, csrf_token)
    try:
        api_create_job(
            JobCreate(
                title=title, company=company, city=city, jd_text=jd_text,
                source_url=source_url.strip() or None,
            ),
            request,
            AuthContext(tenant_id),
            db,
        )
    except (HTTPException, ValueError) as exc:
        return _dashboard_redirect(error=str(getattr(exc, "detail", exc)))
    return _dashboard_redirect(message="岗位保存成功")


@router.post("/interviews")
def create_interview_ui(
    request: Request,
    resume_id: str = Form(...),
    job_id: str = Form(...),
    max_turns: int = Form(2),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    tenant_id = _session_tenant(request)
    if not tenant_id:
        return RedirectResponse("/ui/login", status_code=303)
    _csrf(request, csrf_token)
    try:
        api_create_interview(
            InterviewCreate(
                resume_id=resume_id,
                job_id=job_id,
                idempotency_key=f"ui-{uuid4()}",
                max_turns=max_turns,
            ),
            request,
            AuthContext(tenant_id),
            db,
        )
    except (HTTPException, ValueError) as exc:
        return _dashboard_redirect(error=str(getattr(exc, "detail", exc)))
    return _dashboard_redirect(message="面试创建成功，可以复制候选人链接")


@router.get("/interview/{token}", response_class=HTMLResponse)
def candidate_page(token: str, request: Request, db: Session = Depends(get_db)):
    run_id, tenant_id = _token_data(token, "candidate")
    run = _run(db, tenant_id, run_id)
    current_turn = next((item for item in run.turns if item.answer_text is None), None)
    question = json.loads(current_turn.question_json) if current_turn else None
    return templates.TemplateResponse(
        request,
        "candidate.html",
        {
            "token": token,
            "status": run.status,
            "status_label": STATUS_LABELS.get(run.status, run.status),
            "question": question,
            "completed": current_turn is None,
        },
    )


@router.post("/interview/{token}/answer")
def candidate_answer(
    token: str,
    request: Request,
    answer: str = Form(...),
    db: Session = Depends(get_db),
):
    run_id, tenant_id = _token_data(token, "candidate")
    try:
        api_submit_answer(
            run_id,
            AnswerCreate(answer=answer),
            request,
            AuthContext(tenant_id),
            db,
        )
    except (HTTPException, ValueError) as exc:
        run = _run(db, tenant_id, run_id)
        current_turn = next((item for item in run.turns if item.answer_text is None), None)
        return templates.TemplateResponse(
            request,
            "candidate.html",
            {
                "token": token,
                "status": run.status,
                "status_label": STATUS_LABELS.get(run.status, run.status),
                "question": json.loads(current_turn.question_json) if current_turn else None,
                "completed": current_turn is None,
                "error": str(getattr(exc, "detail", exc)),
            },
            status_code=422,
        )
    return RedirectResponse(f"/ui/interview/{token}", status_code=303)


@router.get("/review/{token}", response_class=HTMLResponse)
def review_page(token: str, request: Request, db: Session = Depends(get_db)):
    session_tenant = _session_tenant(request)
    if not session_tenant:
        return RedirectResponse("/ui/login", status_code=303)
    run_id, token_tenant = _token_data(token, "review", max_age=7 * 86_400)
    if session_tenant != token_tenant:
        raise HTTPException(status_code=404, detail="报告不存在")
    run = _run(db, token_tenant, run_id)
    turns = [
        {
            "number": item.turn_no,
            "question": json.loads(item.question_json),
            "answer": item.answer_text,
            "evaluation": json.loads(item.evaluation_json) if item.evaluation_json else None,
        }
        for item in run.turns
    ]
    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "token": token,
            "status": run.status,
            "status_label": STATUS_LABELS.get(run.status, run.status),
            "analysis": json.loads(run.analysis_json),
            "turns": turns,
            "report": json.loads(run.final_report_json) if run.final_report_json else None,
            "review": {
                "decision": run.review_decision,
                "reviewer": run.reviewer,
                "comment": run.review_comment,
            }
            if run.review_decision
            else None,
            "csrf_token": request.session["csrf"],
            "error": request.query_params.get("error"),
        },
    )


@router.post("/review/{token}")
def review_submit(
    token: str,
    request: Request,
    decision: str = Form(...),
    reviewer: str = Form(...),
    comment: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_tenant = _session_tenant(request)
    if not session_tenant:
        return RedirectResponse("/ui/login", status_code=303)
    _csrf(request, csrf_token)
    run_id, token_tenant = _token_data(token, "review", max_age=7 * 86_400)
    if session_tenant != token_tenant:
        raise HTTPException(status_code=404, detail="报告不存在")
    try:
        api_review_interview(
            run_id,
            ReviewCreate(decision=decision, reviewer=reviewer, comment=comment),
            request,
            AuthContext(token_tenant),
            db,
        )
    except (HTTPException, ValueError) as exc:
        query = urlencode({"error": str(getattr(exc, "detail", exc))})
        return RedirectResponse(f"/ui/review/{token}?{query}", status_code=303)
    return RedirectResponse(f"/ui/review/{token}", status_code=303)

