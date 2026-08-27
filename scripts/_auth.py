#!/usr/bin/env python
"""YunxiaoQA 共享鉴权与 HTTP 会话。"""
from __future__ import annotations

import json
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = json.loads((ROOT / "assets" / "runtime-ids.json").read_text(encoding="utf-8"))
SPACE = (
    (RUNTIME.get("project") or {}).get("last_selected") or {}
).get("spaceIdentifier") or "1280be963a5a2cc126a4118dca"
COOKIE_FALLBACK = Path(tempfile.gettempdir()) / "yunxiao_cookies.json"

AUTH_HELP = """云效会话失效或缺失。请任选一种方式刷新后重试：

1) 推荐：Chrome 已登录 devops.aliyun.com 后执行
   skill-run refresh_cookies.py

2) 手工：将 Cookie 写入当前系统临时目录的 yunxiao_cookies.json，至少含：
   {"XSRF-TOKEN":"...","AONE_SESSION":"..."}

3) 探测：skill-run check_auth.py

注意：不要把 Cookie 写入 Skill 仓库或缺陷描述。"""


class AuthError(RuntimeError):
    """会话缺失或 401/鉴权失败。"""


def load_people() -> dict[str, Any]:
    """只读取本 Skill 自带的人员目录，禁止跨 Skill 路径回退。"""
    merged: dict[str, Any] = {}
    local = RUNTIME.get("people") or {}
    if isinstance(local, dict):
        merged.update(local)
    return merged


def resolve_person(name_or_id: str) -> tuple[str, str]:
    """返回 (identifier, displayName)。支持直接传 user id。"""
    key = (name_or_id or "").strip()
    if not key:
        raise ValueError("人员为空")
    if len(key) >= 20 and key.isalnum():
        return key, key
    people = load_people()
    aliases = {
        "王冕": "wangmian",
        "何斐": "hefei",
        "沈辰": "shenchen",
    }
    slug_hint = aliases.get(key, key)
    for slug, meta in people.items():
        if not isinstance(meta, dict):
            continue
        names = {
            slug,
            meta.get("displayName") or "",
            meta.get("name") or "",
            *(meta.get("aliases") or []),
        }
        if key in names or slug_hint == slug or key.lower() == slug.lower():
            pid = meta.get("identifier")
            if not pid:
                continue
            return pid, meta.get("displayName") or slug
    raise ValueError(
        f"无法解析人员「{key}」；请传云效 user id，或写入本 Skill assets/runtime-ids.json → people"
    )

def load_jar() -> dict[str, str]:
    jar: dict[str, str] = {}
    if COOKIE_FALLBACK.exists():
        raw = json.loads(COOKIE_FALLBACK.read_text())
        if isinstance(raw, dict) and "XSRF-TOKEN" in raw:
            jar = {k: v for k, v in raw.items() if isinstance(v, str)}
        elif isinstance(raw, dict) and "cookies" in raw:
            jar = {c["name"]: c["value"] for c in raw["cookies"] if "name" in c}
    if not jar.get("XSRF-TOKEN") and not jar.get("AONE_SESSION"):
        try:
            import browser_cookie3

            for domain in (".aliyun.com", "devops.aliyun.com", ".devops.aliyun.com"):
                try:
                    for c in browser_cookie3.chrome(domain_name=domain):
                        jar[c.name] = c.value
                except Exception:
                    pass
        except Exception:
            pass
    if not jar.get("XSRF-TOKEN") and not jar.get("AONE_SESSION"):
        raise AuthError(AUTH_HELP)
    return jar


