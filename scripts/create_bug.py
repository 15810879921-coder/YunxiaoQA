#!/usr/bin/env python
"""发起缺陷（本期 / 非本期）。

写操作：须先经 YunxiaoQA Plan 门禁确认后再执行（去掉 --dry-run）。

规则：
1. create 时 ASSOCIATED→【测试】（关联项；云效不允许缺陷作任务子项）——硬门禁，回读失败退出码 3。
2. 产品需求：点选/追溯后**写入描述作追溯记录**；本期不做 Cookie 事后 ASSOCIATED
   （第二挂常报「不能关联相同的工作项」；勿告警、勿伪造成功备注）。
3. 口令 --req 可覆盖自动追溯；点选确认后的编号才写入。
4. 独立建单和测试用例来源建单统一把验证者设置为当前登录用户；不接受验证者覆盖。

示例：
  skill-run create_bug.py --mode 本期 --title '[验证] …' \\
    --test-task DEMO-90 --assignee 沈辰 --dry-run

  skill-run create_bug.py --mode 本期 --source test-case \\
    --test-case CASE-1001 --title '[验证] …' --test-task DEMO-90 \\
    --assignee 沈辰 --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _auth import (  # noqa: E402
    RUNTIME,
    AuthError,
    brief_item,
    create_workitem,
    find_by_serial,
    get_workitem,
    get_workitem_extra,
    list_associated,
    post_list,
    resolve_person,
    resolve_req_from_test,
    session,
    set_document,
    set_workitem_property,
    space_id,
)

BUG_TYPE = RUNTIME["workitem_types"]["bug"]["identifier"]


def enum_options(field: dict) -> dict[str, str]:
    """剔除运行时字段元数据，只保留可选显示名→identifier。"""
    return {
        str(name): str(identifier)
        for name, identifier in field.items()
        if name not in {"fieldIdentifier", "name"} and isinstance(identifier, str)
    }


PRI = enum_options(RUNTIME["fields"]["priority"])
SEV = enum_options(RUNTIME["fields"]["seriousLevel"])


def resolve_target(
    s, space: str, *, sn: str | None, wid: str | None, categories: tuple[str, ...]
) -> dict:
    if wid:
        w = get_workitem(s, wid)
        return brief_item(w)
    if not sn:
        raise SystemExit("须提供编号 (--test-task / --delivery / --req) 或对应 --*-id")
    for cat in categories:
        it = find_by_serial(s, space=space, category=cat, serial=sn)
        if it:
            return brief_item(it)
    raise SystemExit(f"未找到工作项 {sn}（尝试类别 {categories}）")


def default_html(title: str, extra: str | None) -> str:
    body = extra or "<p>（请在 Plan 确认后补全现象/步骤/实际/期望）</p>"
    return f"""<h2>现象</h2>
