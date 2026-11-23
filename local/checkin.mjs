// 本机 GLaDOS 签到：真浏览器跑，靠页面自己的按钮 + Cloudflare 组件通过 Turnstile。
//
// 为什么需要这个
// -------------
// 2026-11-14 起 GLaDOS 签到接口改成 Turnstile 保护：`POST /api/user/checkin` 只带
// `token={host}`，靠浏览器里 CF 组件下发的 clearance 放行，且是 interaction-only
// （后台/隐藏页不下发 token）。纯 Python + requests 拿不到，Actions 上一律 code=5。
//
// 本脚本不做任何伪造：打开真 Chrome → 等几秒让 Turnstile 自己跑完 → 点页面上的
// 签到按钮 → 旁听 /api/user/checkin 的响应。跟上游 extension/inject.js 一个思路，
// 但不依赖扩展、不用浏览器常开。
//
// 用法
// ----
//   npm i                      # 首次
//   node checkin.mjs --login   # 首次：打开窗口手动登录 GLaDOS，登录完直接关掉
//   node checkin.mjs           # 有窗口跑（推荐，Turnstile 需要可见标签页）
//   node checkin.mjs --headless# 试无窗口（Chrome 新版 headless，能不能过看运气）
//
// 退出码：0 已签/签到成功；1 失败；2 未登录

import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROFILE = path.join(HERE, 'profile');
const DOMAIN = process.env.GLADOS_DOMAIN || 'glados.cloud';
const HEADLESS = process.argv.includes('--headless');
const LOGIN_ONLY = process.argv.includes('--login');
// 浏览器通道：本机默认 chrome；云电脑只装了 Edge 时用 GLA_CHANNEL=msedge。
// Turnstile 认指纹，Edge/Chrome 都是真实浏览器，都能过；bundled chromium 不行。
const CHANNEL = process.env.GLA_CHANNEL || 'chrome';
const MIN_STAY = 3000;   // 官网要求 challenge 至少 2.5 秒后才提交

const TZ = (d = new Date()) =>
  new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', hour12: false,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).format(d);

const log = (...a) => console.log(`[${TZ()}]`, ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 已签到文案（与扩展保持一致）
const DONE_TEXT = /已签到|已簽到|\balready\b|\bchecked\b|\bsigned\b|明日|tomorrow/i;

async function main() {
  fs.mkdirSync(PROFILE, { recursive: true });

  if (!fs.existsSync(path.join(PROFILE, 'Default'))) {
    log('首次运行：先登录一次（--login），之后不用再登');
  }

  const ctx = await chromium.launchPersistentContext(PROFILE, {
    headless: HEADLESS,
    channel: CHANNEL,                  // 用系统 Chrome/Edge，指纹比 bundled chromium 自然
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    viewport: { width: 1400, height: 900 },
    args: ['--disable-blink-features=AutomationControlled'],
  });

  try {
    const page = ctx.pages()[0] || (await ctx.newPage());
    const url = `https://${DOMAIN}/console/checkin`;
    log(`打开 ${url}`);
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90_000 });

    // 登录态 + 今日签到状态：用 /api/user/status + /api/user/points 判，
    // 比看 URL 和按钮文案都稳（console 是 SPA，未登录不跳 URL；按钮文案有延迟）。
    const snap = await readSnapshotSafe(page);
    log(`登录态：HTTP ${snap.statusCode ?? '?'} ${snap.loggedIn ? '已登录' : '未登录'}` +
        (snap.loggedIn ? ` · 剩余 ${snap.leftDays ?? '?'} 天 · 总 ${snap.points ?? '?'} 分` : ''));

    if (!snap.loggedIn) {
      if (LOGIN_ONLY) {
        log('请在窗口里登录 GLaDOS，登录成功后直接关闭窗口');
        await new Promise((resolve) => ctx.on('close', resolve));
        return 0;
      }
      console.error('未登录。先跑：node checkin.mjs --login');
      return 2;
    }

    if (LOGIN_ONLY) {
      log('已经是登录态，profile 可用。1.5 秒后自动关闭');
      await sleep(1500);
      return 0;
    }

    // 服务端流水里已经有今天的签到记录 → 直接收工，不点按钮
    // （已签时前端不再发 /api/user/checkin，硬点会白等到超时）
    if (snap.todayPoints != null) {
      log(`今日已签到（${snap.todayKey} 入账 ${snap.todayPoints} 分），今天不用再签`);
      return 0;
    }

    // 等签到按钮（button.ckb 是官网用的 class，兜底按文案找）
    const btn = page.locator('button.ckb').first();
    try {
      await btn.waitFor({ state: 'visible', timeout: 45_000 });
    } catch {
      const byText = page.locator('button', { hasText: /check\s*-?\s*in|签到|簽到/i }).first();
      if (await byText.count()) {
        await byText.waitFor({ state: 'visible', timeout: 10_000 });
        return await clickAndJudge(page, byText);
      }
      console.error('未找到签到按钮（页面结构可能变了）');
      return 1;
    }

    return await clickAndJudge(page, btn);
  } finally {
    await ctx.close().catch(() => {});
  }
}

