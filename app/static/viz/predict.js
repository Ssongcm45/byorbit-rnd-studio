// 건조 결과 예측 패널 — 조건을 바꾸면 예상 수분·TPC·TDF·에너지가 바로 바뀌고, 결과마다 근거(문헌·실측·설비·가정)를 보인다.
// 계산은 서버(/api/viz/predict)가 한다(시험된 기준). 이 파일은 입력·표시만.
import {esc, fmt, h, makeApi, METHOD_COLOR, reducedMotion} from './common.js';

const BASE = '/api/viz/predict';
const DEBOUNCE = 80;
const METHODS = ['동결건조', '열풍건조', '진공건조', '분무건조', '자연건조'];
const COND_KEYS = ['temp_c', 'time_h', 'pressure_pa', 'air_velocity_ms', 'thickness_mm', 'outlet_c', 'residence_s', 'rh', 'initial_moisture', 'target_moisture'];
const TYPE_LABEL = {literature: '문헌', measured: '실측', equipment: '설비 사양', assumption: '가정'};
let uid = 0;

/** mountPredict(el, {api, method, project, byproduct, onChange, showMethod, openEvidence})
 *  → {setMethod(m), setConditions(partial), dispose()} */
export function mountPredict(el, opts = {}) {
  const {json} = makeApi(opts.api);
  const id = 'pr' + (++uid);
  const st = {method: opts.method || '열풍건조', byproduct: opts.byproduct || '', project: opts.project || '',
    models: null, values: {}, result: null, seq: 0, timer: null, ctimer: null, open: new Set(opts.openEvidence ? ['*'] : []), disposed: false};
  const inBv = !!el.closest('.bv');
  const root = h(`<section class="pr" aria-labelledby="${id}-t">
    <div class="pr-top">
      <div class="grow"><h2 id="${id}-t">건조 결과 예측</h2>
        <p class="sub">조건을 바꾸면 예상 결과가 바로 바뀝니다. 결과마다 '근거 보기'에서 식·파라미터·출처를 확인하세요.</p></div>
      <label class="small muted">부산물 <select class="inp pr-bp" aria-label="부산물"></select></label>
    </div>
    <div class="seg pr-methods" role="group" aria-label="건조 방식"${opts.showMethod === false ? ' hidden' : ''}></div>
    <div class="pr-summary info" aria-live="polite"></div>
    <div class="pr-layout">
      <div class="card pr-controls"><h3>공정 조건</h3><div class="pr-inputs"></div>
        <details class="pr-equip"><summary>내 설비 사양</summary><div class="pr-equip-body"></div></details></div>
      <div class="pr-outs" aria-live="polite"></div>
    </div>
    <p class="small muted pr-disc"></p>
  </section>`);
  const shell = inBv ? root : h('<div class="bv"></div>');
  if (!inBv) shell.appendChild(root);
  el.appendChild(shell);
  const $ = s => root.querySelector(s);

  // 방식 버튼
  for (const m of METHODS) {
    const b = h(`<button type="button" aria-pressed="false"><span class="swatch" style="background:${METHOD_COLOR[m]}"></span>${esc(m)}</button>`);
    b.dataset.m = m;
    b.addEventListener('click', () => api.setMethod(m));
    $('.pr-methods').appendChild(b);
  }
  $('.pr-bp').addEventListener('change', e => { st.byproduct = e.target.value; loadModels(true) });

  async function loadModels(keep) {
    const q = new URLSearchParams({method: st.method, byproduct: st.byproduct, project: st.project});
    try {
      const mdl = await json(`${BASE}/models?${q}`);
      if (st.disposed) return;
      st.models = mdl;
      const prev = st.values;
      st.values = {};
      for (const s of mdl.inputs) st.values[s.key] = keep && prev[s.key] !== undefined ? clamp(prev[s.key], s) : s.default;
      if (st.pending) { Object.assign(st.values, pick(st.pending, mdl.inputs)); st.pending = null }
      renderMethods(); renderBp(); renderInputs(); renderEquip();
      $('.pr-disc').textContent = mdl.disclaimer;
      run(true);
    } catch (e) { showErr(e) }
  }

  function renderMethods() {
    for (const b of root.querySelectorAll('.pr-methods button')) b.setAttribute('aria-pressed', String(b.dataset.m === st.method));
  }
  function renderBp() {
    const sel = $('.pr-bp');
    sel.innerHTML = st.models.byproducts.map(b => `<option${b === st.models.byproduct ? ' selected' : ''}>${esc(b)}</option>`).join('');
  }

  function renderInputs() {
    const box = $('.pr-inputs');
    box.innerHTML = '';
    const fit = st.models.fits?.drying;
    for (const s of st.models.inputs) {
      const iid = `${id}-${s.key}`;
      const hint = s.default_from ? `기본값: ${s.default_from}` : (s.key === 'temp_c' && fit && st.method !== '동결건조' && st.method !== '분무건조'
        ? `문헌 근거 범위 ${fit.range_c[0]}–${fit.range_c[1]} ℃` : '');
      const row = h(`<div class="pr-in">
        <label for="${iid}">${esc(s.label)} <span class="muted">(${esc(s.unit)})</span></label>
        <div class="pr-in-row">
          <input type="range" id="${iid}" min="${s.min}" max="${s.max}" step="${s.step}" value="${st.values[s.key]}" aria-describedby="${iid}-h">
          <input type="number" class="inp" min="${s.min}" max="${s.max}" step="${s.step}" value="${st.values[s.key]}" aria-label="${esc(s.label)} 숫자 입력">
        </div>
        <div class="small muted" id="${iid}-h">${esc(hint)}</div>
      </div>`);
      const [rng, num] = row.querySelectorAll('input');
      const set = (v, from) => {
        v = clamp(Number(v), s);
        if (!Number.isFinite(v)) return;
        st.values[s.key] = v;
        if (from !== rng) rng.value = v;
        if (from !== num) num.value = v;
        schedule();
      };
      rng.addEventListener('input', () => set(rng.value, rng));
      num.addEventListener('change', () => set(num.value, num));
      row.dataset.key = s.key;
      box.appendChild(row);
    }
  }

  function syncInputs() {
    for (const row of root.querySelectorAll('.pr-in')) {
      const v = st.values[row.dataset.key];
      for (const i of row.querySelectorAll('input')) i.value = v;
    }
  }

  function schedule() {
    clearTimeout(st.timer);
    st.timer = setTimeout(() => run(false), DEBOUNCE);
    clearTimeout(st.ctimer);
    st.ctimer = setTimeout(() => opts.onChange && opts.onChange(cond()), DEBOUNCE);
  }

  function cond() {
    const c = {};
    for (const k of COND_KEYS) if (st.values[k] !== undefined) c[k] = st.values[k];
    if (st.result?.stage) c.stage = st.result.stage;
    return c;
  }

  async function run() {
    const my = ++st.seq;
    root.classList.add('pr-busy');
    try {
      const r = await json(BASE, {method: 'POST', body: {method: st.method, byproduct: st.byproduct || null, project: st.project || null, inputs: st.values}});
      if (my !== st.seq || st.disposed) return;
      st.result = r;
      renderResult();
    } catch (e) { if (my === st.seq) showErr(e) }
    finally { if (my === st.seq) root.classList.remove('pr-busy') }
  }

  function showErr(e) {
    $('.pr-summary').innerHTML = `<span class="err">예측하지 못했습니다: ${esc(e.message || e)}</span>`;
  }

  function renderResult() {
    const r = st.result;
    const sm = r.summary;
    $('.pr-summary').innerHTML = `<b>${esc(sm.text)}</b>
      <span class="chips" style="display:inline-flex;margin-left:6px">${badge('literature', `${sm.literature_verified}/${sm.literature}`)}${badge('measured', sm.measured)}${badge('equipment', sm.equipment)}${badge('assumption', sm.assumption)}</span>
      <div class="small muted" style="margin-top:4px">${esc(r.disclaimer)} ${esc(r.privacy)}</div>`;
    const box = $('.pr-outs');
    // 근거 펼침 상태 보존
    for (const d of box.querySelectorAll('details.pr-ev')) d.open ? st.open.add(d.dataset.k) : st.open.delete(d.dataset.k);
    box.innerHTML = '';
    for (const o of r.outputs) box.appendChild(card(o));
  }

  function card(o) {
    const warn = o.warnings.filter(w => w.kind === 'extrapolation');
    const other = o.warnings.filter(w => w.kind !== 'extrapolation');
    const band = o.low !== null && o.low !== undefined && o.high !== null && (o.low !== o.value || o.high !== o.value)
      ? `<span class="pr-band">${fmt(o.low, 2)}–${fmt(o.high, 2)}</span>` : '';
    const main = o.status === 'qualitative'
      ? `<div class="pr-qual">${esc(o.qualitative)}</div>`
      : o.value === null ? `<div class="pr-val muted">값 없음</div>`
      : `<div class="pr-val"><b>${fmt(o.value, 2)}</b> <span class="u">${esc(o.unit)}</span> ${band}</div>`;
    const hl = o.headline ? `<div class="pr-hl">${esc(o.headline.label)}: ${o.headline.reachable
      ? `<b>${fmt(o.headline.value, 1)} h</b> <span class="pr-band">${fmt(o.headline.low, 1)}–${fmt(o.headline.high, 1)} h</span>`
      : '<b class="err">도달 못 함</b>'}</div>` : '';
    const sec = (o.secondary || []).map(s => `<li><span class="muted">${esc(s.label)}</span> ${typeof s.value === 'number' ? `<b>${fmt(s.value, 2)}</b>` : esc(s.value)}${s.low !== undefined && s.low !== null ? ` <span class="pr-band">${fmt(s.low, 2)}–${fmt(s.high, 2)}</span>` : ''} <span class="muted">${esc(s.unit || '')}</span></li>`).join('');
    const c = h(`<article class="card pr-card" data-key="${o.key}">
      <div class="row"><h3 class="grow" style="margin:0">${esc(o.label)}</h3>${o.status === 'qualitative' ? '<span class="pill">정성</span>' : ''}${warn.length ? '<span class="pill warn">외삽</span>' : ''}</div>
      <div class="small muted">${esc(o.value_label || '')}</div>
      ${main}${hl}
      ${sec ? `<ul class="pr-sec">${sec}</ul>` : ''}
      ${warn.map(w => `<div class="notice pr-warn" role="note"><b>외삽 — 근거 범위 밖</b> ${esc(w.text.replace(/^외삽 — 근거 범위 밖:\s*/, ''))}</div>`).join('')}
      ${other.map(w => `<div class="small pr-note ${w.kind === 'calibration' ? 'cal' : ''}">${esc(w.text)}</div>`).join('')}
      <div class="pr-charts"></div>
    </article>`);
    const charts = c.querySelector('.pr-charts');
    if (o.chart) charts.appendChild(chartBox('공정 중 변화', lineChart(o.chart, {kind: 'curve', key: o.key})));
    if (o.sensitivity) charts.appendChild(chartBox('온도 vs 결과', lineChart(o.sensitivity, {kind: 'sens', key: o.key}), o.sensitivity.note, o.sensitivity));
    else if (o.key === 'color') charts.appendChild(h(`<div class="small muted">온도별 차트 없음 — 정량 근거가 없어 그리지 않습니다.</div>`));
    c.appendChild(evidenceBlock(o));
    return c;
  }

  function evidenceBlock(o) {
    const open = st.open.has(o.key) || st.open.has('*');
    const rows = o.params.map(p => `<li class="pr-p">
      <div class="pr-p-h"><span class="pr-p-l">${esc(p.label)}</span>${p.role === 'reference' ? '<span class="pr-b derived">대조·참고</span>' : ''} <b class="pr-p-v">${esc(valStr(p.value))}</b> <span class="muted">${esc(p.unit || '')}</span>
        ${p.band ? `<span class="pr-band">폭 ${esc(valStr(p.band))}</span>` : ''}</div>
      <div>${evBadge(p.evidence)}${p.evidence.locator ? `<span class="small muted">${esc(p.evidence.locator)}</span>` : ''}</div>
      ${p.evidence.note ? `<div class="small pr-p-n">${esc(p.evidence.note)}</div>` : ''}${validityStr(p.evidence.validity)}</li>`).join('');
    const srcs = new Map();
    for (const p of o.params) if (p.evidence.type === 'literature' && p.evidence.doi) {
      const s = srcs.get(p.evidence.doi) || {ev: p.evidence, loc: new Set()};
      if (p.evidence.locator) s.loc.add(p.evidence.locator);
      srcs.set(p.evidence.doi, s);
    }
    const cites = [...srcs.values()].map(({ev, loc}) => `<li>${esc(ev.citation)} <a href="https://doi.org/${encodeURI(ev.doi)}" target="_blank" rel="noopener">doi:${esc(ev.doi)}</a>
      ${ev.verified ? `<span class="pill ok">DOI 확인 ${esc(ev.verified_at || '')}</span>` : '<span class="pill warn">DOI 미확인</span>'}
      <div class="small muted">읽은 곳: ${esc([...loc].join(' · '))}${ev.read ? ' — ' + esc(ev.read) : ''}</div></li>`).join('');
    const cal = o.calibration;
    const calHtml = !cal ? '' : `<h4>실측 보정</h4><p class="small">${cal.applied ? `적용함 — 배율 <b>${fmt(cal.factor, 3)}</b>, ${esc(cal.message)}` : esc(cal.message)}</p>
      ${cal.how ? `<p class="small muted">${esc(cal.how)}</p>` : ''}
      ${cal.points && cal.points.length ? `<table><thead><tr><th>시료</th><th class="num">온도</th><th class="num">시간</th><th class="num">실측</th><th class="num">보정 후 예측</th><th class="num">잔차</th></tr></thead><tbody>
        ${cal.points.map(p => `<tr><td>${esc(p.sample)}</td><td class="num">${fmt(p.temp_c, 1)} ℃</td><td class="num">${fmt(p.time_h, 1)} h</td>
          <td class="num">${p.tpc !== undefined ? fmt(p.tpc, 2) : fmt(p.moist_final, 2) + '%'}</td><td class="num">${p.pred_tpc !== undefined ? fmt(p.pred_tpc, 2) : fmt(p.pred_final, 2) + '%'}</td>
          <td class="num">${fmt(p.residual, 3)}</td></tr>`).join('')}</tbody></table>` : ''}`;
    const d = h(`<details class="pr-ev" data-k="${o.key}"${open ? ' open' : ''}><summary>근거 보기</summary>
      <h4>모델</h4><p class="small">${esc(o.formula.model || '')}</p>
      <pre class="pr-f">${esc(o.formula.text)}</pre>
      ${o.formula.latex ? `<details class="small"><summary>LaTeX</summary><code class="pr-tex">${esc(o.formula.latex)}</code></details>` : ''}
      <h4>파라미터</h4>
      <ul class="pr-plist">${rows}</ul>
      ${calHtml}
      ${cites ? `<h4>인용 문헌</h4><ul class="pr-cites">${cites}</ul>` : '<p class="small muted">이 결과에는 문헌 근거가 없습니다(가정·실측·설비만).</p>'}
    </details>`);
    d.addEventListener('toggle', () => { st.open.delete('*'); d.open ? st.open.add(o.key) : st.open.delete(o.key) });
    return d;
  }

  // ---------------------------------------------------------------- 설비 사양
  function renderEquip() {
    const box = $('.pr-equip-body');
    const eq = st.models.equipment;
    box.innerHTML = '';
    const f = h(`<form class="pr-eqf"><p class="small muted">예측의 비에너지 계산에 씁니다. 파일: config/equipment.json</p><div class="pr-eqgrid"></div>
      <div class="row"><button class="btn sm primary" type="submit">저장</button><span class="small pr-eqmsg" role="status"></span></div></form>`);
    const g = f.querySelector('.pr-eqgrid');
    for (const s of eq) {
      const iid = `${id}-eq-${s.key}`;
      g.appendChild(h(`<label for="${iid}" class="small">${esc(s.label)} <span class="muted">(${esc(s.unit)})</span>
        <input class="inp" id="${iid}" name="${s.key}" type="number" step="any" min="${s.min}" max="${s.max}" value="${s.value}">
        <span class="muted">${s.edited_at ? '내 입력 ' + esc(s.edited_at) : '일반 사양(가정)'}</span></label>`));
    }
    f.addEventListener('submit', async e => {
      e.preventDefault();
      const values = {};
      for (const i of f.querySelectorAll('input')) values[i.name] = Number(i.value);
      const msg = f.querySelector('.pr-eqmsg');
      try {
        const r = await json(`${BASE}/equipment`, {method: 'POST', body: {method: st.method, values}});
        st.models.equipment = r.equipment[st.method];
        renderEquip();
        $('.pr-eqmsg').textContent = '저장했습니다.';
        run();
      } catch (ex) { msg.textContent = ex.message; msg.className = 'small err pr-eqmsg' }
    });
    box.appendChild(f);
  }

  const api = {
    setMethod(m) {
      if (!METHODS.includes(m) || m === st.method && st.models) return;
      st.method = m;
      loadModels(false);
    },
    setConditions(partial = {}) {
      if (!st.models || st.models.method !== st.method) { st.pending = {...(st.pending || {}), ...partial}; return }
      Object.assign(st.values, pick(partial, st.models.inputs));
      syncInputs();
      run();
    },
    dispose() {
      st.disposed = true;
      clearTimeout(st.timer); clearTimeout(st.ctimer);
      shell.remove();
    },
    get state() { return {method: st.method, values: {...st.values}, result: st.result} },
  };
  loadModels(false);
  return api;
}

