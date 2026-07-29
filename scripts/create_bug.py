#!/usr/bin/env python3
"""发起缺陷（本期 / 非本期）。

写操作：须先经 YunxiaoQA Plan 门禁确认后再执行（去掉 --dry-run）。

规则（直接发布缺陷 · 强制）：
1. 必须先挂【测试】任务：缺陷作为【测试】的子项（create 时 parent + TASK_SUB）。
2. 从【测试】追溯产品需求，ASSOCIATED 挂到缺陷下（口令 --req 可覆盖）。
3. 子项 / 需求回读校验失败 → 退出码 3。

示例：
  python3 scripts/create_bug.py --mode 本期 --title '[验证] …' \\
    --test-task DEMO-90 --assignee 沈辰 --verifier 王冕 --dry-run
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
    add_relation,
    brief_item,
    create_workitem,
    find_by_serial,
    get_workitem,
    list_associated,
    list_parent_sub,
    resolve_person,
    resolve_req_from_test,
    session,
    set_document,
    space_id,
)

BUG_TYPE = RUNTIME["workitem_types"]["bug"]["identifier"]
PRI = RUNTIME["fields"]["priority"]
SEV = RUNTIME["fields"]["seriousLevel"]


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


def is_sub_of_test(s, bug_id: str, test_id: str) -> bool:
    """缺陷是否为【测试】子项：父链含测试，或测试子列表含缺陷。"""
    parents = list_parent_sub(s, bug_id, forward=False)
    if relation_hit(parents, test_id):
        return True
    children = list_parent_sub(s, test_id, forward=True)
    return relation_hit(children, bug_id)


def main() -> None:
    ap = argparse.ArgumentParser(description="发起缺陷（测试子项 + 需求 ASSOCIATED）")
    ap.add_argument("--mode", choices=["本期", "非本期"], required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--assignee", required=True, help="负责人：姓名或 user id")
    ap.add_argument("--verifier", default="王冕", help="验证者：姓名或 user id")
    ap.add_argument("--priority", default="中", choices=list(PRI.keys()))
    ap.add_argument("--severity", default="3-一般", choices=list(SEV.keys()))
    ap.add_argument("--test-task", default=None, help="如 DEMO-90 / ONEOS-xx（本期必填）")
    ap.add_argument("--test-task-id", default=None)
    ap.add_argument("--delivery", default=None, help="仅用于辅助追溯；不能替代测试任务")
    ap.add_argument("--delivery-id", default=None)
    ap.add_argument(
        "--req",
        default=None,
        help="产品需求编号；缺省则从【测试】/【交付】/【开发】ASSOCIATED 自动拉取",
    )
    ap.add_argument("--req-id", default=None)
    ap.add_argument("--description-html", default=None)
    ap.add_argument("--description-file", default=None)
    ap.add_argument("--space", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--allow-no-test",
        action="store_true",
        help="仅非本期：允许不挂【测试】（无子项、不挂需求）",
    )
    args = ap.parse_args()

    if args.mode == "本期" and args.allow_no_test:
        raise SystemExit("本期禁止 --allow-no-test；必须挂【测试】子项")

    html = args.description_html
    if args.description_file:
        html = Path(args.description_file).read_text(encoding="utf-8")
    if not html:
        html = default_html(args.title, None)

    try:
        assignee_id, assignee_name = resolve_person(args.assignee)
        verifier_id, verifier_name = resolve_person(args.verifier)
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
                "缺陷须作为【测试】子项，并挂上从测试任务追溯的需求"
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
            if not req_meta:
                raise SystemExit(
                    "未能从【测试】追溯到产品需求（自身/父交付/兄弟【开发】ASSOCIATED）。"
                    "请口令补 --req=ONEOS-xx 或先修好测试任务与需求的关联。"
                )

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
            {"fieldIdentifier": "workitem.verifier", "value": verifier_id},
        ],
        "attachmentIdList": [],
        "cloneFrom": None,
    }

    # create 时挂 TASK_SUB→【测试】（子项）；需求事后 ASSOCIATED（create 仅支持一条关系）
    if test_meta:
        tid = test_meta["id"]
        payload["parent"] = tid
        payload["parentIdentifier"] = tid
        payload["createWorkitemRelationInfo"] = {
            "relatedWorkitemIdentifier": tid,
            "relatedToRelationIdentifier": "TASK_SUB",
        }

    plan = {
        "mode": args.mode,
        "space": space,
        "title": args.title,
        "assignee": {"id": assignee_id, "name": assignee_name},
        "verifier": {"id": verifier_id, "name": verifier_name},
        "priority": args.priority,
        "severity": args.severity,
        "testParent": test_meta,
        "reqAssociated": req_meta,
        "relationRule": "缺陷 TASK_SUB→【测试】；缺陷 ASSOCIATED→需求（自测试追溯）",
        "dryRun": args.dry_run,
    }

    if args.dry_run:
        print(json.dumps({"ok": True, "wouldCreate": plan}, ensure_ascii=False, indent=2))
        return

    created = create_workitem(s, payload)
    bug_id = created["identifier"]
    set_document(s, bug_id, html)

    sub_ok = True
    sub_error = None
    if test_meta:
        sub_ok = is_sub_of_test(s, bug_id, test_meta["id"])
        if not sub_ok:
            sub_error = (
                "创建后【测试】子项校验失败：缺陷未出现在测试任务 PARENT_SUB 下。"
                "请删单重试；勿仅用 ASSOCIATED 代替子项。"
            )

    req_ok = True
    req_error = None
    req_api = None
    if req_meta:
        # 优先事后 ASSOCIATED；若已在关联列表则跳过
        already = list_associated(s, bug_id, forward=True) + list_associated(
            s, bug_id, forward=False
        )
        if relation_hit(already, req_meta["id"]):
            req_ok = True
        else:
            req_api = add_relation(
                s, bug_id, to_workitem_id=req_meta["id"], relation="ASSOCIATED"
            )
            if req_api.get("code") != 200:
                # 部分环境报「不能关联相同的工作项」但仍可能已有隐式关系：再回读
                already2 = list_associated(s, bug_id, forward=True) + list_associated(
                    s, bug_id, forward=False
                )
                req_ok = relation_hit(already2, req_meta["id"])
                if not req_ok:
                    req_error = (
                        "需求 ASSOCIATED 失败："
                        f"{req_api.get('errorMsg') or req_api}。"
                        "子项若已成功，请在 UI 手工挂需求或删单后带 --req 重试。"
                    )
            else:
                already2 = list_associated(s, bug_id, forward=True)
                req_ok = relation_hit(already2, req_meta["id"])
                if not req_ok:
                    req_error = "需求 ASSOCIATED API 成功但回读未命中，立刻停。"

    live = brief_item(get_workitem(s, bug_id))
    children_of_test = (
        [
            x.get("serialNumber") or x.get("identifier")
            for x in list_parent_sub(s, test_meta["id"], forward=True)
        ]
        if test_meta
        else []
    )
    assoc_ids = [
        x.get("serialNumber") or x.get("identifier")
        for x in list_associated(s, bug_id, forward=True)
    ]

    ok = (sub_ok if test_meta else True) and (req_ok if req_meta else True)
    out = {
        "ok": ok,
        "bug": live,
        "plan": plan,
        "testSubOk": sub_ok if test_meta else None,
        "testSubError": sub_error,
        "testChildren": children_of_test,
        "reqAssociatedOk": req_ok if req_meta else None,
        "reqAssociatedError": req_error,
        "reqApi": req_api,
        "associated": assoc_ids,
        "note": "规则：缺陷=【测试】TASK_SUB 子项 + ASSOCIATED→需求（自测试追溯）",
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not ok:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
