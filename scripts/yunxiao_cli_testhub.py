#!/usr/bin/env python3
"""Execute an already-planned TestHub testcase through the official Yunxiao CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from yunxiao_cli_runtime import (
    AdapterError,
    find_aliyun,
    now_utc,
    output_dir,
    require_auth_env,
    run_devops,
    unwrap,
    write_json,
)


def directory_ids(value: Any) -> list[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        for key in ("identifier", "id", "directoryIdentifier"):
            candidate = node.get(key)
            if candidate and str(candidate) not in found:
                found.append(str(candidate))
                break
        for child in node.values():
            if isinstance(child, (dict, list)):
                walk(child)

    walk(unwrap(value))
    return found


def result_items(value: Any) -> list[dict[str, Any]]:
    current = unwrap(value)
    if isinstance(current, list):
        return [item for item in current if isinstance(item, dict)]
    if isinstance(current, dict):
        for key in ("result", "list", "items", "records"):
            candidate = current.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
    return []


def item_id(item: dict[str, Any]) -> str:
    for key in ("identifier", "id", "testcaseIdentifier", "workitemIdentifier"):
        if item.get(key):
            return str(item[key])
    nested = item.get("testcase")
    if isinstance(nested, dict):
        return item_id(nested)
    return ""


def read_plan_case(cli: str, plan_id: str, testcase_id: str,
                   preferred_directory_id: str = "") -> dict[str, Any]:
    directories = run_devops(cli, [
        "test-hub-get-test-plan-result-directory-list",
        "--test-plan-identifier", plan_id,
    ])
    snapshots: list[dict[str, Any]] = []
    matched: dict[str, Any] | None = None
    all_directory_ids = directory_ids(directories)
    query_directory_ids = (
        [preferred_directory_id]
        if preferred_directory_id and preferred_directory_id in all_directory_ids
        else all_directory_ids
    )
    for directory_id in query_directory_ids:
        response = run_devops(cli, [
            "test-hub-get-test-result-list",
            "--test-plan-identifier", plan_id,
            "--directory-identifier", directory_id,
        ])
        items = result_items(response)
        snapshots.append({"directoryId": directory_id, "items": items})
        for item in items:
            if item_id(item) == testcase_id:
                matched = item
    return {"directories": directories, "results": snapshots, "matched": matched}


def normalize_status(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    for key in ("status", "testResultStatus", "resultStatus"):
        value = item.get(key)
        if isinstance(value, str):
            return value.upper()
        if isinstance(value, dict):
            for nested in ("identifier", "name", "value"):
                if value.get(nested):
                    return str(value[nested]).upper()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="云效TestHub CLI闭环适配器")
    parser.add_argument("--test-plan-id", required=True)
    parser.add_argument("--test-repo-id", required=True)
    parser.add_argument("--testcase-id", required=True)
    parser.add_argument("--executor-id", required=True)
    parser.add_argument("--status", default="PASS", choices=("TODO", "PASS", "FAILURE", "POSTPONE"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    auth = require_auth_env()
    cli = find_aliyun()
    case = unwrap(run_devops(cli, [
        "test-hub-get-testcase",
        "--test-repo-id", args.test_repo_id,
        "--id", args.testcase_id,
    ]))
    if not isinstance(case, dict) or str(case.get("id")) != args.testcase_id:
        raise AdapterError("测试用例回读失败或编号不一致。")
    case_directory = case.get("directory") if isinstance(case.get("directory"), dict) else {}
    preferred_directory_id = str(case_directory.get("id") or "")

    before = read_plan_case(cli, args.test_plan_id, args.testcase_id, preferred_directory_id)
    actions: list[dict[str, Any]] = []
    capability_gap = before["matched"] is None
    if capability_gap:
        actions.append({
            "action": "blocked-plan-testcase",
            "reason": "当前官方devops CLI未提供把已有用例规划进测试计划的命令",
            "testcaseId": args.testcase_id,
        })
    if normalize_status(before["matched"]) != args.status:
        actions.append({"action": "update-result", "status": args.status, "executorId": args.executor_id})

    receipt: dict[str, Any] = {
        "schemaVersion": "oneos.yunxiao-testhub-cli/v1",
        "mode": "apply" if args.apply else "preflight",
        "generatedAt": now_utc(),
        "organizationId": auth["organizationId"],
        "testPlanId": args.test_plan_id,
        "testRepoId": args.test_repo_id,
        "testcase": {"id": args.testcase_id, "customCode": case.get("customCode"), "subject": case.get("subject")},
        "before": before,
        "plannedActions": actions,
        "capabilityGap": capability_gap,
    }

    target = args.output or output_dir() / f"testhub-{args.test_plan_id}-{args.testcase_id}.json"
    if args.apply and capability_gap:
        receipt["blocked"] = True
        write_json(target, receipt)
        raise AdapterError(
            "CLI_CAPABILITY_GAP：用例尚未规划进计划；官方devops插件0.5.2没有规划命令，"
            "公开OpenAPI也未提供该写接口。未更新测试结果。"
        )

    after_planning = before

    if args.apply and normalize_status(after_planning["matched"]) != args.status:
        receipt["updateResponse"] = run_devops(cli, [
            "test-hub-update-test-result",
            "--testplan-id", args.test_plan_id,
            "--id", args.testcase_id,
            "--executor", args.executor_id,
            "--status", args.status,
        ])

    after = read_plan_case(cli, args.test_plan_id, args.testcase_id, preferred_directory_id) if args.apply else before
    progress = run_devops(cli, [
        "test-hub-get-test-plan-progress-rate",
        "--test-plan-identifier", args.test_plan_id,
    ])
    receipt["after"] = after
    receipt["progress"] = progress
    receipt["verified"] = bool(
        args.apply
        and after["matched"] is not None
        and normalize_status(after["matched"]) == args.status
    )

    write_json(target, receipt)
    print(json.dumps({
        "mode": receipt["mode"],
        "verified": receipt["verified"],
        "testPlanId": args.test_plan_id,
        "testcaseId": args.testcase_id,
        "status": normalize_status(after["matched"]),
        "progress": progress,
        "receipt": str(target),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AdapterError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
