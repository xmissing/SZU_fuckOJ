/* OJ Auto 控制台 */
const $ = (id) => document.getElementById(id);
const RING_C = 2 * Math.PI * 52;

/* 两个 OJ 站点的兜底信息（config.json 里带了就用配置的） */
const SITE_FALLBACK = { '62': 'http://oj.example.com', '61': 'http://oj2.example.com' };
const SITE_LABEL = { '62': '站点 1', '61': '站点 2' };
let modalSite = null;

const state = {
  running: false,
  site: '62',
  // formSite = 表单里此刻填的是哪个站点的凭据。
  // 必须和 site 分开记：一旦两者错位，回写就会把 A 的账号写进 B。
  formSite: null,
  sites: {},
  problems: [],
  contest: null,
  done: 0,
  total: 0,
  startedAt: null,
  logFilter: 'all',
};

/* ---------------- 工具 ---------------- */
function toast(msg, kind = '') {
  const el = $('toast');
  el.textContent = msg;
  el.className = 'toast show ' + kind;
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.className = 'toast ' + kind), 2600);
}

function fmtDuration(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/* ---------------- 配置 / 站点 ---------------- */
async function loadConfig() {
  try {
    const cfg = await (await fetch('/api/config')).json();
    state.site = String(cfg.site || '62');
    state.sites = cfg.sites || {};
    $('maxRetry').value = cfg.max_retry || 3;
    $('limit').value = cfg.limit || 0;
    $('apiBase').value = cfg.api_base || '';
    $('apiKey').value = cfg.api_key || '';
    $('model').value = cfg.model || '';
    applySiteToForm(state.site);
  } catch (e) {
    toast('读取配置失败', 'err');
  }
}

/* 把某个站点的凭据填进表单，并同步顶部站点选择器 */
function applySiteToForm(site) {
  const info = state.sites[site] || {};
  const base = info.base || SITE_FALLBACK[site] || '';
  const name = info.name || SITE_LABEL[site] || '自定义站点';
  $('username').value = info.username || '';
  $('password').value = info.password || '';
  $('siteBase').textContent = base;
  $('accountSite').textContent = site;
  $('accountSiteName').textContent = name;
  $('accountSiteBase').textContent = base;
  $('brandSub').textContent = name + ' · 自动刷题';
  document.title = site + ' · ' + name + ' · OJ Auto';
  state.formSite = site; // 表单从此代表该站点
  renderSiteBtns();
}

/* 顶部站点按钮：只写「站号 + 网址」，不放课程名 */
function renderSiteBtns() {
  const box = $('siteBtns');
  if (!box) return;
  box.innerHTML = siteKeys().map((k) => {
    const on = k === state.site;
    const url = siteBaseOf(k);
    return `<button class="site-btn${on ? ' active' : ''}" data-site="${k}"
        title="${escapeHtml(siteNameOf(k) + ' · ' + url)}">
      <b>${escapeHtml(k)}</b>
      <span class="sb-url">${escapeHtml(url)}</span>
    </button>`;
  }).join('');
  box.querySelectorAll('.site-btn').forEach((b) => {
    b.addEventListener('click', () => switchSite(b.dataset.site));
  });
}

function siteNameOf(k) {
  return (state.sites[k] || {}).name || SITE_LABEL[k] || '自定义站点';
}

function siteBaseOf(k) {
  return (state.sites[k] || {}).base || SITE_FALLBACK[k] || '';
}

/* 登录状态徽章：明确"当前登录的是哪台、哪个账号" */
function setLoginBadge(user) {
  const el = $('siteLogin');
  const out = $('btnLogout');
  if (user) {
    el.textContent = '已登录 ' + user;
    el.className = 'site-login on';
    el.title = `${state.site} · ${siteNameOf(state.site)} · ${siteBaseOf(state.site)}`;
    if (out) { out.hidden = false; out.disabled = !!state.running; }
  } else {
    el.textContent = '未登录';
    el.className = 'site-login';
    el.title = '该站点尚未登录，点「测试连接」登录';
    if (out) out.hidden = true;
  }
}

/* 退出登录：清本地会话缓存 + 清空该站点的实验/题目展示 */
async function doLogout() {
  if (state.running) return toast('任务运行中，先停止再退出登录', 'err');
  const btn = $('btnLogout');
  btn.disabled = true;
  try {
    const r = await fetch('/api/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ site: state.site }),
    });
    const d = await r.json();
    if (!d.ok) {
      toast(d.msg || '退出失败', 'err');
      return;
    }
    state.contests = [];
    state.contest = null;
    state.problems = [];
    state.total = 0;
    state.done = 0;
    state.current = null;
    const sel = $('contestSelect');
    sel.hidden = true;
    sel.innerHTML = '';
    $('contestTitle').textContent = '未连接实验';
    $('contestRange').textContent = '已退出登录，点「测试连接」重新登录';
    $('countdownPill').hidden = true;
    setLoginBadge(null);
    renderProblems();
    renderStats();
    toast(`已退出 ${state.site} · ${siteNameOf(state.site)}`, 'ok');
  } catch (e) {
    toast('退出失败：' + e.message, 'err');
  } finally {
    btn.disabled = false;
  }
}

