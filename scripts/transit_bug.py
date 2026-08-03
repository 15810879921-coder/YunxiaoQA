#!/usr/bin/env python
"""缺陷状态流转（测试侧：已修复→已关闭 / 已修复→再次打开）。

写操作：须先经 YunxiaoQA Plan 门禁确认后再执行。

示例：
  skill-run transit_bug.py --id <workitemId> --from 已修复 --to 已关闭
  skill-run transit_bug.py --sn ONEOS-308 --from 已修复 --to 再次打开 --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _auth import (  # noqa: E402
    brief_item,
    document_content,
    get_workitem,
    post_list,
    session,
    set_document_checked,
    space_id,
    status_id,
    transit,
)

ALLOWED = {("已修复", "已关闭"), ("已修复", "再次打开")}
RETEST_START = "<!-- YUNXIAOQA_BUG_RETEST_EVIDENCE_START -->"
RETEST_END = "<!-- YUNXIAOQA_BUG_RETEST_EVIDENCE_END -->"
RETEST_SCHEMA = "oneos.bug-retest/v1"


def valid_evidence(value: str) -> bool:
    text = (value or "").strip()
    return bool(text) and text.lower() not in {"none", "null", "n/a", "无", "..."} and not (
        "<" in text or ">" in text
    )


def replace_retest_block(original: str, block: str) -> str:
    start = original.find(RETEST_START)
    end = original.find(RETEST_END)
    if start >= 0 and end >= start:
        end += len(RETEST_END)
        return original[:start] + block + original[end:]
    return original + ("" if not original.strip() else "\n") + block


def retest_block(args, serial_number: str, key: str) -> str:
    payload = {
        "schemaVersion": RETEST_SCHEMA,
        "bugId": serial_number,
        "caseId": args.retest_case,
        "testExecutionId": args.retest_execution,
        "evidence": args.retest_evidence,
        "environment": args.environment,
        "deployedVersion": args.deployed_version,
        "result": "passed",
        "verifiedBy": args.verified_by,
        "verifiedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "idempotencyKey": key,
    }
    return (
        f"{RETEST_START}<h2>缺陷复测证据（YunxiaoQA）</h2><pre>"
        + html.escape(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        + f"</pre>{RETEST_END}"
    )


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
    ap.add_argument("--retest-case", default="")
    ap.add_argument("--retest-execution", default="")
    ap.add_argument("--retest-evidence", default="")
    ap.add_argument("--environment", default="")
    ap.add_argument("--deployed-version", default="")
    ap.add_argument("--verified-by", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="跳过 ALLOWED 白名单（危险）")
    args = ap.parse_args()

    pair = (args.from_name, args.to_name)
    if pair not in ALLOWED and not args.force:
        raise SystemExit(f"测试侧默认仅允许 {ALLOWED}；确需其他迁移请加 --force")

    space = space_id(args.space)
    s = session()
    wid, meta = resolve_id(s, space, args.sn, args.workitem_id)
    bug = get_workitem(s, wid)
    meta = brief_item(bug)
    if meta.get("status") != args.from_name:
        raise SystemExit(
            f"缺陷当前状态={meta.get('status')}，期望={args.from_name}；拒绝流转"
        )
    from_id = status_id("bug", args.from_name)
    to_id = status_id("bug", args.to_name)

    retest_key = ""
    retest_evidence: dict[str, str] | None = None
    if args.to_name == "已关闭":
        required = {
            "retestCase": args.retest_case,
            "retestExecution": args.retest_execution,
            "retestEvidence": args.retest_evidence,
            "environment": args.environment,
            "deployedVersion": args.deployed_version,
            "verifiedBy": args.verified_by,
        }
        missing = [name for name, value in required.items() if not valid_evidence(value)]
        if missing:
            raise SystemExit(f"关闭缺陷必须提供逐条复测证据，缺少或无效：{missing}")
        if args.environment.strip().lower() != "test":
            raise SystemExit("关闭缺陷只接受test环境逐条复测证据")
        key_source = "|".join(
            [
                wid,
                args.retest_case.strip(),
                args.retest_execution.strip(),
                args.deployed_version.strip(),
                args.retest_evidence.strip(),
            ]
        )
        retest_key = "retest-" + hashlib.sha256(key_source.encode("utf-8")).hexdigest()[:20]
        retest_evidence = required | {"idempotencyKey": retest_key}

    plan = {
        "workitemId": wid,
        "meta": meta,
        "from": args.from_name,
        "fromId": from_id,
        "to": args.to_name,
        "toId": to_id,
        "dryRun": args.dry_run,
        "retestEvidence": retest_evidence,
    }
    report = f"{meta.get('serialNumber') or args.sn or wid} | {meta.get('subject') or ''} | {args.from_name}→{args.to_name}"
    plan["report"] = report

    if args.dry_run:
        print(json.dumps({"ok": True, "wouldTransit": plan}, ensure_ascii=False, indent=2))
        return

    if args.to_name == "已关闭":
        block = retest_block(args, str(meta.get("serialNumber") or args.sn or wid), retest_key)
        set_document_checked(s, wid, replace_retest_block(document_content(bug), block))
        reread = document_content(get_workitem(s, wid))
        if RETEST_START not in reread or RETEST_END not in reread or retest_key not in reread:
            raise SystemExit("逐条复测证据写入回读失败；缺陷保持已修复")

    result = transit(s, wid, from_id, to_id)
    after = brief_item(get_workitem(s, wid))
    after_sn = after.get("serialNumber")
    after_st = after.get("status")
    expect_sn = meta.get("serialNumber") or args.sn
    line = f"{after_sn} | {after.get('subject') or ''} | {args.from_name}→{after_st}"

    if expect_sn and after_sn != expect_sn:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "serial_mismatch",
                    "expected": expect_sn,
                    "actual": after_sn,
                    "report": line,
                    "plan": plan,
                    "after": after,
                    "hint": "编号回读失败：立刻停；禁止用浏览器补救",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(3)

    if after_st != args.to_name:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "status_mismatch",
                    "expectedStatus": args.to_name,
                    "actualStatus": after_st,
                    "report": line,
                    "plan": plan,
                    "after": after,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(3)

    print(
        json.dumps(
            {"ok": True, "plan": plan, "report": line, "result": result, "after": after},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
