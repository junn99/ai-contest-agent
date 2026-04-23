'use strict';

// ── Telegram WebApp bootstrap ──────────────────────────────────────────────
const TG = window.Telegram?.WebApp;

function initTelegram() {
  if (!TG) return;
  TG.ready();
  TG.expand();
  const tp = TG.themeParams;
  if (tp.bg_color)       document.documentElement.style.setProperty('--tg-bg',       tp.bg_color);
  if (tp.text_color)     document.documentElement.style.setProperty('--tg-text',     tp.text_color);
  if (tp.button_color)   document.documentElement.style.setProperty('--tg-btn',      tp.button_color);
  if (tp.hint_color)     document.documentElement.style.setProperty('--tg-hint',     tp.hint_color);
}

// ── Prefs (localStorage) ───────────────────────────────────────────────────
const PREFS_KEY = 'infoke_prefs';

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY) || '{}'); }
  catch { return {}; }
}

function savePrefs(prefs) {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch {}
}

// ── Data fetching ──────────────────────────────────────────────────────────
async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

function normalizeAnalysis(a) {
  if (!a) return null;
  return {
    ...a,
    approach: a.approach ?? a.suggested_approach ?? '',
    submission: a.submission ?? a.required_deliverables ?? [],
    keywords: a.keywords ?? [],
  };
}

async function loadData() {
  // Prefer split data files; fall back to unified mock.json
  const isDev = new URLSearchParams(window.location.search).has('dev');
  try {
    const [contestsRaw, analysesRaw, artifactsRaw] = await Promise.all([
      fetchJSON('./data/contests.json'),
      fetchJSON('./data/analyses.json').catch(() => ({ analyses: [] })),
      fetchJSON('./data/artifacts.json').catch(() => ({ artifacts: [] })),
    ]);

    const analysisMap = {};
    for (const a of (analysesRaw.analyses ?? [])) analysisMap[a.contest_id] = normalizeAnalysis(a);

    const artifactMap = {};
    for (const a of (artifactsRaw.artifacts ?? [])) artifactMap[a.contest_id] = a;

    const contests = (contestsRaw.contests ?? contestsRaw).map(c => ({
      ...c,
      analysis: analysisMap[c.id] ?? normalizeAnalysis(c.analysis) ?? null,
      artifact: artifactMap[c.id] ?? c.artifact ?? null,
    }));

    return contests;
  } catch {
    // Fall back to mock data (dev mode only loads _dev/mock.json)
    const mockPath = isDev ? './data/_dev/mock.json' : './data/mock.json';
    console.warn('[infoke] using mock data');
    const mock = await fetchJSON(mockPath);
    const contests = mock.contests ?? [];
    return contests.map(c => ({ ...c, analysis: normalizeAnalysis(c.analysis) }));
  }
}

// ── Card rendering ─────────────────────────────────────────────────────────
function dDayLabel(d) {
  if (d === 0) return 'D-Day';
  if (d < 0)  return '마감';
  return `D-${d}`;
}

function roiBadgeClass(roi) {
  if (roi >= 8) return 'roi-high';
  if (roi >= 5) return 'roi-mid';
  return 'roi-low';
}