/* 切换站点：先把手上的输入存回旧站点，再加载新站点 */
function switchSite(site) {
  if (state.running) {
    renderSiteBtns();
    return toast('任务运行中，无法切换站点', 'err');
  }
  if (site === state.site) return;
  stashFormTo();
  state.site = site;
  applySiteToForm(site);
  setLoginBadge(null);
  // 换站点后旧的实验/题目数据全部作废
  state.contests = [];
  state.contest = null;
  state.problems = [];
  state.total = 0;
  state.done = 0;
  state.current = null;
  $('contestSelect').hidden = true;
  $('contestSelect').innerHTML = '';
  $('contestTitle').textContent = '未连接实验';
  $('contestRange').textContent = '已切换到 ' + site + ' 站点，请点「测试连接」';
  $('countdownPill').hidden = true;
  renderProblems();
  renderStats();
  saveConfig();
  toast('已切换到 ' + site + ' · ' + siteNameOf(site), 'ok');
}

/* 把表单内容回写到「它自己所属」的站点，默认取 formSite，避免与 site 错位时写串 */
function stashFormTo(site) {
  const k = site || state.formSite || state.site;
  if (!k) return;
  if (!state.sites[k]) state.sites[k] = {};
  const s = state.sites[k];
  s.username = $('username').value.trim();
  s.password = $('password').value;
}

/* ---------------- 站点设置弹窗 ---------------- */
function siteKeys() {
  const keys = ['62', '61'];
  Object.keys(state.sites || {}).forEach((k) => {
    if (!keys.includes(k)) keys.push(k);
  });
  return keys;
}

function selectSiteChoice(site) {
  modalSite = site;
  document.querySelectorAll('#siteChoices .site-choice').forEach((el) => {
    el.classList.toggle('active', el.dataset.site === site);
  });
}

function renderSiteModal() {
  const box = $('siteChoices');
  box.innerHTML = siteKeys().map((k) => {
    const info = state.sites[k] || {};
    const name = info.name || SITE_LABEL[k] || '自定义站点';
    const base = info.base || SITE_FALLBACK[k] || '';
    const now = k === state.site ? '<span class="sc-now">使用中</span>' : '';
    return `<div class="site-choice" data-site="${k}">
      <div class="sc-head">
        <span class="sc-radio"></span>
        <b class="sc-no">${escapeHtml(k)}</b>
        <span class="sc-name">${escapeHtml(name)}</span>
        ${now}
      </div>
      <input class="sc-url" type="text" spellcheck="false" value="${escapeHtml(base)}" placeholder="http://">
    </div>`;
  }).join('');
  box.querySelectorAll('.site-choice').forEach((el) => {
    el.addEventListener('click', (ev) => {
      if (ev.target.classList.contains('sc-url')) {
        selectSiteChoice(el.dataset.site);
        return;
      }
      selectSiteChoice(el.dataset.site);
    });
  });
  selectSiteChoice(modalSite || state.site);
}

function openSiteModal() {
  if (state.running) return toast('任务运行中，无法修改站点', 'err');
  modalSite = state.site;
  renderSiteModal();
  $('siteModal').hidden = false;
}

function closeSiteModal() {
  $('siteModal').hidden = true;
}

