// 건조 설비 작업 공간: 3D 설비(three.js) ↔ 공정 흐름도(P&ID) 전환, 부품 설명, 단계 재생, 계기값, 시료 조건 반영
//   const eq = mountEquipment(host, {api, onStage(i, p)});
//   eq.setMethod('동결건조'); eq.setStage(1); eq.setCondition({sample, temp_c, time_h, pressure_pa}, {source, jump}); eq.dispose();
// 단독 확인 주소 파라미터(dev.html): view=pid|3d, cut=0|1, stage=n, t=0~1, variant=open|solar, part=id, play=0, labels=0
import {esc, fmt, reducedMotion, vendorUrl} from './common.js';
import {pidSvg} from './pid.js';

let _lib = null;
const loadThree = () => _lib ||= Promise.all([
  import(vendorUrl('three/three.module.min.js')), import(vendorUrl('three/OrbitControls.js')), import('./equipment3d.js'),
]).then(([T3, oc, eq]) => ({T3, OrbitControls: oc.OrbitControls, create: eq.createEquipment3D}))
  .catch(e => { _lib = null; throw e });

const STAGE_SEC = 10;
const lerp = (a, b, t) => a + (b - a) * t;
const ease = t => t * t * (3 - 2 * t);
// 포화 증기압 역함수(Magnus) — 압력(Pa) → 물 끓는점(℃). 0 ~ 100 ℃ 구간 오차 약 ±0.5 ℃
const boilC = p => { const l = Math.log(Math.max(p, 300) / 610.94); return 243.04 * l / (17.625 - l) };
const hrs = h => h == null ? '-' : h < 1 / 60 ? fmt(h * 3600, 1) + '초' : h < 1 ? fmt(h * 60, 0) + '분' : h >= 48 ? fmt(h / 24, 1) + '일' : fmt(h, 1) + '시간';

export function fmtGauge(g, v){
  if (v == null || Number.isNaN(v)) return '-';
  switch (g.unit) {
    case 'Pa': return v >= 99000 ? `${fmt(v / 1000, 1)} kPa(대기압)` : v >= 1000 ? `${fmt(v / 1000, 1)} kPa` : `${fmt(v, v < 10 ? 1 : 0)} Pa`;
    case '℃': return `${fmt(v, 1)} ℃`;
    case '%': return `${fmt(v, 0)} %`;
    case 'rpm': return `${fmt(Math.round(v / 100) * 100, 0)} rpm`;
    default: return `${fmt(v, 0)} ${g.unit}`;
  }
}

