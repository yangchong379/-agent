"""Conservative V2 migration: imports job descriptions, never candidate PII."""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import JobRecord
from app.core.security import detect_prompt_injection, redact_pii


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True, help="V2 interview.db")
    parser.add_argument("--target", required=True, help="V3 SQLAlchemy database URL")
    parser.add_argument("--tenant", required=True)
    args = parser.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"source database not found: {args.source}")
    engine = create_engine(args.target)
    Base.metadata.create_all(engine)
    source = sqlite3.connect(f"file:{args.source.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    rows = source.execute(
        """
        SELECT normalized_title, raw_title, company, location, url, jd_text, snippet
        FROM job_postings
        WHERE COALESCE(jd_text, '') <> ''
        """
    ).fetchall()
    imported = 0
    skipped = 0
    with Session(engine) as target:
        for row in rows:
            title = row["normalized_title"] or row["raw_title"] or "未命名岗位"
            jd_text = redact_pii(row["jd_text"] or row["snippet"])
            duplicate = target.scalar(
                select(JobRecord).where(
                    JobRecord.tenant_id == args.tenant,
                    JobRecord.title == title,
                    JobRecord.company == (row["company"] or "未知企业"),
                    JobRecord.source_url == row["url"],
                )
            )
            if duplicate:
                skipped += 1
                continue
            target.add(
                JobRecord(
                    tenant_id=args.tenant,
                    title=title,
                    company=row["company"] or "未知企业",
                    city=row["location"] or "",
                    jd_text=jd_text,
                    source_url=row["url"],
                    source_type="verified" if row["url"] else "user_provided",
                    injection_flag=detect_prompt_injection(jd_text),
                )
            )
            imported += 1
        target.commit()
    source.close()
    print(f"Imported {imported} jobs; skipped {skipped} duplicates.")
    print("Candidate/interview history was intentionally not imported: obtain consent and map users first.")


if __name__ == "__main__":
    main()
