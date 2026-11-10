"""Transparent resume/JD skill-evidence comparison for the coach UI."""

import re


SKILLS = (
    ("AI Agent / 智能体", ("agent", "智能体")),
    ("LangGraph", ("langgraph",)),
    ("RAG / 检索增强", ("rag", "检索增强")),
    ("MCP", ("mcp", "model context protocol")),
    ("工具调用", ("function calling", "tool use", "工具调用")),
    ("Python", ("python",)),
    ("Java", ("java",)),
    ("PyTorch", ("pytorch",)),
    ("Transformer", ("transformer",)),
    ("多模态", ("多模态", "vlm", "视觉语言")),
    ("计算机视觉", ("计算机视觉", "视觉算法", "opencv")),
    ("点云", ("点云", "point cloud")),
    ("三维重建", ("三维重建", "3d reconstruction")),
    ("深度学习", ("深度学习", "deep learning")),
    ("SQL", ("sql", "mysql", "postgresql")),
    ("Docker", ("docker",)),
    ("FastAPI", ("fastapi",)),
)


def _has(text: str, term: str) -> bool:
    if term.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None
    return term in text


def _excerpt(text: str, aliases: tuple[str, ...], max_chars: int = 180) -> str:
    for segment in re.split(r"[。；;\n]", text):
        if any(_has(segment.lower(), alias.lower()) for alias in aliases):
            return segment.strip()[:max_chars]
    return ""


def compare_resume_job(resume_text: str, jd_text: str) -> dict:
    """Coverage of observable technical requirements, not hiring probability."""
    resume = resume_text.lower()
    jd = jd_text.lower()
    rows = []
    for label, aliases in SKILLS:
        if not any(_has(jd, alias.lower()) for alias in aliases):
            continue
        jd_excerpt = _excerpt(jd_text, aliases)
        preferred = any(word in jd_excerpt for word in ("优先", "加分", "了解"))
        required = not preferred and any(
            word in jd_excerpt for word in ("必须", "必备", "精通", "熟练", "要求", "掌握")
        )
        weight = 2 if required else 1
        evidence = _excerpt(resume_text, aliases) if any(
            _has(resume, alias.lower()) for alias in aliases
        ) else ""
        rows.append({
            "skill": label,
            "required": required,
            "weight": weight,
            "jd_excerpt": jd_excerpt,
            "resume_evidence": evidence,
            "matched": bool(evidence),
        })
    total = sum(row["weight"] for row in rows)
    covered = sum(row["weight"] for row in rows if row["matched"])
    return {
        "coverage": round(100 * covered / total) if total else None,
        "recognized_count": len(rows),
        "matched": [row for row in rows if row["matched"]],
        "gaps": [row for row in rows if not row["matched"]],
        "limited": len(jd_text) < 600,
    }