function renderCard(template, contest) {
  const card = template.content.cloneNode(true);
  const root = card.querySelector('[data-card-id]') ?? card.firstElementChild;

  // identity
  if (root) root.setAttribute('data-card-id', contest.id);
  const set = (attr, val) => {
    card.querySelectorAll(`[${attr}]`).forEach(el => {
      el.setAttribute(attr, val ?? '');
      if (el.tagName === 'SPAN' || el.tagName === 'P' || el.tagName === 'DIV' || el.tagName === 'H3') {
        el.textContent = val ?? '';
      }
    });
  };

  // data-roi / data-d-day / data-category on wrapper
  if (root) {
    root.dataset.roi      = contest.roi ?? 0;
    root.dataset.dDay     = contest.d_day ?? 999;
    root.dataset.category = contest.category ?? '';
  }

  // text fields (T1a uses these named slots)
  const slots = {
    '[data-title]':       contest.title,
    '[data-host]':        contest.host,
    '[data-category]':    contest.category,
    '[data-deadline]':    contest.deadline,
    '[data-d-day]':       dDayLabel(contest.d_day),
    '[data-prize]':       contest.prize_label ?? `${(contest.prize ?? 0).toLocaleString()}원`,
    '[data-roi]':         `ROI ${contest.roi?.toFixed(1) ?? '-'}`,
    '[data-difficulty]':  contest.difficulty ?? '-',
  };
  for (const [sel, val] of Object.entries(slots)) {
    card.querySelectorAll(sel).forEach(el => { el.textContent = val ?? ''; });
  }

  // ROI badge colour
  card.querySelectorAll('[data-roi-badge]').forEach(el => {
    el.className = (el.className + ' ' + roiBadgeClass(contest.roi ?? 0)).trim();
  });

  // Analysis details (inside <details>)
  const a = contest.analysis;
  if (a) {
    card.querySelectorAll('[data-analysis-approach]').forEach(el => { el.textContent = a.approach ?? ''; });
    card.querySelectorAll('[data-analysis-keywords]').forEach(el => {
      el.textContent = (a.keywords ?? []).join(', ');
    });
    card.querySelectorAll('[data-analysis-submission]').forEach(el => {
      el.innerHTML = (a.submission ?? []).map(s => `<li>${s}</li>`).join('');
    });
  }

  // Action buttons
  const pdfBtn      = card.querySelector('[data-action-pdf]');
  const linkBtn     = card.querySelector('[data-action-link]');
  const generateBtn = card.querySelector('[data-action-generate]');

  if (pdfBtn) {
    pdfBtn.addEventListener('click', () => {
      sendAction('pdf', contest.id);
    });
  }
  if (linkBtn) {
    linkBtn.addEventListener('click', () => {
      if (TG) TG.openLink(contest.url);
      else window.open(contest.url, '_blank');
    });
  }
  if (generateBtn) {
    const hasDone = contest.artifact?.status === 'done';
    if (hasDone) {
      generateBtn.setAttribute('disabled', '');
      generateBtn.title = '보고서 이미 생성됨';
    }
    generateBtn.addEventListener('click', () => {
      if (hasDone) return;
      if (window.confirm('보고서를 생성할까요? AI 분석 비용이 발생합니다.')) {
        sendAction('generate', contest.id);
      }
    });
  }

  return card;
}

function sendAction(action, contestId) {
  const payload = JSON.stringify({ action, contest_id: contestId });
  if (TG) {
    TG.sendData(payload);
  } else {
    // Dev fallback
    console.info('[sendAction]', payload);
  }
}

// ── Filter + sort state ────────────────────────────────────────────────────
let allContests = [];
let filterState = { roi: 0, keyword: '', category: '', imminent: false, sort: 'roi' };

function applyFilters() {
  let result = allContests.filter(c => {
    if (filterState.roi > 0 && (c.roi ?? 0) < filterState.roi) return false;
    if (filterState.keyword) {
      const kw = filterState.keyword.toLowerCase();
      const haystack = [c.title, c.host, ...(c.analysis?.keywords ?? [])].join(' ').toLowerCase();
      if (!haystack.includes(kw)) return false;
    }
    if (filterState.category && c.category !== filterState.category) return false;
    if (filterState.imminent && (c.d_day ?? 999) > 7) return false;
    return true;
  });

  const sortFns = {
    roi:      (a, b) => (b.roi ?? 0) - (a.roi ?? 0),
    deadline: (a, b) => (a.d_day ?? 999) - (b.d_day ?? 999),
    prize:    (a, b) => (b.prize ?? 0) - (a.prize ?? 0),
  };
  result.sort(sortFns[filterState.sort] ?? sortFns.roi);
  return result;
}

// ── Chart.js ───────────────────────────────────────────────────────────────
let roiChart = null;
let catChart = null;

