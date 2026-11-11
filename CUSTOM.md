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

## 四个 workflow 的分工

| workflow | 文件 | 触发 | 干什么 |
|---|---|---|---|
| **glados checkin** | `custom-checkin.yml` | **青龙面板 08:40** dispatch、手动 | 跑 `custom_run.py` 签到 + PushPlus 推送 |
| **sync upstream** | `sync-upstream.yml` | 每天北京 **08:10**、手动、被上一条调用 | 拉上游；有更新就 merge+push 并触发一次签到，没更新就空转等明天 |
| **glados watchdog** | `watchdog.yml` | 北京 **16:00 / 19:00** | 只在「今天压根没跑」时兜底触发签到 |
| ~~GLaDOS Check-in~~ | `gladosCheck.yml` | — | 上游自带，**已手动 disable**，避免重复签到 |

> ⚠️ `custom-checkin.yml` **刻意不挂 `on: push`**。
> 否则每次改代码都会签一次，白白产生一堆「重复签到」的空跑。
> 需要验证新代码时：sync 合并后会自己 dispatch，或者手动 Run workflow。

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

> ⚠️ 青龙容器重建后必须恢复：`gh_dispatch.py` 和 `gh_dispatch_pojie52.py` 回到
> `/ql/scripts/`、id=227/228 任务还在、`GH_DISPATCH_TOKEN` 还在。
> 否则签到退化成只剩 GitHub 侧那两次兜底。

## 一天到底签几次、推几条

**正常情况：签 1 次、推 1 条**（青龙 08:40 dispatch 那次）。

| 场景 | 签到次数 | 推送条数 |
|---|---|---|
| 一切正常 | 1（青龙 08:40 dispatch） | 1（签到成功） |
| 青龙没触发（容器挂了/任务被删） | 1（16:00 或 19:00 watchdog 补） | 1 + 青龙侧告警 |
| 上游有更新 | 1–2（08:10 sync 合并后签一次；08:40 若再跑就是重复签到） | 1（重复那次静默） |
| 签到失败 / 积分异常 | 1–3（异常会再拉上游重试一次） | 1 + 1 条异常告警 |
| 手动点 Run workflow（当天已签） | 多一次空跑 | **0**（重复签到不推） |

**三条去噪规则**：

1. **全部「重复签到」不推送** —— 今天早签过了，再推没有新信息
2. **watchdog 只在 16:00–23:00 兜底，一天两次** —— 早先铺了 11:00–22:00 每小时（12 次），
   但 GitHub 对这些高频档丢得厉害（11-10 只落 1 次，还落在 18:29 UTC），
   铺宽没换来命中率，只把可能重复签到的时间段拉长了
3. **push 不触发签到** —— 见上方说明

## 自动拉上游的逻辑

```
08:10  sync upstream
         ├─ 今天已同步过？ → 跳过（防"异常→同步→又异常"死循环）
         ├─ 上游领先 0 个提交 → 打印 notice，什么都不做，等明天
         ├─ 上游有新提交 → git merge upstream/master → git push
         │                   └─ push 触发 glados checkin 立刻签到一次
         └─ 合并冲突 → git merge --abort，推送告警，等你人工处理

08:40  青龙 gh_dispatch.py → dispatch glados checkin
         ├─ 今天已跑过 → 直接跳过（幂等）
         ├─ 正常 → 退出码 0，推送报告
         └─ 异常 → 退出码 1（job 变红）+ 告警推送 + 自动触发 sync upstream
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
- 有账号**签到成功但本次积分 < 阈值**（默认 **3**）

> 为什么要有第二条：GLaDOS 正常给 5~20 分。2026-11 那次只给 1 分，
> 就是服务端加了 challenge 校验、上游没适配 —— 但脚本仍报「签到成功」，
> 光看颜色根本发现不了。

**改阈值**：仓库 Settings → Secrets and variables → Actions → **Variables** →
新建 `GLADOS_MIN_POINTS`（例如 `5`）。不配就用默认 3。

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
| 今天没收到推送 | 青龙 id=227 的日志（有没有 dispatch 成功）；再查 Actions → `glados checkin`；最后看 watchdog 16:00/19:00 |
| 推送说「签到失败」 | 日志里 8 个域名是否全 `code=-2` → Cookie 失效，重新登录取新 Cookie |
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
