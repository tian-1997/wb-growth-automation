#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_growth.py — WorkBuddy「Buddy 加油站 / 成长中心」每日自动化。

一次运行做两件事（状态分开记录、分开上报）：
  1) 签到（Buddy 加油站打卡 / 成长状态）
     - 读取 profile / streak / energy / heatmap，报告今日打卡状态。
     - 说明：该体系的每日「打卡/签到」由使用 WorkBuddy 的行为自动记录，
       服务端没有"手动签到"接口（已核对前端 API 模块确认）。因此这一步是
       "读取并报告"今日签到状态；只要接口调用成功即视为签到状态获取成功。
  2) 派猫猫旅行（buddy travel）
     - 先 GET travel/status：
         state == "arrived"  -> POST travel/claim 领跑到家的积分
     - 再判断能否派新的一趟：
         仅当 state 属于"空闲(idle/done/home)" 且 daily_limit_reached == False
         才 POST travel/depart {location_id}；今天已派过(daily_limit_reached)
         或猫在旅行中(traveling/arrived)则不派。
     - 猫猫部分任何失败都不影响"签到"结论。

凭证（都不进仓库、不进日志）：
  WB_TOKEN            必填，WorkBuddy accessToken（JWT）。GitHub 侧来自 secret。
  WB_WECOM_WEBHOOK    可选，企业微信群「消息推送」（原群机器人，v4.1.41 改名）的 webhook 完整 URL。缺省则只打印不上报。

其余可选：
  WB_BASE             默认 https://www.workbuddy.cn
  WB_TRAVEL_LOCATION_ID  派猫目的地 id；缺省取 travel/config 第一个地点。
  WB_TZ_OFFSET        仅用于把服务端时间折算"今天"，默认 +8（Asia/Shanghai）。

退出码：0 = 签到状态获取成功（无论猫猫成败）；1 = 签到部分失败。
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
import ssl
import datetime

BASE = os.environ.get("WB_BASE", "https://www.workbuddy.cn").rstrip("/")
TOKEN = os.environ.get("WB_TOKEN", "").strip()
WEBHOOK = os.environ.get("WB_WECOM_WEBHOOK", "").strip()
LOC_ID = os.environ.get("WB_TRAVEL_LOCATION_ID", "").strip()
TZ_OFFSET = int(os.environ.get("WB_TZ_OFFSET", "8"))

# 用于脱敏的敏感字段名（大小写不敏感包含匹配）
_SENS = ("token", "authorization", "cookie", "secret", "password", "phone",
         "openid", "unionid", "session", "jti", "sid", "client_token", "uid",
         "instance_id", "record_id", "buddy_id")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def redact(o):
    """脱敏：敏感键打码；超长字符串截断；用于打印/上报，绝不外泄 token。"""
    if isinstance(o, dict):
        return {k: ("<redacted>" if any(s in k.lower() for s in _SENS) else redact(v))
                for k, v in o.items()}
    if isinstance(o, list):
        return [redact(x) for x in o]
    if isinstance(o, str) and len(o) > 72:
        return o[:18] + "...<len=%d>" % len(o)
    return o


def api(method, path, body=None, timeout=25):
    """调用 WorkBuddy 网关。返回 (http_status, parsed_json_or_text)。"""
    if not TOKEN:
        raise RuntimeError("WB_TOKEN 未设置")
    url = BASE + path
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Origin": BASE,
        "Referer": BASE + "/profile/",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, _parse(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        return e.code, _parse(raw)


def _parse(raw):
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"_raw": raw[:500]}


def data_of(resp):
    """统一取 data；兼容 {code,msg,data} 与直接 dict。"""
    if isinstance(resp, dict) and isinstance(resp.get("data"), (dict, list)):
        return resp["data"]
    return resp if isinstance(resp, dict) else {}


