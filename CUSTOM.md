# 本仓库定制说明（不会被上游同步覆盖）

> 上游：`Devilstore/Glados-Railgun-checkin`。本仓库在它之上只做**加法**，
> 所有上游文件（`checkin.py` / `logging_config.py` / `requirements.txt` /
> `.github/workflows/gladosCheck.yml`）都保持逐字节一致，
> 所以 `git merge upstream/master` 永远不会冲突。

## 为什么定制不写进 checkin.py

上游更新很频繁（2026-10 一个月改了 10+ 次）。把 PushPlus、退出码这些直接改在
`checkin.py` 里，每次同步都要人工解一遍冲突。所以这里改成**运行期注入**：

```
custom_run.py
  ├─ checkin.PushService       ← 换成带 PushPlus 的版本（其余后端保留）
  ├─ checkin.CheckinRunner.run ← 包一层，把签到结果抓出来做异常判定
  └─ 跑完 checkin.main() 后：异常 → 退出码 1 + 额外告警推送
```

workflow 里跑 `python custom_run.py`，不直接跑 `checkin.py`。

## 现在的分工（2026-11-17 起签到已迁到本机）

| 谁 | 在哪 | 触发 | 干什么 |
|---|---|---|---|
| **本机签到** | `local/checkin.mjs` | Windows 计划任务 `GLaDOS Checkin`，每天 **08:40** | **唯一的签到入口**：真 Chrome 打开 `/console/checkin` → 等 Turnstile → 点按钮 |
| **sync upstream** | `sync-upstream.yml` | **青龙面板 00:00（主）**、GitHub schedule（兜底）、手动 | 拉上游；有更新就 merge+push（不签到） |
| ~~glados checkin~~ | `custom-checkin.yml` | — | **已 disabled**。纯 Python 路线（见下方「为什么搬走」） |
| ~~glados watchdog~~ | `watchdog.yml` | — | **已 disabled**，职责被本机计划任务接走 |
| ~~GLaDOS Check-in~~ | `gladosCheck.yml` | — | 上游自带，早就 disabled |

> 为什么签到搬走：2026-11-14 起 GLaDOS 给 `POST /api/user/checkin` 加了 Cloudflare
> Turnstile（interaction-only，后台/无头都不下发 token）。Actions 的 Azure 机房 IP
> 会被强制交互式挑战，纯 HTTP 一律 `code=5 Cloudflare verification failed`。
> 同一台机器上用真浏览器，Turnstile 静默通过 —— 实测 `code=0/+2 分`、`code=1 已签到` 都正常。
> 详见 `local/checkin.mjs` 顶部注释与当日工作日志。

> ⚠️ `custom-checkin.yml` **刻意不挂 `on: push`**。
> 否则每次改代码都会签一次，白白产生一堆「重复签到」的空跑。

### 为什么不用 GitHub 自带的 schedule（2026-11-11）

原先是 `cron: '40 8'` + `timezone: Asia/Shanghai`，实测这个仓库的 schedule 被降级了：

| 应触发（北京 08:40） | 实际落地 | 迟到 |
|---|---|---|
| 11-07 | 14:35 | 5h55m |
| 11-08 | 14:41 | 6h01m |
| 11-09 | 15:10 | 6h30m |
| 11-10 | 15:43 | 7h03m |

**每天再往后漂半小时**，说明是持续欠账不是偶发抖动。同一时期 watchdog
（`0 3-14`，本该 12 次/天）11-10 只落了 1 次，时间 18:29 UTC，超出 cron 区间 4.5 小时。

2026-11-16 复查，sync upstream 的 `cron: '10 8 * * *'` 症状一样、甚至更糟：

| 应触发（北京 08:10，当时 cron 就是 `10 8 * * *`） | 实际落地 | 迟到 |
|---|---|---|
| 11-12 | 15:01 | 6h51m |
| 11-13 | 14:30 | 6h20m |
| 11-14 | 14:08 | 5h58m |
| 11-15 | 14:16 | 6h06m |
| 11-16 | **没跑**（这条 cron 被直接丢弃） | — |