def dump_chrome_cookies(path: Path | None = None) -> dict[str, str]:
    """从 Chrome 导出云效相关 Cookie 到 path（默认使用当前系统临时目录）。"""
    try:
        import browser_cookie3
    except ImportError as e:
        raise AuthError(
            "未安装 browser_cookie3，无法自动刷新。\n"
            "请为当前 Skill 启动器选定的 Python 3 安装 browser_cookie3。\n\n" + AUTH_HELP
        ) from e
    jar: dict[str, str] = {}
    for domain in (".aliyun.com", "devops.aliyun.com", ".devops.aliyun.com"):
        try:
            for c in browser_cookie3.chrome(domain_name=domain):
                jar[c.name] = c.value
        except Exception:
            pass
    if not jar.get("XSRF-TOKEN") and not jar.get("AONE_SESSION"):
        raise AuthError(
            "Chrome 中未读到有效云效 Cookie。请先在 Chrome 打开并登录 "
            "https://devops.aliyun.com 后再执行 refresh_cookies.py。\n\n" + AUTH_HELP
        )
    out = path or COOKIE_FALLBACK
    # 只保留关键键，避免把整库 Cookie 写进临时文件过大
    keep = {
        k: v
        for k, v in jar.items()
        if k
        in (
            "XSRF-TOKEN",
            "AONE_SESSION",
            "login_aliyunid_ticket",
            "login_aliyunid_csrf",
            "cna",
            "isg",
            "tfstk",
        )
        or k.lower().startswith("aliyun")
        or "SESSION" in k.upper()
        or "TOKEN" in k.upper()
    }
    if "XSRF-TOKEN" not in keep and "XSRF-TOKEN" in jar:
        keep["XSRF-TOKEN"] = jar["XSRF-TOKEN"]
    if "AONE_SESSION" not in keep and "AONE_SESSION" in jar:
        keep["AONE_SESSION"] = jar["AONE_SESSION"]
    # 仍不够时写全量 jar（仍仅写入本机系统临时目录）
    payload = keep if keep.get("XSRF-TOKEN") or keep.get("AONE_SESSION") else jar
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def session(*, probe: bool = False) -> requests.Session:
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
    if probe:
        probe_auth(s)
    return s


def _raise_if_auth_failed(resp: requests.Response, data: Any | None = None) -> None:
    if resp.status_code in (401, 403):
        raise AuthError(f"HTTP {resp.status_code} 鉴权失败。\n\n{AUTH_HELP}")
    if isinstance(data, dict):
        code = data.get("code")
        msg = str(data.get("errorMsg") or data.get("message") or "")
        if code in (401, 403) or "未登录" in msg or "登录" in msg and "失效" in msg:
            raise AuthError(f"接口返回鉴权失败：{msg or data}\n\n{AUTH_HELP}")


def probe_auth(s: requests.Session, space: str | None = None) -> dict[str, Any]:
    """轻量探测会话是否可用。成功返回摘要；失败抛 AuthError。"""
    sp = space or SPACE
    r = s.post(
        "https://devops.aliyun.com/projex/api/workitem/workitem/list?_input_charset=utf-8",
        json={
            "spaceIdentifier": sp,
            "category": "Bug",
            "toPage": 1,
            "pageSize": 1,
            "searchType": "LIST",
            "conditions": json.dumps({"conditionGroups": [[]]}),
        },
        timeout=30,
    )
    try:
        data = r.json()
    except Exception:
        data = None
    _raise_if_auth_failed(r, data)
    if r.status_code >= 400:
        raise AuthError(f"探测失败 HTTP {r.status_code}\n\n{AUTH_HELP}")
    if isinstance(data, dict) and data.get("errorMsg") and data.get("code") not in (200, None):
        _raise_if_auth_failed(r, data)
        raise AuthError(f"探测失败：{data.get('errorMsg')}\n\n{AUTH_HELP}")
    return {
        "ok": True,
        "space": sp,
        "httpStatus": r.status_code,
        "apiCode": (data or {}).get("code") if isinstance(data, dict) else None,
        "cookieFile": str(COOKIE_FALLBACK) if COOKIE_FALLBACK.exists() else None,
    }


def space_id(override: str | None = None) -> str:
    return override or SPACE


def status_id(kind: str, name: str) -> str:
    block = RUNTIME["status"][kind]
    if name not in block or not isinstance(block[name], str):
        raise KeyError(f"未知状态 {kind}.{name}")
    return block[name]