async function saveSiteModal() {
  const urlRe = /^https?:\/\/[^\s]+$/i;
  const picks = {};
  let bad = '';
  document.querySelectorAll('#siteChoices .site-choice').forEach((el) => {
    const k = el.dataset.site;
    let v = el.querySelector('.sc-url').value.trim().replace(/\/+$/, '');
    if (!v) v = SITE_FALLBACK[k] || '';
    if (!urlRe.test(v)) bad = bad || `${k} 的网址格式不对，要以 http:// 或 https:// 开头`;
    picks[k] = v;
  });
  if (bad) return toast(bad, 'err');

  const target = modalSite || state.site;
  Object.keys(picks).forEach((k) => {
    state.sites[k] = Object.assign({}, state.sites[k] || {}, { base: picks[k] });
  });
  closeSiteModal();

  if (target !== state.site) {
    switchSite(target);
    return;
  }
  stashFormTo();
  applySiteToForm(target);
  setLoginBadge(null);
  await saveConfig();
  toast('网址已更新，请重新「测试连接」', 'ok');
}

function collectConfig() {
  stashFormTo();
  const cur = state.sites[state.formSite || state.site] || {};
  const sel = $('contestSelect');
  const cv = sel && sel.value;
  return {
    site: state.site,
    // 顶层这两个只给前端校验用；后端按 sites[site] 取
    username: (cur.username || '').trim(),
    password: cur.password || '',
    sites: state.sites,
    max_retry: parseInt($('maxRetry').value || '3', 10),
    limit: parseInt($('limit').value || '0', 10) || 0,
    api_base: $('apiBase').value.trim(),
    api_key: $('apiKey').value.trim(),
    model: $('model').value.trim(),
    contest_id: cv === 'all' ? 'all' : (cv ? parseInt(cv, 10) : null),
  };
}

async function saveConfig() {
  try {
    await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(collectConfig()),
    });
  } catch (e) {}
}

/* ---------------- 实验切换 ---------------- */
function fillContestSelect() {
  const sel = $('contestSelect');
  const list = state.contests || [];
  if (!list.length) {
    sel.hidden = true;
    return;
  }
  const todoSum = list.reduce(
    (n, c) => n + (c.problems || []).filter((p) => p.state !== 'ac').length, 0);
  const allOpt = list.length > 1
    ? `<option value="all">全部进行中实验（待做 ${todoSum} 题）</option>`
    : '';
  sel.hidden = false;
  sel.innerHTML = allOpt + list
    .map((c) => {
      const t = (c.problems || []).filter((p) => p.state !== 'ac').length;
      return `<option value="${c.id}">${escapeHtml(c.title)} · 待做 ${t}/${(c.problems || []).length}</option>`;
    })
    .join('');
}

function selectContest(c) {
  if (!c) return;
  state.contest = c;
  state.problems = c.problems || [];
  state.total = state.problems.length;
  state.done = state.problems.filter((p) => p.state === 'ac').length;
  $('contestTitle').textContent = c.title;
  const t = c.end_time ? new Date(c.end_time) : null;
  $('contestRange').textContent = t
    ? `实验 #${c.id} · 截止 ${t.toLocaleString('zh-CN', { hour12: false })}`
    : `实验 #${c.id}`;
  const sel = $('contestSelect');
  if (!sel.hidden) sel.value = String(c.id);
  renderProblems();
  renderStats();
}

let saveTimer = null;
function autoSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveConfig, 500);
}

/* ---------------- 渲染 ---------------- */
const STATE_TEXT = {
  ac: ['AC', 'ac'],
  todo: ['待做', 'todo'],
  running: ['进行中', 'running'],
  failed: ['未通过', 'failed'],
  stopped: ['已停止', 'stopped'],
};

function renderProblems() {
  const list = $('problemList');
  const ps = state.problems || [];
  if (!ps.length) {
    list.innerHTML = '<li class="empty">暂无数据，请先「测试连接」读取进行中的实验</li>';
    return;
  }
  list.innerHTML = ps.map((p, i) => {
    const [text, cls] = STATE_TEXT[p.state] || STATE_TEXT.todo;
    const extra = p.last_status && p.state !== 'ac'
      ? `<span class="badge ${cls}">${text}</span><span class="p-id">${p.last_status}</span>`
      : `<span class="badge ${cls}">${text}</span>`;
    return `<li class="row ${p.state === 'running' ? 'running' : ''}">
      <span class="idx">${String.fromCharCode(65 + i)}</span>
      <span class="p-title">${escapeHtml(p.title)}<span class="p-id">#${p.id}</span></span>
      ${extra}
    </li>`;
  }).join('');
}

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function renderStats() {
  const total = state.total || 0;
  const done = state.done || 0;
  $('statTotal').textContent = total;
  $('statAc').textContent = done;
  const cur = $('statCurrent');
  if (state.current) {
    cur.textContent = state.current.title;
    cur.title = state.current.title;
    $('statCurrentHint').textContent = `#${state.current.id}`;
  } else if (state.running) {
    cur.textContent = '处理中…';
    $('statCurrentHint').textContent = '等待下一题';
  } else {
    cur.textContent = '—';
    $('statCurrentHint').textContent = total ? '已停止/空闲' : '等待开始';
  }
  const pct = total ? done / total : 0;
  $('ringFg').style.strokeDashoffset = String(RING_C * (1 - pct));
  $('ringPct').textContent = Math.round(pct * 100) + '%';
}

