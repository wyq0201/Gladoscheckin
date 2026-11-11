# -*- coding: utf-8 -*-
"""精确触发 GitHub Actions 签到 —— 部署在青龙面板，替代 GitHub 自带的 schedule。

为什么要有这个
--------------
GitHub Actions 的 `schedule` 在这两个仓库上都已经不可用。实测（北京时间）：

    GLaDOS（应 08:40）→ 11-07 14:35 · 11-08 14:41 · 11-09 15:10 · 11-10 15:43
                         起步迟 5h55m，且每天再往后漂半小时
    52pojie（应 07:10）→ 11-03 11:54 · 11-04 10:59 · 11-05 11:27 · 11-06 11:23
                         11-07 10:44 · 11-08 10:23 · 11-09 10:37 · 11-10 12:36

同期的 watchdog（`0 3-14`，本该 12 次/天）11-10 只落了 1 次，18:29 UTC 才跑 ——
比 cron 区间末尾还晚 4.5 小时。规律：**低频档能中但时间不可控，高频档直接被丢**。

而 `workflow_dispatch` 是零延迟的：实测提交 10:24:35，run 的 `created_at` 也是
10:24:35，45 秒跑完。所以把触发权从 GitHub 手里收回来。

青龙侧不受 RandomDelay 影响
--------------------------
`config.sh` 里 `RandomDelay="300"` 只作用于 **.js** 任务（青龙按后缀判断），
本脚本是 .py，准点执行。cron 用 6 段式，可精确到秒。

用法
----
    # GLaDOS（默认值）
    task gh_dispatch.py

    # 52pojie
    task gh_dispatch.py --repo wyq0201/52pojie_checkIn --wf 404205158 \
        --branch main --name 吾爱破解

参数
----
    --repo      owner/name
    --wf        workflow 的数字 id（不是文件名）
    --branch    目标分支，默认 master
    --name      日志/告警里显示的名字，默认 GLaDOS
    --wait      dispatch 后等结果的最大秒数，默认 240

依赖的环境变量
--------------
    GH_DISPATCH_TOKEN   GitHub PAT（classic 需 repo；fine-grained 需 Actions: write）
    PUSH_PLUS_TOKEN     可选，异常时告警用

退出码
------
    0  今天已签 / 本次触发成功
    1  触发失败或结果异常（已推送告警）
"""

import argparse
import datetime
import os
import sys
import time

import requests

TZ_OFFSET = datetime.timezone(datetime.timedelta(hours=8))

API = "https://api.github.com"
PUSHPLUS_URL = "https://www.pushplus.plus/send"
POLL_INTERVAL = 15

TOKEN = (os.environ.get("GH_DISPATCH_TOKEN") or "").strip()
PUSH_TOKEN = (os.environ.get("PUSH_PLUS_TOKEN") or "").strip()


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
        "User-Agent": "ql-gh-dispatch",
    }
    return requests.request(method, API + path, headers=headers, timeout=25, **kw)


def beijing(dt_str: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(TZ_OFFSET)


def today_runs(repo: str, wf: int, ):
    """今天（北京时间）该 workflow 的所有运行，按创建时间倒序。拿不到返回 None。"""
    r = gh("GET", f"/repos/{repo}/actions/workflows/{wf}/runs?per_page=30")
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


def describe(run: dict) -> str:
    when = beijing(run["created_at"]).strftime("%H:%M")
    dur = ""
    if run.get("run_started_at") and run.get("updated_at"):
        try:
            a = datetime.datetime.fromisoformat(run["run_started_at"].replace("Z", "+00:00"))
            b = datetime.datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00"))
            dur = f"，{int((b - a).total_seconds())} 秒"
        except Exception:                            # noqa: BLE001
            pass
    return f"{when} {run.get('conclusion')}{dur}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="wyq0201/Gladoscheckin")
    ap.add_argument("--wf", type=int, default=409103405)
    ap.add_argument("--branch", default="master")
    ap.add_argument("--name", default="GLaDOS")
    ap.add_argument("--wait", type=int, default=240)
    args = ap.parse_args()

    name, repo, wf = args.name, args.repo, args.wf
    log(f"=== {name} ({repo} / {wf}) === 北京时间 "
        f"{datetime.datetime.now(TZ_OFFSET).strftime('%Y-%m-%d %H:%M:%S')}")

    if not TOKEN:
        log("[error] 缺 GH_DISPATCH_TOKEN，无法触发")
        push(f"⚠️ {name} 触发失败", "青龙任务缺 GH_DISPATCH_TOKEN，今天没有触发签到。")
        return 1

    runs = today_runs(repo, wf)
    if runs is None:
        # 拿不到记录不代表已签，继续尝试触发（dispatch 本身幂等无害）
        log("[warn] 无法确认今日状态，仍然触发一次")
    elif runs:
        pending = [r for r in runs if r.get("status") != "completed"]
        if pending:
            log(f"[skip] 今天已有 {len(pending)} 个运行在排队/执行中，不重复触发")
            return 0
        done = [r for r in runs if r.get("status") == "completed"]
        if done:
            log(f"[skip] 今天已跑过 {len(done)} 次（最新 {describe(done[0])}），不重复触发")
            return 0

    log(f"[dispatch] 触发 {repo} / {wf} @ {args.branch}")
    r = gh("POST", f"/repos/{repo}/actions/workflows/{wf}/dispatches",
           json={"ref": args.branch})
    if r.status_code not in (201, 204):
        log(f"[error] dispatch 失败 HTTP {r.status_code}: {r.text[:300]}")
        push(f"⚠️ {name} 触发失败",
             f"dispatch 返回 HTTP {r.status_code}\n\n{r.text[:300]}\n\n今天可能没签到，需要人工确认。")
        return 1
    log("[dispatch] 已提交（204）")

    # 等结果：dispatch 正常运行 45~90 秒
    deadline = time.time() + args.wait
    last = None
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        runs = today_runs(repo, wf)
        if not runs:
            continue
        last = runs[0]
        if last.get("status") != "completed":
            log(f"[wait] 运行中… {last.get('status')}")
            continue
        concl = last.get("conclusion")
        if concl == "success":
            log(f"[ok] 运行成功（{describe(last)}）")
            return 0
        log(f"[error] 运行结论 {concl}（{describe(last)}）")
        push(f"⚠️ {name} 签到失败",
             f"运行结论：{concl}\n\n"
             f"回报：https://github.com/{repo}/actions/runs/{last['id']}")
        return 1

    log(f"[warn] 等了 {args.wait} 秒还没结束，交给汇总脚本兜底")
    if last:
        push(f"⚠️ {name} 签到未按时完成",
             f"dispatch 后 {args.wait} 秒仍未完成（状态 {last.get('status')}）。\n\n"
             f"回报：https://github.com/{repo}/actions/runs/{last['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
