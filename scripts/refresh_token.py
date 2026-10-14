#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refresh_token.py — 从 WorkBuddy 本机登录态导出当前 accessToken（JWT）。

用途：
  在你有登录态的这台 Windows 机器上运行，把 token 打到 stdout，
  再管道进 `gh secret set` 注入 GitHub 仓库 secret。例如：

      python refresh_token.py | gh secret set WB_TOKEN --repo <owner>/<repo>

  也可以用环境变量直接设 secret（GitHub Actions 不读本机，只读 secret）：
      python refresh_token.py > /tmp/wb_token.txt   # 仅你本机临时文件，勿提交

安全约束：
  - token 是明文 JWT，只写 stdout；不落盘、不打印到 CI 日志、不进仓库。
  - 本脚本本身只读登录态文件，不发任何网络请求。

登录态文件位置（Windows 默认）：
  %LOCALAPPDATA%\\CodeBuddyExtension\\Data\\Public\\auth\\workbuddy-desktop.info
  可用环境变量 WB_INFO_PATH 覆盖。

解释器：
  用 `command -v` 动态取 python，不写死版本号（见同目录 run_refresh.sh）。
"""
import json
import os
import sys


def default_info_path() -> str:
    override = os.environ.get("WB_INFO_PATH")
    if override:
        return override
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(
        local, "CodeBuddyExtension", "Data", "Public", "auth", "workbuddy-desktop.info"
    )


def main() -> int:
    path = default_info_path()
    if not os.path.isfile(path):
        sys.stderr.write(
            "找不到登录态文件：%s\n请先在本机登录 WorkBuddy，或用 WB_INFO_PATH 指定 .info 路径。\n" % path
        )
        return 2
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("读取登录态失败：%s\n" % e)
        return 2

    token = (data.get("auth") or {}).get("accessToken") or ""
    if not token:
        sys.stderr.write("登录态里没有 auth.accessToken，可能未登录或结构已变。\n")
        return 3

    # 基本健全性检查：JWT 应是三段 base64url
    if token.count(".") != 2:
        sys.stderr.write("accessToken 不是合法 JWT（非三段式）。\n")
        return 4

    # 只把 token 写 stdout（供管道/重定向），其余诊断信息走 stderr
    sys.stdout.write(token)
    sys.stdout.flush()

    # 诊断信息（含过期时间）写到 stderr，不污染 stdout 的 token
    try:
        import base64, time

        payload_seg = token.split(".")[1]
        payload_seg += "=" * (-len(payload_seg) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_seg))
        exp = payload.get("exp")
        if exp:
            days = (exp - int(time.time())) / 86400.0
            sys.stderr.write(
                "[refresh_token] token OK，有效期还剩约 %.1f 天（过期需在本机重新打开 WorkBuddy 刷新登录态）。\n"
                % days
            )
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
