import requests
import json
import os
import logging
import sys
import datetime
from typing import Dict, List, Optional, Tuple

def beijing_time_converter(timestamp):
    utc_dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
    beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
    beijing_dt = utc_dt.astimezone(beijing_tz)
    return beijing_dt.timetuple()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

root_logger = logging.getLogger()
for handler in root_logger.handlers:
    if hasattr(handler, 'formatter') and handler.formatter is not None:
        handler.formatter.converter = beijing_time_converter

logger = logging.getLogger(__name__)

# ENVIRONMENT
ENV_PUSH_KEY = "PUSH_PLUS_TOKEN"
ENV_COOKIES = "GLADOS_COOKIES"
ENV_EXCHANGE_PLAN = "GLADOS_EXCHANGE_PLAN"
# 可选：手动指定起始 UA。不配就走下面的默认 + 设备自适应
ENV_USER_AGENT = "GLADOS_USER_AGENT"

# API URLs
CHECKIN_URL = "https://glados.cloud/api/user/checkin"
STATUS_URL = "https://glados.cloud/api/user/status"
POINTS_URL = "https://glados.cloud/api/user/points"
EXCHANGE_URL = "https://glados.cloud/api/user/exchange"

# POST DATA
CHECKIN_DATA = {"token": "glados.cloud"}

# ---------------------------------------------------------------------------
# 设备平台 UA 表
#   GLaDOS 从 2026-09 起会校验「签到请求声明的平台」与「账号登录设备的平台」是否一致，
#   对不上就返回 code 4 / reason=device-mismatch（Automated check-in detected），
#   表现为一直签到失败，但积分接口照常返回，很容易误判成 Cookie 坏了。
#   服务端会在响应里给出 loginDevice，照着切一次对应平台的 UA 就能恢复。
# ---------------------------------------------------------------------------
PLATFORM_UA = {
    "Windows": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "macOS": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Linux": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "iPhone": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Android": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
}
# 起始 UA：优先用 GLADOS_USER_AGENT（填你登录那个浏览器的 navigator.userAgent），
# 没配则用 Windows，随后靠上面的设备自适应自动纠正。
DEFAULT_UA = (os.environ.get(ENV_USER_AGENT) or "").strip() or PLATFORM_UA["Windows"]

# 本次运行里学到「哪个平台的 UA 能用」，同一次运行内后续请求复用它
_device_ua_cache: Dict[str, str] = {}

# 签到状态码（以服务端为准，不要靠匹配 message 文本）
CODE_SUCCESS = 0     # 签到成功
CODE_REPEAT = 1      # 今日已签到
CODE_DEVICE = 4      # 被判定为自动签到（设备平台不一致）
CODE_AUTH = -2       # Cookie 无效/过期


def build_headers(user_agent: str) -> Dict[str, str]:
    """构造请求头。

    注意：这里**故意不发 referer**。glados.cloud/console 页面带
    <meta name="referrer" content="no-referrer">，真实浏览器点「签到」时不会带 Referer，
    自己造一个反而是「不像本人浏览器点的」的破绽。
    """
    return {
        'origin': "https://glados.cloud",
        'accept': "application/json, text/plain, */*",
        'user-agent': user_agent,
        'content-type': 'application/json;charset=UTF-8',
    }


# Request Headers（其余接口沿用，签到请求会按平台动态换 UA）
HEADERS_TEMPLATE = build_headers(DEFAULT_UA)

# Exchange Plan Points
EXCHANGE_POINTS = {"plan100": 100, "plan200": 200, "plan500": 500}

# 明确表示「关闭自动兑换」的取值（不区分大小写）。留空 / 不设置同样视为关闭。
EXCHANGE_DISABLED_VALUES = {"", "none", "off", "false", "no", "0", "disable", "disabled"}

