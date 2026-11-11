# -*- coding: utf-8 -*-
"""精确触发 GLaDOS 签到 —— 部署在青龙面板，替代 GitHub 自带的 schedule。

为什么要这个
------------
GitHub Actions 的 `schedule` 在这个仓库上已经不可用了。实测（北京时间）：

    应触发 08:40  →  11-07 14:35 · 11-08 14:41 · 11-09 15:10 · 11-10 15:43

延迟 5h55m 起步，而且**每天还往后漂半小时**。同仓库的 watchdog
（`0 3-14 * * *`，本该 12 次/天）11-10 全天只跑了 1 次，18:29 UTC 才落地 ——
延迟已经跨出 cron 区间 4.5 小时。结论：这个仓库的 schedule 被 GitHub 降级了，
低频 cron 能中但时间不可控，高频 cron 直接被丢弃。

`workflow_dispatch` 则是零延迟的：实测提交 10:24:35，run 的 created_at 也是
10:24:35，45 秒跑完。所以改由青龙精确 dispatch，把触发权拿回来。

青龙侧不受 RandomDelay 影响
--------------------------
`config.sh` 里 `RandomDelay="300"` 只作用于 **.js** 任务（青龙按后缀判断），
本脚本是 .py，准点执行。cron 用 6 段式，可精确到秒：`0 40 8 * * *`。

依赖的环境变量
--------------
    GH_DISPATCH_TOKEN   GitHub PAT（classic，scope 至少含 repo；fine-grained 需 Actions: write）
    PUSH_PLUS_TOKEN     可选，异常时告警用

退出码
------
    0  今天已签 / 本次触发成功
    1  触发失败或结果异常（已推送告警）
"""

import datetime
import os
import sys
import time

import requests

REPO = "wyq0201/Gladoscheckin"
WORKFLOW_ID = 409103405          # custom-checkin.yml = glados checkin
BRANCH = "master"
TZ_OFFSET = datetime.timezone(datetime.timedelta(hours=8))

API = "https://api.github.com"
PUSHPLUS_URL = "https://www.pushplus.plus/send"

TOKEN = (os.environ.get("GH_DISPATCH_TOKEN") or "").strip()
PUSH_TOKEN = (os.environ.get("PUSH_PLUS_TOKEN") or "").strip()

# dispatch 后等结果：正常运行 45~90 秒，给足 4 分钟
WAIT_SECONDS = int((os.environ.get("GH_DISPATCH_WAIT") or "240").strip() or 240)
POLL_INTERVAL = 15


def log(msg: str) -> None:
    print(msg, flush=True)


def push(title: str, content: str) -> None:
    if not PUSH_TOKEN:
        log("[warn] 没配 PUSH_PLUS_TOKEN，跳过告警推送")
        return
    try:
        r = requests.post(
            PUSHPLUS_URL,
            json={
                "token": PUSH_TOKEN,
                "title": " ".join(title.split()),   # 标题不能带换行，否则拒收
                "content": content,
                "template": "txt",
            },
            timeout=15,
        )
        log(f"[push] HTTP {r.status_code}")
    except Exception as e:                          # noqa: BLE001
        log(f"[push] 失败: {e!r}")


def gh(method: str, path: str, **kw):
    headers = {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "ql-glados-dispatch",
    }
    return requests.request(method, API + path, headers=headers, timeout=25, **kw)


def beijing(dt_str: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(TZ_OFFSET)


def today_runs():
    """今天（北京时间）的所有运行，按创建时间倒序。"""
    r = gh("GET", f"/repos/{REPO}/actions/workflows/{WORKFLOW_ID}/runs?per_page=30")
    if r.status_code != 200:
        log(f"[warn] 拉运行记录失败 HTTP {r.status_code}: {r.text[:200]}")
        return None
    today = datetime.datetime.now(TZ_OFFSET).strftime("%Y-%m-%d")
    out = []
    for run in r.json().get("workflow_runs", []):
        try:
            if beijing(run["created_at"]).strftime("%Y-%m-%d") == today:
                out.append(run)
        except Exception:                            # noqa: BLE001
            continue
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return out


def main() -> int:
    if not TOKEN:
        log("[error] 缺 GH_DISPATCH_TOKEN，无法触发")
        push("⚠️ GLaDOS 触发失败", "青龙任务缺 GH_DISPATCH_TOKEN，今天没有触发签到。")
        return 1

    runs = today_runs()
    if runs is None:
        # 拿不到记录不代表已签，继续尝试触发（dispatch 本身是幂等无害的）
        log("[warn] 无法确认今日状态，仍然触发一次")
    elif runs:
        done = [r for r in runs if r.get("status") == "completed"]
        pending = [r for r in runs if r.get("status") != "completed"]
        if pending:
            log(f"[skip] 今天已有 {len(pending)} 个运行在排队/执行中，不重复触发")
            return 0
        if done:
            latest = done[0]
            log(f"[skip] 今天已跑过 {len(done)} 次"
                f"（最新 {beijing(latest['created_at']).strftime('%H:%M')} "
                f"{latest.get('conclusion')}），不重复触发")
            return 0

    log(f"[dispatch] {datetime.datetime.now(TZ_OFFSET).strftime('%H:%M:%S')} 触发 {REPO} / {WORKFLOW_ID}")
    r = gh("POST", f"/repos/{REPO}/actions/workflows/{WORKFLOW_ID}/dispatches",
           json={"ref": BRANCH})
    if r.status_code not in (201, 204):
        log(f"[error] dispatch 失败 HTTP {r.status_code}: {r.text[:300]}")
        push("⚠️ GLaDOS 触发失败",
             f"dispatch 返回 HTTP {r.status_code}\n\n{r.text[:300]}\n\n今天可能没签到，需要人工确认。")
        return 1
    log("[dispatch] 已提交（204）")

    # 等结果：dispatch 正常运行 45~90 秒
    deadline = time.time() + WAIT_SECONDS
    last = None
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        runs = today_runs()
        if not runs:
            continue
        latest = runs[0]
        last = latest
        if latest.get("status") != "completed":
            log(f"[wait] 运行中… {latest.get('status')}")
            continue
        concl = latest.get("conclusion")
        mins = ""
        if latest.get("run_started_at") and latest.get("updated_at"):
            try:
                dur = (datetime.datetime.fromisoformat(latest["updated_at"].replace("Z", "+00:00"))
                       - datetime.datetime.fromisoformat(latest["run_started_at"].replace("Z", "+00:00")))
                mins = f"，耗时 {int(dur.total_seconds())} 秒"
            except Exception:                        # noqa: BLE001
                pass
        if concl == "success":
            log(f"[ok] 签到运行成功{mins}")
            return 0
        log(f"[error] 运行结论 {concl}")
        push("⚠️ GLaDOS 签到失败",
             f"10 分钟内运行结论：{concl}\n\n"
             f"回报：https://github.com/{REPO}/actions/runs/{latest['id']}")
        return 1

    log(f"[warn] 等了 {WAIT_SECONDS} 秒还没结束，交给 watchdog / 汇总脚本兜底")
    if last:
        push("⚠️ GLaDOS 签到未按时完成",
             f"dispatch 后 {WAIT_SECONDS} 秒仍未完成（状态 {last.get('status')}）。\n\n"
             f"回报：https://github.com/{REPO}/actions/runs/{last['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