11-16 上游 v1.0.1（扩展版）能被合进来，其实是 08:40 签到失败后自愈 dispatch 的
（run #17/#18 全是 `workflow_dispatch`），schedule 一次都没贡献。
所以 sync 也照签到的办法处理：**主触发器换成青龙 id=229（北京 00:00），
schedule 降级为兜底并同步挪到 00:20**（留着是因为青龙万一挂了还能兜一下，
即便它再迟 6 小时，也大概率赶在 08:40 签到之前；Guard 会挡掉重复）。

而 `workflow_dispatch` 是零延迟的：实测提交 `10:24:35`，run 的 `created_at` 也是
`10:24:35`，45 秒跑完。所以把触发权收回青龙：

| 项 | 值 |
|---|---|
| 青龙任务 | id=**227**，`task gh_dispatch.py` |
| cron | `0 40 8 * * *`（6 段式，精确到秒） |
| 脚本 | `/ql/scripts/gh_dispatch.py`（本地留档 `deploy/gh_dispatch.py`） |
| 环境变量 | `GH_DISPATCH_TOKEN`（GitHub token，需 `repo` / fine-grained 的 `Actions: write`） |
| 幂等 | 先查当天是否已有运行，有就跳过，不会重复签 |
| 告警 | dispatch 失败 / 运行结论非 success / 4 分钟未完成 → PushPlus |

青龙的 `RandomDelay="300"` **只作用于 .js 任务**，`.py` 准点执行，不受影响。

> **2026-11-17 更新：id=227 这个任务已经删了。** 签到整体搬到本机真浏览器后，
> 它没有存在意义（调起来也只会得到 `code=5`）。要恢复 Actions 路线的话：
> 1. GitHub 上把 `custom-checkin.yml` 重新 enable
> 2. 青龙新建任务：`task gh_dispatch.py`，cron `0 40 8 * * *`
> 3. 但**纯 Python 路线在 Turnstile 面前是死的**，恢复它大概率只是恢复一条必失败链路。

### 同一套脚本也接了 sync upstream（id=229，2026-11-16）

就是上面那张表里的 08:10 那一环（2026-11-16 已挪到 **00:00**），改用同一份 `gh_dispatch.py` 逻辑：

| 项 | 值 |
|---|---|
| 青龙任务 | id=**229**，`task gh_dispatch_sync.py` |
| cron | `0 0 0 * * *`（北京 00:00，2026-11-16 从 `0 10 8 * * *` 改过来） |
| 脚本 | `/ql/scripts/gh_dispatch_sync.py`（无参 wrapper，本地留档 `deploy/gh_dispatch_sync.py`） |
| 目标 | `wyq0201/Gladoscheckin` / workflow **409103406**（sync-upstream.yml）/ `master` |
| 幂等 | 当天已有 run（不论脚本跑的还是自愈 dispatch 的）就跳过，与 sync 内部 Guard 语义一致 |

时序：00:00 同步 → 有更新就 merge+push，**签到不跟着触发**（凌晨那个点日签
是否已跨天不确定，万一判成重复签到，08:40 会因为「今天已跑过」而 skip，等于漏签）。
08:40 青龙照常 dispatch 签到，拿到的就是刚同步好的代码。
需要「改完立刻验证」时，手动 Run workflow 并勾 `dispatch_checkin`。

**代价**：上游提交时间不固定（11-16 那批在 00:32~01:51），00:00 这一趟抓不到
当天凌晨才提交的更新，得等下一个 00:00。兜底靠签到异常自愈时 dispatch sync。

### 同一套脚本也接了 52pojie（id=228）

`wyq0201/52pojie_checkIn` 也被同样的方式拖过：cron 是 23:10 UTC（= 北京 07:10），
实测落地 10:23~12:36，等于整个上午都不可控。所以复用同一份逻辑：