// 读账号快照：登录态、剩余天数、总积分、今天签到拿了几分。
// 移植自上游 extension/background.js 的 fetchAccountSnapshotInPage —— 日历面板用的
// 就是这份 points.history，是判断「今天到底签没签」最可靠的依据。
async function readSnapshot(page) {
  return await page.evaluate(async () => {
    const grab = async (p) => {
      try {
        const r = await fetch(p, {
          credentials: 'include',
          headers: { accept: 'application/json, text/plain, */*' },
        });
        return await r.json();
      } catch {
        return null;
      }
    };
    const status = await grab('/api/user/status');
    const points = await grab('/api/user/points');
    const d = (status && status.data) || {};
    const pd = (points && points.data) || points || {};

    const keyOf = (dt) => `${dt.getFullYear()}-${dt.getMonth() + 1}-${dt.getDate()}`;
    const todayKey = keyOf(new Date());

    const days = {};
    const history = Array.isArray(pd.history) ? pd.history : [];
    for (const it of history) {
      if (!it) continue;
      if (String(it.business || '').indexOf('checkin') === -1) continue;
      const raw = Number(it.time);
      if (!raw) continue;
      const ts = raw < 1e12 ? raw * 1000 : raw;   // 兼容秒级时间戳
      days[keyOf(new Date(ts))] = parseInt(it.change, 10) || 0;
    }
    // 部分站点只给 earned 字典
    const earned = pd.earned;
    if (earned && typeof earned === 'object' && !Array.isArray(earned)) {
      for (const k of Object.keys(earned)) {
        const norm = String(k).replace(
          /^(\d{4})-0?(\d{1,2})-0?(\d{1,2})$/,
          (m, y, mo, da) => `${Number(y)}-${Number(mo)}-${Number(da)}`,
        );
        if (days[norm] == null) days[norm] = Number(earned[k]) || 0;
      }
    }

    return {
      loggedIn: !!(status && status.code === 0),
      statusCode: status ? status.code : null,
      leftDays: d.leftDays != null ? Number(d.leftDays) : null,
      points: pd.points != null ? Number(pd.points) : null,
      todayKey,
      todayPoints: days[todayKey] != null ? days[todayKey] : null,
    };
  });
}

// readSnapshot 的容错壳：SPA 首屏导航会打断 in-page fetch 的 evaluate，
// 报 "Execution context was destroyed"。这属于时序问题，不是签到失败，
// 等页面落定后重试即可（2026-11-20 那次漏签就是栽在这里）。
const NAV_BROKEN = /Execution context was destroyed|Target closed|frame was detached|Cannot find context|navigat(ing|ion)/i;

