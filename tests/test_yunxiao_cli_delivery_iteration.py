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

import yunxiao_cli_delivery_iteration as iteration  # noqa: E402


class DeliveryIterationTests(unittest.TestCase):
    def test_selects_latest_active_version_for_same_end(self) -> None:
        rows = [
            {"id": "old", "name": "OneOS_web端V1.4.7", "status": "DOING"},
            {"id": "latest", "name": "OneOS_web端V1.4.9", "status": "DOING"},
            {"id": "archived", "name": "OneOS_web端V1.5.0", "status": "ARCHIVED"},
            {"id": "mini", "name": "OneOS_小程序端V1.9.0", "status": "DOING"},
        ]
        self.assertEqual(iteration.select_latest_sprint(rows, "Web")["id"], "latest")

    def test_preflight_reports_candidate_without_writing(self) -> None:
        test = {"id": "test-1", "serialNumber": "ONEOS-1", "subject": "【测试】A"}
        delivery = {
            "id": "delivery-1", "serialNumber": "ONEOS-2", "subject": "【交付】A",
            "labels": [{"name": "Web"}], "status": {"displayName": "处理中"},
            "sprint": None,
        }
        sprint = {"id": "sprint-149", "name": "OneOS_web端V1.4.9", "status": "DOING"}
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "receipt.json"
            args = argparse.Namespace(
                space_id="project", test_sn="ONEOS-1", delivery_sn=None,
                delivery_end=None, confirm_sprint_id=None, apply=False,
                output=str(output),
            )
            with patch.object(iteration.core, "find_aliyun", return_value="aliyun"), \
                    patch.object(iteration.core, "require_auth_env", return_value={"organizationId": "org"}), \
                    patch.object(iteration, "resolve_delivery", return_value=(test, delivery)), \
                    patch.object(iteration, "list_sprints", return_value=[sprint]), \
                    patch.object(iteration, "bind_sprint") as writer:
                result = iteration.run(args)
            receipt = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result, 0)
        self.assertTrue(receipt["needsConfirmation"])
        self.assertEqual(receipt["candidateSprint"]["id"], "sprint-149")
        writer.assert_not_called()

    def test_apply_requires_exact_confirmed_sprint_id(self) -> None:
        delivery = {
            "id": "delivery-1", "serialNumber": "ONEOS-2", "subject": "【交付】A",
            "labels": [{"name": "Web"}], "sprint": None,
        }
        sprint = {"id": "sprint-149", "name": "OneOS_web端V1.4.9", "status": "DOING"}
        args = argparse.Namespace(
            space_id="project", test_sn=None, delivery_sn="ONEOS-2",
            delivery_end=None, confirm_sprint_id="wrong", apply=True, output=None,
        )
        with patch.object(iteration.core, "find_aliyun", return_value="aliyun"), \
                patch.object(iteration.core, "require_auth_env", return_value={"organizationId": "org"}), \
                patch.object(iteration, "resolve_delivery", return_value=(None, delivery)), \
                patch.object(iteration, "list_sprints", return_value=[sprint]), \
                patch.object(iteration, "bind_sprint") as writer:
            with self.assertRaisesRegex(iteration.core.AdapterError, "confirm-sprint-id"):
                iteration.run(args)
        writer.assert_not_called()

    def test_apply_binds_and_verifies_exact_sprint(self) -> None:
        delivery = {
            "id": "delivery-1", "serialNumber": "ONEOS-2", "subject": "【交付】A",
            "labels": [{"name": "Web"}], "status": {"displayName": "处理中"},
            "sprint": None,
        }
        sprint = {"id": "sprint-149", "name": "OneOS_web端V1.4.9", "status": "DOING"}
        updated = {**delivery, "sprint": sprint}
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "receipt.json"
            args = argparse.Namespace(
                space_id="project", test_sn=None, delivery_sn="ONEOS-2",
                delivery_end=None, confirm_sprint_id="sprint-149", apply=True,
                output=str(output),
            )
            with patch.object(iteration.core, "find_aliyun", return_value="aliyun"), \
                    patch.object(iteration.core, "require_auth_env", return_value={"organizationId": "org"}), \
                    patch.object(iteration, "resolve_delivery", return_value=(None, delivery)), \
                    patch.object(iteration, "list_sprints", return_value=[sprint]), \
                    patch.object(iteration, "bind_sprint", return_value=updated) as writer:
                result = iteration.run(args)
            receipt = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result, 0)
        self.assertTrue(receipt["verified"])
        writer.assert_called_once_with("aliyun", delivery, "sprint-149")


if __name__ == "__main__":
    unittest.main()
