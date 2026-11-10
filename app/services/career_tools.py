import re
from typing import Literal


CareerIntent = Literal[
    "job_recommendation",
    "resume_optimization",
    "interview_preparation",
    "gap_analysis",
    "action_plan",
    "general_coaching",
]


def classify_career_intent(message: str) -> CareerIntent:
    rules: list[tuple[CareerIntent, tuple[str, ...]]] = [
        ("gap_analysis", ("差距", "不足", "缺少", "匹配度")),
        ("interview_preparation", ("面试", "追问", "模拟", "八股")),
        ("job_recommendation", ("岗位", "职位", "找工作", "工作机会", "推荐工作")),
        ("resume_optimization", ("简历", "项目经历", "自我介绍")),
        ("action_plan", ("计划", "安排", "路线", "下一步")),
    ]
    for intent, keywords in rules:
        if any(keyword in message for keyword in keywords):
            return intent
    return "general_coaching"


def rank_jobs(resume_profile: dict | None, jobs: list[dict], limit: int = 5) -> list[dict]:
    profile = resume_profile or {}
    source = " ".join(
        str(value)
        for field in ("skills", "projects", "education", "research_directions")
        for value in profile.get(field, [])
    )
    resume_terms = _terms(source)
    ranked: list[dict] = []
    for job in jobs:
        job_terms = _terms(
            " ".join(
                [
                    str(job.get("title", "")),
                    str(job.get("description", "")),
                    str(job.get("city", "")),
                ]
            )
        )
        matched = sorted(resume_terms & job_terms)
        coverage = len(matched) / max(1, len(resume_terms))
        precision = len(matched) / max(1, len(job_terms))
        score = round(min(100, (coverage * 0.75 + precision * 0.25) * 100))
        ranked.append({**job, "match_score": score, "matched_keywords": matched[:12]})
    ranked.sort(key=lambda item: (item["match_score"], item.get("title", "")), reverse=True)
    return ranked[:limit]


def _terms(text: str) -> set[str]:
    latin = {value.lower() for value in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{1,30}", text)}
    chinese_chunks = re.findall(r"[\u4e00-\u9fff]+", text)
    chinese = {
        chunk[index : index + 2]
        for chunk in chinese_chunks
        for index in range(max(0, len(chunk) - 1))
    }
    return latin | chinese