| 项 | 值 |
|---|---|
| 青龙任务 | id=**228**，`task gh_dispatch_pojie52.py` |
| cron | `0 10 7 * * *`（北京 07:10） |
| 脚本 | `/ql/scripts/gh_dispatch_pojie52.py`（无参 wrapper，配置写死在文件里） |
| GitHub 侧 | `checkin.yml` 的 schedule 改成 `0 4 * * *`（北京 12:00，兜底） |

**为什么是「无参 wrapper」而不是 `task gh_dispatch.py --repo ...`** ——
青龙的 `task` 会把参数直接喂给内部 `grep`，`--repo` 会得到：

```
grep: unrecognized option: repo
Unrecognized switch: --repo  (-h will show valid options)
```

所以青龙上不能带命令行参数。wrapper 把配置塞进环境变量（`DISPATCH_REPO` 等）
再调 `gh_dispatch.main()`；`gh_dispatch.py` 的 argparse 默认值都从这些环境变量读。

> ⚠️ 青龙容器重建后必须恢复：`gh_dispatch_sync.py`、`gh_dispatch_pojie52.py`
> 回到 `/ql/scripts/`、id=229 / 228 任务还在、`GH_DISPATCH_TOKEN` 还在。
> （`gh_dispatch.py` 和 id=227 已随签到迁走一并删除，容器重建后不用再补。）
> 否则同步退化成只剩 GitHub schedule（等于随机）。

## 一天到底签几次

**现在只有一条路径：本机计划任务 08:40 跑一次。**

| 场景 | 结果 |
|---|---|
| 一切正常 | 签 1 次，`code=0` +N 分，写日志 |
| 今天已经签过 | 先查 `/api/user/points` 命中今天记录 → 直接退出 0，**不点按钮** |
| profile 失效 | 退出码 2，日志提示重跑 `node checkin.mjs --login` |
| Turnstile 没过 | 退出码 1，日志 `code=5` |

不再有推送 —— Actions 那条链路已停，结果只看 `local\logs\checkin-YYYYMMDD.log`。
需要推送就在 `checkin.mjs` 末尾加一个 PushPlus 调用，脚本结构留了位置。

## 自动拉上游的逻辑

```
00:00  青龙 gh_dispatch_sync.py → dispatch sync upstream
         ├─ 今天已同步过？ → 跳过（防"异常→同步→又异常"死循环）
         ├─ 上游领先 0 个提交 → 打印 notice，什么都不做，等明天
         ├─ 上游有新提交 → git merge upstream/master → git push
         │                   └─ 签到不跟着触发（勾了 dispatch_checkin 才触发）
         └─ 合并冲突 → git merge --abort，推送告警，等你人工处理

08:40  本机计划任务 "GLaDOS Checkin" → local/run.bat → checkin.mjs
         ├─ 已登录？否 → 退出码 2，日志提示 --login
         ├─ 今天已签？是 → 直接退出 0（不点按钮）
         └─ 否则点按钮，按响应判 code=0 成功 / code=1 已签 / code=5 Turnstile 未过
```

### ⚠️ 为什么同步要用 SYNC_TOKEN 而不是 GITHUB_TOKEN

2026-11-07/08 连续两天同步失败，报错：

```
! [remote rejected] HEAD -> master
(refusing to allow a GitHub App to create or update workflow
 `.github/workflows/gladosCheck.yml` without `workflows` permission)
```

**不是冲突，是 push 被拒**。原因：上游提交 `bbc0765` 把 `gladosCheck.yml` 的
`name` 从 `auto check` 改成 `GLaDOS Check-in`，而 `GITHUB_TOKEN` 属于 GitHub App，
**没有 `workflows` 权限就不能推送任何 `.github/workflows/**` 的改动**——
这个权限在 `permissions:` 块里也声明不出来，只有 PAT 的 `workflow` scope 可以。