function pick(partial, specs) {
  const out = {};
  for (const s of specs) {
    const v = Number(partial[s.key]);
    if (partial[s.key] !== undefined && partial[s.key] !== null && Number.isFinite(v)) out[s.key] = clamp(v, s);
  }
  return out;
}
function clamp(v, s) { return Math.min(s.max, Math.max(s.min, v)) }

function valStr(v) {
  if (v === null || v === undefined) return '-';
  if (Array.isArray(v)) return v.map(x => fmt(x, 4)).join('–');
  if (typeof v === 'object') return Object.entries(v).map(([k, x]) => `${k}: ${fmt(x, 4)}`).join(' · ');
  return typeof v === 'number' ? fmt(v, 4) : String(v);
}
function validityStr(v) {
  if (!v) return '';
  const parts = [];
  const nm = {temp_c: '온도 ℃', air_velocity_ms: '풍속 m/s', thickness_mm: '두께 mm', pressure_pa: '압력 Pa'};
  for (const [k, r] of Object.entries(v)) parts.push(k === 'byproduct' ? `대상: ${r}` : `${nm[k] || k} ${r[0]}–${r[1]}`);
  return parts.length ? `<div class="muted">유효 범위: ${esc(parts.join(' · '))}</div>` : '';
}
function badge(type, n) {
  return `<span class="pr-b ${type}">${TYPE_LABEL[type]} ${esc(n)}</span>`;
}
function evBadge(ev) {
  if (ev.type === 'literature') return `<span class="pr-b literature">문헌${ev.verified ? ' ✓DOI확인' : ''}</span>${ev.derived ? '<span class="pr-b derived">유도값</span>' : ''}`;
  if (ev.type === 'measured') return `<span class="pr-b measured">실측 n=${esc(ev.n)}</span>`;
  if (ev.type === 'equipment') return `<span class="pr-b equipment">설비 사양</span>`;
  return `<span class="pr-b assumption">가정</span>`;
}

