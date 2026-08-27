#!/usr/bin/env python3
"""Create one Yunxiao Projex bug with PAT auth and verify all critical fields.

This is the official OpenAPI counterpart of ``create_bug.py`` for environments
where a personal access token is configured instead of a browser Cookie.
It performs exact-title duplicate detection, resolves project members/labels,
creates the bug, uploads evidence, and reads everything back.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests


DOMAIN = "https://openapi-rdc.aliyuncs.com"
DEFAULT_SPACE_ID = "1280be963a5a2cc126a4118dca"
DEFAULT_PROJECT = "01_ONEOS"
DEFAULT_BUG_TYPE = "37da3a07df4d08aef2e3b393"


class OpenApiError(RuntimeError):
    pass


def machine_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if os.name != "nt":
        return ""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        )
        return str(winreg.QueryValueEx(key, name)[0]).strip()
    except (FileNotFoundError, OSError):
        return ""


class Client:
    def __init__(self) -> None:
        self.token = machine_env("ALIBABA_CLOUD_YUNXIAO_ACCESS_TOKEN")
        self.organization_id = machine_env(
            "ALIBABA_CLOUD_YUNXIAO_ORGANIZATION_ID"
        )
        if not self.token or not self.organization_id:
            raise OpenApiError(
                "缺少机器或进程环境变量：ALIBABA_CLOUD_YUNXIAO_ACCESS_TOKEN / "
                "ALIBABA_CLOUD_YUNXIAO_ORGANIZATION_ID"
            )
        self.session = requests.Session()
        self.session.headers.update({"x-yunxiao-token": self.token})

    def url(self, path: str) -> str:
        return f"{DOMAIN}/oapi/v1/{path.format(org=self.organization_id)}"

    @staticmethod
    def _json(response: requests.Response, action: str) -> Any:
        try:
            data = response.json()
        except ValueError as exc:
            raise OpenApiError(
                f"{action}返回非 JSON：HTTP {response.status_code}"
            ) from exc
        if response.status_code >= 400:
            if isinstance(data, dict):
                detail = data.get("message") or data.get("errorMessage") or data.get(
                    "errorCode"
                )
            else:
                detail = None
            raise OpenApiError(f"{action}失败：HTTP {response.status_code} {detail or ''}")
        return data

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(self.url(path), params=params, timeout=45)
        return self._json(response, f"GET {path.split('?')[0]}")

    def post_json(self, path: str, body: dict[str, Any]) -> Any:
        response = self.session.post(self.url(path), json=body, timeout=60)
        return self._json(response, f"POST {path}")

    def post_file(self, path: str, file_path: Path) -> Any:
        with file_path.open("rb") as handle:
            response = self.session.post(
                self.url(path),
                files={"file": (file_path.name, handle)},
                timeout=120,
            )
        return self._json(response, f"上传附件 {file_path.name}")


def exact_member(client: Client, name: str) -> dict[str, Any]:
    rows = client.post_json(
        "platform/organizations/{org}/members:search",
        {"query": name, "page": 1, "perPage": 100, "statuses": ["ENABLED"]},
    )
    hits = [row for row in rows if row.get("name") == name]
    if len(hits) != 1:
        raise OpenApiError(f"成员 {name} 未唯一命中，数量={len(hits)}")
    row = hits[0]
    user_id = row.get("userId")
    if not user_id:
        raise OpenApiError(f"成员 {name} 缺少 userId")
    return {"name": name, "id": str(user_id), "memberId": str(row.get("id") or "")}


def exact_label(client: Client, space_id: str, name: str) -> dict[str, Any]:
    rows = client.get(
        f"projex/organizations/{{org}}/projects/{space_id}/labels",
        params={"page": 1, "perPage": 200},
    )
    hits = [row for row in rows if row.get("name") == name]
    if len(hits) != 1:
        raise OpenApiError(f"标签 {name} 未唯一命中，数量={len(hits)}")
    return {"name": name, "id": str(hits[0]["id"])}


def duplicate_rows(client: Client, space_id: str, title: str) -> list[dict[str, Any]]:
    conditions = {
        "conditionGroups": [
            [
                {
                    "fieldIdentifier": "subject",
                    "operator": "CONTAINS",
                    "value": [title],
                    "toValue": None,
                    "className": "string",
                    "format": "input",
                }
            ]
        ]
    }
    rows = client.post_json(
        "projex/organizations/{org}/workitems:search",
        {
            "category": "Bug",
            "conditions": json.dumps(conditions, ensure_ascii=False),
            "orderBy": "gmtCreate",
            "page": 1,
            "perPage": 200,
            "sort": "desc",
            "spaceId": space_id,
            "spaceType": "Project",
        },
    )
    return [
        {
            "id": row.get("id"),
            "serialNumber": row.get("serialNumber"),
            "subject": row.get("subject"),
            "status": (row.get("status") or {}).get("name"),
        }
        for row in rows
        if row.get("subject") == title
    ]


def exact_workitem_by_serial(
    client: Client, space_id: str, serial_number: str, category: str
) -> dict[str, Any]:
    conditions = {
        "conditionGroups": [
            [
                {
                    "fieldIdentifier": "serialNumber",
                    "operator": "EQUALS",
                    "value": [serial_number],
                    "toValue": None,
                    "className": "string",
                    "format": "input",
                }
            ]
        ]
    }
    rows = client.post_json(
        "projex/organizations/{org}/workitems:search",
        {
            "category": category,
            "conditions": json.dumps(conditions, ensure_ascii=False),
            "orderBy": "gmtCreate",
            "page": 1,
            "perPage": 20,
            "sort": "desc",
            "spaceId": space_id,
            "spaceType": "Project",
        },
    )
    hits = [row for row in rows if row.get("serialNumber") == serial_number]
    if len(hits) != 1:
        raise OpenApiError(
            f"工作项 {serial_number} 未唯一命中，category={category}，数量={len(hits)}"
        )
    row = hits[0]
    return {
        "id": str(row.get("id") or ""),
        "serialNumber": str(row.get("serialNumber") or ""),
        "subject": str(row.get("subject") or ""),
        "status": (row.get("status") or {}).get("name"),
    }


def field_display(item: dict[str, Any], field_id: str) -> tuple[str | None, str | None]:
    for field in item.get("customFieldValues") or []:
        if field.get("fieldId") != field_id:
            continue
        values = field.get("values") or []
        if not values:
            return None, None
        return str(values[0].get("identifier") or ""), str(
            values[0].get("displayValue") or ""
        )
    return None, None


def readback(
    client: Client,
    workitem_id: str,
    *,
    title: str,
    assignee: dict[str, Any],
    verifier: dict[str, Any],
    label: dict[str, Any],
    priority: str,
    severity: str,
    files: list[Path],
    test_task: dict[str, Any] | None,
) -> dict[str, Any]:
    item = client.get(f"projex/organizations/{{org}}/workitems/{workitem_id}")
    attachments = client.get(
        f"projex/organizations/{{org}}/workitems/{workitem_id}/attachments"
    )
    relations = (
        client.get(
            f"projex/organizations/{{org}}/workitems/{workitem_id}/relationRecords",
            params={"relationType": "ASSOCIATED"},
        )
        if test_task
        else []
    )
    priority_id, priority_name = field_display(item, "priority")
    severity_id, severity_name = field_display(item, "seriousLevel")
    live_labels = item.get("labels") or []
    live_files = {(str(x.get("fileName") or ""), int(x.get("size") or 0)) for x in attachments}
    checks = {
        "title": item.get("subject") == title,
        "status": (item.get("status") or {}).get("name") == "待确认",
        "assignee": (item.get("assignedTo") or {}).get("id") == assignee["id"],
        "verifier": (item.get("verifier") or {}).get("id") == verifier["id"],
        "creatorIsVerifier": (item.get("creator") or {}).get("id") == verifier["id"],
        "label": any(x.get("id") == label["id"] for x in live_labels),
        "priority": priority_name == priority,
        "severity": severity_name == severity,
        "attachments": all((path.name, path.stat().st_size) in live_files for path in files),
        "testTaskAssociated": (
            any(
                relation.get("relationType") == "ASSOCIATED"
                and str(relation.get("resourceId") or "") == test_task["id"]
                for relation in relations
            )
            if test_task
            else True
        ),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "bug": {
            "id": item.get("id"),
            "serialNumber": item.get("serialNumber"),
            "subject": item.get("subject"),
            "status": item.get("status"),
            "assignee": item.get("assignedTo"),
            "verifier": item.get("verifier"),
            "creator": item.get("creator"),
            "labels": live_labels,
            "priority": {"id": priority_id, "name": priority_name},
            "severity": {"id": severity_id, "name": severity_name},
        },
        "attachments": [
            {"fileName": x.get("fileName"), "size": x.get("size"), "id": x.get("id")}
            for x in attachments
        ],
        "relations": [
            {
                "id": x.get("id"),
                "relationType": x.get("relationType"),
                "resourceId": x.get("resourceId"),
            }
            for x in relations
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="通过云效官方 OpenAPI 发起并校验缺陷")
    parser.add_argument("--title", required=True)
    parser.add_argument("--assignee", required=True)
    parser.add_argument("--verifier", required=True)
    parser.add_argument("--label", required=True, help="项目中真实存在的完整标签名")
    parser.add_argument("--priority", required=True, choices=["紧急", "高", "中", "低"])
    parser.add_argument(
        "--severity", required=True, choices=["1-致命", "2-严重", "3-一般", "4-轻微"]
    )
    parser.add_argument("--description-file", required=True)
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--test-task", help="正式 ASSOCIATED 关联的【测试】任务编号")
    parser.add_argument("--req", help="写入描述追溯的需求编号（不建立关联）")
    parser.add_argument("--space-id", default=DEFAULT_SPACE_ID)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    description_path = Path(args.description_file).resolve()
    if not description_path.is_file():
        raise SystemExit(f"描述文件不存在：{description_path}")
    files = [Path(value).resolve() for value in args.file]
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise SystemExit(f"附件不存在：{missing}")

    try:
        client = Client()
        assignee = exact_member(client, args.assignee)
        verifier = exact_member(client, args.verifier)
        label = exact_label(client, args.space_id, args.label)
        test_task = (
            exact_workitem_by_serial(client, args.space_id, args.test_task, "Task")
            if args.test_task
            else None
        )
        requirement = (
            exact_workitem_by_serial(client, args.space_id, args.req, "Req")
            if args.req
            else None
        )
        duplicates = duplicate_rows(client, args.space_id, args.title)
        if duplicates:
            print(
                json.dumps(
                    {"ok": False, "duplicateBlocked": True, "duplicates": duplicates},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            raise SystemExit(5)

        description = description_path.read_text(encoding="utf-8")
        plan = {
            "project": {"name": args.project, "spaceId": args.space_id},
            "mode": "本期" if test_task else "非本期",
            "source": "standalone",
            "title": args.title,
            "assignee": assignee,
            "verifier": verifier,
            "label": label,
            "priority": args.priority,
            "severity": args.severity,
            "files": [{"name": p.name, "size": p.stat().st_size} for p in files],
            "testTask": test_task,
            "requirementTrace": requirement,
            "duplicateCount": 0,
            "writePath": "official OpenAPI",
        }
        if args.dry_run:
            print(json.dumps({"ok": True, "wouldCreate": plan}, ensure_ascii=False, indent=2))
            return

        priority_ids = {
            "紧急": "646004e97f54bb77fec7b455df",
            "高": "95b89e0a524d9693e1f335ffe5",
            "中": "fa155d1214f9f8db222d39db3b",
            "低": "92924feff9c1085891e7511872",
        }
        severity_ids = {
            "1-致命": "2236ad2f8e6b1b74491ab23015",
            "2-严重": "a3519c4be6d5ca8bb755ab391f",
            "3-一般": "647ee5a979d80379256efb450b",
            "4-轻微": "ebb2d182bccbb6ab33b4b209f2",
        }
        created = client.post_json(
            "projex/organizations/{org}/workitems",
            {
                "assignedTo": assignee["id"],
                "customFieldValues": {
                    "priority": priority_ids[args.priority],
                    "seriousLevel": severity_ids[args.severity],
                },
                "description": description,
                "formatType": "RICHTEXT",
                "labels": [label["id"]],
                "spaceId": args.space_id,
                "subject": args.title,
                "verifier": verifier["id"],
                "workitemTypeId": DEFAULT_BUG_TYPE,
            },
        )
        workitem_id = str(created.get("id") or "")
        if not workitem_id:
            raise OpenApiError("创建成功响应缺少工作项 id")

        relation_created = None
        if test_task:
            relation_created = client.post_json(
                f"projex/organizations/{{org}}/workitems/{workitem_id}/relationRecords",
                {
                    "relationType": "ASSOCIATED",
                    "workitemId": test_task["id"],
                },
            )

        uploaded = []
        for path in files:
            uploaded_raw = client.post_file(
                f"projex/organizations/{{org}}/workitems/{workitem_id}/attachments",
                path,
            )
            uploaded.append(
                {
                    "id": uploaded_raw.get("id"),
                    "name": uploaded_raw.get("name"),
                    "size": uploaded_raw.get("size"),
                    "suffix": uploaded_raw.get("suffix"),
                }
            )

        verified = readback(
            client,
            workitem_id,
            title=args.title,
            assignee=assignee,
            verifier=verifier,
            label=label,
            priority=args.priority,
            severity=args.severity,
            files=files,
            test_task=test_task,
        )
        output = {
            "ok": verified["ok"],
            "plan": plan,
            "relationCreated": relation_created,
            "uploaded": uploaded,
            "readback": verified,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        if not verified["ok"]:
            raise SystemExit(4)
    except OpenApiError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