def load_config() -> Tuple[str, List[str], Optional[str]]:
    push_key_env = os.environ.get(ENV_PUSH_KEY)
    raw_cookies_env = os.environ.get(ENV_COOKIES)
    exchange_plan_env = os.environ.get(ENV_EXCHANGE_PLAN)

    if not push_key_env:
        logger.warning(f"环境变量 '{ENV_PUSH_KEY}' 未设置。")
        push_key = ''
    else:
        push_key = push_key_env

    if not raw_cookies_env:
        logger.warning(f"环境变量 '{ENV_COOKIES}' 未设置。")
        cookies_list = []
    else:
        cookies_list = [cookie.strip() for cookie in raw_cookies_env.split('&') if cookie.strip()]
        if not cookies_list:
            raise ValueError(f"环境变量 '{ENV_COOKIES}' 已设置，但未包含任何有效的 Cookie。")

    # 自动兑换：默认关闭。只有把 GLADOS_EXCHANGE_PLAN 显式设成 plan100/plan200/plan500 才启用。
    # 说明：积分攒着不会浪费，兑换比例是固定的（500 分 = 100 天），需要时才开就来得及。
    raw_plan = (exchange_plan_env or "").strip()
    if raw_plan.lower() in EXCHANGE_DISABLED_VALUES:
        exchange_plan = None
        if exchange_plan_env:
            logger.info(f"环境变量 '{ENV_EXCHANGE_PLAN}' = '{exchange_plan_env}'，自动兑换已关闭。")
        else:
            logger.info(f"环境变量 '{ENV_EXCHANGE_PLAN}' 未设置，自动兑换已关闭（默认行为）。")
    elif raw_plan.lower() in EXCHANGE_POINTS:
        exchange_plan = raw_plan.lower()
        logger.info(f"使用指定的兑换计划: {exchange_plan}")
    else:
        exchange_plan = None
        logger.warning(
            f"环境变量 '{ENV_EXCHANGE_PLAN}' 的值 '{exchange_plan_env}' 无效，已关闭自动兑换。"
            f"可选值: {', '.join(EXCHANGE_POINTS)}，或 off/none 显式关闭。"
        )

    logger.info(f"共加载了 {len(cookies_list)} 个 Cookie 用于签到。")
    logger.info(f"当前 {ENV_PUSH_KEY} {'已设置' if push_key_env else '未设置'}。")
    logger.info(f"当前 {ENV_EXCHANGE_PLAN}: {exchange_plan or '关闭（不自动兑换）'}。")

    return push_key, cookies_list, exchange_plan

def make_request(url: str, method: str, headers: Dict[str, str], data: Optional[Dict] = None, cookies: str = "") -> Optional[requests.Response]:
    session_headers = headers.copy()
    session_headers['cookie'] = cookies

    try:
        if method.upper() == 'POST':
            response = requests.post(url, headers=session_headers, data=json.dumps(data), timeout=30)
        elif method.upper() == 'GET':
            response = requests.get(url, headers=session_headers, timeout=30)
        else:
            logger.error(f"不支持的 HTTP 方法: {method}")
            return None

        if not response.ok:
            logger.warning(f"向 {url} 发起的请求失败，状态码 {response.status_code}。响应内容: {response.text}")
            return None
        return response
    except requests.exceptions.RequestException as e:
        logger.error(f"向 {url} 发起请求时发生网络错误: {e}")
        return None


def checkin_request(cookie: str, user_agent: str) -> Optional[Dict]:
    """发一次签到请求，返回解析后的响应体（失败返回 None）"""
    response = make_request(CHECKIN_URL, 'POST', build_headers(user_agent), CHECKIN_DATA, cookies=cookie)
    if not response:
        return None
    try:
        return response.json()
    except json.JSONDecodeError:
        logger.error(f"解析签到响应 JSON 失败: {response.text}")
        return None


def do_checkin(cookie: str) -> Tuple[Optional[Dict], str]:
    """签到（含设备平台自适应重试）。

    返回 (响应体, 使用的 UA)。返回 None 表示请求层面就失败了。

    流程：先用上次成功的 UA（没有就用默认）签到；若被判定为自动签到
    （code 4 + reason=device-mismatch），读出服务端给的 loginDevice，
    切到对应平台的 UA 再试一次。这是 GLaDOS 2026-09 之后的标准解法。
    """
    start_ua = _device_ua_cache.get("_last") or DEFAULT_UA

    raw = checkin_request(cookie, start_ua)
    if raw is None:
        return None, start_ua

    if raw.get("code") == CODE_DEVICE and raw.get("reason") == "device-mismatch":
        login_device = raw.get("loginDevice")
        recover_ua = _device_ua_cache.get(login_device) or PLATFORM_UA.get(login_device)
        if recover_ua and recover_ua != start_ua:
            logger.warning(
                f"设备平台不匹配 (loginDevice={login_device}, "
                f"currentDevice={raw.get('currentDevice')})，切换 UA 重试"
            )
            raw = checkin_request(cookie, recover_ua)
            if raw is not None:
                return raw, recover_ua
            return None, recover_ua
        logger.error(
            f"被判定为自动签到，但无法自动恢复：loginDevice={login_device} 不在已知平台表里，"
            f"或与当前 UA 相同。请重新登录 glados.cloud 手动签到一次并刷新 Cookie。"
        )

    return raw, start_ua