<p>{title}</p>
<h2>环境</h2>
<p>项目：当前 space · 冒烟/日常发起</p>
<h2>复现步骤</h2>
<ol><li>见口令证据</li></ol>
<h2>实际结果</h2>
{body}
<h2>期望结果</h2>
<p>按验收标准通过</p>
<h2>初步定位</h2>
<p>分层：待确认（推断）</p>
"""


def relation_hit(items: list[dict], target_id: str) -> bool:
    return any(x.get("identifier") == target_id for x in items)


def has_associated(s, a_id: str, b_id: str) -> bool:
    both = list_associated(s, a_id, forward=True) + list_associated(s, a_id, forward=False)
    return relation_hit(both, b_id)


def find_exact_title_duplicates(s, space: str, title: str) -> list[dict]:
    """用 CONTAINS 缩小范围，再以标题完全一致判定重复缺陷。"""
    data = post_list(
        s,
        space=space,
        category="Bug",
        conditions=[
            [
                {
                    "className": "string",
                    "fieldIdentifier": "subject",
                    "format": "input",
                    "operator": "CONTAINS",
                    "value": [title],
                }
            ]
        ],
    )
    items = data.get("result") or []
    return [brief_item(item) for item in items if (item.get("subject") or "").strip() == title.strip()]


def tag_ids(value: object) -> set[str]:
    """兼容云效 tag 字段的对象、列表和嵌套响应形态。"""
    hits: set[str] = set()
    if isinstance(value, list):
        for item in value:
            hits.update(tag_ids(item))
        return hits
    if isinstance(value, dict):
        for key in ("identifier", "id", "value"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                hits.add(item.strip())
        for item in value.values():
            if isinstance(item, (dict, list)):
                hits.update(tag_ids(item))
        return hits
    if isinstance(value, str) and value.strip():
        hits.add(value.strip())
    return hits


def append_req_trace(html: str, req_meta: dict) -> str:
    """描述内追溯需求（非 ASSOCIATION API）。"""
    sn = req_meta.get("serialNumber") or ""
    subj = req_meta.get("subject") or ""
    return html + f"<h2>追溯需求</h2><p>{sn} {subj}</p>"


def append_test_case_trace(html: str, test_case: str) -> str:
    """记录测试用例来源；不伪造未验证的正式工作项关系。"""
    return html + f"<h2>测试用例来源</h2><p>{test_case}</p>"


def _user_meta(value: object) -> tuple[str, str] | None:
    if isinstance(value, str) and value.strip():
        return value.strip(), value.strip()
    if not isinstance(value, dict):
        return None
    identifier = (
        value.get("identifier")
        or value.get("userIdentifier")
        or value.get("userId")
        or value.get("id")
    )
    if not identifier:
        return None
    name = (
        value.get("displayName")
        or value.get("realName")
        or value.get("name")
        or str(identifier)
    )
    return str(identifier), str(name)


def current_actor_from_created(*items: object) -> tuple[str, str] | None:
    """从刚创建工作项的服务端记录取得当前会话用户。"""
    actor_keys = (
        "creator",
        "createdBy",
        "creatorUser",
        "createdByUser",
        "createUser",
    )
    id_keys = (
        "creatorIdentifier",
        "createdByIdentifier",
        "creatorId",
        "createdById",
    )
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in actor_keys:
            hit = _user_meta(item.get(key))
            if hit:
                return hit
        for key in id_keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip(), value.strip()
    return None


def field_user_id(data: object, field_identifier: str) -> str | None:
    """兼容 extra 的对象、字段列表和 user/list 字段形态。"""
    if isinstance(data, list):
        for item in data:
            hit = field_user_id(item, field_identifier)
            if hit:
                return hit
        return None
    if not isinstance(data, dict):
        return None
    if field_identifier in data:
        hit = _user_meta(data[field_identifier])
        if hit:
            return hit[0]
        value = data[field_identifier]
        if isinstance(value, list) and value:
            hit = _user_meta(value[0])
            if hit:
                return hit[0]
    field_key = data.get("fieldIdentifier") or data.get("propertyKey")
    if field_key == field_identifier:
        for key in ("value", "fieldValue", "propertyValue", "users"):
            value = data.get(key)
            if isinstance(value, list) and value:
                value = value[0]
            hit = _user_meta(value)
            if hit:
                return hit[0]
    for value in data.values():
        if isinstance(value, (dict, list)):
            hit = field_user_id(value, field_identifier)
            if hit:
                return hit
    return None


def main() -> None:
    ap = argparse.ArgumentParser(
        description="发起缺陷（ASSOCIATED→【测试】；需求写入描述追溯）"
    )
    ap.add_argument("--mode", choices=["本期", "非本期"], required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--assignee", required=True, help="负责人：姓名或 user id")
    ap.add_argument(
        "--source",
        choices=["standalone", "test-case"],
        default="standalone",
        help="建单来源：独立创建或测试用例创建",
    )
    ap.add_argument("--test-case", default=None, help="测试用例编号/执行记录（source=test-case 必填）")
    ap.add_argument("--priority", default="中", choices=list(PRI.keys()))
    ap.add_argument("--severity", default="3-一般", choices=list(SEV.keys()))
    ap.add_argument("--test-task", default=None, help="如 DEMO-90 / ONEOS-xx（本期必填）")
    ap.add_argument("--test-task-id", default=None)
    ap.add_argument("--delivery", default=None, help="仅用于辅助追溯；不能替代测试任务")
    ap.add_argument("--delivery-id", default=None)
    ap.add_argument(
        "--req",
        default=None,
        help="产品需求编号（写入描述追溯；不做 ASSOCIATED）；缺省从【测试】追溯",
    )
    ap.add_argument("--req-id", default=None)
    ap.add_argument("--description-html", default=None)
    ap.add_argument("--description-file", default=None)
    ap.add_argument("--tag-id", default=None, help="标签 identifier；必须来自云效实时解析")
    ap.add_argument("--tag-name", default=None, help="仅用于 Plan 展示和回读说明")
    ap.add_argument("--space", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--allow-no-test",
        action="store_true",
        help="仅非本期：允许不挂【测试】",
    )
    args = ap.parse_args()

    if args.mode == "本期" and args.allow_no_test:
        raise SystemExit("本期禁止 --allow-no-test；必须 ASSOCIATED→【测试】")
    if args.test_case:
        args.source = "test-case"
    if args.source == "test-case" and not args.test_case:
        raise SystemExit("测试用例创建路径必须提供 --test-case")
    if args.tag_name and not args.tag_id:
        raise SystemExit("提供 --tag-name 时必须同时提供 --tag-id")

    html = args.description_html
    if args.description_file:
        html = Path(args.description_file).read_text(encoding="utf-8")
    if not html:
        html = default_html(args.title, None)

    try:
        assignee_id, assignee_name = resolve_person(args.assignee)
    except ValueError as e:
        raise SystemExit(str(e)) from e

    space = space_id(args.space)
    try:
        s = session(probe=True)
    except AuthError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from e

    test_meta = None
    req_meta = None
    need_test = args.mode == "本期" or not args.allow_no_test

    if need_test:
        if not (args.test_task or args.test_task_id):
            raise SystemExit(
                "发布缺陷必须提供 --test-task/--test-task-id："
                "缺陷须 ASSOCIATED 关联对应编号的【测试】"
            )
        test_meta = resolve_target(
            s,
            space,
            sn=args.test_task,
            wid=args.test_task_id,
            categories=("Task",),
        )
        subj = test_meta.get("subject") or ""
        if not subj.startswith("【测试】"):
            raise SystemExit(
                f"锚点必须是【测试】任务，当前为：{test_meta.get('serialNumber')} | {subj}"
            )

        if args.req or args.req_id:
            req_meta = resolve_target(
                s, space, sn=args.req, wid=args.req_id, categories=("Req",)
            )
        else:
            req_meta = resolve_req_from_test(s, test_meta["id"])
            # 追溯不到不阻断：仅无需求描述段；仍可 Plan 补 --req

    if req_meta:
        html = append_req_trace(html, req_meta)
    if args.test_case:
        html = append_test_case_trace(html, args.test_case)

    duplicates = find_exact_title_duplicates(s, space, args.title)

    payload: dict = {
        "subject": args.title,
        "description": html,
        "formatType": "RICHTEXT",
        "document": {"content": html, "formatType": "RICHTEXT"},
        "spaceIdentifier": space,
        "space": space,
        "spaceType": "Project",
        "workitemTypeIdentifier": BUG_TYPE,
        "workitemType": BUG_TYPE,
        "categoryIdentifier": "Bug",
        "category": "Bug",
        "assignedTo": assignee_id,
        "fieldValueList": [
            {"fieldIdentifier": "priority", "value": PRI[args.priority]},
            {"fieldIdentifier": "seriousLevel", "value": SEV[args.severity]},
            {"fieldIdentifier": "assignedTo", "value": assignee_id},
        ],
        "attachmentIdList": [],
        "cloneFrom": None,
    }

    # create 时仅挂 ASSOCIATED→【测试】
    if test_meta:
        payload["createWorkitemRelationInfo"] = {
            "relatedWorkitemIdentifier": test_meta["id"],
            "relatedToRelationIdentifier": "ASSOCIATED",
        }
    if args.tag_id:
        payload["tag"] = [args.tag_id]

    plan = {
        "mode": args.mode,
        "space": space,
        "title": args.title,
        "source": args.source,
        "testCase": args.test_case,
        "assignee": {"id": assignee_id, "name": assignee_name},
        "verifier": {
            "policy": "current authenticated user",
            "overrideAllowed": False,
            "resolvedAt": "apply from server-recorded creation actor",
        },
        "priority": args.priority,
        "severity": args.severity,
        "tag": {"id": args.tag_id, "name": args.tag_name} if args.tag_id else None,
        "exactTitleDuplicates": duplicates,
        "testAssociated": test_meta,
        "reqTrace": req_meta,
        "relationRule": "ASSOCIATED→【测试】；需求仅描述追溯（不做 API 第二挂）",
        "dryRun": args.dry_run,
    }

    if args.dry_run:
        print(json.dumps({"ok": True, "wouldCreate": plan}, ensure_ascii=False, indent=2))
        return
    if duplicates:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "发现标题完全一致的已有缺陷，已阻止重复创建",
                    "duplicates": duplicates,
                    "plan": plan,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(5)

    created = create_workitem(s, payload)
    bug_id = created["identifier"]
    set_document(s, bug_id, html)
    live_raw = get_workitem(s, bug_id)
    extra_before = get_workitem_extra(s, bug_id)
    current_actor = current_actor_from_created(created, live_raw)
    if not current_actor:
        out = {
            "ok": False,
            "bug": brief_item(live_raw),
            "error": "已建单，但无法从云效建单结果解析当前会话用户，未写验证者",
            "verifierPolicy": "当前登录用户；禁止猜测或口令覆盖",
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        raise SystemExit(4)
    verifier_id, verifier_name = current_actor
    verifier_before = field_user_id(extra_before, "workitem.verifier")
    if verifier_before != verifier_id:
        set_workitem_property(
            s,
            bug_id,
            property_key="workitem.verifier",
            property_value=verifier_id,
        )
    extra_after = get_workitem_extra(s, bug_id)
    verifier_after = field_user_id(extra_after, "workitem.verifier")
    verifier_ok = verifier_after == verifier_id

    test_ok = True
    test_error = None
    if test_meta:
        test_ok = has_associated(s, bug_id, test_meta["id"])
        if not test_ok:
            test_error = (
                "创建后未回读到 ASSOCIATED→【测试】。"
                "请删单重试；create 须在 createWorkitemRelationInfo 挂 ASSOCIATED。"
            )

    full_live = get_workitem(s, bug_id)
    live = brief_item(full_live)
    live_tag_ids = tag_ids(full_live.get("tag"))
    tag_ok = not args.tag_id or args.tag_id in live_tag_ids
    assoc_ids = [
        x.get("serialNumber") or x.get("identifier")
        for x in list_associated(s, bug_id, forward=True)
        + list_associated(s, bug_id, forward=False)
    ]

    ok = verifier_ok and (test_ok if test_meta else True) and tag_ok
    out = {
        "ok": ok,
        "bug": live,
        "plan": plan,
        "verifier": {
            "source": "current authenticated user recorded by Yunxiao",
            "id": verifier_id,
            "name": verifier_name,
            "before": verifier_before,
            "readBack": verifier_after,
            "ok": verifier_ok,
        },
        "testAssociatedOk": test_ok if test_meta else None,
        "testAssociatedError": test_error,
        "tagOk": tag_ok if args.tag_id else None,
        "tagReadBack": sorted(live_tag_ids),
        "reqTrace": req_meta,
        "associated": assoc_ids,
        "note": "硬门禁：ASSOCIATED→【测试】；需求写入描述追溯，不做 ASSOCIATED API",
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not verifier_ok:
        raise SystemExit(4)
    if test_meta and not test_ok:
        raise SystemExit(3)
    if not tag_ok:
        raise SystemExit(6)


if __name__ == "__main__":
    main()