async function readSnapshotSafe(page, attempts = 3) {
  let lastErr = null;
  for (let i = 1; i <= attempts; i++) {
    try {
      return await readSnapshot(page);
    } catch (e) {
      lastErr = e;
      const msg = String((e && e.message) || e);
      if (!NAV_BROKEN.test(msg)) throw e;
      log(`读取账号快照被页面导航打断（${i}/${attempts}）：${msg.split('\n')[0]}`);
      await page.waitForLoadState('domcontentloaded', { timeout: 15_000 }).catch(() => {});
      await sleep(800 * i);
    }
  }
  throw lastErr;
}

async function clickAndJudge(page, btn) {
  const cls = (await btn.getAttribute('class')) || '';
  const text = ((await btn.innerText()) || '').trim();

  if (cls.includes('is-done') || DONE_TEXT.test(text)) {
    log(`今日已签到（按钮：${text || cls}）`);
    return 0;
  }
  log(`按钮状态：${text || cls}`);

  // 拟人停留：给 Turnstile 时间跑完，同时满足官网 2.5 秒限制
  const stay = MIN_STAY + Math.random() * 1500;
  log(`停留 ${(stay / 1000).toFixed(1)}s 等 Turnstile…`);
  await sleep(stay);

  const waiting = page.waitForResponse(
    (r) => r.url().includes('/api/user/checkin') && !r.url().includes('/challenge'),
    { timeout: 45_000 },
  ).catch(() => null);

  log('点击签到按钮');
  await btn.click({ timeout: 15_000, force: true }).catch((e) => {
    log(`点击异常（继续等响应）：${e.message.split('\n')[0]}`);
    log(`当前 URL：${page.url()}`);
  });

  const resp = await waiting;
  if (!resp) {
    // 没抓到请求：可能已签过（页面不再发请求），或点击没落到按钮上。
    // 优先信服务端流水，其次看按钮文案，都不成立才报失败。
    await sleep(2500);
    const snap = await readSnapshotSafe(page).catch(() => null);
    if (snap && snap.todayPoints != null) {
      log(`今日已签到（${snap.todayKey} 入账 ${snap.todayPoints} 分）`);
      return 0;
    }
    const t2 = ((await btn.innerText().catch(() => '')) || '').trim();
    if (DONE_TEXT.test(t2)) {
      log(`今日已签到（按钮：${t2}）`);
      return 0;
    }
    console.error('点击后没抓到 /api/user/checkin 响应，服务端也没有今天的签到记录');
    return 1;
  }

  let data = null;
  try {
    data = await resp.json();
  } catch {
    console.error('签到响应不是 JSON');
    return 1;
  }

  const code = data?.code;
  const msg = data?.message || '';
  log(`响应 code=${code} message=${msg}`);

  // code=1 + "Today's observation logged. Return tomorrow" = 今天已经签过了（正常，不是失败）
  if (code === 1 || data?.repeated === true || data?.checkedIn === true ||
      /already|repeat|return tomorrow|observation logged/i.test(msg)) {
    const pts = data?.data?.change ?? data?.change;
    log(`今日已签到${pts != null ? `（今日已入账 ${pts} 分）` : ''} —— ${msg || '服务端已有记录'}`);
    return 0;
  }
  if (code === 0) {
    // 新协议的 data 里常常没有 change，分数只出现在 message："Checkin! Got 2 Points"
    const pts = data?.data?.change ?? data?.change
      ?? (msg.match(/Got\s+(\d+)\s+Point/i)?.[1])
      ?? '?';
    log(`✅ 签到成功，本次 +${pts} 积分`);
    return 0;
  }
  if (code === 5) {
    console.error('🔴 code=5：Cloudflare 验证未通过 —— 这次没签上。');
    console.error('   若一直这样，把窗口版改无头反而更糟；试试用有窗口模式跑，并让窗口保持前台可见。');
    return 1;
  }
  console.error(`🔴 签到失败：${msg}`);
  return 1;
}

main()
  .then((code) => process.exit(code))
  .catch((e) => {
    console.error('脚本异常：', e?.message || e);
    process.exit(1);
  });
