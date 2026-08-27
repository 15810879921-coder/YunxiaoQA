#!/usr/bin/env python3
"""Comment retest result and close repaired bugs via OpenAPI PAT."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from create_bug_openapi import Client, OpenApiError, exact_workitem_by_serial  # noqa: E402

CLOSED_STATUS_ID = "100085"
DEFAULT_SPACE = "1280be963a5a2cc126a4118dca"


def put_json(client: Client, path: str, body: dict[str, Any]) -> Any:
    response = client.session.put(client.url(path), json=body, timeout=60)
    if response.status_code in {200, 204} and not (response.text or "").strip():
        return None
    return client._json(response, f"PUT {path.split('?')[0]}")


def status_name(item: dict[str, Any]) -> str:
    status = item.get("status") or {}
    return str(status.get("displayName") or status.get("name") or "")


def build_message(serial: str, subject: str) -> str:
    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    return (
        f"【复测通过】环境=test；时间={now}；结论=验证通过，状态改为已关闭。\n"
        f"缺陷={serial}；标题={subject}；验证人=当前登录测试用户（谢佳伟）。\n"
        "说明：测试环境复测通过，按用户确认默认备注关单。\n"
        f"idempotencyKey=qa-close-default-{serial}"
    )


def list_comments(client: Client, workitem_id: str) -> list[dict[str, Any]]:
    rows = client.get(f"projex/organizations/{{org}}/workitems/{workitem_id}/comments")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise OpenApiError(f"评论列表返回异常：{type(rows)}")
    return [row for row in rows if isinstance(row, dict)]


def comment_exists(comments: list[dict[str, Any]], serial: str) -> bool:
    marker = f"idempotencyKey=qa-close-default-{serial}"
    for item in comments:
        raw = json.dumps(item, ensure_ascii=False)
        if marker in raw or (f"缺陷={serial}" in raw and "【复测通过】" in raw):
            return True
    return False


def process_one(
    client: Client,
    *,
    space_id: str,
    serial: str,
    apply: bool,
) -> dict[str, Any]:
    brief = exact_workitem_by_serial(client, space_id, serial, "Bug")
    item = client.get(f"projex/organizations/{{org}}/workitems/{brief['id']}")
    before_status = status_name(item)
    subject = str(item.get("subject") or brief.get("subject") or "")
    message = build_message(serial, subject)
    receipt: dict[str, Any] = {
        "serialNumber": serial,
        "id": brief["id"],
        "subject": subject,
        "beforeStatus": before_status,
        "message": message,
        "commented": False,
        "closed": False,
        "afterStatus": before_status,
        "ok": False,
    }
    if before_status not in {"已修复", "已关闭"}:
        receipt["error"] = f"当前状态={before_status}，仅允许已修复→已关闭"
        return receipt

    comments = list_comments(client, brief["id"])
    already = comment_exists(comments, serial)
    receipt["alreadyCommented"] = already

    if not apply:
        receipt["mode"] = "preflight"
        receipt["wouldComment"] = not already
        receipt["wouldClose"] = before_status == "已修复"
        receipt["ok"] = True
        return receipt

    if not already:
        client.post_json(
            f"projex/organizations/{{org}}/workitems/{brief['id']}/comments",
            {"content": message},
        )
        comments_after = list_comments(client, brief["id"])
        if not comment_exists(comments_after, serial):
            receipt["error"] = "评论写入后回读失败"
            return receipt
        receipt["commented"] = True
    else:
        receipt["commented"] = True

    if before_status != "已关闭":
        put_json(
            client,
            f"projex/organizations/{{org}}/workitems/{brief['id']}",
            {"status": CLOSED_STATUS_ID},
        )
    after = client.get(f"projex/organizations/{{org}}/workitems/{brief['id']}")
    after_status = status_name(after)
    after_sn = str(after.get("serialNumber") or "")
    receipt["afterStatus"] = after_status
    receipt["closed"] = after_status == "已关闭"
    receipt["report"] = f"{after_sn} | {subject} | {before_status}→{after_status}"
    if after_sn.upper() != serial.upper():
        receipt["error"] = f"编号回读不一致：期望 {serial}，实际 {after_sn}"
        return receipt
    if after_status != "已关闭":
        receipt["error"] = f"关单后状态={after_status}，期望已关闭"
        return receipt
    receipt["ok"] = True
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenAPI 评论并关闭已修复缺陷")
    ap.add_argument("--space-id", default=DEFAULT_SPACE)
    ap.add_argument("--sn", action="append", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    client = Client()
    # Verify current user identity for audit.
    user = client.get("platform/user")
    results = [
        process_one(client, space_id=args.space_id, serial=sn, apply=args.apply)
        for sn in args.sn
    ]
    ok = all(row.get("ok") for row in results)
    print(
        json.dumps(
            {
                "ok": ok,
                "mode": "apply" if args.apply else "preflight",
                "operator": {"id": user.get("id"), "name": user.get("name")},
                "count": len(results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OpenApiError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(2) from exc
    except requests.RequestException as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(2) from exc
