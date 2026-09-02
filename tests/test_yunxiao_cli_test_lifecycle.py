from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import yunxiao_cli_test_lifecycle as lifecycle  # noqa: E402


class YunxiaoCliTestLifecycleTests(unittest.TestCase):
    def test_requirement_is_inferred_from_unique_associated_id(self) -> None:
        row = {"id": "req-1", "serialNumber": "ONEOS-500"}
        detail = {**row, "subject": "需求", "status": {"displayName": "待测试"}}
        with patch.object(lifecycle, "search_workitems", return_value=[row]), \
                patch.object(lifecycle, "get_workitem", return_value=detail) as getter:
            result = lifecycle.resolve_requirement("aliyun", "project", ["req-1"])
        self.assertEqual(result["serialNumber"], "ONEOS-500")
        getter.assert_called_once_with("aliyun", "req-1")

    def test_explicit_requirement_must_be_formally_associated(self) -> None:
        detail = {"id": "req-1", "serialNumber": "ONEOS-500"}
        with patch.object(lifecycle, "exact_workitem", return_value=detail):
            with self.assertRaisesRegex(lifecycle.core.AdapterError, "不是测试任务的正式ASSOCIATED需求"):
                lifecycle.resolve_requirement("aliyun", "project", ["req-2"], "ONEOS-500")

    def test_start_preflight_does_not_require_deployment_evidence(self) -> None:
        test = {
            "id": "test-1", "serialNumber": "ONEOS-598", "subject": "【测试】云打印",
            "status": {"displayName": "待处理"},
        }
        req = {
            "id": "req-1", "serialNumber": "ONEOS-500", "subject": "云打印",
            "status": {"displayName": "待测试"},
        }
        parent = {
            "id": "delivery-1", "serialNumber": "ONEOS-590", "subject": "【交付】云打印",
            "status": {"displayName": "已完成"},
        }
        with tempfile.TemporaryDirectory() as folder:
            args = argparse.Namespace(
                command="start", space_id="project", test_sn="ONEOS-598", req_sn=None,
                evidence_manifest=None, deployment_evidence=None, risk_approval=[],
                idempotency_key="qa-start-ONEOS-598", apply=False,
                output=str(Path(folder) / "receipt.json"),
            )
            with patch.object(lifecycle.core, "find_aliyun", return_value="aliyun"), \
                    patch.object(lifecycle.core, "require_auth_env", return_value={"organizationId": "org"}), \
                    patch.object(lifecycle, "exact_workitem", return_value=test), \
                    patch.object(lifecycle, "relation_ids", side_effect=[["delivery-1"], ["req-1"]]), \
                    patch.object(lifecycle, "resolve_requirement", return_value=req), \
                    patch.object(lifecycle, "get_workitem", return_value=parent), \
                    patch.object(lifecycle, "validate_deployment") as validator:
                result = lifecycle.run(args)
        self.assertEqual(result, 0)
        self.assertEqual(args.req_sn, "ONEOS-500")
        validator.assert_not_called()

    def test_test_plan_complete_uses_live_progress_without_manifest_or_report(self) -> None:
        progress = {
            "paasCount": 3, "failureCount": 0,
            "postponeCount": 0, "todoCount": 0,
        }
        with patch.object(lifecycle.core, "run_devops", return_value=progress):
            result = lifecycle.validate_test_plan_complete("aliyun", "plan-1")
        self.assertEqual(result["planId"], "plan-1")
        self.assertEqual(result["caseCounts"], {
            "passed": 3, "failed": 0, "blocked": 0,
            "unexecuted": 0, "total": 3,
        })

    def test_test_plan_complete_rejects_nonpassing_counts(self) -> None:
        for field in ("failureCount", "postponeCount", "todoCount"):
            with self.subTest(field=field):
                progress = {
                    "paasCount": 2, "failureCount": 0,
                    "postponeCount": 0, "todoCount": 0,
                }
                progress[field] = 1
                with patch.object(lifecycle.core, "run_devops", return_value=progress):
                    with self.assertRaisesRegex(
                            lifecycle.core.AdapterError, "尚未全量通过"):
                        lifecycle.validate_test_plan_complete("aliyun", "plan-1")

    def test_complete_preflight_needs_testhub_and_defect_gates_only(self) -> None:
        test = {
            "id": "test-1", "serialNumber": "ONEOS-703",
            "subject": "【测试】任务", "status": {"displayName": "处理中"},
        }
        req = {
            "id": "req-1", "serialNumber": "ONEOS-698",
            "subject": "需求", "status": {"displayName": "测试中"},
        }
        parent = {
            "id": "delivery-1", "serialNumber": "ONEOS-699",
            "subject": "【交付】任务", "status": {"displayName": "处理中"},
            "sprint": {"id": "sprint-1", "name": "OneOS_web端V1.4.9"},
        }
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "receipt.json"
            args = argparse.Namespace(
                command="complete", space_id="project", test_sn="ONEOS-703",
                req_sn="ONEOS-698", evidence_manifest=None,
                deployment_evidence=None, test_plan_id="plan-1",
                risk_approval=[], manual_verdict=None,
                idempotency_key="qa-ONEOS-703", apply=False,
                output=str(output),
            )
            with patch.object(lifecycle.core, "find_aliyun", return_value="aliyun"), \
                    patch.object(lifecycle.core, "require_auth_env", return_value={"organizationId": "org"}), \
                    patch.object(lifecycle, "exact_workitem", return_value=test), \
                    patch.object(lifecycle, "relation_ids", side_effect=[["delivery-1"], ["req-1"]]), \
                    patch.object(lifecycle, "resolve_requirement", return_value=req), \
                    patch.object(lifecycle, "get_workitem", return_value=parent), \
                    patch.object(lifecycle, "validate_test_plan_complete", return_value={
                        "planId": "plan-1", "caseCounts": {
                            "passed": 2, "failed": 0, "blocked": 0,
                            "unexecuted": 0, "total": 2,
                        },
                    }), \
                    patch.object(lifecycle, "collect_bugs", return_value=[]), \
                    patch.object(lifecycle, "validate_deployment") as deployment, \
                    patch.object(lifecycle, "load_manifest") as manifest:
                result = lifecycle.run(args)
            receipt = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result, 0)
        self.assertEqual(receipt["evidenceMode"], "testhub-and-defect-gates")
        self.assertNotIn("deployment", receipt)
        self.assertNotIn("report", receipt)
        self.assertNotIn("manifestSha256", receipt)
        deployment.assert_not_called()
        manifest.assert_not_called()

    def test_deployment_repair_file_is_validated_and_loaded(self) -> None:
        test = {"id": "test-1", "serialNumber": "ONEOS-598"}
        req = {"id": "req-1", "serialNumber": "ONEOS-500"}
        payload = {
            "schemaVersion": lifecycle.DEPLOY_SCHEMA,
            "projectId": "project",
            "iterationId": "iteration-1",
            "iterationName": "Sprint 1",
            "requirementId": "ONEOS-500",
            "testTaskId": "ONEOS-598",
            "status": "success",
            "completedAt": "2026-08-19T09:32:50+08:00",
            "idempotencyKey": "deploy-ONEOS-598",
            "executionId": "pipeline-1#1",
            "environment": "test",
            "deployedVersion": "abcdef12",
            "evidenceUrl": "https://example.test/pipelines/1/runs/1",
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "deployment.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = lifecycle.load_deployment_repair(
                str(path), test, req, "project",
            )
        self.assertEqual(result, payload)

    def test_manual_complete_preflight_skips_evidence_but_keeps_relations(self) -> None:
        test = {
            "id": "test-1", "serialNumber": "ONEOS-703",
            "subject": "【测试】【优化】租赁合同流程优化",
            "status": {"displayName": "处理中"},
        }
        req = {
            "id": "req-1", "serialNumber": "ONEOS-698",
            "subject": "【优化】租赁合同流程优化",
            "status": {"displayName": "测试中"},
        }
        parent = {
            "id": "delivery-1", "serialNumber": "ONEOS-699",
            "subject": "【交付】【优化】租赁合同流程优化",
            "status": {"displayName": "处理中"},
        }
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "receipt.json"
            args = argparse.Namespace(
                command="manual-complete", space_id="project",
                test_sn="ONEOS-703", req_sn="ONEOS-698",
                evidence_manifest=None, deployment_evidence=None,
                risk_approval=[], manual_verdict="passed",
                idempotency_key="qa-manual-ONEOS-703", apply=False,
                output=str(output),
            )
            with patch.object(lifecycle.core, "find_aliyun", return_value="aliyun"), \
                    patch.object(lifecycle.core, "require_auth_env", return_value={"organizationId": "org"}), \
                    patch.object(lifecycle, "exact_workitem", return_value=test), \
                    patch.object(lifecycle, "relation_ids", side_effect=[["delivery-1"], ["req-1"]]), \
                    patch.object(lifecycle, "resolve_requirement", return_value=req), \
                    patch.object(lifecycle, "get_workitem", return_value=parent), \
                    patch.object(lifecycle, "collect_bugs", return_value=[]):
                result = lifecycle.run(args)
            receipt = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result, 0)
        self.assertEqual(receipt["evidenceMode"], "human-confirmed")
        self.assertFalse(receipt["releaseCandidateEligible"])
        self.assertEqual(
            [action["status"] for action in receipt["plannedActions"]],
            ["已完成", "测试完成"],
        )
        self.assertNotIn("deployment", receipt)
        self.assertNotIn("manifestSha256", receipt)

    def test_manual_complete_apply_repairs_intermediate_requirement_state(self) -> None:
        test = {
            "id": "test-1", "serialNumber": "ONEOS-703",
            "subject": "【测试】【优化】租赁合同流程优化",
            "status": {"displayName": "处理中"},
        }
        req = {
            "id": "req-1", "serialNumber": "ONEOS-698",
            "subject": "【优化】租赁合同流程优化",
            "status": {"displayName": "待测试"},
        }
        parent = {
            "id": "delivery-1", "serialNumber": "ONEOS-699",
            "subject": "【交付】【优化】租赁合同流程优化",
            "status": {"displayName": "处理中"},
        }

        def changed(_executable: str, _project: str,
                    item: dict[str, object], target: str) -> dict[str, object]:
            return {**item, "status": {"displayName": target}}

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "receipt.json"
            args = argparse.Namespace(
                command="manual-complete", space_id="project",
                test_sn="ONEOS-703", req_sn="ONEOS-698",
                evidence_manifest=None, deployment_evidence=None,
                risk_approval=[], manual_verdict="passed",
                idempotency_key="qa-manual-ONEOS-703", apply=True,
                output=str(output),
            )
            with patch.object(lifecycle.core, "find_aliyun", return_value="aliyun"), \
                    patch.object(lifecycle.core, "require_auth_env", return_value={"organizationId": "org"}), \
                    patch.object(lifecycle, "exact_workitem", return_value=test), \
                    patch.object(lifecycle, "relation_ids", side_effect=[["delivery-1"], ["req-1"]]), \
                    patch.object(lifecycle, "resolve_requirement", return_value=req), \
                    patch.object(lifecycle, "get_workitem", return_value=parent), \
                    patch.object(lifecycle, "collect_bugs", return_value=[]), \
                    patch.object(lifecycle, "update_status_checked", side_effect=changed) as updater:
                result = lifecycle.run(args)
            receipt = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result, 0)
        self.assertTrue(receipt["verified"])
        self.assertEqual(receipt["after"]["test"]["status"], "已完成")
        self.assertEqual(receipt["after"]["requirement"]["status"], "测试完成")
        self.assertEqual(
            [call.args[3] for call in updater.call_args_list],
            ["测试中", "已完成", "测试完成"],
        )

    def test_manual_complete_rejects_active_bug(self) -> None:
        test = {
            "id": "test-1", "serialNumber": "ONEOS-703", "subject": "【测试】任务",
            "status": {"displayName": "处理中"},
        }
        req = {
            "id": "req-1", "serialNumber": "ONEOS-698", "subject": "需求",
            "status": {"displayName": "测试中"},
        }
        parent = {
            "id": "delivery-1", "serialNumber": "ONEOS-699", "subject": "【交付】任务",
            "status": {"displayName": "处理中"},
        }
        args = argparse.Namespace(
            command="manual-complete", space_id="project", test_sn="ONEOS-703",
            req_sn="ONEOS-698", evidence_manifest=None, deployment_evidence=None,
            risk_approval=[], manual_verdict="passed",
            idempotency_key="qa-manual-ONEOS-703", apply=False, output=None,
        )
        with patch.object(lifecycle.core, "find_aliyun", return_value="aliyun"), \
                patch.object(lifecycle.core, "require_auth_env", return_value={"organizationId": "org"}), \
                patch.object(lifecycle, "exact_workitem", return_value=test), \
                patch.object(lifecycle, "relation_ids", side_effect=[["delivery-1"], ["req-1"]]), \
                patch.object(lifecycle, "resolve_requirement", return_value=req), \
                patch.object(lifecycle, "get_workitem", return_value=parent), \
                patch.object(lifecycle, "collect_bugs", return_value=[{
                    "serialNumber": "ONEOS-704", "subject": "活动缺陷", "status": "已修复",
                }]):
            with self.assertRaisesRegex(lifecycle.core.AdapterError, "activeBugs"):
                lifecycle.run(args)


if __name__ == "__main__":
    unittest.main()
