#!/usr/bin/env python3
"""把历史数据里被旧版归一化误转的「幺」还原成「么」。

旧版 `zhconv` 会把「那么半年」转成「那幺半年」、「有什么证实」转成「有什幺证实」，
这些错字随转写一起写进了 `jobs`。新版本已经不再产生（`app/services/textnorm.py` 里
按位还原），本脚本用来清理已经写坏的数据：默认只预览，加 `--apply` 才写回，写回前自动备份。

    python3 script/fix-yao-typo.py
    python3 script/fix-yao-typo.py --apply
    python3 script/fix-yao-typo.py --db backend/data/app.db
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "backend" / "data" / "app.db"
FIELDS = ("title", "transcript_json", "summary_json")
# 中文里真正用「幺」的词，命中时原样保留
KEEP = ("幺蛾子", "幺儿", "幺妹", "幺鸡", "幺饼", "幺牌", "幺九", "幺半群", "幺元", "幺正", "幺模")
GUARD = "\u0001"


def fix_text(text: str) -> str:
    if not text or "幺" not in text:
        return text
    guarded = text
    for word in KEEP:
        guarded = guarded.replace(word, word.replace("幺", GUARD))
    return guarded.replace("幺", "么").replace(GUARD, "幺")


def rows(connection: sqlite3.Connection):
    return connection.execute(f"SELECT id, {', '.join(FIELDS)} FROM jobs")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true", help="写回数据库（默认只预览）")
    args = parser.parse_args()
    if not args.db.exists():
        print(f"数据库不存在：{args.db}")
        return 1

    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    found = 0
    for row in rows(connection):
        for field in FIELDS:
            raw = row[field] or ""
            fixed = fix_text(raw)
            if fixed == raw:
                continue
            found += 1
            index = next(i for i in range(len(raw)) if raw[i] != fixed[i])
            print(f"{row['id']} {field}")
            print(f"  旧：{raw[max(0, index - 16) : index + 16]!r}")
            print(f"  新：{fixed[max(0, index - 16) : index + 16]!r}")
    print(f"待修正 {found} 处")
    if not found:
        connection.close()
        return 0
    if not args.apply:
        print("（预览模式，未写入；确认后加 --apply）")
        connection.close()
        return 0

    backup = args.db.with_name(f"{args.db.name}.bak-{dt.datetime.now():%Y%m%d%H%M%S}")
    shutil.copy2(args.db, backup)
    with connection:
        for row in rows(connection):
            sets: list[str] = []
            params: list[str] = []
            for field in FIELDS:
                raw = row[field] or ""
                fixed = fix_text(raw)
                if fixed != raw:
                    sets.append(f"{field} = ?")
                    params.append(fixed)
            if sets:
                connection.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", [*params, row["id"]])
    print(f"已写回，备份：{backup}")
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
