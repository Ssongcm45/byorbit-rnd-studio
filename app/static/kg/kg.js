// 지식그래프 — 개념(점)과 관계(선)에 자료·측정값을 이어 붙인 지도 (개념 탭 안의 '지식그래프')
//   import {mountKG} from '/static/kg/kg.js';
//   mountKG(el, {api, toast, openSearch, openWorkbench, center?})  → {center(idOrLabel), refresh(), resize(), dispose(), state}
// 데이터는 모두 /api/kg(이 PC)에서 온다. 그래프 라이브러리는 vendor/cytoscape(고정 버전, CDN 없음).
import {esc, fmt, h, makeApi, loadScript, vendorUrl} from '../viz/common.js';

const B = '/api/kg';
const REL = [  // 화면 순서 = 범례 순서
  ['broader', '상위 분류'], ['derivedFrom', '원료'], ['generatedBy', '발생 공정'], ['contains', '함유 성분'],
  ['measured', '측정'], ['mentions', '언급'], ['other', '기타 관계'],
];
const REL_LABEL = Object.fromEntries(REL);
const SCHEMES = [  // [키(클래스), 체계 이름]
  ['Byproduct', '부산물'], ['Category', '분류'], ['SourceCommodity', '원물'], ['Process', '공정'], ['Constituent', '성분'],
  ['Property', '물성'], ['Unit', '단위'], ['Method', '시험법'], ['Application', '용도'],
];
const MATCH = {pref: '표준명', alt: '동의어', hidden: '숨은 표기'};
let uid = 0;

function ensureCss() {
  for (const [k, href] of [['bv-css', '../viz/viz.css'], ['kg-css', './kg.css']]) {
    if (document.querySelector(`link[data-${k}]`)) continue;
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = new URL(href, import.meta.url).href;
    l.setAttribute(`data-${k}`, '1');
    document.head.appendChild(l);
  }
}

const mem = {
  get(k) { try { return JSON.parse(localStorage.getItem('kg:' + k) || 'null') } catch { return null } },
  set(k, v) { try { localStorage.setItem('kg:' + k, JSON.stringify(v)) } catch { /* 저장 못 해도 화면은 그대로 */ } },
};

