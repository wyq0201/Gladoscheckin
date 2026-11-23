// GLaDOS 本机签到 —— PushPlus 推送。
//
// 为什么是 .mjs 而不是 .ps1：PowerShell 5.1 读无 BOM 的 UTF-8 会把中文全变乱码，
// 这个项目本来就是 node，直接复用。
//
// 推送风格对齐 hw-grow-auto：template=txt，中文标题，正文几行说得清就行。
//
// 用法：
//   node notify.mjs <exitCode> [logPath] --daily   每日结果（成功也推，日常用这个）
//   node notify.mjs <exitCode> [logPath]           仅失败告警（成功静默）
//   node notify.mjs 0 <logPath> --test             测试推送
//
// exitCode：0 已签/签到成功；1 失败；2 未登录；其他 异常

import fs from 'node:fs';

const CFG = 'E:\\workspace\\my_script\\hw-grow-auto\\config.json';

const flags = new Set(process.argv.slice(2).filter((a) => a.startsWith('--')));
const args = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const IS_TEST = flags.has('--test');
const DAILY = flags.has('--daily');
const code = Number(args[0] ?? 1);
const logPath = args[1] || '';

// 成功且非每日模式 → 静默（老行为）
if (code === 0 && !IS_TEST && !DAILY) process.exit(0);

const TZ = (d = new Date()) =>
  new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', hour12: false,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  }).format(d);

const md = TZ().slice(5);           // MM-DD

const REASON = {
  1: '签到失败（Cloudflare code=5 或页面结构变了）',
  2: '未登录（profile 失效，需要重新跑 --login）',
};
const reason = REASON[code] || `异常退出码 ${code}`;

// ── 从日志里捞当日结果 ────────────────────────────────
// 日志形如：
//   [2026/11/23 08:40:06] 登录态：HTTP 0 已登录 · 剩余 449 天 · 总 664 分
//   [2026/11/23 08:40:15] ✅ 签到成功，本次 +2 积分
//   [2026/11/23 08:40:15] 今日已签到（2026-11-23 入账 2 分），今天不用再签
function readResult(file) {
  const out = { leftDays: null, total: null, gained: null, already: false, at: null };
  if (!file || !fs.existsSync(file)) return out;
  const lines = fs.readFileSync(file, 'utf8').split(/\r?\n/);

  for (const ln of lines) {
    if (!ln.startsWith('[')) continue;
    const at = (ln.match(/^\[([^\]]+)\]/) || [])[1];
    if (at) out.at = at;

    const acc = ln.match(/剩余\s*(\d+)\s*天\s*·\s*总\s*(\d+)\s*分/);
    if (acc) {
      out.leftDays = Number(acc[1]);
      out.total = Number(acc[2]);
    }

    const got = ln.match(/签到成功，本次\s*\+(\d+)\s*积分/);
    if (got) {
      out.gained = Number(got[1]);
      out.already = false;
    }

    const had = ln.match(/今日已签到（[^）]*入账\s*(\d+)\s*分）/);
    if (had && out.gained == null) {
      out.gained = Number(had[1]);
      out.already = true;
    }
  }
  return out;
}

const r = readResult(logPath);

let token = '';
try {
  token = JSON.parse(fs.readFileSync(CFG, 'utf8')).pushplusToken || '';
} catch (e) {
  console.log(`[notify] 读不到 token（${CFG}）：${e.message}`);
}
if (!token) {
  console.log('[notify] 没有 pushplusToken，跳过推送');
  process.exit(0);
}

const ok = code === 0;
const lines = [];

if (ok) {
  lines.push(
    `时间：${r.at || TZ()}`,
    r.already ? `结果：今日已签到（+${r.gained ?? '?'} 分）` : `结果：签到成功 +${r.gained ?? '?'} 分`,
  );
  if (r.leftDays != null) lines.push(`账号：剩余 ${r.leftDays} 天 · 总分 ${r.total} 分`);
} else {
  lines.push(`时间：${TZ()}`, `结果：${reason}（exit ${code}）`);
  lines.push(
    '',
    '处理方式：',
    '  cd E:\\workspace\\my_script\\Gladoscheckin\\local',
    code === 2 ? '  node checkin.mjs --login   # 手动登录一次' : '  node checkin.mjs           # 手动重跑看报错',
  );
}

if (IS_TEST) {
  lines.push('', '（测试推送，忽略时间与分数）');
} else if (!ok && logPath && fs.existsSync(logPath)) {
  const tail = fs.readFileSync(logPath, 'utf8').trimEnd().split(/\r?\n/).slice(-12).join('\n');
  if (tail) lines.push('', '—— 日志尾部 ——', tail);
}

const title = IS_TEST
  ? `[测试] GLaDOS 签到 ${md}`
  : ok
    ? `GLaDOS 签到 ${md} +${r.gained ?? '?'} 分`
    : `GLaDOS 签到异常 ${md}`;

try {
  const resp = await fetch('https://www.pushplus.plus/send', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ token, title, content: lines.join('\n'), template: 'txt' }),
  });
  const j = await resp.json().catch(() => ({}));
  console.log(`[notify] pushplus code=${j.code} msg=${j.msg}`);
} catch (e) {
  console.log(`[notify] 推送失败：${e.message}`);
}
process.exit(0);
