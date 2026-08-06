from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import attach_bug  # noqa: E402
import comment_bug  # noqa: E402
import create_bug  # noqa: E402
import set_bug_fields  # noqa: E402


class BugOperationTests(unittest.TestCase):
    def test_create_bug_enums_exclude_runtime_metadata(self) -> None:
        self.assertNotIn("fieldIdentifier", create_bug.PRI)
        self.assertNotIn("name", create_bug.SEV)
        self.assertIn("中", create_bug.PRI)
        self.assertIn("3-一般", create_bug.SEV)

    def test_exact_title_duplicate_filters_contains_result(self) -> None:
        rows = [
            {"identifier": "1", "serialNumber": "ONEOS-1", "subject": "【模块】同名"},
            {"identifier": "2", "serialNumber": "ONEOS-2", "subject": "【模块】同名-补充"},
        ]
        with patch.object(create_bug, "post_list", return_value={"result": rows}):
            found = create_bug.find_exact_title_duplicates(object(), "space", "【模块】同名")
        self.assertEqual([item["serialNumber"] for item in found], ["ONEOS-1"])

    def test_tag_ids_reads_nested_shapes(self) -> None:
        value = [{"identifier": "tag-a"}, {"value": {"id": "tag-b"}}]
        self.assertEqual(create_bug.tag_ids(value), {"tag-a", "tag-b"})

    def test_attachment_match_uses_name_and_size(self) -> None:
        items = [{"aoneFile": {"name": "actual.png", "size": 123}}]
        self.assertIsNotNone(attach_bug.matching(items, "actual.png", 123))
        self.assertIsNone(attach_bug.matching(items, "actual.png", 124))

    def test_rich_comment_escapes_html_and_keeps_jsonml_text(self) -> None:
        value = json.loads(comment_bug.rich_content("通过 <ok>\n版本 v1"))
        self.assertIn("&lt;ok&gt;", value["htmlValue"])
        self.assertEqual(value["jsonMLValue"][2][2][2][2], "通过 <ok>")

    def test_comment_match_requires_every_nonblank_line(self) -> None:
        item = {"content": "测试结果：通过；环境=test；版本=v1"}
        self.assertTrue(comment_bug.comment_matches(item, "测试结果：通过\n版本=v1"))
        self.assertFalse(comment_bug.comment_matches(item, "测试结果：通过\n版本=v2"))

    def test_safe_field_readback_tokens(self) -> None:
        extra = {
            "fieldValueList": [
                {"fieldIdentifier": "tag", "value": [{"identifier": "tag-a"}]}
            ]
        }
        values = set_bug_fields.field_values(extra, "tag")
        self.assertEqual(set_bug_fields.scalar_tokens(values), {"tag-a"})


if __name__ == "__main__":
    unittest.main()
