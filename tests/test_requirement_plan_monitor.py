from __future__ import annotations

import argparse
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import yunxiao_requirement_plan_monitor as monitor  # noqa: E402


class FakeClient:
    def __init__(self, requirements: list[dict[str, object]] | None = None) -> None:
        self.requirements = requirements or []
        self.created: list[dict[str, object]] = []

    def get_project(self, project_id: str) -> dict[str, object]:
        return {"id": project_id, "customCode": "01_ONEOS", "name": "OneOS"}

    def find_member(self, name: str) -> dict[str, object]:
        return {"id": "member-1", "userId": "user-1", "name": name, "status": "ENABLED"}

    def search_requirements(self, project_id: str, marker: str, max_pages: int) -> list[dict[str, object]]:
        return self.requirements

    def list_test_plans(self, project_id: str, sprint_identifier: str, name: str) -> list[dict[str, object]]:
        if self.created:
            return [{"testPlanIdentifier": "plan-1", "name": name}]
        return []

    def create_test_plan(self, body: dict[str, object]) -> dict[str, object]:
        self.created.append(body)
        return {"id": "plan-1"}

    def list_test_repos(self) -> list[dict[str, object]]:
        return [{"testRepoIdentifier": "repo-1", "name": "主用例库"}]

    def search_cases(self, repo_id: str, keyword: str) -> list[dict[str, object]]:
        if keyword == "云打印":
            return [{"id": "case-1", "customCode": "CASE-1", "subject": "云打印正常流程"}]
        return []


def args_for(state: Path, receipt: Path, *, apply: bool = True, bootstrap_existing: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        project_code="01_ONEOS",
        project_id=monitor.DEFAULT_PROJECT_ID,
        manager_name="谢佳伟",
        max_pages=10,
        state_file=state,
        receipt=receipt,
        bootstrap_existing=bootstrap_existing,
        apply=apply,
    )


class RequirementPlanMonitorTests(unittest.TestCase):
    def test_exact_full_width_marker_is_required(self) -> None:
        self.assertTrue(monitor.qualifies("【新增】云打印"))
        self.assertFalse(monitor.qualifies("[新增]云打印"))
        self.assertFalse(monitor.qualifies("新增云打印"))

    def test_plan_name_is_simplified_and_limited(self) -> None:
        name = monitor.normalize_plan_name(" 【新增】  【PC】  云打印能力优化  ")
        self.assertEqual(name, "云打印能力优化")
        self.assertLessEqual(len(monitor.normalize_plan_name("【新增】" + "长" * 100)), 40)

    def test_case_keywords_include_specific_core(self) -> None:
        self.assertEqual(monitor.case_keywords("【新增】支持云打印功能"), ["支持云打印功能", "云打印"])

    def test_plan_range_is_current_day_plus_fourteen(self) -> None:
        self.assertEqual(monitor.plan_dates(date(2026, 8, 19)), ("2026-08-19", "2026-09-02"))

    def test_missing_sprint_blocks_without_create(self) -> None:
        client = FakeClient()
        result = monitor.process_requirement(
            client,
            {"id": "req-1", "serialNumber": "ONEOS-1", "subject": "【新增】云打印"},
            project_id=monitor.DEFAULT_PROJECT_ID,
            manager_id="user-1",
            apply=True,
        )
        self.assertEqual(result["status"], "pending")
        self.assertEqual(client.created, [])

    def test_apply_creates_plan_and_stops_at_case_confirmation(self) -> None:
        client = FakeClient()
        requirement = {
            "id": "req-1",
            "serialNumber": "ONEOS-1",
            "subject": "【新增】支持云打印功能",
            "sprint": {"id": "sprint-1", "name": "迭代1"},
        }
        with patch.object(monitor.time, "sleep"):
            result = monitor.process_requirement(
                client,
                requirement,
                project_id=monitor.DEFAULT_PROJECT_ID,
                manager_id="user-1",
                apply=True,
            )
        self.assertEqual(result["status"], "awaiting-case-confirmation")
        self.assertEqual(result["plan"]["sprintIdentifier"], "sprint-1")
        self.assertEqual(result["plan"]["endDate"], monitor.plan_dates()[1])
        self.assertEqual(result["caseMatches"][0]["testcaseId"], "case-1")
        self.assertEqual(result["caseAddPolicy"], "notify-and-confirm-before-add")
        self.assertEqual(len(client.created), 1)

    def test_first_apply_builds_baseline_without_creating_historical_plan(self) -> None:
        requirement = {
            "id": "req-old",
            "serialNumber": "ONEOS-9",
            "subject": "【新增】历史需求",
            "sprint": {"id": "sprint-1"},
        }
        client = FakeClient([requirement])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = monitor.run(args_for(root / "state.json", root / "receipt.json"), client)
            state = monitor.load_state(root / "state.json")
        self.assertEqual(result["bootstrap"]["status"], "baseline-created")
        self.assertEqual(client.created, [])
        self.assertEqual(state["requirements"]["req-old"]["status"], "baseline")

    def test_known_requirement_is_idempotently_skipped(self) -> None:
        requirement = {
            "id": "req-1",
            "serialNumber": "ONEOS-1",
            "subject": "【新增】云打印",
            "sprint": {"id": "sprint-1"},
        }
        client = FakeClient([requirement])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state_path = root / "state.json"
            monitor.write_json(state_path, {
                "schemaVersion": "oneos.yunxiao-requirement-plan-monitor/v1",
                "initializedAt": "2026-08-19T00:00:00+08:00",
                "requirements": {"req-1": {"status": "no-matching-cases"}},
            })
            result = monitor.run(args_for(state_path, root / "receipt.json"), client)
        self.assertEqual(result["newRequirementCount"], 0)
        self.assertEqual(client.created, [])

    def test_auth_failure_occurs_before_client_construction(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(monitor.MonitorError, "AUTH_CONFIG_MISSING"):
                monitor.require_config()


if __name__ == "__main__":
    unittest.main()
