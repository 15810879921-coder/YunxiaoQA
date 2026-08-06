#!/usr/bin/env python3
"""发布并回读校验云效缺陷评论。"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _auth import (  # noqa: E402
    AuthError,
    _raise_if_auth_failed,
    brief_item,
    find_by_serial,
    get_workitem,
    session,
    space_id,
)


def resolve_id(s, space: str, sn: str | None, wid: str | None) -> tuple[str, dict]:
    if wid:
        item = get_workitem(s, wid)
    else:
        if not sn:
            raise SystemExit("须提供 --id 或 --sn")
        item = find_by_serial(s, space=space, category="Bug", serial=sn)
        if not item:
            raise SystemExit(f"未找到缺陷编号 {sn}")
        item = get_workitem(s, item["identifier"])
    meta = brief_item(item)
    if sn and str(meta.get("serialNumber") or "").upper() != sn.strip().upper():
        raise SystemExit(f"编号回读不一致：期望 {sn}，实际 {meta.get('serialNumber')}")
    return str(item["identifier"]), meta


def rich_content(message: str) -> str:
    lines = message.strip().splitlines() or [message.strip()]
    paragraphs: list[str] = []
    jsonml: list[object] = ["root", {}]
    for line in lines:
        paragraphs.append(f'<p data-type="p"><span>{html.escape(line)}</span></p>')
        jsonml.append(
            ["p", {}, ["span", {"data-type": "text"}, ["span", {"data-type": "leaf"}, line]]]
        )
    return json.dumps(
        {
            "htmlValue": '<article class="4ever-article">' + "".join(paragraphs) + "</article>",
            "jsonMLValue": jsonml,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def comment_list(s, wid: str) -> list[dict]:
    response = s.get(
        f"https://devops.aliyun.com/projex/api/workitem/workitem/{wid}/comment/list"
        "?_input_charset=utf-8",
        timeout=45,
    )
    try:
        data = response.json()
    except ValueError:
        data = None
    _raise_if_auth_failed(response, data)
    response.raise_for_status()
    if not isinstance(data, dict):
        raise RuntimeError("读取缺陷评论返回非 JSON 响应")
    if data.get("code") != 200:
        raise RuntimeError(data.get("errorMsg") or data)
    return data.get("result") or []


def comment_matches(item: dict, message: str) -> bool:
    raw = html.unescape(json.dumps(item, ensure_ascii=False))
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    return bool(lines) and all(line in raw for line in lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="缺陷测试结果评论（幂等、回读校验）")
    ap.add_argument("--id", dest="workitem_id")
    ap.add_argument("--sn")
    ap.add_argument("--space")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--message")
    group.add_argument("--message-file")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    message = args.message
    if args.message_file:
        message = Path(args.message_file).read_text(encoding="utf-8")
    message = (message or "").strip()
    if not message:
        raise SystemExit("评论内容不能为空")

    try:
        s = session(probe=True)
    except AuthError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from exc
    wid, meta = resolve_id(s, space_id(args.space), args.sn, args.workitem_id)
    before = comment_list(s, wid)
    existing = next((item for item in before if comment_matches(item, message)), None)
    plan = {
        "bug": meta,
        "workitemId": wid,
        "message": message,
        "alreadyCommented": bool(existing),
        "dryRun": args.dry_run,
    }
    if args.dry_run or existing:
        print(json.dumps({"ok": True, "wouldComment": plan, "existing": existing}, ensure_ascii=False, indent=2))
        return

    response = s.post(
        f"https://devops.aliyun.com/projex/api/workitem/workitem/{wid}/comment"
        "?_input_charset=utf-8",
        json={"content": rich_content(message), "formatType": "RICHTEXT"},
        timeout=45,
    )
    try:
        data = response.json()
    except ValueError:
        data = None
    _raise_if_auth_failed(response, data)
    response.raise_for_status()
    if not isinstance(data, dict):
        raise RuntimeError("发布缺陷评论返回非 JSON 响应")
    if data.get("code") != 200:
        raise RuntimeError(data.get("errorMsg") or data)
    readback = next((item for item in comment_list(s, wid) if comment_matches(item, message)), None)
    ok = bool(readback)
    print(
        json.dumps(
            {"ok": ok, "plan": plan, "result": data.get("result"), "readback": readback},
            ensure_ascii=False,
            indent=2,
        )
    )
    if not ok:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
