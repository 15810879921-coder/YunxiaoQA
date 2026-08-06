#!/usr/bin/env python3
"""Close one repaired Bug after a CLI-verified TestHub retest."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yunxiao_cli_runtime as core
from yunxiao_cli_testhub import normalize_status, read_plan_case
from zoneinfo import ZoneInfo

SCHEMA = "oneos.yunxiao-qa-bug-retest-cli/v1"
RETEST_SCHEMA = "oneos.bug-retest/v1"
SKIP_PIPELINE_ENDS = {"小程序"}
START = "<!-- YUNXIAOQA_BUG_RETEST_EVIDENCE_START -->"
END = "<!-- YUNXIAOQA_BUG_RETEST_EVIDENCE_END -->"


def rows(value: Any, label: str) -> list[dict[str, Any]]:
    value = core.unwrap(value)
    if not isinstance(value, list):
        raise core.AdapterError(f"{label}返回结构异常。")
    return [item for item in value if isinstance(item, dict)]


def current_user(executable: str) -> dict[str, Any]:
    value = core.unwrap(core.run_devops(executable, ["base-get-user-by-token"]))
    if not isinstance(value, dict) or not value.get("id"):
        raise core.AdapterError("PAT用户回读失败。")
    return value


def get_item(executable: str, item_id: str) -> dict[str, Any]:
    value = core.unwrap(core.run_devops(executable, ["projex-get-workitem", "--id", item_id]))
    if not isinstance(value, dict) or not value.get("id"):
        raise core.AdapterError(f"工作项{item_id}回读失败。")
    return value


def find_by_serial(executable: str, space_id: str, category: str, serial: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for page in range(1, 101):
        batch = rows(core.run_devops(executable, [
            "projex-search-workitems", "--category", category,
            "--space-id", space_id, "--space-type", "Project",
            "--page", str(page), "--per-page", "200", "--sort", "asc",
        ]), f"{category}工作项查询")
        matches.extend(item for item in batch if str(item.get("serialNumber") or "").upper() == serial.upper())
        if len(batch) < 200:
            break
    ids = {str(item.get("id")) for item in matches if item.get("id")}
    if len(ids) != 1:
        raise core.AdapterError(f"{serial}无法在{category}中唯一解析。")
    item = get_item(executable, next(iter(ids)))
    if str(item.get("serialNumber") or "").upper() != serial.upper():
        raise core.AdapterError(f"{serial}编号回读不一致。")
    return item


def status_name(item: dict[str, Any]) -> str:
    status = item.get("status") or {}
    return str(status.get("displayName") or status.get("name") or "")


def relation_ids(executable: str, item_id: str) -> set[str]:
    values = rows(core.run_devops(executable, [
        "projex-list-workitem-relation-records", "--id", item_id, "--relation-type", "ASSOCIATED",
    ]), "Bug关联项查询")
    return {str(value.get("resourceId")) for value in values if value.get("resourceId")}


def close_status_id(executable: str, space_id: str, item: dict[str, Any]) -> str:
    type_id = str((item.get("workitemType") or {}).get("id") or "")
    workflow = core.unwrap(core.run_devops(executable, [
        "projex-get-workitem-workflow", "--project-id", space_id, "--id", type_id,
    ]))
    statuses = workflow.get("statuses") if isinstance(workflow, dict) else []
    matches = {str(row.get("id")) for row in statuses or [] if isinstance(row, dict)
               and row.get("id") and "已关闭" in {str(row.get("name") or ""), str(row.get("displayName") or "")}}
    if len(matches) != 1:
        raise core.AdapterError("Bug状态已关闭无法唯一解析。")
    return next(iter(matches))


def replace_block(content: str, payload: dict[str, Any]) -> str:
    block = f"{START}<h2>缺陷复测证据（YunxiaoQA）</h2><pre>" + \
        html.escape(json.dumps(payload, ensure_ascii=False, sort_keys=True)) + f"</pre>{END}"
    start = content.find(START)
    end = content.find(END)
    if start >= 0 and end >= start:
        return content[:start] + block + content[end + len(END):]
    return content + ("\n" if content.strip() else "") + block


def read_deployment(path: Path, bug_serial: str) -> dict[str, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise core.AdapterError("test部署证据必须是JSON对象。")
    skipped = str(value.get("testPipeline") or "").lower() == "skipped"
    if skipped:
        if str(value.get("deliveryEnd") or "") not in SKIP_PIPELINE_ENDS:
            raise core.AdapterError("只有小程序交付允许跳过test流水线。")
    elif str(value.get("environment")) != "test" or str(value.get("status")) != "成功":
        raise core.AdapterError("test部署证据环境或状态不符合关闭门禁。")
    if bug_serial not in {str(item) for item in value.get("includedBugSerials") or []}:
        raise core.AdapterError("test部署证据未覆盖该Bug。")
    version = str(value.get("deployedVersion") or value.get("testedVersion") or "")
    execution_id = str(value.get("executionId") or value.get("pipelineRunId") or "")
    if not version:
        raise core.AdapterError("test部署证据缺少复测版本。")
    if skipped:
        return {"version": version, "executionId": execution_id or "skipped"}
    if not execution_id:
        raise core.AdapterError("test部署证据缺少版本或执行ID。")
    return {"version": version, "executionId": execution_id}


def main() -> int:
    parser = argparse.ArgumentParser(description="官方CLI逐Bug复测并关闭适配器")
    parser.add_argument("--space-id", required=True)
    parser.add_argument("--bug-sn", required=True)
    parser.add_argument("--test-sn", required=True)
    parser.add_argument("--test-plan-id", required=True)
    parser.add_argument("--testcase-id", required=True)
    parser.add_argument("--test-repo-id", required=True)
    parser.add_argument("--deployment-evidence", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    executable = core.find_aliyun()
    auth = core.require_auth_env()
    user = current_user(executable)
    bug = find_by_serial(executable, args.space_id, "Bug", args.bug_sn)
    test = find_by_serial(executable, args.space_id, "Task", args.test_sn)
    before = {"bug": {"id": str(bug["id"]), "serialNumber": bug["serialNumber"], "status": status_name(bug), "verifier": bug.get("verifier")},
              "test": {"id": str(test["id"]), "serialNumber": test["serialNumber"]}}
    if str((bug.get("verifier") or {}).get("id") or "") != str(user.get("id")):
        raise core.AdapterError("Bug验证者不是当前测试用户，禁止代为关闭。")
    if str(test["id"]) not in relation_ids(executable, str(bug["id"])):
        raise core.AdapterError("Bug未正式ASSOCIATED到指定测试任务。")
    deployment = read_deployment(args.deployment_evidence, args.bug_sn)
    testhub = read_plan_case(executable, args.test_plan_id, args.testcase_id)
    matched = testhub.get("matched")
    if not isinstance(matched, dict) or normalize_status(matched) != "PASS":
        raise core.AdapterError("TestHub未回读到指定用例PASS，禁止关闭Bug。")
    execution_id = str(matched.get("testResultIdentifier") or "")
    if not execution_id:
        raise core.AdapterError("TestHub复测结果缺少执行ID。")
    key_source = "|".join([str(bug["id"]), args.testcase_id, execution_id, deployment["version"]])
    payload = {"schemaVersion": RETEST_SCHEMA, "bugId": args.bug_sn, "testTaskId": str(test["id"]),
               "testTaskSerial": args.test_sn, "testPlanId": args.test_plan_id, "caseId": args.testcase_id,
               "testExecutionId": execution_id, "environment": "test", "deployedVersion": deployment["version"],
               "deploymentExecutionId": deployment["executionId"], "result": "passed",
               "verifiedBy": {"id": user.get("id"), "name": user.get("name")},
               "verifiedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
               "evidence": f"https://devops.aliyun.com/testhub/plan/{args.test_plan_id}/dashboard",
               "idempotencyKey": "qa-retest-" + hashlib.sha256(key_source.encode("utf-8")).hexdigest()[:20]}
    receipt = {"schemaVersion": SCHEMA, "mode": "apply" if args.apply else "preflight", "organizationId": auth["organizationId"],
               "before": before, "deployment": deployment, "testHub": {"testPlanId": args.test_plan_id,
               "testcaseId": args.testcase_id, "executionId": execution_id, "status": normalize_status(matched)},
               "retestEvidence": payload, "verified": False}
    target = args.output or core.output_dir() / f"qa-bug-retest-{args.bug_sn.lower()}.json"
    if not args.apply:
        core.write_json(target, receipt)
        print(json.dumps({"mode": receipt["mode"], "verified": False, "receipt": str(target)}, ensure_ascii=False))
        return 0
    if status_name(bug) not in {"已修复", "已关闭"}:
        raise core.AdapterError(f"Bug当前状态={status_name(bug)}，期望已修复或已关闭。")
    description = replace_block(str(bug.get("description") or ""), payload)
    if description != str(bug.get("description") or ""):
        core.run_devops(executable, ["projex-update-workitem", "--id", str(bug["id"]), "--biz-body",
            json.dumps({"description": description, "formatType": str(bug.get("formatType") or "MARKDOWN")}, ensure_ascii=False, separators=(",", ":"))])
        bug = get_item(executable, str(bug["id"]))
    if payload["idempotencyKey"] not in str(bug.get("description") or ""):
        raise core.AdapterError("逐Bug复测证据写入后回读失败。")
    if status_name(bug) != "已关闭":
        core.run_devops(executable, ["projex-update-workitem", "--id", str(bug["id"]), "--biz-body",
            json.dumps({"status": close_status_id(executable, args.space_id, bug)}, separators=(",", ":"))])
        bug = get_item(executable, str(bug["id"]))
    receipt["after"] = {"serialNumber": bug.get("serialNumber"), "status": status_name(bug), "verifier": bug.get("verifier")}
    receipt["verified"] = status_name(bug) == "已关闭" and str((bug.get("verifier") or {}).get("id") or "") == str(user.get("id"))
    core.write_json(target, receipt)
    if not receipt["verified"]:
        raise core.AdapterError("Bug关闭后状态或验证者回读失败。")
    print(json.dumps({"mode": receipt["mode"], "verified": True, "bug": receipt["after"], "receipt": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
