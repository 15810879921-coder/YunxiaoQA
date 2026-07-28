#!/usr/bin/env python3
"""按状态拉取缺陷。stdout=JSON。

示例：
  python3 scripts/list_bugs.py --status 已修复 --status 暂不修复
  python3 scripts/list_bugs.py --status 待确认
  python3 scripts/list_bugs.py --status 已关闭 --limit 20
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _auth import RUNTIME, brief_item, post_list, session, space_id, status_id  # noqa: E402

BUG_STATUSES = list(
    k
    for k, v in (RUNTIME.get("status") or {}).get("bug", {}).items()
    if isinstance(v, str)
)


def main() -> None:
    ap = argparse.ArgumentParser(description="按状态拉取缺陷")
    ap.add_argument(
        "--status",
        action="append",
        choices=BUG_STATUSES,
        help="可重复；默认 已修复+暂不修复（待验）",
    )
    ap.add_argument("--space", default=None)
    ap.add_argument("--page-size", type=int, default=50)
    ap.add_argument("--limit", type=int, default=0, help="最多返回条数，0=不截断本页")
    args = ap.parse_args()

    names = args.status or ["已修复", "暂不修复"]
    ids = [status_id("bug", n) for n in names]
    space = space_id(args.space)
    s = session()

    conditions = [
        [
            {
                "className": "status",
                "fieldIdentifier": "status",
                "format": "list",
                "operator": "CONTAINS",
                "value": ids,
            }
        ]
    ]
    data = post_list(
        s,
        category="Bug",
        space=space,
        conditions=conditions,
        page_size=args.page_size,
    )
    items = [brief_item(it) for it in (data.get("result") or [])]
    if args.limit and args.limit > 0:
        items = items[: args.limit]
    print(
        json.dumps(
            {
                "space": space,
                "statusFilter": names,
                "count": len(items),
                "apiTotalCount": data.get("totalCount"),
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
