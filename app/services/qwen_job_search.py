"""Source-grounded vacancy discovery using Qwen's web search.

Qwen discovers URLs; its prose answer is deliberately ignored. Only public
job-detail pages that this module can inspect become vacancy cards.
"""

import re
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urlparse

import httpx

from app.services.job_discovery import HAIER_MATCH_TERMS


_SOURCE_PATHS = {
    "www.zhaopin.com": ("/jobdetail/",),
    "maker.haier.net": ("/client/campus/deliverfirst/", "/client/practicemobile/jobdetail/"),
    "jobs.hisense.com": ("/intern/jobs", "/campus/jobs"),
    "talent.baidu.com": ("/jobs/detail/",),
    "longbridge.com": ("/hk/en/jobs/", "/sg/en/jobs/"),
}


def _trusted_job_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower()
    return any(parsed.path.startswith(prefix) for prefix in _SOURCE_PATHS.get(host, ()))


def _meta(page: str, name: str) -> str:
    match = re.search(
        rf'<meta\s+name=["\']{re.escape(name)}["\']\s+content=["\']([^"\']*)',
        page[:30_000], re.I,
    )
    return unescape(match.group(1)).strip() if match else ""


def _title(page: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", page[:30_000], re.I | re.S)
    return re.sub(r"\s+", " ", unescape(match.group(1))).strip() if match else ""


def _job_from_page(url: str, page: str, direction_id: str, location: str) -> dict | None:
    title = _title(page)
    description = _meta(page, "description")
    if not title or "请稍候" in title or "验证码" in title:
        return None
    combined = f"{title} {description}".lower()
    if location.lower() not in combined:
        return None
    terms = HAIER_MATCH_TERMS.get(direction_id, ())
    if not terms or not any(term.lower() in combined for term in terms):
        return None
    # A search-results page, encyclopedia entry or company page is not a job.
    if not any(word in combined for word in ("招聘", "岗位", "职位", "校招", "实习")):
        return None
    job_title = title.split("招聘_")[0].split(" - ")[0][:200]
    company = "招聘单位见来源页"
    company_match = re.search(r"招聘_([^_]+?)招聘", title)
    if company_match:
        company = company_match.group(1)[:200]
    elif urlparse(url).hostname == "maker.haier.net":
        company = "海尔集团"
    elif urlparse(url).hostname == "talent.baidu.com":
        company = "百度"
    elif urlparse(url).hostname == "jobs.hisense.com":
        company = "海信集团"
    return {
        "title": job_title,
        "company": company,
        "location": location,
        "snippet": (description or title)[:500],
        "salary": "",
        "updated": "查询于 " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": "千问联网发现 · 来源页已核对",
        "url": url,
    }


def search_qwen_jobs(
    *, api_key: str, model: str, direction_id: str, query: str, location: str,
    limit: int = 5,
) -> list[dict]:
    """Search current web sources; never treat generated claims as vacancies."""
    if not api_key or not location.strip():
        return []
    import dashscope

    response = dashscope.Generation.call(
        api_key=api_key,
        model=model,
        messages=[{
            "role": "user",
            "content": (
                f"查找{location}的{query}招聘，优先2027届校招或实习，"
                "优先企业官方职位详情页和招聘平台的具体岗位页。"
                "请联网搜索，不要只给职位列表页。"
            ),
        }],
        enable_search=True,
        search_options={"forced_search": True, "enable_source": True},
        result_format="message",
    )
    if response.status_code != 200:
        raise RuntimeError("千问联网搜索调用失败")
    output = response.output or {}
    sources = (output.get("search_info") or {}).get("search_results") or []
    jobs = []
    seen = set()
    with httpx.Client(timeout=8.0, follow_redirects=False) as client:
        for source in sources[:12]:
            url = str(source.get("url") or "")
            if url in seen or not _trusted_job_url(url):
                continue
            seen.add(url)
            try:
                page = client.get(url)
                page.raise_for_status()
                if not page.headers.get("content-type", "").lower().startswith("text/html"):
                    continue
                job = _job_from_page(url, page.text[:2_000_000], direction_id, location)
            except (httpx.HTTPError, UnicodeError):
                continue
            if job:
                jobs.append(job)
            if len(jobs) >= limit:
                break
    return jobs
