// 건조 방식: 설비 작업 공간(3D 설비·P&ID, equipment.js) + 조건→결과 예측(predict.js, 있으면) + 물 상평형도의 공정 경로
//           + 3D 입자 단면(three.js) + 방식별 측정값 비교
import {esc, fmt, reducedMotion, vendorUrl, METHOD_COLOR} from './common.js';
import {mountEquipment} from './equipment.js';

const rnd = seed => () => (seed = (seed * 16807) % 2147483647) / 2147483647;

// ---------------------------------------------------------------- 상평형도
const PX = {l: 64, r: 16, t: 16, b: 44, w: 640, h: 380};
const tMin = -80, tMax = 200, lpMin = -1, lpMax = 7;
const sx = t => PX.l + (t - tMin) / (tMax - tMin) * (PX.w - PX.l - PX.r);
const sy = p => PX.t + (lpMax - Math.log10(Math.max(p, 1e-3))) / (lpMax - lpMin) * (PX.h - PX.t - PX.b);
const P_LABEL = {'-1':'0.1 Pa', 0:'1 Pa', 1:'10 Pa', 2:'100 Pa', 3:'1 kPa', 4:'10 kPa', 5:'100 kPa', 6:'1 MPa', 7:'10 MPa'};

function phaseSvg(ph, method, marker){
  const clipT = pts => pts.filter(q => q.t >= tMin && q.t <= tMax && q.p <= 10 ** lpMax);
  const line = (pts, col, w=2) => `<polyline points="${clipT(pts).map(q => `${sx(q.t).toFixed(1)},${sy(q.p).toFixed(1)}`).join(' ')}" fill="none" stroke="${col}" stroke-width="${w}"/>`;
  let s = `<svg viewBox="0 0 ${PX.w} ${PX.h}" class="flowsvg" role="img" aria-label="물의 상평형도와 ${esc(method)} 공정 경로">
    <defs><marker id="bvPhA" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="${METHOD_COLOR[method]}"/></marker></defs>`;
  for (let lp = lpMin; lp <= lpMax; lp++) s += `<line x1="${PX.l}" x2="${PX.w - PX.r}" y1="${sy(10 ** lp)}" y2="${sy(10 ** lp)}" stroke="var(--v-line)"/><text x="${PX.l - 6}" y="${sy(10 ** lp) + 4}" font-size="10.5" text-anchor="end" fill="var(--v-muted)">${P_LABEL[lp]}</text>`;
  for (let t = -80; t <= 200; t += 40) s += `<line y1="${PX.t}" y2="${PX.h - PX.b}" x1="${sx(t)}" x2="${sx(t)}" stroke="var(--v-line)"/><text x="${sx(t)}" y="${PX.h - PX.b + 16}" font-size="10.5" text-anchor="middle" fill="var(--v-muted)">${t} ℃</text>`;
  s += `<text x="${(PX.l + PX.w) / 2}" y="${PX.h - 6}" font-size="11.5" text-anchor="middle" fill="var(--v-muted)">온도</text>`;
  s += `<line x1="${PX.l}" x2="${PX.w - PX.r}" y1="${sy(101325)}" y2="${sy(101325)}" stroke="var(--v-muted)" stroke-dasharray="4 4"/><text x="${PX.w - PX.r - 4}" y="${sy(101325) - 5}" font-size="10.5" text-anchor="end" fill="var(--v-muted)">대기압 101 kPa</text>`;
  s += line(ph.curves.sublimation, 'var(--cold)', 2.4) + line(ph.curves.vaporization, 'var(--hot)', 2.4) + line(ph.curves.melting, 'var(--v-ink)', 1.8);
  s += `<text x="${sx(-78)}" y="${sy(.25)}" font-size="10.5" fill="var(--cold)">승화 곡선</text><text x="${sx(120)}" y="${sy(1.5e5) + 22}" font-size="10.5" fill="var(--hot)">증발(끓는점) 곡선</text><text x="${sx(3)}" y="${sy(3e6)}" font-size="10.5" fill="var(--v-ink)">융해 곡선</text>`;
  ph.regions.forEach(r => s += `<text x="${sx(r.t)}" y="${sy(r.p)}" font-size="13" font-weight="700" fill="var(--v-muted)" opacity=".8" text-anchor="middle">${esc(r.name)}</text>`);
  const tp = ph.triple_point;
  s += `<circle cx="${sx(tp.t)}" cy="${sy(tp.p)}" r="4.5" fill="var(--v-ink)"/><text x="${sx(tp.t) + 7}" y="${sy(tp.p) + 14}" font-size="10.5" fill="var(--v-ink)">삼중점 0.01 ℃ · 611.657 Pa</text>`;
  const path = ph.paths[method] || [];
  if (path.length) {
    const col = METHOD_COLOR[method];
    for (let i = 0; i < path.length - 1; i++) s += `<line x1="${sx(path[i].t)}" y1="${sy(path[i].p)}" x2="${sx(path[i + 1].t)}" y2="${sy(path[i + 1].p)}" stroke="${col}" stroke-width="3" marker-end="url(#bvPhA)"/>`;
    path.forEach((q, i) => s += `<circle cx="${sx(q.t)}" cy="${sy(q.p)}" r="4" fill="${col}"/><text x="${sx(q.t) + (q.pos === 'l' ? -7 : 6)}" y="${sy(q.p) + (q.pos === 'l' ? 4 : i % 2 ? 15 : -7)}" font-size="11" font-weight="600" fill="${col}" ${q.pos === 'l' ? 'text-anchor="end"' : ''}>${esc(q.label)}</text>`);
  }
  if (marker && marker.t != null) {
    const x = sx(Math.max(tMin, Math.min(tMax, marker.t))), y = sy(marker.p);
    s += `<g><circle cx="${x}" cy="${y}" r="9" fill="none" stroke="var(--v-accent)" stroke-width="2.5"/><circle cx="${x}" cy="${y}" r="2.5" fill="var(--v-accent)"/>
      <text x="${x + 12}" y="${y - 10}" font-size="11" font-weight="700" fill="var(--v-accent)">${esc(marker.label)}</text></g>`;
  }
  return s + '</svg>';
}

