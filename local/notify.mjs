// GLaDOS 本机签到 —— 失败告警（PushPlus）。
//
// 为什么是 .mjs 而不是 .ps1：PowerShell 5.1 读无 BOM 的 UTF-8 会把中文全变乱码，
// 这个项目本来就是 node，直接复用。
//
// 推送风格对齐 hw-grow-auto：template=txt，中文标题，正文几行说得清就行。
//
// 用法：
//   node notify.mjs <exitCode> [logPath] [--test]
//   exitCode 0 不推（正常签到不打扰）；1 失败；2 未登录；其他 异常

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CFG = 'E:\\workspace\\my_script\\hw-grow-auto\\config.json';

const args = process.argv.slice(2).filter((a) => a !== '--test');
const IS_TEST = process.argv.includes('--test');
const code = Number(args[0] ?? 1);
const logPath = args[1] || '';

if (code === 0 && !IS_TEST) process.exit(0);

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

// 日志尾部：够看清是哪一类失败，不刷屏
let tail = '';
if (logPath && fs.existsSync(logPath)) {
  tail = fs.readFileSync(logPath, 'utf8').trimEnd().split(/\r?\n/).slice(-12).join('\n');
}

const lines = [
  `时间：${TZ()}`,
  `结果：${reason}（exit ${code}）`,
];
if (IS_TEST) lines.push('（测试推送，日志内容是今天正常签到的记录，忽略即可）');
lines.push(
  '',
  '处理方式：',
  '  cd E:\\workspace\\my_script\\Gladoscheckin\\local',
  code === 2 ? '  node checkin.mjs --login   # 手动登录一次' : '  node checkin.mjs           # 手动重跑看报错',
);
if (tail) {
  lines.push('', '—— 日志尾部 ——', tail);
}

const title = IS_TEST ? `[测试] GLaDOS 签到告警 ${md}` : `GLaDOS 签到异常 ${md}`;

try {
  const r = await fetch('https://www.pushplus.plus/send', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ token, title, content: lines.join('\n'), template: 'txt' }),
  });
  const j = await r.json().catch(() => ({}));
  console.log(`[notify] pushplus code=${j.code} msg=${j.msg}`);
} catch (e) {
  console.log(`[notify] 推送失败：${e.message}`);
}
process.exit(0);
