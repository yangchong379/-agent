import re
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from app.db.base import Base, SessionLocal, engine
from app.db.models import JobRecord, ResumeRecord
from app.main import app
from app.web import routes as web_routes
from app.services.job_discovery import (
    curated_jobs,
    recommend_directions,
    safe_job_url,
    search_haier_campus_jobs,
    search_jooble_jobs,
)
from app.services.qwen_job_search import _job_from_page, _trusted_job_url
from app.services.qwen_job_search import search_qwen_jobs
from app.services.job_matching import compare_resume_job


def test_directions_are_grounded_in_resume_and_links_are_validated():
    directions = recommend_directions("用 LangGraph 开发 Agent，基于 Qwen2.5-VL 处理多模态图像和点云。")
    assert {item["id"] for item in directions} >= {"agents", "multimodal", "three_d"}
    assert not recommend_directions("只写了个人联系方式，没有技能或项目。")
    assert safe_job_url("javascript:alert(1)") is None
    assert safe_job_url("https://example.org/jobs/1") == "https://example.org/jobs/1"
    jobs = curated_jobs("three_d", "深圳")
    assert jobs and all("www.bing.com/search" not in item["url"] for item in jobs)
    assert all(item["updated"] == "核查于 2026-10-05" for item in jobs)
    assert curated_jobs("three_d", "香港") == []
    assert any(item["company"] == "Longbridge" for item in curated_jobs("agents", ""))
    assert {item["company"] for item in curated_jobs("agents", "青岛")} == {
        "海尔集团 · 卡奥斯平台", "青岛乾程科技股份有限公司"
    }


def test_jooble_results_require_a_real_link(monkeypatch):
    response = Mock()
    response.json.return_value = {
        "jobs": [
            {"title": "AI 工程师", "company": "示例企业", "link": "https://hk.jooble.org/jdp/1"},
            {"title": "无效链接", "link": "javascript:alert(1)"},
        ]
    }
    response.raise_for_status.return_value = None

    def fake_post(url, *, json, timeout):
        assert url == "https://hk.jooble.org/api/test-key"
        assert json["location"] == "香港"
        assert timeout == 15.0
        return response

    monkeypatch.setattr(httpx, "post", fake_post)
    jobs = search_jooble_jobs(
        api_key="test-key", host="hk.jooble.org", query="AI 工程师", location="香港"
    )
    assert len(jobs) == 1
    assert jobs[0]["url"] == "https://hk.jooble.org/jdp/1"
    with pytest.raises(ValueError):
        search_jooble_jobs(api_key="test-key", host="example.org", query="AI", location="香港")


def test_haier_live_source_uses_official_detail_pages_and_filters_city(monkeypatch):
    feed = Mock()
    feed.json.return_value = {
        "status": 1,
        "data": {
            "activity": {"status": "1", "is_del": "0"},
            "list": [
                {"name": "AI工程师", "addr": "青岛市", "click_url": "/client/campus/deliverfirst/id/68/fid/30/rid/516.html"},
                {"name": "AI工程师", "addr": "深圳市", "click_url": "/client/campus/deliverfirst/id/68/fid/30/rid/517.html"},
                {"name": "恶意链接", "addr": "青岛市", "click_url": "https://example.org/evil"},
            ],
        },
    }
    detail = Mock(text='<div class="demand_box">搭建 AI Agent 工作流</div><div class="demand_box">熟悉 LangGraph 与 RAG</div>')

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 10.0, "follow_redirects": False}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, *, data):
            assert url == "https://maker.haier.net/client/campus/getactivityresearchlist.html"
            assert data["keyword"] == "AI" and data["aid"] == "68"
            return feed

        def get(self, url):
            assert url == "https://maker.haier.net/client/campus/deliverfirst/id/68/fid/30/rid/516.html"
            return detail

    monkeypatch.setattr(httpx, "Client", FakeClient)
    jobs = search_haier_campus_jobs(direction_id="agents", location="青岛")
    assert len(jobs) == 1
    assert jobs[0]["title"] == "AI工程师"
    assert "LangGraph" in jobs[0]["snippet"]
    assert jobs[0]["source"] == "海尔官方 2027 校招 · 实时查询"


def test_qwen_sources_must_be_detail_pages_with_city_and_role():
    url = "https://www.zhaopin.com/jobdetail/CC123.htm"
    page = (
        '<title>AI Agent工程师招聘_示例科技招聘 - 智联招聘</title>'
        '<meta name="description" content="示例科技招聘青岛AI Agent工程师，熟悉RAG。">'
    )
    assert _trusted_job_url(url)
    assert not _trusted_job_url("https://www.zhaopin.com/sou/kwAgent")
    assert not _trusted_job_url("https://127.0.0.1/jobdetail/CC123.htm")
    assert not _trusted_job_url("https://www.zhaopin.com.evil.test/jobdetail/CC123.htm")
    job = _job_from_page(url, page, "agents", "青岛")
    assert job and job["company"] == "示例科技"
    assert _job_from_page(url, page, "agents", "深圳") is None
    assert _job_from_page(url, "<title>请稍候 - BOSS直聘</title>", "agents", "青岛") is None


