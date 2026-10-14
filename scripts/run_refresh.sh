#!/usr/bin/env sh
# run_refresh.sh — 用 command -v 动态定位 python（不写死版本号），导出 WorkBuddy token。
#
# 用法（在本机、已登录 WorkBuddy 的机器上）：
#   sh run_refresh.sh | gh secret set WB_TOKEN --repo <owner>/<repo>
# 或先落临时文件再设 secret：
#   sh run_refresh.sh > wb_token.txt
#
# 说明：token 只写 stdout；诊断信息走 stderr，不会污染管道。
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# 动态取解释器：优先 python3，再 python；都不写死版本号
PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then
  echo "[run_refresh] 未找到 python3/python，请先安装 Python 3。" >&2
  exit 127
fi

exec "$PY" "$SCRIPT_DIR/refresh_token.py"
