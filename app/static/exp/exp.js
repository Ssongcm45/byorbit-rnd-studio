// 내 실험 — 공정 흐름을 고치고, 내 조건·결과를 넣고, 예측과 비교·보정한다.
//   import {mountExperiment} from '/static/exp/exp.js';
//   mountExperiment(el, {api, toast, project, openDrying, openStats})  → {open(expId), select(tab), refresh(), setProject(p), dispose()}
//   openStats(expId): '통계 분석' 단추. 없으면 window에 'byorbit:open-stats' 이벤트(detail.expId, preventDefault로 받음), 받는 곳이 없으면 단독 페이지를 연다.
// 계산은 모두 서버(/api/exp — 시험된 기준)가 한다. 이 파일은 입력·표시만. 밖으로 보내는 요청은 없다.
import {esc, fmt, h, makeApi, METHOD_COLOR, reducedMotion} from '../viz/common.js';

const B = '/api/exp';
const TABS = [['flow', '공정 흐름'], ['data', '실험 데이터'], ['result', '결과·보정']];
const TYPE_LABEL = {literature: '문헌', measured: '실측', equipment: '설비 사양', assumption: '가정', input: '내 입력'};
const GROUP_COLOR = {'원료': 'var(--v-earth)', '전처리': 'var(--v-accent)', '분말화': 'var(--v-ok)', '추출': 'var(--m-vd)', '저장': 'var(--m-unk)'};
const ROLE_LABEL = {ignore: '무시', label: '런 이름', date: '날짜', note: '비고', condition: '조건', value: '실측값'};
let uid = 0;

function ensureCss() {
  for (const [k, href] of [['bvCss', '../viz/viz.css'], ['xpCss', './exp.css']]) {
    if (document.querySelector(`link[data-${k === 'bvCss' ? 'bv-css' : 'xp-css'}]`)) continue;
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = new URL(href, import.meta.url).href;
    l.dataset[k] = '1';
    document.head.appendChild(l);
  }
}

const store = {
  get(k) { try { return JSON.parse(localStorage.getItem('xp:' + k) || 'null') } catch { return null } },
  set(k, v) { try { localStorage.setItem('xp:' + k, JSON.stringify(v)) } catch { /* 저장 못 해도 화면은 그대로 */ } },
};