function renderCharts(contests) {
  if (typeof Chart === 'undefined') return;

  const roiCtx = document.querySelector('[data-chart-roi]');
  const catCtx = document.querySelector('[data-chart-category]');

  if (roiCtx) {
    const bins   = ['0-2', '2-4', '4-6', '6-8', '8-10'];
    const counts = [0, 0, 0, 0, 0];
    for (const c of contests) {
      const r = c.roi ?? 0;
      const idx = Math.min(Math.floor(r / 2), 4);
      counts[idx]++;
    }
    if (roiChart) roiChart.destroy();
    roiChart = new Chart(roiCtx, {
      type: 'bar',
      data: {
        labels: bins,
        datasets: [{ label: 'ROI 분포', data: counts, backgroundColor: '#5865f2' }],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
      },
    });
  }

  if (catCtx) {
    const catMap = {};
    for (const c of contests) catMap[c.category] = (catMap[c.category] ?? 0) + 1;
    const labels = Object.keys(catMap);
    const data   = labels.map(l => catMap[l]);
    const colors = ['#5865f2', '#57f287', '#fee75c', '#ed4245', '#eb459e', '#9b59b6'];
    if (catChart) catChart.destroy();
    catChart = new Chart(catCtx, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{ data, backgroundColor: colors.slice(0, labels.length) }],
      },
      options: { responsive: true, plugins: { legend: { position: 'bottom' } } },
    });
  }
}

// ── DOM rendering ──────────────────────────────────────────────────────────
function rerenderList() {
  const cardList = document.querySelector('[data-card-list]');
  const template = document.querySelector('[data-card-template]');
  if (!cardList || !template) return;

  const filtered = applyFilters();
  cardList.innerHTML = '';

  if (filtered.length === 0) {
    cardList.innerHTML = '<p class="empty-state">조건에 맞는 공모전이 없습니다.</p>';
    return;
  }

  const frag = document.createDocumentFragment();
  for (const c of filtered) frag.appendChild(renderCard(template, c));
  cardList.appendChild(frag);

  renderCharts(filtered);
}

// ── Filter control wiring ──────────────────────────────────────────────────
function wireFilters() {
  const prefs = loadPrefs();

  const roiEl      = document.querySelector('[data-filter-roi]');
  const kwEl       = document.querySelector('[data-filter-keyword]');
  const catEl      = document.querySelector('[data-filter-category]');
  const imminentEl = document.querySelector('[data-filter-imminent]');
  const sortEl     = document.querySelector('[data-sort]');

  // Restore prefs
  if (roiEl && prefs.roi != null)          { roiEl.value     = prefs.roi;      filterState.roi      = +prefs.roi; }
  if (kwEl  && prefs.keyword)              { kwEl.value      = prefs.keyword;  filterState.keyword  = prefs.keyword; }
  if (catEl && prefs.category)             { catEl.value     = prefs.category; filterState.category = prefs.category; }
  if (imminentEl && prefs.imminent)        { imminentEl.checked = true;        filterState.imminent = true; }
  if (sortEl && prefs.sort)                { sortEl.value    = prefs.sort;     filterState.sort     = prefs.sort; }

  function save() {
    savePrefs({
      roi:      filterState.roi,
      keyword:  filterState.keyword,
      category: filterState.category,
      imminent: filterState.imminent,
      sort:     filterState.sort,
    });
  }

  roiEl?.addEventListener('change', e => {
    filterState.roi = +e.target.value;
    save(); rerenderList();
  });
  kwEl?.addEventListener('input', e => {
    filterState.keyword = e.target.value.trim();
    save(); rerenderList();
  });
  catEl?.addEventListener('change', e => {
    filterState.category = e.target.value;
    save(); rerenderList();
  });
  imminentEl?.addEventListener('change', e => {
    filterState.imminent = e.target.checked;
    save(); rerenderList();
  });
  sortEl?.addEventListener('change', e => {
    filterState.sort = e.target.value;
    save(); rerenderList();
  });
}

// ── Error UI ───────────────────────────────────────────────────────────────
function showError(msg) {
  const root = document.querySelector('[data-app-root]') ?? document.body;
  const div = document.createElement('div');
  div.className = 'error-banner';
  div.textContent = msg;
  root.prepend(div);
}

// ── Entry point ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  initTelegram();
  wireFilters();

  try {
    allContests = await loadData();
    rerenderList();
  } catch (err) {
    console.error('[infoke] 데이터 로드 실패:', err);
    showError('공모전 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.');
  }
});
