# Glados自动签到

## 食用方式：

### 注册一个GLaDOS的账号([注册地址](https://glados.space/landing/0A58E-NV28S-6U3QV-33VMG))

#### 我的邀请码：([0A58E-NV28S-6U3QV-33VMG](https://0a58e-nv28s-6u3qv-33vmg.glados.space)) 

### **Fork**本仓库

![图片加载失败](imgs/1.png)

### 添加**secret**

1. 跳转至自己的仓库的`Settings`->`Secrets and variables`->`Action`

2. 添加1个`repository secret`，命名为`GLADOS_COOKIES`，其值对应GLaDOS账号的cookie值中的有效部分（获取方式如下）

- 在GLaDOS的签到页面按`F12`

- 切换到`Network`页面下，刷新

![图片加载失败](imgs/2.png)

- 点击第一个选项卡后在`Request Headers`下找到`Cookie`，右键复制cookie的值即可

  > 参考格式：koa:sess=eyJ1c2xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxAwMH0=; koa:sess.sig=xJkOxxxxxxxxxxxxxxxtnM;

![图片加载失败](imgs/3.png)

- 多账号请在 `COOKIES` 中 添加多个 `cookies` 中间使用 `&`连接即可。（例如： `c1&c3&c3...`）

3. 配置积分兑换策略（非必须）

- 添加1个`repository secret`，命名为`GLADOS_EXCHANGE_PLAN`，配置自动兑换积分策略：

| 值 | 积分要求 | 兑换天数 |
|---|---------|---------|
| `plan100` | 100 积分 | 10 天 |
| `plan200` | 200 积分 | 30 天 |
| `plan500` | 500 积分 | 100 天 |

> **默认关闭自动兑换**：不配置 `GLADOS_EXCHANGE_PLAN`（或设为 `off` / `none`）时，
> 脚本只签到、不消耗积分。积分本身不会因为不兑换而消失，攒着等需要的时候再开。

### 积分兑换开关（怎么开 / 怎么关）

改动**只需在 GitHub 网页上点几下，不用动代码**，下一次运行即刻生效。

**关掉自动兑换**（只签到、攒积分不花）

1. 打开 <https://github.com/wyq0201/Gladoscheckin/settings/secrets/actions>
2. 若列表里已有 `GLADOS_EXCHANGE_PLAN`，点它 → **Remove secret**
3. 如果只是想留着占位，也可以把值改成 `off`（或 `none` / `false` / `0` / `disable`），效果一样

**打开自动兑换**

1. 同一个页面点 **New repository secret**
2. Name 填 `GLADOS_EXCHANGE_PLAN`，Secret 填目标档位：

| 值 | 消耗积分 | 兑换天数 | 每 100 分换到 |
|---|---------|---------|--------------|
| `plan100` | 100 积分 | 10 天 | 10 天 |
| `plan200` | 200 积分 | 30 天 | 15 天 |
| `plan500` | 500 积分 | 100 天 | **20 天（最划算）** |

3. 保存即可。之后每次签到后脚本会检查积分，够 `planXXX` 要求的分数就自动兑换一次
   （不够则静默跳过，不会浪费积分）
4. 想看是否生效：下次 Actions 日志里会出现
   `当前 GLADOS_EXCHANGE_PLAN: plan500` 或 `当前 GLADOS_EXCHANGE_PLAN: 关闭（不自动兑换）`

> 配错的值（例如 `plan999`）会被判为无效 → **自动关闭兑换 + 记一条警告**，
> 不会像旧版那样静默回落到 `plan500` 把你的积分花掉。

4. 手机推送（非必须）

- 添加1个`repository secret`，命名为`PUSHDEER_SENDKEY`，其值对应 PushDeer key: ([获取地址](https://www.pushdeer.com/product.html))。

### **star**自己的仓库

![图片加载失败](imgs/4.png)

## 文件结构

```shell
│  checkin.py	# 签到脚本
│
├─.github
│  └─workflows
│          gladosCheck.yml	# Actions 配置文件
```

## 更新日志

- **2026-01**: 重构代码，添加log输出方便定位，支持新版网址，支持配置积分兑换策略。


## 问题排查与定位
- 大家可以通过查询 actions 中的 running checkin 日志快速定位问题，有其他问题提交issue。

  <img width="1684" height="844" alt="image" src="https://github.com/user-attachments/assets/45348a5f-43e4-45f5-8fdf-ce84d343b30d" />

## 日常运维速查（本仓库定制）

| 想做的事 | 怎么做 |
|---|---|
| 看今天有没有签到 | Actions → `auto check`，看最新一条 run 的日志 |
| 立刻手动签到一次 | Actions → `auto check` → **Run workflow** → master |
| 改签到时间 | 编辑 `.github/workflows/gladosCheck.yml` 的 `cron`（UTC，北京时间 = UTC+8） |
| 开关积分自动兑换 | 见上文「积分兑换开关」，只改 Secret，不改代码 |
| 看有没有漏跑 | Actions → `glados watchdog`，会在主任务没跑成时自动兜底触发 |

时间与兜底机制：

- 主任务 `auto check` cron `40 0 * * *`（UTC）= **北京 08:40**
- 看门狗 `glados watchdog` cron `0 3-14 * * *`（UTC）= **北京 11:00–22:00 每小时**，
  只在当天没有签到成功记录时才兜底触发主任务，平时完全静默
- GitHub 的 `schedule` 是 best-effort，**实测延迟 0.5–2 小时**，
  所以 08:40 发起、实际落地常到 09:00–10:40，别看到点没推送就以为坏了
- **改动 cron 后，当天原时段的触发就失效了**，记得手动 Run workflow 补一次

## 声明

本项目不保证稳定运行与更新, 因GitHub相关规定可能会删库, 请注意备份







