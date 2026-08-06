#!/usr/bin/env python3
"""Secret-safe runtime for YunxiaoQA official CLI adapters."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TOKEN_RE = re.compile(r"pt-[A-Za-z0-9_\-]+")


class AdapterError(RuntimeError):
    pass


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def output_dir() -> Path:
    root = os.environ.get("ONEOS_YUNXIAO_TEMP_DIR")
    path = Path(root) if root else Path(tempfile.gettempdir()) / "oneos-yunxiao"
    path.mkdir(parents=True, exist_ok=True)
    return path


def scrub(text: str) -> str:
    token = os.environ.get("ALIBABA_CLOUD_YUNXIAO_ACCESS_TOKEN", "")
    cleaned = ANSI_RE.sub("", text or "")
    if token:
        cleaned = cleaned.replace(token, "<redacted-token>")
    return TOKEN_RE.sub("<redacted-token>", cleaned)


def find_aliyun() -> str:
    candidates = [os.environ.get("ALIYUN_CLI_PATH"), shutil.which("aliyun")]
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        candidates.append(str(Path(os.environ["LOCALAPPDATA"]) / "AliyunCLI" / "aliyun.exe"))
    candidates.extend(("/usr/local/bin/aliyun", "/opt/homebrew/bin/aliyun"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    raise AdapterError("未找到aliyun CLI。请安装官方阿里云CLI和devops插件。")


def require_auth_env() -> dict[str, str]:
    token = os.environ.get("ALIBABA_CLOUD_YUNXIAO_ACCESS_TOKEN", "")
    org_id = os.environ.get("ALIBABA_CLOUD_YUNXIAO_ORGANIZATION_ID", "")
    if not token:
        raise AdapterError("缺少ALIBABA_CLOUD_YUNXIAO_ACCESS_TOKEN。")
    if not org_id:
        raise AdapterError("缺少ALIBABA_CLOUD_YUNXIAO_ORGANIZATION_ID。")
    return {"token": token, "organizationId": org_id}


def run_raw(executable: str, args: list[str], timeout: int = 120,
            scrub_output: bool = True) -> str:
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
        "env": os.environ.copy(),
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run([executable, *args], **kwargs)
    stdout = completed.stdout.strip()
    stderr = scrub(completed.stderr).strip()
    if completed.returncode != 0:
        detail = stderr or scrub(stdout) or f"exit={completed.returncode}"
        raise AdapterError(f"CLI调用失败：{' '.join(args[:2])}；{detail}")
    return scrub(stdout) if scrub_output else stdout


def run_devops(executable: str, args: list[str], timeout: int = 120) -> Any:
    text = run_raw(executable, ["devops", *args], timeout=timeout, scrub_output=False)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AdapterError(f"CLI返回的不是JSON：{args[0] if args else ''}；{scrub(text[:500])}") from exc


def unwrap(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("result", "data"):
            if key in value and len(value) <= 4:
                return value[key]
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
