#!/usr/bin/env python
"""拉取【测试】任务（默认已分配+处理中）。stdout=JSON。

示例：
  skill-run list_test_tasks.py
  skill-run list_test_tasks.py --status 处理中
  skill-run list_test_tasks.py --space 1280be963a5a2cc126a4118dca
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _auth import brief_item, post_list, session, space_id, status_id  # noqa: E402

PREFIX = "【测试】"


def main() -> None:
    ap = argparse.ArgumentParser(description="拉取【测试】任务")
    ap.add_argument(
        "--status",
        action="append",
        choices=["已分配", "待处理", "处理中", "已完成", "已取消"],
        help="可重复；默认 已分配+处理中（待处理仅兼容历史任务）",
    )
    ap.add_argument("--space", default=None)
    ap.add_argument("--page-size", type=int, default=50)
    args = ap.parse_args()

    names = args.status or ["已分配", "处理中"]
    ids = [status_id("task", n) for n in names]
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
        category="Task",
        space=space,
        conditions=conditions,
        page_size=args.page_size,
    )
    items = [
        brief_item(it)
        for it in (data.get("result") or [])
        if (it.get("subject") or "").startswith(PREFIX)
    ]
    print(
        json.dumps(
            {
                "space": space,
                "statusFilter": names,
                "totalMatchedPrefix": len(items),
                "apiTotalCount": data.get("totalCount"),
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
