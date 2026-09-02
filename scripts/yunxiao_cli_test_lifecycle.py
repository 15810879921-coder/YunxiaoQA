#!/usr/bin/env python3
"""Run the Yunxiao QA lifecycle through the official devops CLI.

Completion is selected from the exact task-title marker: new-feature tasks use
the full TestHub/defect evidence gate, while optimization tasks require a latest
passing task comment and no active defects. ``manual-complete`` remains only as
an optimization-task compatibility entrypoint.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yunxiao_cli_runtime as core
from yunxiao_cli_testhub import normalize_status, read_plan_case


SCHEMA = "oneos.yunxiao-qa-lifecycle-cli/v1"
QA_SCHEMA = "oneos.qa-evidence/v1"
DEPLOY_SCHEMA = "oneos.test-deployment/v1"
SKIP_PIPELINE_ENDS = {"小程序"}
QA_START = "<!-- YUNXIAOQA_TEST_EVIDENCE_START -->"
QA_END = "<!-- YUNXIAOQA_TEST_EVIDENCE_END -->"
DEPLOY_START = "<!-- ONEOS_TEST_DEPLOYMENT_EVIDENCE_START -->"
DEPLOY_END = "<!-- ONEOS_TEST_DEPLOYMENT_EVIDENCE_END -->"
BUG_RETEST_START = "<!-- YUNXIAOQA_BUG_RETEST_EVIDENCE_START -->"
BUG_RETEST_END = "<!-- YUNXIAOQA_BUG_RETEST_EVIDENCE_END -->"
BUG_RETEST_SCHEMA = "oneos.bug-retest/v1"
MANUAL_VERDICT = "passed"
MANUAL_TEST_ALLOWED = {"待处理", "处理中", "已完成"}
MANUAL_REQ_ALLOWED = {"待测试", "测试中", "测试完成"}
CLOSED_BUG_STATUSES = {"已关闭", "暂不修复"}
TASK_FLOW_NEW = "new"
TASK_FLOW_OPTIMIZATION = "optimization"
PASS_COMMENT_RE = re.compile(
    r"(?:测试|验证|复测)(?:结果|结论)?\s*[:：]?\s*(?:已|为)?\s*通过"
)
FAIL_COMMENT_RE = re.compile(
    r"(?:测试|验证|复测)(?:结果|结论)?\s*[:：]?\s*(?:为)?\s*"
    r"(?:不通过|未通过|失败|阻塞)|(?:仍(?:然)?(?:存在|复现))|再次打开"
)


def rows(value: Any, label: str) -> list[dict[str, Any]]:
    value = core.unwrap(value)
    if value is None:
        return []
    if not isinstance(value, list):
        raise core.AdapterError(f"{label}返回结构异常。")
    return [row for row in value if isinstance(row, dict)]


def task_flow(subject: str) -> str:
    """Select the completion gate from the exact test-task title markers.

    【新增】wins when both markers exist so an accidental【优化】marker can never
    weaken a new-feature task's evidence gate.
    """
    title = str(subject or "")
    if not title.startswith("【测试】"):
        raise core.AdapterError("目标工作项标题不是【测试】任务。")
    if "【新增】" in title:
        return TASK_FLOW_NEW
    if "【优化】" in title:
        return TASK_FLOW_OPTIMIZATION
    raise core.AdapterError(
        "测试任务标题缺少【新增】或【优化】标记，无法选择闭环门禁。"
    )


def list_workitem_comments(executable: str, workitem_id: str) -> list[dict[str, Any]]:
    value = core.unwrap(core.run_devops(executable, [
        "projex-list-workitem-comments", "--id", workitem_id,
    ]))
    if isinstance(value, dict):
        for key in ("items", "comments", "list"):
            if isinstance(value.get(key), list):
                value = value[key]
                break
    return rows(value, "测试任务评论查询")


def _string_content(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [part for item in value for part in _string_content(item)]
    if isinstance(value, dict):
        return [part for item in value.values() for part in _string_content(item)]
    return []


def comment_text(item: dict[str, Any]) -> str:
    for key in ("content", "comment", "body", "text"):
        if key in item:
            text = " ".join(_string_content(item[key]))
            if text.strip():
                return html.unescape(re.sub(r"<[^>]+>", " ", text)).strip()
    return ""


def comment_timestamp(item: dict[str, Any]) -> float | None:
    for key in (
        "gmtCreate", "createdAt", "createTime", "createdTime",
        "gmtModified", "updatedAt", "updateTime",
    ):
        value = item.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value or "").strip()
        if not text:
            continue
        if text.isdigit():
            return float(text)
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return None


def comment_verdict(text: str) -> str | None:
    matches = [(match.start(), "failed") for match in FAIL_COMMENT_RE.finditer(text)]
    matches.extend((match.start(), "passed") for match in PASS_COMMENT_RE.finditer(text))
    return max(matches, default=(0, None), key=lambda row: row[0])[1]


def require_latest_pass_comment(executable: str,
                                workitem_id: str) -> dict[str, Any]:
    decisive: list[dict[str, Any]] = []
    for index, item in enumerate(list_workitem_comments(executable, workitem_id)):
        text = comment_text(item)
        verdict = comment_verdict(text)
        if verdict:
            decisive.append({
                "index": index,
                "timestamp": comment_timestamp(item),
                "verdict": verdict,
                "snapshot": {
                    "id": str(item.get("id") or item.get("identifier") or ""),
                    "createdAt": item.get("gmtCreate") or item.get("createdAt")
                    or item.get("createTime") or item.get("createdTime"),
                    "content": text[:500],
                },
            })
    if not decisive:
        raise core.AdapterError(
            "【优化】测试任务缺少明确的测试通过评论（如“测试结果：通过”）。"
        )
    if any(row["timestamp"] is None for row in decisive):
        verdicts = {str(row["verdict"]) for row in decisive}
        if len(verdicts) > 1:
            raise core.AdapterError(
                "测试任务存在互相冲突的通过/不通过评论且时间不可排序，请补充最新明确结论。"
            )
        latest = decisive[-1]
    else:
        latest = max(decisive, key=lambda row: (float(row["timestamp"]), int(row["index"])))
    if latest["verdict"] != "passed":
        raise core.AdapterError(json.dumps({
            "error": "optimization_latest_comment_not_passed",
            "latestConclusion": latest["snapshot"],
        }, ensure_ascii=False))
    return latest["snapshot"]


def get_workitem(executable: str, workitem_id: str) -> dict[str, Any]:
    value = core.unwrap(core.run_devops(executable, [
        "projex-get-workitem", "--id", workitem_id,
    ]))
    if not isinstance(value, dict) or not value.get("id"):
        raise core.AdapterError(f"工作项{workitem_id}回读失败。")
    return value


def search_workitems(executable: str, project_id: str,
                     category: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for page in range(1, 101):
        batch = rows(core.run_devops(executable, [
            "projex-search-workitems", "--category", category,
            "--space-id", project_id, "--space-type", "Project",
            "--page", str(page), "--per-page", "200", "--sort", "asc",
        ]), f"{category}工作项查询")
        result.extend(batch)
        if len(batch) < 200:
            break
    return result


def exact_workitem(executable: str, project_id: str, category: str,
                   serial_number: str) -> dict[str, Any]:
    matches = [row for row in search_workitems(executable, project_id, category)
               if str(row.get("serialNumber") or "").upper() == serial_number.upper()]
    ids = {str(row.get("id") or "") for row in matches if row.get("id")}
    if len(ids) != 1:
        raise core.AdapterError(f"{serial_number}无法在{category}中唯一解析。")
    item = get_workitem(executable, next(iter(ids)))
    if str(item.get("serialNumber") or "").upper() != serial_number.upper():
        raise core.AdapterError(f"{serial_number}编号回读不一致。")
    return item


def resolve_requirement(executable: str, project_id: str,
                        associated_ids: list[str],
                        serial_number: str | None = None) -> dict[str, Any]:
    if serial_number:
        requirement = exact_workitem(executable, project_id, "Req", serial_number)
        if str(requirement.get("id") or "") not in associated_ids:
            raise core.AdapterError(
                f"口令需求{serial_number}不是测试任务的正式ASSOCIATED需求。"
            )
        return requirement
    candidates = [row for row in search_workitems(executable, project_id, "Req")
                  if str(row.get("id") or "") in associated_ids]
    candidate_ids = {str(row.get("id") or "") for row in candidates if row.get("id")}
    if len(candidate_ids) != 1:
        raise core.AdapterError(
            f"测试任务无法唯一反查正式ASSOCIATED需求：匹配到{len(candidate_ids)}个。"
        )
    return get_workitem(executable, next(iter(candidate_ids)))


def status_name(item: dict[str, Any]) -> str:
    status = item.get("status") or {}
    return str(status.get("displayName") or status.get("name") or "")


def item_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "serialNumber": str(item.get("serialNumber") or ""),
        "subject": str(item.get("subject") or ""),
        "status": status_name(item),
    }


def relation_ids(executable: str, workitem_id: str,
                 relation_type: str) -> list[str]:
    values = rows(core.run_devops(executable, [
        "projex-list-workitem-relation-records", "--id", workitem_id,
        "--relation-type", relation_type,
    ]), f"{relation_type}关系查询")
    return sorted({str(row.get("resourceId")) for row in values
                   if row.get("resourceId")})


def parse_json_block(content: str, start_marker: str,
                     end_marker: str) -> dict[str, Any]:
    start = content.find(start_marker)
    end = content.find(end_marker)
    if start < 0 or end <= start:
        raise core.AdapterError(f"缺少受管证据区块：{start_marker}")
    fragment = html.unescape(content[start + len(start_marker):end])
    left = fragment.find("{")
    right = fragment.rfind("}")
    if left < 0 or right <= left:
        raise core.AdapterError(f"受管证据区块缺JSON对象：{start_marker}")
    value = json.loads(fragment[left:right + 1])
    if not isinstance(value, dict):
        raise core.AdapterError("受管证据JSON必须是对象。")
    return value


def valid_ref(value: object) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.lower() not in {"none", "null", "n/a", "无", "..."} \
        and "<" not in text and ">" not in text


def is_skip_deployment(value: dict[str, Any]) -> bool:
    return str(value.get("testPipeline") or "").lower() == "skipped"


def validate_deployment_payload(value: dict[str, Any], test: dict[str, Any],
                                req: dict[str, Any], project_id: str) -> dict[str, Any]:
    skipped = is_skip_deployment(value)
    required = {
        "schemaVersion", "projectId", "iterationId", "iterationName",
        "requirementId", "testTaskId", "status", "completedAt", "idempotencyKey",
    }
    required |= {"deliveryEnd", "testPipeline", "reason"} if skipped else {
        "executionId", "environment", "deployedVersion", "evidenceUrl",
    }
    missing = sorted(required - set(value))
    if missing:
        raise core.AdapterError(f"test部署证据缺字段：{missing}")
    if value["schemaVersion"] != DEPLOY_SCHEMA:
        raise core.AdapterError("test部署证据schema无效。")
    if str(value["projectId"]) != project_id:
        raise core.AdapterError("test部署证据项目不一致。")
    if str(value["requirementId"]) not in {
        str(req.get("id") or ""), str(req.get("serialNumber") or "")
    }:
        raise core.AdapterError("test部署证据需求不一致。")
    if str(value["testTaskId"]) not in {
        str(test.get("id") or ""), str(test.get("serialNumber") or "")
    }:
        raise core.AdapterError("test部署证据测试任务不一致。")
    if skipped:
        if str(value["deliveryEnd"]) not in SKIP_PIPELINE_ENDS:
            raise core.AdapterError("只有小程序交付允许跳过test流水线。")
        if str(value["status"]).lower() not in {"skipped", "跳过", "已跳过"}:
            raise core.AdapterError("跳过区块status必须标记为skipped。")
        fields = ("iterationId", "iterationName", "reason", "completedAt",
                  "idempotencyKey")
    else:
        if str(value["environment"]).lower() != "test" or \
                str(value["status"]).lower() not in {"success", "succeeded", "成功"}:
            raise core.AdapterError("test环境部署尚未成功。")
        fields = ("iterationId", "iterationName", "executionId", "deployedVersion",
                  "evidenceUrl", "completedAt", "idempotencyKey")
    for field in fields:
        if not valid_ref(value[field]):
            raise core.AdapterError(f"test部署证据字段无效：{field}")
    return value


def validate_deployment(test: dict[str, Any], req: dict[str, Any],
                        project_id: str) -> dict[str, Any]:
    value = parse_json_block(str(test.get("description") or ""),
                             DEPLOY_START, DEPLOY_END)
    return validate_deployment_payload(value, test, req, project_id)


def load_deployment_repair(path_value: str, test: dict[str, Any],
                           req: dict[str, Any], project_id: str) -> dict[str, Any]:
    path = Path(path_value).resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise core.AdapterError("部署证据修复文件必须是JSON对象。")
    return validate_deployment_payload(value, test, req, project_id)


def load_manifest(path: str, *, test: dict[str, Any], req: dict[str, Any],
                  deployment: dict[str, Any], project_id: str,
                  require_complete: bool) -> tuple[dict[str, Any], str]:
    manifest_path = Path(path).resolve()
    raw = manifest_path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or value.get("schemaVersion") != QA_SCHEMA:
        raise core.AdapterError(f"测试证据清单必须使用{QA_SCHEMA}。")
    required = {
        "projectId", "iterationId", "iterationName", "requirementId",
        "testTaskId", "testPlan", "caseRun", "report", "testDeployment",
        "collectedAt",
    }
    missing = sorted(required - set(value))
    if missing:
        raise core.AdapterError(f"测试证据清单缺字段：{missing}")
    if str(value["projectId"]) != project_id:
        raise core.AdapterError("测试证据项目不一致。")
    if str(value["requirementId"]) not in {
        str(req.get("id") or ""), str(req.get("serialNumber") or "")
    } or str(value["testTaskId"]) not in {
        str(test.get("id") or ""), str(test.get("serialNumber") or "")
    }:
        raise core.AdapterError("测试证据工作项不一致。")
    if str(value["iterationId"]) != str(deployment["iterationId"]) or \
            str(value["iterationName"]) != str(deployment["iterationName"]):
        raise core.AdapterError("测试证据迭代与部署证据不一致。")
    deployed = value.get("testDeployment")
    if not isinstance(deployed, dict):
        raise core.AdapterError("testDeployment必须是对象。")
    if is_skip_deployment(deployment):
        if not is_skip_deployment(deployed) or \
                str(deployed.get("deliveryEnd") or "") != str(deployment["deliveryEnd"]):
            raise core.AdapterError(
                "小程序跳过test流水线时，testDeployment必须写deliveryEnd与testPipeline=skipped。"
            )
    else:
        for field in ("executionId", "deployedVersion", "evidenceUrl"):
            if str(deployed.get(field) or "") != str(deployment[field]):
                raise core.AdapterError(f"测试证据与部署证据不一致：{field}")
    plan = value.get("testPlan")
    run = value.get("caseRun")
    report = value.get("report")
    if not all(isinstance(item, dict) for item in (plan, run, report)):
        raise core.AdapterError("testPlan、caseRun、report必须是对象。")
    for label, item in (("测试计划", plan), ("用例执行", run), ("测试报告", report)):
        if not valid_ref(item.get("id")) or not valid_ref(item.get("url")):
            raise core.AdapterError(f"{label}必须同时提供真实ID和URL。")
    counts = {name: int(run.get(name, -1))
              for name in ("total", "passed", "failed", "blocked", "unexecuted")}
    if any(count < 0 for count in counts.values()) or \
            counts["total"] != sum(counts[name] for name in
                                    ("passed", "failed", "blocked", "unexecuted")):
        raise core.AdapterError("用例执行计数无法闭合。")
    if require_complete and str(run.get("status") or "").lower() not in {
        "completed", "完成", "已完成"
    }:
        raise core.AdapterError("用例执行记录尚未完成。")
    testcase_id = str(run.get("testcaseId") or "")
    if not testcase_id:
        raise core.AdapterError("caseRun缺少testcaseId。")
    value["caseCounts"] = counts
    value["manifestPath"] = str(manifest_path)
    value["manifestSha256"] = hashlib.sha256(raw).hexdigest()
    return value, testcase_id


def validate_testhub(executable: str, evidence: dict[str, Any],
                     testcase_id: str, *, require_complete: bool) -> dict[str, Any]:
    plan_id = str(evidence["testPlan"]["id"])
    live_case = read_plan_case(executable, plan_id, testcase_id)
    matched = live_case.get("matched")
    if not isinstance(matched, dict):
        raise core.AdapterError("TestHub目标用例无法回读。")
    if require_complete and normalize_status(matched) != "PASS":
        raise core.AdapterError("TestHub目标用例未回读为PASS。")
    result_id = str(matched.get("testResultIdentifier") or "")
    if result_id != str(evidence["caseRun"]["id"]):
        raise core.AdapterError("TestHub用例执行ID不一致。")
    progress = core.unwrap(core.run_devops(executable, [
        "test-hub-get-test-plan-progress-rate", "--test-plan-identifier", plan_id,
    ]))
    if not isinstance(progress, dict):
        raise core.AdapterError("TestHub计划进度回读异常。")
    live_counts = {
        "passed": int(progress.get("paasCount", -1)),
        "failed": int(progress.get("failureCount", -1)),
        "blocked": int(progress.get("postponeCount", -1)),
        "unexecuted": int(progress.get("todoCount", -1)),
    }
    live_counts["total"] = sum(live_counts.values())
    if live_counts != evidence["caseCounts"]:
        raise core.AdapterError(f"TestHub计划计数不一致：{live_counts}")
    if live_counts["total"] <= 0:
        raise core.AdapterError("TestHub计划没有用例。")
    if require_complete and any(live_counts[name] != 0 for name in
                                ("failed", "blocked", "unexecuted")):
        raise core.AdapterError("TestHub计划尚未全量通过。")
    expected_dashboard = f"/testhub/plan/{plan_id}/dashboard"
    if expected_dashboard not in str(evidence["report"]["url"]):
        raise core.AdapterError("测试报告URL不是该计划的TestHub概览。")
    return {"progress": progress, "matched": matched}


def validate_test_plan_complete(executable: str, plan_id: str) -> dict[str, Any]:
    """Validate completion directly from TestHub without a QA manifest/report."""
    if not str(plan_id or "").strip():
        raise core.AdapterError("完成测试必须提供--test-plan-id。")
    progress = core.unwrap(core.run_devops(executable, [
        "test-hub-get-test-plan-progress-rate",
        "--test-plan-identifier", str(plan_id),
    ]))
    if not isinstance(progress, dict):
        raise core.AdapterError("TestHub计划进度回读异常。")
    counts = {
        "passed": int(progress.get("paasCount", -1)),
        "failed": int(progress.get("failureCount", -1)),
        "blocked": int(progress.get("postponeCount", -1)),
        "unexecuted": int(progress.get("todoCount", -1)),
    }
    counts["total"] = sum(counts.values())
    if counts["total"] <= 0:
        raise core.AdapterError("TestHub计划没有用例。")
    if any(counts[name] != 0 for name in ("failed", "blocked", "unexecuted")):
        raise core.AdapterError(f"TestHub计划尚未全量通过：{counts}")
    return {"planId": str(plan_id), "progress": progress, "caseCounts": counts}


def bug_retest(bug: dict[str, Any], deployed_version: str, *,
               match_version: bool = True) -> tuple[bool, str, str]:
    if status_name(bug) != "已关闭":
        return False, "", ""
    try:
        value = parse_json_block(str(bug.get("description") or ""),
                                 BUG_RETEST_START, BUG_RETEST_END)
    except (core.AdapterError, ValueError, json.JSONDecodeError):
        return False, "", ""
    key = str(value.get("idempotencyKey") or "")
    version = str(value.get("deployedVersion") or "")
    valid = value.get("schemaVersion") == BUG_RETEST_SCHEMA and \
        str(value.get("result") or "").lower() == "passed" and \
        str(value.get("environment") or "").lower() == "test" and \
        (version == deployed_version if match_version else True) and \
        all(valid_ref(value.get(field)) for field in (
            "caseId", "testExecutionId", "evidence", "deployedVersion",
            "verifiedBy", "verifiedAt", "idempotencyKey",
        ))
    return valid, version, key


def collect_bugs(executable: str, project_id: str, test_id: str,
                 deployed_version: str, *,
                 match_version: bool = True) -> list[dict[str, Any]]:
    bugs: list[dict[str, Any]] = []
    for row in search_workitems(executable, project_id, "Bug"):
        bug_id = str(row.get("id") or "")
        if not bug_id or test_id not in relation_ids(executable, bug_id, "ASSOCIATED"):
            continue
        bug = get_workitem(executable, bug_id)
        valid, version, key = bug_retest(bug, deployed_version,
                                         match_version=match_version)
        bugs.append({
            **item_snapshot(bug),
            "retestEvidenceValid": valid,
            "retestDeployedVersion": version,
            "retestIdempotencyKey": key,
        })
    return sorted(bugs, key=lambda item: item["serialNumber"])


def parse_approvals(values: list[str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for raw in values:
        bug, separator, detail = raw.partition("=")
        approver, pipe, evidence = detail.partition("|")
        key = bug.strip().upper()
        if not separator or not pipe or not key or not approver.strip() or not evidence.strip():
            raise core.AdapterError(
                f"暂不修复批准格式错误：{raw!r}；应为 BUG-ID=批准人|批准记录ID或URL"
            )
        result[key] = {"approver": approver.strip(), "evidence": evidence.strip()}
    return result


def managed_block(payload: dict[str, Any]) -> str:
    return f"{QA_START}<h2>测试执行证据（YunxiaoQA）</h2><pre>" + \
        html.escape(json.dumps(payload, ensure_ascii=False, sort_keys=True)) + \
        f"</pre>{QA_END}"


def deployment_block(payload: dict[str, Any]) -> str:
    return f"{DEPLOY_START}<pre>" + \
        html.escape(json.dumps(payload, ensure_ascii=False, sort_keys=True)) + \
        f"</pre>{DEPLOY_END}"


def replace_block(content: str, block: str) -> str:
    start = content.find(QA_START)
    end = content.find(QA_END)
    if start >= 0 and end >= start:
        return content[:start] + block + content[end + len(QA_END):]
    return content + ("\n" if content.strip() else "") + block


def replace_deployment_block(content: str, block: str) -> str:
    start = content.find(DEPLOY_START)
    end = content.find(DEPLOY_END)
    if start >= 0 and end >= start:
        return content[:start] + block + content[end + len(DEPLOY_END):]
    marker = "## 下一阶段"
    if marker in content:
        return content.replace(marker, block + "\n\n" + marker, 1)
    return content + ("\n" if content.strip() else "") + block


def status_id(executable: str, project_id: str, item: dict[str, Any],
              target_name: str) -> str:
    type_id = str((item.get("workitemType") or {}).get("id") or "")
    workflow = core.unwrap(core.run_devops(executable, [
        "projex-get-workitem-workflow", "--project-id", project_id,
        "--id", type_id,
    ]))
    statuses = workflow.get("statuses") if isinstance(workflow, dict) else []
    matches = {str(row.get("id")) for row in statuses or [] if isinstance(row, dict)
               and row.get("id") and target_name in {
                   str(row.get("name") or ""), str(row.get("displayName") or "")
               }}
    if len(matches) != 1:
        raise core.AdapterError(f"状态{target_name}无法唯一解析。")
    return next(iter(matches))


def update_item(executable: str, workitem_id: str,
                body: dict[str, Any]) -> dict[str, Any]:
    core.run_devops(executable, [
        "projex-update-workitem", "--id", workitem_id, "--biz-body",
        json.dumps(body, ensure_ascii=False, separators=(",", ":")),
    ])
    return get_workitem(executable, workitem_id)


def update_status_checked(executable: str, project_id: str,
                          item: dict[str, Any], target_name: str) -> dict[str, Any]:
    """Update one status and immediately verify the exact serial and target."""
    expected_sn = str(item.get("serialNumber") or "")
    updated = update_item(executable, str(item["id"]), {
        "status": status_id(executable, project_id, item, target_name),
    })
    if str(updated.get("serialNumber") or "").upper() != expected_sn.upper() or \
            status_name(updated) != target_name:
        raise core.AdapterError(
            f"状态写入后回读失败：期望{expected_sn}|{target_name}，"
            f"实际{item_snapshot(updated)}"
        )
    return updated


def run(args: argparse.Namespace) -> int:
    executable = core.find_aliyun()
    auth = core.require_auth_env()
    test = exact_workitem(executable, args.space_id, "Task", args.test_sn)
    flow = task_flow(str(test.get("subject") or ""))
    parents = relation_ids(executable, str(test["id"]), "PARENT")
    associated = relation_ids(executable, str(test["id"]), "ASSOCIATED")
    req = resolve_requirement(executable, args.space_id, associated, args.req_sn)
    args.req_sn = str(req.get("serialNumber") or "")
    before = {"test": item_snapshot(test), "requirement": item_snapshot(req)}
    if len(parents) != 1 or str(req["id"]) not in associated:
        raise core.AdapterError("测试任务正式PARENT/ASSOCIATED关系不完整。")
    parent = get_workitem(executable, parents[0])
    if not str(parent.get("subject") or "").startswith("【交付】"):
        raise core.AdapterError("测试任务唯一父项不是【交付】任务。")
    if args.command == "manual-complete":
        if flow != TASK_FLOW_OPTIMIZATION:
            raise core.AdapterError(
                "manual-complete仅适用于标题含【优化】的测试任务；"
                "【新增】必须走complete完整证据门禁。"
            )
        if args.manual_verdict != MANUAL_VERDICT:
            raise core.AdapterError(
                "【优化】兼容闭环必须传"
                "--manual-verdict passed。"
            )
        if status_name(test) not in MANUAL_TEST_ALLOWED or \
                status_name(req) not in MANUAL_REQ_ALLOWED:
            raise core.AdapterError(f"【优化】兼容闭环状态门禁失败：{before}")
        sprint = parent.get("sprint") if isinstance(parent.get("sprint"), dict) else {}
        if not str(sprint.get("id") or ""):
            raise core.AdapterError(
                "父【交付】缺少迭代；请先运行yunxiao_cli_delivery_iteration.py预检，"
                "将候选发用户确认后补绑。"
            )
        pass_comment = require_latest_pass_comment(executable, str(test["id"]))
        bugs = collect_bugs(
            executable, args.space_id, str(test["id"]), "", match_version=False,
        )
        active = [bug for bug in bugs if bug["status"] not in CLOSED_BUG_STATUSES]
        if active:
            raise core.AdapterError(json.dumps({
                "error": "manual_complete_has_active_bugs",
                "activeBugs": active,
                "hint": "【优化】通过评论不能覆盖活动缺陷；请先闭环缺陷。",
            }, ensure_ascii=False))

        actions: list[dict[str, Any]] = []
        if status_name(test) == "待处理":
            actions.append({
                "operation": "projex-update-workitem", "target": args.test_sn,
                "status": "处理中",
            })
        if status_name(req) == "待测试":
            actions.append({
                "operation": "projex-update-workitem", "target": args.req_sn,
                "status": "测试中",
            })
        if status_name(test) != "已完成":
            actions.append({
                "operation": "projex-update-workitem", "target": args.test_sn,
                "status": "已完成",
            })
        if status_name(req) != "测试完成":
            actions.append({
                "operation": "projex-update-workitem", "target": args.req_sn,
                "status": "测试完成",
            })

        receipt: dict[str, Any] = {
            "schemaVersion": SCHEMA,
            "mode": "apply" if args.apply else "preflight",
            "command": "manual-complete",
            "taskFlow": flow,
            "evidenceMode": "optimization-pass-comment-and-active-defect-gate",
            "manualVerdict": MANUAL_VERDICT,
            "releaseCandidateEligible": False,
            "organizationId": auth["organizationId"],
            "projectId": args.space_id,
            "before": before,
            "relations": {
                "parentIds": parents,
                "parent": {**item_snapshot(parent), "sprint": {
                    "id": str(sprint.get("id") or ""),
                    "name": str(sprint.get("name") or ""),
                }},
                "associatedIds": associated,
            },
            "passComment": pass_comment,
            "bugs": bugs,
            "plannedActions": actions,
            "verified": False,
        }
        if args.apply:
            if status_name(test) == "待处理":
                test = update_status_checked(
                    executable, args.space_id, test, "处理中",
                )
            if status_name(req) == "待测试":
                req = update_status_checked(
                    executable, args.space_id, req, "测试中",
                )
            if status_name(test) != "已完成":
                test = update_status_checked(
                    executable, args.space_id, test, "已完成",
                )
            if status_name(req) != "测试完成":
                req = update_status_checked(
                    executable, args.space_id, req, "测试完成",
                )
            receipt["after"] = {
                "test": item_snapshot(test),
                "requirement": item_snapshot(req),
            }
            receipt["verified"] = status_name(test) == "已完成" and \
                status_name(req) == "测试完成"
            if not receipt["verified"]:
                raise core.AdapterError("【优化】兼容闭环状态写入后回读失败。")
        target = Path(args.output) if args.output else core.output_dir() / \
            f"qa-lifecycle-{args.test_sn.lower()}-manual-complete.json"
        core.write_json(target, receipt)
        print(json.dumps({
            "mode": receipt["mode"],
            "command": "manual-complete",
            "testTask": receipt.get("after", before)["test"],
            "requirement": receipt.get("after", before)["requirement"],
            "bugs": len(bugs),
            "releaseCandidateEligible": False,
            "verified": receipt["verified"],
            "receipt": str(target),
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "start":
        if status_name(test) not in {"待处理", "处理中"} or \
                status_name(req) not in {"待测试", "测试中"}:
            raise core.AdapterError(f"开始测试状态门禁失败：{before}")
        actions = []
        if status_name(test) != "处理中":
            actions.append({
                "operation": "projex-update-workitem", "target": args.test_sn,
                "status": "处理中",
            })
        if status_name(req) != "测试中":
            actions.append({
                "operation": "projex-update-workitem", "target": args.req_sn,
                "status": "测试中",
            })
        receipt: dict[str, Any] = {
            "schemaVersion": SCHEMA,
            "mode": "apply" if args.apply else "preflight",
            "command": "start", "organizationId": auth["organizationId"],
            "projectId": args.space_id, "before": before,
            "relations": {
                "parentIds": parents,
                "parent": item_snapshot(parent),
                "associatedIds": associated,
            },
            "plannedActions": actions, "verified": False,
        }
        if args.apply:
            if status_name(test) != "处理中":
                test = update_item(executable, str(test["id"]), {
                    "status": status_id(executable, args.space_id, test, "处理中")
                })
            if status_name(req) != "测试中":
                req = update_item(executable, str(req["id"]), {
                    "status": status_id(executable, args.space_id, req, "测试中")
                })
            receipt["after"] = {
                "test": item_snapshot(test), "requirement": item_snapshot(req),
            }
            receipt["verified"] = status_name(test) == "处理中" and \
                status_name(req) == "测试中"
            if not receipt["verified"]:
                raise core.AdapterError("开始测试状态写入后回读失败。")
        target = Path(args.output) if args.output else core.output_dir() / \
            f"qa-lifecycle-{args.test_sn.lower()}-start.json"
        core.write_json(target, receipt)
        print(json.dumps({
            "mode": receipt["mode"], "command": "start",
            "testTask": receipt.get("after", before)["test"],
            "requirement": receipt.get("after", before)["requirement"],
            "verified": receipt["verified"], "receipt": str(target),
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "complete":
        if status_name(test) not in {"处理中", "已完成"} or \
                status_name(req) not in {"测试中", "测试完成"}:
            raise core.AdapterError(f"完成测试状态门禁失败：{before}")
        sprint = parent.get("sprint") if isinstance(parent.get("sprint"), dict) else {}
        if not str(sprint.get("id") or ""):
            raise core.AdapterError(
                "父【交付】缺少迭代；请先运行yunxiao_cli_delivery_iteration.py预检，"
                "将候选发用户确认后补绑。"
            )
        bugs = collect_bugs(
            executable, args.space_id, str(test["id"]), "", match_version=False,
        )
        active = [bug for bug in bugs if bug["status"] not in CLOSED_BUG_STATUSES]
        live_testhub: dict[str, Any] | None = None
        approvals: dict[str, dict[str, str]] = {}
        pass_comment: dict[str, Any] | None = None
        if flow == TASK_FLOW_NEW:
            live_testhub = validate_test_plan_complete(
                executable, str(getattr(args, "test_plan_id", "") or ""),
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
            if active or missing or closed_invalid or extra:
                raise core.AdapterError(json.dumps({
                    "activeBugs": active, "missingRiskApprovals": missing,
                    "closedWithoutRetest": closed_invalid,
                    "extraApprovals": extra,
                }, ensure_ascii=False))
        else:
            pass_comment = require_latest_pass_comment(
                executable, str(test["id"]),
            )
            if active:
                raise core.AdapterError(json.dumps({
                    "error": "optimization_complete_has_active_bugs",
                    "activeBugs": active,
                    "hint": "【优化】任务必须先闭环全部活动缺陷。",
                }, ensure_ascii=False))
        release_candidate = flow == TASK_FLOW_NEW
        evidence_mode = "testhub-and-defect-gates" if release_candidate else \
            "optimization-pass-comment-and-active-defect-gate"
        actions: list[dict[str, Any]] = []
        if status_name(test) != "已完成":
            actions.append({"operation": "projex-update-workitem",
                            "target": args.test_sn, "status": "已完成"})
        if status_name(req) != "测试完成":
            actions.append({"operation": "projex-update-workitem",
                            "target": args.req_sn, "status": "测试完成"})
        receipt: dict[str, Any] = {
            "schemaVersion": SCHEMA,
            "mode": "apply" if args.apply else "preflight",
            "command": "complete",
            "taskFlow": flow,
            "evidenceMode": evidence_mode,
            "releaseCandidateEligible": release_candidate,
            "organizationId": auth["organizationId"],
            "projectId": args.space_id,
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
            "plannedActions": actions,
            "verified": False,
        }
        if live_testhub is not None:
            receipt["testHub"] = live_testhub
            receipt["riskApprovals"] = approvals
        if pass_comment is not None:
            receipt["passComment"] = pass_comment
        if args.apply:
            if status_name(test) != "已完成":
                test = update_status_checked(
                    executable, args.space_id, test, "已完成",
                )
            if status_name(req) != "测试完成":
                req = update_status_checked(
                    executable, args.space_id, req, "测试完成",
                )
            receipt["after"] = {
                "test": item_snapshot(test), "requirement": item_snapshot(req),
            }
            receipt["verified"] = status_name(test) == "已完成" and \
                status_name(req) == "测试完成"
            if not receipt["verified"]:
                raise core.AdapterError("测试完成状态写入后回读失败。")
        target = Path(args.output) if args.output else core.output_dir() / \
            f"qa-lifecycle-{args.test_sn.lower()}-complete.json"
        core.write_json(target, receipt)
        print(json.dumps({
            "mode": receipt["mode"], "command": "complete",
            "testTask": receipt.get("after", before)["test"],
            "requirement": receipt.get("after", before)["requirement"],
            "testPlan": live_testhub,
            "bugs": len(bugs),
            "releaseCandidateEligible": release_candidate,
            "verified": receipt["verified"], "receipt": str(target),
        }, ensure_ascii=False, indent=2))
        return 0
    if status_name(test) not in {"处理中", "已完成"} or \
            status_name(req) not in {"测试中", "测试完成"}:
        raise core.AdapterError(f"状态门禁失败：{before}")
    if not args.evidence_manifest:
        raise core.AdapterError("record/complete必须提供--evidence-manifest。")
    deployment_repair = None
    if args.deployment_evidence:
        deployment_repair = load_deployment_repair(
            args.deployment_evidence, test, req, args.space_id,
        )
        repaired_description = replace_deployment_block(
            str(test.get("description") or ""), deployment_block(deployment_repair)
        )
        if args.apply and repaired_description != str(test.get("description") or ""):
            test = update_item(executable, str(test["id"]), {
                "description": repaired_description,
                "formatType": str(test.get("formatType") or "MARKDOWN"),
            })
        else:
            test = {**test, "description": repaired_description}
    deployment = validate_deployment(test, req, args.space_id)
    evidence, testcase_id = load_manifest(
        args.evidence_manifest, test=test, req=req, deployment=deployment,
        project_id=args.space_id, require_complete=args.command == "complete",
    )
    live_testhub = validate_testhub(
        executable, evidence, testcase_id, require_complete=args.command == "complete",
    )
    approvals = parse_approvals(args.risk_approval)
    bugs = collect_bugs(executable, args.space_id, str(test["id"]),
                        str(deployment.get("deployedVersion") or ""),
                        match_version=not is_skip_deployment(deployment))
    if args.command == "complete":
        active = [bug for bug in bugs if bug["status"] not in {"已关闭", "暂不修复"}]
        missing = [bug for bug in bugs if bug["status"] == "暂不修复"
                   and bug["serialNumber"].upper() not in approvals]
        closed_invalid = [bug for bug in bugs if bug["status"] == "已关闭"
                          and not bug["retestEvidenceValid"]]
        extra = sorted(set(approvals) - {bug["serialNumber"].upper() for bug in bugs
                                        if bug["status"] == "暂不修复"})
        if active or missing or closed_invalid or extra:
            raise core.AdapterError(json.dumps({
                "activeBugs": active, "missingRiskApprovals": missing,
                "closedWithoutRetest": closed_invalid, "extraApprovals": extra,
            }, ensure_ascii=False))
    bug_snapshot = [{
        "id": bug["id"], "serialNumber": bug["serialNumber"],
        "status": bug["status"],
        "retestDeployedVersion": bug["retestDeployedVersion"],
        "retestIdempotencyKey": bug["retestIdempotencyKey"],
    } for bug in bugs]
    completed_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    try:
        existing_payload = parse_json_block(
            str(test.get("description") or ""), QA_START, QA_END,
        )
        if existing_payload.get("idempotencyKey") == args.idempotency_key and \
                existing_payload.get("manifestSha256") == evidence["manifestSha256"] and \
                valid_ref(existing_payload.get("completedAt")):
            completed_at = str(existing_payload["completedAt"])
    except (core.AdapterError, ValueError, json.JSONDecodeError):
        pass
    payload = {
        "schemaVersion": QA_SCHEMA, "sourceVerified": True,
        "projectId": evidence["projectId"], "iterationId": evidence["iterationId"],
        "iterationName": evidence["iterationName"],
        "requirementId": evidence["requirementId"], "testTaskId": evidence["testTaskId"],
        "testPlan": evidence["testPlan"], "caseRun": evidence["caseRun"],
        "caseCounts": evidence["caseCounts"], "report": evidence["report"],
        "testDeployment": evidence["testDeployment"], "bugSnapshot": bug_snapshot,
        "bugSnapshotSha256": hashlib.sha256(json.dumps(
            bug_snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "riskApprovals": approvals, "manifestSha256": evidence["manifestSha256"],
        "completedAt": completed_at,
        "idempotencyKey": args.idempotency_key,
    }
    description = replace_block(str(test.get("description") or ""), managed_block(payload))
    actions = [{"operation": "projex-update-workitem", "target": args.test_sn,
                "fields": ["description"]}]
    if deployment_repair is not None:
        actions.insert(0, {"operation": "projex-update-workitem", "target": args.test_sn,
                           "fields": ["oneos.test-deployment/v1"]})
    if args.command == "complete":
        actions.extend([
            {"operation": "projex-update-workitem", "target": args.test_sn,
             "status": "已完成"},
            {"operation": "projex-update-workitem", "target": args.req_sn,
             "status": "测试完成"},
        ])
    receipt: dict[str, Any] = {
        "schemaVersion": SCHEMA, "mode": "apply" if args.apply else "preflight",
        "command": args.command, "organizationId": auth["organizationId"],
        "projectId": args.space_id, "before": before, "relations": {
            "parentIds": parents, "associatedIds": associated,
        }, "deployment": deployment, "testHub": live_testhub,
        "bugs": bugs, "manifestSha256": evidence["manifestSha256"],
        "plannedActions": actions, "verified": False,
    }
    if args.apply:
        if description != str(test.get("description") or ""):
            test = update_item(executable, str(test["id"]), {
                "description": description,
                "formatType": str(test.get("formatType") or "MARKDOWN"),
            })
        reread_payload = parse_json_block(str(test.get("description") or ""), QA_START, QA_END)
        if reread_payload.get("manifestSha256") != evidence["manifestSha256"]:
            raise core.AdapterError("QA证据区块写入后回读失败。")
        if args.command == "complete":
            if status_name(test) != "已完成":
                test = update_item(executable, str(test["id"]), {
                    "status": status_id(executable, args.space_id, test, "已完成")
                })
            if status_name(req) != "测试完成":
                req = update_item(executable, str(req["id"]), {
                    "status": status_id(executable, args.space_id, req, "测试完成")
                })
        receipt["after"] = {"test": item_snapshot(test), "requirement": item_snapshot(req)}
        receipt["evidenceReadback"] = reread_payload
        receipt["verified"] = status_name(test) == (
            "已完成" if args.command == "complete" else before["test"]["status"]
        ) and status_name(req) == (
            "测试完成" if args.command == "complete" else before["requirement"]["status"]
        )
        if not receipt["verified"]:
            raise core.AdapterError("测试生命周期写入后状态回读失败。")
    target = Path(args.output) if args.output else core.output_dir() / \
        f"qa-lifecycle-{args.test_sn.lower()}-{args.command}.json"
    core.write_json(target, receipt)
    print(json.dumps({
        "mode": receipt["mode"], "command": args.command,
        "testTask": receipt.get("after", before)["test"],
        "requirement": receipt.get("after", before)["requirement"],
        "caseCounts": evidence["caseCounts"], "bugs": len(bugs),
        "verified": receipt["verified"], "receipt": str(target),
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("start", "record", "complete", "manual-complete")
    )
    parser.add_argument("--space-id", required=True)
    parser.add_argument("--test-sn", required=True)
    parser.add_argument("--req-sn")
    parser.add_argument("--evidence-manifest")
    parser.add_argument("--deployment-evidence")
    parser.add_argument("--test-plan-id")
    parser.add_argument("--risk-approval", action="append", default=[])
    parser.add_argument("--manual-verdict", choices=(MANUAL_VERDICT,))
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        return run(args)
    except (core.AdapterError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": core.scrub(str(exc))},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
