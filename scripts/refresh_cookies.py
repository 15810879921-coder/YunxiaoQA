#!/usr/bin/env python3
"""从本机 Chrome 刷新云效 Cookie 到 /tmp/yunxiao_cookies.json。

须先在 Chrome 登录 https://devops.aliyun.com 。

示例：
  python3 scripts/refresh_cookies.py
  python3 scripts/refresh_cookies.py --probe
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _auth import (  # noqa: E402
    AUTH_HELP,
    AuthError,
    COOKIE_FALLBACK,
    dump_chrome_cookies,
    probe_auth,
    session,
    space_id,
)


def main() -> None:
    ap = argparse.ArgumentParser(description="刷新云效 Cookie")
    ap.add_argument("--out", default=str(COOKIE_FALLBACK), help="写出路径")
    ap.add_argument("--probe", action="store_true", help="写出后立刻探测")
    ap.add_argument("--space", default=None)
    args = ap.parse_args()
    try:
        jar = dump_chrome_cookies(Path(args.out))
        out = {
            "ok": True,
            "path": args.out,
            "keys": sorted(jar.keys()),
            "hasXsrf": bool(jar.get("XSRF-TOKEN")),
            "hasAoneSession": bool(jar.get("AONE_SESSION")),
        }
        if args.probe:
            s = session(probe=False)
            out["probe"] = probe_auth(s, space_id(args.space))
        print(json.dumps(out, ensure_ascii=False, indent=2))
    except AuthError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
        print(AUTH_HELP, file=sys.stderr)
        raise SystemExit(2) from e


if __name__ == "__main__":
    main()
