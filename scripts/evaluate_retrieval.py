import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.retrieval import LocalKnowledgeRetriever


def main() -> None:
    retriever = LocalKnowledgeRetriever(Path("knowledge"))
    cases = [
        json.loads(line)
        for line in Path("evals/cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    passed = 0
    for case in cases:
        text = "\n".join(item.text for item in retriever.search(case["query"], top_k=3))
        ok = any(token in text for token in case["must_contain_any"])
        passed += int(ok)
        print(f"{'PASS' if ok else 'FAIL'} {case['id']}")
    print(f"retrieval recall: {passed}/{len(cases)} = {passed / len(cases):.1%}")
    raise SystemExit(0 if passed == len(cases) else 1)


if __name__ == "__main__":
    main()
