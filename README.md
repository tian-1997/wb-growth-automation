# WorkBuddy「Buddy 加油站」每日自动化

用 GitHub Actions 定时完成两件事，并把结果推送到**企业微信群机器人**：

1. **签到**：读取 Buddy 加油站/成长中心今日打卡状态（连续天数、能量余额、等级）
2. **派猫猫旅行**：先领掉已到家（arrived）的旅行积分，再判断能否派新的一趟——今天已派过（`daily_limit_reached`）就不派

> **关于「签到」的说明（重要）**：经核对前端 API 模块，该体系的每日打卡由使用 WorkBuddy 的行为自动记录，服务端**没有「手动签到」POST 接口**（`streak`/`heatmap` 均为只读 GET）。因此脚本做的是「读取并报告今日签到状态」——接口调用成功即视为签到状态获取成功。
>
> **结论口径**：签到部分成功即算整体成功（退出码 0），猫猫部分失败不影响签到结论。

---

## 目录结构

```
wb-growth-automation/
├── .github/workflows/daily-growth.yml   # GitHub Actions 定时任务
└── scripts/
    ├── refresh_token.py                 # 本机导出 token（只写 stdout，不落盘）
    ├── run_refresh.sh                   # command -v 动态取 python 跑上面的脚本
    └── daily_growth.py                  # 核心自动化（纯标准库，无第三方依赖）
```

---

## 部署步骤（一次性）

### 1. 建仓库并推送

```bash
mkdir wb-growth-automation && cd wb-growth-automation
# 把本目录的全部文件拷进来，然后：
git init && git add -A && git commit -m "WorkBuddy daily growth automation"
git remote add origin git@github.com:<owner>/<repo>.git
git push -u origin main
```

### 2. 注入 Secret（token 不进仓库、不进日志）

在本机（已登录 WorkBuddy 的机器）执行：

```bash
cd scripts
sh run_refresh.sh | gh secret set WB_TOKEN --repo <owner>/<repo>
```

没有 `gh` CLI 的话，等价做法（二选一）：

- 先 `sh run_refresh.sh > wb_token.txt`，然后到仓库 **Settings → Secrets and variables → Actions → New repository secret**，Name 填 `WB_TOKEN`，Value 粘贴文件内容。**用完删掉 `wb_token.txt`，且不要提交它。**
- 或安装 gh CLI（https://cli.github.com）后按上面的管道命令执行。

可选 Secret：

| Secret | 作用 | 缺省行为 |
|---|---|---|
| `WB_TOKEN` | **必填**，WorkBuddy accessToken（JWT） | 无 |
| `WB_WECOM_WEBHOOK` | 企业微信群机器人 webhook 完整 URL | 不配置则只跑流程、不推送 |
| `WB_TRAVEL_LOCATION_ID` | 指定派猫目的地 id | 自动取目的地列表第一个 |

### 3. 触发一次验收

推送后进入仓库 **Actions → daily-growth → Run workflow** 手动跑一次。日志里会打印脱敏后的原始返回（`WB_DEBUG_RAW=1`），不含 token。

---

## 定时说明

- 默认 cron：`0 1 * * *`（UTC 01:00 = **北京时间每天 09:00**）
- 想改时间就改 `daily-growth.yml` 里那一行 `cron`（注意是 **UTC**，北京时间 = UTC+8）
- GitHub Actions 的 schedule 是尽力而为，高峰可能延迟几分钟到十几分钟，属正常现象
- `workflow_dispatch` 保留手动触发入口，随时可立即跑

---

## Token 刷新周期

- 登录态文件：`%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info`（可用 `WB_INFO_PATH` 覆盖）
- token 为明文 JWT，**有效期约 30 天**。过期后 Actions 会返回 401，届时在本机重新打开一次 WorkBuddy（它会自动刷新登录态），再跑一次第 2 步的 `run_refresh.sh | gh secret set` 即可
- `refresh_token.py` 会在 stderr 提示剩余有效天数（如 `有效期还剩约 12.3 天`），不污染 stdout 的 token 管道

---

## 已实测的真实接口（HTTP 200，非网传旧接口）

| 功能 | 方法 | 路径 |
|---|---|---|
| 派猫状态 | GET | `/activity/growth/buddy/travel/status` |
| 领到家积分 | POST | `/activity/growth/buddy/travel/claim` |
| 派出新一趟 | POST | `/activity/growth/buddy/travel/depart` `{location_id}` |
| 旅行目的地 | GET | `/activity/growth/buddy/travel/config` |
| 连续签到 | GET | `/activity/growth/streak` |
| 能量余额 | GET | `/activity/growth/energy` |
| 打卡热力图 | GET | `/activity/growth/heatmap` |
| 成长概况 | GET | `/v2/activity/growth/profile` |

接口定义来自登录后 SPA（usercenter）的 `growthSpace-*.js` API 模块，与桌面端实际请求一致。

---

## 本地验收记录（2026-10-14，真实 token 实测）

```
== 1) 签到（成长状态） ==
今日(2026-10-14)已打卡，连续签到 7 天，能量余额 13，等级 玩虾老手(4)
== 2) 派猫猫旅行 ==
派猫猫：已派出一趟去「咖啡馆」（HTTP 200）。
== 3) 推送企业微信 ==
[wecom] 未配置 WB_WECOM_WEBHOOK，跳过推送。
---- 脱敏原始返回 ----
签到.raw: {"profile":{"code":0,...,"data":{"completed":4,"level":4,"level_name":"玩虾老手","total":17}},
           "streak":{"code":0,...,"data":{"streak":{"days":7,...}}},
           "energy":{"code":0,...,"data":{"balance":13,"total_consumed":10,"total_earned":23}}}
猫猫.status: {"state":"idle","buddy_id":"<redacted>","record_id":"<redacted>","daily_limit_reached":false,...}
猫猫.depart: {"code":0,"msg":"OK",...,"data":{"state":"traveling","location":{"id":1,"code":"coffee","name":"咖啡馆","duration_hours":2},"depart_at":1791953723,"arrive_at":1791960923,...}}
```

验证点：签到状态读取成功（连续 7 天 / 能量 13 / Lv4）；派猫猫状态机正确从 `idle` → `traveling`；`arrive_at` 约 2 小时后到期，下次运行会先 `claim` 再判断派新。

---

## 已知限制

- 本机当前未安装 `gh` CLI，secret 注入需用网页端粘贴方式（见第 2 步）
- 推送渠道按标题要求做的是**企业微信**群机器人（markdown）。若实际想推**飞书**，告诉我，把 `push_wecom()` 换成飞书自定义机器人 webhook（JSON `msg_type:text` 或 interactive 卡片）即可，其余逻辑不变
