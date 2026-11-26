// 흐름: 두 시스템(R&D Studio + Food MCP)을 묶은 구성도 + 자료 처리 파이프라인
import {esc, h, fmt, reducedMotion} from './common.js';

const CW = 184, CH = 58;
const COLS = [24, 292, 560, 828, 1110];
const colX = c => COLS[c], rowY = r => 64 + r * 106;
const W = colX(4) + CW + 24, H = rowY(3) + CH + 26;
// 화면 배치(백엔드 col/row보다 우선) — 선이 노드를 지나지 않게 고른 자리
const POS = {browser:[0,1], fastapi:[1,1], watcher:[0,3], folder:[1,3], sqlite:[2,2], claude:[2,0],
  mcp_rd:[3,2], mcp_food:[3,1], anthropic:[4,0], neon:[4,1], pubchem:[4,2], codex:[4,3]};
const KIND_COLOR = {local:'var(--v-accent)', cloud:'var(--v-warn)', external:'var(--v-earth)'};
const KIND_KO = {local:'이 PC', cloud:'클라우드', external:'외부(선택)'};
const STATUS_KO = {ok:'동작', off:'꺼짐', missing:'없음'};
const STATUS_COLOR = {ok:'var(--v-ok)', off:'var(--v-muted)', missing:'var(--v-bad)'};

function box(id){ const [c, r] = POS[id] || [0, 0]; return {x: colX(c), y: rowY(r)} }
const L = (b, f=.5) => [b.x, b.y + CH * f], R = (b, f=.5) => [b.x + CW, b.y + CH * f];
const T = (b, f=.5) => [b.x + CW * f, b.y], B = (b, f=.5) => [b.x + CW * f, b.y + CH];

function route(from, to){
  const a = box(from), b = box(to), gapX = c => colX(c) - 42;
  const k = from + '>' + to;
  switch (k) {
    case 'browser>fastapi': return [R(a), L(b)];
    case 'watcher>fastapi': return [T(a), [a.x + CW / 2, rowY(2) + CH / 2], [b.x + 30, rowY(2) + CH / 2], B(b, 30 / CW)];
    case 'fastapi>folder': return [B(a, .4), T(b, .4)];
    case 'fastapi>sqlite': return [R(a, .72), [gapX(2), a.y + CH * .72], [gapX(2), b.y + CH / 2], L(b)];
    case 'fastapi>claude': return [R(a, .28), [gapX(2), a.y + CH * .28], [gapX(2), b.y + CH / 2], L(b)];
    case 'claude>anthropic': return [R(a), L(b)];
    case 'claude>mcp_food': return [B(a, .45), [a.x + CW * .45, b.y + CH / 2], L(b)];
    case 'claude>mcp_rd': return [B(a, .85), [a.x + CW * .85, rowY(2) - 32], [gapX(3), rowY(2) - 32], [gapX(3), b.y + CH * .3], L(b, .3)];
    case 'mcp_rd>sqlite': return [L(a, .72), R(b, .72)];
    case 'mcp_food>neon': return [R(a), L(b)];
    case 'fastapi>pubchem': return [B(a, .8), [a.x + CW * .8, rowY(2) - 14], [gapX(4), rowY(2) - 14], [gapX(4), b.y + CH / 2], L(b)];
    case 'fastapi>codex': return [B(a, .93), [a.x + CW * .93, rowY(3) - 18], [gapX(4) + 12, rowY(3) - 18], [gapX(4) + 12, b.y + CH / 2], L(b)];
    default: return [R(a), L(b)];
  }
}
const pathD = pts => 'M' + pts.map(p => p.map(v => v.toFixed(1)).join(',')).join(' L');
// 라벨이 겹치지 않게 고른 자리: [구간 번호, 구간 안 위치 0~1]
const LABEL_AT = {'claude>mcp_food': [1, .72], 'claude>mcp_rd': [0, .35], 'fastapi>sqlite': [1, .3]};
function midpoint(pts, key){
  const o = LABEL_AT[key];
  if (o) { const [i, t] = o; return [pts[i][0] + (pts[i+1][0] - pts[i][0]) * t, pts[i][1] + (pts[i+1][1] - pts[i][1]) * t] }
  // 가장 긴 구간의 가운데
  let best = 0, bi = 0;
  for (let i = 0; i < pts.length - 1; i++) { const d = Math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1]); if (d > best) { best = d; bi = i } }
  return [(pts[bi][0] + pts[bi+1][0]) / 2, (pts[bi][1] + pts[bi+1][1]) / 2];
}

