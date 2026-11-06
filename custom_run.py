#!/usr/bin/env python3
"""GLaDOS 签到 —— 本地定制包装层

为什么单独一个文件
------------------
上游 `Devilstore/Glados-Railgun-checkin` 更新很频繁。如果把 PushPlus 推送、
失败/异常退出码这些定制直接写进 `checkin.py`，每次同步上游都会冲突，
要人工解一遍。所以这里**一行都不改上游**，全部用运行期注入：

    checkin.PushService        ← 换成带 PushPlus 的版本
    checkin.CheckinRunner.run  ← 包一层，把签到结果抓出来做异常判定

于是 `git merge upstream/master` 永远干净。定制只活在本文件 + 几个自己的 workflow 里。

用法
----
    python custom_run.py          # workflow 里跑这个，不要直接跑 checkin.py

退出码
------
    0  正常（签到成功 / 重复签到，且积分正常）
    1  上游脚本自身报错（配置错、异常），或本次判定为异常
    2  预留（当前不单独使用，异常统一走 1，便于 workflow 统一处理）

异常判定（任一命中即视为异常，退出码 1 + 额外告警推送）
------------------------------------------------------
    * 有账号签到失败（CheckinStatus.FAILURE）
    * 有账号签到成功但本次积分 < GLADOS_MIN_POINTS（默认 3）
      —— GLaDOS 正常给 5~20 分，只给 1 分通常意味着服务端加了新的校验
         （例如 2026-11 的 challenge 校验），上游没适配就会一直吃保底分
"""
import os
import sys
from typing import List, Optional

import requests

import checkin
from checkin import LogEmoji, logger

DEFAULT_MIN_POINTS = 3
PUSHPLUS_URL = "https://www.pushplus.plus/send"


def _min_points() -> int:
    raw = (os.environ.get("GLADOS_MIN_POINTS") or "").strip()
    if not raw:
        return DEFAULT_MIN_POINTS
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"{LogEmoji.WARNING} GLADOS_MIN_POINTS='{raw}' 不是整数，用默认 {DEFAULT_MIN_POINTS}")
        return DEFAULT_MIN_POINTS


class PushPlusBackend(checkin.PushBackend):
    """PushPlus（pushplus.plus）后端 —— 纯 HTTP，不额外引依赖"""

    name = "PushPlus"

    def __init__(self, token: str):
        self.token = token

    def send(self, report) -> bool:
        # PushPlus 的 title 不能带换行，否则接口拒收
        title = " ".join(str(report.title).split()) or "GLaDOS 签到通知"
        payload = {
            "token": self.token,
            "title": title,
            "content": self._render(report),
            "template": "txt",
        }
        try:
            resp = requests.post(PUSHPLUS_URL, json=payload, timeout=15)
            if resp.status_code != 200:
                logger.error(f"{LogEmoji.ERROR} [{self.name}] 推送失败: HTTP {resp.status_code} {resp.text[:200]}")
                return False
            try:
                data = resp.json()
            except ValueError:
                logger.error(f"{LogEmoji.ERROR} [{self.name}] 推送失败: 响应非 JSON {resp.text[:200]}")
                return False
            if data.get("code") == 200:
                logger.info(f"{LogEmoji.SUCCESS} [{self.name}] 推送成功")
                return True
            logger.error(f"{LogEmoji.ERROR} [{self.name}] 推送失败: {data}")
            return False
        except Exception as e:  # noqa: BLE001 - 推送失败不应影响主流程
            logger.error(f"{LogEmoji.ERROR} [{self.name}] 推送失败: {e}")
            return False


class CustomPushService(checkin.PushService):
    """保留上游的 PushDeer / Server酱，额外挂上 PushPlus"""

    def __init__(self, config=None):
        super().__init__(config)
        token = (os.environ.get("PUSH_PLUS_TOKEN") or "").strip()
        if token:
            self.backends.append(PushPlusBackend(token))


class _Alert:
    """给 PushPlusBackend 用的最小报告对象（只发简短告警，不重发整份报告）"""

    def __init__(self, title: str, content: str):
        self.title = title
        self._content = content

    def render(self, line_sep: str = "\n") -> str:
        return self._content


def find_problems(report, min_points: int) -> List[str]:
    problems: List[str] = []
    for entry in report.entries:
        result = entry.result
        label = f"#{entry.index} {entry.name or ''}".strip()
        if result.code is checkin.CheckinStatus.FAILURE:
            hints = f"（{result.note}）" if result.note else ""
            problems.append(f"{label} 签到失败{hints} 域名={result.domain}")
        elif result.code is checkin.CheckinStatus.SUCCESS and result.points < min_points:
            problems.append(
                f"{label} 积分异常：本次仅 {result.points} 分（阈值 {min_points}），"
                f"总 {result.points_total} 分 · 域名={result.domain}"
            )
    return problems


def main() -> int:
    # ---- 注入定制 ---- #
    checkin.PushService = CustomPushService

    captured = {}
    original_run = checkin.CheckinRunner.run

    def run_and_capture(self, budget=None):
        report = original_run(self, budget)
        captured["report"] = report
        return report

    checkin.CheckinRunner.run = run_and_capture

    # ---- 跑上游主流程（它自己会渲染报告 + 推送） ---- #
    base_code = 0
    try:
        checkin.main()
    except SystemExit as e:
        base_code = e.code if isinstance(e.code, int) else (1 if e.code else 0)

    report = captured.get("report")
    if report is None:
        # 配置阶段就挂了（没有账号），上游已 exit 1
        logger.error(f"{LogEmoji.ERROR} 未拿到签到结果，按上游退出码 {base_code or 1} 结束")
        return base_code or 1

    # ---- 异常判定 ---- #
    min_points = _min_points()
    problems = find_problems(report, min_points)

    if not problems:
        logger.info(f"{LogEmoji.SUCCESS} 本次签到结果正常（阈值 {min_points} 分），无需拉取上游")
        return base_code

    logger.error(f"{LogEmoji.ERROR} 检测到 {len(problems)} 项异常，判定为需要检查上游：")
    for p in problems:
        logger.error(f"{LogEmoji.ERROR}   · {p}")

    token = (os.environ.get("PUSH_PLUS_TOKEN") or "").strip()
    if token:
        alert = _Alert(
            "⚠️ GLaDOS 签到异常",
            "本次判定为异常，已触发上游代码同步（若上游无更新则等明天再检查）：\n"
            + "\n".join(f"· {p}" for p in problems),
        )
        PushPlusBackend(token).send(alert)

    return 1


if __name__ == "__main__":
    sys.exit(main())
