# WorkBuddy「Buddy 加油站」每日自动化

用 GitHub Actions 定时完成两件事，并把结果推送到**企业微信**（群机器人，v4.1.41 起官方更名为「消息推送」）：

1. **签到**：读取 Buddy 加油站/成长中心今日打卡状态（连续天数、能量余额、等级）
2. **派猫猫旅行**：先领掉已到家（arrived）的旅行积分，再判断能否派新的一趟——今天已派过（`daily_limit_reached`）就不派

> **关于「签到」的说明（重要）**：经核对前端 API 模块，该体系的每日打卡由使用 WorkBuddy 的行为自动记录，服务端**没有「手动签到」POST 接口**（`streak`/`heatmap` 均为只读 GET）。因此脚本做的是「读取并报告今日签到状态」——接口调用成功即视为签到状态获取成功。
>
> **结论口径**：签到部分成功即算整体成功（退出码 0），猫猫部分失败不影响签到结论。

---

## 目录结构

```
wb-growth-automation/
├── .github/workflows/daily-growth.yml   # GitHub Actions 云端备份触发
├── .github/workflows/balance-diag.yml   # 只读余额诊断（核对积分池归属，不领不派不推送）
├── .env.wecom                            # 本机运行用的 webhook 配置（gitignore，不进仓库）
├── logs/daily.log                        # 本机定时任务运行日志（gitignore）
├── logs/actions/last-run.txt             # Actions 每日运行脱敏记录（提交回仓库，可远程查看）
├── logs/diag/last-diag.txt               # 余额诊断脱敏记录（同上）
└── scripts/
    ├── refresh_token.py                 # 本机导出 token（access/refresh 两种，只写 stdout）
    ├── run_refresh.sh                   # command -v 动态取 python 跑上面的脚本
    ├── renew_token.py                   # 云端无感续签：RT 换新 AT 并写回 secret
    ├── daily_growth.py                  # 核心自动化（纯标准库，无第三方依赖）
    └── test_push.py                     # webhook 连通性测试（只读，零副作用）
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

> 本目录已完成 `git init` 并含首次提交（含 `.gitignore`/`.gitattributes`），只需执行 `git remote add origin ...` + `git push`。

### 2. 注入 Secret（token 不进仓库、不进日志）

在本机（已登录 WorkBuddy 的机器）执行：

```bash
cd scripts
sh run_refresh.sh | gh secret set WB_TOKEN --repo <owner>/<repo>
```

没有 `gh` CLI 的话，等价做法（二选一）：

- 先 `sh run_refresh.sh > wb_token.txt`，然后到仓库 **Settings → Secrets and variables → Actions → New repository secret**，Name 填 `WB_TOKEN`，Value 粘贴文件内容。**用完删掉 `wb_token.txt`，且不要提交它。**
- 或安装 gh CLI（https://cli.github.com）后按上面的管道命令执行。

> **Git Bash 用户注意**：`run_refresh.sh` 内部已规避 MSYS 路径转换问题（`/c/...` 被错误转成 `C:\c\...`）——做法是先 `cd` 到脚本目录再用相对文件名调 python。如果你在自己的脚本里拼绝对路径调 Windows 版 python，也会踩同一个坑。

可选 Secret：

| Secret | 作用 | 缺省行为 |
|---|---|---|
| `WB_TOKEN` | **必填**，WorkBuddy accessToken（JWT）；无感续签生效后仅作兜底 | 无 |
| `WB_WECOM_WEBHOOK` | 企业微信群「消息推送」的 webhook 完整 URL | 不配置则只跑流程、不推送 |
| `WB_REFRESH_TOKEN` | 可选，refreshToken；配了就启用每天云端无感续签（见下文专节） | 不配置则维持 30 天人工续 |
| `WB_GH_PAT` | 可选，fine-grained PAT（Secrets: write）；续签后把新 RT 写回 secret 用 | 不配置则续签照跑但 60 天后要重新播种 |
| `WB_TRAVEL_LOCATION_ID` | 指定派猫目的地 id | 自动取目的地列表第一个 |

### 3. 获取企业微信 webhook（「消息推送」）

> **入口改名提示**：企业微信 v4.1.41 起「群机器人」更名为「**消息推送**」，在群设置面板里找「消息推送」即可，位置不变。

操作路径：

1. 打开目标群聊 → 右上角 "..." → 聊天信息面板
2. 点「**消息推送**」→ 添加 → 新建 → 起名（如 "Buddy日报"）→ 创建
3. 点刚建的消息推送 → 复制 **Webhook 地址**
4. 到仓库 Settings → Secrets and variables → Actions 存成 secret，Name 填 `WB_WECOM_WEBHOOK`

已知限制（企业微信官方帮助中心）：

- 仅**内部群**支持；群里含外部联系人（微信用户）时不显示该入口
- 群开启「仅群主可管理」时，只有群主有添加入口
- 管理员可在后台限制「可创建消息推送的成员」，不在名单内会提示无权限
- 频率上限 20 条/分钟（本方案每天 1 条，无压力）
- 群开启全员禁言时推送不显示，需群主关闭禁言

### 4. 触发一次验收

推送后进入仓库 **Actions → daily-growth → Run workflow** 手动跑一次。日志里会打印脱敏后的原始返回（`WB_DEBUG_RAW=1`），不含 token。

**部署前先验证 webhook**（可选但推荐）：本机跑

```bash
WB_WECOM_WEBHOOK=<你的webhook地址> WB_TOKEN=$(sh scripts/run_refresh.sh) python scripts/test_push.py
```

只读接口 + 发一条带【格式测试】标记的消息，不派猫不领积分，零副作用。返回 `{"errcode":0,"errmsg":"ok"}` 即通。

---

## 定时说明

### 主触发：WorkBuddy 定时任务（每天 15:05，本机执行）

2026-10-16 起的主触发方式，已在 WorkBuddy 里配好两个 recurring automation：

| 任务 | 时间 | 作用 |
|---|---|---|
| Buddy加油站每日自动化（15:05主档） | 每天 15:05 | 正式每日跑 |
| Buddy加油站每日自动化（20:05晚档备份） | 每天 20:05 | 下午电脑没开时的补跑 |

实测特性（2026-10-16 探针验证）：

- **准点**：预定 09:18:00 触发，实际 09:18:37 执行，误差 37 秒——不像 GitHub 调度器那样丢槽位
- **本机执行**：运行在你的电脑上（探针确认主机名、工作目录、登录态文件均可访问）
- **token 永远新鲜**：每次跑都用 `run_refresh.sh` 从本机登录态现取 token，**30 天过期问题不存在**
- 运行日志追加在 `logs/daily.log`（已 gitignore），排查问题先看它

**唯一条件**：到点时电脑和 WorkBuddy 要开着。15:05 没开就 20:05 备份档补上；两档都错过，靠下面的 GitHub Actions 云端兜底。

### 备份触发：GitHub Actions 每小时轮询（云端执行）

workflow 的 cron 是 `5 7-12 * * *`（UTC 每小时 07:05~12:05 = **北京时间 15:05~20:05，每小时一档**）。本机两档都错过时，云端任一档跑成也能完成当天任务；`workflow_dispatch` 保留手动触发入口，另外**改动 workflow 文件并推送**也会立刻触发一次（应急补跑用）。

为什么云端是「每小时一档」而不是「每天一档」：2026-10-15 实测，GitHub 调度器**连续丢掉三个槽位**（01:00 / 06:07 / 07:05 UTC 全部静默消失，无记录无通知）。第三方同期实测（Hyperping，10 月）：单槽跑成率仅 64%，新仓库优先级最低。每天 6 档即使按 64% 算，至少一档跑成的概率 ≈ 99.4%。

云端跑的稳健性保证：

- 脚本幂等：服务端硬限制「一天只派一次」，重复跑不会重复派猫；`arrived` 才会 claim，不会重复领
- **只在有实质动作时才推企业微信**（领到积分 / 派出新趟 / 任一环节出错 / 续期告警）——跑成几档都不刷屏，正常一天 1~2 条（派出一条 + 猫到家领一条）
- 想强制推送（调试用）：设 `WB_FORCE_PUSH=1`

**心跳机制**：企业微信群里收到「派猫猫」相关消息 = 当天跑成过；**连续整天群里静默 = 所有触发都 miss 了**，先看 `logs/daily.log`（本机两档跑没跑），再看 Actions 页面（云端跑没跑）。

### GitHub 定时任务的可靠性真相（备查）

GitHub 官方文档原文：*"The schedule event can be delayed during periods of high loads... If the load is sufficiently high enough, some queued jobs may be dropped."*

2026 年 10 月的第三方实测数据（Hyperping，4 个公开仓库、7 天）：

| 指标 | 实测值 |
|---|---|
| 时间槽真正跑成的比例 | **仅 64%** |
| 中位启动延迟 | 7.4 分钟 |
| 两次运行间隔 ≥25 分钟的比例 | 25.7% |
| 最长间隔 | **137 分钟** |

其他已知规律：丢掉的槽位不会补跑（无失败记录、无通知）；公共仓库 60 天无提交会被自动禁用 schedule（我们不涉及）。

### 备选：外部调度器（追求准点才需要）

多档轮询已经足够稳健。如果追求「每天精确 15:05 一条消息」，用外部免费 cron 服务打 GitHub API，**绕开它的调度队列**（手动触发从来可靠）：

1. **给 PAT 加权限**：GitHub → Settings → Developer settings → Personal access tokens → Fine-grained → 选 `wb-growth-automation` 仓库 → 权限勾选 **Actions: Read and write**（就是已有的 `WB_GH_PAT`，编辑加权限即可）
2. **注册 cron-job.org**（免费）：新建任务
   - URL：`https://api.github.com/repos/tian-1997/wb-growth-automation/actions/workflows/daily-growth.yml/dispatches`
   - 方法：**POST**
   - Header：`Authorization: Bearer <你的PAT>`、`Accept: application/vnd.github+json`
   - Body：`{"ref":"main"}`
   - 计划：每天北京时间 15:05（时区 Asia/Shanghai）
