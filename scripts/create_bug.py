#!/usr/bin/env python3
"""发起缺陷（本期 / 非本期）。

写操作：须先经 YunxiaoQA Plan 门禁确认后再执行（去掉 --dry-run）。

规则：
1. create 时 ASSOCIATED→【测试】（关联项；云效不允许缺陷作任务子项）——硬门禁，回读失败退出码 3。
2. 产品需求：点选/追溯后**写入描述作追溯记录**；本期不做 Cookie 事后 ASSOCIATED
   （第二挂常报「不能关联相同的工作项」；勿告警、勿伪造成功备注）。
3. 口令 --req 可覆盖自动追溯；点选确认后的编号才写入。

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
    brief_item,
    create_workitem,
    find_by_serial,
    get_workitem,
    list_associated,
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


def has_associated(s, a_id: str, b_id: str) -> bool:
    both = list_associated(s, a_id, forward=True) + list_associated(s, a_id, forward=False)
    return relation_hit(both, b_id)


def append_req_trace(html: str, req_meta: dict) -> str:
    """描述内追溯需求（非 ASSOCIATION API）。"""
    sn = req_meta.get("serialNumber") or ""
    subj = req_meta.get("subject") or ""
    return html + f"<h2>追溯需求</h2><p>{sn} {subj}</p>"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="发起缺陷（ASSOCIATED→【测试】；需求写入描述追溯）"
    )
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
        help="产品需求编号（写入描述追溯；不做 ASSOCIATED）；缺省从【测试】追溯",
    )
    ap.add_argument("--req-id", default=None)
    ap.add_argument("--description-html", default=None)
    ap.add_argument("--description-file", default=None)
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

    # create 时仅挂 ASSOCIATED→【测试】
    if test_meta:
        payload["createWorkitemRelationInfo"] = {
            "relatedWorkitemIdentifier": test_meta["id"],
            "relatedToRelationIdentifier": "ASSOCIATED",
        }

    plan = {
        "mode": args.mode,
        "space": space,
        "title": args.title,
        "assignee": {"id": assignee_id, "name": assignee_name},
        "verifier": {"id": verifier_id, "name": verifier_name},
        "priority": args.priority,
        "severity": args.severity,
        "testAssociated": test_meta,
        "reqTrace": req_meta,
        "relationRule": "ASSOCIATED→【测试】；需求仅描述追溯（不做 API 第二挂）",
        "dryRun": args.dry_run,
    }

    if args.dry_run:
        print(json.dumps({"ok": True, "wouldCreate": plan}, ensure_ascii=False, indent=2))
        return

    created = create_workitem(s, payload)
    bug_id = created["identifier"]
    set_document(s, bug_id, html)

    test_ok = True
    test_error = None
    if test_meta:
        test_ok = has_associated(s, bug_id, test_meta["id"])
        if not test_ok:
            test_error = (
                "创建后未回读到 ASSOCIATED→【测试】。"
                "请删单重试；create 须在 createWorkitemRelationInfo 挂 ASSOCIATED。"
            )

    live = brief_item(get_workitem(s, bug_id))
    assoc_ids = [
        x.get("serialNumber") or x.get("identifier")
        for x in list_associated(s, bug_id, forward=True)
        + list_associated(s, bug_id, forward=False)
    ]

    ok = test_ok if test_meta else True
    out = {
        "ok": ok,
        "bug": live,
        "plan": plan,
        "testAssociatedOk": test_ok if test_meta else None,
        "testAssociatedError": test_error,
        "reqTrace": req_meta,
        "associated": assoc_ids,
        "note": "硬门禁：ASSOCIATED→【测试】；需求写入描述追溯，不做 ASSOCIATED API",
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not ok:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