function renderRunning() {
  const running = state.running;
  $('btnRun').disabled = running;
  $('btnStop').disabled = !running;
  $('btnTest').disabled = running;
  $('btnSiteEdit').disabled = running;
  document.querySelectorAll('.site-btn').forEach((b) => { b.disabled = running; });
  if (!$('btnLogout').hidden) $('btnLogout').disabled = running;
  const dot = $('sideDot');
  dot.className = 'dot' + (running ? ' on' : (state.error ? ' err' : ''));
  $('sideStatusText').textContent = running ? '运行中' : (state.error ? '异常' : '空闲');
}

/* ---------------- 日志 ---------------- */
function appendLog(item) {
  const panel = $('logPanel');
  if (panel.querySelector('.log-empty')) panel.innerHTML = '';
  const div = document.createElement('div');
  div.className = 'log-line ' + (item.level || 'info');
  div.dataset.level = item.level || 'info';
  div.innerHTML = `<span class="log-time">${item.ts || ''}</span><span class="log-text">${escapeHtml(item.text)}</span>`;
  if (state.logFilter !== 'all' && div.dataset.level !== state.logFilter) div.style.display = 'none';
  panel.appendChild(div);
  while (panel.childElementCount > 900) panel.removeChild(panel.firstChild);
  panel.scrollTop = panel.scrollHeight;
}

function applyLogFilter() {
  document.querySelectorAll('#logPanel .log-line').forEach((el) => {
    el.style.display = (state.logFilter === 'all' || el.dataset.level === state.logFilter) ? '' : 'none';
  });
}

/* ---------------- 倒计时 ---------------- */
function tick() {
  if (state.contest && state.contest.end_time) {
    const end = new Date(state.contest.end_time).getTime();
    const left = end - Date.now();
    const pill = $('countdownPill');
    if (left > 0) {
      pill.hidden = false;
      pill.textContent = '剩余 ' + fmtDuration(left / 1000);
    } else {
      pill.hidden = false;
      pill.textContent = '已截止';
    }
  }
  if (state.running && state.startedAt) {
    $('statElapsed').textContent = fmtDuration(Date.now() / 1000 - state.startedAt);
  }
}

/* ---------------- 应用状态 ---------------- */
function applyState(s) {
  if (s.problems) state.problems = s.problems;
  if (s.contest) state.contest = s.contest;
  if (typeof s.done === 'number') state.done = s.done;
  if (typeof s.total === 'number') state.total = s.total;
  state.current = s.current || null;
  state.error = s.error || null;
  state.startedAt = s.started_at || null;
  const wasRunning = state.running;
  state.running = !!s.running;

  if (s.contest) {
    $('contestTitle').textContent = s.contest.title || '未连接实验';
    const t = s.contest.end_time ? new Date(s.contest.end_time) : null;
    $('contestRange').textContent = t
      ? `实验 #${s.contest.id} · 截止 ${t.toLocaleString('zh-CN', { hour12: false })}`
      : `实验 #${s.contest.id}`;
  }
  if (!state.running && wasRunning) {
    $('statElapsed').textContent = $('statElapsed').textContent;
    if (s.summary) toast(`完成：AC ${s.summary.ac}/${s.summary.total}`, 'ok');
  }
  renderProblems();
  renderStats();
  renderRunning();
}

/* ---------------- SSE ---------------- */
function connect() {
  const es = new EventSource('/api/stream');
  es.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    if (msg.type === 'log') appendLog(msg);
    else if (msg.type === 'state') applyState(msg);
  };
  es.onerror = () => {
    $('sideStatusText').textContent = '连接断开，重连中…';
  };
  es.onopen = () => {
    $('sideStatusText').textContent = state.running ? '运行中' : '空闲';
  };
}