export function mountExperiment(el, opts = {}) {
  ensureCss();
  const {json} = makeApi(opts.api);
  const toast = opts.toast || (m => console.info(m));
  const id = 'xp' + (++uid);
  const st = {list: [], exp: null, cat: null, templates: [], tab: opts.tab || 'flow', sim: null, sel: null, cmp: null, sens: null,
    cal: null, sug: null, imp: null, parityTarget: 'moisture', disposed: false, paramTimer: null, open: new Set(opts.openEvidence ? ['*'] : []),
    project: opts.project || ''};
  const inBv = !!el.closest('.bv');
  const root = h(`<section class="pr xp" aria-labelledby="${id}-t">
    <div class="xp-top">
      <div class="grow"><h2 id="${id}-t">내 실험</h2>
        <p class="sub small muted">공정 흐름(원료 → 전처리 → 건조 → 분말화 → 추출 …)을 내 방식대로 고치고, 내가 잰 값을 넣어 예측과 비교·보정합니다. 모든 계산은 이 컴퓨터 안에서만 합니다.</p></div>
      <div class="xp-pick">
        <label class="sr-only" for="${id}-sel">실험 고르기</label>
        <select class="inp xp-sel" id="${id}-sel"></select>
        <span class="xp-conf"></span>
        <button class="btn sm xp-newbtn" type="button" aria-expanded="false">새 실험</button>
        <button class="btn sm xp-edit" type="button" aria-expanded="false" aria-controls="${id}-editf">이름·등급</button>
        <button class="btn sm xp-del" type="button" aria-expanded="false" aria-controls="${id}-delf">지우기</button>
        <button class="btn sm xp-stats" type="button" title="이 실험의 런으로 회귀분석·t검정·논문용 표와 그림 만들기">통계 분석</button>
      </div>
    </div>
    <form class="card xp-new" hidden aria-label="새 실험 만들기">
      <label>실험 이름 <input class="inp" name="name" required maxlength="80" placeholder="예: 사과박 열풍 온도 비교 1차"></label>
      <label>흐름 틀 <select class="inp" name="template"></select></label>
      <label>부산물 <input class="inp" name="byproduct" value="사과박" maxlength="40"></label>
      <label>보안 등급 <select class="inp" name="conf"><option>내부</option><option>일반</option><option>기밀</option></select></label>
      <div class="row"><button class="btn primary sm" type="submit">만들기</button><button class="btn sm xp-cancel" type="button">취소</button></div>
      <p class="small muted" style="grid-column:1/-1;margin:0">틀은 복사되어 이 실험만의 흐름이 됩니다. 단계를 더하고·빼고·순서를 바꾸고·끌 수 있습니다. '기밀' 실험도 밖으로 나가지 않습니다(이 앱에는 실험 자료를 보내는 길이 없음).</p>
    </form>
    <form class="card xp-new xp-editf" id="${id}-editf" hidden aria-label="실험 이름·보안 등급 바꾸기">
      <label>실험 이름 <input class="inp" name="name" required maxlength="80"></label>
      <label>보안 등급 <select class="inp" name="conf"><option>내부</option><option>일반</option><option>기밀</option></select></label>
      <div class="row"><button class="btn primary sm" type="submit">저장</button><button class="btn sm xp-editcancel" type="button">취소</button></div>
      <p class="small muted xp-editmsg" style="grid-column:1/-1;margin:0">Esc로 닫습니다. '기밀'로 바꾸면 내려받은 표·그림을 다룰 때 등급에 맞게 다루세요.</p>
    </form>
    <div class="card xp-delf" id="${id}-delf" hidden role="group" aria-label="실험 지우기 확인">
      <p class="xp-delmsg" style="margin:0 0 8px"></p>
      <div class="row"><button class="btn sm danger xp-delok" type="button">지우기</button><button class="btn sm xp-delcancel" type="button">취소</button></div>
    </div>
    <div class="tabs" role="tablist" aria-label="내 실험">${TABS.map(([k, l]) => `<button role="tab" id="${id}-tab-${k}" aria-controls="${id}-p-${k}" aria-selected="false" tabindex="-1" data-tab="${k}">${l}</button>`).join('')}</div>
    ${TABS.map(([k]) => `<div role="tabpanel" id="${id}-p-${k}" aria-labelledby="${id}-tab-${k}" data-panel="${k}" hidden></div>`).join('')}
    <div class="sr-only" aria-live="polite" id="${id}-live"></div>
  </section>`);
  const shell = inBv ? root : h('<div class="bv"></div>');
  if (!inBv) shell.appendChild(root);
  el.appendChild(shell);
  const $ = s => root.querySelector(s);
  const panel = k => root.querySelector(`[data-panel="${k}"]`);
  const say = m => { $(`#${id}-live`).textContent = m };
  const fail = e => { toast(e.message || String(e)); say(e.message || String(e)) };

  // ---------------------------------------------------------------- 머리: 실험 고르기·만들기
  $('.xp-sel').addEventListener('change', e => open(e.target.value));
  $('.xp-newbtn').addEventListener('click', () => toggleNew());
  $('.xp-cancel').addEventListener('click', () => toggleNew(false));
  function toggleNew(on) {
    const f = $('.xp-new');
    on = on ?? f.hidden;
    f.hidden = !on;
    $('.xp-newbtn').setAttribute('aria-expanded', String(on));
    if (on) f.querySelector('[name=name]').focus();
  }
  $('.xp-new').addEventListener('submit', async e => {
    e.preventDefault();
    const f = e.target;
    try {
      const x = await json(`${B}/experiments`, {method: 'POST', body: {name: f.name.value, template_id: f.template.value || null,
        byproduct: f.byproduct.value || null, confidentiality: f.conf.value}});
      f.reset(); toggleNew(false);
      toast(`'${x.name}' 실험을 만들었습니다.`);
      await loadList(); open(x.exp_id);
    } catch (ex) { fail(ex) }
  });
  // 이름·등급 바꾸기, 지우기 확인 — 창(prompt·confirm) 대신 제자리 양식. Esc로 닫고 닫으면 단추로 초점을 돌린다.
  function toggleInline(sel, btnSel, on, focusSel) {
    const f = $(sel), b = $(btnSel);
    on = on ?? f.hidden;
    if (on) { for (const [s2, b2] of [['.xp-editf', '.xp-edit'], ['.xp-delf', '.xp-del']]) if (s2 !== sel) { $(s2).hidden = true; $(b2).setAttribute('aria-expanded', 'false') } }
    f.hidden = !on;
    b.setAttribute('aria-expanded', String(on));
    if (on) f.querySelector(focusSel)?.focus(); else b.focus();
    return on;
  }
  $('.xp-edit').addEventListener('click', () => {
    if (!st.exp) return;
    const f = $('.xp-editf');
    if (f.hidden) { f.name.value = st.exp.name; f.conf.value = st.exp.confidentiality }
    toggleInline('.xp-editf', '.xp-edit', undefined, '[name=name]');
  });
  $('.xp-editcancel').addEventListener('click', () => toggleInline('.xp-editf', '.xp-edit', false));
  $('.xp-editf').addEventListener('keydown', e => { if (e.key === 'Escape') { e.preventDefault(); toggleInline('.xp-editf', '.xp-edit', false) } });
  $('.xp-editf').addEventListener('submit', async e => {
    e.preventDefault();
    const f = e.target;
    try {
      await json(`${B}/experiments/${st.exp.exp_id}`, {method: 'PUT', body: {name: f.name.value, confidentiality: f.conf.value}});
      toggleInline('.xp-editf', '.xp-edit', false);
      say('이름·보안 등급을 저장했습니다.');
      await loadList(); open(st.exp.exp_id);
    } catch (ex) { fail(ex) }
  });
  $('.xp-del').addEventListener('click', () => {
    if (!st.exp) return;
    $('.xp-delmsg').textContent = `'${st.exp.name}' 실험과 런 ${st.exp.runs.length}개를 지울까요? 지운 기록은 변경 기록에 남습니다.`;
    toggleInline('.xp-delf', '.xp-del', undefined, '.xp-delcancel');
  });
  $('.xp-delcancel').addEventListener('click', () => toggleInline('.xp-delf', '.xp-del', false));
  $('.xp-delf').addEventListener('keydown', e => { if (e.key === 'Escape') { e.preventDefault(); toggleInline('.xp-delf', '.xp-del', false) } });
  $('.xp-delok').addEventListener('click', async () => {
    if (!st.exp) return;
    try {
      await json(`${B}/experiments/${st.exp.exp_id}`, {method: 'DELETE'});
      $('.xp-delf').hidden = true; $('.xp-del').setAttribute('aria-expanded', 'false');
      toast('실험을 지웠습니다.'); say('실험을 지웠습니다.');
      st.exp = null; await loadList(); await open(st.list[0]?.exp_id); $('.xp-sel').focus();
    } catch (ex) { fail(ex) }
  });

  // 통계 분석 열기: 호스트가 openStats를 주면 그것을, 아니면 'byorbit:open-stats' 이벤트(호스트가 preventDefault로 받음),
  // 아무도 받지 않으면(단독 페이지) 통계 분석 단독 페이지를 새 탭으로 연다.
  $('.xp-stats').addEventListener('click', () => {
    const expId = st.exp?.exp_id;
    if (!expId) { toast('먼저 실험을 고르거나 만드세요.'); return }
    if (opts.openStats) { opts.openStats(expId); return }
    const ev = new CustomEvent('byorbit:open-stats', {detail: {expId}, cancelable: true});
    if (window.dispatchEvent(ev)) window.open(new URL(`../stats/dev.html?exp=${encodeURIComponent(expId)}`, import.meta.url), '_blank', 'noopener');
  });

  async function loadList() {
    const [l, t] = await Promise.all([json(`${B}/experiments`), st.templates.length ? {templates: st.templates} : json(`${B}/templates`)]);
    st.list = l.experiments; st.templates = t.templates;
    $('.xp-sel').innerHTML = st.list.length ? st.list.map(x => `<option value="${x.exp_id}">${esc(x.name)}${x.confidentiality === '기밀' ? ' (기밀)' : ''} — 런 ${x.n_runs}</option>`).join('')
      : '<option value="">실험이 없습니다 — 새 실험을 만드세요</option>';
    $('.xp-new [name=template]').innerHTML = st.templates.map(t => `<option value="${t.wf_id}">${esc(t.name)}</option>`).join('');
  }

  async function open(expId) {
    if (!expId) { st.exp = null; renderAll(); return }
    try {
      st.exp = await json(`${B}/experiments/${expId}`);
      $('.xp-sel').value = expId;
      st.cmp = st.sens = st.cal = st.sug = st.imp = null;
      for (const [s2, b2] of [['.xp-editf', '.xp-edit'], ['.xp-delf', '.xp-del']]) { $(s2).hidden = true; $(b2).setAttribute('aria-expanded', 'false') }
      if (!st.sel || !st.exp.flow.steps.some(s => s.key === st.sel)) st.sel = (st.exp.flow.steps.find(s => s.type === 'dry') || st.exp.flow.steps[0]).key;
      await simulate();
      renderAll();
    } catch (ex) { fail(ex) }
  }

  function renderHead() {
    const x = st.exp;
    const c = $('.xp-conf');
    c.innerHTML = !x ? '' : x.confidentiality === '기밀' ? '<span class="pill secret" title="기밀 — 이 컴퓨터 밖으로 보내지 않음">기밀</span>'
      : `<span class="pill ${x.confidentiality === '내부' ? 'internal' : ''}">${esc(x.confidentiality)}</span>`;
    if (x && x.calibration_applied) c.innerHTML += ' <span class="pill ok">보정에 적용됨</span>';
    $('.xp-edit').disabled = $('.xp-del').disabled = !x;
  }

  // ---------------------------------------------------------------- 탭
  root.querySelectorAll('[role=tab]').forEach((b, i, all) => {
    b.onclick = () => select(b.dataset.tab);
    b.onkeydown = ev => {
      const d = ev.key === 'ArrowRight' ? 1 : ev.key === 'ArrowLeft' ? -1 : 0;
      if (d) { const n = all[(i + d + all.length) % all.length]; n.focus(); select(n.dataset.tab) }
    };
  });
  function select(k) {
    if (!TABS.some(t => t[0] === k)) k = 'flow';
    st.tab = k;
    root.querySelectorAll('[role=tab]').forEach(b => { const on = b.dataset.tab === k; b.setAttribute('aria-selected', on); b.tabIndex = on ? 0 : -1 });
    root.querySelectorAll('[role=tabpanel]').forEach(p => p.hidden = p.dataset.panel !== k);
    renderTab();
  }
  function renderAll() { renderHead(); renderTab() }
  function renderTab() {
    if (!st.exp) {
      for (const [k] of TABS) panel(k).innerHTML = `<div class="xp-empty">실험을 고르거나 '새 실험'으로 만드세요. 틀: ${st.templates.map(t => esc(t.name)).join(' · ')}</div>`;
      return;
    }
    ({flow: renderFlow, data: renderData, result: renderResult})[st.tab]();
  }

  // ---------------------------------------------------------------- 흐름 모의
  async function simulate() {
    if (!st.exp) return;
    root.classList.add('xp-busy');
    try { st.sim = await json(`${B}/simulate`, {method: 'POST', body: {wf_id: st.exp.wf_id}}) }
    catch (ex) { st.sim = null; fail(ex) }
    finally { root.classList.remove('xp-busy') }
  }
  async function flowOp(body) {
    try {
      const f = await json(`${B}/flows/${st.exp.wf_id}/ops`, {method: 'POST', body});
      st.exp.flow = f;
      st.cmp = st.sug = st.cal = null;
      await simulate();
      if (st.tab === 'flow') renderFlow();
      return f;
    } catch (ex) {
      if (/강제\(force\)/.test(ex.message) && confirm(ex.message + '\n\n그래도 지울까요?')) return flowOp({...body, force: true});
      fail(ex);
    }
  }

  // ---------------------------------------------------------------- 공정 흐름 탭
  function stepColor(s, simStep) {
    const t = st.cat?.steps.find(c => c.type === s.type);
    if (s.type === 'dry') return METHOD_COLOR[(simStep?.params || s.params).method || '열풍건조'] || 'var(--v-accent)';
    return GROUP_COLOR[t?.group] || 'var(--v-accent)';
  }
  function stepLine(s, p) {
    p = p || s.params;
    const n = (v, d = 1) => v === null || v === undefined ? '—' : fmt(v, d);
    switch (s.type) {
      case 'feed': return `${n(p.mass_kg, 0)} kg · 수분 ${p.moisture_pct != null ? n(p.moisture_pct) + '%' : '기본값'}${p.tpc_mg_g != null ? ` · TPC ${n(p.tpc_mg_g, 2)}` : ''}`;
      case 'wash': return `남는 물 ${p.uptake_pct != null ? n(p.uptake_pct) + '%' : '가정'} · 손실 ${p.solids_loss_pct != null ? n(p.solids_loss_pct) + '%' : '가정'}`;
      case 'press': return `압착 후 수분 ${n(p.target_moisture_pct)}%`;
      case 'mill': return `입자 ${n(p.particle_mm, 2)} mm`;
      case 'dry': {
        const m = p.method || '열풍건조';
        const bits = [m];
        if (p.temp_c != null) bits.push(`${n(p.temp_c, 0)} ℃`);
        if (p.pressure_pa != null && m !== '열풍건조') bits.push(`${n(p.pressure_pa, 0)} Pa`);
        if (p.time_h != null) bits.push(`${n(p.time_h)} h`);
        if (m === '분무건조' && p.outlet_c != null) bits.push(`출구 ${n(p.outlet_c, 0)} ℃`);
        return bits.join(' · ');
      }
      case 'sieve': return `체 ${n(p.mesh_um, 0)} µm${p.yield_pct != null ? ` · 통과 ${n(p.yield_pct)}%` : ''}`;
      case 'extract': return `${p.solvent && p.solvent !== '에탄올 수용액' ? esc(p.solvent) : `에탄올 ${n(p.ethanol_pct, 0)}%`} · ${n(p.temp_c, 0)} ℃ · ${n(p.time_min, 0)}분${p.acid ? ` · ${esc(p.acid)}` : ''}`;
      case 'store': return `${esc(p.package || '')} · ${n(p.days, 0)}일 · ${n(p.temp_c, 0)} ℃`;
      default: return '';
    }
  }

  function renderFlow() {
    const P = panel('flow');
    const steps = st.exp.flow.steps;
    const simBy = Object.fromEntries((st.sim?.steps || []).map(s => [s.key, s]));
    const feedWet = st.sim?.steps?.[0]?.stream_out?.wet_kg || 1;
    const sm = st.sim?.summary;
    P.innerHTML = '';
    const tool = h(`<div class="card"><div class="row"><h3 class="grow" style="margin:0">공정 흐름 <span class="small muted">— ${esc(st.exp.flow.name)} · v${st.exp.flow.version} · ${esc(st.exp.byproduct)}</span></h3>
      ${sm ? `<span class="chips">${badge('literature', `${sm.literature_verified}/${sm.literature}`)}${badge('measured', sm.measured)}${badge('equipment', sm.equipment)}${badge('assumption', sm.assumption)}${badge('input', sm.input)}</span>` : ''}</div>
      <p class="small muted" style="margin:4px 0 8px">단계를 끌어 순서를 바꾸거나 ←·→ 단추를 쓰세요. 단계를 누르면 아래에서 값을 고칩니다. 사이의 막대는 흐름의 질량(갈색 건물 + 파란 물)과 TPC 잔존율입니다 — 흐름 기본값으로 모의한 값.</p>
      <div class="xp-tool"><span class="lab">단계 추가</span></div>
      <div class="xp-chainwrap"><ol class="xp-chain" aria-label="공정 단계 (순서대로)"></ol></div>
      <div class="xp-legend"><span><i style="background:var(--v-earth)"></i>건물(고형분)</span><span><i style="background:var(--cold)"></i>물</span><span><i style="background:var(--v-ok)"></i>TPC 잔존율(원료 대비)</span><span>막대 높이 = 원료 대비 습량</span></div>
      ${sm ? `<p class="small muted" style="margin:6px 0 0">${esc(sm.text)}. ${esc(st.sim.disclaimer)}</p>` : ''}
    </div>`);
    const tl = tool.querySelector('.xp-tool');
    for (const c of st.cat.steps) {
      const b = h(`<button class="btn sm" type="button" title="${esc(c.desc)}">+ ${esc(c.label)}</button>`);
      b.onclick = async () => {
        const selIdx = steps.findIndex(s => s.key === st.sel);
        const f = await flowOp({op: 'add', type: c.type, index: selIdx >= 0 ? selIdx + 1 : steps.length});
        if (f) { const added = f.steps.find(s => !steps.some(o => o.key === s.key)); if (added) { st.sel = added.key; renderFlow() } say(`${c.label} 단계를 넣었습니다.`) }
      };
      tl.appendChild(b);
    }
    const ol = tool.querySelector('.xp-chain');
    steps.forEach((s, i) => {
      const ss = simBy[s.key];
      if (i > 0) ol.appendChild(linkEl(simBy[steps[i - 1].key] || null, feedWet, steps, i));
      const out = ss?.stream_out;
      const li = h(`<li class="xp-step${s.enabled === false ? ' off' : ''}${ss?.error ? ' err' : ''}" draggable="true" data-key="${s.key}" tabindex="0"
          aria-current="${st.sel === s.key}" style="--g:${stepColor(s, ss)}" aria-label="${i + 1}번째 단계 ${esc(s.label)}${s.enabled === false ? ' (꺼짐)' : ''}">
        <span class="grip" aria-hidden="true" title="끌어서 옮기기">⠿</span>
        <div class="row" style="gap:6px;flex-wrap:nowrap"><span class="no">${i + 1}</span><span class="nm">${esc(s.label)}</span></div>
        <div class="kv1">${stepLine(s, ss?.params)}</div>
        <div class="out">${s.enabled === false ? '<span class="pill off">꺼짐 — 건너뜀</span>' : ss?.error ? '<span class="pill bad">오류</span>'
          : out ? `<span>수분 <b>${fmt(out.moisture_pct, 1)}</b>%</span><span>${fmt(out.wet_kg, 1)} kg</span>` : ''}</div>
        <div class="ctl">
          <button type="button" class="mv" data-d="-1" aria-label="${esc(s.label)} 앞으로 옮기기" ${i === 0 ? 'disabled' : ''}>←</button>
          <button type="button" class="mv" data-d="1" aria-label="${esc(s.label)} 뒤로 옮기기" ${i === steps.length - 1 ? 'disabled' : ''}>→</button>
          <button type="button" class="tg" aria-pressed="${s.enabled !== false}" aria-label="${esc(s.label)} ${s.enabled === false ? '켜기' : '끄기'}" ${s.type === 'feed' ? 'disabled' : ''}>${s.enabled === false ? '켜기' : '끄기'}</button>
          <button type="button" class="rm" aria-label="${esc(s.label)} 지우기" ${s.type === 'feed' && steps.filter(x => x.type === 'feed').length === 1 ? 'disabled' : ''}>✕</button>
        </div>
      </li>`);
      li.addEventListener('click', e => { if (e.target.closest('button')) return; st.sel = s.key; renderFlow() });
      li.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target === li) { e.preventDefault(); st.sel = s.key; renderFlow(); panel('flow').querySelector('.xp-form input, .xp-form select')?.focus() } });
      li.querySelectorAll('.mv').forEach(b => b.onclick = async () => { await flowOp({op: 'move', key: s.key, delta: Number(b.dataset.d)}); say(`${s.label}을 옮겼습니다.`); focusStep(s.key) });
      li.querySelector('.tg').onclick = async () => { await flowOp({op: 'enable', key: s.key, enabled: s.enabled === false}); focusStep(s.key) };
      li.querySelector('.rm').onclick = async () => { if (confirm(`'${s.label}' 단계를 지울까요?`)) { await flowOp({op: 'remove', key: s.key}); say(`${s.label} 단계를 지웠습니다.`) } };
      // 끌어 옮기기
      li.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', s.key); e.dataTransfer.effectAllowed = 'move'; li.classList.add('drag') });
      li.addEventListener('dragend', () => { li.classList.remove('drag'); ol.querySelectorAll('.drop-before').forEach(x => x.classList.remove('drop-before')) });
      li.addEventListener('dragover', e => { e.preventDefault(); ol.querySelectorAll('.drop-before').forEach(x => x.classList.remove('drop-before')); li.classList.add('drop-before') });
      li.addEventListener('drop', async e => {
        e.preventDefault();
        const k = e.dataTransfer.getData('text/plain');
        if (!k || k === s.key) return;
        const from = steps.findIndex(x => x.key === k);
        let to = i; if (from < to) to -= 1;
        await flowOp({op: 'move', key: k, index: to});
        say('순서를 바꿨습니다.');
      });
      ol.appendChild(li);
    });
    if (st.sim?.final) ol.appendChild(linkEl(simBy[steps[steps.length - 1].key], feedWet, steps, steps.length, true));
    P.appendChild(tool);
    P.appendChild(stepPanel(steps.find(s => s.key === st.sel) || steps[0], simBy));
  }
  function focusStep(k) { requestAnimationFrame(() => panel('flow').querySelector(`.xp-step[data-key="${k}"]`)?.focus()) }

  function linkEl(prev, feedWet, steps, i, last) {
    const o = prev?.stream_out || prev?.stream_in;
    if (!o) return h('<li class="xp-link" aria-hidden="true"><span class="xp-arrow">→</span></li>');
    const f = Math.max(0.03, Math.min(1, o.wet_kg / feedWet));
    const wf = o.wet_kg ? o.water_kg / o.wet_kg : 0;
    return h(`<li class="xp-link" role="presentation" title="${last ? '최종' : `${i}→${i + 1}`}: ${fmt(o.wet_kg, 2)} kg, 수분 ${fmt(o.moisture_pct, 1)}%, TPC 잔존 ${fmt(o.tpc_ret_pct, 1)}%">
      <span class="xp-bar" aria-hidden="true"><span class="fill" style="--f:${f.toFixed(3)}"><i class="w" style="flex:${wf.toFixed(3)}"></i><i class="d" style="flex:${(1 - wf).toFixed(3)}"></i></span></span>
      <span>${fmt(o.wet_kg, 1)} kg</span><span>${fmt(o.moisture_pct, 1)}%</span>
      <span class="xp-tpcbar" aria-hidden="true"><i style="width:${Math.max(0, Math.min(100, o.tpc_ret_pct || 0))}%"></i></span><span>TPC ${fmt(o.tpc_ret_pct, 0)}%</span>
      <span class="sr-only">${last ? '최종 제품' : '다음 단계로'}: ${fmt(o.wet_kg, 2)} kg, 수분 ${fmt(o.moisture_pct, 1)}%, TPC 잔존 ${fmt(o.tpc_ret_pct, 1)}%</span>
      ${last ? '<b style="font-size:11px">제품</b>' : '<span class="xp-arrow" aria-hidden="true">→</span>'}</li>`);
  }

  // 범주 조건의 목록(<datalist>): 목록에서 고르거나 직접 입력. 키보드로 ↓를 누르면 목록이 열린다.
  // 목록은 단계 목록(catalog)을 받은 뒤 한 번만 root에 만든다(흐름·런 표가 같은 목록을 씀).
  function buildChoiceLists() {
    const seen = new Set();
    const box = h('<div class="xp-dls" hidden></div>');
    for (const c of st.cat.steps) for (const sp of c.params) {
      if (!(sp.type === 'select' && sp.free) || seen.has(sp.key)) continue;
      seen.add(sp.key);
      box.insertAdjacentHTML('beforeend', `<datalist id="${id}-dl-${sp.key}">${(sp.options || []).map(o => `<option value="${esc(o)}"></option>`).join('')}</datalist>`);
    }
    root.appendChild(box);
  }
  function choiceList() { return '' }

  function specsFor(s) {
    if (s.type === 'dry') return st.cat.dry_methods[s.params.method || '열풍건조'];
    return st.cat.steps.find(c => c.type === s.type).params;
  }

  function stepPanel(s, simBy) {
    const ss = simBy[s.key];
    const wrap = h(`<div class="xp-panel"><form class="card xp-form" aria-label="${esc(s.label)} 단계 값"><h3 style="margin:0">${esc(s.label)} <span class="small muted">(${esc(s.key)})</span></h3></form><div class="card xp-live"></div></div>`);
    const f = wrap.querySelector('form');
    const t = st.cat.steps.find(c => c.type === s.type);
    f.appendChild(h(`<p class="small muted" style="margin:0">${esc(t.desc)}</p>`));
    const nm = h(`<label>단계 이름 <input class="inp" name="__label" value="${esc(s.label)}" maxlength="40"></label>`);
    nm.querySelector('input').addEventListener('change', e => flowOp({op: 'rename', key: s.key, label: e.target.value}));
    f.appendChild(nm);
    for (const sp of specsFor(s)) {
      const iid = `${id}-f-${s.key}-${sp.key}`;
      const cur = s.params[sp.key];
      const eff = ss?.params?.[sp.key];
      let ctl;
      if (sp.type === 'select' && sp.free) {
        ctl = h(`<label for="${iid}">${esc(sp.label)} <span class="hint">(목록에서 고르거나 직접 입력)</span>
          <input class="inp" id="${iid}" name="${sp.key}" list="${id}-dl-${sp.key}" maxlength="40" autocomplete="off" value="${esc(cur ?? '')}" placeholder="비움(기록 안 함)" data-t="text">
          ${choiceList(sp)}${sp.help ? `<span class="hint">${esc(sp.help)}</span>` : ''}</label>`);
      } else if (sp.type === 'select') {
        ctl = h(`<label for="${iid}">${esc(sp.label)} <select class="inp" id="${iid}" name="${sp.key}">${sp.options.map(o => `<option${(cur ?? sp.default) === o ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select>${sp.help ? `<span class="hint">${esc(sp.help)}</span>` : ''}</label>`);
      } else {
        const ph = cur == null && eff != null ? `기본 ${fmt(eff, 3)}` : (sp.optional ? '비움(기본값)' : '');
        ctl = h(`<label for="${iid}">${esc(sp.label)} <span class="hint">(${esc(sp.unit || '')}${sp.min !== undefined ? `, ${fmt(sp.min, 3)}–${fmt(sp.max, 3)}` : ''})</span>
          <input class="inp" id="${iid}" name="${sp.key}" type="number" step="any" min="${sp.min}" max="${sp.max}" value="${cur ?? ''}" placeholder="${esc(ph)}">
          ${sp.help ? `<span class="hint">${esc(sp.help)}</span>` : ''}</label>`);
      }
      const inp = ctl.querySelector('input,select');
      inp.addEventListener('change', () => {
        clearTimeout(st.paramTimer);
        const v = inp.tagName === 'SELECT' ? inp.value : inp.dataset.t === 'text' ? (inp.value.trim() || null) : inp.value === '' ? null : Number(inp.value);
        if (inp.type === 'number' && v !== null && (v < sp.min || v > sp.max)) { inp.classList.add('bad'); say(`${sp.label}: ${sp.min}–${sp.max} 사이로 넣으세요.`); return }
        inp.classList.remove('bad');
        st.paramTimer = setTimeout(() => flowOp({op: 'params', key: s.key, params: {[sp.key]: v}}), 150);
      });
      f.appendChild(ctl);
    }
    const tools = h(`<div class="row"></div>`);
    if (s.type === 'dry') {
      const m = (ss?.params || s.params).method || '열풍건조';
      const b = h(`<button class="btn sm" type="button">건조 방식 탭에서 보기 (${esc(m)})</button>`);
      b.onclick = () => opts.openDrying ? opts.openDrying(m, ss?.predict?.inputs) : window.open(new URL(`../viz/predict-dev.html?method=${encodeURIComponent(m)}`, import.meta.url), '_blank', 'noopener');
      tools.appendChild(b);
    }
    if (tools.children.length) f.appendChild(tools);
    // 결과
    const live = wrap.querySelector('.xp-live');
    if (!ss) { live.innerHTML = '<p class="small muted">모의 결과가 없습니다.</p>'; return wrap }
    if (ss.skipped) { live.innerHTML = '<p class="small muted">꺼진 단계 — 흐름이 이 단계를 건너뜁니다. 켜면 다시 계산합니다.</p>'; return wrap }
    if (ss.error) { live.innerHTML = `<p class="err" role="alert">${esc(ss.error)}</p>`; return wrap }
    live.appendChild(h(`<div class="row"><h3 class="grow" style="margin:0">이 단계를 지난 뒤 (기본 조건 모의)</h3>${ss.drying_method ? `<span class="pill" style="color:${METHOD_COLOR[ss.drying_method]}">${esc(ss.drying_method)}</span>` : ''}</div>`));
    const outs = h('<div class="xp-outs"></div>');
    for (const o of Object.values(ss.outputs)) outs.appendChild(outCard(o, `${s.key}:${o.key}`));
    live.appendChild(outs);
    const extra = [];
    for (const n of ss.notes || []) extra.push(`<li>${esc(n)}</li>`);
    for (const l of ss.losses || []) if (l.dm_kg > 0) extra.push(`<li>밝힌 손실·분리: ${esc(l.what)} — 건물 ${fmt(l.dm_kg, 3)} kg</li>`);
    if (ss.balance) extra.push(`<li>건물 수지: 들어온 ${fmt(ss.balance.dm_in, 3)} = 나간 ${fmt(ss.balance.dm_out, 3)} + 밝힌 손실 ${fmt(ss.balance.declared_loss, 3)} kg (차 ${fmt(ss.balance.closure, 6)})</li>`);
    if (extra.length) live.appendChild(h(`<ul class="xp-loss">${extra.join('')}</ul>`));
    for (const w of ss.warnings || []) live.appendChild(h(`<div class="${w.kind === 'extrapolation' ? 'notice' : 'small pr-note'}" role="note">${w.kind === 'extrapolation' ? '<b>외삽 — 근거 범위 밖</b> ' : ''}${esc(w.text.replace(/^외삽 — 근거 범위 밖:\s*/, ''))}</div>`));
    return wrap;
  }

  function outCard(o, k) {
    const band = o.low != null && o.high != null && (o.low !== o.value || o.high !== o.value) ? ` <span class="pr-band">${fmt(o.low, 2)}–${fmt(o.high, 2)}</span>` : '';
    const ex = (o.warnings || []).some(w => w.kind === 'extrapolation');
    const c = h(`<div class="xp-out"><div class="row"><span class="t grow">${esc(o.label)}</span>${ex ? '<span class="pill warn">외삽</span>' : ''}${o.calibration?.applied ? '<span class="pill ok">보정</span>' : ''}</div>
      <div class="v">${o.status === 'unreachable' ? '<b class="err">도달 못 함</b>' : o.value == null ? '<span class="muted">값 없음</span>' : `<b>${fmt(o.value, 2)}</b> <span class="muted">${esc(o.unit)}</span>${band}`}</div>
      ${o.value_label ? `<div class="small muted">${esc(o.value_label)}</div>` : ''}</div>`);
    c.appendChild(evidenceBlock(o, k));
    return c;
  }

  function evidenceBlock(o, k) {
    const open = st.open.has(k) || st.open.has('*');
    const params = o.params || [];
    const rows = params.map(p => `<li class="pr-p">
      <div class="pr-p-h"><span class="pr-p-l">${esc(p.label)}</span>${p.role === 'reference' ? '<span class="pr-b derived">대조·참고</span>' : ''} <b class="pr-p-v">${esc(valStr(p.value))}</b> <span class="muted">${esc(p.unit || '')}</span>
        ${p.band ? `<span class="pr-band">폭 ${esc(valStr(p.band))}</span>` : ''}</div>
      <div>${evBadge(p.evidence)}${p.evidence.locator ? `<span class="small muted">${esc(p.evidence.locator)}</span>` : ''}</div>
      ${p.evidence.note ? `<div class="small pr-p-n">${esc(p.evidence.note)}</div>` : ''}${validityStr(p.evidence.validity)}</li>`).join('');
    const srcs = new Map();
    for (const p of params) if (p.evidence.type === 'literature' && p.evidence.doi) {
      const s = srcs.get(p.evidence.doi) || {ev: p.evidence, loc: new Set()};
      if (p.evidence.locator) s.loc.add(p.evidence.locator);
      srcs.set(p.evidence.doi, s);
    }
    const cites = [...srcs.values()].map(({ev, loc}) => `<li>${esc(ev.citation)} <a href="https://doi.org/${encodeURI(ev.doi)}" target="_blank" rel="noopener">doi:${esc(ev.doi)}</a>
      ${ev.verified ? `<span class="pill ok">DOI 확인 ${esc(ev.verified_at || '')}</span>` : '<span class="pill warn">DOI 미확인</span>'}
      <div class="small muted">읽은 곳: ${esc([...loc].join(' · '))}${ev.read ? ' — ' + esc(ev.read) : ''}</div></li>`).join('');
    const cal = o.calibration;
    const calHtml = !cal ? '' : `<h4>실측 보정</h4><p class="small">${cal.applied ? `적용함 — 배율 <b>${fmt(cal.factor, 3)}</b>, ${esc(cal.message)}` : esc(cal.message)}</p>${cal.how ? `<p class="small muted">${esc(cal.how)}</p>` : ''}
      ${cal.points?.length ? `<table><thead><tr><th>시료</th><th class="num">온도</th><th class="num">시간</th><th class="num">실측</th><th class="num">보정 후 예측</th><th class="num">잔차</th></tr></thead><tbody>
      ${cal.points.map(p => `<tr><td>${esc(p.sample)}</td><td class="num">${fmt(p.temp_c, 1)} ℃</td><td class="num">${fmt(p.time_h, 1)} h</td><td class="num">${p.moist_final !== undefined ? fmt(p.moist_final, 2) + '%' : p.tpc != null ? fmt(p.tpc, 2) : fmt(p.retention * 100, 1) + '%'}</td>
        <td class="num">${p.pred_final !== undefined ? fmt(p.pred_final, 2) + '%' : p.pred_tpc != null ? fmt(p.pred_tpc, 2) : fmt(p.pred_retention * 100, 1) + '%'}</td><td class="num">${fmt(p.residual, 3)}</td></tr>`).join('')}</tbody></table>` : ''}`;
    const warns = (o.warnings || []).filter(w => w.kind !== 'extrapolation').map(w => `<div class="small pr-note ${w.kind === 'calibration' ? 'cal' : ''}">${esc(w.text)}</div>`).join('')
      + (o.warnings || []).filter(w => w.kind === 'extrapolation').map(w => `<div class="notice pr-warn" role="note"><b>외삽 — 근거 범위 밖</b> ${esc(w.text.replace(/^외삽 — 근거 범위 밖:\s*/, ''))}</div>`).join('');
    const d = h(`<details class="pr-ev" data-k="${esc(k)}"${open ? ' open' : ''}><summary>근거</summary>
      ${o.formula?.model ? `<h4>모델</h4><p class="small">${esc(o.formula.model)}</p>` : ''}
      ${o.formula?.text ? `<pre class="pr-f">${esc(o.formula.text)}</pre>` : ''}
      ${warns}
      ${rows ? `<h4>파라미터</h4><ul class="pr-plist">${rows}</ul>` : '<p class="small muted">계수 없음(앞 단계 값을 이어받음).</p>'}
      ${calHtml}
      ${cites ? `<h4>인용 문헌</h4><ul class="pr-cites">${cites}</ul>` : '<p class="small muted">이 값에는 문헌 근거가 없습니다(가정·실측·설비·내 입력만).</p>'}
    </details>`);
    d.addEventListener('toggle', () => { st.open.delete('*'); d.open ? st.open.add(k) : st.open.delete(k) });
    return d;
  }

  // ---------------------------------------------------------------- 실험 데이터 탭
  function gridColumns() {
    const steps = st.exp.flow.steps;
    const saved = store.get('cols:' + st.exp.exp_id);
    const conds = [], vals = [];
    const addC = (k, p) => { if (!conds.some(c => c[0] === k && c[1] === p)) conds.push([k, p]) };
    const addV = (k, t) => { if (!vals.some(c => c[0] === k && c[1] === t)) vals.push([k, t]) };
    for (const s of steps) {
      if (s.enabled === false) continue;
      if (s.type === 'feed') { addC(s.key, 'moisture_pct'); addC(s.key, 'tpc_mg_g') }
      if (s.type === 'press') addC(s.key, 'target_moisture_pct');
      if (s.type === 'dry') {
        const m = s.params.method || '열풍건조';
        for (const p of {열풍건조: ['temp_c', 'time_h'], 동결건조: ['temp_c', 'pressure_pa', 'time_h'], 진공건조: ['temp_c', 'pressure_pa', 'time_h'],
          분무건조: ['temp_c', 'outlet_c'], 자연건조: ['temp_c', 'time_h', 'rh']}[m] || []) addC(s.key, p);
        addV(s.key, 'moisture'); addV(s.key, 'tpc');
      }
      if (s.type === 'sieve') addV(s.key, 'sieve_yield');
      if (s.type === 'extract') { addC(s.key, 'ethanol_pct'); addC(s.key, 'temp_c'); addC(s.key, 'time_min'); addC(s.key, 'acid'); addV(s.key, 'tpc_extract_yield') }
      if (s.type === 'store') { addC(s.key, 'days'); addV(s.key, 'moisture') }
    }
    for (const r of st.exp.runs) {
      for (const [k, c] of Object.entries(r.conditions)) for (const p of Object.keys(c)) addC(k, p);
      for (const v of r.values) if (v.kind === 'measured') addV(v.step_key, v.target_key || v.target);
    }
    for (const [k, p] of saved?.conds || []) if (steps.some(s => s.key === k)) addC(k, p);
    for (const [k, t] of saved?.vals || []) if (steps.some(s => s.key === k)) addV(k, t);
    const hide = new Set(saved?.hide || []);
    const order = Object.fromEntries(steps.map((s, i) => [s.key, i]));
    const srt = a => a.sort((x, y) => (order[x[0]] ?? 99) - (order[y[0]] ?? 99));
    return {conds: srt(conds).filter(c => !hide.has('c:' + c.join('.'))), vals: srt(vals).filter(c => !hide.has('v:' + c.join('.')))};
  }
  const tgtInfo = k => st.cat.targets.find(t => t.key === k) || {label: k, unit: ''};
  function paramSpec(stepKey, p) {
    const s = st.exp.flow.steps.find(x => x.key === stepKey);
    return s ? specsFor(s).find(x => x.key === p) : null;
  }

  function renderData() {
    const P = panel('data');
    const steps = st.exp.flow.steps;
    const sl = Object.fromEntries(steps.map(s => [s.key, s.label]));
    const {conds, vals} = gridColumns();
    P.innerHTML = '';
    const card = h(`<div class="card"><div class="row"><h3 class="grow" style="margin:0">런 표 <span class="small muted">— 런 ${st.exp.runs.length}개</span></h3>
      <button class="btn sm primary xp-addrun" type="button">+ 런 추가</button>
      <label class="btn sm" style="cursor:pointer">파일 가져오기 (CSV·XLSX)<input type="file" class="sr-only xp-file" accept=".csv,.tsv,.txt,.xlsx,.xlsm"></label>
      <a class="btn sm" href="${B}/experiments/${st.exp.exp_id}/export.csv" download>CSV 내보내기</a></div>
      <p class="small muted" style="margin:4px 0 8px">파란 열 = 조건(비우면 흐름 기본값), 갈색 열 = 내가 잰 값. 값 칸에는 숫자, <b>ND</b>(불검출), <b>&lt; 0.01</b>(검출 한계)를 넣을 수 있습니다. 칸을 벗어나면 저장됩니다.</p>
      <div class="xp-tool" style="margin-bottom:8px"><span class="lab">열 추가</span><select class="inp xp-addcol" aria-label="열 추가"><option value="">조건이나 값을 고르세요</option></select></div>
      <div class="xp-imp"></div>
      <div class="xp-grid"></div></div>`);
    // 열 추가 고르기
    const addSel = card.querySelector('.xp-addcol');
    const optsC = [], optsV = [];
    for (const s of steps) {
      for (const sp of specsFor(s)) if (!conds.some(c => c[0] === s.key && c[1] === sp.key) && !(sp.help || '').startsWith('기록용')) optsC.push(`<option value="c:${s.key}.${sp.key}">[조건] ${esc(s.label)} · ${esc(sp.label)}</option>`);
      for (const t of st.cat.targets) if (!vals.some(c => c[0] === s.key && c[1] === t.key)) optsV.push(`<option value="v:${s.key}.${t.key}">[실측] ${esc(s.label)} · ${esc(t.label)}</option>`);
    }
    addSel.insertAdjacentHTML('beforeend', `<optgroup label="조건">${optsC.join('')}</optgroup><optgroup label="실측값">${optsV.join('')}</optgroup>`);
    addSel.onchange = () => {
      const v = addSel.value; if (!v) return;
      const [kind, rest] = v.split(':'); const [k, p] = rest.split('.');
      const saved = store.get('cols:' + st.exp.exp_id) || {conds: [], vals: [], hide: []};
      (kind === 'c' ? saved.conds : saved.vals).push([k, p]);
      saved.hide = (saved.hide || []).filter(x => x !== v);
      store.set('cols:' + st.exp.exp_id, saved);
      renderData();
    };
    card.querySelector('.xp-addrun').onclick = async () => {
      try {
        await json(`${B}/experiments/${st.exp.exp_id}/runs`, {method: 'POST', body: {}});
        st.exp = await json(`${B}/experiments/${st.exp.exp_id}`); st.cmp = st.cal = st.sug = null;
        renderData(); say('런을 하나 넣었습니다.');
        panel('data').querySelector('tbody tr:last-child input')?.focus();
      } catch (ex) { fail(ex) }
    };
    card.querySelector('.xp-file').onchange = e => { const f = e.target.files[0]; if (f) importPreview(f); e.target.value = '' };
    // 표
    const g = card.querySelector('.xp-grid');
    if (!st.exp.runs.length) {
      g.innerHTML = `<div class="xp-empty">아직 런이 없습니다. '+ 런 추가'로 한 줄씩 넣거나, 표 파일(CSV·XLSX)을 가져오세요.<br>예시 열 이름: 런, 날짜, 원료 수분(%), 건조 온도(℃), 건조 시간(h), 건조 후 수분(%), TPC (mg GAE/g 건량)</div>`;
    } else {
      const colHead = (txt, sub, cls, hideKey) => `<th class="${cls}" scope="col">${esc(txt)}<span class="sk">${esc(sub)}</span>${hideKey ? `<button type="button" class="btn sm xp-hide" data-h="${hideKey}" aria-label="${esc(txt)} 열 숨기기" style="height:18px;padding:0 5px;margin-top:2px">숨김</button>` : ''}</th>`;
      const head = `<tr><th scope="col">런</th><th scope="col">이름</th><th scope="col">날짜</th>
        ${conds.map(([k, p]) => { const sp = paramSpec(k, p); return colHead(sp?.label || p, `${sl[k] || k}${sp?.unit ? ' · ' + sp.unit : ''}`, 'grpc', `c:${k}.${p}`) }).join('')}
        ${vals.map(([k, t]) => { const ti = tgtInfo(t); return colHead(ti.label, `${sl[k] || k} · ${ti.unit}`, 'grpv', `v:${k}.${t}`) }).join('')}
        <th scope="col">비고</th><th scope="col"><span class="sr-only">지우기</span></th></tr>`;
      const tb = st.exp.runs.map(r => {
        const cells = conds.map(([k, p]) => {
          const sp = paramSpec(k, p); const v = r.conditions[k]?.[p];
          const base = st.exp.flow.steps.find(s => s.key === k)?.params?.[p];
          if (sp?.type === 'select' && sp.free) return `<td class="grpc"><input class="inp txt choice" data-c="${k}.${p}" data-t="text" list="${id}-dl-${p}" maxlength="40" autocomplete="off" value="${esc(v ?? '')}" placeholder="${esc(base ?? '')}" aria-label="${esc(r.alias)} ${esc(sp.label)} (목록에서 고르거나 직접 입력)"></td>`;
          if (sp?.type === 'select') return `<td class="grpc"><select class="inp txt" data-c="${k}.${p}" aria-label="${esc(r.alias)} ${esc(sp.label)}"><option value="">(흐름: ${esc(base ?? sp.default)})</option>${sp.options.map(o => `<option${v === o ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select></td>`;
          return `<td class="grpc"><input class="inp" data-c="${k}.${p}" inputmode="decimal" value="${v ?? ''}" placeholder="${base != null ? esc(fmt(base, 3)) : ''}" aria-label="${esc(r.alias)} ${esc(sp?.label || p)}"></td>`;
        }).join('');
        const vcells = vals.map(([k, t]) => {
          const v = r.values.find(x => x.kind === 'measured' && x.step_key === k && (x.target_key || x.target) === t);
          const shown = v ? (v.value_text && (v.value === null || /^[<>≤≥]/.test(v.value_text)) ? v.value_text : v.value ?? '') : '';
          return `<td class="grpv"><input class="inp" data-v="${k}.${t}" value="${esc(shown)}" aria-label="${esc(r.alias)} ${esc(sl[k] || k)} ${esc(tgtInfo(t).label)}"></td>`;
        }).join('');
        return `<tr data-run="${r.xrun_id}"><td class="alias">${esc(r.alias)}</td>
          <td><input class="inp txt" data-f="label" value="${esc(r.label || '')}" aria-label="${esc(r.alias)} 이름"></td>
          <td><input class="inp txt" data-f="run_date" value="${esc(r.run_date || '')}" placeholder="YYYY-MM-DD" style="width:104px" aria-label="${esc(r.alias)} 날짜"></td>
          ${cells}${vcells}<td><input class="inp txt" data-f="note" value="${esc(r.note || '')}" aria-label="${esc(r.alias)} 비고"></td>
          <td><button class="btn sm xp-rmrun" type="button" aria-label="${esc(r.alias)} 지우기">✕</button></td></tr>`;
      }).join('');
      g.innerHTML = `<table><thead>${head}</thead><tbody>${tb}</tbody></table>`;
      g.querySelectorAll('.xp-hide').forEach(b => b.onclick = () => {
        const saved = store.get('cols:' + st.exp.exp_id) || {conds: [], vals: [], hide: []};
        saved.hide = [...new Set([...(saved.hide || []), b.dataset.h])];
        store.set('cols:' + st.exp.exp_id, saved); renderData();
      });
      g.querySelectorAll('tbody tr').forEach(tr => {
        const run = st.exp.runs.find(r => r.xrun_id === tr.dataset.run);
        tr.querySelector('.xp-rmrun').onclick = async () => {
          if (!confirm(`${run.alias}(${run.label || ''})를 지울까요?`)) return;
          try { await json(`${B}/runs/${run.xrun_id}`, {method: 'DELETE'}); st.exp = await json(`${B}/experiments/${st.exp.exp_id}`); st.cmp = st.cal = null; renderData() }
          catch (ex) { fail(ex) }
        };
        tr.querySelectorAll('input,select').forEach(inp => inp.addEventListener('change', () => saveCell(run, inp, tr)));
      });
    }
    P.appendChild(card);
    if (st.imp) renderImport(card.querySelector('.xp-imp'));
  }

  async function saveCell(run, inp, tr) {
    const body = {};
    if (inp.dataset.f) body[inp.dataset.f] = inp.value;
    if (inp.dataset.c) {
      const cond = JSON.parse(JSON.stringify(run.conditions));
      tr.querySelectorAll('[data-c]').forEach(i => {
        const [k, p] = i.dataset.c.split('.');
        const v = i.value.trim();
        if (v === '') { if (cond[k]) delete cond[k][p] } else (cond[k] ||= {})[p] = i.tagName === 'SELECT' || i.dataset.t === 'text' ? v : Number(v);
      });
      body.conditions = cond;
    }
    if (inp.dataset.v) {
      const shown = new Set([...tr.querySelectorAll('[data-v]')].map(i => i.dataset.v));
      const values = run.values.filter(v => v.kind === 'measured' && !shown.has(`${v.step_key}.${v.target_key || v.target}`))
        .map(v => ({step_key: v.step_key, target: v.target, value: v.value_text && (v.value === null || /^[<>≤≥]/.test(v.value_text)) ? v.value_text : v.value, unit: v.unit, basis: v.basis}));
      tr.querySelectorAll('[data-v]').forEach(i => {
        const [k, t] = i.dataset.v.split('.');
        if (i.value.trim() === '') return;
        const old = run.values.find(v => v.kind === 'measured' && v.step_key === k && (v.target_key || v.target) === t);
        values.push({step_key: k, target: t, value: i.value.trim(), unit: old?.unit || null, basis: old?.basis || null});
      });
      body.values = values;
    }
    try {
      const r = await json(`${B}/runs/${run.xrun_id}`, {method: 'PUT', body});
      Object.assign(run, r);
      inp.classList.remove('bad');
      st.cmp = st.cal = st.sug = null;
      say(`${run.alias} 저장함`);
    } catch (ex) { inp.classList.add('bad'); fail(ex) }
  }

  // ---------------------------------------------------------------- 가져오기
  async function importPreview(file) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      st.imp = await json(`${B}/experiments/${st.exp.exp_id}/import/preview`, {method: 'POST', body: fd});
      renderData();
      say(`${file.name}: ${st.imp.n_rows}행을 읽었습니다. 열 대응을 확인하세요.`);
    } catch (ex) { fail(ex) }
  }
  function renderImport(box) {
    const im = st.imp;
    const stepOpts = sel => im.steps.map(s => `<option value="${s.key}"${s.key === sel ? ' selected' : ''}>${esc(s.label)} (${s.key})</option>`).join('');
    const keyOpts = (col) => {
      if (col.role === 'condition') {
        const s = im.steps.find(x => x.key === col.step_key);
        return (s?.params || []).map(p => `<option value="${p.key}"${p.key === col.key ? ' selected' : ''}>${esc(p.label)}${p.unit ? ' (' + esc(p.unit) + ')' : ''}</option>`).join('');
      }
      if (col.role === 'value') return im.targets.map(t => `<option value="${t.key}"${t.key === col.key ? ' selected' : ''}>${esc(t.label)} (${esc(t.unit)})</option>`).join('');
      return '';
    };
    box.innerHTML = '';
    const c = h(`<div class="card" style="margin-bottom:10px;border-color:var(--v-accent)"><div class="row"><h3 class="grow" style="margin:0">가져오기 — ${esc(im.file_name)} <span class="small muted">${im.n_rows}행 · 머리글 ${im.header_row}행</span></h3>
      <button class="btn sm primary xp-commit" type="button">${im.n_rows}행 가져오기</button><button class="btn sm xp-impcancel" type="button">취소</button></div>
      <p class="small muted" style="margin:4px 0">열마다 역할·단계·항목·단위를 확인하세요. 괄호 속 단위는 자동으로 표준 단위로 바꿉니다(예: mg GAE/100 g → mg GAE/g, min → h). ${esc(im.privacy)}</p>
      ${im.issues.length ? `<div class="notice" role="note"><b>확인할 열</b> ${im.issues.map(esc).join(' · ')}</div>` : ''}
      <div class="xp-grid" style="margin-top:6px"><table><thead><tr><th>열 이름</th><th>역할</th><th>단계</th><th>항목</th><th>단위</th><th>기준</th><th>앞 3행</th></tr></thead><tbody></tbody></table></div>
      <div class="xp-trial small" style="margin-top:6px"></div></div>`);
    const tb = c.querySelector('tbody');
    im.columns.forEach((col, i) => {
      const tr = h(`<tr><td><b>${esc(col.header)}</b></td>
        <td><select class="inp" data-k="role" aria-label="${esc(col.header)} 역할">${Object.entries(ROLE_LABEL).map(([k, l]) => `<option value="${k}"${k === col.role ? ' selected' : ''}>${l}</option>`).join('')}</select></td>
        <td>${col.role === 'condition' || col.role === 'value' ? `<select class="inp" data-k="step_key" aria-label="${esc(col.header)} 단계"><option value="">단계 고르기</option>${stepOpts(col.step_key)}</select>` : ''}</td>
        <td>${col.role === 'condition' || col.role === 'value' ? `<select class="inp" data-k="key" aria-label="${esc(col.header)} 항목"><option value="">항목 고르기</option>${keyOpts(col)}</select>` : ''}</td>
        <td>${col.role === 'condition' || col.role === 'value' ? `<input class="inp" data-k="unit" value="${esc(col.unit || '')}" aria-label="${esc(col.header)} 단위" placeholder="표준">` : ''}</td>
        <td>${col.role === 'value' ? `<select class="inp" data-k="basis" aria-label="${esc(col.header)} 기준"><option value="">자동</option>${['건량', '습량'].map(b => `<option${col.basis === b ? ' selected' : ''}>${b}</option>`).join('')}</select>` : ''}</td>
        <td class="small muted">${col.sample.map(esc).join(' · ')}</td></tr>`);
      tr.querySelectorAll('[data-k]').forEach(s => s.addEventListener('change', () => {
        col[s.dataset.k] = s.value || null;
        if (s.dataset.k === 'role') { col.key = null; if (!['condition', 'value'].includes(col.role)) col.step_key = null }
        if (s.dataset.k === 'step_key' && col.role === 'condition') col.key = null;
        renderImport(box);
      }));
      tb.appendChild(tr);
    });
    const tr = c.querySelector('.xp-trial');
    tr.innerHTML = (im.trial.length ? `<b>첫 행 읽은 결과:</b> ${esc(JSON.stringify(im.trial[0].conditions))} · ${im.trial[0].values.map(v => `${esc(v.step_key)} ${esc(v.target_text)} ${v.value ?? esc(v.value_text)}${v.value_text && v.value != null ? ` (${esc(v.value_text)})` : ''}`).join(' · ')}` : '')
      + im.errors.map(e => `<div class="err">${e.row}행: ${esc(e.error)}</div>`).join('');
    c.querySelector('.xp-impcancel').onclick = () => { st.imp = null; renderData() };
    c.querySelector('.xp-commit').onclick = async () => {
      try {
        const r = await json(`${B}/experiments/${st.exp.exp_id}/import/commit`, {method: 'POST', body: {token: im.token, columns: im.columns}});
        st.imp = null;
        toast(r.message);
        if (r.errors.length) alert(r.message + '\n\n' + r.errors.slice(0, 10).map(e => `${e.row}행: ${e.error}`).join('\n'));
        st.exp = await json(`${B}/experiments/${st.exp.exp_id}`); st.cmp = st.cal = st.sug = null;
        await loadList(); $('.xp-sel').value = st.exp.exp_id;
        renderData();
      } catch (ex) { fail(ex) }
    };
    box.appendChild(c);
  }

  // ---------------------------------------------------------------- 결과·보정 탭
  async function renderResult() {
    const P = panel('result');
    if (!st.exp.runs.length) { P.innerHTML = '<div class="xp-empty">비교할 런이 없습니다. 실험 데이터 탭에서 런과 실측값을 넣으세요.</div>'; return }
    if (!st.cmp) {
      P.innerHTML = '<div class="xp-empty">예측과 실측을 비교하는 중…</div>';
      try { st.cmp = await json(`${B}/experiments/${st.exp.exp_id}/compare`, {method: 'POST', body: {}}) }
      catch (ex) { P.innerHTML = `<div class="xp-empty err">${esc(ex.message)}</div>`; return }
    }
    if (!st.params) st.params = {};
    if (!st.params[st.exp.exp_id]) { try { st.params[st.exp.exp_id] = (await json(`${B}/experiments/${st.exp.exp_id}/params`)).params } catch { st.params[st.exp.exp_id] = [] } }
    P.innerHTML = '';
    const c = st.cmp;
    const targets = Object.keys(c.summary);
    if (!targets.includes(st.parityTarget)) st.parityTarget = targets[0];
    // 요약
    const sum = h(`<div class="card"><div class="row"><h3 class="grow" style="margin:0">예측 대 실측</h3>
      <button class="btn sm xp-recmp" type="button">다시 계산</button><button class="btn sm xp-savepred" type="button" title="지금 예측값을 이 런들의 '예측' 값으로 남김(보정에는 안 씀)">예측값 저장</button></div>
      ${c.in_sample ? `<div class="notice" role="note" style="margin-top:6px"><b>표본 내 비교</b> ${esc(c.notes.join(' '))}</div>` : ''}
      <p class="small muted" style="margin:6px 0">잔차 = 실측 − 예측. 폭 안 = 실측이 예측의 불확실 폭 안에 든 런 수. ${esc(c.disclaimer)}</p>
      ${targets.length ? `<table><thead><tr><th>대상</th><th class="num">n</th><th class="num">MAE</th><th class="num">RMSE</th><th class="num">평균 잔차(편향)</th><th class="num">MAPE</th><th class="num">폭 안</th><th>단위</th></tr></thead><tbody>
      ${targets.map(k => { const s = c.summary[k]; return `<tr><td>${esc(s.label)}${s.note ? ` <span class="pill warn" title="${esc(s.note)}">n 적음</span>` : ''}</td><td class="num">${s.n}</td><td class="num">${fmt(s.mae, 3)}</td><td class="num">${fmt(s.rmse, 3)}</td><td class="num">${fmt(s.bias, 3)}</td><td class="num">${s.mape == null ? '-' : fmt(s.mape, 1) + '%'}</td><td class="num">${s.with_band ? `${s.within_band}/${s.with_band}` : '<span class="muted" title="예측에 폭이 없음(가정값·설정값)">-</span>'}</td><td class="small muted">${esc(s.unit)}</td></tr>` }).join('')}</tbody></table>`
        : '<p class="small muted">잔차를 계산할 짝이 없습니다 — 실측값이 흐름의 예측 대상(수분·TPC·수율 등)과 같은 단계에 있는지 확인하세요.</p>'}</div>`);
    sum.querySelector('.xp-recmp').onclick = () => { st.cmp = null; renderResult() };
    sum.querySelector('.xp-savepred').onclick = async () => {
      try { await json(`${B}/experiments/${st.exp.exp_id}/compare`, {method: 'POST', body: {save_predicted: true}}); toast('예측값을 저장했습니다(종류: 예측).') } catch (ex) { fail(ex) }
    };
    P.appendChild(sum);
    // 패리티 + 잔차
    if (targets.length) {
      const two = h(`<div class="xp-two"><div class="card"><div class="row"><h3 class="grow" style="margin:0">패리티(예측 vs 실측)</h3>
        <select class="inp xp-pt" aria-label="패리티 대상">${targets.map(k => `<option value="${k}"${k === st.parityTarget ? ' selected' : ''}>${esc(c.summary[k].label)}</option>`).join('')}</select></div><figure class="xp-chart xp-par"></figure></div>
        <div class="card"><h3 style="margin:0 0 6px">런별 잔차</h3><figure class="xp-chart xp-resb"></figure></div></div>`);
      two.querySelector('.xp-pt').onchange = e => { st.parityTarget = e.target.value; renderResult() };
      const pts = c.parity[st.parityTarget] || [];
      two.querySelector('.xp-par').appendChild(parityChart(pts, c.summary[st.parityTarget]));
      two.querySelector('.xp-par').appendChild(h(`<figcaption class="small muted">점선 = 예측과 실측이 같은 선. 가로 막대 = 예측의 불확실 폭.</figcaption>`));
      two.querySelector('.xp-resb').appendChild(residualChart(pts, c.summary[st.parityTarget]));
      P.appendChild(two);
    }
    // 표
    const tbl = h(`<div class="card xp-res"><h3 style="margin:0 0 6px">런 × 단계 × 대상</h3><div class="xp-grid"><table><thead><tr><th>런</th><th>단계</th><th>대상</th><th class="num">실측</th><th class="num">예측 [폭]</th><th class="num">잔차</th><th>메모</th><th>근거</th></tr></thead><tbody></tbody></table></div></div>`);
    const tb = tbl.querySelector('tbody');
    for (const r of c.runs) {
      for (const p of r.pairs) {
        const tr = h(`<tr><td class="small">${esc(r.alias)}<div class="muted">${esc(r.label || '')}</div></td><td class="small">${esc(p.step_label)}</td><td class="small">${esc(p.label)}</td>
          <td class="r">${p.measured_text && (p.measured == null || /^[<>≤≥]/.test(p.measured_text)) ? esc(p.measured_text) : fmt(p.measured, 3)}${p.measured_db != null ? `<div class="small muted">건량 ${fmt(p.measured_db, 3)}</div>` : ''}</td>
          <td class="r">${p.predicted == null ? '-' : `${fmt(p.predicted, 3)} <span class="pr-band">${fmt(p.low, 2)}–${fmt(p.high, 2)}</span>`}</td>
          <td class="r ${p.residual > 0 ? 'pos' : p.residual < 0 ? 'neg' : ''}">${p.residual == null ? '-' : (p.residual > 0 ? '+' : '') + fmt(p.residual, 3)}${p.within_band === false ? ' <span class="pill warn">폭 밖</span>' : ''}</td>
          <td class="small muted">${esc([p.note, p.conversion, ...(p.warnings || []).map(w => w.kind === 'extrapolation' ? '외삽' : w.text)].filter(Boolean).join(' · '))}</td><td></td></tr>`);
        if (p.ev && c.evidence[p.ev]) tr.lastElementChild.appendChild(evidenceBlock(c.evidence[p.ev], 'cmp:' + p.ev));
        tb.appendChild(tr);
      }
      for (const e of r.errors) tb.appendChild(h(`<tr><td class="small">${esc(r.alias)}</td><td colspan="7" class="err">${esc(e.step)}: ${esc(e.error)}</td></tr>`));
    }
    P.appendChild(tbl);
    P.appendChild(sensCard());
    P.appendChild(calCard());
    P.appendChild(sugCard());
  }

  function sensCard() {
    const prm = st.params[st.exp.exp_id] || [];
    const steps = st.exp.flow.steps.filter(s => s.enabled !== false);
    const s0 = st.sensReq || {step_key: (prm.find(p => p.param === 'temp_c' && steps.find(s => s.key === p.step_key)?.type === 'dry') || prm[0] || {}).step_key,
      param: (prm.find(p => p.param === 'temp_c' && steps.find(s => s.key === p.step_key)?.type === 'dry') || prm[0] || {}).param, target: 'moisture'};
    if (!s0.target_step) s0.target_step = s0.step_key;
    const card = h(`<div class="card"><h3 style="margin:0 0 6px">민감도 — 값 하나를 바꾸면</h3>
      <div class="xp-tool"><label class="small">바꿀 값 <select class="inp xp-sp">${prm.map(p => `<option value="${p.step_key}.${p.param}"${p.step_key === s0.step_key && p.param === s0.param ? ' selected' : ''}>${esc(p.step_label)} · ${esc(p.label)} (${esc(p.unit)})</option>`).join('')}</select></label>
      <label class="small">결과 단계 <select class="inp xp-ts">${steps.map(s => `<option value="${s.key}"${s.key === s0.target_step ? ' selected' : ''}>${esc(s.label)}</option>`).join('')}</select></label>
      <label class="small">결과 <select class="inp xp-tt">${['moisture', 'tpc_ret', 'tpc', 'mass', 'time_target', 'energy', 'tpc_extract_yield', 'sieve_yield'].map(k => `<option value="${k}"${k === s0.target ? ' selected' : ''}>${esc(tgtInfo(k).label)}</option>`).join('')}</select></label>
      <label class="small">기준 런 <select class="inp xp-br"><option value="">흐름 기본값</option>${st.exp.runs.map(r => `<option value="${r.xrun_id}"${r.xrun_id === s0.base_run ? ' selected' : ''}>${esc(r.alias)} ${esc(r.label || '')}</option>`).join('')}</select></label>
      <button class="btn sm primary xp-go" type="button">그리기</button></div>
      <figure class="xp-chart xp-sens" style="margin-top:8px"></figure></div>`);
    const draw = async () => {
      const [sk, pm] = card.querySelector('.xp-sp').value.split('.');
      st.sensReq = {step_key: sk, param: pm, target_step: card.querySelector('.xp-ts').value, target: card.querySelector('.xp-tt').value, base_run: card.querySelector('.xp-br').value || null};
      const fig = card.querySelector('.xp-sens');
      fig.innerHTML = '<div class="small muted">계산 중…</div>';
      try {
        st.sens = await json(`${B}/experiments/${st.exp.exp_id}/sensitivity`, {method: 'POST', body: st.sensReq});
        fig.innerHTML = '';
        fig.appendChild(lineChart(st.sens));
        const lg = ['<i class="k cur"></i>기준 조건', '<i class="k band"></i>불확실 폭'];
        if (st.sens.measured.length) lg.push('<i class="k meas"></i>내 실측');
        fig.appendChild(h(`<div class="pr-legend small muted">${lg.map(x => `<span>${x}</span>`).join('')}</div>`));
        fig.appendChild(h(`<figcaption class="small muted">${esc(st.sens.note)}${st.sens.errors.length ? ' 일부 구간 오류: ' + esc(st.sens.errors.join(' / ')) : ''}</figcaption>`));
      } catch (ex) { fig.innerHTML = `<div class="err">${esc(ex.message)}</div>` }
    };
    card.querySelector('.xp-go').onclick = draw;
    if (st.sens && st.sensReq) { requestAnimationFrame(() => { const fig = card.querySelector('.xp-sens'); fig.appendChild(lineChart(st.sens)); fig.appendChild(h(`<figcaption class="small muted">${esc(st.sens.note)}</figcaption>`)) }) }
    else if (prm.length) requestAnimationFrame(draw);
    return card;
  }

  function calCard() {
    const card = h(`<div class="card xp-cal"><div class="row"><h3 class="grow" style="margin:0">내 데이터로 보정</h3>
      ${st.exp.calibration_applied ? '<span class="pill ok">보정에 적용됨</span>' : '<span class="pill off">보정에 안 씀</span>'}</div>
      <p class="small muted" style="margin:4px 0">건조 단계의 내 실측(건조 전후 수분·TPC)을 건조 예측의 보정 근거로 씁니다 — CoA 실측과 함께 n을 셉니다. 적용 전에는 문헌·CoA만 씁니다. 문헌 값을 몰래 바꾸지 않고, 바뀌는 것을 전·후로 보입니다.</p>
      <div class="xp-tool"><label class="small"><input type="checkbox" class="xp-ea"${st.calEa ? ' checked' : ''}> Ea(활성화 에너지)도 내 자료로 맞춤 <span class="muted">(서로 다른 온도 3개 이상일 때만)</span></label>
      <button class="btn sm xp-calprev" type="button">보정 미리보기</button>
      <button class="btn sm primary xp-calapply" type="button">${st.exp.calibration_applied ? '설정 다시 적용' : '보정에 적용'}</button>
      ${st.exp.calibration_applied ? '<button class="btn sm xp-calremove" type="button">보정에서 빼기</button>' : ''}</div>
      <div class="xp-calbody"></div></div>`);
    const body = card.querySelector('.xp-calbody');
    const ea = card.querySelector('.xp-ea');
    ea.onchange = () => { st.calEa = ea.checked; preview() };
    async function preview() {
      body.innerHTML = '<div class="small muted">계산 중…</div>';
      try { st.cal = await json(`${B}/experiments/${st.exp.exp_id}/calibrate/preview`, {method: 'POST', body: {use_ea_fit: !!st.calEa}}); drawCal() }
      catch (ex) { body.innerHTML = `<div class="err">${esc(ex.message)}</div>` }
    }
    async function applyCal(include) {
      try {
        const r = await json(`${B}/experiments/${st.exp.exp_id}/calibrate/apply`, {method: 'POST', body: {include, use_ea_fit: !!st.calEa}});
        toast(include ? '보정에 적용했습니다 — 건조 방식 탭의 예측에도 쓰입니다.' : '보정에서 뺐습니다.');
        st.cal = r.preview; st.exp = await json(`${B}/experiments/${st.exp.exp_id}`); st.cmp = null; await simulate();
        renderHead(); renderResult();
      } catch (ex) { fail(ex) }
    }
    card.querySelector('.xp-calprev').onclick = preview;
    card.querySelector('.xp-calapply').onclick = () => applyCal(true);
    card.querySelector('.xp-calremove')?.addEventListener('click', () => applyCal(false));
    function drawCal() {
      const v = st.cal;
      ea.disabled = !v.ea_possible;
      if (!v.ea_possible && ea.checked) { ea.checked = false; st.calEa = false }
      const row = (lab, b, a, unit = '') => `<tr><th scope="row">${lab}</th><td class="num">${b}</td><td class="num${b !== a ? ' chg' : ''}">${a}</td><td class="small muted">${unit}</td></tr>`;
      const fac = x => x?.applied ? fmt(x.factor, 3) : '보정 없음(문헌)';
      const nn = x => x?.applied ? `${x.n} (CoA ${x.n_coa ?? x.n} · 실험 ${x.n_exp ?? 0})` : '0';
      const eaS = (x, lit) => x?.ea?.applied ? `${fmt(x.ea.ea_kj, 2)} (내 맞춤)` : `${fmt(lit, 2)} (문헌 맞춤)`;
      const err = (s, k) => s?.[k] ? `${fmt(s[k].rmse, 3)} (n=${s[k].n})` : '-';
      const L = v.literature_only;
      body.innerHTML = `<table style="margin-top:6px"><thead><tr><th></th><th class="num">보정 전</th><th class="num">이 실험 넣은 뒤</th><th></th></tr></thead><tbody>
        ${row('건조 속도 배율 c', fac(v.before.dry), fac(v.after.dry), '× 문헌 k(T)')}
        ${row('건조 보정 n', nn(v.before.dry), nn(v.after.dry))}
        ${row('건조 Ea', eaS(v.before.dry, L.dry_ea_kj), eaS(v.after.dry, L.dry_ea_kj), 'kJ/mol')}
        ${row('배율 맞춤 RMSE(ln k)', fmt(v.before.dry?.rmse_ln, 3), fmt(v.after.dry?.ea?.applied ? v.after.dry.ea.rmse_ln : v.after.dry?.rmse_ln, 3))}
        ${row('TPC 손실 배율', fac(v.before.tpc), fac(v.after.tpc), '× 문헌 k(T)')}
        ${row('TPC 보정 n', nn(v.before.tpc), nn(v.after.tpc))}
        ${row('TPC Ea', eaS(v.before.tpc, L.tpc_ea_kj), eaS(v.after.tpc, L.tpc_ea_kj), 'kJ/mol')}
        ${row('이 실험 건조 후 수분 RMSE', err(v.before.summary, 'moisture'), err(v.after.summary, 'moisture'), '% 습량')}
        ${row('이 실험 건조 후 TPC RMSE', err(v.before.summary, 'tpc'), err(v.after.summary, 'tpc'), 'mg GAE/g')}
        </tbody></table>
        ${v.after.dry?.message ? `<p class="small" style="margin:6px 0 2px"><b>건조:</b> ${esc(v.after.dry.message)}. ${esc(v.after.dry.ea?.message || '')}</p>` : ''}
        ${v.after.tpc?.message ? `<p class="small" style="margin:2px 0"><b>TPC:</b> ${esc(v.after.tpc.message)}. ${esc(v.after.tpc.ea?.message || '')}</p>` : ''}
        <h4 style="margin:10px 0 4px;font-size:12.5px">이 실험의 런 (서로 다른 온도 ${v.distinct_temps.length}개: ${v.distinct_temps.map(t => fmt(t, 0)).join(', ')} ℃)</h4>
        <div class="xp-grid"><table><thead><tr><th>런</th><th>방식</th><th class="num">온도</th><th class="num">시간</th><th class="num">건조 전 수분</th><th>출처</th><th class="num">건조 후</th><th class="num">TPC</th><th>속도 보정</th><th>TPC 보정</th><th>못 쓰는 이유</th></tr></thead><tbody>
        ${v.runs.map(r => `<tr><td>${esc(r.alias)}</td><td>${esc(r.method)}</td><td class="num">${fmt(r.temp_c, 0)}</td><td class="num">${fmt(r.time_h, 1)}</td><td class="num">${fmt(r.moist_init, 1)}</td><td class="small muted">${esc(r.init_from || '-')}</td>
          <td class="num">${fmt(r.moist_final, 1)}</td><td class="num">${fmt(r.tpc, 2)}</td><td>${r.usable.dry ? '<span class="pill ok">씀</span>' : '-'}</td><td>${r.usable.tpc ? '<span class="pill ok">씀</span>' : r.usable.tpc_ref ? '<span class="pill">기준</span>' : '-'}</td><td class="small muted">${esc(r.reasons.join(' · '))}</td></tr>`).join('')}</tbody></table></div>
        ${pointTable(v.after.dry, '건조 속도 — 점별 (문헌만 → 보정 후)', 'dry')}
        ${pointTable(v.after.tpc, 'TPC — 점별 (문헌만 → 보정 후)', 'tpc')}
        <details class="small" style="margin-top:6px"><summary>보정 규칙</summary><ul>${v.rules.map(r => `<li>${esc(r)}</li>`).join('')}</ul></details>`;
    }
    function pointTable(cal, title, kind) {
      const pts = (cal?.points || []);
      if (!pts.length) return '';
      return `<h4 style="margin:10px 0 4px;font-size:12.5px">${esc(title)}</h4><div class="xp-grid"><table><thead><tr><th>시료·런</th><th class="num">온도</th><th class="num">시간</th><th class="num">k 실측</th><th class="num">k 문헌</th><th class="num">문헌만 예측</th><th class="num">보정 후 예측</th><th class="num">실측</th><th class="num">잔차 전 → 후</th></tr></thead><tbody>
        ${pts.map(p => kind === 'dry' ? `<tr><td class="small">${esc(p.sample)}</td><td class="num">${fmt(p.temp_c, 0)}</td><td class="num">${fmt(p.time_h, 1)}</td><td class="num">${fmt(p.k_meas, 4)}</td><td class="num">${fmt(p.k_lit, 4)}</td><td class="num">${fmt(p.lit_final, 2)}%</td><td class="num">${fmt(p.pred_final, 2)}%</td><td class="num">${fmt(p.moist_final, 2)}%</td><td class="num">${fmt(p.residual_lit, 2)} → ${fmt(p.residual, 2)}</td></tr>`
          : `<tr><td class="small">${esc(p.sample)}</td><td class="num">${fmt(p.temp_c, 0)}</td><td class="num">${fmt(p.time_h, 1)}</td><td class="num">${fmt(p.k_meas, 4)}</td><td class="num">${fmt(p.k_lit, 4)}</td><td class="num">${fmt(p.lit_retention * 100, 1)}%</td><td class="num">${fmt(p.pred_retention * 100, 1)}%</td><td class="num">${fmt(p.retention * 100, 1)}%</td><td class="num">${fmt(p.residual_lit, 3)} → ${fmt(p.residual, 3)}</td></tr>`).join('')}</tbody></table></div>`;
    }
    if (st.cal) requestAnimationFrame(drawCal); else if (opts.autoCalibrate) requestAnimationFrame(preview);
    else body.innerHTML = '<p class="small muted">\'보정 미리보기\'를 누르면 보정 전·후를 나란히 보입니다. 저장은 \'보정에 적용\'을 눌러야 합니다.</p>';
    return card;
  }

  function sugCard() {
    const card = h(`<div class="card xp-sug"><div class="row"><h3 class="grow" style="margin:0">다음 실험 제안</h3><span class="pill xp-badge-sug">제안</span><button class="btn sm xp-sg" type="button">제안 받기</button></div><div class="xp-sgbody"></div></div>`);
    const body = card.querySelector('.xp-sgbody');
    const fmtP = p => !p ? '-' : `${fmt(p.value, 2)} <span class="pr-band">${fmt(p.low, 1)}–${fmt(p.high, 1)}</span>`;
    function draw() {
      const s = st.sug;
      body.innerHTML = `<p class="small muted" style="margin:4px 0">${esc(s.disclaimer)}</p>${s.notes.map(n => `<p class="small" style="margin:2px 0">${esc(n)}</p>`).join('')}
        ${s.validity ? `<p class="small muted" style="margin:2px 0">근거 범위: ${esc(s.validity.method)} ${s.validity.temp_range.map(t => fmt(t, 0)).join('–')} ℃ (${esc(s.validity.source)})</p>` : ''}
        ${s.gap_fill.length ? `<h4 style="margin:8px 0 4px;font-size:12.5px">빈 온도 채우기</h4><table><thead><tr><th class="num">온도</th><th class="num">시간</th><th class="num">예상 수분 %</th><th class="num">TPC 잔존 %</th><th>왜</th></tr></thead><tbody>
          ${s.gap_fill.map(g => `<tr><td class="num">${fmt(g.temp_c, 0)} ℃</td><td class="num">${fmt(Object.values(g.conditions)[0].time_h, 1)} h</td><td class="num">${fmtP(g.predicted.moisture)}</td><td class="num">${fmtP(g.predicted.tpc_ret)}</td><td class="small muted">${esc(g.why)}</td></tr>`).join('')}</tbody></table>` : ''}
        ${s.factorial.map((f, i) => `<h4 style="margin:10px 0 4px;font-size:12.5px">${esc(f.step_label)} — ${esc(f.design)}</h4><p class="small muted" style="margin:0 0 4px">${esc(f.why)}</p>
          <table><thead><tr>${f.factors.map(x => `<th class="num">${esc(x.label)} (${esc(x.unit)})</th>`).join('')}<th class="num">예상 수분 %</th><th class="num">TPC 잔존 %</th>${f.rows[0]?.predicted?.tpc_extract_yield ? '<th class="num">TPC 추출 수율 %</th>' : ''}<th></th></tr></thead><tbody>
          ${f.rows.map(r => `<tr class="${r.done ? 'done' : ''}">${f.factors.map(x => `<td class="num">${fmt(r[x.key], 1)}</td>`).join('')}<td class="num">${fmtP(r.predicted.moisture)}</td><td class="num">${fmtP(r.predicted.tpc_ret)}</td>${r.predicted.tpc_extract_yield ? `<td class="num">${fmtP(r.predicted.tpc_extract_yield)}</td>` : ''}<td class="small">${r.done ? '이미 함' : ''}</td></tr>`).join('')}</tbody></table>
          <button class="btn sm xp-mk" data-i="${i}" type="button" style="margin-top:4px">이 배치로 빈 런 만들기(계획으로 저장)</button>`).join('')}`;
      body.querySelectorAll('.xp-mk').forEach(b => b.onclick = async () => {
        const d = st.sug.factorial[Number(b.dataset.i)];
        if (!confirm(`${d.design}의 아직 안 한 조건 ${d.rows.filter(r => !r.done).length}개로 빈 런을 만들까요? 실측은 실험하면서 채웁니다.`)) return;
        try { const r = await json(`${B}/experiments/${st.exp.exp_id}/plan`, {method: 'POST', body: {design: d, add_runs: true}}); toast(`계획을 저장하고 빈 런 ${r.runs.length}개를 만들었습니다.`); st.exp = await json(`${B}/experiments/${st.exp.exp_id}`); st.cmp = null; select('data') }
        catch (ex) { fail(ex) }
      });
    }
    card.querySelector('.xp-sg').onclick = async () => {
      body.innerHTML = '<div class="small muted">계산 중…</div>';
      try { st.sug = await json(`${B}/experiments/${st.exp.exp_id}/suggest`); draw() } catch (ex) { body.innerHTML = `<div class="err">${esc(ex.message)}</div>` }
    };
    if (st.sug) requestAnimationFrame(draw);
    return card;
  }

  // ---------------------------------------------------------------- 시작
  const api = {
    open, select,
    async refresh() { await loadList(); if (st.exp) await open(st.exp.exp_id) },
    setProject(p) { st.project = p || '' },
    dispose() { st.disposed = true; clearTimeout(st.paramTimer); shell.remove() },
    get state() { return {exp: st.exp, tab: st.tab, sel: st.sel} },
  };
  (async () => {
    try {
      st.cat = await json(`${B}/steps`);
      buildChoiceLists();
      await loadList();
      select(st.tab);
      const want = opts.expId === 'first' ? st.list[0]?.exp_id : opts.expId || store.get('last') || st.list[0]?.exp_id;
      if (opts.step) st.sel = opts.step;
      await open(st.list.some(x => x.exp_id === want) ? want : st.list[0]?.exp_id);
    } catch (ex) { fail(ex); root.querySelector('[data-panel=flow]').innerHTML = `<div class="xp-empty err">${esc(ex.message)}</div>` }
  })();
  $('.xp-sel').addEventListener('change', e => store.set('last', e.target.value));
  return api;
}