export function mountFlow(el, ctx){
  el.innerHTML = `
  <div class="card">
    <div class="row"><h2 class="grow" data-help="viz.flow">두 시스템을 묶은 구조</h2>
      <span class="pill local">■ 이 PC</span><span class="pill cloud">■ 클라우드</span><span class="pill external">■ 외부(선택)</span>
      <button class="btn sm" data-act="refresh">새로고침</button></div>
    <p class="sub">R&amp;D Studio(이 PC)와 ByOrbit Food MCP가 Claude Code를 가운데 두고 어떻게 이어지는지, 각 경계를 무엇이 넘는지 보여줍니다. 상자나 선을 누르면 자세히 봅니다.</p>
    <div data-map><div class="empty">구성도를 불러오는 중…</div></div>
  </div>
  <div class="split">
    <div class="card" data-detail><h2>자세히</h2><p class="sub">구성도에서 상자(구성 요소)나 선(데이터 흐름)을 누르세요. 주황 선이 PC 밖으로 나가는 흐름입니다.</p></div>
    <div class="card"><h2>PC 밖으로 나가는 것</h2><div data-out class="small"></div></div>
  </div>
  <div class="card">
    <div class="row"><h2 class="grow" data-help="viz.pipeline">자료 처리 파이프라인</h2>
      <label class="small muted">프로젝트 <select class="inp" data-proj aria-label="프로젝트"><option value="">전체</option></select></label></div>
    <p class="sub">투입한 자료가 청크 → 라벨 → 측정값 → 리포트로 이어지는 개수입니다.</p>
    <div data-pipe><div class="empty">불러오는 중…</div></div>
  </div>`;
  const $ = s => el.querySelector(s);
  let data = null, sel = null;

  async function load(){
    try { data = await ctx.api.json('/api/viz/system') }
    catch (e) { $('[data-map]').innerHTML = `<p class="err">구성도를 불러오지 못했습니다: ${esc(e.message)} — 앱이 실행 중인지 확인하고 새로고침을 누르세요.</p>`; return }
    draw(); outList();
  }

  function draw(){
    const nodes = data.nodes, edges = data.edges, anim = !reducedMotion();
    const markers = Object.entries({local:'var(--v-muted)', cloud:'var(--v-warn)', external:'var(--v-earth)'}).map(([k, c]) =>
      `<marker id="bvArr-${k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${c}"/></marker>`).join('');
    const pcRight = colX(3) + CW + 13;
    let s = `<svg class="flowsvg" viewBox="0 0 ${W} ${H}" role="group" aria-label="시스템 구성도">
      <defs>${markers}</defs>
      <rect x="8" y="10" width="${pcRight - 8}" height="${H - 16}" rx="14" fill="none" stroke="var(--v-accent)" stroke-opacity=".45" stroke-dasharray="6 5"/>
      <text x="20" y="32" font-size="13" font-weight="700" fill="var(--v-accent)">이 PC (로컬) — 원본 파일·DB는 여기를 떠나지 않음</text>
      <rect x="${colX(4) - 13}" y="10" width="${CW + 26}" height="${H - 16}" rx="14" fill="var(--v-warn)" fill-opacity=".06" stroke="var(--v-warn)" stroke-opacity=".55" stroke-dasharray="6 5"/>
      <text x="${colX(4)}" y="32" font-size="13" font-weight="700" fill="var(--v-warn)">PC 밖</text>`;
    edges.forEach((e, i) => {
      const pts = route(e.from, e.to), d = pathD(pts), col = e.boundary === 'local' ? 'var(--v-muted)' : e.boundary === 'cloud' ? 'var(--v-warn)' : 'var(--v-earth)';
      const [mx, my] = midpoint(pts, e.from + '>' + e.to), lw = Math.max(40, e.label.length * 11 + 12);
      s += `<g class="edge" data-edge="${i}" tabindex="0" role="button" aria-label="${esc(e.label)}: ${esc(e.crosses)}">
        <path d="${d}" fill="none" stroke="transparent" stroke-width="14"/>
        <path class="e" id="bvE${i}" d="${d}" fill="none" stroke="${col}" stroke-width="${e.boundary === 'local' ? 1.6 : 2.2}" ${e.boundary === 'external' ? 'stroke-dasharray="5 4"' : ''} marker-end="url(#bvArr-${e.boundary})"/>
        ${anim ? `<circle r="3.2" fill="${col}"><animateMotion dur="${(2.4 + (i % 4) * .5).toFixed(1)}s" repeatCount="indefinite"><mpath href="#bvE${i}"/></animateMotion></circle>` : ''}
        <rect x="${mx - lw / 2}" y="${my - 9}" width="${lw}" height="18" rx="9" fill="var(--v-surface)" stroke="${col}" stroke-opacity=".6"/>
        <text x="${mx}" y="${my + 4}" font-size="11" text-anchor="middle" fill="${col === 'var(--v-muted)' ? 'var(--v-ink)' : col}">${esc(e.label)}</text></g>`;
    });
    nodes.forEach(n => {
      const b = box(n.id), kc = KIND_COLOR[n.kind] || 'var(--v-muted)';
      const m = n.label.match(/^(.*?)\s*(\(.*\))$/), l1 = m ? m[1] : n.label, l2 = m ? m[2] : '';
      s += `<g class="node" data-node="${esc(n.id)}" tabindex="0" role="button" aria-label="${esc(n.label)} — ${STATUS_KO[n.status] || n.status}">
        <rect class="box" x="${b.x}" y="${b.y}" width="${CW}" height="${CH}" rx="10" fill="var(--v-surface)" stroke="${kc}" stroke-width="1.6"/>
        <rect x="${b.x}" y="${b.y}" width="6" height="${CH}" rx="3" fill="${kc}"/>
        <text x="${b.x + 16}" y="${b.y + 22}" font-size="13" font-weight="700" fill="var(--v-ink)">${esc(l1)}</text>
        <text x="${b.x + 16}" y="${b.y + 40}" font-size="11" fill="var(--v-muted)">${esc(l2 || KIND_KO[n.kind])}</text>
        <circle cx="${b.x + CW - 14}" cy="${b.y + 14}" r="5" fill="${STATUS_COLOR[n.status] || 'var(--v-muted)'}"><title>${STATUS_KO[n.status] || n.status}</title></circle>
        <text x="${b.x + CW - 12}" y="${b.y + CH - 9}" font-size="10.5" text-anchor="end" fill="${STATUS_COLOR[n.status]}">${STATUS_KO[n.status] || ''}</text></g>`;
    });
    s += '</svg>';
    const host = $('[data-map]');
    host.innerHTML = `<div style="overflow-x:auto">${s}</div>`;
    const svg = host.querySelector('svg');
    svg.style.minWidth = '760px';
    const act = (g, fn) => { g.addEventListener('click', fn); g.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); fn() } }) };
    svg.querySelectorAll('[data-node]').forEach(g => act(g, () => showNode(g.dataset.node)));
    svg.querySelectorAll('[data-edge]').forEach(g => act(g, () => showEdge(+g.dataset.edge)));
    if (sel) (sel.t === 'n' ? showNode(sel.id) : showEdge(sel.id));
  }

  function mark(attr, id){
    el.querySelectorAll('.flowsvg .sel').forEach(x => x.classList.remove('sel'));
    el.querySelector(`.flowsvg [${attr}="${id}"]`)?.classList.add('sel');
  }

  function edgeRow(e){
    const nm = id => esc(data.nodes.find(n => n.id === id)?.label || id);
    return `<tr><td>${nm(e.from)} → ${nm(e.to)}<br><span class="pill ${e.boundary}">${KIND_KO[e.boundary]}</span></td><td>${esc(e.crosses)}</td></tr>`;
  }

  function showNode(id){
    const n = data.nodes.find(x => x.id === id); if (!n) return;
    sel = {t:'n', id}; mark('data-node', id);
    const rel = data.edges.filter(e => e.from === id || e.to === id);
    const tools = n.tools ? `<h3>허용 도구 ${n.tools.length}개</h3><div class="chips">${n.tools.map(t => `<span class="pill">${esc(t)}</span>`).join('')}
      ${(n.blocked || []).map(t => `<span class="pill bad" title="보안상 차단"><s>${esc(t)}</s> 차단</span>`).join('')}</div>` : '';
    $('[data-detail]').innerHTML = `<h2>${esc(n.label)}</h2>
      <div class="row" style="margin:4px 0 8px"><span class="pill ${n.kind}">${KIND_KO[n.kind]}</span><span class="pill ${n.status}">${STATUS_KO[n.status] || n.status}</span></div>
      <p style="margin:0 0 6px">${esc(n.detail)}</p>${tools}
      ${rel.length ? `<h3>이어진 흐름</h3><table><thead><tr><th>방향</th><th>넘어가는 것</th></tr></thead><tbody>${rel.map(edgeRow).join('')}</tbody></table>` : ''}`;
  }

  function showEdge(i){
    const e = data.edges[i]; if (!e) return;
    sel = {t:'e', id:i}; mark('data-edge', i);
    $('[data-detail]').innerHTML = `<h2>${esc(e.label)}</h2>
      <div class="row" style="margin:4px 0 8px"><span class="pill ${e.boundary}">${KIND_KO[e.boundary]}</span></div>
      <table><tbody>${edgeRow(e)}</tbody></table>`;
  }

  function outList(){
    const out = data.edges.filter(e => e.boundary !== 'local');
    $('[data-out]').innerHTML = `<p class="muted" style="margin:0 0 6px">CoA 전송 규칙: <b>${data.coa_rule === 'block' ? '보내지 않기' : '식별 정보 가림'}</b></p>
      <table><tbody>${out.map(edgeRow).join('')}</tbody></table>`;
  }

  async function loadProjects(){
    try {
      const ps = await ctx.api.json('/api/projects');
      $('[data-proj]').innerHTML = '<option value="">전체</option>' + ps.map(p => `<option ${p.name === ctx.project ? 'selected' : ''}>${esc(p.name)}</option>`).join('');
    } catch { /* 단독 페이지 등 — 전체만 */ }
  }

  async function loadPipe(){
    const p = $('[data-proj]').value;
    try {
      const r = await ctx.api.json('/api/viz/pipeline' + (p ? '?project=' + encodeURIComponent(p) : ''));
      $('[data-pipe]').innerHTML = `<div class="pipe">${r.stages.map((s, i) => `${i ? '<div class="arr" aria-hidden="true">→</div>' : ''}
        <div class="pst"><div class="small muted">${esc(s.label)}</div><div class="n">${fmt(s.n, 0)}</div>
        <ul>${Object.entries(s.detail).filter(([, v]) => v).map(([k, v]) => `<li>${esc(k)} ${fmt(v, 0)}</li>`).join('')}</ul></div>`).join('')}</div>
        ${r.note ? `<p class="small muted" style="margin:6px 0 0">${esc(r.note)}</p>` : ''}`;
    } catch (e) { $('[data-pipe]').innerHTML = `<p class="err">${esc(e.message)}</p>` }
  }

  $('[data-act=refresh]').onclick = () => { load(); loadPipe() };
  $('[data-proj]').onchange = loadPipe;
  load(); loadProjects().then(loadPipe);
  return {refresh(){ load(); loadPipe() }, setProject(p){ ctx.project = p; const s = $('[data-proj]'); if ([...s.options].some(o => o.value === p || o.text === p)) { s.value = p; loadPipe() } }};
}
