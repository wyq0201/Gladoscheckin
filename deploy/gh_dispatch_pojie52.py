# -*- coding: utf-8 -*-
"""青龙任务入口：触发 52pojie（吾爱破解）签到。

为什么要单独一个文件而不是 `task gh_dispatch.py --repo xxx`
----------------------------------------------------------
青龙的 `task` 命令是把参数直接喂给内部 `grep` 的，传 `--repo` 会得到：

    grep: unrecognized option: repo
    Unrecognized switch: --repo

所以青龙上不能带命令行参数。这里用无参 wrapper 把配置塞进环境变量，
再调公共逻辑 `gh_dispatch.main()`。

部署
----
青龙 → 脚本管理 → `/ql/scripts/gh_dispatch_pojie52.py`（和 `gh_dispatch.py` 同级）
青龙 → 定时任务 → `task gh_dispatch_pojie52.py`，cron `0 10 7 * * *`（北京 07:10）

为什么是 07:10
--------------
原 GitHub cron 就是 23:10 UTC（= 北京 07:10），但实测 schedule 落地被拖到
10:23~12:36，跨掉了整个上午。52pojie 的日签到在北京时间凌晨刷新，早上越早签完
越不容易撞上白天的风控，所以维持 07:10 不变，只把触发权从 GitHub 收回青龙。
"""

import os
import sys

os.environ["DISPATCH_REPO"] = "wyq0201/52pojie_checkIn"
os.environ["DISPATCH_WF"] = "404205158"     # .github/workflows/checkin.yml
os.environ["DISPATCH_BRANCH"] = "main"
os.environ["DISPATCH_NAME"] = "吾爱破解"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gh_dispatch                            # noqa: E402

if __name__ == "__main__":
    sys.exit(gh_dispatch.main())