def test_qwen_web_search_uses_only_validated_source_urls(monkeypatch):
    from dashscope import Generation

    response = SimpleNamespace(
        status_code=200,
        output={
            "choices": [{"message": {"content": "我虚构了一个招聘岗位：https://evil.test/job"}}],
            "search_info": {"search_results": [
                {"url": "https://www.zhaopin.com/sou/kwAgent"},
                {"url": "https://www.zhaopin.com/jobdetail/CC123.htm"},
            ]},
        },
    )

    def fake_generation_call(**kwargs):
        assert kwargs["enable_search"] is True
        assert kwargs["search_options"]["enable_source"] is True
        assert "简历" not in kwargs["messages"][0]["content"]
        return response

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url):
            assert url == "https://www.zhaopin.com/jobdetail/CC123.htm"
            return SimpleNamespace(
                headers={"content-type": "text/html; charset=utf-8"},
                text='<title>AI Agent工程师招聘_示例科技招聘 - 智联招聘</title>'
                     '<meta name="description" content="示例科技招聘青岛AI Agent工程师，熟悉RAG。">',
                raise_for_status=lambda: None,
            )

    monkeypatch.setattr(Generation, "call", fake_generation_call)
    monkeypatch.setattr(httpx, "Client", FakeClient)
    jobs = search_qwen_jobs(
        api_key="test-key", model="qwen-plus", direction_id="agents",
        query="智能体工程师", location="青岛",
    )
    assert len(jobs) == 1
    assert jobs[0]["url"] == "https://www.zhaopin.com/jobdetail/CC123.htm"
    assert "evil.test" not in str(jobs)


def test_matcher_reports_evidence_and_missing_mandatory_skill():
    result = compare_resume_job(
        "使用 LangGraph 构建 Agent；搭建 RAG 检索问答，熟悉 Javascript。",
        "必须掌握 Java；使用 LangGraph 开发智能体；RAG 经验优先。",
    )
    assert result["coverage"] is not None and result["coverage"] < 100
    assert any(row["skill"] == "Java" and row["required"] for row in result["gaps"])
    assert any(row["skill"] == "LangGraph" for row in result["matched"])


