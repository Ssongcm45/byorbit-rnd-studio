// 통계 분석 — 데이터 고르기 → 변수 역할 → 분석 실행 → 가정 점검·표 1·그림 1·해석 세 문장 → 내보내기
//   import {mountStats} from '/static/stats/stats.js';
//   mountStats(el, {api, toast, project, expId?, demo?})  → {open(expId), openDemo(levels), refresh(), dispose(), state}
// 계산은 모두 서버(/api/stats — 시험된 기준)가 한다. 이 파일은 입력·표시만. 밖으로 보내는 요청은 없다.
import {esc, fmt, h, makeApi} from '../viz/common.js';

const B = '/api/stats';
const STATUS = {pass: ['통과', 'ok'], warn: ['주의', 'warn'], fail: ['실패', 'bad'], info: ['설계로 판단', 'off']};
const STATUS_EN = {pass: 'Pass', warn: 'Caution', fail: 'Fail', info: 'Design-based'};
const TYPE_LABEL = {continuous: '연속', categorical: '범주', id: '런 이름·번호', ignore: '쓰지 않음'};
let uid = 0;

function ensureCss() {
  for (const [k, href] of [['bv-css', '../viz/viz.css'], ['st-css', './stats.css']]) {
    if (document.querySelector(`link[data-${k}]`)) continue;
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = new URL(href, import.meta.url).href;
    l.setAttribute(`data-${k}`, '1');
    document.head.appendChild(l);
  }
}

const mem = {
  get(k) { try { return JSON.parse(localStorage.getItem('st:' + k) || 'null') } catch { return null } },
  set(k, v) { try { localStorage.setItem('st:' + k, JSON.stringify(v)) } catch { /* 저장 못 해도 화면은 그대로 */ } },
};