export function mountKG(el, opts = {}) {
  ensureCss();
  const {json} = makeApi(opts.api);
  const base = typeof opts.api === 'string' ? opts.api.replace(/\/$/, '') : '';
  const toast = opts.toast || (m => console.info(m));
  const id = 'kg' + (++uid);
  const savedTypes = mem.get('types');
  const st = {
    center: null, centerLabel: '', depth: mem.get('depth') === 2 ? 2 : 1, layout: mem.get('layout') === 'concentric' ? 'concentric' : 'cose',
    types: new Set(Array.isArray(savedTypes) && savedTypes.length ? savedTypes : REL.map(r => r[0])),
    graph: null, selected: null, history: [], sugg: [], suggIdx: -1, cy: null, disposed: false, seq: 0, panelSeq: 0,
  };

  const root = h(`<section class="kg" aria-labelledby="${id}-t">
    <h2 class="sr-only" id="${id}-t">지식그래프</h2>
    <p class="kg-explain"><b>개념(점)과 관계(선)로 이어진 지식 지도입니다.</b> 동의어는 같은 점으로 모입니다.
      점을 누르면 옆(좁은 화면에서는 아래)에 자세히, 두 번 누르면 그 개념을 가운데로 옮깁니다.</p>
    <div class="kg-bar">
      <div class="kg-find">
        <input class="inp" id="${id}-q" type="search" autocomplete="off" role="combobox" aria-expanded="false"
          aria-controls="${id}-sugg" aria-autocomplete="list" aria-label="개념 찾기"
          placeholder="개념 찾기 — 표준명·동의어 (예: 사과 포마스, TPC, FD)">
        <ul class="kg-sugg" id="${id}-sugg" role="listbox" aria-label="찾은 개념" hidden></ul>
      </div>
      <span class="seg-l" data-help="kg.depth">깊이</span>
      <div class="seg" role="group" aria-label="깊이">
        <button type="button" data-depth="1" title="가운데 개념과 바로 이어진 점만">1단계</button>
        <button type="button" data-depth="2" title="이웃의 이웃까지">2단계</button></div>
      <span class="seg-l" data-help="kg.layout">배치</span>
      <div class="seg" role="group" aria-label="배치">
        <button type="button" data-layout="cose" title="서로 당기고 밀어 자연스럽게 퍼지는 배치(cose)">그물</button>
        <button type="button" data-layout="concentric" title="가운데 개념에서 1단계·2단계 이웃을 둥근 띠로 나눠 놓는 배치(너비 우선 단계별 동심원)">단계</button></div>
      <button type="button" class="btn sm" data-act="back" disabled title="앞에 보던 개념으로">← 이전</button>
      <span class="grow"></span>
      <a class="btn sm" href="${base}${B}/export.ttl" download="rd-studio-ontology.ttl" title="표준 시드 + 내 확장 개념을 SKOS Turtle로 (Protégé 등)">TTL 내보내기</a>
      <a class="btn sm" href="${base}${B}/export.json" download="rd-studio-knowledge-graph.json" title="점·선 목록 JSON (기밀 자료 이름은 가림, 기밀 측정값은 뺌)">JSON 내보내기</a><span data-help-chips="kg.export" data-help-bare></span>
    </div>
    <div class="kg-chips" role="group" aria-label="선 종류 거르기">
      <span class="seg-l" data-help="kg.edges">선</span>
      ${REL.map(([k, l]) => `<button type="button" class="kg-chip" data-type="${k}" style="--sw:var(--kg-e-${k})" aria-pressed="true">
        <span class="sw${k === 'mentions' ? ' dash' : ''}" aria-hidden="true"></span>${esc(l)} <span class="n" data-n="${k}"></span></button>`).join('')}
    </div>
    <div class="kg-legend" aria-label="점 색 범례">
      <span class="seg-l">점</span>
      ${SCHEMES.map(([k, l]) => `<span><span class="dot" style="--c:var(--kg-${k})" aria-hidden="true"></span>${esc(l)}</span>`).join('')}
      <span><span class="dot doc" aria-hidden="true"></span>자료(문서)</span>
    </div>
    <div class="kg-main">
      <div class="kg-stage">
        <div class="kg-cy" role="img" aria-label="지식그래프 그림. 같은 내용을 아래 '이웃 목록'에서 키보드로 볼 수 있습니다."></div>
        <div class="kg-hint">휠: 확대 · 끌기: 이동 · 두 번 누르기: 가운데로</div>
        <div class="kg-tools"><button type="button" class="btn sm" data-act="fit" title="전체가 보이게">맞춤</button></div>
        <div class="kg-loading">지식그래프를 불러오는 중…</div>
        <div class="kg-status" aria-live="polite"></div>
      </div>
      <aside class="kg-panel" aria-live="polite" aria-label="선택한 점 자세히"><p class="empty">점을 누르면 표준명·동의어·관계·언급 자료·측정값이 여기에 나옵니다.</p></aside>
    </div>
    <details class="kg-nb" open><summary>이웃 목록 <span class="small muted">(키보드로 보기 — 그림과 같은 내용)</span></summary><div class="kg-nbody"></div></details>
    <div class="sr-only" aria-live="polite" id="${id}-live"></div>
  </section>`);
  const inBv = !!el.closest('.bv');
  const shell = inBv ? root : h('<div class="bv"></div>');
  if (!inBv) shell.appendChild(root);
  el.appendChild(shell);
  const $ = s => root.querySelector(s);
  const $$ = s => [...root.querySelectorAll(s)];
  const say = m => { $(`#${id}-live`).textContent = m };
  const fail = e => { const m = e.message || String(e); toast(m); say(m) };

  // ---------------------------------------------------------------- 색 (kg.css 변수 → cytoscape)
  const css = () => {
    const cs = getComputedStyle(root);
    const v = n => cs.getPropertyValue(n).trim();
    const out = {ink: v('--v-ink') || '#131b26', muted: v('--v-muted') || '#586577', surface: v('--v-surface') || '#fff',
      bg: v('--kg-canvas') || '#f4f6f9', accent: v('--v-accent') || '#1d4f9c', doc: v('--kg-Document'), docLine: v('--kg-doc-line')};
    for (const [k] of SCHEMES) out[k] = v('--kg-' + k);
    out.Other = v('--kg-Other');
    for (const [k] of REL) out['e-' + k] = v('--kg-e-' + k);
    return out;
  };
  const styleSheet = c => [
    {selector: 'node', style: {
      'background-color': n => c[n.data('key')] || c.Other, 'label': 'data(label)', 'font-size': 12, 'color': c.ink,
      'text-valign': 'bottom', 'text-halign': 'center', 'text-margin-y': 4, 'text-outline-color': c.bg, 'text-outline-width': 2,
      'width': 22, 'height': 22, 'border-width': 1.5, 'border-color': c.surface, 'text-wrap': 'ellipsis', 'text-max-width': 120,
      'font-family': 'Malgun Gothic, Pretendard, Apple SD Gothic Neo, sans-serif', 'min-zoomed-font-size': 5}},
    {selector: 'node[?more]', style: {'border-color': c.muted, 'border-style': 'dashed', 'border-width': 2}},
    {selector: 'node.doc', style: {'shape': 'round-rectangle', 'width': 22, 'height': 16, 'background-color': c.doc,
      'border-color': c.docLine, 'border-width': 1.5, 'border-style': 'solid', 'font-size': 10, 'color': c.muted, 'text-max-width': 140}},
    {selector: 'node.center', style: {'width': 38, 'height': 38, 'font-size': 14, 'font-weight': 700, 'border-width': 3,
      'border-color': c.ink, 'border-style': 'solid', 'text-margin-y': 5, 'z-index': 10}},
    {selector: 'node:selected', style: {'border-color': c.accent, 'border-width': 4, 'border-style': 'solid', 'overlay-opacity': 0}},
    {selector: 'node.proposed', style: {'background-opacity': .5}},
    {selector: 'edge', style: {
      'width': 1.6, 'line-color': e => c['e-' + e.data('type')] || c['e-other'], 'target-arrow-color': e => c['e-' + e.data('type')] || c['e-other'],
      'target-arrow-shape': 'triangle', 'arrow-scale': .75, 'curve-style': 'bezier', 'opacity': .85,
      'font-size': 9.5, 'color': c.ink, 'text-background-color': c.surface, 'text-background-opacity': .9, 'text-background-padding': 2,
      'text-rotation': 'autorotate', 'label': '', 'font-family': 'Malgun Gothic, Pretendard, sans-serif'}},
    {selector: 'edge[type="mentions"]', style: {'line-style': 'dashed', 'width': e => Math.min(1 + (e.data('count') || 1) * .35, 4.5)}},
    {selector: 'edge[type="measured"]', style: {'width': 2.2, 'line-style': 'solid', 'target-arrow-shape': 'tee'}},
    {selector: 'edge[type="broader"]', style: {'target-arrow-shape': 'triangle-backcurve'}},
    {selector: 'edge.lab', style: {'label': 'data(elabel)', 'opacity': 1, 'z-index': 9}},
    {selector: '.dim', style: {'opacity': .12}},
  ];

  // ---------------------------------------------------------------- 그래프 그리기
  let cyLib = null;
  const getCy = async () => {
    if (cyLib) return cyLib;
    await loadScript(vendorUrl('cytoscape/cytoscape.min.js'));
    cyLib = window.cytoscape;
    if (!cyLib) throw new Error('그래프 라이브러리를 읽지 못했습니다. app/static/vendor/cytoscape 폴더가 있는지 확인하세요.');
    return cyLib;
  };
  const edgeText = e => {
    if (e.type === 'measured') {
      const rng = e.min != null && e.max != null && e.min !== e.max ? ` (${fmt(e.min)}–${fmt(e.max)})` : '';
      return `측정 n=${e.n}` + (e.mean != null ? ` · 평균 ${fmt(e.mean)}${rng} ${e.unit || ''}` : ' · 수치 없음(불검출 등)');
    }
    if (e.type === 'mentions') return `언급 ${e.count}회`;
    return e.label || REL_LABEL[e.type] || e.rel_type;
  };
  // 단계: 서버가 너비 우선으로 매긴 깊이(0·1·2)로 둥근 띠를 나눈다. 같은 띠 안은 선 종류 순서로 놓는다
  const layoutOpts = () => st.layout === 'concentric'
    ? {name: 'concentric', concentric: n => 10 - (n.data('depth') || 0), levelWidth: () => 1, minNodeSpacing: 34,
      sort: (a, b) => (a.data('key') || '').localeCompare(b.data('key') || '') || (a.data('label') || '').localeCompare(b.data('label') || ''),
      spacingFactor: .95, animate: false, padding: 30, nodeDimensionsIncludeLabels: false}
    : {name: 'cose', animate: false, randomize: true, nodeRepulsion: () => 16000, idealEdgeLength: () => 120, nodeOverlap: 20, edgeElasticity: () => 80,
      gravity: .35, numIter: 1500, componentSpacing: 60, padding: 30, nodeDimensionsIncludeLabels: true};

  async function draw(g) {
    const cytoscape = await getCy();
    if (st.disposed) return;
    const els = [
      ...g.nodes.map(n => ({group: 'nodes', data: {...n, more: n.hidden > 0 || n.more_docs > 0},
        classes: [n.kind === 'document' ? 'doc' : '', n.id === g.center ? 'center' : '', n.status && n.status !== 'active' ? 'proposed' : ''].join(' ')})),
      ...g.edges.map(e => ({group: 'edges', data: {...e, id: e.id, elabel: edgeText(e)}})),
    ];
    if (!st.cy) {
      st.cy = cytoscape({container: $('.kg-cy'), elements: els, style: styleSheet(css()), layout: {name: 'preset'},
        minZoom: .2, maxZoom: 3.5, boxSelectionEnabled: false});
      wire(st.cy);
      st.cy.layout(layoutOpts()).run();  // 만든 뒤에 돌려야 계층 배치의 뿌리(가운데 점)를 집을 수 있다
    } else {
      st.cy.elements().remove();
      st.cy.add(els);
      st.cy.layout(layoutOpts()).run();
    }
    st.cy.fit(undefined, 30);
    $('.kg-loading').hidden = true;
  }

  function wire(cy) {
    let last = {id: null, t: 0};
    cy.on('tap', 'node', ev => {
      const n = ev.target, now = Date.now();
      if (last.id === n.id() && now - last.t < 380) { last = {id: null, t: 0}; recenterNode(n.data()); return }
      last = {id: n.id(), t: now};
      select(n.id());
    });
    cy.on('tap', ev => { if (ev.target === cy) clearHover() });
    cy.on('mouseover', 'node', ev => hover(ev.target));
    cy.on('mouseout', 'node', () => { clearHover(); if (st.selected) labelEdges(st.selected) });
    cy.on('mouseover', 'edge', ev => ev.target.addClass('lab'));
    cy.on('mouseout', 'edge', ev => { if (!st.selected || !ev.target.connectedNodes().some(n => n.id() === st.selected)) ev.target.removeClass('lab') });
  }
  const hover = n => {
    const cy = st.cy, nb = n.closedNeighborhood();
    cy.elements().addClass('dim'); nb.removeClass('dim');
    cy.edges().removeClass('lab'); n.connectedEdges().addClass('lab');
  };
  const clearHover = () => { st.cy?.elements().removeClass('dim') };
  const labelEdges = nid => {
    if (!st.cy) return;
    st.cy.edges().removeClass('lab');
    const n = st.cy.getElementById(nid);
    if (n.nonempty() && n.connectedEdges().length <= 12) n.connectedEdges().addClass('lab');
  };
  const recenterNode = d => {
    if (d.kind === 'document') { select(d.id); if (opts.openWorkbench) toast('자료 점은 가운데로 옮기지 않습니다. 오른쪽의 "작업대 열기"를 쓰세요.'); return }
    go(d.id);
  };

  // ---------------------------------------------------------------- 불러오기
  async function go(center, {push = true} = {}) {
    const my = ++st.seq;
    const q = new URLSearchParams({depth: st.depth, types: [...st.types].join(',')});
    if (center) q.set('center', center);
    $('.kg-loading').hidden = false; $('.kg-loading').textContent = '지식그래프를 불러오는 중…';
    let g;
    try { g = await json(`${B}/graph?${q}`) } catch (e) {
      if (my !== st.seq) return;
      $('.kg-loading').textContent = e.message; fail(e); return;
    }
    if (my !== st.seq || st.disposed) return;
    if (push && st.center && st.center !== g.center) st.history.push(st.center);
    st.history = st.history.slice(-20);
    $('[data-act=back]').disabled = !st.history.length;
    st.center = g.center; st.centerLabel = g.center_label; st.graph = g;
    if (!g.nodes.length) { $('.kg-loading').textContent = '보일 점이 없습니다.'; return }
    try { await draw(g) } catch (e) { $('.kg-loading').hidden = false; $('.kg-loading').textContent = e.message; fail(e); return }
    status(g); counts(g); neighbors(g.center);
    select(g.center, {quiet: true});
    say(`'${g.center_label}' 중심, 점 ${g.nodes.length}개 · 선 ${g.edges.length}개`);
  }
  const status = g => {
    $('.kg-status').innerHTML = `<span>가운데: <b>${esc(g.center_label)}</b></span><span>점 ${g.nodes.length} · 선 ${g.edges.length} · 깊이 ${g.depth}</span>` +
      (g.truncated ? `<span class="warn">더 있음 — 점이 ${g.cap}개를 넘어 가까운 것만 보였습니다. 깊이를 1로 줄이거나 선 종류를 끄세요.</span>` : '');
  };
  const counts = g => {
    for (const [k] of REL) { const s = $(`[data-n="${k}"]`); if (s) s.textContent = g.edge_counts?.[k] ? g.edge_counts[k] : '' }
  };

  // ---------------------------------------------------------------- 이웃 목록 (키보드 대안)
  function neighbors(nid) {
    const g = st.graph; if (!g) return;
    const node = g.nodes.find(n => n.id === nid); if (!node) return;
    const name = Object.fromEntries(g.nodes.map(n => [n.id, n]));
    const groups = {};
    for (const e of g.edges) {
      let other = null, dir = '';
      if (e.source === nid) { other = e.target; dir = '→' } else if (e.target === nid) { other = e.source; dir = '←' } else continue;
      const k = e.type + dir;
      (groups[k] ||= {type: e.type, dir, items: []}).items.push({n: name[other], e});
    }
    const order = REL.map(r => r[0]);
    const list = Object.values(groups).sort((a, b) => order.indexOf(a.type) - order.indexOf(b.type) || (a.dir < b.dir ? -1 : 1));
    $('.kg-nbody').innerHTML = `<p class="small muted" style="margin:6px 0 0">‘${esc(node.label)}’에 바로 이어진 점 ${list.reduce((s, x) => s + x.items.length, 0)}개.
      이름을 누르면 자세히, ‘가운데로’를 누르면 그 개념을 중심으로 다시 그립니다.</p>` + (list.map(gp => `<div class="grp" style="--el:var(--kg-e-${gp.type})">
      <b>${gp.dir === '→' ? '' : '← '}${esc(REL_LABEL[gp.type] || gp.type)}${gp.dir === '→' ? ' →' : ''}</b> <span class="small muted">${gp.items.length}</span>
      <ul>${gp.items.filter(x => x.n).map(x => `<li><button type="button" data-sel="${esc(x.n.id)}">${esc(x.n.label)}${x.e.type === 'mentions' ? ` <span class="muted">(${x.e.count}회)</span>` : ''}${x.e.type === 'measured' && x.e.mean != null ? ` <span class="muted">(평균 ${fmt(x.e.mean)} ${esc(x.e.unit || '')})</span>` : ''}</button>
        ${x.n.kind === 'concept' ? `<button type="button" class="btn sm" data-go="${esc(x.n.id)}" aria-label="${esc(x.n.label)}을 가운데로">가운데로</button>` : ''}</li>`).join('')}</ul></div>`).join('') || '<p class="empty">이어진 점이 없습니다. 선 종류 거르기를 확인하세요.</p>');
  }

  // ---------------------------------------------------------------- 옆 패널
  async function select(nid, {quiet = false} = {}) {
    st.selected = nid;
    if (st.cy) {
      st.cy.nodes().unselect();
      const n = st.cy.getElementById(nid);
      if (n.nonempty()) n.select();
      labelEdges(nid);
    }
    neighbors(nid);
    const panel = $('.kg-panel');
    const my = ++st.panelSeq;
    panel.innerHTML = '<p class="empty">불러오는 중…</p>';
    try {
      if (nid.startsWith('doc:')) {
        const d = await json(`${B}/document/${encodeURIComponent(nid.slice(4))}`);
        if (my === st.panelSeq) panel.innerHTML = docPanel(d);
      } else {
        const c = await json(`${B}/concept/${encodeURIComponent(nid)}`);
        if (my === st.panelSeq) panel.innerHTML = conceptPanel(c);
      }
      if (!quiet) say('자세히: ' + (panel.querySelector('h3')?.textContent || ''));
    } catch (e) { if (my === st.panelSeq) panel.innerHTML = `<p class="err">${esc(e.message)}</p>` }
  }
  const sch = (key, name) => `<span class="sch" style="--c:var(--kg-${esc(key || 'Other')})">${esc(name || '')}</span>`;
  const conf = c => c === '기밀' ? '<span class="pill bad">기밀</span>' : c === '내부' ? '<span class="pill warn">내부</span>' : '<span class="pill">일반</span>';
  function conceptPanel(c) {
    const pref = c.labels.pref || [], alt = c.labels.alt || [], hid = c.labels.hidden || [];
    const en = c.pref_label_en || pref.find(l => l.lang === 'en')?.label || '';
    const rel = (rows, dir) => rows.map(r => `<li style="--el:var(--kg-e-${REL_LABEL[r.rel_type] ? r.rel_type : 'other'})">
      <span class="rl">${dir === 'in' ? '← ' : ''}${esc(r.rel_label)}</span>
      <button type="button" class="linkish" data-go="${esc(r.concept_id)}" title="가운데로">${esc(r.label)}</button> ${sch(r.key, r.scheme)}</li>`).join('');
    const INLIM = 14;
    const inRows = c.relations_in || [];
    const m = c.measurements || {rows: []};
    const mtitle = m.role === 'byproduct' ? '이 부산물에서 잰 항목' : m.role === 'target' ? '이 항목을 잰 부산물' : '';
    return `<h3>${esc(c.pref_label)} ${sch(c.key, c.scheme)}${c.status !== 'active' ? ' <span class="pill warn">제안</span>' : ''}${c.origin === 'mine' ? ' <span class="pill external">내 확장</span>' : ''}</h3>
      ${en ? `<div class="muted small">${esc(en)}</div>` : ''}
      <div class="kv" style="margin-top:10px">
        <b>표준명</b><span>${pref.map(l => `<span class="tag">${esc(l.label)}${l.lang ? `<span class="muted lang">${esc(l.lang)}</span>` : ''}</span>`).join('')}</span>
        <b>동의어</b><span>${alt.map(l => `<span class="tag">${esc(l.label)}</span>`).join('') || '<span class="muted">없음</span>'}</span>
        <b>숨은 표기</b><span>${hid.map(l => `<span class="tag hid" title="검색·라벨링에는 쓰지만 화면에 표준으로 보이지 않는 표기(오타·옛 표기)">${esc(l.label)}</span>`).join('') || '<span class="muted">없음</span>'}</span>
        <b>체계</b><span>${esc(c.scheme || '')}${c.class?.label_en ? ` <span class="muted">· 클래스 ${esc(c.class.label_en)}</span>` : ''}${c.byproduct?.sector ? ` <span class="muted">· ${esc(c.byproduct.sector)}</span>` : ''}</span>
        <b>IRI</b><span><code>${esc(c.iri || '')}</code></span>
        ${c.definition ? `<b>정의</b><span>${esc(c.definition)}</span>` : ''}
      </div>
      <div class="kg-actions">
        ${c.concept_id !== st.center ? `<button type="button" class="btn sm primary" data-go="${esc(c.concept_id)}">가운데로</button>` : ''}
        ${opts.openSearch ? `<button type="button" class="btn sm" data-search="${esc(c.pref_label)}" title="동의어까지 넓혀 자료를 찾습니다">검색 열기</button>` : ''}
        <button type="button" class="btn sm" data-copy="${esc(c.iri || '')}">IRI 복사</button>
      </div>
      <h4>관계 <span class="n">${(c.relations_out || []).length + inRows.length}</span></h4>
      ${(c.relations_out || []).length || inRows.length ? `<ul class="rels">${rel(c.relations_out || [], 'out')}${rel(inRows.slice(0, INLIM), 'in')}</ul>
        ${inRows.length > INLIM ? `<details><summary class="small muted">← 들어오는 관계 ${inRows.length - INLIM}개 더</summary><ul class="rels">${rel(inRows.slice(INLIM), 'in')}</ul></details>` : ''}` : '<p class="small muted">이어진 관계가 없습니다.</p>'}
      <h4>언급 자료 <span class="n">${c.documents.length}</span></h4>
      ${c.documents.length ? `<ul class="docs">${c.documents.map(d => `<li><span class="fn">${esc(d.title || d.file_name)}</span>
        <span class="row small muted">${conf(d.confidentiality)} 라벨 ${d.mentions}개${d.year ? ' · ' + esc(d.year) : ''}</span>
        <span class="row">${opts.openWorkbench ? `<button type="button" class="btn sm" data-wb="${esc(d.doc_id)}" data-chunk="${esc(d.first_chunk_id || '')}">작업대 열기</button>` : ''}
        ${opts.openSearch ? `<button type="button" class="btn sm" data-search="${esc(c.pref_label)}">검색 열기</button>` : ''}</span></li>`).join('')}</ul>`
        : '<p class="small muted">아직 이 개념을 가리킨 라벨이 없습니다. 자료를 넣으면 사전 라벨링이 자동으로 이어 줍니다.</p>'}
      ${m.rows.length ? `<h4>측정값 요약 <span class="n">${m.rows.reduce((s, r) => s + r.n, 0)}개</span></h4>
        <p class="small muted" style="margin:0 0 4px">${mtitle}. 시료 식별 정보(로트·공급처)는 싣지 않습니다. 값 하나하나는 ‘측정값’ 탭에서 봅니다.</p>
        <table class="meas"><thead><tr><th>${m.role === 'byproduct' ? '항목' : '부산물'}</th><th class="num">n</th><th class="num">평균</th><th class="num">범위</th><th>단위</th></tr></thead>
        <tbody>${m.rows.map(r => `<tr><td>${r.concept_id ? `<button type="button" class="linkish" data-go="${esc(r.concept_id)}">${esc(r.item)}</button>` : esc(r.item)}</td>
          <td class="num">${r.n}</td><td class="num">${r.mean != null ? fmt(r.mean) : '-'}</td>
          <td class="num">${r.min != null && r.max != null && r.min !== r.max ? `${fmt(r.min)}–${fmt(r.max)}` : r.min != null ? fmt(r.min) : '-'}</td><td>${esc(r.unit || '')}</td></tr>`).join('')}</tbody></table>
        ${m.rows.some(r => r.n_numeric < r.n) ? '<p class="small muted" style="margin:4px 0 0">수치가 없는 값(불검출·음성 등)은 n에만 셉니다.</p>' : ''}` : ''}`;
  }
  function docPanel(d) {
    return `<h3>${esc(d.title || d.file_name)} <span class="sch" style="--c:var(--kg-doc-line)">자료</span></h3>
      <div class="kv" style="margin-top:10px"><b>파일</b><span>${esc(d.file_name)}</span><b>등급</b><span>${conf(d.confidentiality)}</span>
        <b>종류</b><span>${esc(d.source_type || '')}${d.year ? ' · ' + esc(d.year) : ''}</span><b>측정값</b><span>${d.measurements}개</span></div>
      <div class="kg-actions">${opts.openWorkbench ? `<button type="button" class="btn sm primary" data-wb="${esc(d.doc_id)}" data-chunk="${esc(d.first_chunk_id || '')}">작업대 열기</button>` : ''}</div>
      <h4>이 자료가 언급한 개념 <span class="n">${d.concepts.length}</span></h4>
      ${d.concepts.length ? `<ul class="rels">${d.concepts.map(k => `<li><span class="rl" style="--el:var(--v-muted)">${k.mentions}회</span>
        <button type="button" class="linkish" data-go="${esc(k.concept_id)}">${esc(k.label)}</button> ${sch(k.key, k.scheme)}</li>`).join('')}</ul>` : '<p class="small muted">라벨이 없습니다.</p>'}`;
  }

  // ---------------------------------------------------------------- 찾기 (동의어 포함)
  const input = $(`#${id}-q`), box = $(`#${id}-sugg`);
  let tq = null;
  const closeSugg = () => { box.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); st.suggIdx = -1 };
  const paintSugg = () => {
    box.innerHTML = st.sugg.length ? st.sugg.map((s, i) => `<li role="option" id="${id}-o${i}" data-i="${i}" aria-selected="${i === st.suggIdx}">
      ${s.via ? `<span class="via">${esc(s.via)}</span><span class="arrow" aria-label="표준명">→</span>` : ''}<b>${esc(s.pref_label)}</b>
      ${sch(s.key, s.scheme)}${s.via ? `<span class="small muted">${esc(MATCH[s.match_type] || '')}</span>` : ''}</li>`).join('')
      : '<li class="empty" role="option" aria-disabled="true">맞는 개념이 없습니다. 다른 표기(영문·약어)로 찾아 보거나 ‘분류·목록’에서 개념을 추가하세요.</li>';
    box.hidden = false; input.setAttribute('aria-expanded', 'true');
    if (st.suggIdx >= 0) input.setAttribute('aria-activedescendant', `${id}-o${st.suggIdx}`); else input.removeAttribute('aria-activedescendant');
  };
  const pick = i => { const s = st.sugg[i]; if (!s) return; closeSugg(); input.value = s.via ? `${s.via} → ${s.pref_label}` : s.pref_label; go(s.concept_id) };
  input.addEventListener('input', () => {
    clearTimeout(tq);
    const q = input.value.trim();
    if (!q) { closeSugg(); return }
    tq = setTimeout(async () => {
      try { const r = await json(`${B}/search?${new URLSearchParams({q, limit: 12})}`); if (input.value.trim() !== q) return; st.sugg = r.results; st.suggIdx = r.results.length ? 0 : -1; paintSugg() } catch (e) { fail(e) }
    }, 180);
  });
  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (box.hidden || !st.sugg.length) return;
      e.preventDefault();
      st.suggIdx = (st.suggIdx + (e.key === 'ArrowDown' ? 1 : -1) + st.sugg.length) % st.sugg.length; paintSugg();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (!box.hidden && st.suggIdx >= 0) pick(st.suggIdx);
      else if (input.value.trim()) go(input.value.trim().split('→').pop().trim());
    } else if (e.key === 'Escape') closeSugg();
  });
  input.addEventListener('blur', () => setTimeout(closeSugg, 150));
  box.addEventListener('mousedown', e => { const li = e.target.closest('li[data-i]'); if (li) { e.preventDefault(); pick(+li.dataset.i) } });

  // ---------------------------------------------------------------- 버튼
  const paintSeg = () => {
    $$('[data-depth]').forEach(b => b.setAttribute('aria-pressed', String(+b.dataset.depth === st.depth)));
    $$('[data-layout]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.layout === st.layout)));
    $$('[data-type]').forEach(b => b.setAttribute('aria-pressed', String(st.types.has(b.dataset.type))));
  };
  root.addEventListener('click', e => {
    const t = e.target.closest('button,a'); if (!t || !root.contains(t)) return;
    if (t.dataset.depth) { st.depth = +t.dataset.depth; mem.set('depth', st.depth); paintSeg(); go(st.center, {push: false}) }
    else if (t.dataset.layout) { st.layout = t.dataset.layout; mem.set('layout', st.layout); paintSeg(); if (st.cy) { st.cy.layout(layoutOpts()).run(); st.cy.fit(undefined, 30) } }
    else if (t.dataset.type) {
      const k = t.dataset.type;
      if (st.types.has(k) && st.types.size === 1) { toast('선 종류를 하나는 남겨 두세요.'); return }
      st.types.has(k) ? st.types.delete(k) : st.types.add(k);
      mem.set('types', [...st.types]); paintSeg(); go(st.center, {push: false});
    }
    else if (t.dataset.act === 'fit') st.cy?.fit(undefined, 30);
    else if (t.dataset.act === 'back') { const prev = st.history.pop(); if (prev) go(prev, {push: false}); $('[data-act=back]').disabled = !st.history.length }
    else if (t.dataset.go) go(t.dataset.go);
    else if (t.dataset.sel) { select(t.dataset.sel); const n = st.cy?.getElementById(t.dataset.sel); if (n?.nonempty()) st.cy.animate({center: {eles: n}, duration: 200}) }
    else if (t.dataset.search != null && opts.openSearch) opts.openSearch(t.dataset.search);
    else if (t.dataset.wb && opts.openWorkbench) opts.openWorkbench(t.dataset.wb, t.dataset.chunk || null, 'labels');
    else if (t.dataset.copy != null) {
      navigator.clipboard?.writeText(t.dataset.copy).then(() => toast('IRI를 복사했습니다'), () => toast(t.dataset.copy));
    }
  });

  // 밝은·어두운 화면이 바뀌면 색을 다시 읽는다
  const mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  const restyle = () => { if (st.cy) st.cy.style(styleSheet(css())) };
  mq?.addEventListener?.('change', restyle);
  let lastW = 0;
  const ro = window.ResizeObserver ? new ResizeObserver(ents => {  // 판 크기가 바뀌면(창 크기·탭 전환) 다시 맞춘다
    const w = Math.round(ents[0]?.contentRect.width || 0);
    if (!st.cy || !w || Math.abs(w - lastW) < 8) return;
    lastW = w; st.cy.resize(); st.cy.fit(undefined, 30);
  }) : null;
  ro?.observe($('.kg-cy'));

  paintSeg();
  go(opts.center || null);

  return {
    state: st,
    center: c => go(c),
    refresh: () => go(st.center, {push: false}),
    resize: () => { st.cy?.resize(); st.cy?.fit(undefined, 30) },
    restyle,
    dispose: () => { st.disposed = true; mq?.removeEventListener?.('change', restyle); ro?.disconnect(); st.cy?.destroy(); shell.remove() },
  };
}