/* ---------------- 操作 ---------------- */
async function doTest() {
  const btn = $('btnTest');
  const cfg = collectConfig();
  if (!cfg.username || !cfg.password) return toast('请填写学号与密码', 'err');
  btn.classList.add('loading');
  const old = btn.innerHTML;
  btn.innerHTML = '连接中…';
  $('apiChip').textContent = '识别验证码…';
  $('apiChip').className = 'chip cyan';
  try {
    const r = await fetch('/api/test', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cfg),
    });
    const d = await r.json();
    if (d.ok) {
      $('apiChip').textContent = '可用';
      $('apiChip').className = 'chip ok';
      setLoginBadge(d.user || '');
      toast(`已登录 ${d.site || state.site} · ${siteNameOf(d.site || state.site)}：${d.user}`, 'ok');
      state.contests = d.contests || [];
      fillContestSelect();
      if (state.contests.length) selectContest(state.contests[0]);
    } else {
      $('apiChip').textContent = '不可用';
      $('apiChip').className = 'chip bad';
      toast(d.msg || '连接失败', 'err');
    }
  } catch (e) {
    $('apiChip').textContent = '异常';
    $('apiChip').className = 'chip bad';
    toast('请求失败：' + e.message, 'err');
  } finally {
    btn.classList.remove('loading');
    btn.innerHTML = old;
  }
}

async function doRun() {
  const cfg = collectConfig();
  if (!cfg.username || !cfg.password) return toast('请填写学号与密码', 'err');
  if (!cfg.api_base || !cfg.api_key) return toast('请填写 AI 接口地址与密钥', 'err');
  try {
    const r = await fetch('/api/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cfg),
    });
    const d = await r.json();
    if (d.ok) {
      toast(`任务已启动（${d.site}${d.limit ? ' · 最多 ' + d.limit + ' 题' : ' · 全部'}）`, 'ok');
      state.startedAt = Date.now() / 1000;
      $('statElapsed').textContent = '00:00';
    } else {
      toast(d.msg || '启动失败', 'err');
    }
  } catch (e) {
    toast('启动失败：' + e.message, 'err');
  }
}

async function doStop() {
  await fetch('/api/stop', { method: 'POST' });
  toast('正在停止…');
}

/* ---------------- API 连接视图 ---------------- */
function setApiResult(kind, html) {
  const box = $('apiResult');
  box.hidden = false;
  box.className = 'api-result ' + kind;
  box.innerHTML = html;
}

function setApiChip(text, kind) {
  const chip = $('apiChip');
  chip.textContent = text;
  chip.className = 'chip' + (kind ? ' ' + kind : '');
}

async function doPing() {
  const cfg = collectConfig();
  if (!cfg.api_base || !cfg.api_key || !cfg.model) {
    return toast('请先填写 Base URL、API Key 与模型', 'err');
  }
  const btn = $('btnPing');
  const old = btn.innerHTML;
  btn.classList.add('loading');
  btn.innerHTML = '连接中…';
  setApiResult('loading', '正在向 <b>' + escapeHtml(cfg.api_base) + '</b> 发起请求，推理模型可能需 10~60 秒…');
  setApiChip('检测中', 'cyan');
  try {
    const r = await fetch('/api/ping', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cfg),
    });
    const d = await r.json();
    if (d.ok) {
      setApiChip('可用', 'ok');
      setApiResult('ok',
        '<div class="r-head">接口可用 · ' + (d.cost != null ? d.cost + 's' : '') + '</div>' +
        '模型 <b>' + escapeHtml(d.model || cfg.model) + '</b><br>' +
        '回复：<span class="r-body">' + escapeHtml(d.reply || '(空)') + '</span>');
      toast('AI 接口连通正常', 'ok');
    } else {
      setApiChip('不可用', 'bad');
      setApiResult('bad', '<div class="r-head">接口不可用</div>' + escapeHtml(d.msg || '未知错误'));
      toast('接口不可用', 'err');
    }
  } catch (e) {
    setApiChip('异常', 'bad');
    setApiResult('bad', '<div class="r-head">请求异常</div>' + escapeHtml(e.message));
    toast('请求失败：' + e.message, 'err');
  } finally {
    btn.classList.remove('loading');
    btn.innerHTML = old;
  }
}

