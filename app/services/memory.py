import hashlib
import re
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import UserMemory


SENSITIVE_TERMS = {
    "身份证",
    "银行卡",
    "密码",
    "疾病",
    "病史",
    "宗教",
    "民族",
    "政治面貌",
    "性取向",
}


def memory_fingerprint(category: str, content: str) -> str:
    normalized = re.sub(r"\s+", " ", content.strip().lower())
    return hashlib.sha256(f"{category}:{normalized}".encode("utf-8")).hexdigest()


def is_safe_memory(content: str) -> bool:
    """Only durable career context is stored; sensitive traits are deliberately excluded."""
    return not any(term in content for term in SENSITIVE_TERMS)


def upsert_memory(
    db: Session,
    *,
    tenant_id: str,
    owner_id: str,
    category: str,
    content: str,
    source_conversation_id: str | None = None,
) -> UserMemory | None:
    clean = re.sub(r"\s+", " ", content).strip()[:500]
    if len(clean) < 2 or not is_safe_memory(clean):
        return None
    fingerprint = memory_fingerprint(category, clean)
    existing = db.scalar(
        select(UserMemory).where(
            UserMemory.tenant_id == tenant_id,
            UserMemory.owner_id == owner_id,
            UserMemory.fingerprint == fingerprint,
        )
    )
    if existing:
        existing.is_active = True
        return existing
    record = UserMemory(
        tenant_id=tenant_id,
        owner_id=owner_id,
        category=category,
        content=clean,
        fingerprint=fingerprint,
        source_conversation_id=source_conversation_id,
    )
    db.add(record)
    return record


def rank_memories(memories: Iterable[UserMemory], query: str, limit: int = 8) -> list[UserMemory]:
    query_tokens = _tokens(query)
    scored: list[tuple[float, UserMemory]] = []
    for memory in memories:
        if not memory.is_active:
            continue
        memory_tokens = _tokens(memory.content)
        overlap = len(query_tokens & memory_tokens)
        score = overlap / max(1, len(query_tokens | memory_tokens))
        if overlap or memory.category in {"goal", "constraint"}:
            scored.append((score, memory))
    scored.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
    return [item[1] for item in scored[:limit]]


def _tokens(text: str) -> set[str]:
    latin = re.findall(r"[a-z0-9+#.-]{2,}", text.lower())
    chinese_chunks = re.findall(r"[\u4e00-\u9fff]+", text)
    chinese = {
        chunk[index : index + 2]
        for chunk in chinese_chunks
        for index in range(max(1, len(chunk) - 1))
        if len(chunk[index : index + 2]) == 2
    }
    return set(latin) | chinese
