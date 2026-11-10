"""Export V2 Chroma documents into an auditable Markdown file."""

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chroma-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("knowledge/imported_v2.md"))
    args = parser.parse_args()
    import chromadb

    client = chromadb.PersistentClient(path=str(args.chroma_dir))
    sections: list[str] = ["# 从 V2 导出的知识（上线前必须人工审阅）\n"]
    for collection in client.list_collections():
        data = collection.get(include=["documents", "metadatas"])
        documents = data.get("documents") or []
        metadatas = data.get("metadatas") or [{} for _ in documents]
        for index, (document, metadata) in enumerate(zip(documents, metadatas, strict=False), 1):
            if not document:
                continue
            sections.append(
                f"## {collection.name} / {index}\n\n来源元数据：`{metadata}`\n\n{document.strip()}\n"
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(sections), encoding="utf-8")
    print(f"Exported knowledge to {args.output}. Review it before deployment.")


if __name__ == "__main__":
    main()

