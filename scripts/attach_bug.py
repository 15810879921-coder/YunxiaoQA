#!/usr/bin/env python3
"""上传本地文件并回读校验云效缺陷附件。"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
from pathlib import Path

import requests

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


def serial_matches(actual: object, expected: str) -> bool:
    return str(actual or "").strip().upper() == expected.strip().upper()


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
    if sn and not serial_matches(meta.get("serialNumber"), sn):
        raise SystemExit(f"编号回读不一致：期望 {sn}，实际 {meta.get('serialNumber')}")
    return str(item["identifier"]), meta


def attachment_list(s, wid: str) -> list[dict]:
    response = s.get(
        f"https://devops.aliyun.com/projex/api/workitem/workitem/{wid}/attachment/list"
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
        raise RuntimeError("读取附件列表返回非 JSON 响应")
    if data.get("code") != 200:
        raise RuntimeError(data.get("errorMsg") or data)
    return data.get("result") or []


def attachment_name_size(item: dict) -> tuple[str | None, int | None]:
    file_data = item.get("aoneFile") or item
    name = file_data.get("name") or file_data.get("originalFilename")
    size = file_data.get("size")
    try:
        size = int(size) if size is not None else None
    except (TypeError, ValueError):
        size = None
    return name, size


def matching(items: list[dict], name: str, size: int) -> dict | None:
    for item in items:
        if attachment_name_size(item) == (name, size):
            return item
    return None


def upload_one(s, wid: str, path: Path) -> object:
    info_response = s.get(
        f"https://devops.aliyun.com/projex/api/workitem/workitem/{wid}"
        "/attachment/upload/info?_input_charset=utf-8",
        params={"fileName": path.name},
        timeout=45,
    )
    try:
        info_data = info_response.json()
    except ValueError:
        info_data = None
    _raise_if_auth_failed(info_response, info_data)
    info_response.raise_for_status()
    if not isinstance(info_data, dict):
        raise RuntimeError("附件上传凭证返回非 JSON 响应")
    if info_data.get("code") != 200:
        raise RuntimeError(info_data.get("errorMsg") or info_data)
    info = info_data["result"]
    oss_key = f"{info['dir']}{int(time.time() * 1000)}{path.name}"

    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as handle:
        upload = requests.post(
            info["host"],
            data={
                "name": path.name,
                "key": oss_key,
                "policy": info["policy"],
                "OSSAccessKeyId": info["accessid"],
                "success_action_status": "200",
                "signature": info["signature"],
            },
            files={"file": (path.name, handle, mime)},
            timeout=90,
        )
    if upload.status_code != 200:
        raise RuntimeError(f"OSS 上传失败 HTTP {upload.status_code}: {upload.text[:500]}")

    relation = s.post(
        f"https://devops.aliyun.com/projex/api/workitem/workitem/{wid}/attachfile"
        "?_input_charset=utf-8",
        json={
            "originalFilename": path.name,
            "fileIdentifier": oss_key,
            "showType": "independent",
        },
        timeout=45,
    )
    try:
        relation_data = relation.json()
    except ValueError:
        relation_data = None
    _raise_if_auth_failed(relation, relation_data)
    relation.raise_for_status()
    if not isinstance(relation_data, dict):
        raise RuntimeError("绑定缺陷附件返回非 JSON 响应")
    if relation_data.get("code") != 200:
        raise RuntimeError(relation_data.get("errorMsg") or relation_data)
    return relation_data.get("result")


def main() -> None:
    ap = argparse.ArgumentParser(description="缺陷附件上传（幂等、支持多文件与回读校验）")
    ap.add_argument("--id", dest="workitem_id")
    ap.add_argument("--sn")
    ap.add_argument("--space")
    ap.add_argument("--file", action="append", required=True, help="可重复传入")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    paths = [Path(value).resolve() for value in args.file]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise SystemExit(f"文件不存在：{missing}")

    try:
        s = session(probe=True)
    except AuthError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from exc
    wid, meta = resolve_id(s, space_id(args.space), args.sn, args.workitem_id)
    before = attachment_list(s, wid)
    plans = []
    for path in paths:
        size = path.stat().st_size
        plans.append(
            {
                "file": str(path),
                "fileName": path.name,
                "size": size,
                "alreadyAttached": bool(matching(before, path.name, size)),
            }
        )
    plan = {"bug": meta, "workitemId": wid, "files": plans, "dryRun": args.dry_run}
    if args.dry_run:
        print(json.dumps({"ok": True, "wouldAttach": plan}, ensure_ascii=False, indent=2))
        return

    uploaded = []
    for path, item in zip(paths, plans):
        if not item["alreadyAttached"]:
            uploaded.append({"fileName": path.name, "result": upload_one(s, wid, path)})

    after = attachment_list(s, wid)
    readback = []
    for path in paths:
        hit = matching(after, path.name, path.stat().st_size)
        readback.append({"fileName": path.name, "ok": bool(hit), "attachment": hit})
    ok = all(item["ok"] for item in readback)
    print(
        json.dumps(
            {"ok": ok, "plan": plan, "uploaded": uploaded, "readback": readback},
            ensure_ascii=False,
            indent=2,
        )
    )
    if not ok:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
