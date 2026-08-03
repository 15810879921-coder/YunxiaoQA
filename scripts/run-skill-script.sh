#!/bin/sh
set -u

if [ "$#" -lt 1 ]; then
    echo '用法: run-skill-script.sh <script.py> [参数...]' >&2
    exit 64
fi

script_name=$1
shift
case "$script_name" in
    ''|*/*|*\\*|*..*) echo "仅允许调用当前 Skill scripts 目录下的 Python 脚本: $script_name" >&2; exit 64 ;;
esac
case "$script_name" in
    *.py) ;;
    *) echo "仅允许调用 Python 脚本: $script_name" >&2; exit 64 ;;
esac

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 70
target_script=$script_dir/$script_name
if [ ! -f "$target_script" ]; then echo "脚本不存在: $script_name" >&2; exit 66; fi

python_command=
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)' >/dev/null 2>&1; then
    python_command=$(command -v python3)
elif command -v python >/dev/null 2>&1 && python -c 'import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)' >/dev/null 2>&1; then
    python_command=$(command -v python)
else
    echo '未找到可用的 Python 3。请先安装 Python 3，并确保本机命令行可以访问。' >&2
    exit 69
fi

export PYTHONDONTWRITEBYTECODE=1
temp_base=$("$python_command" -c 'import tempfile; print(tempfile.gettempdir())') || exit 70
ONEOS_YUNXIAO_TEMP_DIR=$temp_base/oneos-yunxiao
export ONEOS_YUNXIAO_TEMP_DIR
mkdir -p -- "$ONEOS_YUNXIAO_TEMP_DIR" || exit 73
exec "$python_command" "$target_script" "$@"