// ---------------------------------------------------------------- 3D 입자 단면 (three.js)
let _three = null;
async function three(){
  if (!_three) _three = Promise.all([import(vendorUrl('three/three.module.min.js')), import(vendorUrl('three/OrbitControls.js'))])
    .then(([T3, oc]) => ({T3, OrbitControls: oc.OrbitControls}));
  return _three;
}

function particleView(box, lib, method, p, cut){
  const {T3, OrbitControls} = lib;
  const w = box.clientWidth || 300, hgt = box.clientHeight || 300;
  const renderer = new T3.WebGLRenderer({antialias: true, alpha: true});
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setSize(w, hgt);
  renderer.localClippingEnabled = true;
  box.appendChild(renderer.domElement);
  const scene = new T3.Scene();
  const cam = new T3.PerspectiveCamera(38, w / hgt, .1, 50);
  cam.position.set(1.4, 1.0, 3.6);
  scene.add(new T3.HemisphereLight(0xffffff, 0x444444, 1.6));
  const dl = new T3.DirectionalLight(0xffffff, 1.6); dl.position.set(3, 4, 5); scene.add(dl);
  const controls = new OrbitControls(cam, renderer.domElement);
  controls.enableDamping = true; controls.autoRotate = !reducedMotion(); controls.autoRotateSpeed = 1.2;
  controls.minDistance = 2; controls.maxDistance = 8;

  const R = .55 + .45 * p.shrinkage, rand = rnd(method.length * 977 + 13);
  const phase = Array.from({length: 6}, () => rand() * 6.28);
  const plane = new T3.Plane(new T3.Vector3(0, 0, -1), 0);
  const clip = cut ? [plane] : [];
  // 겉면: 거칠기·주름(수축)을 반지름 변위로
  const geo = new T3.IcosahedronGeometry(R, 32), pos = geo.attributes.position, v = new T3.Vector3();
  const wr = (1 - p.shrinkage) * .12;
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i).normalize();
    const n = Math.sin(v.x * 7 + phase[0]) * Math.sin(v.y * 6 + phase[1]) * Math.sin(v.z * 8 + phase[2]);
    const fine = Math.sin(v.x * 23 + phase[3]) * Math.sin(v.y * 19 + phase[4]) * Math.sin(v.z * 21 + phase[5]);
    v.multiplyScalar(R * (1 + p.roughness * .06 * fine - wr * Math.abs(n)));
    pos.setXYZ(i, v.x, v.y, v.z);
  }
  geo.computeVertexNormals();
  const tint = new T3.Color(p.tint);
  const shell = new T3.Mesh(geo, new T3.MeshStandardMaterial({color: tint, roughness: .9, metalness: 0, side: T3.DoubleSide, clippingPlanes: clip}));
  scene.add(shell);
  // 기공
  const pores = [];
  if (p.hollow) pores.push({x: 0, y: 0, z: 0, r: R * .58, sy: 1});
  let tries = 0;
  while (pores.length < p.pore_count + (p.hollow ? 1 : 0) && tries++ < 6000) {
    const r = Math.max(.012, (p.pore_mean + (rand() + rand() + rand() - 1.5) * p.pore_sd)) * R;
    const q = {x: (rand() * 2 - 1) * R, y: (rand() * 2 - 1) * R, z: (rand() * 2 - 1) * R, r, sy: method === '동결건조' ? 1.7 : 1};
    const d = Math.hypot(q.x, q.y, q.z);
    if (d + r * q.sy > R * .9) continue;
    if (p.hollow && d - r < R * .64) continue;
    pores.push(q);
  }
  const poreMat = new T3.MeshStandardMaterial({color: tint.clone().multiplyScalar(.35), roughness: 1, side: T3.BackSide, clippingPlanes: [plane]});
  const poreGroup = new T3.Group();
  const sg = new T3.SphereGeometry(1, 18, 12);
  pores.forEach(q => { const m = new T3.Mesh(sg, poreMat); m.position.set(q.x, q.y, q.z); m.scale.set(q.r, q.r * q.sy, q.r); poreGroup.add(m) });
  // 단면 뚜껑: 기공 자리는 투명하게 뚫는다
  const cv = document.createElement('canvas'); cv.width = cv.height = 512;
  const g = cv.getContext('2d'), k = 256 / R;
  g.fillStyle = '#' + tint.clone().lerp(new T3.Color(0xffffff), .12).getHexString(); g.beginPath(); g.arc(256, 256, 255, 0, 7); g.fill();
  g.globalCompositeOperation = 'destination-out';
  pores.forEach(q => { const rz = q.r * q.r - q.z * q.z; if (rz <= 0) return; const rr = Math.sqrt(rz); g.beginPath(); g.ellipse(256 + q.x * k, 256 - q.y * k, rr * k, rr * q.sy * k, 0, 0, 7); g.fill() });
  const tex = new T3.CanvasTexture(cv);
  const cap = new T3.Mesh(new T3.CircleGeometry(R * .985, 96), new T3.MeshStandardMaterial({map: tex, transparent: true, alphaTest: .5, roughness: 1, side: T3.DoubleSide}));
  scene.add(poreGroup, cap);
  poreGroup.visible = cap.visible = cut;

  let alive = true, raf = 0;
  const loop = () => { if (!alive) return; raf = requestAnimationFrame(loop); if (!box.isConnected) return dispose(); controls.update(); renderer.render(scene, cam) };
  loop();
  const ro = new ResizeObserver(() => { const W = box.clientWidth, Hh = box.clientHeight; if (!W || !Hh) return; renderer.setSize(W, Hh); cam.aspect = W / Hh; cam.updateProjectionMatrix() });
  ro.observe(box);
  function dispose(){ alive = false; cancelAnimationFrame(raf); ro.disconnect(); controls.dispose(); renderer.dispose(); geo.dispose(); sg.dispose(); tex.dispose(); renderer.domElement.remove() }
  return {
    dispose,
    setCut(on){ shell.material.clippingPlanes = on ? [plane] : []; shell.material.needsUpdate = true; poreGroup.visible = cap.visible = on },
    setRotate(on){ controls.autoRotate = on },
  };
}

