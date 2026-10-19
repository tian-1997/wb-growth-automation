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

    log("[3/3] 对照与深挖：tasks/claim 的 code 校验行为 + 隐藏任务 code  candidates")
    # 对照组：完全不可能的 code。若返回 task not found -> 上面的 daily_checkin/checkin/daily
    # 是真实存在的任务 code（只是不在 /v2/activity/growth/tasks 列表里=隐藏任务）；
    # 若同样返回 task not completed -> claim 不校验 code 存在性，上面结果无信息量。
    for code in (
        "__bogus_control__",
        "daily_checkin", "checkin", "daily", "sign_in", "check_in",
        "daily_sign", "daily_active", "daily_chat", "daily_task",
        "oil_station", "gas_station", "buddy_daily", "daily_visit",
        "daily_login", "login", "visit", "active", "daily_use",
    ):
        try:
            http, raw = api("POST", "/activity/growth/tasks/%s/claim" % code, body={})
            log("claim code=%-18s -> %s %s" % (code, http, raw[:200]))
        except Exception as e:  # noqa: BLE001
            log("claim code=%-18s -> 失败 %s" % (code, str(e)[:120]))

    log("[4/4] 任务列表变体（找隐藏的每日任务从哪露出）")
    for method, path, body in (
        ("GET", "/v2/activity/growth/tasks", None),
        ("GET", "/activity/growth/tasks", None),
        ("GET", "/v2/activity/growth/tasks?type=daily", None),
        ("GET", "/v2/activity/growth/tasks?include_daily=1", None),
        ("GET", "/v2/activity/growth/daily-tasks", None),
        ("GET", "/v2/activity/growth/tasks/daily", None),
    ):
        try:
            code, raw = api(method, path, body=body)
            log("%s %s -> %s %s" % (method, path, code, raw[:600]))
        except Exception as e:  # noqa: BLE001
            log("%s %s -> 失败 %s" % (method, path, str(e)[:120]))

    log("[5/5] v1 等级任务清单全量 + 逐 code 领取")
    # v1 /activity/growth/tasks 返回的是"等级任务"（养虾尝试→老手，与 v2 任务清单
    # 是两套东西），前端用户中心不用它，App 用——弹窗每日领取大概率就是这一套。
    try:
        code, raw = api("GET", "/activity/growth/tasks")
        log("v1 全量: %s" % raw[:4000])
        try:
            codes = [t.get("code") for t in json.loads(raw)["data"]["tasks"]]
        except Exception:  # noqa: BLE001
            codes = []
        log("v1 codes: %s" % codes)
        for c in codes:
            try:
                http, rraw = api("POST", "/activity/growth/tasks/%s/claim" % c, body={})
                log("v1 claim %-20s -> %s %s" % (c, http, rraw[:200]))
            except Exception as e:  # noqa: BLE001
                log("v1 claim %-20s -> 失败 %s" % (c, str(e)[:120]))
    except Exception as e:  # noqa: BLE001
        log("v1 清单读取失败：%s" % str(e)[:120])

    log("[6/6] 第四轮：公众号任务/等级徽章/分享奖励等最后一组候选")
    for method, path, body in (
        # 公众号任务（+100积分+5能量，唯一与弹窗奖励数值完全一致的已知项）
        ("POST", "/activity/growth/tasks/wb_wechat_oa_subscribe_task/claim", {}),
        ("GET", "/v1/activity/growth/subscribe-task/status", None),
        ("GET", "/v2/activity/growth/subscribe-task", None),
        ("POST", "/v2/activity/growth/subscribe-task/claim", {}),
        ("POST", "/v1/activity/growth/subscribe-task/claim", {}),
        # 等级徽章领取（v1 等级任务列表 status=available，可能另有领取口）
        ("POST", "/v2/activity/growth/badges/first_chat/claim", {}),
        ("POST", "/v2/activity/growth/badges/expert_summoned/claim", {}),
        ("POST", "/activity/growth/level-tasks/first_chat/claim", {}),
        # 热力图分享奖励（POST 语义， daily share bonus 候选）
        ("POST", "/activity/growth/heatmap/share", {}),
        # 其他每日奖励 guess
        ("GET", "/v2/activity/growth/claimable", None),
        ("GET", "/v2/activity/growth/daily-bonus", None),
        ("POST", "/activity/growth/daily-bonus/claim", {}),
    ):
        try:
            code, raw = api(method, path, body=body)
            log("%-6s %-55s -> %s %s" % (method, path, code, raw[:250]))
        except Exception as e:  # noqa: BLE001
            log("%-6s %-55s -> 失败 %s" % (method, path, str(e)[:120]))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
