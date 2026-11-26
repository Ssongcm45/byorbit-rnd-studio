// 분자 구조: 검색(동의어) → 2D 구조식(RDKit SVG) + 3D(3Dmol.js) + 성질표. 로컬에 없을 때만 PubChem 가져오기.
import {esc, h, fmt, loadScript, vendorUrl, reducedMotion} from './common.js';

const PROPS = [
  ['formula', '분자식'], ['mw', '분자량 (g/mol)'], ['exact_mass', '정확 질량'], ['logp', 'logP (Crippen)'],
  ['hbd', '수소결합 주개'], ['hba', '수소결합 받개'], ['tpsa', 'TPSA (Å²)'], ['rotatable_bonds', '회전 가능 결합'], ['heavy_atoms', '무거운 원자 수']];

export function mountMolecule(el, ctx){
  el.innerHTML = `
  <div class="card">
    <div class="row">
      <h2 class="grow" data-help="viz.molecule">분자 구조</h2>
      <input class="inp" data-q list="bvMolList" placeholder="예: 클로로겐산 · chlorogenic acid · 총폴리페놀" aria-label="성분명 검색" style="width:min(340px,100%)" autocomplete="off">
      <datalist id="bvMolList"></datalist>
      <button class="btn primary" data-go>보기</button>
    </div>
    <p class="sub" style="margin-top:6px">한글·영문·동의어로 찾습니다. 구조는 이 PC의 시드와 RDKit으로 그립니다(인터넷 불필요).</p>
    <div data-chips class="chips"></div>
    <p data-rdkit class="notice" hidden></p>
  </div>
  <div data-out></div>`;
  const $ = s => el.querySelector(s);
  let viewer = null, spin = !reducedMotion(), style = 'stick', curKey = null, list = null;

  async function loadList(){
    try {
      list = await ctx.api.json('/api/viz/structures');
      if (!list.rdkit) { const n = $('[data-rdkit]'); n.hidden = false; n.innerHTML = `<b>RDKit 없음</b> — ${esc(list.message)}` }
      $('#bvMolList').innerHTML = list.items.map(i => `<option value="${esc(i.ko)}">${esc(i.en || '')}</option>`).join('') +
        list.representatives.map(r => `<option value="${esc(r.term)}">대표 구조로 보기</option>`).join('');
      const byClass = {};
      list.items.forEach(i => (byClass[i.class_ko || '기타'] ||= []).push(i));
      $('[data-chips]').innerHTML = Object.entries(byClass).map(([c, items]) =>
        `<span class="small muted" style="margin:4px 4px 0 6px;align-self:center">${esc(c)}</span>` +
        items.map(i => `<button class="chip" data-term="${esc(i.ko)}">${esc(i.ko)}</button>`).join('')).join('') +
        `<span class="small muted" style="margin:4px 4px 0 6px;align-self:center">고분자·혼합물(대표 구조)</span>` +
        list.representatives.map(r => `<button class="chip rep" data-term="${esc(r.term)}" title="${esc(r.note)}">${esc(r.term)}</button>`).join('');
      $('[data-chips]').querySelectorAll('[data-term]').forEach(b => b.onclick = () => open(b.dataset.term));
    } catch (e) { $('[data-chips]').innerHTML = `<p class="err">성분 목록을 불러오지 못했습니다: ${esc(e.message)}</p>` }
  }

  async function open(term){
    term = String(term || '').trim();
    if (!term) return;
    $('[data-q]').value = term;
    const out = $('[data-out]');
    out.innerHTML = '<div class="card"><div class="empty">찾는 중…</div></div>';
    let r;
    try { r = await ctx.api.json('/api/viz/structures/resolve?term=' + encodeURIComponent(term)) }
    catch (e) { out.innerHTML = `<div class="card"><p class="err">${esc(e.message)}</p></div>`; return }
    if (!r.found) return notFound(r);
    show(r);
  }

  function notFound(r){
    const out = $('[data-out]');
    out.innerHTML = `<div class="card">
      <h2>'${esc(r.term)}'의 구조가 이 PC에 없습니다</h2>
      <p class="sub">${esc(r.message)}</p>
      ${r.suggestions?.length ? `<p class="small">비슷한 이름: ${r.suggestions.map(s => `<button class="chip" data-term="${esc(s.ko)}">${esc(s.ko)}</button>`).join(' ')}</p>` : ''}
      <div class="info">
        <b>PubChem에서 가져오기</b> — 아래 <b>영문 성분명 하나만</b> PubChem(미국 국립보건원 공개 화학 DB)에 보냅니다.
        시료·공급처·로트 정보나 측정값은 보내지 않습니다. 받은 구조는 이 PC에 저장되어 다음부터는 인터넷 없이 보입니다.
        <div class="row" style="margin-top:8px">
          <input class="inp grow" data-en value="${esc(r.name_en || '')}" placeholder="영문 성분명 (예: ferulic acid)" aria-label="보낼 영문 성분명">
          <button class="btn primary" data-fetch>PubChem에서 가져오기</button>
        </div>
        <p data-fmsg class="small" style="margin:6px 0 0"></p>
      </div></div>`;
    out.querySelectorAll('[data-term]').forEach(b => b.onclick = () => open(b.dataset.term));
    out.querySelector('[data-fetch]').onclick = async () => {
      const en = out.querySelector('[data-en]').value.trim(), msg = out.querySelector('[data-fmsg]');
      if (!en) { msg.innerHTML = '<span class="err">보낼 영문 성분명을 넣으세요.</span>'; return }
      msg.textContent = `PubChem에 '${en}'만 보내는 중…`;
      try {
        const e = await ctx.api.json('/api/viz/structures/fetch', {method:'POST', body:{name_en: en, term: r.term}});
        await loadList(); show({...e, found:true}); ctx.toast?.(e.message);
      } catch (e) { msg.innerHTML = `<span class="err">${esc(e.message)}</span>` }
    };
  }

  async function show(e){
    curKey = e.key;
    const out = $('[data-out]');
    out.innerHTML = `
    ${e.representative ? `<div class="notice" role="note"><b>대표 구조</b> — '${esc(e.represents)}'은(는) 단일 분자가 아닙니다. ${esc(e.representative_note)}</div>` : ''}
    <div class="card">
      <div class="row"><h2 class="grow">${esc(e.ko)} <span class="muted" style="font-weight:400">${esc(e.en || '')}</span></h2>
        <span class="pill">${esc(e.class_ko || '')}</span><span class="pill ${e.source?.startsWith('PubChem') ? 'external' : 'local'}">${esc(e.source || '')}</span></div>
      <p class="sub">${esc(e.note || '')}</p>
      <div class="grid2">
        <div><h3>2D 구조식</h3><div class="mol2d-box" data-2d><span class="muted small">그리는 중…</span></div></div>
        <div><div class="row"><h3 class="grow">3D 모델</h3>
            <div class="seg" role="group" aria-label="3D 표현">
              <button data-style="stick" aria-pressed="true">막대</button><button data-style="sphere" aria-pressed="false">공</button><button data-style="surface" aria-pressed="false">표면</button></div>
            <button class="btn sm" data-spin aria-pressed="${spin}">회전</button></div>
          <div class="mol3d-box" data-3d aria-label="${esc(e.ko)} 3D 모델 (드래그로 회전, 휠로 확대)"><div class="empty">3D 좌표를 만드는 중…</div></div>
          <p class="small muted" style="margin:4px 0 0">ETKDGv3로 좌표를 만들고 MMFF94로 다듬은 한 가지 형태(형태이성질체 중 하나)입니다.</p></div>
      </div>
      <h3>성질 (RDKit 계산값)</h3><div data-props class="small muted">계산 중…</div>
      <p class="small muted" style="margin:8px 0 0">SMILES <code class="small" style="word-break:break-all">${esc(e.smiles)}</code></p>
    </div>`;
    out.querySelectorAll('[data-style]').forEach(b => b.onclick = () => { style = b.dataset.style; out.querySelectorAll('[data-style]').forEach(x => x.setAttribute('aria-pressed', x === b)); applyStyle() });
    out.querySelector('[data-spin]').onclick = ev => { spin = !spin; ev.currentTarget.setAttribute('aria-pressed', spin); viewer?.spin(spin ? 'y' : false) };
    const key = e.key;
    ctx.api.text(`/api/viz/structures/${encodeURIComponent(key)}.svg`).then(svg => {
      if (curKey === key) out.querySelector('[data-2d]').innerHTML = svg;
    }).catch(err => { out.querySelector('[data-2d]').innerHTML = `<p class="err" style="padding:12px">${esc(err.message)}</p>` });
    ctx.api.json(`/api/viz/structures/${encodeURIComponent(key)}`).then(d => {
      if (curKey !== key) return;
      out.querySelector('[data-props]').innerHTML = d.props
        ? `<table style="max-width:520px"><tbody>${PROPS.map(([k, l]) => `<tr><th>${l}</th><td class="num" style="text-align:left">${k === 'formula' ? esc(d.props[k]) : fmt(d.props[k], 4)}</td></tr>`).join('')}
           ${d.props.charge ? `<tr><th>전하</th><td>${d.props.charge > 0 ? '+' : ''}${d.props.charge} (양이온 형태)</td></tr>` : ''}</tbody></table>`
        : `<p class="err">${esc(d.message || '성질을 계산하지 못했습니다.')}</p>`;
    }).catch(err => { out.querySelector('[data-props]').innerHTML = `<p class="err">${esc(err.message)}</p>` });
    load3d(key, out.querySelector('[data-3d]'));
  }

  async function load3d(key, box){
    viewer = null;
    let sdf;
    try { sdf = await ctx.api.text(`/api/viz/structures/${encodeURIComponent(key)}.sdf`) }
    catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return }
    try { await loadScript(vendorUrl('3dmol/3Dmol-min.js')) }
    catch (e) { box.innerHTML = `<div class="empty">3D 라이브러리(3Dmol.js)를 불러오지 못했습니다. app/static/vendor/3dmol 폴더를 확인하세요.</div>`; return }
    if (curKey !== key) return;
    box.innerHTML = '';
    try {
      viewer = window.$3Dmol.createViewer(box, {backgroundAlpha: 0, antialias: true});
      viewer.addModel(sdf, 'sdf');
      applyStyle();
      viewer.zoomTo(); viewer.render();
      if (spin) viewer.spin('y');
    } catch (e) { box.innerHTML = `<div class="empty">3D 화면을 만들지 못했습니다(WebGL 미지원일 수 있음): ${esc(e.message)}</div>` }
  }

  function applyStyle(){
    if (!viewer) return;
    viewer.removeAllSurfaces();
    const dark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
    const scheme = {prop:'elem', map: {C: dark ? 0xc9d1dc : 0x5b6470, H: dark ? 0xeeeeee : 0xb8c0ca, O: 0xd84438, N: 0x4477e0, S: 0xd49e14}};
    if (style === 'stick') viewer.setStyle({}, {stick:{radius:.16, colorscheme:scheme}, sphere:{scale:.22, colorscheme:scheme}});
    else if (style === 'sphere') viewer.setStyle({}, {sphere:{colorscheme:scheme}});
    else { viewer.setStyle({}, {stick:{radius:.12, colorscheme:scheme}}); viewer.addSurface(window.$3Dmol.SurfaceType.VDW, {opacity:.72, colorscheme:scheme}) }
    viewer.render();
  }

  $('[data-go]').onclick = () => open($('[data-q]').value);
  $('[data-q]').addEventListener('keydown', ev => { if (ev.key === 'Enter') open(ev.currentTarget.value) });
  loadList();
  return {open};
}
