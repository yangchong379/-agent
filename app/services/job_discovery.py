"""Resume-grounded career directions and linked vacancy search."""

import re
from datetime import datetime, timezone
from dataclasses import dataclass
from html import unescape
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True)
class CareerDirection:
    id: str
    title: str
    query: str
    terms: tuple[str, ...]


DIRECTIONS = (
    CareerDirection(
        "multimodal", "多模态 / 视觉算法工程师", "多模态 算法工程师",
        ("多模态", "视觉语言", "qwen2.5-vl", "vlm", "clip", "图像理解", "计算机视觉"),
    ),
    CareerDirection(
        "three_d", "3D 生成 / 点云算法工程师", "点云 3D 算法工程师",
        ("点云", "3d", "三维重建", "几何", "mesh", "tripo", "instantmesh", "nerf"),
    ),
    CareerDirection(
        "agents", "AI Agent / 大模型应用工程师", "智能体 大模型应用工程师",
        ("智能体", "agent", "langgraph", "rag", "工具调用", "大模型", "llm"),
    ),
    CareerDirection(
        "ml", "机器学习 / 算法工程师", "机器学习 算法工程师",
        ("机器学习", "深度学习", "pytorch", "tensorflow", "模型训练", "算法优化"),
    ),
    CareerDirection(
        "python_backend", "Python 后端工程师", "Python 后端工程师",
        ("python", "fastapi", "django", "flask", "后端", "api开发"),
    ),
    CareerDirection(
        "java_backend", "Java 后端工程师", "Java 后端工程师",
        ("java", "spring boot", "springboot", "微服务", "redis", "mysql"),
    ),
    CareerDirection(
        "frontend", "前端开发工程师", "前端开发工程师",
        ("前端", "react", "vue", "typescript", "javascript", "小程序"),
    ),
    CareerDirection(
        "data", "数据工程 / 数据分析师", "数据工程师 数据分析师",
        ("数据分析", "数据工程", "数据仓库", "spark", "hadoop", "sql", "bi"),
    ),
    CareerDirection(
        "product", "产品经理", "产品经理",
        ("产品经理", "需求分析", "用户研究", "产品规划", "原型设计"),
    ),
    CareerDirection(
        "operations", "运营专员", "运营专员",
        ("运营", "增长", "用户运营", "内容运营", "活动策划"),
    ),
)


def _contains(text: str, term: str) -> bool:
    if term.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None
    return term in text


def recommend_directions(resume_text: str, limit: int = 4) -> list[dict]:
    """Suggest directions only where the resume contains supporting terms."""
    text = resume_text.lower()
    ranked = []
    for direction in DIRECTIONS:
        evidence = [term for term in direction.terms if _contains(text, term)]
        if evidence:
            ranked.append(
                {
                    "id": direction.id,
                    "title": direction.title,
                    "query": direction.query,
                    "evidence": evidence[:5],
                    "score": len(evidence),
                }
            )
    ranked.sort(key=lambda item: (-item["score"], item["title"]))
    return ranked[:limit]


def safe_job_url(value: str | None) -> str | None:
    if not value or len(value) > 2048:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return value