// ---------------------------------------------------------------- 표시 도우미
function valStr(v) {
  if (v === null || v === undefined) return '-';
  if (Array.isArray(v)) return v.map(x => fmt(x, 4)).join('–');
  if (typeof v === 'object') return Object.entries(v).map(([k, x]) => `${k}: ${typeof x === 'number' ? fmt(x, 4) : x}`).join(' · ');
  return typeof v === 'number' ? fmt(v, 4) : String(v);
}
function validityStr(v) {
  if (!v) return '';
  const nm = {temp_c: '온도 ℃', air_velocity_ms: '풍속 m/s', thickness_mm: '두께 mm', pressure_pa: '압력 Pa', mesh_um: '체 눈 µm', ethanol_pct: '에탄올 %'};
  const parts = Object.entries(v).map(([k, r]) => k === 'byproduct' ? `대상: ${r}` : Array.isArray(r) ? `${nm[k] || k} ${r[0]}–${r[1]}` : `${k}: ${r}`);
  return parts.length ? `<div class="muted">유효 범위: ${esc(parts.join(' · '))}</div>` : '';
}
function badge(type, n) { return `<span class="pr-b ${type}">${TYPE_LABEL[type]} ${esc(n)}</span>` }
function evBadge(ev) {
  if (ev.type === 'literature') return `<span class="pr-b literature">문헌${ev.verified ? ' ✓DOI확인' : ''}</span>${ev.derived ? '<span class="pr-b derived">유도값</span>' : ''}`;
  if (ev.type === 'measured') return `<span class="pr-b measured">실측 n=${esc(ev.n)}</span>`;
  if (ev.type === 'equipment') return '<span class="pr-b equipment">설비 사양</span>';
  if (ev.type === 'input') return '<span class="pr-b input">내 입력</span>';
  return '<span class="pr-b assumption">가정</span>';
}
function ticks(a, b, n) {
  const span = b - a, step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0 || 1)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= step0) || step0 || 1;
  const out = [];
  for (let t = Math.ceil(a / step) * step; t <= b + 1e-9; t += step) out.push(+t.toFixed(10));
  return out;
}
function svgEl(W, H, label) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('class', 'pr-svg');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', label);
  return svg;
}