function chartBox(title, svg, note, d) {
  const b = h(`<figure class="pr-chart"><figcaption class="small muted">${esc(title)}</figcaption></figure>`);
  b.appendChild(svg);
  if (d) {
    const lg = ['<i class="k cur"></i>현재', '<i class="k band"></i>불확실 폭'];
    if ((d.measured || []).length) lg.push('<i class="k meas"></i>실측');
    if ((d.literature || []).length) lg.push('<i class="k lit"></i>문헌');
    if (d.band_lit) lg.push('<i class="k litband"></i>문헌·가정 범위');
    b.appendChild(h(`<div class="pr-legend small muted">${lg.map(x => `<span>${x}</span>`).join('')}</div>`));
  }
  if (note) b.appendChild(h(`<div class="small muted pr-cnote">${esc(note)}</div>`));
  return b;
}

/** 작은 선 그래프(SVG). d.points = [[x, y, lo, hi], ...] */
function lineChart(d, {kind}) {
  const W = 320, H = 178, L = 40, R = 10, T = 20, B = 34;
  const pts = (d.points || []).filter(p => p[1] !== null && p[1] !== undefined);
  const extra = [...(d.measured || []), ...(d.literature || [])];
  const xs = pts.map(p => p[0]).concat(extra.map(m => m.x));
  const ys = pts.flatMap(p => [p[1], p[2], p[3]]).filter(v => v !== null && v !== undefined && Number.isFinite(v))
    .concat(extra.map(m => m.y));
  if (d.target !== undefined) ys.push(d.target);
  if (d.band_lit) ys.push(...d.band_lit);
  if (d.current && d.current[1] !== null) ys.push(d.current[1]);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('class', 'pr-svg');
  svg.setAttribute('role', 'img');
  if (!pts.length || !ys.length) {
    svg.setAttribute('aria-label', '그릴 값 없음');
    svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" class="pr-ax">이 조건에서 그릴 값이 없습니다(목표 미도달 등)</text>`;
    return svg;
  }
  let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(0, ...ys), y1 = Math.max(...ys) * 1.08;
  if (x1 === x0) x1 = x0 + 1;
  if (y1 <= y0) y1 = y0 + 1;
  const sx = x => L + (x - x0) / (x1 - x0) * (W - L - R);
  const sy = y => T + (1 - (y - y0) / (y1 - y0)) * (H - T - B);
  const path = arr => arr.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join('');
  let s = '';
  // 축·눈금
  for (const t of ticks(y0, y1, 4)) s += `<line x1="${L}" x2="${W - R}" y1="${sy(t)}" y2="${sy(t)}" class="pr-grid"/><text x="${L - 4}" y="${sy(t) + 3}" text-anchor="end" class="pr-ax">${fmt(t, 1)}</text>`;
  for (const t of ticks(x0, x1, 5)) s += `<text x="${sx(t)}" y="${H - B + 13}" text-anchor="middle" class="pr-ax">${fmt(t, 1)}</text>`;
  s += `<text x="${(L + W - R) / 2}" y="${H - 4}" text-anchor="middle" class="pr-ax">${esc(d.x_label || '')}</text>`;
  s += `<text x="${L - 30}" y="11" class="pr-ax">${esc(d.y_label || '')}</text>`;
  if (d.band_lit && d.band_lit[1] !== null) {
    const [a, b] = d.band_lit;
    s += `<rect x="${L}" width="${W - L - R}" y="${sy(Math.max(a, b))}" height="${Math.max(1.5, sy(Math.min(a, b)) - sy(Math.max(a, b)))}" class="pr-litband"><title>문헌·가정 범위 ${fmt(a, 2)}–${fmt(b, 2)}</title></rect>`;
  }
  // 불확실 폭
  const bandPts = pts.filter(p => p[2] !== null && p[2] !== undefined && p[3] !== null && p[3] !== undefined);
  if (bandPts.length > 1) {
    const up = bandPts.map(p => [p[0], Math.max(p[2], p[3])]), dn = bandPts.map(p => [p[0], Math.min(p[2], p[3])]).reverse();
    s += `<path d="${path(up)}${dn.map(p => `L${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join('')}Z" class="pr-bandfill"/>`;
  }
  s += `<path d="${path(pts)}" class="pr-line"/>`;
  if (d.target !== undefined) s += `<line x1="${L}" x2="${W - R}" y1="${sy(d.target)}" y2="${sy(d.target)}" class="pr-target"/><text x="${W - R}" y="${sy(d.target) - 3}" text-anchor="end" class="pr-ax">목표 ${fmt(d.target, 1)}</text>`;
  if (kind === 'curve' && d.time_h !== undefined && d.time_h !== null && d.time_h <= x1) s += `<line x1="${sx(d.time_h)}" x2="${sx(d.time_h)}" y1="${T}" y2="${H - B}" class="pr-now"/><text x="${sx(d.time_h) + (sx(d.time_h) > W - 70 ? -3 : 3)}" y="${T + 9}" text-anchor="${sx(d.time_h) > W - 70 ? 'end' : 'start'}" class="pr-ax">설정 ${fmt(d.time_h, 1)} h</text>`;
  for (const m of d.literature || []) s += `<path d="M${sx(m.x)},${sy(m.y) - 5}l5,5l-5,5l-5,-5z" class="pr-lit"><title>${esc(m.label)}</title></path>`;
  for (const m of d.measured || []) s += `<circle cx="${sx(m.x)}" cy="${sy(m.y)}" r="4.5" class="pr-meas"><title>실측 ${esc(m.label)}</title></circle>`;
  if (d.current && d.current[1] !== null && d.current[1] !== undefined) s += `<circle cx="${sx(d.current[0])}" cy="${sy(d.current[1])}" r="5" class="pr-cur"><title>현재 조건 ${fmt(d.current[0], 1)} → ${fmt(d.current[1], 2)}</title></circle>`;
  svg.innerHTML = s;
  const desc = `${d.y_label} 대 ${d.x_label}` + (d.current && d.current[1] !== null ? `, 현재 ${fmt(d.current[0], 1)}에서 ${fmt(d.current[1], 2)}` : '')
    + ((d.measured || []).length ? `, 실측 ${d.measured.length}점` : '');
  svg.setAttribute('aria-label', desc);
  if (!reducedMotion()) svg.classList.add('pr-anim');
  return svg;
}

function ticks(a, b, n) {
  const span = b - a, step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= step0) || step0;
  const out = [];
  for (let t = Math.ceil(a / step) * step; t <= b + 1e-9; t += step) out.push(+t.toFixed(10));
  return out;
}