// ---------------------------------------------------------------- 비교 차트
function compareSvg(groups, unit){
  const rowH = 34, w = 640, l = 150, r = 150, hgt = groups.length * rowH + 30;
  const lo = Math.min(0, ...groups.map(g => g.min)), hi = Math.max(...groups.map(g => g.max)) * 1.08 || 1;
  const x = v => l + (v - lo) / (hi - lo) * (w - l - r);
  let s = `<svg viewBox="0 0 ${w} ${hgt}" class="flowsvg" style="max-width:760px" role="img" aria-label="건조 방식별 ${esc(unit)} 비교">`;
  for (let i = 0; i <= 4; i++) { const v = lo + (hi - lo) * i / 4; s += `<line x1="${x(v)}" x2="${x(v)}" y1="4" y2="${hgt - 22}" stroke="var(--v-line)"/><text x="${x(v)}" y="${hgt - 8}" font-size="10.5" text-anchor="middle" fill="var(--v-muted)">${fmt(v, 1)}</text>` }
  groups.forEach((g, i) => {
    const y = 18 + i * rowH, col = METHOD_COLOR[g.method] || 'var(--m-unk)';
    s += `<g><title>${esc(g.method)}: 평균 ${fmt(g.mean, 3)} ${esc(unit)} (n=${g.n}, ${fmt(g.min, 3)}–${fmt(g.max, 3)}) · ${esc(g.samples.join(', '))}</title>
      <circle cx="12" cy="${y}" r="5" fill="${col}"/><text x="22" y="${y + 4}" font-size="12.5" font-weight="600" fill="var(--v-ink)">${esc(g.method)}</text>
      <line x1="${x(lo)}" x2="${x(g.mean)}" y1="${y}" y2="${y}" stroke="${col}" stroke-width="10" stroke-opacity=".28" stroke-linecap="round"/>
      <line x1="${x(g.min)}" x2="${x(g.max)}" y1="${y}" y2="${y}" stroke="${col}" stroke-width="2.5"/>
      <line x1="${x(g.min)}" x2="${x(g.min)}" y1="${y - 6}" y2="${y + 6}" stroke="${col}" stroke-width="2"/><line x1="${x(g.max)}" x2="${x(g.max)}" y1="${y - 6}" y2="${y + 6}" stroke="${col}" stroke-width="2"/>
      <circle cx="${x(g.mean)}" cy="${y}" r="6" fill="${col}" stroke="var(--v-surface)" stroke-width="2"/>
      <text x="${w - r + 10}" y="${y + 4}" font-size="12" fill="var(--v-ink)">${fmt(g.mean, 2)} <tspan fill="var(--v-muted)" font-size="11">n=${g.n}${g.n > 1 ? ` · ${fmt(g.min, 1)}–${fmt(g.max, 1)}` : ''}</tspan></text></g>`;
  });
  return s + '</svg>';
}

