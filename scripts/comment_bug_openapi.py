#!/usr/bin/env python3
"""Publish one idempotent Yunxiao Projex bug comment with PAT auth."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from create_bug_openapi import (  # noqa: E402
    Client,
    OpenApiError,
    exact_workitem_by_serial,
)

DEFAULT_SPACE = "1280be963a5a2cc126a4118dca"


def list_comments(client: Client, workitem_id: str) -> list[dict[str, Any]]:
    rows = client.get(f"projex/organizations/{{org}}/workitems/{workitem_id}/comments")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise OpenApiError(f"评论列表返回异常：{type(rows)}")
    return [row for row in rows if isinstance(row, dict)]


def comment_matches(item: dict[str, Any], message: str) -> bool:
    raw = json.dumps(item, ensure_ascii=False)
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    return bool(lines) and all(line in raw for line in lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="缺陷评论（PAT OpenAPI，幂等、回读）")
    parser.add_argument("--sn", required=True)
    parser.add_argument("--space-id", default=DEFAULT_SPACE)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--message")
    group.add_argument("--message-file")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    message = args.message
    if args.message_file:
        message = Path(args.message_file).read_text(encoding="utf-8")
    message = (message or "").strip()
    if not message:
        raise SystemExit("评论内容不能为空")

    try:
        client = Client()
        bug = exact_workitem_by_serial(client, args.space_id, args.sn, "Bug")
        comments = list_comments(client, bug["id"])
        existing = next((item for item in comments if comment_matches(item, message)), None)
        plan = {
            "bug": bug,
            "message": message,
            "alreadyCommented": bool(existing),
            "dryRun": args.dry_run,
            "writePath": "official OpenAPI",
        }
        if args.dry_run or existing:
            print(
                json.dumps(
                    {"ok": True, "wouldComment": plan, "existing": existing},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        result = client.post_json(
            f"projex/organizations/{{org}}/workitems/{bug['id']}/comments",
            {"content": message},
        )
        readback = next(
            (
                item
                for item in list_comments(client, bug["id"])
                if comment_matches(item, message)
            ),
            None,
        )
        ok = bool(readback)
        print(
            json.dumps(
                {"ok": ok, "plan": plan, "result": result, "readback": readback},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if ok else 3
    except OpenApiError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
