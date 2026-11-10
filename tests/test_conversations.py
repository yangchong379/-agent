from fastapi.testclient import TestClient

from app.db.base import Base, engine
from app.main import app


HEADERS = {"X-API-Key": "test-api-key-value", "X-Tenant-ID": "tenant-coach"}


def test_context_conversation_and_managed_memory():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        created = client.post(
            "/conversations",
            headers=HEADERS,
            json={"title": "Java 求职", "memory_enabled": True},
        )
        assert created.status_code == 201, created.text
        conversation_id = created.json()["id"]

        first = client.post(
            f"/conversations/{conversation_id}/messages",
            headers=HEADERS,
            json={"content": "我的目标是 Java 后端工程师，我有 3 年 Spring Boot 经验。"},
        )
        assert first.status_code == 200, first.text
        assert first.json()["message"]["role"] == "assistant"
        assert first.json()["memories_saved"]

        second = client.post(
            f"/conversations/{conversation_id}/messages",
            headers=HEADERS,
            json={"content": "请结合之前的信息告诉我下一步怎么准备。"},
        )
        assert second.status_code == 200, second.text
        assert "此前确认的背景" in second.json()["message"]["content"]

        detail = client.get(f"/conversations/{conversation_id}", headers=HEADERS)
        assert [item["role"] for item in detail.json()["messages"]] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]

        memories = client.get("/memories", headers=HEADERS).json()
        memory_id = memories[0]["id"]
        updated = client.patch(
            f"/memories/{memory_id}",
            headers=HEADERS,
            json={"content": "目标岗位是高级 Java 后端工程师"},
        )
        assert updated.status_code == 200
        deleted = client.delete(f"/memories/{memory_id}", headers=HEADERS)
        assert deleted.status_code == 204


def test_conversation_tenant_isolation():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        created = client.post("/conversations", headers=HEADERS, json={})
        other = {"X-API-Key": "test-api-key-value", "X-Tenant-ID": "other-tenant"}
        response = client.get(f"/conversations/{created.json()['id']}", headers=other)
        assert response.status_code == 404
        other_user = {**HEADERS, "X-User-ID": "another-user"}
        response = client.get(f"/conversations/{created.json()['id']}", headers=other_user)
        assert response.status_code == 404


def test_adaptive_three_turn_interview():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        resume = client.post(
            "/resumes",
            headers=HEADERS,
            json={
                "source_name": "candidate.txt",
                "resume_text": "三年 Java 后端经验，负责 Spring Boot、MySQL 和 Redis 性能优化。",
                "consent": True,
            },
        ).json()
        job = client.post(
            "/jobs",
            headers=HEADERS,
            json={
                "title": "Java 后端工程师",
                "company": "示例企业",
                "jd_text": "负责核心交易系统，要求 Java、数据库、高并发和故障排查经验。",
            },
        ).json()
        run = client.post(
            "/interviews",
            headers=HEADERS,
            json={"resume_id": resume["id"], "job_id": job["id"], "max_turns": 3},
        ).json()
        for expected_status in (
            "awaiting_followup_answer",
            "awaiting_followup_answer",
            "pending_human_review",
        ):
            response = client.post(
                f"/interviews/{run['id']}/answers",
                headers=HEADERS,
                json={"answer": "我先建立基线，再用日志、指标和压测验证结果与方案取舍。"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == expected_status
        assert len(response.json()["turns"]) == 3
        assert response.json()["final_report"] is not None
