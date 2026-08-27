from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import transit_test_lifecycle as lifecycle  # noqa: E402


def detail(
    wid: str,
    sn: str,
    subject: str,
    status_name: str,
    status_id: str,
) -> dict[str, object]:
    return {
        "identifier": wid,
        "serialNumber": sn,
        "subject": subject,
        "status": {"displayName": status_name, "identifier": status_id},
    }


class TransitTestLifecycleTests(unittest.TestCase):
    def test_start_uses_pending_as_source(self) -> None:
        self.assertEqual(
            lifecycle.ACTION_STATES["start"],
            ("待处理", "处理中", "待测试", "测试中"),
        )

    def test_transition_plan_resolves_direct_target(self) -> None:
        test = detail("t", "ONEOS-10", "【测试】登录", "待处理", "pending")
        session_obj = object()
        with patch.object(
            lifecycle,
            "resolve_next_status_id",
            return_value="100010",
        ) as resolver:
            plan = lifecycle.transition_plan(
                session_obj,
                test,
                "待处理",
                "处理中",
            )

        self.assertFalse(plan["alreadyDone"])
        self.assertEqual(plan["toId"], "100010")
        resolver.assert_called_once_with(session_obj, "t", "pending", "处理中")

    def test_transition_plan_is_idempotent_at_target(self) -> None:
        test = detail("t", "ONEOS-20", "【测试】登录", "处理中", "100010")
        with patch.object(lifecycle, "resolve_next_status_id") as resolver:
            plan = lifecycle.transition_plan(
                object(),
                test,
                "待处理",
                "处理中",
            )

        self.assertTrue(plan["alreadyDone"])
        self.assertEqual(plan["toId"], "100010")
        resolver.assert_not_called()

    def test_complete_builds_test_requirement_order_only(self) -> None:
        items = [object(), object()]
        planned = [
            {"serialNumber": "TEST"},
            {"serialNumber": "REQ"},
        ]
        with patch.object(
            lifecycle,
            "transition_plan",
            side_effect=planned,
        ) as transition:
            result = lifecycle.build_transition_plans(
                object(),
                "complete",
                items[0],
                items[1],
            )

        self.assertEqual(result, planned)
        self.assertEqual(
            [call.args[1] for call in transition.call_args_list],
            items,
        )


if __name__ == "__main__":
    unittest.main()
