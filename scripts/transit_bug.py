#!/usr/bin/env python3
"""缺陷状态流转（测试侧：已修复→已关闭 / 已修复→再次打开）。

写操作：须先经 YunxiaoQA Plan 门禁确认后再执行。

示例：
  python3 scripts/transit_bug.py --id <workitemId> --from 已修复 --to 已关闭
  python3 scripts/transit_bug.py --sn ONEOS-308 --from 已修复 --to 再次打开 --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _auth import (  # noqa: E402
    brief_item,
    post_list,
    session,
    space_id,
    status_id,
    transit,
)

ALLOWED = {("已修复", "已关闭"), ("已修复", "再次打开")}


def resolve_id(s, space: str, sn: str | None, wid: str | None) -> tuple[str, dict]:
    if wid:
        return wid, {"id": wid}
    if not sn:
        raise SystemExit("须提供 --id 或 --sn")
    data = post_list(s, category="Bug", space=space, page_size=100)
    for it in data.get("result") or []:
        if it.get("serialNumber") == sn:
            return it["identifier"], brief_item(it)
    # 扩大：无状态过滤可能不够；再按 serial 条件搜
    conditions = [
        [
            {
                "className": "string",
                "fieldIdentifier": "serialNumber",
                "format": "input",
                "operator": "CONTAINS",
                "value": [sn],
            }
        ]
    ]
    data = post_list(s, category="Bug", space=space, conditions=conditions, page_size=20)
    for it in data.get("result") or []:
        if it.get("serialNumber") == sn:
            return it["identifier"], brief_item(it)
    raise SystemExit(f"未找到缺陷编号 {sn}")


def main() -> None:
    ap = argparse.ArgumentParser(description="缺陷状态流转（测试侧）")
    ap.add_argument("--id", dest="workitem_id", default=None)
    ap.add_argument("--sn", default=None, help="如 ONEOS-308")
    ap.add_argument("--from", dest="from_name", required=True, choices=["已修复"])
    ap.add_argument("--to", dest="to_name", required=True, choices=["已关闭", "再次打开"])
    ap.add_argument("--space", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="跳过 ALLOWED 白名单（危险）")
    args = ap.parse_args()

    pair = (args.from_name, args.to_name)
    if pair not in ALLOWED and not args.force:
        raise SystemExit(f"测试侧默认仅允许 {ALLOWED}；确需其他迁移请加 --force")

    space = space_id(args.space)
    s = session()
    wid, meta = resolve_id(s, space, args.sn, args.workitem_id)
    from_id = status_id("bug", args.from_name)
    to_id = status_id("bug", args.to_name)

    plan = {
        "workitemId": wid,
        "meta": meta,
        "from": args.from_name,
        "fromId": from_id,
        "to": args.to_name,
        "toId": to_id,
        "dryRun": args.dry_run,
    }
    if args.dry_run:
        print(json.dumps({"ok": True, "wouldTransit": plan}, ensure_ascii=False, indent=2))
        return

    result = transit(s, wid, from_id, to_id)
    print(json.dumps({"ok": True, "plan": plan, "result": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