def today_str(server_now=None):
    # 不用 utcfromtimestamp()：Python 3.12+ 已废弃，新版镜像上会刷警告
    t = server_now or time.time()
    dt = datetime.datetime.fromtimestamp(
        t + TZ_OFFSET * 3600, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _pick_balance(d):
    """从 summary 响应里挑余额字段，兼容 balance/credits/points/total 等命名。"""
    if not isinstance(d, dict):
        return None
    for k in ("balance", "credits", "credit", "points", "point",
              "total", "remain", "remaining", "amount", "value"):
        v = d.get(k)
        if isinstance(v, (int, float)):
            return v
    return None


def _energy_balance():
    """能量余额；失败返回 None。"""
    try:
        _, en = api("GET", "/activity/growth/energy")
        v = data_of(en).get("balance")
        return v if isinstance(v, (int, float)) else None
    except Exception:  # noqa: BLE001
        return None


def _credits_balance():
    """积分余额（redeem/summary，兑换体系的积分池）；失败返回 None。"""
    try:
        _, rd = api("GET", "/activity/growth/redeem/summary")
        return _pick_balance(data_of(rd))
    except Exception:  # noqa: BLE001
        return None


# ---------------- 第一部分：签到（成长状态，读取并报告） ----------------
def do_checkin():
    result = {"ok": False, "lines": [], "detail": {}}
    try:
        _, profile = api("GET", "/v2/activity/growth/profile")
        _, streak = api("GET", "/activity/growth/streak")
        _, energy = api("GET", "/activity/growth/energy")
        _, heatmap = api("GET", "/activity/growth/heatmap")
        _, redeem = api("GET", "/activity/growth/redeem/summary")
    except Exception as e:  # noqa: BLE001
        result["lines"].append("签到状态获取失败：%s" % e)
        return result

    prof = data_of(profile)
    st = data_of(streak)
    en = data_of(energy)
    hm = data_of(heatmap)

    streak_days = ((st.get("streak") or {}).get("days")) if isinstance(st, dict) else None
    energy_balance = en.get("balance") if isinstance(en, dict) else None
    credits = _pick_balance(data_of(redeem))
    level = prof.get("level") if isinstance(prof, dict) else None
    level_name = prof.get("level_name") if isinstance(prof, dict) else None

    # 今日是否已打卡：heatmap cells 里找"今天"，看 score/state
    today = today_str()
    today_checked = None
    if isinstance(hm, dict):
        for cell in hm.get("cells", []) or []:
            if cell.get("date") == today:
                sc = cell.get("score")
                state = cell.get("state")
                today_checked = bool(sc and sc > 0) or state in ("checked", "today_checked")
                break

    result["ok"] = True
    result["detail"] = {
        "level": level, "level_name": level_name,
        "streak_days": streak_days, "energy_balance": energy_balance,
        "credits": credits, "today": today, "today_checked": today_checked,
    }
    seg = "已打卡" if today_checked else ("未打卡" if today_checked is False else "状态未知")
    line = "今日(%s)%s" % (today, seg)
    if streak_days is not None:
        line += "，连续签到 %s 天" % streak_days
    if energy_balance is not None:
        line += "，能量余额 %s" % energy_balance
    if credits is not None:
        line += "，积分余额 %s" % credits
    if level_name:
        line += "，等级 %s(%s)" % (level_name, level)
    result["lines"].append(line)
    # 原始返回（脱敏）存档，便于验收
    result["raw"] = {"profile": redact(profile), "streak": redact(streak),
                     "energy": redact(energy), "redeem": redact(redeem)}
    return result


# ---------------- 第二部分：派猫猫旅行（先领后派） ----------------
def do_travel():
    result = {"ok": False, "lines": [], "actions": []}
    try:
        _, status = api("GET", "/activity/growth/buddy/travel/status")
    except Exception as e:  # noqa: BLE001
        result["lines"].append("派猫猫：读取状态失败：%s" % e)
        return result

    sd = data_of(status)
    state = sd.get("state")
    daily_limit = bool(sd.get("daily_limit_reached"))
    reward = sd.get("reward_credit")
    result["status"] = redact(sd)
    result["ok"] = True

    # 1) 先领：猫已到家(arrived) -> claim
    if state == "arrived":
        try:
            e_before = _energy_balance()
            code, claim = api("POST", "/activity/growth/buddy/travel/claim", body={})
            cd = data_of(claim)
            got = cd.get("reward_credit", reward)
            result["lines"].append("派猫猫：猫猫已到家，领取积分 %s（HTTP %s）" % (got, code))
            result["actions"].append("claim")
            result["claim_raw"] = redact(claim)
            # 到账验证（服务端真相优先）：
            # 旅行奖励只进积分池、不进能量池，所以"能量没动"不能判定未到账；
            # 以 travel/records 里今天这条的 claimed_at / reward_credit 为准。
            # （2026-10-16 修复：旧逻辑拿能量余额做唯一判据，积分池不可读时会误报。）
            credited_server_side = None
            try:
                _, recs = api("GET", "/activity/growth/buddy/travel/records")
                result["records_raw"] = redact(recs)
                for rec in (data_of(recs).get("records") or []):
                    if rec.get("travel_date") == today_str():
                        claimed_at = rec.get("claimed_at")
                        rc = rec.get("reward_credit")
                        credited_server_side = bool(claimed_at) and (rc == got or rc is None)
                        result["claim_record"] = {
                            "travel_date": rec.get("travel_date"),
                            "reward_credit": rc,
                            "claimed_at": claimed_at,
                        }
                        break
            except Exception:  # noqa: BLE001
                pass
            e_after = _energy_balance()
            c_after = _credits_balance()
            result["claim_deltas"] = [("能量", e_before, e_after)]
            if c_after is not None:
                result["claim_deltas"].append(("积分", None, c_after))
            if credited_server_side is True:
                result["lines"].append("到账验证：服务端已记录本次领取（claimed_at 已写、积分 %s）。" % got)
            elif credited_server_side is False:
                result["claim_not_credited"] = True
                result["lines"].append(
                    "⚠️ 服务端记录显示本次领取未入账（claimed_at 未写），建议去 App 内手动领一次")
            else:
                # 记录读不到时的降级判断：只在积分池可读时判定，能量不动不算未到账
                result["lines"].append(
                    "到账验证：travel/records 不可读，本次仅按 HTTP 200 归档；能量 %s→%s（旅行奖励不进能量池，属正常）。"
                    % (e_before, e_after))
            # 领完后刷新一次状态，决定接下来能否派
            _, status2 = api("GET", "/activity/growth/buddy/travel/status")
            sd = data_of(status2)
            state = sd.get("state")
            daily_limit = bool(sd.get("daily_limit_reached"))
        except Exception as e:  # noqa: BLE001
            result["lines"].append("派猫猫：领取失败：%s" % e)
            return result

    # 2) 再派：仅空闲且今日未派过才派新的一趟
    idle_states = ("idle", "done", "home", "")
    if state in idle_states:
        if daily_limit:
            result["lines"].append("派猫猫：今天已经派过啦，明天再来（不再重复派）。")
        else:
            loc_id = LOC_ID
            loc_name = None
            if not loc_id:
                try:
                    _, cfg = api("GET", "/activity/growth/buddy/travel/config")
                    locs = data_of(cfg).get("locations") or []
                    if locs:
                        loc_id = locs[0].get("id")
                        loc_name = locs[0].get("name")
                except Exception as e:  # noqa: BLE001
                    result["lines"].append("派猫猫：获取目的地失败：%s" % e)
                    return result
            if loc_id in (None, ""):
                result["lines"].append("派猫猫：没有可用目的地，跳过派猫。")
                return result
            try:
                code, dep = api("POST", "/activity/growth/buddy/travel/depart",
                                body={"location_id": loc_id})
                dd = data_of(dep)
                ok = (isinstance(dep, dict) and dep.get("code") == 0)
                where = loc_name or ("地点#%s" % loc_id)
                if ok:
                    result["lines"].append(
                        "派猫猫：已派出一趟去「%s」（HTTP %s）。" % (where, code))
                    result["actions"].append("depart")
                else:
                    result["lines"].append(
                        "派猫猫：派出未成功（HTTP %s）：%s" % (code, redact(dep)))
                result["depart_raw"] = redact(dep)
            except Exception as e:  # noqa: BLE001
                result["lines"].append("派猫猫：派出失败：%s" % e)
                return result
    elif state == "traveling":
        result["lines"].append("派猫猫：猫猫还在旅行中，等她回家再领。")
    elif state == "arrived":
        result["lines"].append("派猫猫：猫猫已到家（领取步骤见上）。")
    else:
        result["lines"].append("派猫猫：当前状态 %s，不派新趟。" % state)

    # 旅行记录：每次都拉一次（不只领取时），便于从运行记录核对历史领取是否入账
    if "records_raw" not in result:
        try:
            _, recs = api("GET", "/activity/growth/buddy/travel/records")
            result["records_raw"] = redact(recs)
        except Exception:  # noqa: BLE001
            pass

    return result


# ---------------- 企业微信推送 ----------------
def push_wecom(checkin, travel):
    if not WEBHOOK:
        log("[wecom] 未配置 WB_WECOM_WEBHOOK，跳过推送。")
        return False
    # 不用 utcnow()：Python 3.12+ 已废弃
    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=TZ_OFFSET)
    title = "WorkBuddy 加油站 · 每日自动化（%s）" % now.strftime("%Y-%m-%d %H:%M")

    c_ok = checkin.get("ok")
    c_lines = "\n".join("> %s" % x for x in checkin.get("lines", [])) or "> 无"
    t_ok = travel.get("ok")
    t_lines = "\n".join("> %s" % x for x in travel.get("lines", [])) or "> 无"
    # 猫猫小节的标题按本次实际动作措辞
    acts = travel.get("actions") or []
    if "claim" in acts and "depart" in acts:
        t_head = "已领积分 + 已派新趟"
    elif "depart" in acts:
        t_head = "已派新趟"
    elif "claim" in acts:
        t_head = "已领到积分"
    else:
        t_head = "完成" if t_ok else "失败/跳过"

    content = (
        "**%s**\n"
        "**🛢 签到（Buddy 加油站）**：%s\n%s\n"
        "**🐱 派猫猫旅行**：%s\n%s"
    ) % (
        title,
        "成功" if c_ok else "失败",
        c_lines,
        t_head,
        t_lines,
    )
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    # 云端续签写回失败时附一行告警（自动续期链约 60 天后会断）
    if os.environ.get("WB_RENEW_WARN") == "1":
        content += ("\n> ⚠️ 凭证自动续期写回失败（检查 WB_GH_PAT），"
                    "约 60 天后需按 README 重新播种 WB_REFRESH_TOKEN")
        payload = {"msgtype": "markdown", "markdown": {"content": content}}
    req = urllib.request.Request(
        WEBHOOK, method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context()) as r:
            body = r.read().decode("utf-8", "replace")
            log("[wecom] push HTTP %s %s" % (r.status, body[:200]))
            return r.status == 200 and '"errcode":0' in body
    except Exception as e:  # noqa: BLE001
        log("[wecom] push failed: %s" % e)
        return False


