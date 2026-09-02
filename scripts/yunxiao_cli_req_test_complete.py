#!/usr/bin/env python3
"""Advance a requirement after reapplying the test task's title-selected gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yunxiao_cli_runtime as core
from yunxiao_cli_test_lifecycle import (
    CLOSED_BUG_STATUSES,
    TASK_FLOW_NEW,
    collect_bugs,
    exact_workitem,
    get_workitem,
    item_snapshot,
    parse_approvals,
    require_latest_pass_comment,
    relation_ids,
    resolve_requirement,
    status_id,
    status_name,
    task_flow,
    update_item,
    validate_test_plan_complete,
)

SCHEMA = "oneos.yunxiao-req-test-complete/v1"


def run(args: argparse.Namespace) -> int:
    executable = core.find_aliyun()
    auth = core.require_auth_env()
    test = exact_workitem(executable, args.space_id, "Task", args.test_sn)
    flow = task_flow(str(test.get("subject") or ""))
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
    sprint = parent.get("sprint") if isinstance(parent.get("sprint"), dict) else {}
    if not str(sprint.get("id") or ""):
        raise core.AdapterError(
            "父【交付】缺少迭代；请先运行yunxiao_cli_delivery_iteration.py补绑。"
        )

    bugs = collect_bugs(executable, args.space_id, str(test["id"]), "", match_version=False)
    active = [bug for bug in bugs if bug["status"] not in CLOSED_BUG_STATUSES]
    if active:
        raise core.AdapterError(json.dumps({
            "error": "存在活跃缺陷，禁止需求测试完成。",
            "activeBugs": active,
        }, ensure_ascii=False))

    test_plan: dict[str, Any] | None = None
    pass_comment: dict[str, Any] | None = None
    approvals: dict[str, dict[str, str]] = {}
    if flow == TASK_FLOW_NEW:
        test_plan = validate_test_plan_complete(
            executable, str(args.test_plan_id or ""),
        )
        approvals = parse_approvals(args.risk_approval)
        missing = [bug for bug in bugs if bug["status"] == "暂不修复"
                   and bug["serialNumber"].upper() not in approvals]
        closed_invalid = [bug for bug in bugs if bug["status"] == "已关闭"
                          and not bug["retestEvidenceValid"]]
        extra = sorted(set(approvals) - {
            bug["serialNumber"].upper() for bug in bugs
            if bug["status"] == "暂不修复"
        })
        if missing or closed_invalid or extra:
            raise core.AdapterError(json.dumps({
                "missingRiskApprovals": missing,
                "closedWithoutRetest": closed_invalid,
                "extraApprovals": extra,
            }, ensure_ascii=False))
    else:
        pass_comment = require_latest_pass_comment(
            executable, str(test["id"]),
        )

    receipt: dict[str, Any] = {
        "schemaVersion": SCHEMA,
        "mode": "apply" if args.apply else "preflight",
        "organizationId": auth["organizationId"],
        "projectId": args.space_id,
        "taskFlow": flow,
        "evidenceMode": "testhub-and-defect-gates" if flow == TASK_FLOW_NEW
        else "optimization-pass-comment-and-active-defect-gate",
        "releaseCandidateEligible": flow == TASK_FLOW_NEW,
        "before": before,
        "relations": {
            "parentIds": parents,
            "parent": {**item_snapshot(parent), "sprint": {
                "id": str(sprint.get("id") or ""),
                "name": str(sprint.get("name") or ""),
            }},
            "associatedIds": associated,
        },
        "bugs": bugs,
        "testPlan": test_plan,
        "passComment": pass_comment,
        "riskApprovals": approvals,
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
    parser.add_argument("--test-plan-id", help="【新增】必填；官方CLI回读TestHub计划进度")
    parser.add_argument("--risk-approval", action="append", default=[])
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