3. 之后由 cron-job.org 准点触发；同时可把 workflow 里的 cron 改成每天一档 `5 7 * * *` 作为备份（两条链路互不干扰，服务端限制保证不会重复派猫）

---

## Token 刷新周期

- 登录态文件：`%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info`（可用 `WB_INFO_PATH` 覆盖）
- token 为明文 JWT：**accessToken 寿命 30 天，refreshToken 寿命约 60 天**
- 刷新接口（从桌面 app 主进程代码挖出，非网传接口）：`POST /v2/plugin/auth/token/refresh`，头带 `X-Refresh-Token` / `X-Auth-Refresh-Source: plugin` / `X-Domain: www.workbuddy.cn`
- **实测该接口不废止旧 refreshToken**（同一个 RT 可重复调用），所以云端续期和桌面 app 自己的续期互不冲突、互不踢号
- `refresh_token.py` 会在 stderr 提示剩余有效天数（如 `有效期还剩约 12.3 天`），不污染 stdout 的 token 管道
- **本机定时任务方式不受过期影响**：每次跑都从登录态现取 token，无需任何续期操作（前提是那台电脑登录着 WorkBuddy）；下面的续签机制只是给 GitHub 云端执行路径用的

---

## 无感续签（推荐，一次配置后永久免管）

