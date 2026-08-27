#!/usr/bin/env python3
"""Advance requirement 测试中→测试完成 when test task is already 已完成 and no active bugs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yunxiao_cli_runtime as core
from yunxiao_cli_test_lifecycle import (
    collect_bugs,
    exact_workitem,
    get_workitem,
    item_snapshot,
    relation_ids,
    resolve_requirement,
    status_id,
    status_name,
    update_item,
)

SCHEMA = "oneos.yunxiao-req-test-complete/v1"
ACTIVE_BUG_STATUSES = {"待确认", "处理中", "已修复", "再次打开"}


def plan_summary(executable: str, plan_id: str) -> dict[str, Any]:
    progress = core.unwrap(core.run_devops(executable, [
        "test-hub-get-test-plan-progress-rate",
        "--test-plan-identifier", plan_id,
    ]))
    if not isinstance(progress, dict):
        raise core.AdapterError("TestHub计划进度回读异常。")
    return {
        "testPlanId": plan_id,
        "url": f"https://devops.aliyun.com/testhub/plan/{plan_id}/dashboard",
        "progress": progress,
    }


def run(args: argparse.Namespace) -> int:
    executable = core.find_aliyun()
    auth = core.require_auth_env()
    test = exact_workitem(executable, args.space_id, "Task", args.test_sn)
    associated = relation_ids(executable, str(test["id"]), "ASSOCIATED")
    req = resolve_requirement(executable, args.space_id, associated, args.req_sn)
    args.req_sn = str(req.get("serialNumber") or "")
    before = {"test": item_snapshot(test), "requirement": item_snapshot(req)}

    if status_name(test) != "已完成":
        raise core.AdapterError(f"【测试】必须为已完成，当前={status_name(test)}。")
    if status_name(req) != "测试中":
        raise core.AdapterError(f"需求必须为测试中，当前={status_name(req)}。")

    parents = relation_ids(executable, str(test["id"]), "PARENT")
    if len(parents) != 1 or str(req["id"]) not in associated:
        raise core.AdapterError("测试任务正式 PARENT/ASSOCIATED 关系不完整。")
    parent = get_workitem(executable, parents[0])
    if not str(parent.get("subject") or "").startswith("【交付】"):
        raise core.AdapterError("测试任务唯一父项不是【交付】任务。")

    bugs = collect_bugs(executable, args.space_id, str(test["id"]), "", match_version=False)
    active = [bug for bug in bugs if bug["status"] in ACTIVE_BUG_STATUSES]
    if active:
        raise core.AdapterError(json.dumps({
            "error": "存在活跃缺陷，禁止需求测试完成。",
            "activeBugs": active,
        }, ensure_ascii=False))

    test_plan: dict[str, Any] | None = None
    if args.test_plan_id:
        test_plan = plan_summary(executable, args.test_plan_id)

    receipt: dict[str, Any] = {
        "schemaVersion": SCHEMA,
        "mode": "apply" if args.apply else "preflight",
        "organizationId": auth["organizationId"],
        "projectId": args.space_id,
        "before": before,
        "bugs": bugs,
        "testPlan": test_plan,
        "plannedActions": [{
            "operation": "projex-update-workitem",
            "target": args.req_sn,
            "status": "测试完成",
        }],
        "verified": False,
    }

    if args.apply:
        req = update_item(executable, str(req["id"]), {
            "status": status_id(executable, args.space_id, req, "测试完成"),
        })
        receipt["after"] = {
            "test": item_snapshot(test),
            "requirement": item_snapshot(req),
        }
        receipt["verified"] = status_name(req) == "测试完成"
        if not receipt["verified"]:
            raise core.AdapterError("需求状态写入后回读失败。")

    target = Path(args.output) if args.output else \
        core.output_dir() / f"req-test-complete-{args.req_sn.lower()}.json"
    core.write_json(target, receipt)
    print(json.dumps({
        "mode": receipt["mode"],
        "verified": receipt["verified"],
        "testTask": receipt.get("after", before)["test"],
        "requirement": receipt.get("after", before)["requirement"],
        "testPlan": test_plan,
        "receipt": str(target),
        "reportLine": f"{args.req_sn} | {before['requirement']['subject']} | 测试中→测试完成"
            if receipt["verified"] else None,
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="需求测试完成：测试中→测试完成（无缺陷捷径）")
    parser.add_argument("--space-id", required=True)
    parser.add_argument("--test-sn", required=True)
    parser.add_argument("--req-sn")
    parser.add_argument("--test-plan-id", help="可选；回读并记录 TestHub 计划进度到回执")
    parser.add_argument("--idempotency-key")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except core.AdapterError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
