#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
renew_token.py — 云端「无感续签」：用 refreshToken 换新的 accessToken。

工作流程（在 GitHub Actions 里每天跑一次）：
  1. POST https://www.workbuddy.cn/v2/plugin/auth/token/refresh
     头：X-Refresh-Token / X-Auth-Refresh-Source: plugin / X-Domain
     （端点与请求方式来自桌面 app 主进程代码，非网传接口）
  2. 把返回的新 refreshToken 写回仓库 secret WB_REFRESH_TOKEN
     （需要 gh CLI + WB_GH_PAT；gh 在 GitHub 托管 runner 上预装）
  3. 新 accessToken 打到 stdout（本脚本唯一的 stdout 输出），
     由 workflow 注入后续步骤的 WB_TOKEN

为什么能「无感」（已实测验证）：
  - 该刷新接口**不废止旧 refreshToken**（同一个 RT 可重复调用），
    所以云端每天续期和桌面 app 自己的续期互不冲突、互不踢号。
  - accessToken 寿命 30 天，refreshToken 寿命约 60 天；只要每天续一次
    并把新 RT 写回 secret，链条就永远不会断。

失败分级：
  - 刷新失败（RT 过期/网络/限流）→ 退出码 1，由 workflow 回退到 WB_TOKEN
  - 刷新成功但写回失败（没配 WB_GH_PAT / 没装 gh / gh 报错）→ 退出码 2，
    token 照用，但自动续期链约 60 天后会断，workflow 会往群里发告警

环境变量：
  WB_REFRESH_TOKEN   必填，当前有效的 refreshToken
  WB_GH_PAT          可选，fine-grained PAT（Secrets: write），用于写回 secret
  WB_GH_REPO         可选，owner/repo；缺省取 GITHUB_REPOSITORY（Actions 自动注入）
"""
import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("WB_BASE", "https://www.workbuddy.cn").rstrip("/")
RT = os.environ.get("WB_REFRESH_TOKEN", "").strip()
PAT = os.environ.get("WB_GH_PAT", "").strip()
REPO = (os.environ.get("WB_GH_REPO") or os.environ.get("GITHUB_REPOSITORY") or "").strip()
SECRET_NAME = "WB_REFRESH_TOKEN"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def call_refresh(rt):
    req = urllib.request.Request(
        BASE + "/v2/plugin/auth/token/refresh", method="POST",
        data=json.dumps({}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Refresh-Token": rt,
            "X-Auth-Refresh-Source": "plugin",
            "X-Domain": "www.workbuddy.cn",
            "User-Agent": "Mozilla/5.0",
            "Origin": BASE,
            "Referer": BASE + "/profile/",
        })
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return e.code, {"_raw": raw[:300]}
    except Exception as e:  # noqa: BLE001
        return None, {"_error": str(e)}


def write_back(new_rt):
    """把新 refreshToken 写回仓库 secret。失败只告警，返回 bool。"""
    if not PAT:
        log("[renew] 未配置 WB_GH_PAT，跳过写回（secret 里的 RT 约 60 天后到期需重新播种）")
        return False
    gh = shutil.which("gh")
    if not gh:
        log("[renew] 环境里没有 gh CLI，跳过写回（GitHub 托管 runner 默认预装）")
        return False
    if not REPO:
        log("[renew] 未知仓库名（WB_GH_REPO/GITHUB_REPOSITORY 都为空），跳过写回")
        return False
    try:
        # 值走 stdin，不进 argv，避免泄漏到进程列表/日志
        p = subprocess.run(
            [gh, "secret", "set", SECRET_NAME, "--repo", REPO],
            input=new_rt, text=True, timeout=60,
            env={**os.environ, "GH_TOKEN": PAT},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if p.returncode == 0:
            log("[renew] 新 refreshToken 已写回 secret %s" % SECRET_NAME)
            return True
        log("[renew] 写回失败（gh exit %s）：%s" % (p.returncode, (p.stdout or "")[:200]))
        return False
    except Exception as e:  # noqa: BLE001
        log("[renew] 写回异常：%s" % e)
        return False


def main():
    if not RT:
        log("[renew] 未设置 WB_REFRESH_TOKEN，无法续签。")
        return 1

    code, resp = call_refresh(RT)
    if code != 200:
        log("[renew] 刷新失败 HTTP %s：%s" % (code, json.dumps(resp, ensure_ascii=False)[:300]))
        return 1

    data = (resp.get("data") or {}) if isinstance(resp, dict) else {}
    new_at = data.get("accessToken") or ""
    new_rt = data.get("refreshToken") or ""
    if not new_at:
        log("[renew] 响应里没有 accessToken：%s" % json.dumps(resp, ensure_ascii=False)[:300])
        return 1

    days = (data.get("expiresIn") or 0) // 86400
    log("[renew] 续签成功：新 accessToken 有效期 %s 天" % days)

    writeback_ok = True
    if new_rt and new_rt != RT:
        writeback_ok = write_back(new_rt)
    elif new_rt == RT:
        log("[renew] 服务端返回原 refreshToken（未轮换），无需写回")
    else:
        log("[renew] 响应没有 refreshToken 字段，跳过写回")

    # stdout 只输出新 accessToken
    sys.stdout.write(new_at)
    sys.stdout.flush()
    # 0=续签且写回OK；2=续签OK但写回失败（链条约60天后会断）
    return 0 if writeback_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
