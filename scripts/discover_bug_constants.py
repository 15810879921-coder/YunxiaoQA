#!/usr/bin/env python
"""实网探测：Bug 类型 / 缺陷状态 / 验证者字段 / 任务「处理中」。stdout=JSON。"""
from __future__ import annotations

import json
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

import requests

try:
    import browser_cookie3
except ImportError:
    browser_cookie3 = None

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = json.loads(
    (ROOT / "assets" / "runtime-ids.json").read_text(encoding="utf-8")
)
ORG = RUNTIME["project"]["organizationIdentifier"]
SPACE = (RUNTIME.get("project", {}).get("last_selected") or {}).get(
    "spaceIdentifier"
) or "1280be963a5a2cc126a4118dca"


def load_jar() -> dict[str, str]:
    jar: dict[str, str] = {}
    if browser_cookie3:
        for domain in (".aliyun.com", "devops.aliyun.com", ".devops.aliyun.com"):
            try:
                for c in browser_cookie3.chrome(domain_name=domain):
                    jar[c.name] = c.value
            except Exception:
                pass
    if not jar.get("XSRF-TOKEN"):
        p = Path(tempfile.gettempdir()) / "yunxiao_cookies.json"
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            jar = (
                raw
                if isinstance(raw, dict) and "XSRF-TOKEN" in raw
                else {c["name"]: c["value"] for c in raw.get("cookies", [])}
            )
    if not jar.get("XSRF-TOKEN"):
        raise RuntimeError("缺少 XSRF-TOKEN：请先在 Chrome 登录 devops.aliyun.com")
    return jar


def session() -> requests.Session:
    jar = load_jar()
    x = jar.get("XSRF-TOKEN", "")
    xsrf = urllib.parse.unquote(x) if "%" in x else x
    cookie = "; ".join(f"{k}={v}" for k, v in jar.items())
    s = requests.Session()
    s.headers.update(
        {
            "Cookie": cookie,
            "x-xsrf-token": xsrf,
            "X-XSRF-TOKEN": xsrf,
            "Origin": "https://devops.aliyun.com",
            "Referer": "https://devops.aliyun.com/projex",
            "accept": "application/json",
            "Content-Type": "application/json",
        }
    )
    return s


def try_get(s: requests.Session, path: str, params: dict | None = None) -> Any:
    url = f"https://devops.aliyun.com{path}"
    r = s.get(url, params=params, timeout=30)
    try:
        body = r.json()
    except Exception:
        body = {"_text": r.text[:500]}
    return {"status_code": r.status_code, "body": body}


def try_post(s: requests.Session, path: str, payload: Any) -> Any:
    url = f"https://devops.aliyun.com{path}"
    r = s.post(url, json=payload, timeout=30)
    try:
        body = r.json()
    except Exception:
        body = {"_text": r.text[:500]}
    return {"status_code": r.status_code, "body": body}


def main() -> None:
    s = session()
    out: dict[str, Any] = {"org": ORG, "space": SPACE, "probes": {}}

    # 1) workitem types in project
    candidates = [
        (
            "types_by_space",
            "GET",
            f"/projex/api/workspace/project/{SPACE}/workitem/type",
            None,
        ),
        (
            "types_list",
            "GET",
            "/projex/api/workitem/workitemType/list",
            {"spaceIdentifier": SPACE, "spaceType": "Project", "organizationId": ORG},
        ),
        (
            "types_search",
            "GET",
            "/projex/api/workitem/workitem_type/list",
            {"spaceIdentifier": SPACE, "category": "Bug"},
        ),
        (
            "types_category_Bug",
            "GET",
            "/projex/api/workitem/workitemType",
            {
                "spaceIdentifier": SPACE,
                "spaceType": "Project",
                "categoryIdentifier": "Bug",
            },
        ),
    ]

    for name, method, path, params in candidates:
        if method == "GET":
            out["probes"][name] = try_get(s, path, params)

    # 2) workflow status for Bug
    status_paths = [
        (
            "wf_bug",
            "/projex/api/workitem/workitem_type/workflow/status",
            {
                "spaceIdentifier": SPACE,
                "spaceType": "Project",
                "workitemCategoryIdentifier": "Bug",
            },
        ),
        (
            "wf_bug2",
            "/projex/api/workitem/workflow/status/list",
            {
                "spaceIdentifier": SPACE,
                "spaceType": "Project",
                "categoryIdentifier": "Bug",
            },
        ),
        (
            "wf_bug3",
            "/projex/api/workitem/status/list",
            {"spaceIdentifier": SPACE, "categoryIdentifier": "Bug"},
        ),
    ]
    for name, path, params in status_paths:
        out["probes"][name] = try_get(s, path, params)

    # 3) search recent bugs
    search_payloads = [
        (
            "search_bug_v1",
            "/projex/api/workitem/workitem/list",
            {
                "spaceIdentifier": SPACE,
                "spaceType": "Project",
                "category": "Bug",
                "toPage": 1,
                "pageSize": 5,
                "conditions": json.dumps({"conditionGroups": [[]]}),
            },
        ),
        (
            "search_bug_v2",
            "/projex/api/workitem/workitem/list",
            {
                "spaceId": SPACE,
                "category": "Bug",
                "toPage": 1,
                "pageSize": 5,
            },
        ),
    ]
    for name, path, payload in search_payloads:
        out["probes"][name] = try_post(s, path, payload)

    # 4) OpenAPI-style under same cookie (sometimes works)
    out["probes"]["openapi_types"] = try_get(
        s,
        f"/oapi/v1/projex/organizations/{ORG}/projects/{SPACE}/workitemTypes",
        {"category": "Bug"},
    )
    out["probes"]["openapi_wf"] = try_get(
        s,
        f"/oapi/v1/projex/organizations/{ORG}/workitems/workflow/statuses",
        {
            "spaceType": "Project",
            "spaceIdentifier": SPACE,
            "workitemCategoryIdentifier": "Bug",
        },
    )

    print(json.dumps(out, ensure_ascii=False, indent=2)[:50000])


if __name__ == "__main__":
    main()
