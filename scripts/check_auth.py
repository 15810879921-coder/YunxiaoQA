#!/usr/bin/env python3
"""探测云效会话是否可用。stdout=JSON。

示例：
  python3 scripts/check_auth.py
  python3 scripts/check_auth.py --space 65eca0c2e16a23939081e19e14
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _auth import AUTH_HELP, AuthError, probe_auth, session, space_id  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="探测云效鉴权")
    ap.add_argument("--space", default=None)
    args = ap.parse_args()
    try:
        s = session(probe=False)
        info = probe_auth(s, space_id(args.space))
        print(json.dumps(info, ensure_ascii=False, indent=2))
    except AuthError as e:
        print(
            json.dumps(
                {"ok": False, "error": str(e), "help": AUTH_HELP},
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(2) from e


if __name__ == "__main__":
    main()
