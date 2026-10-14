#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_push.py — 企业微信「消息推送」webhook 连通性 + 消息格式测试。

与 daily_growth.py 的区别：**只读**，不做任何状态变更——
不 depart（派猫）、不 claim（领积分），只 GET 签到相关只读接口拼一条
与线上同格式的测试消息发到群里，用于部署前验收推送效果。

用法：
  WB_WECOM_WEBHOOK=<url> WB_TOKEN=<jwt> python test_push.py
  # 不带 WB_TOKEN 也能跑：用示例数据拼消息，只验证 webhook 通不通

依赖：纯标准库。
退出码：0 = webhook 返回 errcode 0；1 = 失败。
"""
import json
import os
import ssl
import sys
import urllib.request
import urllib.error

BASE = os.environ.get("WB_BASE", "https://www.workbuddy.cn").rstrip("/")
TOKEN = os.environ.get("WB_TOKEN", "").strip()
WEBHOOK = os.environ.get("WB_WECOM_WEBHOOK", "").strip()
TZ_OFFSET = int(os.environ.get("WB_TZ_OFFSET", "8"))


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def api(method, path):
    if not TOKEN:
        raise RuntimeError("WB_TOKEN 未设置")
    req = urllib.request.Request(
        BASE + path, method=method,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
            "Origin": BASE,
            "Referer": BASE + "/profile/",
        })
    with urllib.request.urlopen(req, timeout=25, context=ssl.create_default_context()) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_checkin_lines():
    """只读接口取真实签到数据；失败则回退示例数据。"""
    try:
        prof = (api("GET", "/v2/activity/growth/profile") or {}).get("data") or {}
        st = (api("GET", "/activity/growth/streak") or {}).get("data") or {}
        en = (api("GET", "/activity/growth/energy") or {}).get("data") or {}
        days = (st.get("streak") or {}).get("days")
        line = "今日已打卡"
        if days is not None:
            line += "，连续签到 %s 天" % days
        if en.get("balance") is not None:
            line += "，能量余额 %s" % en["balance"]
        if prof.get("level_name"):
            line += "，等级 %s(%s)" % (prof["level_name"], prof.get("level"))
        return line, True
    except Exception as e:  # noqa: BLE001
        log("[test] 读取签到数据失败，改用示例数据：%s" % e)
        return "今日已打卡，连续签到 7 天，能量余额 13，等级 玩虾老手(4)", False


def main():
    if not WEBHOOK:
        log("错误：未设置 WB_WECOM_WEBHOOK。")
        return 1

    c_line, real = fetch_checkin_lines()

    content = (
        "**WorkBuddy 加油站 · 推送格式测试**\n"
        "（这是一条测试消息，不会产生任何积分/派猫变动）\n"
        "**🛢 签到（Buddy 加油站）**：成功\n"
        "> %s\n"
        "**🐱 派猫猫旅行**：完成\n"
        "> 正式运行时这里显示：猫猫已到家领取积分 / 已派出新一趟 / 今天已派过 / 旅行中"
    ) % c_line

    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    log("[test] 数据来源：%s" % ("真实接口" if real else "示例数据（token 无效或未提供）"))
    log("[test] 发送内容：\n%s" % content)

    req = urllib.request.Request(
        WEBHOOK, method="POST", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context()) as r:
            body = r.read().decode("utf-8", "replace")
            log("[test] HTTP %s %s" % (r.status, body[:300]))
            ok = r.status == 200 and '"errcode":0' in body
            log("[test] %s" % ("推送成功，请到企业微信群确认消息样式" if ok else "webhook 返回异常，请检查上面的响应体"))
            return 0 if ok else 1
    except urllib.error.HTTPError as e:
        log("[test] HTTP %s %s" % (e.code, e.read().decode("utf-8", "replace")[:300]))
        return 1
    except Exception as e:  # noqa: BLE001
        log("[test] 发送失败：%s" % e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