# Public employer/university postings checked on 2026-10-05. These are snapshots,
# never presented as live API results; the source pages remain the authority.
CURATED_JOBS = (
    {
        "title": "算法实习生（多智能体 / Agent 方向）",
        "company": "海尔集团 · 卡奥斯平台",
        "location": "青岛市",
        "snippet": "硕士在读；工业 MCP、Agent 库和多智能体编排。要求 Python、LangGraph/LangChain/AutoGen，了解工具调用与任务规划。实习安排为 2026-08-24 至 2027-02-16、每周 5 天；请确认现在是否仍可投递。",
        "salary": "150元/天（来源页标注）",
        "updated": "核查于 2026-10-05",
        "source": "海尔官方招聘页 · 实习岗位快照",
        "url": "https://maker.haier.net/client/practicemobile/jobdetail/id/10001718",
        "directions": ("agents", "ml"),
    },
    {
        "title": "AI应用工程师（2027届校招公告）",
        "company": "青岛乾程科技股份有限公司",
        "location": "青岛市",
        "snippet": "2027届本/硕/博校招；公告将 AI 应用工程师列为青岛 AI 类岗位，但未列出该岗位的细分 Agent 技术要求。投递方式为关注「乾程招聘」微信公众号。",
        "salary": "未注明具体岗位薪资",
        "updated": "核查于 2026-10-05",
        "source": "天津工业大学就业网 · 企业校招公告快照",
        "url": "https://jobs.tiangong.edu.cn/correcruit/content/id/56177.html",
        "directions": ("agents", "ml"),
    },
    {
        "title": "AI视觉算法工程师（2027届校招）",
        "company": "深圳市纵维立方科技有限公司",
        "location": "深圳市龙岗区",
        "snippet": "硕士及以上；Python、PyTorch、计算机视觉；了解 3D 重建、点云、Mesh、NeRF、Diffusion 者优先。职位页标注有效期至 2026-11-29。",
        "salary": "1.5万–3万元/月（来源页标注）",
        "updated": "核查于 2026-10-05",
        "source": "四川大学就业指导中心 · 岗位快照",
        "url": "https://jy.scu.edu.cn/index/index/employjobdetail.html?data=MDAwMDAwMDAwMJG6n3_Ed6imi4qQtLh4Y9yKlLa-sobddricp9CWi5qikaeWacSdqLqGfaK2w4iil5C4zNbGiL-E",
        "directions": ("three_d", "multimodal", "ml"),
    },
    {
        "title": "三维重建算法工程师（2027届校招）",
        "company": "深圳大漠大智控技术有限公司",
        "location": "深圳",
        "snippet": "图像与点云处理、相机位姿估计、表面重建、多视图重建；涉及 SLAM、3D Gaussian Splatting。",
        "salary": "2.5万–4.5万元/月（来源页标注）",
        "updated": "核查于 2026-10-05",
        "source": "华中科技大学就业信息网 · 校招公告快照",
        "url": "https://job.hust.edu.cn/zpinfo1/2409264.htm",
        "directions": ("three_d", "ml"),
    },
    {
        "title": "深圳-多模态算法工程师（校招，J100770）",
        "company": "百度",
        "location": "深圳",
        "snippet": "视觉语言等多模态理解与生成、图文对齐和评估；要求 Python、PyTorch/PaddlePaddle，熟悉 Transformer、ViT、CLIP。",
        "salary": "未注明",
        "updated": "核查于 2026-10-05",
        "source": "百度校园招聘 · 岗位快照",
        "url": "https://talent.baidu.com/jobs/detail/GRADUATE/6c2e943b-ac8e-40b1-aa64-9787335d4b06",
        "directions": ("multimodal", "ml"),
    },
    {
        "title": "AI Agent 开发工程师（全职）",
        "company": "Longbridge",
        "location": "深圳",
        "snippet": "多 Agent 工作流、RAG、工具调用、LangGraph 等；页面未说明接收应届生，投递前请确认。",
        "salary": "未注明",
        "updated": "核查于 2026-10-05",
        "source": "Longbridge 官方招聘页 · 岗位快照",
        "url": "https://longbridge.com/hk/en/jobs/cc8f46b5-06ac-4a31-aafc-78bdbe741e8d",
        "directions": ("agents", "python_backend"),
    },
)


def curated_jobs(direction_id: str, location: str, limit: int = 10) -> list[dict]:
    """Return verified-at-date detail-page snapshots, not search-page links."""
    wanted = location.strip().lower()
    return [
        {key: value for key, value in item.items() if key != "directions"}
        for item in CURATED_JOBS
        if direction_id in item["directions"] and (not wanted or wanted in item["location"].lower())
        and safe_job_url(item["url"])
    ][:limit]


HAIER_CAMPUS_URL = "https://maker.haier.net"
HAIER_SEARCH_TERMS = {
    "agents": "AI",
    "multimodal": "多模态",
    "three_d": "三维",
    "ml": "算法",
    "python_backend": "软件",
    "java_backend": "软件",
    "frontend": "前端",
    "data": "数据",
    "product": "产品",
    "operations": "运营",
}
HAIER_MATCH_TERMS = {
    "agents": ("agent", "智能体", "langgraph", "rag", "mcp"),
    "multimodal": ("多模态", "视觉语言", "图像", "视频", "视觉"),
    "three_d": ("三维", "3d", "点云", "重建", "几何"),
}