def test_coach_can_choose_direction_and_view_saved_vacancy_link(monkeypatch):
    monkeypatch.setattr(web_routes, "search_haier_campus_jobs", lambda **kwargs: [])
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        login = client.post(
            "/ui/login", data={"api_key": "test-api-key-value", "tenant_id": "career-demo"},
            follow_redirects=True,
        )
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', login.text).group(1)
        resume = client.post(
            "/ui/coach/resume",
            data={
                "source_name": "智能体简历", "resume_text": "我使用 LangGraph 开发 Agent，并用 RAG 构建问答系统。",
                "consent": "true", "csrf_token": csrf,
            },
            follow_redirects=True,
        )
        assert "AI Agent / 大模型应用工程师" in resume.text
        job = client.post(
            "/ui/jobs",
            data={
                "title": "AI Agent 工程师", "company": "示例企业", "city": "香港",
                "jd_text": "招聘 Agent 开发工程师，使用 LangGraph 和 RAG 构建智能体。",
                "source_url": "https://example.org/jobs/agent-1", "csrf_token": csrf,
            },
            follow_redirects=True,
        )
        assert job.status_code == 200
        with SessionLocal() as db:
            resume_id = db.scalar(select(ResumeRecord.id))
        results = client.get(
            "/ui/coach/jobs",
            params={"resume_id": resume_id, "direction_id": "agents", "location": "香港"},
        )
        assert results.status_code == 200
        assert "https://example.org/jobs/agent-1" in results.text
        assert "未配置跨企业的 Jooble 职位源" in results.text
        assert "匹配的岗位信息" in results.text
        assert "www.bing.com/search?" not in results.text
        shenzhen = client.get(
            "/ui/coach/jobs",
            params={"resume_id": resume_id, "direction_id": "agents", "location": "深圳"},
        )
        assert "AI Agent 开发工程师" in shenzhen.text
        assert "Longbridge" in shenzhen.text
        assert "核查于 2026-10-05" in shenzhen.text
        qingdao = client.get(
            "/ui/coach/jobs",
            params={"resume_id": resume_id, "direction_id": "agents", "location": "青岛"},
        )
        assert "海尔集团" in qingdao.text
        assert "青岛乾程科技" in qingdao.text
        assert "Longbridge" not in qingdao.text
        import_token = re.search(r'name="job_token" value="([^"]+)"', qingdao.text).group(1)
        imported = client.post(
            "/ui/coach/jobs/save",
            data={"job_token": import_token, "csrf_token": csrf},
            follow_redirects=True,
        )
        assert imported.status_code == 200
        assert "简历技能证据覆盖率" in imported.text
        assert "海尔集团" in imported.text
        coached = client.post(
            "/ui/coach",
            data={
                "resume_id": resume_id,
                "job_id": imported.url.params["job_id"],
                "title": "针对性岗位辅导",
                "csrf_token": csrf,
            },
            follow_redirects=True,
        )
        assert coached.status_code == 200
        assert "针对性岗位辅导" in coached.text
        with SessionLocal() as db:
            imported_count = len(list(db.scalars(select(JobRecord).where(
                JobRecord.tenant_id == "career-demo"
            ))))
        duplicate = client.post(
            "/ui/coach/jobs/save",
            data={"job_token": import_token, "csrf_token": csrf},
            follow_redirects=True,
        )
        assert duplicate.status_code == 200
        with SessionLocal() as db:
            assert len(list(db.scalars(select(JobRecord).where(
                JobRecord.tenant_id == "career-demo"
            )))) == imported_count
        rejected = client.post(
            "/ui/coach/jobs/save",
            data={"job_token": import_token + "tamper", "csrf_token": csrf},
        )
        assert rejected.status_code == 400
        monkeypatch.setattr(
            web_routes, "search_haier_campus_jobs",
            lambda **kwargs: [{
                "title": "AI工程师（2027校招）", "company": "海尔集团", "location": "青岛市",
                "snippet": "AI Agent 工作流", "salary": "", "updated": "查询于 2026-10-05",
                "source": "海尔官方 2027 校招 · 实时查询",
                "url": "https://maker.haier.net/client/campus/deliverfirst/id/68/fid/30/rid/516.html",
            }],
        )
        live_without_key = client.get(
            "/ui/coach/jobs",
            params={"resume_id": resume_id, "direction_id": "agents", "location": "青岛"},
        )
        assert "AI工程师（2027校招）" in live_without_key.text
        assert "海尔官方 2027 校招 · 实时查询" in live_without_key.text
        monkeypatch.setattr(
            web_routes, "get_settings",
            lambda: SimpleNamespace(
                dashscope_api_key=SecretStr("test-key"), jooble_api_key=None, jooble_api_host=""
            ),
        )
        monkeypatch.setattr(
            web_routes, "search_qwen_jobs",
            lambda **kwargs: [{
                "title": "AI Agent 校招工程师", "company": "示例企业", "location": "青岛",
                "snippet": "RAG", "salary": "", "updated": "查询于 2026-10-06",
                "source": "千问联网发现 · 来源页已核对",
                "url": "https://www.zhaopin.com/jobdetail/CC123.htm",
            }],
        )
        qwen = client.get(
            "/ui/coach/jobs",
            params={"resume_id": resume_id, "direction_id": "agents", "location": "青岛", "use_qwen": "true"},
        )
        assert "AI Agent 校招工程师" in qwen.text
        assert "千问联网发现" in qwen.text
        monkeypatch.setattr(web_routes, "search_haier_campus_jobs", lambda **kwargs: [])
        no_city = client.get(
            "/ui/coach/jobs",
            params={"resume_id": resume_id, "direction_id": "agents"},
        )
        assert "目标地区：不限" in no_city.text
        assert "Longbridge" in no_city.text
        assert "https://example.org/jobs/agent-1" in no_city.text
        monkeypatch.setattr(
            web_routes, "get_settings",
            lambda: SimpleNamespace(
                jooble_api_key=SecretStr("test-key"), jooble_api_host="hk.jooble.org"
            ),
        )
        monkeypatch.setattr(
            web_routes, "search_jooble_jobs",
            lambda **kwargs: [{
                "title": "智能体工程师", "company": "招聘企业", "location": "香港",
                "snippet": "构建真实 AI Agent", "salary": "", "updated": "2026-10-05",
                "source": "Jooble", "url": "https://hk.jooble.org/jdp/123",
            }],
        )
        live = client.get(
            "/ui/coach/jobs",
            params={"resume_id": resume_id, "direction_id": "agents", "location": "香港"},
        )
        assert live.status_code == 200
        assert "https://hk.jooble.org/jdp/123" in live.text
        assert "招聘企业" in live.text
        other_tenant = client.post(
            "/ui/login", data={"api_key": "test-api-key-value", "tenant_id": "other-tenant"},
            follow_redirects=True,
        )
        assert other_tenant.status_code == 200
        other_csrf = re.search(r'name="csrf_token" value="([^"]+)"', other_tenant.text).group(1)
        assert client.get(str(imported.url)).status_code == 404
        assert client.post(
            "/ui/coach/jobs/save",
            data={"job_token": import_token, "csrf_token": other_csrf},
        ).status_code == 403
        forbidden = client.get(
            "/ui/coach/jobs",
            params={"resume_id": resume_id, "direction_id": "agents", "location": "香港"},
        )
        assert forbidden.status_code == 404
