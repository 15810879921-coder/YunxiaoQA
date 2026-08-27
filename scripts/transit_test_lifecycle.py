#!/usr/bin/env python
"""推进测试生命周期，并同步需求状态与可审计证据。

支持三个动作：
  start:    【测试】待处理→处理中；需求待测试→测试中
  record:   在测试进行中幂等写入并回读计划/用例/执行/报告
  complete: 写入测试证据；【测试】处理中→已完成；需求测试中→测试完成

所有写操作均要求先运行 --dry-run，并通过 YunxiaoQA Plan 门禁确认。
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _auth import (  # noqa: E402
    AuthError,
    brief_item,
    document_content,
    find_by_serial,
    get_workitem,
    list_associated,
    list_parent_sub,
    resolve_next_status_id,
    session,
    set_document_checked,
    space_id,
    transit,
)
from close_test_task import bug_status_name, is_bug_item  # noqa: E402

TEST_PREFIX = "【测试】"
DELIVERY_PREFIX = "【交付】"
BLOCK_START = "<!-- YUNXIAOQA_TEST_EVIDENCE_START -->"
BLOCK_END = "<!-- YUNXIAOQA_TEST_EVIDENCE_END -->"
DEPLOY_START = "<!-- ONEOS_TEST_DEPLOYMENT_EVIDENCE_START -->"
DEPLOY_END = "<!-- ONEOS_TEST_DEPLOYMENT_EVIDENCE_END -->"
QA_SCHEMA = "oneos.qa-evidence/v1"
DEPLOY_SCHEMA = "oneos.test-deployment/v1"
SKIP_PIPELINE_ENDS = {"小程序"}
BUG_RETEST_START = "<!-- YUNXIAOQA_BUG_RETEST_EVIDENCE_START -->"
BUG_RETEST_END = "<!-- YUNXIAOQA_BUG_RETEST_EVIDENCE_END -->"
BUG_RETEST_SCHEMA = "oneos.bug-retest/v1"
ACTION_STATES = {
    "start": ("待处理", "处理中", "待测试", "测试中"),
    "complete": ("处理中", "已完成", "测试中", "测试完成"),
}


def same_serial(left: object, right: object) -> bool:
    def bare(value: object) -> str:
        text = str(value or "").strip().upper()
        return text.split("-")[-1] if "-" in text else text

    return bool(bare(left)) and bare(left) == bare(right)


def exact_item(s, space: str, category: str, serial: str) -> dict[str, Any]:
    item = find_by_serial(s, space=space, category=category, serial=serial)
    if not item:
        raise RuntimeError(f"未找到 {category} 编号 {serial}")
    full = get_workitem(s, str(item["identifier"]))
    meta = brief_item(full)
    if not same_serial(meta.get("serialNumber"), serial):
        raise RuntimeError(
            f"编号门禁失败：请求 {serial}，实际 {meta.get('serialNumber')}"
        )
    return full


def relation_ids(s, workitem_id: str, category: str) -> set[str]:
    result: set[str] = set()
    getter = list_associated if category == "ASSOCIATED" else list_parent_sub
    for forward in (True, False):
        for item in getter(s, workitem_id, forward=forward):
            if item.get("identifier"):
                result.add(str(item["identifier"]))
    return result


def resolve_context(
    s, space: str, test_sn: str, req_sn: str | None
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    test = exact_item(s, space, "Task", test_sn)
    test_meta = brief_item(test)
    if not str(test_meta.get("subject") or "").startswith(TEST_PREFIX):
        raise RuntimeError(f"{test_sn} 不是以「{TEST_PREFIX}」开头的测试任务")

    parents = list_parent_sub(s, str(test_meta["id"]), forward=False)
    deliveries = [
        item
        for item in parents
        if str(item.get("subject") or "").startswith(DELIVERY_PREFIX)
    ]
    if len(deliveries) != 1:
        raise RuntimeError(
            f"关系门禁失败：{test_sn} 的正式父【交付】唯一命中数={len(deliveries)}"
        )
    delivery = brief_item(
        get_workitem(s, str(deliveries[0]["identifier"]))
    )

    associated_ids = relation_ids(s, str(test_meta["id"]), "ASSOCIATED")
    if req_sn:
        req = exact_item(s, space, "Req", req_sn)
        if str(req["identifier"]) not in associated_ids:
            raise RuntimeError(
                f"关系门禁失败：{test_sn} 未正式 ASSOCIATED→{req_sn}"
            )
    else:
        candidates: list[dict[str, Any]] = []
        for workitem_id in associated_ids:
            try:
                item = get_workitem(s, workitem_id)
            except Exception:
                continue
            category = str(
                item.get("category") or item.get("categoryIdentifier") or ""
            ).lower()
            type_text = json.dumps(item.get("workitemType") or {}, ensure_ascii=False)
            if category in {"req", "requirement"} or "需求" in type_text:
                candidates.append(item)
        if len(candidates) != 1:
            raise RuntimeError(
                f"关系门禁失败：{test_sn} 正式关联需求唯一命中数={len(candidates)}；"
                "请显式传 --req-sn"
            )
        req = candidates[0]
    return test, req, delivery


def current_status(item: dict[str, Any]) -> tuple[str, str]:
    meta = brief_item(item)
    name = str(meta.get("status") or "")
    identifier = str(meta.get("statusId") or "")
    if not name or not identifier:
        raise RuntimeError(
            f"{meta.get('serialNumber')} 状态名称或 identifier 为空，拒绝写入"
        )
    return name, identifier


def transition_plan(
    s,
    item: dict[str, Any],
    expected_from: str,
    target: str,
) -> dict[str, Any]:
    meta = brief_item(item)
    name, identifier = current_status(item)
    if name == target:
        target_id = identifier
        already_done = True
    elif name != expected_from:
        raise RuntimeError(
            f"{meta.get('serialNumber')} 当前状态「{name}」，期望源状态"
            f"「{expected_from}」或目标状态「{target}」"
        )
    else:
        target_id = resolve_next_status_id(
            s, str(meta["id"]), identifier, target
        )
        already_done = False
    return {
        "id": str(meta["id"]),
        "serialNumber": str(meta.get("serialNumber") or ""),
        "subject": str(meta.get("subject") or ""),
        "from": name,
        "fromId": identifier,
        "to": target,
        "toId": target_id,
        "alreadyDone": already_done,
    }


def build_transition_plans(
    s,
    action: str,
    test: dict[str, Any],
    req: dict[str, Any],
) -> list[dict[str, Any]]:
    """按测试任务→需求的固定顺序生成状态计划；不推进父【交付】。"""
    test_from, test_to, req_from, req_to = ACTION_STATES[action]
    return [
        transition_plan(s, test, test_from, test_to),
        transition_plan(s, req, req_from, req_to),
    ]


def collect_bugs(
    s, test_id: str, deployed_version: str, *, match_version: bool = True
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    bugs: list[dict[str, Any]] = []
    for getter, forward in (
        (list_parent_sub, True),
        (list_associated, True),
        (list_associated, False),
    ):
        for relation_item in getter(s, test_id, forward=forward):
            workitem_id = str(relation_item.get("identifier") or "")
            if not workitem_id or workitem_id in seen:
                continue
            seen.add(workitem_id)
            item = relation_item
            if not bug_status_name(item):
                item = get_workitem(s, workitem_id)
            if not is_bug_item(item):
                continue
            full = get_workitem(s, workitem_id)
            meta = brief_item(full)
            bug_state = bug_status_name(full)
            retest_valid = False
            retest_key = ""
            retest_version = ""
            if bug_state == "已关闭":
                try:
                    retest = parse_json_block(
                        document_content(full), BUG_RETEST_START, BUG_RETEST_END
                    )
                    retest_key = str(retest.get("idempotencyKey") or "")
                    retest_version = str(retest.get("deployedVersion") or "")
                    retest_valid = (
                        retest.get("schemaVersion") == BUG_RETEST_SCHEMA
                        and str(retest.get("result") or "").lower() == "passed"
                        and str(retest.get("environment") or "").lower() == "test"
                        and (
                            retest_version == str(deployed_version)
                            if match_version
                            else True
                        )
                        and all(
                            valid_ref(retest.get(field))
                            for field in (
                                "caseId",
                                "testExecutionId",
                                "evidence",
                                "deployedVersion",
                                "verifiedBy",
                                "verifiedAt",
                                "idempotencyKey",
                            )
                        )
                    )
                except (RuntimeError, ValueError, json.JSONDecodeError):
                    retest_valid = False
            bugs.append(
                {
                    "id": workitem_id,
                    "serialNumber": str(meta.get("serialNumber") or ""),
                    "subject": str(meta.get("subject") or ""),
                    "status": bug_state,
                    "retestEvidenceValid": retest_valid,
                    "retestDeployedVersion": retest_version,
                    "retestIdempotencyKey": retest_key,
                }
            )
    return bugs


def parse_approvals(values: list[str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for raw in values:
        bug, separator, detail = raw.partition("=")
        approver, pipe, evidence = detail.partition("|")
        key = bug.strip().upper()
        if not separator or not pipe or not key or not approver.strip() or not evidence.strip():
            raise RuntimeError(
                f"暂不修复批准格式错误：{raw!r}；应为 BUG-ID=批准人|批准记录ID或URL"
            )
        result[key] = {
            "approver": approver.strip(),
            "evidence": evidence.strip(),
        }
    return result


def parse_json_block(content: str, start_marker: str, end_marker: str) -> dict[str, Any]:
    start = content.find(start_marker)
    end = content.find(end_marker)
    if start < 0 or end <= start:
        raise RuntimeError(f"缺少受管证据区块：{start_marker}")
    fragment = html.unescape(content[start + len(start_marker) : end])
    left = fragment.find("{")
    right = fragment.rfind("}")
    if left < 0 or right <= left:
        raise RuntimeError(f"受管证据区块缺JSON对象：{start_marker}")
    value = json.loads(fragment[left : right + 1])
    if not isinstance(value, dict):
        raise RuntimeError("受管证据JSON必须是对象")
    return value


def valid_ref(value: object) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.lower() not in {"none", "null", "n/a", "无", "..."} and not (
        "<" in text or ">" in text
    )


def is_skip_deployment(value: dict[str, Any]) -> bool:
    return str(value.get("testPipeline") or "").lower() == "skipped"


def test_deployment_evidence(
    test: dict[str, Any], req_meta: dict[str, Any], test_meta: dict[str, Any], space: str
) -> dict[str, Any]:
    data = parse_json_block(document_content(test), DEPLOY_START, DEPLOY_END)
    skipped = is_skip_deployment(data)
    required = {
        "schemaVersion",
        "projectId",
        "iterationId",
        "iterationName",
        "requirementId",
        "testTaskId",
        "status",
        "completedAt",
        "idempotencyKey",
    }
    required |= (
        {"deliveryEnd", "testPipeline", "reason"}
        if skipped
        else {"executionId", "environment", "deployedVersion", "evidenceUrl"}
    )
    missing = sorted(required - set(data))
    if missing:
        raise RuntimeError(f"test部署证据缺字段：{missing}")
    if data["schemaVersion"] != DEPLOY_SCHEMA:
        raise RuntimeError(f"test部署证据schema无效：{data['schemaVersion']}")
    if str(data["projectId"]) != space:
        raise RuntimeError("test部署证据项目与测试任务项目不一致")
    if str(data["requirementId"]) not in {
        str(req_meta.get("id") or ""),
        str(req_meta.get("serialNumber") or ""),
    }:
        raise RuntimeError("test部署证据需求与正式关联需求不一致")
    if str(data["testTaskId"]) not in {
        str(test_meta.get("id") or ""),
        str(test_meta.get("serialNumber") or ""),
    }:
        raise RuntimeError("test部署证据测试任务编号不一致")
    if skipped:
        if str(data["deliveryEnd"]) not in SKIP_PIPELINE_ENDS:
            raise RuntimeError("只有小程序交付允许跳过test流水线")
        if str(data["status"]).lower() not in {"skipped", "跳过", "已跳过"}:
            raise RuntimeError("跳过区块status必须标记为skipped")
        fields = (
            "iterationId",
            "iterationName",
            "reason",
            "completedAt",
            "idempotencyKey",
        )
    else:
        if str(data["environment"]).lower() != "test" or str(
            data["status"]
        ).lower() not in {
            "成功",
            "success",
            "succeeded",
        }:
            raise RuntimeError("正常需求提测前必须有成功的test环境部署")
        fields = (
            "iterationId",
            "iterationName",
            "executionId",
            "deployedVersion",
            "evidenceUrl",
            "completedAt",
            "idempotencyKey",
        )
    for field in fields:
        if not valid_ref(data[field]):
            raise RuntimeError(f"test部署证据字段无效：{field}")
    return data


def load_evidence_manifest(
    path: str,
    *,
    space: str,
    req_meta: dict[str, Any],
    test_meta: dict[str, Any],
    deployment: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    manifest_path = Path(path).resolve()
    if not manifest_path.is_file():
        raise RuntimeError(f"测试证据清单不存在：{manifest_path}")
    raw = manifest_path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or data.get("schemaVersion") != QA_SCHEMA:
        raise RuntimeError(f"测试证据清单必须使用{QA_SCHEMA}")
    required = {
        "projectId",
        "iterationId",
        "iterationName",
        "requirementId",
        "testTaskId",
        "testPlan",
        "caseRun",
        "report",
        "testDeployment",
        "collectedAt",
    }
    missing = sorted(required - set(data))
    if missing:
        raise RuntimeError(f"测试证据清单缺字段：{missing}")
    if str(data["projectId"]) != space:
        raise RuntimeError("测试证据项目不一致")
    if str(data["requirementId"]) not in {
        str(req_meta.get("id") or ""),
        str(req_meta.get("serialNumber") or ""),
    }:
        raise RuntimeError("测试证据需求不一致")
    if str(data["testTaskId"]) not in {
        str(test_meta.get("id") or ""),
        str(test_meta.get("serialNumber") or ""),
    }:
        raise RuntimeError("测试证据测试任务不一致")
    if str(data["iterationId"]) != str(deployment["iterationId"]):
        raise RuntimeError("测试证据迭代与提测部署迭代不一致")
    if str(data["iterationName"]) != str(deployment["iterationName"]):
        raise RuntimeError("测试证据迭代名称与提测部署不一致")
    deployed = data.get("testDeployment")
    if not isinstance(deployed, dict):
        raise RuntimeError("测试证据清单testDeployment必须是对象")
    if is_skip_deployment(deployment):
        if not is_skip_deployment(deployed) or str(
            deployed.get("deliveryEnd") or ""
        ) != str(deployment["deliveryEnd"]):
            raise RuntimeError(
                "小程序跳过test流水线时，清单testDeployment必须写deliveryEnd与testPipeline=skipped"
            )
    else:
        for field in ("executionId", "deployedVersion", "evidenceUrl"):
            if str(deployed.get(field) or "") != str(deployment[field]):
                raise RuntimeError(f"测试证据清单与提测部署字段不一致：{field}")
    plan = data.get("testPlan")
    run = data.get("caseRun")
    report = data.get("report")
    if not all(isinstance(value, dict) for value in (plan, run, report)):
        raise RuntimeError("testPlan、caseRun、report必须是对象")
    for label, value in (("测试计划", plan), ("用例执行", run), ("测试报告", report)):
        if not valid_ref(value.get("id")) or not valid_ref(value.get("url")):
            raise RuntimeError(f"{label}必须同时提供真实ID和URL")
    counts = {name: int(run.get(name, -1)) for name in ("total", "passed", "failed", "blocked", "unexecuted")}
    if any(value < 0 for value in counts.values()):
        raise RuntimeError("用例执行计数缺失或小于0")
    if counts["total"] != counts["passed"] + counts["failed"] + counts["blocked"] + counts["unexecuted"]:
        raise RuntimeError("用例执行计数无法闭合")
    if str(run.get("status") or "").lower() not in {"completed", "完成", "已完成"}:
        raise RuntimeError("用例执行记录尚未完成")
    data["caseCounts"] = counts
    digest = hashlib.sha256(raw).hexdigest()
    data["manifestPath"] = str(manifest_path)
    data["manifestSha256"] = digest
    return data, digest


def replace_managed_block(original: str, block: str) -> str:
    start = original.find(BLOCK_START)
    end = original.find(BLOCK_END)
    if start >= 0 and end >= start:
        end += len(BLOCK_END)
        return original[:start] + block + original[end:]
    separator = "" if not original.strip() else "\n"
    return original + separator + block


def evidence_block(
    evidence: dict[str, Any],
    approvals: dict[str, dict[str, str]],
    bugs: list[dict[str, Any]],
    key: str,
) -> str:
    completed_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    bug_snapshot = [
        {
            "id": bug["id"],
            "serialNumber": bug["serialNumber"],
            "status": bug["status"],
            "retestDeployedVersion": bug["retestDeployedVersion"],
            "retestIdempotencyKey": bug["retestIdempotencyKey"],
        }
        for bug in sorted(bugs, key=lambda value: str(value["id"]))
    ]
    bug_snapshot_sha256 = hashlib.sha256(
        json.dumps(bug_snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    payload = {
        "schemaVersion": QA_SCHEMA,
        "sourceVerified": True,
        "projectId": evidence["projectId"],
        "iterationId": evidence["iterationId"],
        "iterationName": evidence["iterationName"],
        "requirementId": evidence["requirementId"],
        "testTaskId": evidence["testTaskId"],
        "testPlan": evidence["testPlan"],
        "caseRun": evidence["caseRun"],
        "caseCounts": evidence["caseCounts"],
        "report": evidence["report"],
        "testDeployment": evidence["testDeployment"],
        "bugSnapshot": bug_snapshot,
        "bugSnapshotSha256": bug_snapshot_sha256,
        "riskApprovals": approvals,
        "manifestSha256": evidence["manifestSha256"],
        "completedAt": completed_at,
        "idempotencyKey": key,
    }
    return (
        f"{BLOCK_START}<h2>测试执行证据（YunxiaoQA）</h2><pre>"
        + html.escape(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        + f"</pre>{BLOCK_END}"
    )


def readback(s, plan: dict[str, str]) -> dict[str, Any]:
    after = brief_item(get_workitem(s, plan["id"]))
    if not same_serial(after.get("serialNumber"), plan["serialNumber"]):
        raise RuntimeError(
            f"编号回读失败：期望 {plan['serialNumber']}，实际 {after.get('serialNumber')}"
        )
    if after.get("status") != plan["to"]:
        raise RuntimeError(
            f"状态回读失败：{plan['serialNumber']} 期望 {plan['to']}，"
            f"实际 {after.get('status')}"
        )
    return after


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--test-sn", required=True)
    parser.add_argument("--req-sn")
    parser.add_argument("--space")
    parser.add_argument("--dry-run", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="推进测试任务与需求的测试阶段状态")
    subs = parser.add_subparsers(dest="action", required=True)
    start = subs.add_parser("start", help="开始测试")
    add_common(start)
    record = subs.add_parser("record", help="记录并回读测试证据")
    add_common(record)
    complete = subs.add_parser("complete", help="完成测试并写入证据")
    add_common(complete)
    for target in (record, complete):
        target.add_argument("--evidence-manifest", required=True)
        target.add_argument("--risk-approval", action="append", default=[])
    return parser


def main() -> None:
    args = build_parser().parse_args()
    space = space_id(args.space)
    try:
        s = session()
        test, req, delivery = resolve_context(
            s, space, args.test_sn.strip(), args.req_sn.strip() if args.req_sn else None
        )
        test_meta = brief_item(test)
        req_meta = brief_item(req)
        deployment = test_deployment_evidence(test, req_meta, test_meta, space)
        evidence: dict[str, Any] | None = None
        evidence_digest = ""
        if args.action in {"record", "complete"}:
            evidence, evidence_digest = load_evidence_manifest(
                args.evidence_manifest,
                space=space,
                req_meta=req_meta,
                test_meta=test_meta,
                deployment=deployment,
            )
        if args.action == "record":
            if test_meta.get("status") != "处理中" or req_meta.get("status") != "测试中":
                raise RuntimeError(
                    "记录证据门禁失败：要求【测试】=处理中且需求=测试中"
                )
            approvals = parse_approvals(args.risk_approval)
            bugs = collect_bugs(
                s,
                str(test_meta["id"]),
                str(deployment.get("deployedVersion") or ""),
                match_version=not is_skip_deployment(deployment),
            )
            key_source = "|".join(
                [
                    space,
                    str(req_meta["id"]),
                    str(test_meta["id"]),
                    evidence_digest,
                ]
            )
            key = "qa-" + hashlib.sha256(key_source.encode("utf-8")).hexdigest()[:20]
            assert evidence is not None
            block = evidence_block(evidence, approvals, bugs, key)
            record_output = {
                "ok": True,
                "dryRun": args.dry_run,
                "action": "record",
                "test": test_meta,
                "requirement": req_meta,
                "delivery": delivery,
                "bugsSnapshot": bugs,
                "caseCounts": evidence["caseCounts"],
                "testDeployment": deployment,
                "evidenceManifestSha256": evidence_digest,
                "evidenceIdempotencyKey": key,
            }
            if args.dry_run:
                print(json.dumps(record_output, ensure_ascii=False, indent=2))
                return
            set_document_checked(
                s,
                str(test_meta["id"]),
                replace_managed_block(document_content(test), block),
            )
            reread_document = document_content(
                get_workitem(s, str(test_meta["id"]))
            )
            if (
                BLOCK_START not in reread_document
                or BLOCK_END not in reread_document
                or key not in reread_document
            ):
                raise RuntimeError("测试证据写入后回读失败")
            print(json.dumps(record_output | {"dryRun": False}, ensure_ascii=False, indent=2))
            return

        test_from, test_to, req_from, req_to = ACTION_STATES[args.action]

        if test_meta.get("status") == test_to and req_meta.get("status") == req_to:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "alreadyDone": True,
                        "test": test_meta,
                        "requirement": req_meta,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return

        test_plan, req_plan = build_transition_plans(s, args.action, test, req)
        output: dict[str, Any] = {
            "ok": True,
            "dryRun": args.dry_run,
            "action": args.action,
            "delivery": delivery,
            "wouldTransit": [test_plan, req_plan],
        }

        block = ""
        bugs: list[dict[str, str]] = []
        approvals: dict[str, dict[str, str]] = {}
        if args.action == "complete":
            assert evidence is not None
            counts = evidence["caseCounts"]
            if any(counts[name] for name in ("unexecuted", "failed", "blocked")):
                raise RuntimeError(
                    "测试门禁失败：未执行/失败/阻塞用例必须全部为 0"
                )
            approvals = parse_approvals(args.risk_approval)
            bugs = collect_bugs(
                s,
                test_plan["id"],
                str(deployment.get("deployedVersion") or ""),
                match_version=not is_skip_deployment(deployment),
            )
            active = [
                bug
                for bug in bugs
                if bug["status"] not in {"已关闭", "暂不修复"}
            ]
            missing = [
                bug
                for bug in bugs
                if bug["status"] == "暂不修复"
                and bug["serialNumber"].upper() not in approvals
            ]
            extra = sorted(
                set(approvals)
                - {
                    bug["serialNumber"].upper()
                    for bug in bugs
                    if bug["status"] == "暂不修复"
                }
            )
            closed_without_retest = [
                bug
                for bug in bugs
                if bug["status"] == "已关闭" and not bug["retestEvidenceValid"]
            ]
            if active or missing or extra or closed_without_retest:
                raise RuntimeError(
                    "缺陷门禁失败："
                    + json.dumps(
                        {
                            "active": active,
                            "wontFixWithoutApproval": missing,
                            "approvalWithoutWontFixBug": extra,
                            "closedWithoutPerBugRetestEvidence": closed_without_retest,
                        },
                        ensure_ascii=False,
                    )
                )
            key_source = "|".join(
                [
                    space,
                    str(req_plan["id"]),
                    str(test_plan["id"]),
                    evidence_digest,
                ]
            )
            key = "qa-" + hashlib.sha256(key_source.encode("utf-8")).hexdigest()[:20]
            block = evidence_block(evidence, approvals, bugs, key)
            output.update(
                {
                "bugs": bugs,
                "testEvidence": {
                    "plan": evidence["testPlan"],
                    "caseRun": evidence["caseRun"],
                    "report": evidence["report"],
                    "testDeployment": evidence["testDeployment"],
                    "manifestSha256": evidence_digest,
                },
                "evidenceIdempotencyKey": key,
                    "evidenceWillBeWritten": True,
                }
            )

        if args.dry_run:
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return

        if args.action == "complete":
            original = document_content(test)
            set_document_checked(
                s,
                test_plan["id"],
                replace_managed_block(original, block),
            )
            reread_document = document_content(get_workitem(s, test_plan["id"]))
            if BLOCK_START not in reread_document or BLOCK_END not in reread_document:
                raise RuntimeError("测试证据写入后回读失败；状态尚未推进")

        if not test_plan["alreadyDone"]:
            transit(
                s,
                test_plan["id"],
                test_plan["fromId"],
                test_plan["toId"],
            )
        test_after = readback(s, test_plan)
        try:
            if not req_plan["alreadyDone"]:
                transit(
                    s,
                    req_plan["id"],
                    req_plan["fromId"],
                    req_plan["toId"],
                )
            req_after = readback(s, req_plan)
        except Exception as error:
            raise RuntimeError(
                f"需求状态推进失败；测试任务已到 {test_after.get('status')}，"
                f"必须人工审计后再处理：{error}"
            ) from error

        output["after"] = {
            "test": test_after,
            "requirement": req_after,
        }
        if args.action == "complete":
            output["handoff"] = {
                "sourceSkill": "YunxiaoQA",
                "targetSkill": "yunxiao-release-operations",
                "requirement": req_after,
                "testTask": test_after,
                "deliveryTask": delivery,
                "iteration": {
                    "id": deployment["iterationId"],
                    "name": deployment["iterationName"],
                },
                "bugs": bugs,
                "testEvidence": output["testEvidence"],
                "evidenceIdempotencyKey": output["evidenceIdempotencyKey"],
                "allowedNextAction": "组建发布批次",
                "nextCommand": (
                    "组建发布批次：迭代=<名称>；需求="
                    + str(req_after.get("serialNumber") or args.req_sn or "")
                ),
            }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except AuthError as error:
        print(
            json.dumps(
                {"ok": False, "error": "auth", "message": str(error)},
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(2) from error
    except (RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {"ok": False, "error": "gate", "message": str(error)},
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(3) from error


if __name__ == "__main__":
    main()