// ---------------------------------------------------------------- 화면
export function mountDrying(el, ctx){
  el.innerHTML = `
  <div class="card">
    <div class="row"><h2 class="grow">건조 방식</h2><div class="seg" data-methods role="group" aria-label="건조 방식 고르기"></div></div>
    <p class="sub" data-summary></p>
    <div data-equip></div>
    <div class="stage-strip" data-stages></div>
    <p class="small muted" style="margin:8px 0 0" data-gnote></p>
  </div>
  <div class="card" data-predict-host></div>
  <div class="split">
    <div class="card"><h2>물의 상평형도와 공정 경로</h2><p class="sub">어느 상태 경계를 넘어 물이 빠지는지 보여줍니다. 세로축은 로그 눈금 압력입니다.</p>
      <div data-phase><div class="empty">불러오는 중…</div></div><p class="small muted" data-pnote style="margin:6px 0 0"></p></div>
    <div class="card"><h2>기전과 예상 효과</h2><div data-effects></div>
      <h3>CoA 시료의 실제 조건</h3><div data-cond class="small muted">측정값 비교를 불러오면 이 방식으로 말린 CoA 시료의 조건이 여기에 나옵니다.</div></div>
  </div>
  <div class="card">
    <div class="row"><h2 class="grow">3D 입자 단면</h2>
      <label class="small">비교 <select class="inp" data-cmp aria-label="비교할 건조 방식"></select></label>
      <label class="small"><input type="checkbox" data-cut checked> 단면 자르기</label>
      <label class="small"><input type="checkbox" data-rot> 자동 회전</label></div>
    <p class="sub" data-pnote2></p>
    <div class="grid2" data-3d></div>
  </div>
  <div class="card">
    <div class="row"><h2 class="grow">방식별 측정값 비교</h2>
      <input class="inp" data-bp placeholder="부산물 (예: 사과박, 비우면 전체)" aria-label="부산물">
      <input class="inp" data-tg value="식이섬유, 폴리페놀" aria-label="항목(쉼표로 여러 개)">
      <button class="btn" data-cmpgo>비교</button></div>
    <p class="sub">CoA는 시료의 전처리(건조 방법)로, 논문 추출값은 같은 문단의 건조 표기로 묶습니다. 막대 끝 = 최소·최대, 점 = 평균.</p>
    <div data-chart><div class="empty">불러오는 중…</div></div>
  </div>`;
  const $ = s => el.querySelector(s);
  let methods = [], phase = null, cur = ctx.initialMethod || '동결건조', cmpMethod = '열풍건조', stageIdx = 0, pred = null, predTried = false;
  let views = [], compareData = null, marker = null;
  $('[data-rot]').checked = !reducedMotion();
  // 설비 작업 공간: 단계 재생이 아래 단계 띠를 함께 움직인다
  const equip = mountEquipment($('[data-equip]'), {api: ctx.api, onStage: i => { if (i !== stageIdx) { stageIdx = i; highlight() } }});
  /** 조건(CoA 시료·예측 패널)을 설비 계기·제어반 화면에 얹는다. cond: {temp_c, time_h, pressure_pa, air_velocity_ms, thickness_mm, stage?, sample?} */
  function applyConditions(cond, opt = {}){
    if (!cond) return equip.setCondition(null);
    equip.setCondition({sample: '예측 조건', ...cond}, {jump: false, ...opt});
  }
  async function mountPredictPanel(){
    const host = $('[data-predict-host]');
    if (pred) { pred.setMethod?.(cur); return }
    if (predTried) return;
    predTried = true;
    const P = await import('./predict.js').catch(() => null);
    if (!P?.mountPredict || !el.isConnected) { host.hidden = true; return }
    try { pred = P.mountPredict(host, {api: ctx.api, method: cur, project: ctx.project, showMethod: false, onChange: c => applyConditions(c)}) }
    catch (e) { console.error(e); host.hidden = true }
  }

  function pick(m){
    cur = m;
    $('[data-methods]').querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', b.dataset.m === m));
    const d = methods.find(x => x.name === m); if (!d) return;
    $('[data-summary]').innerHTML = `<b style="color:${METHOD_COLOR[m]}">${esc(m)}</b> <span class="muted">${esc(d.en)}</span> — ${esc(d.summary)}`;
    equip.setMethod(m);
    $('[data-stages]').innerHTML = d.stages.map((s, i) => `<button type="button" class="st" data-i="${i}" title="이 단계로 설비 보기"><b>${i + 1}. ${esc(s.name)}</b>${esc(s.desc)}
      <div class="muted" style="margin-top:3px">${rng(s.temp_c, ' ℃')} · ${pres(s.pressure_pa)} · ${hrs(s.time_h)}</div></button>`).join('');
    $('[data-stages]').querySelectorAll('.st').forEach(b => b.onclick = () => equip.setStage(+b.dataset.i));
    stageIdx = 0; highlight();
    mountPredictPanel();
    const eff = Object.entries(d.effects).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join('');
    $('[data-effects]').innerHTML = `<p style="margin:0 0 8px">${esc(d.mechanism)}</p>
      <div class="kv" style="margin-bottom:8px"><b>일반 조건</b><span>${rng(d.params.temp_c, ' ℃')} · ${pres(d.params.pressure_pa)} · ${hrs(d.params.time_h)}${d.params.outlet_c ? ` · 출구 ${rng(d.params.outlet_c, ' ℃')}` : ''}</span></div>
      <table><tbody>${eff}</tbody></table><p class="small muted" style="margin:6px 0 0">${esc(methodsNote)}</p>`;
    marker = null; drawPhase(); conditions(); build3d();
  }
  let methodsNote = '', particleNote = '';
  const rng = (a, u) => a ? (a[0] === a[1] ? fmt(a[0], 1) + u : `${fmt(a[0], 1)} ~ ${fmt(a[1], 1)}${u}`) : '-';
  const pres = a => { const f = p => p >= 100000 ? '대기압' : p >= 1000 ? fmt(p / 1000, 1) + ' kPa' : fmt(p, 1) + ' Pa'; return a[0] === a[1] ? f(a[0]) : `${f(a[0])} ~ ${f(a[1])}` };
  const hrs = a => { const f = hh => hh < 1 / 60 ? fmt(hh * 3600, 1) + '초' : hh < 1 ? fmt(hh * 60, 0) + '분' : hh >= 48 ? fmt(hh / 24, 1) + '일' : fmt(hh, 1) + '시간'; return a[0] === a[1] ? f(a[0]) : `${f(a[0])} ~ ${f(a[1])}` };

  function highlight(){
    el.querySelectorAll('.stage-strip .st').forEach((s, i) => { s.classList.toggle('on', i === stageIdx); s.setAttribute('aria-current', i === stageIdx ? 'step' : 'false') });
  }

  function drawPhase(){ if (phase) $('[data-phase]').innerHTML = phaseSvg(phase, cur, marker) }

  async function build3d(){
    views.forEach(v => v.dispose()); views = [];
    const host = $('[data-3d]');
    const pair = [cur, cmpMethod === cur ? (cur === '동결건조' ? '열풍건조' : '동결건조') : cmpMethod];
    host.innerHTML = pair.map(m => { const p = methods.find(x => x.name === m)?.particle || {}; return `<div><div class="stage3d" data-pv="${esc(m)}" role="img" aria-label="${esc(m)} 입자 단면 3D (드래그로 돌려보기)"><span class="cap" style="color:${METHOD_COLOR[m]}">${esc(m)}</span></div>
      <p class="small muted" style="margin:4px 0 0">기공률 약 ${Math.round(p.porosity * 100)}% · 부피 유지 약 ${Math.round(p.shrinkage * 100)}%${p.hollow ? ' · 속 빈 입자' : ''}</p></div>` }).join('');
    let lib;
    try { lib = await three() } catch (e) { host.innerHTML = `<p class="err">3D 라이브러리(three.js)를 불러오지 못했습니다. app/static/vendor/three 폴더를 확인하세요. (${esc(e.message)})</p>`; return }
    const cut = $('[data-cut]').checked;
    for (const m of pair) {
      const box = host.querySelector(`[data-pv="${CSS.escape(m)}"]`); if (!box) continue;
      try { const v = particleView(box, lib, m, methods.find(x => x.name === m).particle, cut); v.setRotate($('[data-rot]').checked); views.push(v) }
      catch (e) { box.insertAdjacentHTML('beforeend', `<div class="empty">3D 화면을 만들지 못했습니다(WebGL 미지원일 수 있음).</div>`) }
    }
  }

  function conditions(){
    const box = $('[data-cond]');
    if (!compareData) return;
    const conds = [];
    compareData.targets.forEach(t => t.groups.filter(g => g.method === cur).forEach(g => g.conditions.forEach(c => { if (!conds.some(x => x.sample === c.sample)) conds.push(c) })));
    if (!conds.length) { box.innerHTML = `이 방식으로 말린 CoA 시료의 온도·시간 기록이 없습니다. CoA의 전처리 칸에 "${esc(cur)}; 온도 ℃; 시간 h"처럼 적으면 여기에 나옵니다.`; return }
    const defP = {동결건조: 15, 진공건조: 8000}[cur] || 101325;
    box.innerHTML = `<div class="chips">${conds.map((c, i) => `<button class="chip" data-ci="${i}">${esc(c.sample)}: ${c.temp_c != null ? fmt(c.temp_c, 1) + ' ℃' : '온도 ?'} · ${c.time_h != null ? fmt(c.time_h, 1) + ' h' : '시간 ?'}${c.pressure_pa != null ? ' · ' + fmt(c.pressure_pa, 1) + ' Pa' : ''}</button>`).join('')}</div>
      <p class="small muted" style="margin:4px 0 0">누르면 상평형도와 위 설비 계기·제어반에 그 조건을 표시합니다(압력 기록이 없으면 이 방식의 일반 압력).</p>`;
    box.querySelectorAll('[data-ci]').forEach(b => b.onclick = () => {
      const c = conds[+b.dataset.ci];
      marker = {t: c.temp_c ?? 20, p: c.pressure_pa ?? defP, label: c.sample}; drawPhase();
      applyConditions({sample: `CoA ${c.sample}`, temp_c: c.temp_c, time_h: c.time_h, pressure_pa: c.pressure_pa}, {jump: true});
      pred?.setConditions?.({temp_c: c.temp_c, time_h: c.time_h, pressure_pa: c.pressure_pa});
    });
  }

  async function loadCompare(){
    const bp = $('[data-bp]').value.trim(), tg = $('[data-tg]').value.split(',').map(s => s.trim()).filter(Boolean);
    const q = new URLSearchParams(); if (bp) q.set('byproduct', bp); tg.forEach(t => q.append('target', t)); if (ctx.project && ctx.compareByProject) q.set('project', ctx.project);
    const box = $('[data-chart]');
    try { compareData = await ctx.api.json('/api/viz/drying/compare?' + q) }
    catch (e) { box.innerHTML = `<p class="err">${esc(e.message)}</p>`; return }
    conditions();
    if (compareData.note) { box.innerHTML = `<div class="empty">${esc(compareData.note)}</div>`; return }
    box.innerHTML = compareData.targets.map(t => {
      if (!t.groups.length) return `<h3>${esc(t.target)}</h3><p class="small muted">'${esc(t.target)}' 측정값이 없습니다.</p>`;
      const units = [...new Set(t.groups.map(g => g.unit))];
      return units.map(u => { const gs = t.groups.filter(g => g.unit === u); return `<h3>${esc(t.target)} <span class="muted" style="font-weight:400">(${esc(u)})</span></h3>${compareSvg(gs, u)}
        <table><thead><tr><th>방식</th><th class="num">n</th><th class="num">평균</th><th class="num">최소–최대</th><th>시료·문헌</th><th>방식 판단 근거</th></tr></thead><tbody>
        ${gs.map(g => `<tr><td><span class="swatch" style="background:${METHOD_COLOR[g.method] || 'var(--m-unk)'}"></span> ${esc(g.method)}</td><td class="num">${g.n}</td><td class="num">${fmt(g.mean, 3)}</td><td class="num">${fmt(g.min, 3)}–${fmt(g.max, 3)}</td><td>${esc(g.samples.join(', '))}</td><td class="small muted">${esc(g.how.join(', '))}</td></tr>`).join('')}</tbody></table>` }).join('');
    }).join('') + `<p class="small muted" style="margin:8px 0 0">${esc(compareData.privacy)}</p>`;
  }

  $('[data-cut]').onchange = ev => views.forEach(v => v.setCut(ev.currentTarget.checked));
  $('[data-rot]').onchange = ev => views.forEach(v => v.setRotate(ev.currentTarget.checked));
  $('[data-cmp]').onchange = ev => { cmpMethod = ev.currentTarget.value; build3d() };
  $('[data-cmpgo]').onclick = loadCompare;
  $('[data-tg]').addEventListener('keydown', ev => { if (ev.key === 'Enter') loadCompare() });
  $('[data-bp]').addEventListener('keydown', ev => { if (ev.key === 'Enter') loadCompare() });

  (async () => {
    try {
      const [m, ph] = await Promise.all([ctx.api.json('/api/viz/drying/methods'), ctx.api.json('/api/viz/drying/phase')]);
      methods = m.methods; phase = ph; methodsNote = m.note; particleNote = m.particle_note;
    } catch (e) { $('[data-equip]').innerHTML = `<p class="err">건조 방식 자료를 불러오지 못했습니다: ${esc(e.message)}</p>`; return }
    $('[data-gnote]').textContent = methodsNote; $('[data-pnote]').textContent = phase.note; $('[data-pnote2]').textContent = particleNote;
    $('[data-methods]').innerHTML = methods.map(d => `<button data-m="${esc(d.name)}" aria-pressed="false"><span class="swatch" style="background:${METHOD_COLOR[d.name]}"></span>${esc(d.name)}</button>`).join('');
    $('[data-methods]').querySelectorAll('button').forEach(b => b.onclick = () => pick(b.dataset.m));
    $('[data-cmp]').innerHTML = methods.map(d => `<option ${d.name === cmpMethod ? 'selected' : ''}>${esc(d.name)}</option>`).join('');
    pick(methods.some(d => d.name === cur) ? cur : methods[0].name);
    loadCompare();
  })();
  return {pick: m => methods.length && pick(m), refresh: loadCompare, dispose(){ equip.dispose(); views.forEach(v => v.dispose()); pred?.dispose?.() },
    applyConditions};
}
