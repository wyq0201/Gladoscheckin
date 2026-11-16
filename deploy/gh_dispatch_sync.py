# -*- coding: utf-8 -*-
"""青龙任务入口：触发 sync upstream（拉上游代码），替代 GitHub 自带的 schedule。

为什么需要这个
--------------
`sync-upstream.yml` 上挂的 `cron: '10 8 * * *'`（北京 08:10）被 GitHub 的定时
调度器严重降级。实测落地时间（北京时间，用 API 拉的 `created_at`）：

    应 08:10  →  11-12 15:01 · 11-13 14:30 · 11-14 14:08 · 11-15 14:16
    11-16     →  完全没有 scheduled run（这次 cron 被直接丢弃）

也就是说迟 6 小时起、且不稳定。11-16 那天上游 v1.0.1 能被合进来，实际是
08:40 签到失败后自愈 dispatch 的（run #17/#18 都是 workflow_dispatch），
不是 schedule 干的活。

`workflow_dispatch` 走的是 webhook，实测秒级创建、十几秒跑完，所以把触发权
收回青龙，和签到（id=227）用同一套办法。

部署
----
青龙 → 脚本管理 → `/ql/scripts/gh_dispatch_sync.py`（和 `gh_dispatch.py` 同级）
青龙 → 定时任务 → `task gh_dispatch_sync.py`，cron `0 10 8 * * *`（北京 08:10）

为什么还是 08:10
----------------
和原 cron 保持同一时点：先同步、后签到（08:40）。上游有新提交时 sync 会
merge+push 并立刻 dispatch 一次签到，等于「改完立即用新代码验证」；
上游没更新就空转，签到仍走 08:40。
"""

import os
import sys

os.environ["DISPATCH_REPO"] = "wyq0201/Gladoscheckin"
os.environ["DISPATCH_WF"] = "409103406"     # .github/workflows/sync-upstream.yml
os.environ["DISPATCH_BRANCH"] = "master"
os.environ["DISPATCH_NAME"] = "GLaDOS-sync"
os.environ["DISPATCH_WAIT"] = "180"         # 含 git merge + push，比签到略放宽

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gh_dispatch                            # noqa: E402

if __name__ == "__main__":
    sys.exit(gh_dispatch.main())