/** 패리티: x = 예측, y = 실측, 가로 막대 = 예측 폭 */
function parityChart(pts, s) {
  const W = 320, H = 260, L = 44, R = 10, T = 14, Bm = 34;
  const all = pts.flatMap(p => [p.pred, p.meas, p.low, p.high]).filter(v => v != null && Number.isFinite(v));
  if (!all.length) { const e = svgEl(W, H, '그릴 점 없음'); e.innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" class="pr-ax">그릴 점이 없습니다</text>`; return e }
  let a = Math.min(...all), b = Math.max(...all);
  const pad = (b - a) * 0.08 || Math.abs(a) * 0.1 || 1; a -= pad; b += pad;
  const sx = x => L + (x - a) / (b - a) * (W - L - R), sy = y => T + (1 - (y - a) / (b - a)) * (H - T - Bm);
  let g = '';
  for (const t of ticks(a, b, 4)) g += `<line x1="${L}" x2="${W - R}" y1="${sy(t)}" y2="${sy(t)}" class="pr-grid"/><text x="${L - 4}" y="${sy(t) + 3}" text-anchor="end" class="pr-ax">${fmt(t, 1)}</text><text x="${sx(t)}" y="${H - Bm + 13}" text-anchor="middle" class="pr-ax">${fmt(t, 1)}</text>`;
  g += `<line x1="${sx(a)}" y1="${sy(a)}" x2="${sx(b)}" y2="${sy(b)}" class="xp-11"/>`;
  g += `<text x="${(L + W - R) / 2}" y="${H - 4}" text-anchor="middle" class="pr-ax">예측 (${esc(s.unit)})</text><text x="4" y="10" class="pr-ax">실측</text>`;
  for (const p of pts) {
    if (p.low != null && p.high != null) g += `<line x1="${sx(Math.min(p.low, p.high))}" x2="${sx(Math.max(p.low, p.high))}" y1="${sy(p.meas)}" y2="${sy(p.meas)}" stroke="var(--v-accent)" stroke-opacity=".45" stroke-width="3" stroke-linecap="round"/>`;
    g += `<circle cx="${sx(p.pred)}" cy="${sy(p.meas)}" r="5" class="pr-meas xp-pt"><title>${esc(p.run)} ${esc(p.step)}: 예측 ${fmt(p.pred, 2)} · 실측 ${fmt(p.meas, 2)}</title></circle>`;
  }
  const svg = svgEl(W, H, `${s.label} 패리티 그림: ${pts.length}점, RMSE ${fmt(s.rmse, 3)} ${s.unit}`);
  svg.innerHTML = g;
  return svg;
}

function residualChart(pts, s) {
  const W = 320, H = 200, L = 44, R = 10, T = 14, Bm = 40;
  const svg = svgEl(W, H, `${s.label} 런별 잔차: 평균 ${fmt(s.bias, 3)}`);
  if (!pts.length) return svg;
  const res = pts.map(p => p.meas - p.pred);
  const m = Math.max(...res.map(Math.abs), 1e-9) * 1.15;
  const sy = y => T + (1 - (y + m) / (2 * m)) * (H - T - Bm);
  const bw = (W - L - R) / pts.length;
  let g = '';
  for (const t of ticks(-m, m, 4)) g += `<line x1="${L}" x2="${W - R}" y1="${sy(t)}" y2="${sy(t)}" class="pr-grid"/><text x="${L - 4}" y="${sy(t) + 3}" text-anchor="end" class="pr-ax">${fmt(t, 2)}</text>`;
  g += `<line x1="${L}" x2="${W - R}" y1="${sy(0)}" y2="${sy(0)}" class="xp-res0"/>`;
  pts.forEach((p, i) => {
    const r = res[i], x = L + i * bw + bw * 0.2, y0 = sy(0), y1 = sy(r);
    g += `<rect x="${x}" width="${bw * 0.6}" y="${Math.min(y0, y1)}" height="${Math.max(1, Math.abs(y1 - y0))}" class="${r >= 0 ? 'xp-bar-pos' : 'xp-bar-neg'}"><title>${esc(p.run)}: 잔차 ${fmt(r, 3)}</title></rect>`;
    g += `<text x="${x + bw * 0.3}" y="${H - Bm + 12}" text-anchor="middle" class="pr-ax">${esc(p.run.replace('런 ', '#'))}</text>`;
  });
  g += `<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle" class="pr-ax">잔차 = 실측 − 예측 (${esc(s.unit)})</text>`;
  svg.innerHTML = g;
  return svg;
}

/** 민감도 선 그래프. d.points = [[x, y, lo, hi]], d.measured = [{x, y, label}] */
function lineChart(d) {
  const W = 520, H = 230, L = 46, R = 12, T = 22, Bm = 36;
  const pts = (d.points || []).filter(p => p[1] != null);
  const xs = pts.map(p => p[0]).concat((d.measured || []).map(m => m.x));
  const ys = pts.flatMap(p => [p[1], p[2], p[3]]).filter(v => v != null && Number.isFinite(v)).concat((d.measured || []).map(m => m.y));
  if (!pts.length || !ys.length) { const e = svgEl(W, H, '그릴 값 없음'); e.innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" class="pr-ax">이 범위에서 그릴 값이 없습니다(단계 오류·목표 미도달 등)</text>`; return e }
  let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(0, ...ys), y1 = Math.max(...ys) * 1.08;
  if (x1 === x0) x1 = x0 + 1; if (y1 <= y0) y1 = y0 + 1;
  const sx = x => L + (x - x0) / (x1 - x0) * (W - L - R), sy = y => T + (1 - (y - y0) / (y1 - y0)) * (H - T - Bm);
  const path = arr => arr.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join('');
  let s = '';
  for (const t of ticks(y0, y1, 4)) s += `<line x1="${L}" x2="${W - R}" y1="${sy(t)}" y2="${sy(t)}" class="pr-grid"/><text x="${L - 4}" y="${sy(t) + 3}" text-anchor="end" class="pr-ax">${fmt(t, 1)}</text>`;
  for (const t of ticks(x0, x1, 6)) s += `<text x="${sx(t)}" y="${H - Bm + 13}" text-anchor="middle" class="pr-ax">${fmt(t, 1)}</text>`;
  s += `<text x="${(L + W - R) / 2}" y="${H - 4}" text-anchor="middle" class="pr-ax">${esc(d.x_label)}</text><text x="4" y="12" class="pr-ax">${esc(d.y_label)}</text>`;
  const bp = pts.filter(p => p[2] != null && p[3] != null);
  if (bp.length > 1) {
    const up = bp.map(p => [p[0], Math.max(p[2], p[3])]), dn = bp.map(p => [p[0], Math.min(p[2], p[3])]).reverse();
    s += `<path d="${path(up)}${dn.map(p => `L${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join('')}Z" class="pr-bandfill"/>`;
  }
  s += `<path d="${path(pts)}" class="pr-line"/>`;
  for (const m of d.measured || []) s += `<circle cx="${sx(m.x)}" cy="${sy(m.y)}" r="4.5" class="pr-meas"><title>실측 ${esc(m.label)}</title></circle>`;
  if (d.current && d.current[1] != null) s += `<circle cx="${sx(d.current[0])}" cy="${sy(d.current[1])}" r="5" class="pr-cur"><title>기준 조건 ${fmt(d.current[0], 1)} → ${fmt(d.current[1], 2)}</title></circle>`;
  const svg = svgEl(W, H, `${d.y_label} 대 ${d.x_label}${(d.measured || []).length ? `, 실측 ${d.measured.length}점` : ''}`);
  svg.innerHTML = s;
  if (!reducedMotion()) svg.classList.add('pr-anim');
  return svg;
}
