#!/usr/bin/env python3
"""闭环【测试】任务：待处理|处理中 → 已完成。

强制：--sn 精确解析 serialNumber；apply 后回读编号/标题/状态，对不上则失败退出。
禁止用浏览器点列表改状态；本脚本是唯一闭环写入口。

写操作：须先经 YunxiaoQA Plan 门禁确认后再执行。

示例：
  python3 scripts/close_test_task.py --sn ONEOS-343 --dry-run
  python3 scripts/close_test_task.py --sn ONEOS-343
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _auth import (  # noqa: E402
    AuthError,
    brief_item,
    find_by_serial,
    get_workitem,
    list_associated,
    session,
    space_id,
    status_id,
    transit,
)

PREFIX = "【测试】"
ALLOWED_FROM = {"待处理", "处理中"}
TARGET = "已完成"
CLOSED_BUG_STATUSES = {"暂不修复", "已关闭"}


def bug_status_name(it: dict[str, Any]) -> str:
    st = it.get("status") or {}
    return (st.get("displayName") or st.get("name") or "").strip()


def report_line(sn: str, subject: str, frm: str, to: str) -> str:
    return f"{sn} | {subject} | {frm}→{to}"


def resolve_task(s, space: str, sn: str) -> dict[str, Any]:
    it = find_by_serial(s, space=space, category="Task", serial=sn)
    if not it:
        raise SystemExit(f"未找到任务编号 {sn}（category=Task，serialNumber 精确匹配）")
    if it.get("serialNumber") != sn:
        raise SystemExit(
            f"编号匹配错误：请求 {sn}，解析到 {it.get('serialNumber')} | {it.get('subject')}"
        )
    return it


def is_bug_item(it: dict[str, Any]) -> bool:
    cat = (it.get("category") or it.get("categoryIdentifier") or "").strip().lower()
    if cat == "bug":
        return True
    wtype = it.get("workitemType")
    if isinstance(wtype, dict):
        type_name = (wtype.get("name") or wtype.get("displayName") or "").lower()
        if "bug" in type_name or "缺陷" in type_name:
            return True
    st = bug_status_name(it)
    # 关联列表偶发缺 category：用缺陷专用状态名兜底识别
    return st in {"待确认", "已修复", "再次打开", "暂不修复", "已关闭"}


def check_associated_closed(s, workitem_id: str) -> list[dict[str, str]]:
    """返回未闭环缺陷摘要；空列表=可闭环。"""
    open_bugs: list[dict[str, str]] = []
    for it in list_associated(s, workitem_id, forward=True):
        if not is_bug_item(it):
            continue
        st = bug_status_name(it)
        if st not in CLOSED_BUG_STATUSES:
            open_bugs.append(
                {
                    "serialNumber": it.get("serialNumber") or "",
                    "subject": it.get("subject") or "",
                    "status": st or "(空)",
                }
            )
    return open_bugs


def main() -> None:
    ap = argparse.ArgumentParser(description="闭环【测试】任务 → 已完成")
    ap.add_argument("--sn", required=True, help="如 ONEOS-343（强制；禁止只凭标题）")
    ap.add_argument("--space", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--skip-assoc-check",
        action="store_true",
        help="跳过关联缺陷闭环校验（危险；仅 Plan 显式批准）",
    )
    ap.add_argument(
        "--allow-non-prefix",
        action="store_true",
        help="允许标题不以【测试】开头（默认拒绝）",
    )
    args = ap.parse_args()

    sn = args.sn.strip()
    space = space_id(args.space)

    try:
        s = session()
    except AuthError as e:
        print(json.dumps({"ok": False, "error": "auth", "message": str(e)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from e

    item = resolve_task(s, space, sn)
    meta = brief_item(item)
    subject = meta.get("subject") or ""
    from_name = meta.get("status") or ""
    wid = meta["id"]

    if not args.allow_non_prefix and not subject.startswith(PREFIX):
        raise SystemExit(
            f"拒绝：{sn} 标题不以「{PREFIX}」开头：{subject}\n"
            "若确认为测试任务，Plan 确认后加 --allow-non-prefix"
        )

    if from_name == TARGET:
        line = report_line(sn, subject, from_name, TARGET)
        print(
            json.dumps(
                {
                    "ok": True,
                    "alreadyDone": True,
                    "report": line,
                    "meta": meta,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if from_name not in ALLOWED_FROM:
        raise SystemExit(
            f"拒绝：{sn} 当前状态「{from_name}」不在 {sorted(ALLOWED_FROM)}，无法闭环到{TARGET}"
        )

    open_bugs: list[dict[str, str]] = []
    if not args.skip_assoc_check:
        open_bugs = check_associated_closed(s, wid)
        if open_bugs:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "assoc_open",
                        "report": report_line(sn, subject, from_name, TARGET),
                        "openBugs": open_bugs,
                        "hint": "关联缺陷未全部 ∈ {暂不修复, 已关闭}；勿改状态",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            raise SystemExit(4)

    from_id = status_id("task", from_name)
    to_id = status_id("task", TARGET)
    plan = {
        "workitemId": wid,
        "serialNumber": sn,
        "subject": subject,
        "from": from_name,
        "fromId": from_id,
        "to": TARGET,
        "toId": to_id,
        "report": report_line(sn, subject, from_name, TARGET),
        "dryRun": args.dry_run,
    }

    if args.dry_run:
        print(json.dumps({"ok": True, "wouldTransit": plan}, ensure_ascii=False, indent=2))
        return

    transit(s, wid, from_id, to_id)

    # 强制回读：编号硬门禁（防点错行 / 错 id）
    after = brief_item(get_workitem(s, wid))
    after_sn = after.get("serialNumber")
    after_st = after.get("status")
    after_sub = after.get("subject") or ""
    line = report_line(str(after_sn), after_sub, from_name, str(after_st))

    if after_sn != sn:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "serial_mismatch",
                    "expected": sn,
                    "actual": after_sn,
                    "report": line,
                    "before": meta,
                    "after": after,
                    "hint": "编号回读失败：立刻停；禁止继续用浏览器补救",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(3)

    if after_st != TARGET:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "status_mismatch",
                    "expectedStatus": TARGET,
                    "actualStatus": after_st,
                    "report": line,
                    "after": after,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(3)

    print(
        json.dumps(
            {
                "ok": True,
                "plan": plan,
                "report": line,
                "after": after,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
