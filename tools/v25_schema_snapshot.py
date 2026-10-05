"""V2.5 迁移前的库结构快照（临时工具，V2.5 交付后可删）。

用法：
    python tools/v25_schema_snapshot.py            # 写 .v25_schema_baseline.json
    python tools/v25_schema_snapshot.py after.json # 写指定文件

用途：迁移前后对比「表 / 列 / 行数」，证明 V2.4 数据没有被破坏。
"""

import json
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "backend", "learning.db")


def snapshot(db_path):
    conn = sqlite3.connect(db_path)
    tables = [row[0] for row in conn.execute(
        "select name from sqlite_master where type='table' order by name")]
    out = {}
    for table in tables:
        if table.startswith("sqlite_"):
            continue
        columns = {row[1]: row[2] for row in conn.execute('PRAGMA table_info("%s")' % table)}
        columns["__rows"] = conn.execute('select count(*) from "%s"' % table).fetchone()[0]
        out[table] = columns
    conn.close()
    return out


def main(argv):
    target = argv[1] if len(argv) > 1 else os.path.join(BASE_DIR, ".v25_schema_baseline.json")
    data = snapshot(DB_PATH)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1, sort_keys=True)
    print("tables:", len(data))
    print("rows:", {name: cols["__rows"] for name, cols in data.items() if cols["__rows"]})
    print("written:", target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
