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
| **glados checkin** | `custom-checkin.yml` | 每天北京 **08:40**、push、手动 | 跑 `custom_run.py` 签到 + PushPlus 推送 |
| **sync upstream** | `sync-upstream.yml` | 每天北京 **08:10**、手动、被上一条调用 | 拉上游；有更新就 merge+push，没更新就空转等明天 |
| **glados watchdog** | `watchdog.yml` | 北京 11:00–22:00 每小时 | 只在「今天压根没跑」时兜底触发签到 |
| ~~auto check~~ | `gladosCheck.yml` | — | 上游自带，**已手动 disable**，避免重复签到 |

## 自动拉上游的逻辑

```
08:10  sync upstream
         ├─ 今天已同步过？ → 跳过（防"异常→同步→又异常"死循环）
         ├─ 上游领先 0 个提交 → 打印 notice，什么都不做，等明天
         ├─ 上游有新提交 → git merge upstream/master → git push
         │                   └─ push 触发 glados checkin 立刻签到一次
         └─ 合并冲突 → git merge --abort，推送告警，等你人工处理

08:40  glados checkin
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
| 今天没收到推送 | Actions → `glados checkin` 有没有跑；没跑就等 watchdog 11:00 起兜底 |
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