export function mountStats(el, opts = {}) {
  ensureCss();
  const {json} = makeApi(opts.api);
  const base = typeof opts.api === 'string' ? opts.api.replace(/\/$/, '') : '';
  const toast = opts.toast || (m => console.info(m));
  const id = 'st' + (++uid);
  const st = {kind: opts.expId ? 'experiment' : 'demo', expId: opts.expId || null, levels: opts.demo || 2, censored: 'exclude',
    upload: null, mapping: null, ds: null, spec: null, res: null, lang: mem.get('lang') || 'ko', width: mem.get('width') || 'double',
    zero: 'auto', test: 'welch', alpha: 0.05, datasets: null, busy: false, disposed: false};
  const inBv = !!el.closest('.bv');
  const root = h(`<section class="sx" aria-labelledby="${id}-t">
    <div class="sx-top"><div class="grow"><h2 id="${id}-t" data-help="stats">통계 분석</h2>
      <p class="sub small muted">수율에 온도·시간·산 종류가 주는 영향을 회귀분석하고, 산 종류별 차이를 t검정합니다. 가정 점검, 논문용 표 1개·그림 1장·해석 세 문장, Python·R·Stata 재현 파일을 만듭니다. 모든 계산은 이 PC 안에서만 합니다.</p></div></div>
    <ol class="sx-steps">
      <li class="card sx-s1"><h3 data-help="stats.source"><span class="sx-n">1</span>데이터 고르기 · 변수 역할</h3><div class="sx-src"></div><div class="sx-prev"></div><div class="sx-roles"></div></li>
      <li class="card sx-s2"><h3><span class="sx-n">2</span>분석 실행</h3><div class="sx-runbox"></div></li>
      <li class="card sx-s3"><h3><span class="sx-n">3</span>결과</h3><div class="sx-res"><p class="empty">분석을 실행하면 가정 점검·표 1·그림 1·해석이 여기에 나옵니다.</p></div></li>
      <li class="card sx-s4"><h3><span class="sx-n">4</span>내보내기</h3><div class="sx-exp"><p class="empty">분석을 실행한 뒤 내려받을 수 있습니다.</p></div></li>
    </ol>
    <div class="sr-only" aria-live="polite" id="${id}-live"></div>
  </section>`);
  const shell = inBv ? root : h('<div class="bv"></div>');
  if (!inBv) shell.appendChild(root);
  el.appendChild(shell);
  const $ = s => root.querySelector(s);
  const say = m => { $(`#${id}-live`).textContent = m };
  const fail = e => { const m = e.message || String(e); toast(m); say(m) };
  const fileUrl = (name, extra = {}) => {
    const q = new URLSearchParams({lang: st.lang, width: st.width, zero: st.zero, ...extra});
    return `${base}${B}/results/${st.res.result_id}/files/${name}?${q}`;
  };

  // ---------------------------------------------------------------- ① 데이터 출처
  function source() {
    if (st.kind === 'experiment') return {kind: 'experiment', exp_id: st.expId, censored: st.censored};
    if (st.kind === 'upload') return {kind: 'upload', token: st.upload?.token, mapping: st.mapping, censored: st.censored};
    return {kind: 'demo', levels: st.levels};
  }

  function renderSource() {
    const c = $('.sx-src');
    const exps = st.datasets?.experiments || [];
    c.innerHTML = `<div class="seg" role="group" aria-label="데이터 출처">
        ${[['experiment', '내 실험'], ['upload', '파일 (CSV·XLSX)'], ['demo', '예시 (가짜)']].map(([k, l]) => `<button type="button" data-kind="${k}" aria-pressed="${st.kind === k}">${l}</button>`).join('')}
      </div>
      <div class="sx-srcbody row" style="margin-top:10px"></div>`;
    c.querySelectorAll('[data-kind]').forEach(b => b.onclick = () => { st.kind = b.dataset.kind; st.res = null; renderSource(); if (st.kind !== 'upload' || st.upload) loadPreview(); else clearPreview() });
    const body = c.querySelector('.sx-srcbody');
    if (st.kind === 'experiment') {
      if (!exps.length) { body.innerHTML = '<p class="small muted">실험이 없습니다 — \'실험\' 탭에서 실험을 만들고 런을 넣거나, 파일·예시를 쓰세요.</p>'; return }
      if (!st.expId || !exps.some(x => x.exp_id === st.expId)) st.expId = exps[0].exp_id;
      body.innerHTML = `<label class="small">실험 <select class="inp sx-exp-sel">${exps.map(x => `<option value="${x.exp_id}"${x.exp_id === st.expId ? ' selected' : ''}>${esc(x.name)} — 런 ${x.n_runs}${x.confidentiality === '기밀' ? ' (기밀)' : ''}</option>`).join('')}</select></label>
        ${censoredSel()}
        <p class="small muted sx-hint">산 종류·용매 종류는 실험 데이터 탭의 조건 칸(추출 · 산 종류)에 넣으면 범주 변수가 됩니다. 예전처럼 런 비고에 <code>산=구연산</code>으로 적은 것도 읽습니다.</p>`;
      body.querySelector('.sx-exp-sel').onchange = e => { st.expId = e.target.value; st.res = null; loadPreview() };
    } else if (st.kind === 'upload') {
      body.innerHTML = `<label class="btn sm" style="cursor:pointer">파일 고르기<input type="file" class="sr-only sx-file" accept=".csv,.tsv,.txt,.xlsx,.xlsm"></label>
        <span class="small muted">${st.upload ? esc(st.upload.file_name) + ` — ${st.upload.n_rows}행` : '첫 줄에 열 이름, 둘째 줄부터 한 줄에 한 런. 예: 런, 온도(℃), 시간(min), 산, 수율(%)'}</span>${censoredSel()}`;
      body.querySelector('.sx-file').onchange = async e => {
        const f = e.target.files[0];
        if (!f) return;
        const fd = new FormData(); fd.append('file', f);
        try { st.upload = await json(`${B}/upload`, {method: 'POST', body: fd}); st.mapping = st.upload.mapping; st.res = null; renderSource(); loadPreview() }
        catch (ex) { fail(ex) }
      };
    } else {
      body.innerHTML = `<label class="small">예시 <select class="inp sx-demo">${(st.datasets?.demos || [{levels: 2, label: '구연산 vs 염산'}, {levels: 3, label: '구연산·염산·질산'}]).map(d => `<option value="${d.levels}"${+d.levels === +st.levels ? ' selected' : ''}>${esc(d.label)}</option>`).join('')}</select></label>
        <span class="pill warn">가짜 데이터 — 논문에 쓰지 마세요</span>`;
      body.querySelector('.sx-demo').onchange = e => { st.levels = +e.target.value; st.res = null; loadPreview() };
    }
    const cs = body.querySelector('.sx-cens');
    if (cs) cs.onchange = e => { st.censored = e.target.value; loadPreview() };
  }
  const censoredSel = () => `<label class="small">검출 한계(&lt; x) <select class="inp sx-cens">
      ${[['exclude', '결측으로 뺌(기본)'], ['limit', '한계값으로 넣음'], ['half', '한계의 1/2로 넣음']].map(([k, l]) => `<option value="${k}"${st.censored === k ? ' selected' : ''}>${l}</option>`).join('')}</select></label>`;

  function clearPreview() { st.ds = null; $('.sx-prev').innerHTML = ''; $('.sx-roles').innerHTML = ''; renderRun() }

  async function loadPreview() {
    if (st.kind === 'experiment' && !st.expId) return clearPreview();
    $('.sx-prev').innerHTML = '<p class="small muted">데이터를 읽는 중…</p>';
    try {
      st.ds = await json(`${B}/dataset/preview`, {method: 'POST', body: {source: source()}});
      st.spec = mergeSpec(st.ds.suggested);
      renderPreview(); renderRoles(); renderRun();
    } catch (ex) { st.ds = null; $('.sx-prev').innerHTML = `<p class="err">${esc(ex.message)}</p>`; $('.sx-roles').innerHTML = ''; renderRun() }
  }

  function mergeSpec(sug) {
    // 같은 이름의 변수가 남아 있으면 사용자가 고른 역할을 지킨다
    const names = new Set(st.ds.codebook.map(v => v.name));
    const prev = st.spec;
    if (!prev || !names.has(prev.outcome)) return {...sug, categorical: [...(sug.categorical || [])]};
    return {...prev, continuous: prev.continuous.filter(c => names.has(c)), categorical: prev.categorical.filter(c => names.has(c.name)),
      group: names.has(prev.group) ? prev.group : sug.group,
      interactions: (prev.interactions || []).filter(p => p.every(v => names.has(v))), quadratic: (prev.quadratic || []).filter(c => names.has(c)),
      xvar: names.has(prev.xvar) ? prev.xvar : null};
  }

  function renderPreview() {
    const ds = st.ds;
    const cb = ds.codebook;
    const miss = ds.missing || {};
    const rows = ds.rows.slice(0, 12);
    const cell = (v, name, i) => {
      const why = miss[name]?.[String(i)];
      if (v === null || v === undefined || v === '') return `<td class="sx-miss" title="${esc(why || '빈칸')}">· <span class="small">${esc(why || '빈칸')}</span></td>`;
      return typeof v === 'number' ? `<td class="num">${fmt(v, 4)}</td>` : `<td>${esc(v)}</td>`;
    };
    const mapEditor = st.kind === 'upload' && st.mapping ? `<details class="sx-map" open><summary>열 대응 (변수 이름은 R·Stata용 영문 소문자)</summary>
        <div class="sx-tablewrap"><table><thead><tr><th>파일 열</th><th>변수 이름</th><th>한국어 이름</th><th>단위</th><th>형식</th><th>예</th></tr></thead><tbody>
        ${st.mapping.map((m, i) => `<tr data-i="${i}"><td>${esc(m.header)}</td>
          <td><input class="inp sx-m-name" value="${esc(m.name)}" maxlength="32" aria-label="${esc(m.header)} 변수 이름" style="width:120px"></td>
          <td><input class="inp sx-m-label" value="${esc(m.label_ko)}" aria-label="${esc(m.header)} 한국어 이름" style="width:120px"></td>
          <td><input class="inp sx-m-unit" value="${esc(m.unit)}" aria-label="${esc(m.header)} 단위" style="width:70px"></td>
          <td><select class="inp sx-m-type" aria-label="${esc(m.header)} 형식">${Object.entries(TYPE_LABEL).map(([k, l]) => `<option value="${k}"${m.type === k ? ' selected' : ''}>${l}</option>`).join('')}</select></td>
          <td class="small muted">${esc((m.sample || []).join(', '))}</td></tr>`).join('')}
        </tbody></table></div><button type="button" class="btn sm primary sx-m-apply">열 대응 적용</button></details>` : '';
    const nMiss = Object.values(ds.missing_count || {}).reduce((a, b) => a + b, 0);
    $('.sx-prev').innerHTML = `
      ${ds.is_demo ? '<div class="notice"><b>예시 데이터는 가짜(모의)입니다.</b> 화면·내보내기 모두에 \'예시(모의) 데이터\'라고 표시됩니다. 실제 실험 데이터로 바꿔 쓰세요.</div>' : ''}
      ${(ds.warnings || []).filter(w => !ds.is_demo || !w.includes('가짜')).map(w => `<div class="info small">${esc(w)}</div>`).join('')}
      ${mapEditor}
      <div class="row" style="margin:8px 0 4px"><b class="grow">${esc(ds.title)}</b><span class="small muted">${ds.n}행 · 변수 ${cb.length}개${nMiss ? ` · 결측 칸 ${nMiss}개` : ''}</span></div>
      <div class="sx-tablewrap"><table class="sx-data"><thead><tr>${cb.map(v => `<th title="${esc(v.source || '')}">${esc(v.name)}<br><span class="sx-lab">${esc(v.label_ko)}${v.unit ? ` (${esc(v.unit)})` : ''} · ${TYPE_LABEL[v.type] || v.type}</span></th>`).join('')}</tr></thead>
        <tbody>${rows.map((r, i) => `<tr>${cb.map(v => cell(r[v.name], v.name, i)).join('')}</tr>`).join('')}</tbody></table></div>
      ${ds.n > rows.length ? `<p class="small muted">처음 ${rows.length}행만 보입니다(전체 ${ds.n}행은 모두 분석에 씁니다).</p>` : ''}`;
    const ap = $('.sx-m-apply');
    if (ap) ap.onclick = () => {
      $('.sx-map').querySelectorAll('tr[data-i]').forEach(tr => {
        const m = st.mapping[+tr.dataset.i];
        m.name = tr.querySelector('.sx-m-name').value.trim(); m.label_ko = tr.querySelector('.sx-m-label').value.trim();
        m.unit = tr.querySelector('.sx-m-unit').value.trim(); m.type = tr.querySelector('.sx-m-type').value;
      });
      st.res = null; loadPreview();
    };
  }

  function renderRoles() {
    const cb = st.ds.codebook;
    const cont = cb.filter(v => v.type === 'continuous');
    const cats = cb.filter(v => v.type === 'categorical');
    const sp = st.spec;
    const lab = v => `${esc(v.label_ko)}${v.unit ? ` (${esc(v.unit)})` : ''} <span class="muted">${esc(v.name)}</span>`;
    const catSel = sp.categorical[0]?.name || '';
    const catVar = cats.find(v => v.name === catSel);
    $('.sx-roles').innerHTML = `<div class="sx-rolegrid">
      <label><span data-help="stats.roles">결과 변수 <span class="muted">(연속)</span></span><select class="inp sx-out">${cont.map(v => `<option value="${v.name}"${v.name === sp.outcome ? ' selected' : ''}>${esc(v.label_ko)} — ${esc(v.name)}</option>`).join('')}</select></label>
      <fieldset><legend>연속 설명 변수</legend><div class="chips">${cont.filter(v => v.name !== sp.outcome).map(v => `<label class="chip"><input type="checkbox" value="${v.name}"${sp.continuous.includes(v.name) ? ' checked' : ''}> ${lab(v)}</label>`).join('') || '<span class="small muted">없음</span>'}</div></fieldset>
      <label><span>범주 설명 변수</span><select class="inp sx-cat"><option value="">없음</option>${cats.map(v => `<option value="${v.name}"${v.name === catSel ? ' selected' : ''}>${esc(v.label_ko)} — ${esc(v.name)} (${(v.levels || []).length}수준)</option>`).join('')}</select></label>
      <label><span>기준 수준</span><select class="inp sx-ref"${catVar ? '' : ' disabled'}>${(catVar?.levels || []).map(l => `<option value="${esc(l.value)}"${l.value === sp.categorical[0]?.reference ? ' selected' : ''}>${esc(l.label_ko)} (${esc(l.value)})</option>`).join('')}</select></label>
      <label><span>집단 비교(t검정) 변수</span><select class="inp sx-grp"><option value="">하지 않음</option>${cats.map(v => `<option value="${v.name}"${v.name === sp.group ? ' selected' : ''}>${esc(v.label_ko)} (${(v.levels || []).length}수준)</option>`).join('')}</select></label>
      <label><span>t검정 종류</span><select class="inp sx-test">${[['welch', 'Welch (기본 — 등분산 가정 없음)'], ['student', 'Student (등분산 가정)'], ['auto', 'Levene 보고 자동']].map(([k, l]) => `<option value="${k}"${(sp.test || st.test) === k ? ' selected' : ''}>${l}</option>`).join('')}</select></label>
      <label><span>유의수준 α</span><input class="inp sx-alpha" type="number" min="0.001" max="0.2" step="0.01" value="${sp.alpha ?? st.alpha}"></label>
      ${termsHtml()}
      </div>
      <p class="small muted sx-formula"></p>`;
    function termsHtml() {
      // 선택 항: 기본은 꺼짐(주효과만). 설명 변수 둘씩 짝 → 교호작용, 연속 변수 → 2차항(값 3개 이상 필요). 그림 1 가로축.
      const preds = [...sp.continuous, ...sp.categorical.map(c => c.name)];
      const nm = n => esc(cb.find(v => v.name === n)?.label_ko || n);
      sp.interactions = (sp.interactions || []).filter(p => p.every(v => preds.includes(v)));
      sp.quadratic = (sp.quadratic || []).filter(c => sp.continuous.includes(c));
      if (sp.xvar && !sp.continuous.includes(sp.xvar)) sp.xvar = null;
      const pairs = [];
      for (let i = 0; i < preds.length; i++) for (let j = i + 1; j < preds.length; j++) pairs.push([preds[i], preds[j]]);
      const has = p => sp.interactions.some(q => (q[0] === p[0] && q[1] === p[1]) || (q[0] === p[1] && q[1] === p[0]));
      const xdef = sp.continuous.find(c => c.startsWith('temp')) || sp.continuous[0];
      return `<fieldset class="sx-terms"><legend data-help="stats.terms">모형 항 (선택 — 기본은 주효과만)</legend><div class="chips">
          ${pairs.map(p => `<label class="chip"><input type="checkbox" class="sx-ix" value="${esc(p.join(':'))}"${has(p) ? ' checked' : ''}> ${nm(p[0])} × ${nm(p[1])}</label>`).join('')}
          ${sp.continuous.map(c => `<label class="chip"><input type="checkbox" class="sx-sq" value="${esc(c)}"${sp.quadratic.includes(c) ? ' checked' : ''}> ${nm(c)}² <span class="muted">2차항</span></label>`).join('')}
          ${!pairs.length && !sp.continuous.length ? '<span class="small muted">설명 변수를 두 개 이상 고르면 교호작용을, 연속 변수를 고르면 2차항을 넣을 수 있습니다.</span>' : ''}</div>
          <p class="small muted" style="margin:4px 0 0">곱항·2차항은 연속 변수를 표본 평균으로 중심화해 만듭니다. 계수가 늘어나므로 런 수(계수당 10개 이상 권장)를 확인하세요.</p></fieldset>
        <label><span>그림 1 가로축</span><select class="inp sx-xvar"${sp.continuous.length ? '' : ' disabled'}>${sp.continuous.map(c => `<option value="${esc(c)}"${(sp.xvar || xdef) === c ? ' selected' : ''}>${nm(c)}</option>`).join('') || '<option value="">연속 설명 변수 없음</option>'}</select></label>`;
    }
    const R = $('.sx-roles');
    const sync = () => {
      sp.outcome = R.querySelector('.sx-out').value;
      sp.continuous = [...R.querySelectorAll('fieldset:not(.sx-terms) input:checked')].map(x => x.value).filter(x => x !== sp.outcome);
      const cat = R.querySelector('.sx-cat').value;
      const ref = R.querySelector('.sx-ref').value;
      const cv = cats.find(v => v.name === cat);
      sp.categorical = cat ? [{name: cat, reference: cv?.levels?.some(l => l.value === ref) ? ref : cv?.levels?.[0]?.value}] : [];
      sp.group = R.querySelector('.sx-grp').value || null;
      sp.test = R.querySelector('.sx-test').value;
      sp.alpha = +R.querySelector('.sx-alpha').value || 0.05;
      sp.interactions = [...R.querySelectorAll('.sx-ix:checked')].map(x => x.value.split(':'));
      sp.quadratic = [...R.querySelectorAll('.sx-sq:checked')].map(x => x.value);
      sp.xvar = R.querySelector('.sx-xvar')?.value || null;
      formula();
    };
    const formula = () => {
      const rhs = [...sp.continuous, ...sp.categorical.map(c => `${c.name} (기준 = ${c.reference})`),
        ...(sp.quadratic || []).map(c => `${c}²`), ...(sp.interactions || []).map(p => p.join(' × '))];
      R.querySelector('.sx-formula').textContent = `모형: ${sp.outcome} ~ ${rhs.join(' + ') || '1'}` + (sp.group ? ` · 집단 비교: ${sp.group}` : '');
    };
    R.querySelectorAll('select, input').forEach(x => x.addEventListener('change', () => {
      const before = R.querySelector('.sx-cat').value;
      sync();
      const structural = x.classList.contains('sx-out') || x.classList.contains('sx-cat') || x.closest('fieldset:not(.sx-terms)');
      if (structural) {
        if (x.classList.contains('sx-cat') && before && !sp.group) sp.group = before;
        const key = x.className + '|' + x.value;
        renderRoles();
        // 다시 그린 뒤에도 키보드 초점을 같은 칸에 둔다
        [...$('.sx-roles').querySelectorAll('select, input')].find(y => y.className + '|' + y.value === key || (x.tagName === 'SELECT' && y.className === x.className))?.focus();
      }
    }));
    formula();
  }

  // ---------------------------------------------------------------- ② 실행
  function renderRun() {
    const c = $('.sx-runbox');
    c.innerHTML = `<div class="row"><button type="button" class="btn primary sx-go"${st.ds ? '' : ' disabled'}>분석 실행</button>
      <label class="small">언어 <select class="inp sx-lang"><option value="ko"${st.lang === 'ko' ? ' selected' : ''}>한국어</option><option value="en"${st.lang === 'en' ? ' selected' : ''}>English</option></select></label>
      <label class="small">숫자 앞 0 <select class="inp sx-zero">${[['auto', '자동(한국어 0.034 · 영어 .034)'], ['apa', 'APA (.034)'], ['leading', '0 붙임 (0.034)']].map(([k, l]) => `<option value="${k}"${st.zero === k ? ' selected' : ''}>${l}</option>`).join('')}</select></label>
      <label class="small">그림 폭 <select class="inp sx-width"><option value="double"${st.width === 'double' ? ' selected' : ''}>2단 175 mm</option><option value="single"${st.width === 'single' ? ' selected' : ''}>1단 85 mm</option></select></label>
      <span class="small muted sx-status"></span></div>
      ${st.res ? `<p class="sx-methods-short"><b>방법:</b> ${esc(st.lang === 'en' ? st.res.methods.short_en : st.res.methods.short_ko)}</p>` : ''}`;
    c.querySelector('.sx-go').onclick = runAnalysis;
    c.querySelector('.sx-lang').onchange = e => { st.lang = e.target.value; mem.set('lang', st.lang); if (st.res) { renderResults(); renderExports(); renderRun() } };
    c.querySelector('.sx-width').onchange = e => { st.width = e.target.value; mem.set('width', st.width); if (st.res) { renderResults(); renderExports() } };
    c.querySelector('.sx-zero').onchange = e => { st.zero = e.target.value; if (st.res) runAnalysis() };
  }

  async function runAnalysis(ev) {
    if (!st.ds || st.busy) return;
    st.busy = true;
    const b = $('.sx-go'); b.disabled = true; $('.sx-status').textContent = '계산 중…';
    const t0 = performance.now();
    try {
      st.res = await json(`${B}/run`, {method: 'POST', body: {source: source(), spec: {...st.spec, zero: st.zero}}});
      renderRun();
      $('.sx-status').textContent = `${((performance.now() - t0) / 1000).toFixed(1)}초 · n = ${st.res.dataset.n_used}`;
      renderResults(); renderExports();
      say('분석을 마쳤습니다.');
      if (ev) $('.sx-s3').scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (ex) { fail(ex); $('.sx-status').textContent = ''; $('.sx-res').innerHTML = `<p class="err">${esc(ex.message)}</p>` }
    finally { st.busy = false; const g = $('.sx-go'); if (g) g.disabled = false }
  }

  // ---------------------------------------------------------------- ③ 결과
  function renderResults() {
    const r = st.res;
    const en = st.lang === 'en';
    const ov = STATUS[r.overall];
    const dropped = r.dataset.dropped || [];
    const checks = r.assumptions.map(c => `<article class="sx-check s-${c.status}">
        <header><span class="pill ${STATUS[c.status][1]}">${en ? STATUS_EN[c.status] : STATUS[c.status][0]}</span><b>${esc(en ? c.name_en : c.name_ko)}</b></header>
        <p class="sx-stat"><span class="muted">${esc(en ? c.test_en || c.test : c.test)}</span><br>${esc(en ? c.stat_en || c.stat : c.stat)}</p>
        <p class="small">${esc(en ? c.text_en : c.text_ko)}</p>
        <p class="small muted">${en ? 'Criterion' : '기준'}: ${esc(en ? c.threshold_en || c.threshold : c.threshold)}</p></article>`).join('');
    const sentences = r.interpretation[st.lang];
    const mva = r.marginal_vs_adjusted;
    $('.sx-res').innerHTML = `
      ${r.dataset.is_demo ? '<div class="notice"><b>예시(모의) 데이터</b>로 낸 결과입니다 — 실제 측정값이 아닙니다.</div>' : ''}
      <div class="row sx-sum"><span class="pill ${ov[1]}">가정 점검 종합: ${ov[0]}</span>
        <span class="small">분석 n = <b>${r.dataset.n_used}</b> / 전체 ${r.dataset.n_total}${dropped.length ? ` · 목록별 삭제 ${dropped.length}개` : ''}</span>
        <span class="small">표준오차: <b>${r.primary_se === 'HC3' ? 'HC3 강건(이분산 확인)' : '일반 OLS'}</b></span></div>
      ${dropped.length ? `<details class="small"><summary>뺀 런 ${dropped.length}개와 이유</summary><ul>${dropped.map(d => `<li>${esc(d.run)} — ${esc(Object.entries(d.reasons).map(([k, v]) => `${k}: ${v}`).join(', '))}</li>`).join('')}</ul></details>` : ''}
      <h4><span data-help="stats.interp">해석 세 문장</span> <span class="small muted">— 숫자로만 만든 틀 문장(AI 생성 아님)</span>
        <span class="seg sx-lt" role="group" aria-label="해석 언어"><button type="button" data-l="ko" aria-pressed="${!en}">한국어</button><button type="button" data-l="en" aria-pressed="${en}">English</button></span>
        <button type="button" class="btn sm sx-copy">복사</button></h4>
      <ol class="sx-interp">${sentences.map(s => `<li>${esc(s)}</li>`).join('')}</ol>
      <h4 data-help="stats.table1">표 1 <span class="small muted">— 학술지 형식 미리보기(위·머리글 아래·맨 아래 가로줄만)</span></h4>
      <div class="sx-paper">${r.table1[st.lang]}</div>
      <h4 data-help="stats.fig1">그림 1 <span class="small muted">— ${st.width === 'single' ? '1단 85 mm' : '2단 175 mm'}, 300 dpi</span></h4>
      <div class="sx-paper sx-fig"><img alt="${esc(en ? 'Figure 1' : '그림 1')}" src="${fileUrl('figure1.png', {download: 'false'})}"><p class="sx-cap">${esc(r.caption[st.lang])}</p></div>
      <h4 data-help="stats.checks">가정 점검</h4>
      <p class="small muted">'통과'는 위반의 근거가 없다는 뜻이지 가정이 맞다는 증명이 아닙니다(특히 n이 작을 때). 기준값과 검정 이름을 함께 봅니다.</p>
      <div class="sx-checks">${checks}</div>
      ${r.t_test_note ? `<div class="info small"><b>3수준 이상에서의 t검정:</b> ${esc(r.t_test_note[st.lang])}</div>` : ''}
      ${mva ? `<div class="info small"><b>t검정과 회귀의 산 효과가 다른 이유:</b> ${esc(mva[st.lang])}</div>` : ''}
      ${r.regression ? `<details class="sx-diag"><summary>보조 그림 S1 — 잔차 진단(그림 1에 세지 않음)</summary><div class="sx-paper"><img alt="잔차 진단" loading="lazy" src="${fileUrl('diagnostics.png', {download: 'false'})}"></div></details>` : ''}
      <details><summary>방법 문장 (논문 '통계 분석' 절에 쓸 초안)</summary><p class="sx-methods">${esc(r.methods[st.lang])}</p></details>`;
    $('.sx-res').querySelectorAll('.sx-lt [data-l]').forEach(b => b.onclick = () => { st.lang = b.dataset.l; mem.set('lang', st.lang); renderRun(); renderResults(); renderExports() });
    $('.sx-copy').onclick = async () => {
      try { await navigator.clipboard.writeText(sentences.join(' ')); toast('해석 세 문장을 복사했습니다.') } catch { toast('복사하지 못했습니다 — 글을 직접 골라 복사하세요.') }
    };
  }

  // ---------------------------------------------------------------- ④ 내보내기
  function renderExports() {
    const a = (name, label, extra = '') => `<a class="btn sm" href="${fileUrl(name)}" download>${label}</a>${extra}`;
    $('.sx-exp').innerHTML = `
      <div class="row"><a class="btn primary" href="${fileUrl('bundle.zip')}" download>논문용 묶음 받기 (ZIP)</a>
        <span class="small muted">표 1(DOCX·HTML·CSV·LaTeX·MD) · 그림 1(PNG·SVG·PDF) · 그림 설명 · 해석(한·영) · 방법 · 가정 점검(DOCX·HTML) · 진단 그림 · 재현 파일</span></div>
      <div class="sx-explist">
        <div><b>표 1</b> ${a('table1.docx', 'DOCX')} ${a('table1.html', 'HTML')} ${a('table1.csv', 'CSV')} ${a('table1.tex', 'LaTeX')} ${a('table1.md', 'Markdown')}</div>
        <div><b>그림 1</b> ${a('figure1.png', 'PNG 300 dpi')} ${a('figure1.svg', 'SVG')} ${a('figure1.pdf', 'PDF')} ${a('caption.txt', '그림 설명')}</div>
        <div><b>글</b> ${a('interpretation.txt', '해석 세 문장')} ${a('methods.txt', '방법 문장')}</div>
        <div><b>가정 점검</b> ${a('assumptions.docx', 'DOCX')} ${a('assumptions.html', 'HTML')} ${st.res.regression ? a('diagnostics.png', '진단 그림') : ''}</div>
        <div><b data-help="stats.repro">Python·R·Stata 재현 파일</b>${a('reproduce.zip', '재현 패키지 ZIP')} ${a('data.csv', 'data.csv')} ${a('codebook.csv', 'codebook.csv')} ${a('analysis.py', 'analysis.py')} ${a('analysis.R', 'analysis.R')} ${a('analysis.do', 'analysis.do')}</div>
      </div>
      <p class="small muted">analysis.py는 이 앱과 같은 계산 코드라 같은 숫자가 나옵니다(시험으로 확인). analysis.R·analysis.do는 표준 명령만 썼지만 이 PC에 R·Stata가 없어 <b>실행해 보지 않았습니다</b> — 처음 돌릴 때 app_results.json과 비교하세요.</p>
      ${st.res.dataset.confidentiality === '기밀' ? '<div class="notice small"><b>기밀 실험</b> — 내려받은 파일을 PC 밖으로 보낼 때 등급에 맞게 다루세요.</div>' : ''}`;
  }

  // ---------------------------------------------------------------- 시작
  const api = {
    async open(expId) { st.kind = 'experiment'; st.expId = expId; st.res = null; await refresh(); },
    async openDemo(levels = 2) { st.kind = 'demo'; st.levels = levels; st.res = null; renderSource(); await loadPreview() },
    refresh, run: () => runAnalysis(null),
    dispose() { st.disposed = true; shell.remove() },
    get state() { return {kind: st.kind, expId: st.expId, spec: st.spec, result: st.res} },
  };
  async function refresh() {
    try { st.datasets = await json(`${B}/datasets`) } catch (ex) { fail(ex) }
    renderSource(); renderRun();
    await loadPreview();
  }
  refresh().then(() => { if (opts.autoRun && st.ds) runAnalysis(null) });
  return api;
}
