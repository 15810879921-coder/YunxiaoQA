#!/usr/bin/env python
"""已停用的旧测试闭环入口。

该入口无法同时校验正常需求test部署、QA证据清单和逐Bug复测证据，
因此始终拒绝写入。请使用 transit_test_lifecycle.py complete。
"""
from __future__ import annotations

import argparse
import json
from typing import Any


def bug_status_name(item: dict[str, Any]) -> str:
    """供完整闭环脚本复用的只读状态解析器。"""
    status = item.get("status") or item.get("workitemStatus") or {}
    if isinstance(status, str):
        return status.strip()
    if not isinstance(status, dict):
        return ""
    return str(status.get("displayName") or status.get("name") or "").strip()


def is_bug_item(item: dict[str, Any]) -> bool:
    """供完整闭环脚本复用的只读缺陷类型判定器。"""
    category = str(item.get("category") or item.get("categoryIdentifier") or "").lower()
    if category == "bug":
        return True
    workitem_type = item.get("workitemType")
    if isinstance(workitem_type, dict):
        name = str(
            workitem_type.get("name") or workitem_type.get("displayName") or ""
        ).lower()
        if "bug" in name or "缺陷" in name:
            return True
    return bug_status_name(item) in {"待确认", "已修复", "再次打开", "暂不修复", "已关闭"}


def main() -> None:
    parser = argparse.ArgumentParser(description="旧闭环入口已停用")
    parser.add_argument("--sn", required=True, help="原测试任务编号")
    parser.add_argument("--dry-run", action="store_true")
    args, unknown = parser.parse_known_args()
    print(
        json.dumps(
            {
                "ok": False,
                "error": "deprecated_unsafe_entry",
                "testTask": args.sn.strip(),
                "ignoredArguments": unknown,
                "message": "旧入口不能证明完整测试闭环，已禁止状态写入。",
                "nextCommand": (
                    "skill-run transit_test_lifecycle.py complete "
                    f"--test-sn {args.sn.strip()} --req-sn <需求编号> "
                    "--evidence-manifest <证据清单.json> --dry-run"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    raise SystemExit(4)


if __name__ == "__main__":
    main()
