import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.services.vector_math import cosine_similarity


@dataclass(frozen=True)
class EvidenceChunk:
    id: str
    source: str
    text: str
    score: float


class LocalKnowledgeRetriever:
    """Auditable local baseline; replace with pgvector/OpenSearch at larger scale."""

    def __init__(self, knowledge_dir: Path, chunk_size: int = 900, overlap: int = 120) -> None:
        self.knowledge_dir = knowledge_dir
        self.chunk_size = chunk_size
        self.overlap = overlap
        self._chunks = self._load()

    def _load(self) -> list[tuple[str, str, str]]:
        chunks: list[tuple[str, str, str]] = []
        if not self.knowledge_dir.exists():
            return chunks
        for path in sorted(self.knowledge_dir.rglob("*")):
            if path.suffix.lower() not in {".md", ".txt"} or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            step = max(1, self.chunk_size - self.overlap)
            for start in range(0, len(text), step):
                content = text[start : start + self.chunk_size].strip()
                if not content:
                    continue
                relative = path.relative_to(self.knowledge_dir).as_posix()
                chunk_id = hashlib.sha256(f"{relative}:{start}:{content}".encode()).hexdigest()[:16]
                chunks.append((chunk_id, relative, content))
        return chunks

    def search(self, query: str, top_k: int = 4) -> list[EvidenceChunk]:
        ranked = [
            EvidenceChunk(id=chunk_id, source=source, text=text, score=cosine_similarity(query, text))
            for chunk_id, source, text in self._chunks
        ]
        ranked.sort(key=lambda item: item.score, reverse=True)
        return [item for item in ranked[:top_k] if item.score > 0]


def format_evidence(chunks: list[EvidenceChunk]) -> str:
    if not chunks:
        return "没有检索到内部知识证据。不得编造引用。"
    return "\n\n".join(
        f"[evidence_id={item.id}; source={item.source}; score={item.score:.3f}]\n{item.text}"
        for item in chunks
    )

