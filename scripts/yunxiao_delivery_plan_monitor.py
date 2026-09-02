#!/usr/bin/env python3
"""Public entrypoint for the Yunxiao delivery-task TestHub plan monitor."""

from yunxiao_requirement_plan_monitor import MonitorError, main


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MonitorError as exc:
        import json
        import sys

        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