async function doSaveApi() {
  const cfg = collectConfig();
  const btn = $('btnSaveApi');
  btn.classList.add('loading');
  try {
    const r = await fetch('/api/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cfg),
    });
    const d = await r.json();
    if (d.ok) {
      setApiResult('ok',
        '<div class="r-head">配置已保存</div>已写入本地 <b>config.json</b>，下次启动自动加载。');
      toast('配置已保存', 'ok');
    } else {
      toast('保存失败', 'err');
    }
  } catch (e) {
    toast('保存失败：' + e.message, 'err');
  } finally {
    btn.classList.remove('loading');
  }
}

/* ---------------- 视图切换 ---------------- */
function switchView(name) {
  document.querySelectorAll('.nav-item').forEach((x) => {
    x.classList.toggle('active', x.dataset.view === name);
  });
  document.querySelectorAll('.view').forEach((v) => {
    v.classList.toggle('active', v.id === 'view-' + name);
  });
  try { localStorage.setItem('oj.view', name); } catch (e) {}
  if (name === 'console') {
    const p = $('logPanel');
    if (p) p.scrollTop = p.scrollHeight;
  }
}

/* ---------------- 前端版本自检（改了 static 后旧页面会提示刷新） ---------------- */
let uiVer = null;
async function checkUiVersion() {
  try {
    const r = await fetch('/api/version', { cache: 'no-store' });
    const d = await r.json();
    if (!d || !d.ver) return;
    if (uiVer === null) {
      uiVer = d.ver;
      return;
    }
    if (d.ver !== uiVer) $('uiUpdate').hidden = false;
  } catch (e) {}
}

/* ---------------- 绑定 ---------------- */
window.addEventListener('DOMContentLoaded', async () => {
  await loadConfig();
  connect();

  document.querySelectorAll('input').forEach((el) => {
    el.addEventListener('change', autoSave);
    el.addEventListener('blur', autoSave);
  });

  $('btnTest').addEventListener('click', doTest);
  $('btnRun').addEventListener('click', doRun);
  $('btnStop').addEventListener('click', doStop);
  $('btnPing').addEventListener('click', doPing);
  $('btnSaveApi').addEventListener('click', doSaveApi);

  $('contestSelect').addEventListener('change', (e) => {
    const c = (state.contests || []).find((x) => String(x.id) === e.target.value);
    if (c) selectContest(c);
  });

  document.querySelectorAll('.eye').forEach((btn) => {
    btn.addEventListener('click', () => {
      const input = $(btn.dataset.target);
      input.type = input.type === 'password' ? 'text' : 'password';
    });
  });

  document.querySelectorAll('.seg-btn').forEach((b) => {
    b.addEventListener('click', () => {
      document.querySelectorAll('.seg-btn').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.logFilter = b.dataset.level;
      applyLogFilter();
    });
  });

  $('btnClear').addEventListener('click', () => {
    $('logPanel').innerHTML = '<div class="log-empty">日志已清空（服务端仍保留历史）</div>';
  });

  // 侧边栏视图切换（控制台 / API 连接）
  document.querySelectorAll('.nav-item').forEach((a) => {
    a.addEventListener('click', () => switchView(a.dataset.view));
  });
  // 站点选择按钮在 renderSiteBtns() 里逐个绑定
  $('btnLogout').addEventListener('click', doLogout);
  $('uiReload').addEventListener('click', () => location.reload());
  checkUiVersion();
  setInterval(checkUiVersion, 15000);

  // 站点设置弹窗
  $('btnSiteEdit').addEventListener('click', openSiteModal);
  $('siteModalClose').addEventListener('click', closeSiteModal);
  $('siteCancel').addEventListener('click', closeSiteModal);
  $('siteSave').addEventListener('click', saveSiteModal);
  $('siteModal').addEventListener('click', (e) => {
    if (e.target.id === 'siteModal') closeSiteModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('siteModal').hidden) closeSiteModal();
  });
  let savedView = 'console';
  try { savedView = localStorage.getItem('oj.view') || 'console'; } catch (e) {}
  if (!document.getElementById('view-' + savedView)) savedView = 'console';
  switchView(savedView);

  try {
    const s = await (await fetch('/api/status')).json();
    (s.logs || []).forEach(appendLog);
    applyState(s);
  } catch (e) {}

  setInterval(tick, 1000);
  tick();
});
