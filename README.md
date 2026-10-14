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
├── .github/workflows/daily-growth.yml   # GitHub Actions 定时任务
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

- 默认 cron：`0 1 * * *`（UTC 01:00 = **北京时间每天 09:00**）
- 想改时间就改 `daily-growth.yml` 里那一行 `cron`（注意是 **UTC**，北京时间 = UTC+8）
- GitHub Actions 的 schedule 是尽力而为，高峰可能延迟几分钟到十几分钟，属正常现象
- `workflow_dispatch` 保留手动触发入口，随时可立即跑

---

## Token 刷新周期

- 登录态文件：`%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info`（可用 `WB_INFO_PATH` 覆盖）
- token 为明文 JWT：**accessToken 寿命 30 天，refreshToken 寿命约 60 天**
- 刷新接口（从桌面 app 主进程代码挖出，非网传接口）：`POST /v2/plugin/auth/token/refresh`，头带 `X-Refresh-Token` / `X-Auth-Refresh-Source: plugin` / `X-Domain: www.workbuddy.cn`
- **实测该接口不废止旧 refreshToken**（同一个 RT 可重复调用），所以云端续期和桌面 app 自己的续期互不冲突、互不踢号
- `refresh_token.py` 会在 stderr 提示剩余有效天数（如 `有效期还剩约 12.3 天`），不污染 stdout 的 token 管道

---

## 无感续签（推荐，一次配置后永久免管）

默认方案每个月要人工续一次 token。想彻底无感，加两个 secret 就能让 workflow 每天自动续期：

```
每天 09:00 云端自动：
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

- 本机当前未安装 `gh` CLI，secret 注入需用网页端粘贴方式（见第 2 步）
- 推送渠道为企业微信群「消息推送」（原群机器人，markdown 格式）。markdown 不支持缩进，推送内容里的 `> ` 引用行按官方语法渲染为引用块
- 企业微信「消息推送」仅支持内部群；若目标群含外部微信用户，需换内部群（见第 3 步限制清单）
