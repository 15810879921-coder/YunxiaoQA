#!/usr/bin/env python3
"""List pending retest bugs via OpenAPI PAT (no Cookie / no aliyun CLI)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from create_bug_openapi import Client, OpenApiError  # noqa: E402

DEFAULT_SPACE = "1280be963a5a2cc126a4118dca"  # 01_ONEOS
STATUS_IDS = {
    "已修复": "29",
    "暂不修复": "31",
}


def brief(row: dict) -> dict:
    status = row.get("status") or {}
    assignee = row.get("assignedTo") or {}
    verifier = row.get("verifier") or {}
    return {
        "id": row.get("id"),
        "serialNumber": row.get("serialNumber"),
        "subject": row.get("subject"),
        "status": status.get("displayName") or status.get("name"),
        "assignee": assignee.get("name") if isinstance(assignee, dict) else assignee,
        "verifier": verifier.get("name") if isinstance(verifier, dict) else verifier,
        "gmtModified": row.get("gmtModified"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space-id", default=DEFAULT_SPACE)
    ap.add_argument("--status", action="append", choices=list(STATUS_IDS), default=None)
    ap.add_argument("--per-page", type=int, default=100)
    ap.add_argument("--max-pages", type=int, default=10)
    args = ap.parse_args()
    names = args.status or ["已修复", "暂不修复"]
    ids = [STATUS_IDS[n] for n in names]
    client = Client()
    conditions = {
        "conditionGroups": [
            [
                {
                    "fieldIdentifier": "status",
                    "operator": "CONTAINS",
                    "value": ids,
                    "toValue": None,
                    "className": "status",
                    "format": "list",
                }
            ]
        ]
    }
    items: list[dict] = []
    for page in range(1, args.max_pages + 1):
        rows = client.post_json(
            "projex/organizations/{org}/workitems:search",
            {
                "category": "Bug",
                "conditions": json.dumps(conditions, ensure_ascii=False),
                "orderBy": "gmtModified",
                "page": page,
                "perPage": args.per_page,
                "sort": "desc",
                "spaceId": args.space_id,
                "spaceType": "Project",
            },
        )
        if not isinstance(rows, list):
            raise OpenApiError(f"搜索返回异常：{type(rows)}")
        items.extend(brief(row) for row in rows if isinstance(row, dict))
        if len(rows) < args.per_page:
            break
    print(
        json.dumps(
            {
                "spaceId": args.space_id,
                "statusFilter": names,
                "count": len(items),
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OpenApiError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(2) from exc
