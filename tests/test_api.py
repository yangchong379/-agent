from fastapi.testclient import TestClient

from app.db.base import Base, engine
from app.main import app


HEADERS = {"X-API-Key": "test-api-key-value", "X-Tenant-ID": "tenant-demo"}


def test_complete_interview_lifecycle():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        resume = client.post(
            "/resumes",
            headers=HEADERS,
            json={
                "source_name": "demo.txt",
                "resume_text": "三年 Java 后端经验，负责 Spring Boot、MySQL、Redis 性能优化项目。",
                "consent": True,
            },
        )
        assert resume.status_code == 201, resume.text
        job = client.post(
            "/jobs",
            headers=HEADERS,
            json={
                "title": "Java 后端工程师",
                "company": "示例企业",
                "city": "深圳",
                "jd_text": "负责核心交易系统，要求 Java、MySQL、缓存和高并发故障排查经验。",
            },
        )
        assert job.status_code == 201, job.text
        run = client.post(
            "/interviews",
            headers=HEADERS,
            json={"resume_id": resume.json()["id"], "job_id": job.json()["id"]},
        )
        assert run.status_code == 201, run.text
        run_id = run.json()["id"]
        first = client.post(
            f"/interviews/{run_id}/answers",
            headers=HEADERS,
            json={"answer": "我先定义 P99 延迟和吞吐基线，通过日志、指标与火焰图定位，再用压测验证优化效果。"},
        )
        assert first.json()["status"] == "awaiting_followup_answer"
        second = client.post(
            f"/interviews/{run_id}/answers",
            headers=HEADERS,
            json={"answer": "使用相同数据量和流量做对照测试，比较 P99、错误率和资源使用率，并做回归验证。"},
        )
        assert second.json()["status"] == "pending_human_review"
        reviewed = client.post(
            f"/interviews/{run_id}/review",
            headers=HEADERS,
            json={"decision": "approved", "reviewer": "reviewer-001", "comment": "已复核证据"},
        )
        assert reviewed.json()["status"] == "review_approved"


def test_tenant_isolation():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        created = client.post(
            "/jobs",
            headers=HEADERS,
            json={
                "title": "后端工程师",
                "company": "示例企业",
                "jd_text": "负责企业后端系统的设计、开发、测试、监控和持续优化。",
            },
        )
        assert created.status_code == 201
        wrong_tenant = {"X-API-Key": "test-api-key-value", "X-Tenant-ID": "other-tenant"}
        response = client.post(
            "/interviews",
            headers=wrong_tenant,
            json={"resume_id": "missing", "job_id": created.json()["id"]},
        )
        assert response.status_code == 404

