"""Dependency-light end-to-end check using the mock model and a temporary database."""

import os
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        database_path = (Path(temp_dir) / "smoke.db").as_posix()
        os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
        os.environ["APP_API_KEY"] = "smoke-test-api-key"
        os.environ["LLM_PROVIDER"] = "mock"
        os.environ["AUTO_CREATE_SCHEMA"] = "true"

        from fastapi.testclient import TestClient

        from app.db.base import engine
        from app.main import app

        headers = {"X-API-Key": "smoke-test-api-key", "X-Tenant-ID": "smoke-tenant"}
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            resume = client.post(
                "/resumes",
                headers=headers,
                json={
                    "source_name": "smoke.txt",
                    "resume_text": "三年 Java 后端经验，负责 Spring Boot、MySQL、Redis 性能优化项目。",
                    "consent": True,
                },
            )
            assert resume.status_code == 201, resume.text
            job = client.post(
                "/jobs",
                headers=headers,
                json={
                    "title": "Java 后端工程师",
                    "company": "示例企业",
                    "jd_text": "负责核心系统，要求 Java、MySQL、高并发、监控与故障排查经验。",
                },
            )
            assert job.status_code == 201, job.text
            run = client.post(
                "/interviews",
                headers=headers,
                json={"resume_id": resume.json()["id"], "job_id": job.json()["id"]},
            )
            assert run.status_code == 201, run.text
            run_id = run.json()["id"]
            for answer in (
                "我先建立 P99 延迟和吞吐基线，再通过日志、指标与火焰图定位，最后压测验证。",
                "保持环境和数据量一致，比较 P99、错误率和资源使用率，并进行回归验证。",
            ):
                run = client.post(
                    f"/interviews/{run_id}/answers", headers=headers, json={"answer": answer}
                )
                assert run.status_code == 200, run.text
            assert run.json()["status"] == "pending_human_review"
            reviewed = client.post(
                f"/interviews/{run_id}/review",
                headers=headers,
                json={"decision": "approved", "reviewer": "smoke-reviewer"},
            )
            assert reviewed.json()["status"] == "review_approved"
        engine.dispose()
    print("SMOKE TEST PASSED: complete API lifecycle and human review")


if __name__ == "__main__":
    main()