（**仅 GitHub 云端路径需要**；本机定时任务每次现取 token，无此问题）默认方案每个月要人工续一次 token。想彻底无感，加两个 secret 就能让 workflow 每天自动续期：

```
每天下午时段（15:05~20:05 任一档跑成）云端自动：
  1. 用 secret 里的 WB_REFRESH_TOKEN 调刷新接口 → 拿到新 accessToken（30 天）+ 新 refreshToken（60 天）
  2. 用新 accessToken 跑当天的签到/派猫/推送
  3. 通过 gh CLI + PAT 把新 refreshToken 写回 secret（链条永久滚动，不会断）
```

**一次性配置（3 步）：**

1. **建 PAT**：GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token
   - Repository access：只选 `wb-growth-automation` 这一个仓库
   - Permissions → Repository permissions → **Secrets: Read and write**
   - Expiration 选一年（到期需换一次，届时群里会提前告警）
2. **播种 refreshToken**（本机执行）：

   ```bash
   cd scripts
   sh run_refresh.sh refresh > wb_rt.txt   # 导出 refreshToken
   # 把 wb_rt.txt 内容存为 secret：WB_REFRESH_TOKEN；删掉 wb_rt.txt
   ```

   同时把上一步的 PAT 存为 secret：`WB_GH_PAT`。
