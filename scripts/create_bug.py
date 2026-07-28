#!/usr/bin/env python3
"""发起缺陷（本期 / 非本期）。

写操作：须先经 YunxiaoQA Plan 门禁确认后再执行（去掉 --dry-run）。

本期必须 create 时挂 ASSOCIATED（测试任务或交付），创建后强制回读校验；
校验失败则退出码 3（云效常无法事后补关联）。

示例：
  # 干跑
  python3 scripts/create_bug.py --mode 本期 --title '[验证] …' \\
    --test-task DEMO-90 --assignee 沈辰 --verifier 王冕 --dry-run

  # 实写
  python3 scripts/create_bug.py --mode 本期 --title '[验证] …' \\
    --test-task DEMO-90 --assignee 沈辰 --verifier 王冕 \\
    --description-html '<p>实际…</p><p>期望…</p>'

  python3 scripts/create_bug.py --mode 非本期 --title '…' \\
    --assignee 沈辰 --verifier 王冕 --description-file ./bug.html
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


def association_hit(assoc: list[dict], target_id: str) -> bool:
    return any(x.get("identifier") == target_id for x in assoc)


def main() -> None:
    ap = argparse.ArgumentParser(description="发起缺陷（create + 强制关联校验）")
    ap.add_argument("--mode", choices=["本期", "非本期"], required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--assignee", required=True, help="负责人：姓名或 user id")
    ap.add_argument("--verifier", default="王冕", help="验证者：姓名或 user id")
    ap.add_argument("--priority", default="中", choices=list(PRI.keys()))
    ap.add_argument("--severity", default="3-一般", choices=list(SEV.keys()))
    ap.add_argument("--test-task", default=None, help="如 DEMO-90 / ONEOS-xx")
    ap.add_argument("--test-task-id", default=None)
    ap.add_argument("--delivery", default=None)
    ap.add_argument("--delivery-id", default=None)
    ap.add_argument("--req", default=None, help="可选：额外 ASSOCIATED 需求编号（仅记录意图；主关联仍用测试/交付）")
    ap.add_argument("--description-html", default=None)
    ap.add_argument("--description-file", default=None)
    ap.add_argument("--space", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--allow-no-associate",
        action="store_true",
        help="仅非本期可用；本期禁止",
    )
    args = ap.parse_args()

    if args.mode == "本期" and args.allow_no_associate:
        raise SystemExit("本期禁止 --allow-no-associate")

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

    associate_meta = None
    if args.mode == "本期":
        if not (args.test_task or args.test_task_id or args.delivery or args.delivery_id):
            raise SystemExit("本期必须提供 --test-task/--test-task-id 或 --delivery/--delivery-id")
        if args.test_task or args.test_task_id:
            associate_meta = resolve_target(
                s,
                space,
                sn=args.test_task,
                wid=args.test_task_id,
                categories=("Task",),
            )
        else:
            associate_meta = resolve_target(
                s,
                space,
                sn=args.delivery,
                wid=args.delivery_id,
                categories=("Task",),
            )
    elif args.test_task or args.test_task_id or args.delivery or args.delivery_id:
        # 非本期也可选挂关联
        if args.test_task or args.test_task_id:
            associate_meta = resolve_target(
                s,
                space,
                sn=args.test_task,
                wid=args.test_task_id,
                categories=("Task",),
            )
        else:
            associate_meta = resolve_target(
                s,
                space,
                sn=args.delivery,
                wid=args.delivery_id,
                categories=("Task",),
            )
    elif not args.allow_no_associate and args.mode == "非本期":
        # 非本期允许无关联，默认即可
        pass

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
    if associate_meta:
        payload["createWorkitemRelationInfo"] = {
            "relatedWorkitemIdentifier": associate_meta["id"],
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
        "associateAtCreate": associate_meta,
        "reqHint": args.req,
        "dryRun": args.dry_run,
    }

    if args.dry_run:
        print(json.dumps({"ok": True, "wouldCreate": plan}, ensure_ascii=False, indent=2))
        return

    created = create_workitem(s, payload)
    bug_id = created["identifier"]
    set_document(s, bug_id, html)
    live = brief_item(get_workitem(s, bug_id))
    assoc = list_associated(s, bug_id, forward=True)
    assoc_ids = [x.get("serialNumber") or x.get("identifier") for x in assoc]

    assoc_ok = True
    assoc_error = None
    if associate_meta:
        assoc_ok = association_hit(assoc, associate_meta["id"])
        if not assoc_ok:
            assoc_error = (
                "创建后 ASSOCIATED 校验失败：目标未出现在关联列表。"
                "云效常无法事后补关联（「不能关联相同的工作项」）。"
                "请删单重试或在 UI 确认 createWorkitemRelationInfo 是否生效。"
            )

    out = {
        "ok": assoc_ok if associate_meta else True,
        "bug": live,
        "plan": plan,
        "associated": assoc_ids,
        "associatedOk": assoc_ok if associate_meta else None,
        "associatedError": assoc_error,
        "note": "创建后禁止依赖 relation/record 补关联；本期必须以 create 挂上",
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if associate_meta and not assoc_ok:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