所以 `sync-upstream.yml` 的 checkout 用的是 `secrets.SYNC_TOKEN`
（classic PAT，scope = `repo` + `workflow`），`persist-credentials` 让后续
`git push` 复用它。

**PAT 过期/被吊销时**：同步会失败并推送「GLaDOS 同步上游失败」告警，
届时重新生成一个带 `repo` + `workflow` scope 的 classic PAT，
更新 `SYNC_TOKEN` secret 即可，不用改代码。

## 什么算「异常」

`custom_run.py` 里判定，任一命中即异常：

- 有账号**签到失败**（`code=-2` Cookie 失效、`code=4` 设备不符等）
- 有账号**签到成功但本次积分 < 阈值**（默认 **2**，即只有 1 分报警）

> 为什么要有第二条：GLaDOS 单日签到是**随机分**，实测 2 / 8 / 10 都出现过
> （总积分逐日核对得上，都是真值）。只有 **1 分**才是「被识别为自动签到」的
> 保底分（上游 README 原文：「只给 1 积分 = GLaDOS 判定为自动签到」）。
> 2026-11 加 challenge 校验那次就是 1 分。
>
> 2026-11-12 单日只给 2 分，被旧默认阈值 3 误判成「积分异常」，workflow 标红
> + 触发上游同步 —— 属于阈值定得太高，已下调到 2（1 分才报警）。

**改阈值**：仓库 Settings → Secrets and variables → Actions → **Variables** →
新建 `GLADOS_MIN_POINTS`（例如 `5`）。不配就用默认 2。

## 推送

只配了 PushPlus（`PUSH_PLUS_TOKEN`）。上游还支持 PushDeer / Server酱，
配了也会一起发。PushPlus 对**完全相同的内容**会拒收（`code=999`），
重复签到那几次可能收不到推送，属正常。

## 积分兑换开关

**默认关闭**。要开就在 Secrets 里把 `GLADOS_EXCHANGE_PLAN` 设成
`plan100`（100分→10天）/ `plan200`（200分→30天）/ `plan500`（500分→100天）。
设 `off` / `none` 或不设 = 关闭。改完下次运行生效，不用动代码。

## 排查速查

| 现象 | 先看哪里 |
|---|---|
| 今天没签到 | 本机 `local\logs\checkin-YYYYMMDD.log`（最新一份）；再看计划任务 `GLaDOS Checkin` 上次运行结果 |
| 本机日志报 `code=5` | Turnstile 没过。检查任务是否在「用户已登录」会话里跑、窗口有没有真的渲染出来 |
| 本机日志报「未登录」 | profile 失效，重跑 `node checkin.mjs --login` 登录一次 |
| 本机没有任何日志 | 计划任务没跑：`schtasks /query /tn "GLaDOS Checkin"` 看上次运行时间与返回码 |
| 推送说「签到失败」（旧 Actions 路线） | 日志里 8 个域名是否全 `code=-2` → Cookie 失效，重新登录取新 Cookie |
| 推送说「积分异常」 | 上游可能又加了新校验 → 看 `sync upstream` 是否拉到新代码 |
| job 变红 | 点进去看 `Running checkin` 步骤的日志，异常项会打在最下面 |
| 同步冲突 | 说明上游改了我们也改过的文件（理论上不会发生），需要人工 merge |
| 同步报 `refusing to allow ... without workflows permission` | `SYNC_TOKEN` 失效或没配，重新生成带 `repo`+`workflow` scope 的 PAT 并更新 secret |

**Cookie 失效的标准做法**：浏览器登录 glados.cloud → F12 → Network → 刷新 →
任一请求 → Request Headers → 复制 `Cookie` 和 `User-Agent` → 拼成 JSON 数组塞进
`GLADOS_COOKIES` secret：

```json
[{"name":"主号","origin":"glados.cloud","cookie":"koa:sess=...; koa:sess.sig=...; gld:sess=...; gld:sess.sig=...","user-agent":"Mozilla/5.0 (...) ..."}]
```
