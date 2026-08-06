#!/usr/bin/env python3
"""安全回填少量缺陷字段，并做精确回读。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _auth import (  # noqa: E402
    AuthError,
    brief_item,
    find_by_serial,
    get_workitem,
    get_workitem_extra,
    session,
    set_workitem_property,
    space_id,
)

SAFE_PROPERTIES = {
    "assignedTo",
    "priority",
    "seriousLevel",
    "sprint",
    "tag",
    "workitem.verifier",
}


def field_values(data: object, field_identifier: str) -> list[object]:
    hits: list[object] = []
    if isinstance(data, list):
        for item in data:
            hits.extend(field_values(item, field_identifier))
        return hits
    if not isinstance(data, dict):
        return hits
    if field_identifier in data:
        hits.append(data[field_identifier])
    field_key = data.get("fieldIdentifier") or data.get("propertyKey")
    if field_key == field_identifier:
        for key in ("value", "fieldValue", "propertyValue", "users"):
            if key in data:
                hits.append(data[key])
    for value in data.values():
        if isinstance(value, (dict, list)):
            hits.extend(field_values(value, field_identifier))
    return hits


def scalar_tokens(value: object) -> set[str]:
    hits: set[str] = set()
    if isinstance(value, list):
        for item in value:
            hits.update(scalar_tokens(item))
    elif isinstance(value, dict):
        for key in ("identifier", "id", "value"):
            item = value.get(key)
            if not isinstance(item, (dict, list)) and item is not None:
                hits.add(str(item))
        for item in value.values():
            if isinstance(item, (dict, list)):
                hits.update(scalar_tokens(item))
    elif value is not None:
        hits.add(str(value))
    return hits


def main() -> None:
    ap = argparse.ArgumentParser(description="缺陷字段回填（安全白名单、支持 dry-run 与回读）")
    ap.add_argument("--sn", required=True)
    ap.add_argument("--property", required=True, choices=sorted(SAFE_PROPERTIES))
    ap.add_argument("--value", action="append", required=True)
    ap.add_argument("--as-list", action="store_true")
    ap.add_argument("--space")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        s = session(probe=True)
    except AuthError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from exc
    item = find_by_serial(s, space=space_id(args.space), category="Bug", serial=args.sn)
    if not item:
        raise SystemExit(f"未找到缺陷编号 {args.sn}")
    live = get_workitem(s, item["identifier"])
    meta = brief_item(live)
    if str(meta.get("serialNumber") or "").upper() != args.sn.strip().upper():
        raise SystemExit(f"编号回读不一致：期望 {args.sn}，实际 {meta.get('serialNumber')}")

    value: object = args.value if args.as_list or len(args.value) > 1 else args.value[0]
    plan = {"bug": meta, "property": args.property, "value": value, "dryRun": args.dry_run}
    if args.dry_run:
        print(json.dumps({"ok": True, "wouldSet": plan}, ensure_ascii=False, indent=2))
        return

    set_workitem_property(
        s,
        item["identifier"],
        property_key=args.property,
        property_value=value,
    )
    extra = get_workitem_extra(s, item["identifier"])
    live_after = get_workitem(s, item["identifier"])
    readback = field_values(extra, args.property) + field_values(live_after, args.property)
    actual = scalar_tokens(readback)
    expected = scalar_tokens(value)
    ok = expected.issubset(actual)
    print(
        json.dumps(
            {"ok": ok, "plan": plan, "readback": readback, "expected": sorted(expected), "actual": sorted(actual)},
            ensure_ascii=False,
            indent=2,
        )
    )
    if not ok:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