def post_list(
    s: requests.Session,
    *,
    category: str,
    space: str,
    conditions: list[list[dict[str, Any]]] | None = None,
    to_page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    body = {
        "spaceIdentifier": space,
        "category": category,
        "toPage": to_page,
        "pageSize": page_size,
        "searchType": "LIST",
        "conditions": json.dumps({"conditionGroups": conditions or [[]]}),
    }
    r = s.post(
        "https://devops.aliyun.com/projex/api/workitem/workitem/list?_input_charset=utf-8",
        json=body,
        timeout=45,
    )
    try:
        data = r.json()
    except Exception:
        data = None
    _raise_if_auth_failed(r, data)
    r.raise_for_status()
    if data is None:
        raise RuntimeError("list 响应非 JSON")
    if data.get("code") not in (200, None) and data.get("errorMsg"):
        raise RuntimeError(data.get("errorMsg") or data)
    return data


def get_workitem(s: requests.Session, workitem_id: str) -> dict[str, Any]:
    r = s.get(
        f"https://devops.aliyun.com/projex/api/workitem/workitem/{workitem_id}?_input_charset=utf-8",
        timeout=45,
    )
    try:
        data = r.json()
    except Exception:
        data = None
    _raise_if_auth_failed(r, data)
    r.raise_for_status()
    if not isinstance(data, dict) or data.get("code") not in (200, None):
        raise RuntimeError((data or {}).get("errorMsg") if isinstance(data, dict) else data)
    result = data.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(data)
    return result


def get_workitem_extra(s: requests.Session, workitem_id: str) -> Any:
    """读取验证者等扩展字段。"""
    r = s.get(
        f"https://devops.aliyun.com/projex/api/workitem/workitem/{workitem_id}/extra",
        timeout=45,
    )
    try:
        data = r.json()
    except Exception:
        data = None
    _raise_if_auth_failed(r, data)
    r.raise_for_status()
    if not isinstance(data, dict) or data.get("code") not in (200, None):
        raise RuntimeError((data or {}).get("errorMsg") if isinstance(data, dict) else data)
    return data.get("result")


def set_workitem_property(
    s: requests.Session,
    workitem_id: str,
    *,
    property_key: str,
    property_value: Any,
    operate_type: str = "COVER",
) -> None:
    """更新单个工作项字段；调用方必须随后回读。"""
    r = s.patch(
        f"https://devops.aliyun.com/projex/api/workitem/workitem/{workitem_id}?_input_charset=utf-8",
        json={
            "workitemIdentifier": workitem_id,
            "propertyKey": property_key,
            "propertyValue": property_value,
            "operateType": operate_type,
        },
        timeout=45,
    )
    try:
        data = r.json()
    except Exception:
        data = None
    _raise_if_auth_failed(r, data)
    r.raise_for_status()
    if isinstance(data, dict) and data.get("code") not in (200, None):
        raise RuntimeError(data.get("errorMsg") or data)


def list_relations(
    s: requests.Session,
    workitem_id: str,
    *,
    category: str,
    forward: bool = True,
) -> list[dict[str, Any]]:
    r = s.get(
        f"https://devops.aliyun.com/projex/api/workitem/v2/workitem/{workitem_id}/relation/workitem/list/by-relation-category",
        params={"category": category, "isForward": str(forward).lower()},
        timeout=45,
    )
    try:
        data = r.json()
    except Exception:
        data = None
    _raise_if_auth_failed(r, data)
    r.raise_for_status()
    if not isinstance(data, dict):
        return []
    return list(data.get("result") or [])


def list_associated(
    s: requests.Session, workitem_id: str, *, forward: bool = True
) -> list[dict[str, Any]]:
    return list_relations(s, workitem_id, category="ASSOCIATED", forward=forward)


def list_parent_sub(
    s: requests.Session, workitem_id: str, *, forward: bool = True
) -> list[dict[str, Any]]:
    """forward=True：当前项的子项；forward=False：父项方向。"""
    return list_relations(s, workitem_id, category="PARENT_SUB", forward=forward)


def add_relation(
    s: requests.Session,
    workitem_id: str,
    *,
    to_workitem_id: str,
    relation: str = "ASSOCIATED",
) -> dict[str, Any]:
    r = s.post(
        f"https://devops.aliyun.com/projex/api/workitem/workitem/{workitem_id}/relation/record?_input_charset=utf-8",
        json={
            "relationIdentifier": relation,
            "toWorkitemIdentifier": to_workitem_id,
        },
        timeout=45,
    )
    try:
        data = r.json()
    except Exception:
        data = None
    _raise_if_auth_failed(r, data)
    if not isinstance(data, dict):
        raise RuntimeError(data)
    return data


def _is_req_item(it: dict[str, Any]) -> bool:
    cat = (it.get("category") or it.get("categoryIdentifier") or "").strip()
    if cat in ("Req", "Requirement"):
        return True
    wtype = it.get("workitemType")
    if isinstance(wtype, dict):
        name = (
            (wtype.get("name") or "")
            + (wtype.get("displayName") or "")
            + (wtype.get("identifier") or "")
        )
        if "需求" in name or "Req" in name:
            return True
    return False


def resolve_req_from_test(
    s: requests.Session, test_id: str
) -> dict[str, Any] | None:
    """从【测试】追溯产品需求：自身 ASSOCIATED → 父【交付】ASSOCIATED → 兄弟【开发】ASSOCIATED。"""
    seen: set[str] = set()

    def pick(items: list[dict[str, Any]]) -> dict[str, Any] | None:
        for it in items:
            wid = it.get("identifier")
            if not wid or wid in seen:
                continue
            seen.add(wid)
            full = it
            if not _is_req_item(full):
                try:
                    full = get_workitem(s, wid)
                except Exception:
                    continue
            if _is_req_item(full):
                return brief_item(full)
        return None

    hit = pick(list_associated(s, test_id, forward=True)) or pick(
        list_associated(s, test_id, forward=False)
    )
    if hit:
        return hit

    parents = list_parent_sub(s, test_id, forward=False)
    for p in parents:
        pid = p.get("identifier")
        if not pid:
            continue
        hit = pick(list_associated(s, pid, forward=True)) or pick(
            list_associated(s, pid, forward=False)
        )
        if hit:
            return hit
        for child in list_parent_sub(s, pid, forward=True):
            subj = child.get("subject") or ""
            if not subj.startswith("【开发】"):
                continue
            cid = child.get("identifier")
            if not cid:
                continue
            hit = pick(list_associated(s, cid, forward=True)) or pick(
                list_associated(s, cid, forward=False)
            )
            if hit:
                return hit

    return None


def create_workitem(s: requests.Session, payload: dict[str, Any]) -> dict[str, Any]:
    url = "https://devops.aliyun.com/projex/api/workitem/workitem?_input_charset=utf-8"
    last: Any = None
    for method in ("POST", "PUT"):
        r = s.request(method, url, json=payload, timeout=60)
        try:
            data = r.json()
        except Exception:
            data = None
        _raise_if_auth_failed(r, data)
        last = data
        result = (data or {}).get("result") if isinstance(data, dict) else None
        if (
            r.status_code < 400
            and isinstance(data, dict)
            and data.get("code") == 200
            and isinstance(result, dict)
            and result.get("identifier")
        ):
            return result
    raise RuntimeError(last)


def set_document(s: requests.Session, workitem_id: str, html: str) -> None:
    r = s.patch(
        f"https://devops.aliyun.com/projex/api/workitem/workitem/{workitem_id}/document?_input_charset=utf-8",
        json={"content": html, "formatType": "RICHTEXT"},
        timeout=45,
    )
    try:
        data = r.json()
    except Exception:
        data = None
    _raise_if_auth_failed(r, data)
    # document patch 偶发非 200 体；不强制


def set_document_checked(s: requests.Session, workitem_id: str, html: str) -> None:
    """严格更新描述；用于证据等必须回读的受管区块。"""
    r = s.patch(
        f"https://devops.aliyun.com/projex/api/workitem/workitem/{workitem_id}/document?_input_charset=utf-8",
        json={"content": html, "formatType": "RICHTEXT"},
        timeout=45,
    )
    try:
        data = r.json()
    except Exception:
        data = None
    _raise_if_auth_failed(r, data)
    r.raise_for_status()
    if isinstance(data, dict) and data.get("code") not in (200, None):
        raise RuntimeError(data.get("errorMsg") or data)


def document_content(item: dict[str, Any]) -> str:
    """兼容 get_workitem 的几种描述字段形态。"""
    doc = item.get("document")
    if isinstance(doc, dict):
        return str(doc.get("content") or "")
    if isinstance(doc, str):
        return doc
    for key in ("description", "content"):
        value = item.get(key)
        if isinstance(value, str):
            return value
    return ""


def list_next_statuses(
    s: requests.Session, workitem_id: str, current_status_id: str
) -> list[dict[str, str]]:
    """读取当前工作项允许的下一状态，不依赖本地硬编码 ID。"""
    r = s.get(
        f"https://devops.aliyun.com/projex/api/workitem/workitem/{workitem_id}/nextStatus/list",
        params={
            "currentStatusIdentifier": current_status_id,
            "_input_charset": "utf-8",
        },
        timeout=45,
    )
    try:
        data = r.json()
    except Exception:
        data = None
    _raise_if_auth_failed(r, data)
    r.raise_for_status()
    if not isinstance(data, dict) or data.get("code") not in (200, None):
        raise RuntimeError((data or {}).get("errorMsg") if isinstance(data, dict) else data)
    raw = data.get("result") or []
    if isinstance(raw, dict):
        raw = raw.get("statuses") or raw.get("list") or raw.get("data") or []
    result: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        status = item.get("status") if isinstance(item.get("status"), dict) else item
        identifier = status.get("identifier") or status.get("statusIdentifier")
        name = status.get("displayName") or status.get("name") or status.get("statusName")
        if identifier and name:
            result.append({"identifier": str(identifier), "name": str(name)})
    return result


def resolve_next_status_id(
    s: requests.Session,
    workitem_id: str,
    current_status_id: str,
    target_name: str,
) -> str:
    choices = list_next_statuses(s, workitem_id, current_status_id)
    matches = [x for x in choices if x["name"].strip() == target_name.strip()]
    if len(matches) != 1:
        names = [x["name"] for x in choices]
        raise RuntimeError(
            f"状态门禁失败：目标「{target_name}」唯一命中数={len(matches)}；"
            f"当前可选={names}"
        )
    return matches[0]["identifier"]


def transit(
    s: requests.Session, workitem_id: str, from_status: str, to_status: str
) -> dict[str, Any]:
    r = s.post(
        f"https://devops.aliyun.com/projex/api/workitem/workitem/{workitem_id}/status/transit?_input_charset=utf-8",
        json={"fromStatus": from_status, "toStatus": to_status},
        timeout=45,
    )
    try:
        data = r.json()
    except Exception:
        data = None
    _raise_if_auth_failed(r, data)
    r.raise_for_status()
    if not isinstance(data, dict) or data.get("code") != 200 or data.get("result") is not True:
        raise RuntimeError((data or {}).get("errorMsg") if isinstance(data, dict) else data)
    return data


def format_serial(item: dict[str, Any]) -> str | None:
    """list/get 偶发返回裸数字；拼成 DEMO-126 / ONEOS-xx。"""
    raw = item.get("serialNumber")
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if "-" in s:
        return s
    space = item.get("space")
    code = None
    if isinstance(space, dict):
        code = space.get("customCode") or space.get("name")
    if not code:
        # 回退当前会话项目
        try:
            code = (RUNTIME.get("project") or {}).get("last_selected", {}).get(
                "customCode"
            )
        except Exception:
            code = None
    if code and s.isdigit():
        return f"{code}-{s}"
    return s


def brief_item(item: dict[str, Any]) -> dict[str, Any]:
    st = item.get("status") or item.get("workitemStatus") or {}
    if not isinstance(st, dict):
        st = {}
    assigned = item.get("assignedTo") or item.get("assignedToUser") or {}
    return {
        "id": item.get("identifier"),
        "serialNumber": format_serial(item),
        "subject": item.get("subject"),
        "status": st.get("displayName") or st.get("name"),
        "statusId": st.get("identifier"),
        "assignee": assigned.get("displayName") or assigned.get("realName"),
        "assigneeId": assigned.get("identifier"),
        "sprint": (item.get("sprint") or {}).get("name")
        if isinstance(item.get("sprint"), dict)
        else item.get("sprint"),
    }


def find_by_serial(
    s: requests.Session, *, space: str, category: str, serial: str
) -> dict[str, Any] | None:
    sn = serial.strip()
    bare = sn.split("-")[-1] if "-" in sn else sn

    def hit(it: dict[str, Any]) -> bool:
        raw = it.get("serialNumber")
        if raw is None:
            return False
        if str(raw) == sn or str(raw) == bare:
            return True
        if isinstance(raw, int) and bare.isdigit() and raw == int(bare):
            return True
        sraw = str(raw)
        if sraw.upper() == sn.upper():
            return True
        if "-" in sraw and sraw.split("-")[-1] == bare:
            return True
        return False

    # 先无条件扫一页（避免「编号搜索不合法」）；精确匹配
    try:
        data = post_list(s, category=category, space=space, page_size=100)
        for it in data.get("result") or []:
            if hit(it):
                return it
    except Exception:
        pass

    # 带项目前缀的完整编号偶发可用 CONTAINS
    if "-" in sn:
        try:
            conditions = [
                [
                    {
                        "className": "string",
                        "fieldIdentifier": "serialNumber",
                        "format": "input",
                        "operator": "CONTAINS",
                        "value": [sn],
                    }
                ]
            ]
            data = post_list(
                s, category=category, space=space, conditions=conditions, page_size=50
            )
            for it in data.get("result") or []:
                if hit(it):
                    return it
        except Exception:
            pass
    return None
