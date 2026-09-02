#!/usr/bin/env python3
"""Detect and repair a missing sprint on a test task's parent delivery task.

The preflight selects the latest active sprint for the delivery end.  Apply is
guarded by the exact sprint identifier shown to and confirmed by the user.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yunxiao_cli_runtime as core


SCHEMA = "oneos.yunxiao-delivery-iteration-cli/v1"
ACTIVE_SPRINT_STATUSES = {"TODO", "DOING"}


def rows(value: Any, label: str) -> list[dict[str, Any]]:
    value = core.unwrap(value)
    if value is None:
        return []
    if not isinstance(value, list):
        raise core.AdapterError(f"{label}返回结构异常。")
    return [row for row in value if isinstance(row, dict)]


def get_workitem(executable: str, workitem_id: str) -> dict[str, Any]:
    value = core.unwrap(core.run_devops(executable, [
        "projex-get-workitem", "--id", workitem_id,
    ]))
    if not isinstance(value, dict) or not value.get("id"):
        raise core.AdapterError(f"工作项{workitem_id}回读失败。")
    return value


def search_tasks(executable: str, project_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for page in range(1, 101):
        batch = rows(core.run_devops(executable, [
            "projex-search-workitems", "--category", "Task",
            "--space-id", project_id, "--space-type", "Project",
            "--page", str(page), "--per-page", "200", "--sort", "asc",
        ]), "Task工作项查询")
        result.extend(batch)
        if len(batch) < 200:
            break
    return result


def exact_task(executable: str, project_id: str, serial_number: str) -> dict[str, Any]:
    matches = [row for row in search_tasks(executable, project_id)
               if str(row.get("serialNumber") or "").upper() == serial_number.upper()]
    ids = {str(row.get("id") or "") for row in matches if row.get("id")}
    if len(ids) != 1:
        raise core.AdapterError(f"{serial_number}无法在Task中唯一解析。")
    item = get_workitem(executable, next(iter(ids)))
    if str(item.get("serialNumber") or "").upper() != serial_number.upper():
        raise core.AdapterError(f"{serial_number}编号回读不一致。")
    return item


def relation_ids(executable: str, workitem_id: str, relation_type: str) -> list[str]:
    values = rows(core.run_devops(executable, [
        "projex-list-workitem-relation-records", "--id", workitem_id,
        "--relation-type", relation_type,
    ]), f"{relation_type}关系查询")
    return sorted({str(row.get("resourceId")) for row in values if row.get("resourceId")})


def resolve_delivery(executable: str, project_id: str, test_sn: str | None,
                     delivery_sn: str | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if delivery_sn:
        delivery = exact_task(executable, project_id, delivery_sn)
        if not str(delivery.get("subject") or "").startswith("【交付】"):
            raise core.AdapterError(f"{delivery_sn}不是【交付】任务。")
        return None, delivery
    if not test_sn:
        raise core.AdapterError("必须提供--test-sn或--delivery-sn。")
    test = exact_task(executable, project_id, test_sn)
    if not str(test.get("subject") or "").startswith("【测试】"):
        raise core.AdapterError(f"{test_sn}不是【测试】任务。")
    parents = relation_ids(executable, str(test["id"]), "PARENT")
    if len(parents) != 1:
        raise core.AdapterError(f"{test_sn}无法唯一反查父【交付】任务。")
    delivery = get_workitem(executable, parents[0])
    if not str(delivery.get("subject") or "").startswith("【交付】"):
        raise core.AdapterError(f"{test_sn}唯一父项不是【交付】任务。")
    return test, delivery


def sprint_snapshot(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    sprint_id = str(value.get("id") or value.get("identifier") or "")
    if not sprint_id:
        return None
    return {
        "id": sprint_id,
        "name": str(value.get("name") or ""),
        "status": str(value.get("status") or ""),
        "startDate": value.get("startDate"),
        "endDate": value.get("endDate"),
    }


def item_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    status = item.get("status") if isinstance(item.get("status"), dict) else {}
    return {
        "id": str(item.get("id") or ""),
        "serialNumber": str(item.get("serialNumber") or ""),
        "subject": str(item.get("subject") or ""),
        "status": str(status.get("displayName") or status.get("name") or ""),
        "sprint": sprint_snapshot(item.get("sprint")),
    }


def delivery_end(delivery: dict[str, Any], explicit: str | None = None) -> str:
    if explicit:
        return explicit
    names = [str(label.get("name") or "") for label in delivery.get("labels") or []
             if isinstance(label, dict)]
    probe = " ".join(names + [str(delivery.get("subject") or "")]).lower()
    mini = "小程序" in probe
    web = any(token in probe for token in ("web", "pc端", "pc-", "pc_"))
    if mini == web:
        raise core.AdapterError(
            "无法从父【交付】标签唯一判定Web/小程序端；请在Plan中明确--delivery-end。"
        )
    return "小程序" if mini else "Web"


def list_sprints(executable: str, project_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for page in range(1, 101):
        batch = rows(core.run_devops(executable, [
            "projex-list-sprints", "--id", project_id,
            "--page", str(page), "--per-page", "100",
        ]), "迭代查询")
        result.extend(batch)
        if len(batch) < 100:
            break
    return result


def version_key(name: str) -> tuple[int, ...]:
    match = re.search(r"(?i)v(\d+(?:\.\d+)+)", name)
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def endpoint_matches(name: str, end: str) -> bool:
    lowered = name.lower()
    if end == "小程序":
        return "小程序" in lowered
    return "web端" in lowered or "pc端" in lowered


def select_latest_sprint(sprints: list[dict[str, Any]], end: str) -> dict[str, Any]:
    candidates = [row for row in sprints
                  if str(row.get("status") or "") in ACTIVE_SPRINT_STATUSES
                  and not bool(row.get("locked"))
                  and endpoint_matches(str(row.get("name") or ""), end)
                  and version_key(str(row.get("name") or ""))]
    if not candidates:
        raise core.AdapterError(f"未找到{end}端未归档且未锁定的版本迭代。")
    return max(candidates, key=lambda row: (
        version_key(str(row.get("name") or "")),
        int(row.get("startDate") or 0), int(row.get("gmtCreate") or 0),
    ))


def bind_sprint(executable: str, delivery: dict[str, Any], sprint_id: str) -> dict[str, Any]:
    core.run_devops(executable, [
        "projex-update-workitem", "--id", str(delivery["id"]), "--biz-body",
        json.dumps({"sprint": sprint_id}, ensure_ascii=False, separators=(",", ":")),
    ])
    updated = get_workitem(executable, str(delivery["id"]))
    if str(updated.get("serialNumber") or "").upper() != \
            str(delivery.get("serialNumber") or "").upper() or \
            (sprint_snapshot(updated.get("sprint")) or {}).get("id") != sprint_id:
        raise core.AdapterError("父【交付】迭代写入后回读失败。")
    return updated


def run(args: argparse.Namespace) -> int:
    executable = core.find_aliyun()
    auth = core.require_auth_env()
    test, delivery = resolve_delivery(
        executable, args.space_id, args.test_sn, args.delivery_sn,
    )
    current = sprint_snapshot(delivery.get("sprint"))
    receipt: dict[str, Any] = {
        "schemaVersion": SCHEMA,
        "mode": "apply" if args.apply else "preflight",
        "organizationId": auth["organizationId"],
        "projectId": args.space_id,
        "testTask": item_snapshot(test) if test else None,
        "deliveryTask": item_snapshot(delivery),
        "currentSprint": current,
        "plannedActions": [],
        "needsConfirmation": False,
        "verified": bool(current),
    }
    if not current:
        end = delivery_end(delivery, args.delivery_end)
        candidate = select_latest_sprint(list_sprints(executable, args.space_id), end)
        chosen = sprint_snapshot(candidate)
        if not chosen:
            raise core.AdapterError("候选迭代缺少唯一ID。")
        receipt["deliveryEnd"] = end
        receipt["candidateSprint"] = chosen
        receipt["needsConfirmation"] = not args.apply
        receipt["plannedActions"].append({
            "operation": "projex-update-workitem",
            "target": str(delivery.get("serialNumber") or ""),
            "field": "sprint",
            "value": chosen,
        })
        if args.apply:
            if args.confirm_sprint_id != chosen["id"]:
                raise core.AdapterError(
                    "apply前必须把Plan中已确认的候选迭代ID通过--confirm-sprint-id原样传入。"
                )
            delivery = bind_sprint(executable, delivery, chosen["id"])
            receipt["after"] = item_snapshot(delivery)
            receipt["verified"] = \
                (receipt["after"].get("sprint") or {}).get("id") == chosen["id"]
            receipt["needsConfirmation"] = False
    target = Path(args.output) if args.output else core.output_dir() / \
        f"qa-delivery-iteration-{str(delivery.get('serialNumber') or '').lower()}.json"
    core.write_json(target, receipt)
    print(json.dumps({
        "mode": receipt["mode"],
        "testTask": receipt["testTask"],
        "deliveryTask": receipt.get("after", receipt["deliveryTask"]),
        "candidateSprint": receipt.get("candidateSprint"),
        "needsConfirmation": receipt["needsConfirmation"],
        "verified": receipt["verified"],
        "receipt": str(target),
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--space-id", required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--test-sn")
    target.add_argument("--delivery-sn")
    parser.add_argument("--delivery-end", choices=("Web", "小程序"))
    parser.add_argument("--confirm-sprint-id")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        return run(args)
    except (core.AdapterError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": core.scrub(str(exc))},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