def _haier_detail_text(page: str) -> str:
    """Extract the two job-description blocks from Haier's public detail page."""
    blocks = re.findall(r'<div\s+class="demand_box"[^>]*>(.*?)</div>', page, re.S | re.I)
    parts = []
    for block in blocks[:2]:
        clean = re.sub(r"<br\s*/?>", "；", block, flags=re.I)
        clean = re.sub(r"<[^>]+>", " ", clean)
        clean = re.sub(r"\s+", " ", unescape(clean)).strip(" ；")
        if clean:
            parts.append(clean)
    return "；".join(parts)[:800]


def search_haier_campus_jobs(
    *, direction_id: str, location: str, limit: int = 5
) -> list[dict]:
    """Read current 2027 campus vacancies from Haier's public official site.

    This source only covers Haier. Never send resume text, and never follow URLs
    returned by the feed unless they match its fixed on-site detail path.
    """
    keyword = HAIER_SEARCH_TERMS.get(direction_id)
    if not keyword:
        return []
    with httpx.Client(timeout=10.0, follow_redirects=False) as client:
        response = client.post(
            f"{HAIER_CAMPUS_URL}/client/campus/getactivityresearchlist.html",
            data={"from": "jituan", "page": "1", "pagesize": "30", "keyword": keyword, "aid": "68"},
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or {}
        activity = data.get("activity") or {}
        if payload.get("status") != 1 or activity.get("status") != "1" or activity.get("is_del") == "1":
            return []

        wanted = location.strip().lower()
        terms = HAIER_MATCH_TERMS.get(
            direction_id,
            next((item.terms for item in DIRECTIONS if item.id == direction_id), ()),
        )
        jobs = []
        for item in (data.get("list") or [])[:12]:
            city = str(item.get("addr") or "")[:100]
            if wanted and wanted not in city.lower():
                continue
            path = str(item.get("click_url") or "")
            if not re.fullmatch(r"/client/campus/deliverfirst/id/68/fid/\d+/rid/\d+\.html", path):
                continue
            title = str(item.get("name") or "")[:200]
            if direction_id == "agents" and "产品经理" in title:
                continue
            detail = client.get(f"{HAIER_CAMPUS_URL}{path}")
            detail.raise_for_status()
            description = _haier_detail_text(detail.text)
            searchable = f"{title} {description}".lower()
            matches = sum(term.lower() in searchable for term in terms)
            if not description or not matches:
                continue
            score = matches + (2 if "智能体" in title or "agent" in title.lower() else 0)
            jobs.append((score, {
                "title": title,
                "company": "海尔集团",
                "location": city or "地点未注明",
                "snippet": description[:500],
                "salary": "",
                "updated": "查询于 " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "source": "海尔官方 2027 校招 · 实时查询",
                "url": f"{HAIER_CAMPUS_URL}{path}",
            }))
    jobs.sort(key=lambda pair: pair[0], reverse=True)
    return [job for _, job in jobs[:limit]]


def search_jooble_jobs(
    *, api_key: str, host: str, query: str, location: str, limit: int = 10
) -> list[dict]:
    """Fetch linked vacancies from the configured regional Jooble API."""
    if not re.fullmatch(r"(?:[a-z]{2,3}\.)?jooble\.org", host.lower()):
        raise ValueError("JOOBLE_API_HOST 必须是对应地区的 jooble.org 域名")
    response = httpx.post(
        f"https://{host.lower()}/api/{api_key}",
        json={"keywords": query, "location": location, "ResultOnPage": limit, "page": 1},
        timeout=15.0,
    )
    response.raise_for_status()
    data = response.json()
    jobs = []
    for item in data.get("jobs", [])[:limit]:
        link = safe_job_url(item.get("link"))
        if not link:
            continue
        jobs.append(
            {
                "title": str(item.get("title") or "未注明职位")[:200],
                "company": str(item.get("company") or "企业未注明")[:200],
                "location": str(item.get("location") or "地点未注明")[:100],
                "snippet": str(item.get("snippet") or "")[:500],
                "salary": str(item.get("salary") or "")[:100],
                "updated": str(item.get("updated") or "")[:50],
                "source": "Jooble",
                "url": link,
            }
        )
    return jobs