export function mountEquipment(host, {api, onStage} = {}){
  host.innerHTML = `<div class="eq">
    <div class="row eq-bar">
      <div class="grow"><b data-eqtitle>설비</b> <span class="small muted" data-eqscale></span></div>
      <div class="seg" data-variant role="group" aria-label="자연건조 형태" hidden></div>
      <div class="seg" role="group" aria-label="보기 방식"><button type="button" data-view="3d" aria-pressed="true">3D 설비</button><button type="button" data-view="pid" aria-pressed="false">공정 흐름도(P&amp;ID)</button></div>
    </div>
    <div class="eq-main">
      <div class="eq-view" data-viewbox>
        <div class="eq-3d" data-v3d></div>
        <div class="eq-pid" data-vpid hidden></div>
        <div class="eq-tools" data-tools role="group" aria-label="3D 보기 도구">
          <button type="button" class="btn sm" data-cut aria-pressed="false">절개 보기</button>
          <button type="button" class="btn sm" data-rot aria-pressed="false">자동 회전</button>
          <button type="button" class="btn sm" data-lbl aria-pressed="true">라벨</button>
          <button type="button" class="btn sm" data-reset>시점 초기화</button>
        </div>
        <div class="eq-badge" data-badge hidden></div>
        <div class="eq-msg" data-msg hidden></div>
      </div>
      <aside class="eq-side">
        <div class="eq-info" data-info aria-live="polite"></div>
        <h3>부품 목록</h3>
        <ul class="eq-plist" data-plist aria-label="부품 목록"></ul>
      </aside>
    </div>
    <div class="eq-play">
      <button type="button" class="btn sm" data-play aria-pressed="false">재생</button><span data-help-chips="viz.play" data-help-bare></span>
      <label class="small"><span class="muted">단계</span> <select class="inp" data-stagesel aria-label="공정 단계"></select></label>
      <div class="eq-prog" aria-hidden="true"><i data-prog></i></div>
      <span class="small muted" data-elapsed></span>
    </div>
    <div class="eq-gauges" data-gauges></div>
    <p class="small muted" style="margin:6px 0 0" data-eqnote></p>
  </div>`;
  const $ = s => host.querySelector(s);
  const q = new URLSearchParams(location.search);
  let first = true;
  let method = null, variant = q.get('variant') || null, eq = null, view = q.get('view') === 'pid' ? 'pid' : '3d';
  let cut = false, rotate = false, labels = q.get('labels') !== '0' && host.clientWidth > 560;
  let playing = !reducedMotion() && q.get('play') !== '0', stage = 0, p = 0, cond = null, selected = null;
  let v3 = null, webgl = true, gen = 0, build = 0, state = null, alive = true;
  const cache = {};

  // ------------------------------------------------------------ 상태 계산
  function compute(){
    if (!eq) return null;
    const S = eq.stages[stage] || eq.stages[0], e = ease(p), g = {}, a = {}, unit = {};
    eq.gauges.forEach(x => unit[x.key] = x.unit);
    for (const [k, [x, y]] of Object.entries(S.gauges)) g[k] = unit[k] === 'Pa' ? Math.exp(lerp(Math.log(x), Math.log(y), e)) : lerp(x, y, e);
    for (const [k, [x, y]] of Object.entries(S.anim)) a[k] = lerp(x, y, e);
    const over = new Set();
    if (cond && (cond.stage ?? eq.condition.stage) === stage) {
      const cm = eq.condition;
      if (cond.temp_c != null) { const k = cm.temp_low && cond.temp_c < -45 ? cm.temp_low : cm.temp; g[k] = cond.temp_c; over.add(k) }
      if (cond.pressure_pa != null && cm.pressure) { g[cm.pressure] = cond.pressure_pa; over.add(cm.pressure) }
    }
    eq.gauges.forEach(x => { if (x.derive === 'boil') { g[x.key] = boilC(g[x.from]); if (over.has(x.from)) over.add(x.key) } });
    const tm = s => { const [lo, hi] = s.time_h; return lo > 0 ? Math.sqrt(lo * hi) : (lo + hi) / 2 };
    let el = 0; eq.stages.forEach((s, i) => { if (i < stage) el += tm(s); else if (i === stage) el += tm(s) * p });
    const total = eq.stages.reduce((t, s) => t + tm(s), 0);
    const rows = eq.gauges.map(x => ({key: x.key, tag: x.tag, label: x.label, text: fmtGauge(x, g[x.key]), cond: over.has(x.key)}));
    return {stage, p, g, a, rows, over, playing, elapsed: el, total, sub: `${stage + 1}. ${S.name}`};
  }

  // ------------------------------------------------------------ 재생 시계(화면에 보일 때만)
  let raf = 0, last = 0, inView = true, uiT = 0;
  function tick(now){
    raf = 0;
    if (!alive || !inView || document.hidden || host.offsetParent === null) return;
    raf = requestAnimationFrame(tick);
    const dt = Math.min(.1, (now - (last || now)) / 1000); last = now;
    if (playing && eq) {
      p += dt / STAGE_SEC;
      if (p >= 1) { p = 0; stage = (stage + 1) % eq.stages.length; stageUi() }
    }
    state = compute();
    if (now - uiT > 160) { uiT = now; paint() }
  }
  const kick = () => { if (alive && !raf) { last = 0; raf = requestAnimationFrame(tick) } };
  const io = 'IntersectionObserver' in window ? new IntersectionObserver(es => { inView = es[es.length - 1].isIntersecting; if (inView) kick() }) : null;
  io?.observe(host);
  const onVis = () => { if (!document.hidden) kick() };
  document.addEventListener('visibilitychange', onVis);

  function paint(){
    if (!state || !eq) return;
    $('[data-prog]').style.width = `${(state.stage + state.p) / eq.stages.length * 100}%`;
    const ct = cond?.time_h != null ? ` · 시료 조건 ${hrs(cond.time_h)}` : '';
    $('[data-elapsed]').textContent = `경과 약 ${hrs(state.elapsed)} / 전체 약 ${hrs(state.total)}${ct}`;
    state.rows.forEach(r => {
      const el = host.querySelector(`.eq-g[data-k="${r.key}"]`);
      if (el) { el.querySelector('b').textContent = r.text; el.classList.toggle('cond', r.cond) }
      host.querySelectorAll(`[data-gv="${r.key}"]`).forEach(t => { t.textContent = r.text; t.classList.toggle('cond', r.cond) });
    });
    if (selected) host.querySelectorAll('[data-infog]').forEach(el => { const r = state.rows.find(x => x.key === el.dataset.infog); if (r) el.textContent = r.text });
    onStage?.(state.stage, state.p);
  }
  function stageUi(){
    $('[data-stagesel]').value = String(stage);
    $('[data-play]').textContent = playing ? '일시정지' : '재생';
    $('[data-play]').setAttribute('aria-pressed', playing);
    $('[data-vpid]').classList.toggle('eq-paused', !playing);
  }

  // ------------------------------------------------------------ 방식·형태 바꾸기
  function setMethod(name){
    if (!first) { variant = null; cond = null; selected = null }
    method = name;
    return load(false);
  }
  async function load(keep){
    const g = ++gen, key = `${method}|${variant || ''}`;
    let data;
    try { data = cache[key] ||= await api.json(`/api/viz/drying/equipment/${encodeURIComponent(method)}${variant ? `?variant=${encodeURIComponent(variant)}` : ''}`) }
    catch (e) { delete cache[key]; if (g === gen) { const m = $('[data-msg]'); m.hidden = false; m.textContent = `설비 모델을 불러오지 못했습니다: ${e.message}` } return }
    if (g !== gen) return;
    eq = data; variant = data.variant;
    if (!keep) {
      cut = first && q.get('cut') != null ? q.get('cut') === '1' : !!data.cut_default;
      stage = 0; p = 0;
      if (first) {
        if (q.get('stage') != null) { stage = Math.max(0, Math.min(eq.stages.length - 1, +q.get('stage') || 0)); p = q.get('t') != null ? +q.get('t') : .55; playing = q.get('play') === '1' }
        if (q.get('part')) selected = q.get('part');
      }
    }
    if (selected && !eq.parts.some(x => x.id === selected)) selected = null;
    first = false;
    $('[data-eqtitle]').textContent = eq.title;
    $('[data-eqscale]').textContent = eq.scale;
    $('[data-eqnote]').textContent = eq.note;
    const vs = $('[data-variant]');
    vs.hidden = !eq.variants.length;
    vs.innerHTML = eq.variants.map(v => `<button type="button" data-vid="${esc(v.id)}" aria-pressed="${v.id === variant}">${esc(v.name)}</button>`).join('');
    vs.querySelectorAll('button').forEach(b => b.onclick = () => { if (b.dataset.vid !== variant) { variant = b.dataset.vid; load(true) } });
    $('[data-stagesel]').innerHTML = eq.stages.map((s, i) => `<option value="${i}">${i + 1}. ${esc(s.name)}</option>`).join('');
    $('[data-plist]').innerHTML = eq.parts.map(x => `<li><button type="button" data-pid="${esc(x.id)}" aria-pressed="${x.id === selected}">${esc(x.name)}</button></li>`).join('');
    $('[data-plist]').querySelectorAll('button').forEach(b => b.onclick = () => select(b.dataset.pid, true));
    $('[data-gauges]').innerHTML = eq.gauges.map(x => `<button type="button" class="eq-g" data-k="${esc(x.key)}" data-part="${esc(x.part)}" title="${esc(x.tag)} — 누르면 관련 부품 설명"><span class="tag">${esc(x.tag)}</span><b>-</b><small>${esc(x.label)}</small></button>`).join('');
    $('[data-gauges]').querySelectorAll('.eq-g').forEach(b => b.onclick = () => select(b.dataset.part, true));
    stageUi(); badge();
    state = compute();
    renderPid(); info();
    await renderView();
    paint(); kick();
  }

  // ------------------------------------------------------------ 보기 전환
  function toolsUi(){
    host.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-pressed', b.dataset.view === view));
    $('[data-view="3d"]').disabled = !webgl;
    $('[data-tools]').hidden = view !== '3d';
    $('[data-cut]').setAttribute('aria-pressed', cut); $('[data-rot]').setAttribute('aria-pressed', rotate); $('[data-lbl]').setAttribute('aria-pressed', labels);
    $('[data-v3d]').hidden = view !== '3d'; $('[data-vpid]').hidden = view !== 'pid';
  }
  function disposeV3(){ v3?.dispose(); v3 = null; $('[data-v3d]').innerHTML = '' }
  async function renderView(){
    toolsUi();
    if (view !== '3d') { disposeV3(); return }
    const b = ++build; disposeV3();
    $('[data-msg]').hidden = true;
    let lib;
    try { lib = await loadThree() } catch (e) { return fallback(`3D 라이브러리(three.js)를 불러오지 못해 공정 흐름도로 보여줍니다. app/static/vendor/three 폴더를 확인하세요. (${e.message})`) }
    if (b !== build || view !== '3d' || !eq) return;
    try {
      v3 = lib.create($('[data-v3d]'), lib, {method, variant, parts: eq.parts, getState: () => state, onPick: id => select(id), cut, labels,
        onError: e => { const b2 = build; setTimeout(() => { if (b2 === build) { disposeV3(); fallback(`3D 화면을 그리는 중 오류가 나서 공정 흐름도로 보여줍니다. (${e.message})`) } }) }});
    } catch (e) {
      console.error(e); webgl = false;
      return fallback('이 브라우저에서 WebGL(3D)을 쓸 수 없어 공정 흐름도로 보여줍니다. 그래픽 가속을 켜면 3D 설비를 볼 수 있습니다.');
    }
    v3.setRotate(rotate);
    if (selected) v3.select(selected);
  }
  function fallback(msg){
    view = 'pid'; toolsUi(); renderPid();
    const m = $('[data-msg]'); m.hidden = false; m.textContent = msg;
  }
  function renderPid(){
    if (!eq) return;
    const box = $('[data-vpid]');
    box.innerHTML = pidSvg(method, variant, eq);
    box.classList.toggle('eq-paused', !playing);
    box.querySelectorAll('.pid-part').forEach(g => {
      g.addEventListener('click', () => select(g.dataset.part));
      g.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(g.dataset.part) } });
    });
    markPid(); paint();
  }
  const markPid = () => $('[data-vpid]').querySelectorAll('.pid-part').forEach(g => g.classList.toggle('sel', g.dataset.part === selected));

  // ------------------------------------------------------------ 부품 선택·설명
  function select(id, fromList){
    if (!eq) return;
    selected = eq.parts.some(x => x.id === id) ? id : null;
    v3?.select(selected); markPid(); info();
    $('[data-plist]').querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', b.dataset.pid === selected));
    if (fromList && selected) $('[data-info]').focus?.();
  }
  function info(){
    const box = $('[data-info]');
    const x = eq?.parts.find(y => y.id === selected);
    if (!x) { box.innerHTML = `<p class="small muted" style="margin:0">3D 모델이나 흐름도에서 부품을 누르거나, 아래 목록에서 고르면 역할·일반 설정값·부산물 건조에서 중요한 점이 나옵니다.</p>`; return }
    const gs = eq.gauges.filter(g => g.part === x.id);
    box.innerHTML = `<h3 tabindex="-1">${esc(x.name)}</h3><dl>
      <dt>역할</dt><dd>${esc(x.role)}</dd>
      <dt>일반 설정값·범위</dt><dd>${esc(x.setting)}</dd>
      <dt>부산물 건조에서 왜 중요한가</dt><dd>${esc(x.note)}</dd>
      ${gs.length ? `<dt>관련 계기(지금 값)</dt><dd>${gs.map(g => `<span class="eq-chip"><span class="mono">${esc(g.tag)}</span> ${esc(g.label)} <b data-infog="${esc(g.key)}">${esc(state?.rows.find(r => r.key === g.key)?.text || '-')}</b></span>`).join(' ')}</dd>` : ''}
    </dl>`;
  }

  // ------------------------------------------------------------ 시료 조건
  function badge(){
    const b = $('[data-badge]');
    if (!cond || !eq) { b.hidden = true; return }
    const parts = [cond.temp_c != null ? `${fmt(cond.temp_c, 1)} ℃` : null, cond.time_h != null ? `${fmt(cond.time_h, 1)} h` : null,
      cond.pressure_pa != null ? fmtGauge({unit: 'Pa'}, cond.pressure_pa) : null, cond.air_velocity_ms != null ? `풍속 ${fmt(cond.air_velocity_ms, 1)} m/s` : null,
      cond.thickness_mm != null ? `두께 ${fmt(cond.thickness_mm, 1)} mm` : null].filter(Boolean);
    const st = eq.stages[cond.stage ?? eq.condition.stage];
    b.hidden = false;
    b.innerHTML = `<span><b>${esc(cond.sample || '조건')}</b>: ${esc(parts.join(' · ') || '값 없음')}</span><span class="small muted">${esc(st ? `${st.name} 단계 계기에 표시` : '')}</span><button type="button" class="btn sm" data-clear aria-label="시료 조건 표시 끄기">해제</button>`;
    b.querySelector('[data-clear]').onclick = () => { cond = null; badge(); state = compute(); paint() };
  }
  function setCondition(c, {jump = true} = {}){
    if (!c) { cond = null; badge(); state = compute(); paint(); return }
    cond = {...c};
    if (eq && cond.stage == null) cond.stage = eq.condition.stage;
    if (jump && eq) { stage = cond.stage; p = .5; playing = false; stageUi() }
    else if (eq && !playing) { stage = cond.stage; stageUi() }
    badge(); state = compute(); paint(); kick();
  }

  // ------------------------------------------------------------ 이벤트
  host.querySelectorAll('[data-view]').forEach(b => b.onclick = () => { if (b.disabled || view === b.dataset.view) return; view = b.dataset.view; renderView().then(() => { renderPid(); select(selected) }) });
  $('[data-cut]').onclick = () => { cut = !cut; v3?.setCut(cut); toolsUi() };
  $('[data-rot]').onclick = () => { rotate = !rotate; v3?.setRotate(rotate); toolsUi() };
  $('[data-lbl]').onclick = () => { labels = !labels; v3?.setLabels(labels); toolsUi() };
  $('[data-reset]').onclick = () => v3?.resetView();
  $('[data-play]').onclick = () => { playing = !playing; stageUi(); kick() };
  $('[data-stagesel]').onchange = e => setStage(+e.target.value);
  function setStage(i){ if (!eq) return; stage = Math.max(0, Math.min(eq.stages.length - 1, i)); p = 0; stageUi(); state = compute(); paint(); kick() }

  return {
    setMethod, setStage, setCondition,
    get state(){ return state },
    dispose(){ alive = false; cancelAnimationFrame(raf); io?.disconnect(); document.removeEventListener('visibilitychange', onVis); disposeV3() },
  };
}
