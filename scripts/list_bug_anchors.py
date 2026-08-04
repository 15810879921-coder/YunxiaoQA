#!/usr/bin/env python
"""发起缺陷 · 挂载点选：输出【测试】/需求字母表与 AskQuestion 载荷。

示例：
  # 第一步：点选测试任务
  skill-run list_bug_anchors.py --gate test

  # 第二步：已选测试任务后点选需求（含自动追溯候选）
  skill-run list_bug_anchors.py --gate req --test-task DEMO-90

  # 口令已给编号时做唯一校验 / 预勾建议
  skill-run list_bug_anchors.py --gate test --match DEMO-90
"""
from __future__ import annotations

import argparse
import json
import string
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
    list_parent_sub,
    post_list,
    resolve_req_from_test,
    session,
    space_id,
    status_id,
)

PREFIX = "【测试】"
LETTERS = list(string.ascii_lowercase)


def letter_options(items: list[dict[str, Any]], *, label_fn) -> tuple[list[dict], dict]:
    options: list[dict[str, str]] = []
    letter_map: dict[str, Any] = {}
    for i, it in enumerate(items):
        if i >= len(LETTERS):
            break
        letter = LETTERS[i]
        label = label_fn(it)
        oid = str(it.get("serialNumber") or it.get("id") or letter)
        options.append({"id": letter, "label": f"{letter}. {label}"})
        letter_map[letter] = {
            "serialNumber": it.get("serialNumber"),
            "id": it.get("id") or it.get("identifier"),
            "subject": it.get("subject"),
            "status": it.get("status"),
            "label": label,
        }
    return options, letter_map


def list_open_tests(s, space: str, statuses: list[str], page_size: int) -> list[dict]:
    ids = [status_id("task", n) for n in statuses]
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
        s, category="Task", space=space, conditions=conditions, page_size=page_size
    )
    return [
        brief_item(it)
        for it in (data.get("result") or [])
        if (it.get("subject") or "").startswith(PREFIX)
    ]


def collect_req_candidates(s, test_id: str) -> list[dict]:
    """去重后的需求候选：优先自动追溯命中，再补测试/交付/开发 ASSOCIATED 全部需求。"""
    out: list[dict] = []
    seen: set[str] = set()

    def add(meta: dict | None, *, source: str) -> None:
        if not meta:
            return
        wid = meta.get("id") or meta.get("identifier")
        if not wid or wid in seen:
            return
        seen.add(wid)
        row = dict(meta)
        row["source"] = source
        out.append(row)

    primary = resolve_req_from_test(s, test_id)
    add(primary, source="auto_trace")

    def harvest(owner_id: str, source: str) -> None:
        for fwd in (True, False):
            for it in list_associated(s, owner_id, forward=fwd):
                wid = it.get("identifier")
                if not wid or wid in seen:
                    continue
                try:
                    full = get_workitem(s, wid)
                except Exception:
                    continue
                cat = (full.get("category") or full.get("categoryIdentifier") or "").strip()
                if cat not in ("Req", "Requirement"):
                    continue
                add(brief_item(full), source=source)

    harvest(test_id, "test_associated")
    for p in list_parent_sub(s, test_id, forward=False):
        pid = p.get("identifier")
        if not pid:
            continue
        harvest(pid, "delivery_associated")
        for child in list_parent_sub(s, pid, forward=True):
            if (child.get("subject") or "").startswith("【开发】"):
                cid = child.get("identifier")
                if cid:
                    harvest(cid, "dev_associated")

    # auto_trace 置顶
    out.sort(key=lambda x: 0 if x.get("source") == "auto_trace" else 1)
    return out


def match_filter(items: list[dict], match: str | None) -> tuple[list[dict], str | None]:
    if not match:
        return items, None
    m = match.strip()
    hits = [
        it
        for it in items
        if str(it.get("serialNumber") or "") == m
        or m in str(it.get("subject") or "")
        or str(it.get("id") or "") == m
    ]
    if len(hits) == 1:
        return hits, "unique"
    if len(hits) == 0:
        return items, "zero"
    return hits, "multi"