def checkin_and_process(cookie: str, exchange_plan: Optional[str]) -> Tuple[str, str, str, str, str, str]:
    """返回 (状态, 本次积分, 剩余天数, 剩余积分, 兑换结果, 结果码)

    结果码：OK / REPEAT / AUTH / DEVICE / FAIL，供 main() 决定退出码。
    """
    status_msg = "签到请求失败"
    points_gained = "0"
    remaining_days = "获取剩余天数失败"
    remaining_points = "获取剩余积分失败"
    exchange_msg = "兑换跳过或失败"
    result_code = "FAIL"

    raw, used_ua = do_checkin(cookie)
    if raw is None:
        return status_msg, points_gained, remaining_days, remaining_points, exchange_msg, result_code

    code = raw.get("code", -99)
    message = raw.get("message", "无消息字段")
    points_gained = str(raw.get("points", 0))

    if code == CODE_SUCCESS:
        status_msg = f"签到成功，获得 {points_gained} 积分"
        result_code = "OK"
        _device_ua_cache["_last"] = used_ua
        logger.info(f"签到成功 (code {code}, points {points_gained}, UA={used_ua})")
    elif code == CODE_REPEAT:
        status_msg = "重复签到，明天再来"
        points_gained = "0"
        result_code = "REPEAT"
        _device_ua_cache["_last"] = used_ua
        logger.info(f"重复签到 (code {code})")
    elif code == CODE_DEVICE:
        status_msg = f"被判定为自动签到，签到失败: {message}"
        points_gained = "0"
        result_code = "DEVICE"
        logger.error(
            f"签到被判定为自动签到 (code 4, message: {message})。"
            f"服务端给的 loginDevice={raw.get('loginDevice')}, currentDevice={raw.get('currentDevice')}；"
            f"本次使用的 UA 是 {used_ua}。若自动切换 UA 仍失败，"
            f"请重新登录 glados.cloud 手动签到一次并刷新 GLADOS_COOKIES。"
        )
    elif code == CODE_AUTH:
        status_msg = f"认证失败，Cookie 无效或已过期: {message}"
        points_gained = "0"
        result_code = "AUTH"
        logger.error(f"认证失败 (code -2)，Cookie 无效、已过期或不完整（注意 gld:sess.sig 要一起复制）")
    else:
        status_msg = f"签到失败: {message}"
        points_gained = "0"
        result_code = "FAIL"

    status_response = make_request(STATUS_URL, 'GET', HEADERS_TEMPLATE, cookies=cookie)
    if status_response:
        try:
            status_data = status_response.json()
            left_days_float = status_data.get('data', {}).get('leftDays', None)
            if left_days_float is not None:
                remaining_days = f"{int(float(left_days_float))} 天"
            else:
                remaining_days = "获取剩余天数失败 (响应结构异常)"
        except json.JSONDecodeError:
            logger.error(f"解析状态响应 JSON 失败: {status_response.text}")
            remaining_days = "获取剩余天数失败 (JSON解析错误)"
        except (ValueError, TypeError):
            remaining_days = "获取剩余天数失败 (数值转换错误)"
    else:
        remaining_days = "获取剩余天数失败 (HTTP请求失败)"

    # 注意：points_data 在这里先初始化，避免积分接口失败时下面引用未定义变量
    points_data: Dict = {}
    points_response = make_request(POINTS_URL, 'GET', HEADERS_TEMPLATE, cookies=cookie)
    if points_response:
        try:
            points_data = points_response.json()
            points_float = points_data.get('points', None)
            if points_float is not None:
                remaining_points = f"{int(float(points_float))} 积分"
            else:
                remaining_points = "获取剩余积分失败 (响应结构异常)"
        except json.JSONDecodeError:
            logger.error(f"解析积分响应 JSON 失败: {points_response.text}")
            remaining_points = "获取剩余积分失败 (JSON解析错误)"
        except (ValueError, TypeError):
            remaining_points = "获取剩余积分失败 (数值转换错误)"
    else:
        remaining_points = "获取剩余积分失败 (HTTP请求失败)"

    current_points_numeric = 0
    try:
        current_points_numeric = int(float(points_data.get('points', 0)))
    except (ValueError, TypeError):
        logger.warning(f"无法解析当前积分数值，可能影响兑换判断: {remaining_points}")

    if exchange_plan is None:
        exchange_msg = "自动兑换已关闭"
        logger.info(
            f"当前积分 {current_points_numeric}；自动兑换已关闭，跳过兑换。"
            f"需要启用时把 GitHub Secret `{ENV_EXCHANGE_PLAN}` 设为 plan100/plan200/plan500 即可。"
        )
    else:
        required_points = EXCHANGE_POINTS.get(exchange_plan, 500)
        if current_points_numeric >= required_points:
            logger.info(f"开始兑换 {exchange_plan} 计划 (需要 {required_points} 积分)")
            exchange_response = make_request(EXCHANGE_URL, 'POST', HEADERS_TEMPLATE, {"planType": exchange_plan}, cookies=cookie)
            if exchange_response:
                try:
                    exchange_data = exchange_response.json()
                    ex_code = exchange_data.get('code', -1)
                    if ex_code == 0:
                        exchange_msg = f"兑换成功：{exchange_plan}"
                    else:
                        detailed_msg = exchange_data.get('message', "未知错误")
                        exchange_msg = f"兑换失败: {exchange_plan}, 错误代码: {ex_code}, 详情: {detailed_msg}"
                except json.JSONDecodeError:
                    logger.error(f"解析兑换响应 JSON 失败: {exchange_response.text}")
                    exchange_msg = f"兑换响应解析失败: {exchange_plan}"
            else:
                exchange_msg = f"兑换请求失败：{exchange_plan}"
        else:
            logger.info(f"积分不足以兑换 {exchange_plan}。所需: {required_points}, 当前: {current_points_numeric}")
            exchange_msg = f"积分不足，未兑换: {exchange_plan}"

    return status_msg, points_gained, remaining_days, remaining_points, exchange_msg, result_code