3. 推送后手动触发一次 workflow 验证。日志出现 `[renew] 续签成功` + `新 refreshToken 已写回 secret` 即接通。

**降级链**（任何一环断都不会静默）：

| 情况 | 行为 |
|---|---|
| 没配 `WB_REFRESH_TOKEN` | 跳过续签，用 `WB_TOKEN`（维持旧的月续模式） |
| 刷新失败（RT 过期等） | 回退 `WB_TOKEN`；两者都失效则群里收到「签到失败」 |
| 写回失败（PAT 失效等） | 当天照常跑，但日报里附一行 ⚠️ 告警，提醒约 60 天后要重新播种 |

**不想要 PAT 也行**：只配 `WB_REFRESH_TOKEN` 不配 `WB_GH_PAT`，续签照常工作，只是 secret 里的 RT 约 60 天后到期，届时重新跑一次第 2 步即可——也从月续变成双月续。

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

- **本机取 token 依赖 App 的登录态格式**：2026-10-16 起新版 App 把登录态改为加密存储（`$wbEncrypted` 信封，密钥在 App 原生存储），`refresh_token.py` 会明确报错（exit 5）而不是崩溃。此时本机定时任务自动改走**云端 fallback**（更新 workflow 文件标记行并推送，触发 GitHub Actions，云端有完整的 token 续签链），无需人工介入
- 推送渠道为企业微信群「消息推送」（原群机器人，markdown 格式）。markdown 不支持缩进，推送内容里的 `> ` 引用行按官方语法渲染为引用块
- 企业微信「消息推送」仅支持内部群；若目标群含外部微信用户，需换内部群（见第 3 步限制清单）
- **「积分」和「能量」是两个池子，且旅行奖励只进积分池**：travel 的 `reward_credit` 是积分（Credit），`/activity/growth/energy` 的能量余额不会因为领旅行积分而变化——这是正常现象，不是没到账
- **旅行/任务领的积分和界面上的「总剩余积分」是同一个池子（2026-10-19 实测确认）**：`POST /billing/meter/get-user-resource-summary` 返回 `TotalCredits: 2661.6000005`，与账户页「剩余积分 2,661.6」逐位一致。该池由 billing/meter 体系管理（套餐/权益包发分、AI 用量扣分），带小数是因为用量按模型倍率（x0.21/x0.65/x1.20）扣小数；旅行每次只发 8~10 的整数分，落到这个池里。官方活动规则原文（App 内成长中心页面）：「积分（Credit）将在用户点击'领取奖励'后实时到账至用户的积分账户，可用于产品内已开通的积分消费场景」；抽奖中奖文案亦注明「积分已发放，**将在几分钟内到账**」——**到账有分钟级延迟**，收到'已领取'推送后立刻去看余额不会变，过几分钟才变；加上展示界面普遍 `Math.floor` 取整（显示 2,661）、AI 同时在扣分，净变化经常看起来就是 0
- **增长体系没有暴露自己的积分余额接口**（2026-10-16/19 两轮实测：`redeem/summary` 只有兑换档位计数、`lottery/summary` 只有抽奖次数、`lottery/prizes`/`badges`/`tasks`/`buddy/info`/`plans-usage` 均无余额字段）。主账户余额走 `POST /billing/meter/get-user-resource-summary`（前端 usercenter 同款 POST，GET 会 405）；到账验证以**服务端真相**为准：领取后查 `travel/records`，今天这条的 `claimed_at` 已写、`reward_credit` 对得上即判定入账；读不到记录时才降级为 HTTP 200 归档（不再拿能量余额当判据——旧逻辑因此误报过）
- **只读余额诊断**：`balance-diag.yml`（改 workflow 文件推送即触发 / Actions 页手动触发），`WB_DIAG_ONLY=1` 只读状态不领不派不推送，`WB_PROBE_ENDPOINTS=1` 附带上文全部余额端点探测，记录提交到 `logs/diag/last-diag.txt`
- 任务奖励（如「和 AI 聊天 30 次」= 100 积分 + 5 能量值）是积分+能量都给，与旅行奖励不同
