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

import yunxiao_cli_req_test_complete as req_complete  # noqa: E402


class RequirementTestCompleteTests(unittest.TestCase):
    @staticmethod
    def items(marker: str) -> tuple[dict, dict, dict]:
        test = {
            "id": "test-1", "serialNumber": "ONEOS-703",
            "subject": f"【测试】{marker}任务",
            "status": {"displayName": "已完成"},
        }
        req = {
            "id": "req-1", "serialNumber": "ONEOS-698",
            "subject": f"{marker}需求",
            "status": {"displayName": "测试中"},
        }
        parent = {
            "id": "delivery-1", "serialNumber": "ONEOS-699",
            "subject": f"【交付】{marker}任务",
            "status": {"displayName": "处理中"},
            "sprint": {"id": "sprint-1", "name": "OneOS_web端V1.4.9"},
        }
        return test, req, parent

    def run_preflight(self, marker: str, test_plan_id: str | None) -> tuple[dict, object, object]:
        test, req, parent = self.items(marker)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        output = Path(folder.name) / "receipt.json"
        args = argparse.Namespace(
            space_id="project", test_sn="ONEOS-703", req_sn="ONEOS-698",
            test_plan_id=test_plan_id, risk_approval=[],
            idempotency_key="qa-ONEOS-703", output=output, apply=False,
        )
        comment = patch.object(
            req_complete, "require_latest_pass_comment",
            return_value={"id": "comment-1", "content": "测试结果：通过"},
        )
        testhub = patch.object(
            req_complete, "validate_test_plan_complete",
            return_value={"planId": "plan-1", "caseCounts": {"total": 2}},
        )
        with patch.object(req_complete.core, "find_aliyun", return_value="aliyun"), \
                patch.object(req_complete.core, "require_auth_env", return_value={"organizationId": "org"}), \
                patch.object(req_complete, "exact_workitem", return_value=test), \
                patch.object(req_complete, "relation_ids", side_effect=[["req-1"], ["delivery-1"]]), \
                patch.object(req_complete, "resolve_requirement", return_value=req), \
                patch.object(req_complete, "get_workitem", return_value=parent), \
                patch.object(req_complete, "collect_bugs", return_value=[]), \
                comment as comment_mock, testhub as testhub_mock:
            result = req_complete.run(args)
        self.assertEqual(result, 0)
        return json.loads(output.read_text(encoding="utf-8")), comment_mock, testhub_mock

    def test_optimization_requirement_completion_requires_pass_comment(self) -> None:
        receipt, comment, testhub = self.run_preflight("【优化】", None)
        self.assertEqual(receipt["taskFlow"], "optimization")
        self.assertEqual(receipt["passComment"]["id"], "comment-1")
        comment.assert_called_once_with("aliyun", "test-1")
        testhub.assert_not_called()

    def test_new_requirement_completion_requires_testhub(self) -> None:
        receipt, comment, testhub = self.run_preflight("【新增】", "plan-1")
        self.assertEqual(receipt["taskFlow"], "new")
        self.assertEqual(receipt["testPlan"]["planId"], "plan-1")
        comment.assert_not_called()
        testhub.assert_called_once_with("aliyun", "plan-1")


if __name__ == "__main__":
    unittest.main()