def main() -> None:
    ap = argparse.ArgumentParser(description="缺陷挂载点选（测试任务 / 需求）")
    ap.add_argument("--gate", choices=["test", "req", "both"], default="test")
    ap.add_argument("--test-task", default=None, help="已选【测试】编号；--gate req|both 时必填")
    ap.add_argument("--test-task-id", default=None)
    ap.add_argument("--match", default=None, help="口令预填匹配（编号/标题片段）")
    ap.add_argument("--space", default=None)
    ap.add_argument("--page-size", type=int, default=50)
    ap.add_argument(
        "--status",
        action="append",
        choices=["已分配", "待处理", "处理中", "已完成", "已取消"],
        help="测试任务状态；默认 已分配+处理中（待处理仅兼容历史任务）",
    )
    args = ap.parse_args()

    space = space_id(args.space)
    try:
        s = session(probe=True)
    except AuthError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from e

    result: dict[str, Any] = {
        "ok": True,
        "space": space,
        "gate": args.gate,
        "rule": "缺陷须 ASSOCIATED→【测试】；需求写入描述追溯（不做 ASSOCIATED）。未点选【测试】禁止 create。",
        "askQuestionPreferred": True,
    }

    if args.gate in ("test", "both"):
        statuses = args.status or ["已分配", "处理中"]
        items = list_open_tests(s, space, statuses, args.page_size)
        filtered, match_state = match_filter(items, args.match)
        options, letter_map = letter_options(
            filtered,
            label_fn=lambda it: (
                f"{it.get('serialNumber')} · {it.get('subject')} · {it.get('status')}"
                + (" ★" if match_state == "unique" else "")
            ),
        )
        result["test"] = {
            "statusFilter": statuses,
            "total": len(items),
            "shown": len(filtered),
            "match": args.match,
            "matchState": match_state,
            "suggestedLetter": "a" if match_state == "unique" and options else None,
            "askQuestion": {
                "id": "test_task",
                "prompt": "挂载点选 · 【测试】任务（缺陷将 ASSOCIATED 关联此项）",
                "options": options,
            },
            "letters": letter_map,
            "emptyHint": "无已分配/处理中【测试】：请先让开发提测建【测试】，或扩大 --status",
        }
        if not options:
            result["ok"] = False

    if args.gate in ("req", "both"):
        test_id = args.test_task_id
        test_sn = args.test_task
        if not test_id and test_sn:
            it = find_by_serial(s, space=space, category="Task", serial=test_sn)
            if not it:
                print(
                    json.dumps(
                        {"ok": False, "error": f"未找到测试任务 {test_sn}"},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                raise SystemExit(1)
            test_id = it["identifier"]
            test_meta = brief_item(it)
        elif test_id:
            test_meta = brief_item(get_workitem(s, test_id))
        else:
            print(
                json.dumps(
                    {"ok": False, "error": "--gate req|both 须提供 --test-task 或 --test-task-id"},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            raise SystemExit(1)

        candidates = collect_req_candidates(s, test_id)
        filtered, match_state = match_filter(candidates, args.match)
        options, letter_map = letter_options(
            filtered,
            label_fn=lambda it: (
                f"{it.get('serialNumber')} · {it.get('subject')} · 来源={it.get('source')}"
                + (" ★" if it.get("source") == "auto_trace" or match_state == "unique" else "")
            ),
        )
        result["req"] = {
            "test": test_meta,
            "total": len(candidates),
            "shown": len(filtered),
            "match": args.match,
            "matchState": match_state,
            "suggestedLetter": "a" if options else None,
            "askQuestion": {
                "id": "req",
                "prompt": f"追溯需求 · 写入描述非 ASSOCIATED（父测试={test_meta.get('serialNumber')}）",
                "options": options,
            },
            "letters": letter_map,
            "emptyHint": "无法追溯需求：请先在云效把需求关联到【交付】/【开发】/【测试】，或口令显式 需求=",
        }
        if not options:
            result["ok"] = False

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
