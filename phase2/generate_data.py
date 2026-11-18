"""Generate the Phase 2 benchmark data set (docs/phase2-design.md §7).

Writes an empty registrations table (metadata + header CSV) and the INSERT SQL
that fills it. Generated files live under phase2/data/ and are not committed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

META = {
    "table_name": "registrations",
    "next_id": 0,
    "columns": [
        {"name": "id", "type_name": "INT", "nullable": False, "auto_increment": True},
        {"name": "student_id", "type_name": "INT", "nullable": False, "auto_increment": False},
        {"name": "course_id", "type_name": "INT", "nullable": False, "auto_increment": False},
        {"name": "status", "type_name": "STRING", "nullable": False, "auto_increment": False},
    ],
}
HEADER = "id,student_id,course_id,status\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument(
        "--data-dir", type=Path, default=Path("phase2/data/registrations")
    )
    parser.add_argument(
        "--out", type=Path, default=Path("phase2/data/insert_registrations.sql")
    )
    args = parser.parse_args()
    if args.rows < 1:
        parser.error("--rows must be at least 1")

    args.data_dir.mkdir(parents=True, exist_ok=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    (args.data_dir / "registrations.meta.json").write_text(
        json.dumps(META, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.data_dir / "registrations.csv").write_text(HEADER, encoding="utf-8")

    with args.out.open("w", encoding="utf-8", newline="\n") as sql:
        for index in range(args.rows):
            sql.write(
                f'INSERT INTO "registrations" VALUES '
                f"({1000 + index}, {index % 300}, 'APPLIED');\n"
            )

    print(f"rows={args.rows}")
    print(f"sql={args.out} ({args.out.stat().st_size} bytes)")
    print(f"data={args.data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
