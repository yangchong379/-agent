import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.base import Base, SessionLocal, engine
from app.db.models import InterviewRun, JobRecord, ResumeRecord
from app.main import app
from app.web.routes import _token


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match
    return match.group(1)


def test_complete_server_rendered_ui_flow():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        root = client.get("/", follow_redirects=False)
        assert root.status_code == 303
        login = client.post(
            "/ui/login",
            data={"api_key": "test-api-key-value", "tenant_id": "tenant-demo"},
            follow_redirects=True,
        )
        assert login.status_code == 200
        assert "招聘面试工作台" in login.text
        csrf = _csrf(login.text)

        resume = client.post(
            "/ui/resumes",
            data={
                "source_name": "candidate-ui.txt",
                "resume_text": "三年 Java 后端经验，负责 Spring Boot、MySQL、Redis 性能优化项目。",
                "consent": "true",
                "csrf_token": csrf,
            },
            follow_redirects=True,
        )
        assert "简历解析并保存成功" in resume.text
        job = client.post(
            "/ui/jobs",
            data={
                "title": "Java 后端工程师",
                "company": "示例企业",
                "city": "深圳",
                "jd_text": "负责核心后端系统，要求 Java、MySQL、缓存、高并发和线上故障排查经验。",
                "csrf_token": csrf,
            },
            follow_redirects=True,
        )
        assert "岗位保存成功" in job.text

        with SessionLocal() as db:
            resume_id = db.scalar(select(ResumeRecord.id))
            job_id = db.scalar(select(JobRecord.id))
        created = client.post(
            "/ui/interviews",
            data={"resume_id": resume_id, "job_id": job_id, "csrf_token": csrf},
            follow_redirects=True,
        )
        assert "面试创建成功" in created.text
        with SessionLocal() as db:
            run = db.scalar(select(InterviewRun))
            run_id = run.id
        candidate_token = _token(run_id, "tenant-demo", "candidate")
        review_token = _token(run_id, "tenant-demo", "review")

        question = client.get(f"/ui/interview/{candidate_token}")
        assert question.status_code == 200
        assert "第一轮问题" in question.text
        first = client.post(
            f"/ui/interview/{candidate_token}/answer",
            data={"answer": "我先建立指标基线，再通过日志、监控和火焰图定位，最后压测验证。"},
            follow_redirects=True,
        )
        assert "补充问题" in first.text
        second = client.post(
            f"/ui/interview/{candidate_token}/answer",
            data={"answer": "保持环境和数据量一致，比较 P99、错误率和资源使用率并执行回归测试。"},
            follow_redirects=True,
        )
        assert "回答已提交" in second.text

        report = client.get(f"/ui/review/{review_token}")
        assert "面试证据报告" in report.text
        assert "最终报告" in report.text
        reviewed = client.post(
            f"/ui/review/{review_token}",
            data={
                "decision": "approved",
                "reviewer": "reviewer-ui",
                "comment": "已核验原始回答和评分依据。",
                "csrf_token": csrf,
            },
            follow_redirects=True,
        )
        assert "审核已通过" in reviewed.text


def test_invalid_login_is_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/ui/login",
            data={"api_key": "wrong", "tenant_id": "tenant-demo"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "API Key或企业标识不正确" in response.text


def test_resume_can_be_uploaded_from_coach_page():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        page = client.post(
            "/ui/login",
            data={"api_key": "test-api-key-value", "tenant_id": "tenant-demo"},
            follow_redirects=True,
        )
        csrf = _csrf(page.text)
        saved = client.post(
            "/ui/coach/resume",
            data={"source_name": "我的后端简历", "consent": "true", "csrf_token": csrf},
            files={
                "resume_file": (
                    "resume.txt",
                    "三年 Python 后端经验，使用 FastAPI、MySQL 开发求职智能体。".encode(),
                    "text/plain",
                )
            },
            follow_redirects=True,
        )

        assert saved.status_code == 200
        assert "简历已解析保存" in saved.text
        with SessionLocal() as db:
            resume = db.scalar(select(ResumeRecord))
            assert resume is not None
            assert resume.source_name == "我的后端简历"

