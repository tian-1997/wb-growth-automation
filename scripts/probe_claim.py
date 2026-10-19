#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_claim.py — 一次性发放口探测（2026-10-19）。

背景：App 用户菜单弹窗「Buddy加油站 · 每日可领100积分 / 立即领取」点击后
直接到账 +100 积分 +5 能量，无任何页面/弹窗。该弹窗文案与端点是服务端下发
配置：整个 App asar 与用户中心前端 JS 里均无对应端点（已全量搜索确认）。

方法：向候选端点发请求——
  [1] GET 状态端点（零副作用）：命中即暴露功能是否存在；
  [2] POST claim 端点：今日额度用户已于 11:03 手动领过，重复领取预期返回
      "已领取"类业务错误——这本身就是最强识别信号；若端点不存在则 404。
注意：POST 探测只针对"每日领取"语义的候选路径，刻意避开 redeem（里程碑兑换）、
lottery/draw（抽奖）、makeup-cards/use 等会产生其他消耗的端点。
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("WB_BASE", "https://www.workbuddy.cn").rstrip("/")
TOKEN = os.environ.get("WB_TOKEN", "").strip()


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def api(method, path, body=None, timeout=20):
    url = BASE + path
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Origin": BASE,
        "Referer": BASE + "/profile/",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def main():
    if not TOKEN:
        log("错误：未设置 WB_TOKEN。")
        return 1

    log("---- 菜单弹窗发放口探测（2026-10-19）----")

    log("[1/2] GET 状态端点（零副作用）")
    for path in (
        "/v2/activity/growth/daily/status",
        "/activity/growth/daily/status",
        "/v2/activity/growth/checkin/status",
        "/activity/growth/checkin/status",
        "/v2/activity/growth/daily-task/status",
        "/v2/activity/growth/daily-reward/status",
        "/v2/activity/growth/sign/status",
    ):
        try:
            code, raw = api("GET", path)
            log("GET  %s -> %s %s" % (path, code, raw[:300]))
        except Exception as e:  # noqa: BLE001
            log("GET  %s -> 失败 %s" % (path, str(e)[:120]))

    log("[2/2] POST claim 端点（今日已领，命中即现「已领取」类错误）")
    for path in (
        "/activity/growth/checkin",
        "/v2/activity/growth/checkin",
        "/activity/growth/daily/claim",
        "/v2/activity/growth/daily/claim",
        "/activity/growth/daily-checkin/claim",
        "/v2/activity/growth/daily-checkin/claim",
        "/activity/growth/daily-reward/claim",
        "/v2/activity/growth/daily-reward/claim",
        "/activity/growth/subscribe-task/claim",
        "/v2/activity/growth/subscribe-task/claim",
        "/activity/growth/tasks/daily_checkin/claim",
        "/activity/growth/tasks/checkin/claim",
        "/activity/growth/tasks/daily/claim",
        "/activity/growth/sign/claim",
        "/v2/activity/growth/sign/claim",
    ):
        try:
            code, raw = api("POST", path, body={})
            log("POST %s -> %s %s" % (path, code, raw[:300]))
        except Exception as e:  # noqa: BLE001
            log("POST %s -> 失败 %s" % (path, str(e)[:120]))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