def format_push_content(results: List[Dict[str, str]]) -> Tuple[str, str]:
    success_count = sum(1 for r in results if r['result_code'] in ("OK", "REPEAT"))
    fail_count = sum(1 for r in results if r['result_code'] not in ("OK", "REPEAT"))

    title = f'GLaDOS 签到, 成功{success_count}, 失败{fail_count}'

    content_lines = []
    for i, res in enumerate(results, 1):
        line_parts = [
            f"账号{i}:",
            f"P:{res['points']}",
            f"剩余天数:{res['days']}",
            f"总积分:{res['points_total']}",
            f"| {res['status']}",
            f"; {res['exchange']}"
        ]
        line = " ".join(line_parts)
        content_lines.append(line)

    content = "\n".join(content_lines)
    return title, content

def send_pushplus(token: str, title: str, content: str) -> None:
    safe_title = str(title).replace("\r", " ").replace("\n", " ").strip()
    if not safe_title:
        safe_title = "GLaDOS 签到通知"

    data = {
        "token": token,
        "title": safe_title,
        "content": str(content),
        "template": "txt"
    }

    response = requests.post(
        "https://www.pushplus.plus/send",
        json=data,
        timeout=15
    )

    logger.info(f"PushPlus 状态码: {response.status_code}")
    logger.info(f"PushPlus 返回: {response.text}")

    response.raise_for_status()

    result = response.json()
    if result.get("code") != 200:
        raise Exception(f"PushPlus 推送失败: {result}")

def main() -> int:
    """返回退出码：0 = 签到成功/已签到；1 = 签到失败；2 = 配置错误。

    有了退出码，Action 才会在失败时变红并给你发 GitHub 失败邮件 ——
    否则脚本永远退 0，签失败了你也看不见。
    """
    push_key = ""
    results: List[Dict[str, str]] = []
    config_error = False

    try:
        push_key, cookies_list, exchange_plan = load_config()

        if not cookies_list:
            logger.error("未找到有效的 Cookie，退出程序。")
            title, content = "# 未找到 cookies!", ""
            config_error = True
        else:
            if os.environ.get(ENV_USER_AGENT, "").strip():
                logger.info(f"起始 User-Agent: 使用 {ENV_USER_AGENT} 指定的值")
            else:
                logger.info(f"起始 User-Agent: 内置 {DEFAULT_UA.split(') ')[0]}) "
                            f"（可用 {ENV_USER_AGENT} 覆盖为登录浏览器的 UA）")
            for idx, cookie in enumerate(cookies_list, 1):
                logger.info(f"正在处理第 {idx} 个账户...")
                status, points, days, points_total, exchange, rcode = checkin_and_process(cookie, exchange_plan)
                results.append({
                    'status': status,
                    'points': points,
                    'days': days,
                    'points_total': points_total,
                    'exchange': exchange,
                    'result_code': rcode,
                })

            title, content = format_push_content(results)
            logger.info(f"推送标题: {title}")
            logger.info(f"推送内容:\n{content}")

    except Exception as e:
        logger.error(f"主程序执行过程中发生未预期的错误: {e}")
        title, content = "# 脚本执行出错", str(e)
        config_error = True

    if not push_key:
        logger.info(f"未设置 '{ENV_PUSH_KEY}'，跳过推送通知。")
    else:
        try:
            send_pushplus(push_key, title, content)
            logger.info("PushPlus 推送通知发送成功。")
        except Exception as e:
            logger.error(f"发送 PushPlus 推送通知失败: {e}")

    if config_error:
        logger.error("签到完成 (退出码 2)")
        return 2

    all_ok = bool(results) and all(r['result_code'] in ("OK", "REPEAT") for r in results)
    if all_ok:
        logger.info("签到完成 (退出码 0)")
        return 0

    logger.error("签到失败 (退出码 1)")
    return 1


if __name__ == '__main__':
    sys.exit(main())