def main():
    if not TOKEN:
        log("错误：未设置 WB_TOKEN。")
        return 1

    log("== 1) 签到（成长状态） ==")
    checkin = do_checkin()
    for x in checkin.get("lines", []):
        log("   " + x)

    log("== 2) 派猫猫旅行 ==")
    travel = do_travel()
    for x in travel.get("lines", []):
        log("   " + x)

    log("== 3) 推送企业微信 ==")
    # 多档位轮询模式下，只有"有实质动作"或"出错"才推送，避免重复刷屏：
    #   - 领到了积分（claim）或派出了新趟（depart）
    #   - 签到/猫猫任一环节出错（失败必须可见）
    #   - 凭证续期写回失败（自动续期链约 60 天后会断，需提前知晓）
    # 静默运行 = 心跳机制：群里没消息且 Actions 无新记录 = 调度器丢槽位。
    # 例外：设 WB_FORCE_PUSH=1 时无条件推送（调试/验收用）。
    acts = travel.get("actions") or []
    renew_warn = os.environ.get("WB_RENEW_WARN") == "1"
    force_push = os.environ.get("WB_FORCE_PUSH") == "1"
    actionable = bool(acts) or not checkin.get("ok") or not travel.get("ok") or renew_warn
    if actionable or force_push:
        push_wecom(checkin, travel)
    else:
        log("[wecom] 本次无实质动作（旅行中/今日已派过），跳过推送。")

    # 脱敏原始返回（验收用）：打印到 stderr，不含 token
    if os.environ.get("WB_DEBUG_RAW") == "1":
        log("---- 脱敏原始返回 ----")
        log("签到.raw:", json.dumps(checkin.get("raw", {}), ensure_ascii=False)[:1500])
        log("猫猫.status:", json.dumps(travel.get("status", {}), ensure_ascii=False)[:1200])
        if "claim_raw" in travel:
            log("猫猫.claim:", json.dumps(travel["claim_raw"], ensure_ascii=False)[:800])
        if "claim_deltas" in travel:
            log("猫猫.claim_deltas:", json.dumps(travel["claim_deltas"], ensure_ascii=False)[:300])
        if "records_raw" in travel:
            log("猫猫.records:", json.dumps(travel["records_raw"], ensure_ascii=False)[:1200])
        if "depart_raw" in travel:
            log("猫猫.depart:", json.dumps(travel["depart_raw"], ensure_ascii=False)[:800])
        # 积分余额端点探测（一次性诊断）：旅行奖励只进积分池，但积分池的
        # 余额端点一直没定位到（redeem/summary 只有兑换计数、订阅体系的
        # remainCredits 是另一套）。逐个试候选端点，找到含余额字段的那个。
        log("---- 积分余额端点探测 ----")
        for path in (
            "/activity/growth/lottery/summary",
            "/activity/growth/lottery/prizes",
            "/activity/growth/buddy/info",
            "/v2/activity/growth/badges",
            "/v2/activity/growth/tasks",
            "/profile/assets/plans-usage/standard",
        ):
            try:
                code, resp = api("GET", path, timeout=15)
                log("探测 %s -> HTTP %s %s" % (path, code,
                    json.dumps(redact(resp), ensure_ascii=False)[:400]))
            except Exception as e:  # noqa: BLE001
                log("探测 %s -> 失败 %s" % (path, str(e)[:120]))

    # 结论：签到状态获取成功即算成功（猫猫成败不影响）
    return 0 if checkin.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
