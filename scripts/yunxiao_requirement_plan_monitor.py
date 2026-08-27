#!/usr/bin/env python3
"""Monitor new Yunxiao requirements and create idempotent TestHub plans.

The monitor only creates plans for requirements whose subject contains the exact
marker ``【新增】``. Existing testcase matches are reported for confirmation; this
script never plans/adds testcases because Yunxiao does not expose that write in
the public OAPI.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests


DEFAULT_ENDPOINT = "https://openapi-rdc.aliyuncs.com"
DEFAULT_PROJECT_CODE = "01_ONEOS"
DEFAULT_PROJECT_ID = "1280be963a5a2cc126a4118dca"
DEFAULT_MANAGER_NAME = "谢佳伟"
TITLE_MARKER = "【新增】"
SHANGHAI_TZ = timezone(timedelta(hours=8))
GENERIC_PREFIXES = ("新增", "增加", "支持", "实现", "需求", "功能")
GENERIC_SUFFIXES = ("需求", "功能", "能力", "优化")


class MonitorError(RuntimeError):
    """A safe, user-actionable monitor failure."""


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat(timespec="seconds")


def redact(text: str, token: str) -> str:
    result = str(text)
    if token:
        result = result.replace(token, "***")
    result = re.sub(r"pt-[A-Za-z0-9_\-]+", "pt-***", result)
    return result


def require_config() -> dict[str, str]:
    token = os.environ.get("ALIBABA_CLOUD_YUNXIAO_ACCESS_TOKEN", "").strip()
    organization_id = os.environ.get("ALIBABA_CLOUD_YUNXIAO_ORGANIZATION_ID", "").strip()
    missing = []
    if not token:
        missing.append("ALIBABA_CLOUD_YUNXIAO_ACCESS_TOKEN")
    if not organization_id:
        missing.append("ALIBABA_CLOUD_YUNXIAO_ORGANIZATION_ID")
    if missing:
        raise MonitorError(
            "AUTH_CONFIG_MISSING：缺少 " + ", ".join(missing)
            + "；本轮未读取需求、未创建测试计划。请在本机安全配置环境变量，禁止在聊天中粘贴令牌。"
        )
    endpoint = os.environ.get("ALIBABA_CLOUD_YUNXIAO_ENDPOINT", DEFAULT_ENDPOINT).strip().rstrip("/")
    if not endpoint.startswith("https://"):
        raise MonitorError("ALIBABA_CLOUD_YUNXIAO_ENDPOINT 必须是 https:// 接入点。")
    return {"token": token, "organizationId": organization_id, "endpoint": endpoint}


def default_state_path() -> Path:
    local = os.environ.get("LOCALAPPDATA", "").strip()
    root = Path(local) if local else Path(tempfile.gettempdir())
    return root / "OneOS" / "YunxiaoQA" / "requirement-testplan-monitor.json"


def default_receipt_path() -> Path:
    root = Path(os.environ.get("TEMP", tempfile.gettempdir())) / "OneOS" / "YunxiaoQA" / "receipts"
    stamp = datetime.now(SHANGHAI_TZ).strftime("%Y%m%d-%H%M%S")
    return root / f"requirement-testplan-monitor-{stamp}.json"


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schemaVersion": "oneos.yunxiao-requirement-plan-monitor/v1", "requirements": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MonitorError(f"状态文件无法读取：{path}：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("requirements", {}), dict):
        raise MonitorError(f"状态文件格式无效：{path}")
    data.setdefault("schemaVersion", "oneos.yunxiao-requirement-plan-monitor/v1")
    data.setdefault("requirements", {})
    return data


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def qualifies(subject: str) -> bool:
    return TITLE_MARKER in str(subject)


def normalize_plan_name(subject: str, max_length: int = 40) -> str:
    text = str(subject).replace(TITLE_MARKER, " ")
    text = re.sub(r"\s+", " ", text).strip(" -_—:：;；,，。")
    text = re.sub(r"^[\[【][^\]】]+[\]】]\s*", "", text).strip()
    if not text:
        text = "新增需求测试"
    return text[:max_length].rstrip()


def case_keywords(subject: str) -> list[str]:
    """Derive strict-to-broad subject keywords, keeping broad terms >=2 chars."""
    full = normalize_plan_name(subject, max_length=80)
    candidates = [full]
    compact = full
    for prefix in GENERIC_PREFIXES:
        if compact.startswith(prefix) and len(compact) > len(prefix) + 1:
            compact = compact[len(prefix):].lstrip(" -_—:：")
            break
    for suffix in GENERIC_SUFFIXES:
        if compact.endswith(suffix) and len(compact) > len(suffix) + 1:
            compact = compact[:-len(suffix)].rstrip(" -_—:：")
            break
    candidates.append(compact)
    candidates.extend(re.split(r"[、,，;；:：/|]+", compact))
    result: list[str] = []
    for value in candidates:
        value = re.sub(r"\s+", " ", value).strip()
        if len(value) >= 2 and value not in result:
            result.append(value)
    return result[:3]


def plan_dates(today: date | None = None) -> tuple[str, str]:
    start = today or datetime.now(SHANGHAI_TZ).date()
    return start.isoformat(), (start + timedelta(days=14)).isoformat()


def item_id(item: dict[str, Any]) -> str:
    for key in ("id", "identifier", "workitemIdentifier", "testPlanIdentifier"):
        if item.get(key):
            return str(item[key])
    return ""


def sprint_id(requirement: dict[str, Any]) -> str:
    sprint = requirement.get("sprint")
    if isinstance(sprint, dict):
        return str(sprint.get("id") or sprint.get("identifier") or "")
    return str(requirement.get("sprintIdentifier") or "")


def exact_named(items: Iterable[dict[str, Any]], name: str, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    return [item for item in items if any(str(item.get(key) or "") == name for key in keys)]


class YunxiaoOAPI:
    def __init__(self, endpoint: str, organization_id: str, token: str, timeout: int = 30):
        self.endpoint = endpoint.rstrip("/")
        self.organization_id = organization_id
        self.token = token
        self.timeout = timeout
        self.session = requests.Session()

    @property
    def prefix(self) -> str:
        return f"/oapi/v1"

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                body: dict[str, Any] | None = None) -> tuple[Any, dict[str, str]]:
        url = self.endpoint + path
        try:
            response = self.session.request(
                method,
                url,
                params=params,
                json=body,
                headers={"Content-Type": "application/json", "x-yunxiao-token": self.token},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise MonitorError(f"云效 OpenAPI 请求失败：{redact(str(exc), self.token)}") from exc
        if response.status_code >= 400:
            message = redact(response.text[:800], self.token)
            raise MonitorError(f"云效 OpenAPI {response.status_code}：{message}")
        if not response.content:
            data: Any = None
        else:
            try:
                data = response.json()
            except ValueError as exc:
                raise MonitorError("云效 OpenAPI 返回了非 JSON 内容。") from exc
        return data, {key.lower(): value for key, value in response.headers.items()}

    def org_path(self, service: str, suffix: str) -> str:
        return f"{self.prefix}/{service}/organizations/{self.organization_id}{suffix}"

    def get_project(self, project_id: str) -> dict[str, Any]:
        value, _ = self.request("GET", self.org_path("projex", f"/projects/{project_id}"))
        if not isinstance(value, dict):
            raise MonitorError("项目回读格式无效。")
        return value

    def find_member(self, name: str) -> dict[str, Any]:
        value, _ = self.request(
            "POST",
            self.org_path("platform", "/members:search"),
            body={"page": 1, "perPage": 100, "query": name, "statuses": ["ENABLED"]},
        )
        items = value if isinstance(value, list) else []
        matches = exact_named([item for item in items if isinstance(item, dict)], name, ("name",))
        if len(matches) != 1:
            raise MonitorError(f"人员校验失败：启用成员中“{name}”精确匹配到 {len(matches)} 人，必须唯一。")
        if not (matches[0].get("userId") or matches[0].get("id")):
            raise MonitorError(f"人员“{name}”缺少 userId。")
        return matches[0]

    def search_requirements(self, project_id: str, marker: str, max_pages: int = 10) -> list[dict[str, Any]]:
        condition = {
            "conditionGroups": [[{
                "fieldIdentifier": "subject",
                "operator": "CONTAINS",
                "value": [marker],
                "toValue": None,
                "className": "string",
                "format": "input",
            }]]
        }
        result: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            value, headers = self.request(
                "POST",
                self.org_path("projex", "/workitems:search"),
                body={
                    "category": "Req",
                    "conditions": json.dumps(condition, ensure_ascii=False, separators=(",", ":")),
                    "orderBy": "gmtCreate",
                    "page": page,
                    "perPage": 200,
                    "sort": "desc",
                    "spaceId": project_id,
                    "spaceType": "Project",
                },
            )
            items = value if isinstance(value, list) else []
            result.extend(item for item in items if isinstance(item, dict) and qualifies(str(item.get("subject") or "")))
            total_pages = int(headers.get("x-total-pages") or 0)
            if len(items) < 200 or (total_pages and page >= total_pages):
                break
        return result

    def list_test_plans(self, project_id: str, sprint_identifier: str, name: str) -> list[dict[str, Any]]:
        value, _ = self.request(
            "POST",
            self.org_path("projex", "/testPlan/list"),
            params={
                "page": 1,
                "perPage": 1000,
                "projectIdentifier": project_id,
                "sprintIdentifier": sprint_identifier,
                "name": name,
            },
        )
        return [item for item in (value if isinstance(value, list) else []) if isinstance(item, dict)]

    def create_test_plan(self, body: dict[str, Any]) -> dict[str, Any]:
        value, _ = self.request("POST", self.org_path("testhub", "/testPlans"), body=body)
        if not isinstance(value, dict) or not item_id(value):
            raise MonitorError("创建测试计划返回值缺少计划 ID。")
        return value

    def list_test_repos(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for page in range(1, 101):
            value, headers = self.request(
                "GET", self.org_path("testhub", "/testRepo/list"), params={"page": page, "perPage": 100}
            )
            items = value if isinstance(value, list) else []
            result.extend(item for item in items if isinstance(item, dict))
            total_pages = int(headers.get("x-total-pages") or 0)
            if len(items) < 100 or (total_pages and page >= total_pages):
                break
        return result

    def search_cases(self, repo_id: str, keyword: str) -> list[dict[str, Any]]:
        condition = {
            "conditionGroups": [[{
                "fieldIdentifier": "subject",
                "operator": "CONTAINS",
                "value": [keyword],
                "toValue": None,
                "className": "string",
                "format": "input",
            }]]
        }
        result: list[dict[str, Any]] = []
        for page in range(1, 101):
            value, headers = self.request(
                "POST",
                self.org_path("testhub", f"/testRepos/{repo_id}/testcases:search"),
                body={
                    "conditions": json.dumps(condition, ensure_ascii=False, separators=(",", ":")),
                    "orderBy": "gmtCreate",
                    "page": page,
                    "perPage": 200,
                    "sort": "desc",
                },
            )
            items = value if isinstance(value, list) else []
            result.extend(item for item in items if isinstance(item, dict))
            total_pages = int(headers.get("x-total-pages") or 0)
            if len(items) < 200 or (total_pages and page >= total_pages):
                break
        return result


def validate_project(project: dict[str, Any], expected_code: str, expected_id: str) -> None:
    actual_id = item_id(project)
    actual_code = str(project.get("customCode") or "")
    actual_name = str(project.get("name") or "")
    if actual_id != expected_id:
        raise MonitorError(f"项目回读 ID 不一致：期望 {expected_id}，实际 {actual_id or '-'}。")
    if expected_code not in (actual_code, actual_name):
        raise MonitorError(
            f"项目回读不一致：期望 {expected_code}，实际 customCode={actual_code or '-'} name={actual_name or '-'}。"
        )


def find_existing_plan(plans: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    exact = exact_named(plans, name, ("name",))
    return exact[0] if exact else None


def case_summary(case: dict[str, Any], repo: dict[str, Any], keyword: str) -> dict[str, Any]:
    return {
        "testRepoId": str(repo.get("testRepoIdentifier") or repo.get("id") or ""),
        "testRepoName": str(repo.get("name") or ""),
        "testcaseId": item_id(case),
        "customCode": case.get("customCode"),
        "subject": case.get("subject"),
        "matchedKeyword": keyword,
    }


def search_all_visible_cases(client: YunxiaoOAPI, subject: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    repos = client.list_test_repos()
    keywords = case_keywords(subject)
    matches: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for repo in repos:
        repo_id = str(repo.get("testRepoIdentifier") or repo.get("id") or "")
        if not repo_id:
            continue
        for keyword in keywords:
            try:
                cases = client.search_cases(repo_id, keyword)
            except MonitorError as exc:
                errors.append({"testRepoId": repo_id, "testRepoName": str(repo.get("name") or ""), "error": str(exc)})
                break
            for case in cases:
                key = (repo_id, item_id(case))
                if not key[1] or key in seen:
                    continue
                seen.add(key)
                matches.append(case_summary(case, repo, keyword))
            if cases:
                break
    return matches, errors


def make_plan_body(requirement: dict[str, Any], project_id: str, manager_id: str,
                   name: str, sprint_identifier: str, today: date | None = None) -> dict[str, Any]:
    start, end = plan_dates(today)
    serial = str(requirement.get("serialNumber") or "")
    requirement_identifier = item_id(requirement)
    description = (
        "由 YunxiaoQA 每日需求监测自动创建。\n"
        f"需求：{serial or requirement_identifier} {requirement.get('subject') or ''}\n"
        f"幂等标识：YunxiaoQA requirement={requirement_identifier}"
    )
    return {
        "description": description,
        "endDate": end,
        "managerIdentifiers": [manager_id],
        "memberIdentifiers": [manager_id],
        "name": name,
        "projectIdentifier": project_id,
        "scope": "public",
        "sprintIdentifier": sprint_identifier,
        "startDate": start,
    }


def process_requirement(client: YunxiaoOAPI, requirement: dict[str, Any], *, project_id: str,
                        manager_id: str, apply: bool) -> dict[str, Any]:
    requirement_identifier = item_id(requirement)
    subject = str(requirement.get("subject") or "")
    serial = str(requirement.get("serialNumber") or "")
    sprint_identifier = sprint_id(requirement)
    base = {
        "requirementId": requirement_identifier,
        "serialNumber": serial,
        "subject": subject,
        "sprintIdentifier": sprint_identifier,
    }
    if not requirement_identifier:
        return {**base, "status": "blocked", "error": "需求缺少内部 ID。"}
    if not sprint_identifier:
        return {**base, "status": "pending", "error": "需求未选择迭代；未创建测试计划，将在下次监测重试。"}
    plan_name = normalize_plan_name(subject)
    body = make_plan_body(requirement, project_id, manager_id, plan_name, sprint_identifier)
    plans = client.list_test_plans(project_id, sprint_identifier, plan_name)
    existing = find_existing_plan(plans, plan_name)
    if not apply and not existing:
        return {**base, "status": "preflight", "plan": body, "plannedAction": "create-test-plan"}

    created = False
    plan = existing
    if plan is None:
        created_response = client.create_test_plan(body)
        created = True
        created_id = item_id(created_response)
        plan = {"testPlanIdentifier": created_id, "name": plan_name}
        for attempt in range(3):
            readback = client.list_test_plans(project_id, sprint_identifier, plan_name)
            matched = next((item for item in readback if item_id(item) == created_id), None)
            if matched:
                plan = matched
                break
            if attempt < 2:
                time.sleep(1)

    plan_id = item_id(plan or {})
    if not plan_id:
        return {**base, "status": "blocked", "error": "测试计划创建/查重后仍缺少计划 ID，已停止用例扫描。"}

    matches, scan_errors = search_all_visible_cases(client, subject)
    status = "awaiting-case-confirmation" if matches else "no-matching-cases"
    return {
        **base,
        "status": status,
        "plan": {
            "id": plan_id,
            "name": plan_name,
            "created": created,
            "startDate": body["startDate"],
            "endDate": body["endDate"],
            "manager": DEFAULT_MANAGER_NAME,
            "member": DEFAULT_MANAGER_NAME,
            "projectIdentifier": project_id,
            "sprintIdentifier": sprint_identifier,
        },
        "caseMatches": matches,
        "caseScanErrors": scan_errors,
        "caseAddPolicy": "notify-and-confirm-before-add",
    }


def run(args: argparse.Namespace, client: YunxiaoOAPI) -> dict[str, Any]:
    project = client.get_project(args.project_id)
    validate_project(project, args.project_code, args.project_id)
    member = client.find_member(args.manager_name)
    manager_id = str(member.get("userId") or member.get("id"))
    requirements = client.search_requirements(args.project_id, TITLE_MARKER, args.max_pages)
    state = load_state(args.state_file)
    receipt: dict[str, Any] = {
        "schemaVersion": "oneos.yunxiao-requirement-plan-monitor-run/v1",
        "generatedAt": now_iso(),
        "mode": "apply" if args.apply else "preflight",
        "frequency": "daily",
        "rule": {
            "titleMarker": TITLE_MARKER,
            "projectCode": args.project_code,
            "projectId": args.project_id,
            "manager": args.manager_name,
            "member": args.manager_name,
            "dateRangeDays": 14,
            "testRepos": "all-visible",
            "caseAddPolicy": "notify-and-confirm-before-add",
        },
        "projectReadback": {"id": item_id(project), "customCode": project.get("customCode"), "name": project.get("name")},
        "memberReadback": {"id": manager_id, "name": member.get("name"), "status": member.get("status")},
        "qualifiedRequirementCount": len(requirements),
        "results": [],
    }

    if not state.get("initializedAt") and not args.bootstrap_existing:
        receipt["bootstrap"] = {
            "status": "baseline-created" if args.apply else "baseline-planned",
            "historicalQualifiedRequirementsIgnored": len(requirements),
            "note": "首次成功运行仅建立基线，不为历史需求创建计划。",
        }
        if args.apply:
            state["initializedAt"] = now_iso()
            for requirement in requirements:
                identifier = item_id(requirement)
                if identifier:
                    state["requirements"][identifier] = {
                        "status": "baseline",
                        "subject": requirement.get("subject"),
                        "serialNumber": requirement.get("serialNumber"),
                        "observedAt": now_iso(),
                    }
            write_json(args.state_file, state)
        return receipt

    state.setdefault("initializedAt", now_iso())
    known = state["requirements"]
    for requirement in reversed(requirements):
        identifier = item_id(requirement)
        prior = known.get(identifier, {}) if identifier else {}
        if prior.get("status") in {"baseline", "awaiting-case-confirmation", "no-matching-cases", "created", "reused"}:
            continue
        result = process_requirement(
            client,
            requirement,
            project_id=args.project_id,
            manager_id=manager_id,
            apply=args.apply,
        )
        receipt["results"].append(result)
        if args.apply and identifier:
            known[identifier] = {**result, "observedAt": now_iso()}
    if args.apply:
        state["lastSuccessfulScanAt"] = now_iso()
        write_json(args.state_file, state)
    receipt["newRequirementCount"] = len(receipt["results"])
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="每日监测【新增】需求并创建云效测试计划")
    parser.add_argument("--project-code", default=DEFAULT_PROJECT_CODE)
    parser.add_argument("--project-id", default=os.environ.get("YUNXIAO_QA_PROJECT_ID", DEFAULT_PROJECT_ID))
    parser.add_argument("--manager-name", default=DEFAULT_MANAGER_NAME)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--state-file", type=Path, default=default_state_path())
    parser.add_argument("--receipt", type=Path, default=default_receipt_path())
    parser.add_argument("--bootstrap-existing", action="store_true", help="首次运行也处理当前匹配需求（默认只建立基线）")
    parser.add_argument("--apply", action="store_true", help="创建计划并写入幂等状态；省略则仅预检")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = require_config()
    client = YunxiaoOAPI(config["endpoint"], config["organizationId"], config["token"])
    receipt = run(args, client)
    write_json(args.receipt, receipt)
    summary = {
        "ok": True,
        "mode": receipt["mode"],
        "frequency": receipt["frequency"],
        "bootstrap": receipt.get("bootstrap"),
        "newRequirementCount": receipt.get("newRequirementCount", 0),
        "results": receipt["results"],
        "receipt": str(args.receipt),
        "stateFile": str(args.state_file),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MonitorError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)

