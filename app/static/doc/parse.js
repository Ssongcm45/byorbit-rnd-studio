// 파서 선택 — 문서마다 파서 도구를 골라 다시 파싱하고, 결과를 나란히 비교하고, 고른 결과로 다시 청킹한다.
// 서버: /api/parse (app/routes_parse.py). 작업대(L)가 '파싱' 탭에서 지연 로드한다:
//   import {mountParse} from './parse.js'; mountParse(el, {api, docId, toast, onReparsed})
// 클라우드 도구(Upstage)만 문서 파일을 밖으로 보낸다 — '기밀' 문서는 서버가 막고(403), 화면도 버튼을 잠근다.
import {esc, fmt, h, makeApi} from '../viz/common.js';

const BASE = '/api/parse';
const POLL_MS = 800;
const EXT_LABEL = {'.pdf': 'PDF', '.hwpx': 'HWPX', '.hwp': 'HWP(구 형식)', '.xlsx': '엑셀', '.xlsm': '엑셀(매크로)',
  '.txt': '텍스트', '.md': '마크다운', '.csv': 'CSV', '.png': 'PNG', '.jpg': 'JPG', '.jpeg': 'JPEG', '.tif': 'TIF', '.tiff': 'TIFF'};
const CF_PILL = {'기밀': 'bad', '내부': 'warn', '일반': 'ok'};
let uid = 0;

function ensureCss(href) {
  const abs = new URL(href, import.meta.url).href;
  if ([...document.querySelectorAll('link[rel=stylesheet]')].some(l => l.href === abs)) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet'; l.href = abs;
  document.head.appendChild(l);
}

const STYLE = `
.pz .pz-notice{font-size:12.5px;color:var(--v-muted);border-left:3px solid var(--v-accent);padding:6px 10px;background:var(--v-accent-soft);border-radius:0 8px 8px 0}
.pz .pz-head{display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap}
.pz .pz-head h2{margin:0}
.pz .pz-tools{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}
.pz .pz-tool{border:1px solid var(--v-line);border-radius:10px;padding:10px 12px;background:var(--v-surface);display:flex;flex-direction:column;gap:6px;min-width:0}
.pz .pz-tool.cloud{border-color:var(--v-warn);background:linear-gradient(0deg,var(--v-warn-soft),var(--v-surface) 60%)}
.pz .pz-tool.off{opacity:.92}
.pz .pz-tool .t{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.pz .pz-tool .t b{font-size:13.5px}
.pz .pz-tool p{margin:0;font-size:12px;color:var(--v-muted)}
.pz .pz-tool .str{font-size:11.5px;color:var(--v-ink)}
.pz .pz-tool .hint{font-size:11.5px;color:var(--v-warn);overflow-wrap:anywhere}
.pz .pz-tool .warn{font-size:11.5px;color:var(--v-bad);font-weight:600}
.pz .pz-tool .opts{display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:12px}
.pz .pz-tool .opts select{height:26px;font-size:12px}
.pz .pz-tool .go{margin-top:auto;display:flex;gap:6px;align-items:center}
.pz .pill.ok{background:var(--v-ok-soft);color:var(--v-ok)} .pz .pill.warn{background:var(--v-warn-soft);color:var(--v-warn)}
.pz .pill.bad{background:var(--v-bad-soft);color:var(--v-bad)} .pz .pill.acc{background:var(--v-accent-soft);color:var(--v-accent)}
.pz table.pz-res{width:100%;border-collapse:collapse;font-size:12.5px}
.pz table.pz-res th{font-size:11px;color:var(--v-muted);text-align:left;font-weight:600;padding:6px;border-bottom:1px solid var(--v-line);white-space:nowrap}
.pz table.pz-res td{padding:7px 6px;border-bottom:1px solid var(--v-line);vertical-align:top}
.pz table.pz-res td.n{text-align:right;font-family:var(--v-mono);white-space:nowrap}
.pz table.pz-res tr.chosen td{background:var(--v-ok-soft)}
.pz .pz-wl{font-size:11px;color:var(--v-warn);max-width:280px}
.pz .pz-err{font-size:11.5px;color:var(--v-bad);max-width:320px;overflow-wrap:anywhere}
.pz .pz-cmpbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.pz .pz-cmpbar label{font-size:12px;color:var(--v-muted);display:flex;gap:4px;align-items:center}
.pz .pz-pages{display:flex;gap:2px;align-items:flex-end;height:34px;overflow-x:auto;padding:2px 0}
.pz .pz-pages button{border:0;background:none;padding:0 1px;cursor:pointer;display:flex;gap:1px;align-items:flex-end;height:100%}
.pz .pz-pages button i{display:block;width:5px;border-radius:2px 2px 0 0;min-height:2px}
.pz .pz-pages button i.a{background:var(--v-accent)} .pz .pz-pages button i.b{background:var(--v-earth)}
.pz .pz-pages button[aria-current=true]{outline:2px solid var(--v-ink);outline-offset:1px;border-radius:3px}
.pz .pz-cols{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}
@media (max-width:860px){.pz .pz-cols{grid-template-columns:minmax(0,1fr)}}
.pz .pz-col{border:1px solid var(--v-line);border-radius:10px;min-width:0;background:var(--v-surface)}
.pz .pz-col>header{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:8px 10px;border-bottom:1px solid var(--v-line);background:var(--v-surface-2);border-radius:10px 10px 0 0;font-size:12.5px}
.pz .pz-col>header .sw{width:10px;height:10px;border-radius:3px;display:inline-block}
.pz .pz-col .body{padding:10px 12px;max-height:640px;overflow:auto;font-size:13px;line-height:1.6}
.pz .pz-col .body .blk{margin:0 0 8px;position:relative;padding-left:34px}
.pz .pz-col .body .blk>.k{position:absolute;left:0;top:3px;font-size:10px;font-weight:600;font-family:var(--v-font);color:var(--v-muted);background:var(--v-surface-2);border-radius:4px;padding:0 4px}
.pz .pz-col .body .blk.heading{font-weight:700}
.pz .pz-col .body .blk.heading.l1{font-size:14.5px}.pz .pz-col .body .blk.heading.l2{font-size:13.5px}
.pz .pz-col .body .blk.table>.k{background:var(--v-accent-soft);color:var(--v-accent)}
.pz .pz-col .body table{border-collapse:collapse;font-size:12px;margin:2px 0;max-width:100%}
.pz .pz-col .body .tw{overflow-x:auto}
.pz .pz-col .body td,.pz .pz-col .body th{border:1px solid var(--v-line);padding:3px 6px;vertical-align:top;text-align:left}
.pz .pz-col .body th{background:var(--v-surface-2);font-weight:600}
.pz .pz-col .body .more{font-size:11.5px;color:var(--v-muted)}
.pz .pz-col .empty{padding:24px 12px;color:var(--v-muted);font-size:12.5px;text-align:center}
.pz .pz-defs{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px}
.pz .pz-defs label{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--v-muted)}
.pz dialog.pz-dlg{border:1px solid var(--v-line);border-radius:12px;background:var(--v-surface);color:var(--v-ink);max-width:min(560px,calc(100vw - 32px));padding:18px 20px;box-shadow:0 10px 40px rgba(0,0,0,.25)}
.pz dialog.pz-dlg::backdrop{background:rgba(10,15,25,.45)}
.pz dialog.pz-dlg h3{margin:0 0 8px;font-size:15px}
.pz dialog.pz-dlg ul{margin:6px 0;padding-left:18px;font-size:12.5px}
.pz dialog.pz-dlg .acts{display:flex;gap:8px;justify-content:flex-end;margin-top:14px;flex-wrap:wrap}
.pz .pz-run{font-size:11.5px;color:var(--v-muted)}
.pz .spin{display:inline-block;width:11px;height:11px;border:2px solid var(--v-line);border-top-color:var(--v-accent);border-radius:50%;animation:bvspin 1s linear infinite}
`;

function injectCss() {
  if (document.getElementById('pz-style')) return;
  const s = document.createElement('style');
  s.id = 'pz-style'; s.textContent = STYLE;
  document.head.appendChild(s);
}

const ms = v => v == null ? '-' : v < 1000 ? `${fmt(v, 0)}ms` : `${fmt(v / 1000, 1)}초`;
const localTime = s => {
  if (!s) return '-';
  const d = new Date(s.replace(' ', 'T') + (/[zZ+]/.test(s.slice(10)) ? '' : 'Z'));
  return isNaN(d) ? s : d.toLocaleString('ko-KR', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'});
};

function tableHtml(rows, more) {
  if (!rows || !rows.length) return '';
  const [head, ...body] = rows;
  return `<div class="tw"><table><thead><tr>${head.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${
    body.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${
    more ? `<div class="more">… ${fmt(more, 0)}행 더</div>` : ''}`;
}

function blockHtml(b) {
  if (b.type === 'table') {
    return `<div class="blk table"><span class="k">표</span>${b.caption ? `<div class="more">${esc(b.caption)}</div>` : ''}${tableHtml(b.rows, b.more_rows)}</div>`;
  }
  if (b.type === 'heading') return `<div class="blk heading l${Math.min(3, b.level || 1)}"><span class="k">H${b.level || 1}</span>${esc(b.text)}</div>`;
  return `<p class="blk"><span class="k">본문</span>${esc(b.text)}${b.more_chars ? `<span class="more"> … ${fmt(b.more_chars, 0)}자 더</span>` : ''}</p>`;
}

/** mountParse(el, {api, docId, toast, onReparsed}) → {refresh(), setDoc(id), dispose()} */
export function mountParse(el, opts = {}) {
  ensureCss('../viz/viz.css');
  injectCss();
  const {json} = makeApi(opts.api);
  const toast = opts.toast || (m => console.log(m));
  const id = 'pz' + (++uid);
  const st = {docId: opts.docId || '', doc: null, tools: [], results: [], cmp: null, a: '', b: '', page: null,
    running: {}, timers: new Set(), disposed: false, defaults: null, toolOpts: {}};

  const root = h(`<section class="bv pz" aria-labelledby="${id}-t">
    <div class="wrap" style="padding-top:0">
      <div class="card"><div class="pz-head"><div class="grow"><h2 id="${id}-t">파서 선택</h2><div class="pz-docline small muted"></div></div>
        <button class="btn sm pz-reload" type="button">새로 고침</button></div>
        <p class="pz-notice" style="margin:10px 0 0">로컬 도구는 문서를 이 PC 안에서만 읽습니다. <b>클라우드 도구(Upstage)만 문서 파일을 밖으로 보냅니다</b> — '기밀' 문서는 보낼 수 없습니다.</p></div>
      <div class="card"><h2 data-help="wb.tools">도구</h2><p class="sub">도구를 골라 실행하면 결과가 아래 표에 쌓입니다. 실행만으로는 청크·라벨이 바뀌지 않습니다 — 결과를 비교한 뒤 '이 결과로 다시 청킹'을 누를 때만 바뀝니다.</p>
        <div class="pz-tools" aria-live="polite"></div><details class="pz-other" hidden><summary class="small muted"></summary><div class="pz-tools pz-tools-other" style="margin-top:8px"></div></details></div>
      <div class="card"><div class="row"><h2 class="grow" data-help="wb.rechunk">결과</h2></div>
        <p class="sub">같은 도구를 다시 실행하면 이전 결과(선택 안 된 것)를 바꿉니다. 초록색 줄이 지금 청크를 만든 결과입니다.</p>
        <div class="pz-results" style="overflow-x:auto"></div></div>
      <div class="card"><h2 data-help="wb.compare">나란히 비교</h2><p class="sub">두 결과를 같은 쪽끼리 맞춰 봅니다. 막대는 쪽별 글자 수(파랑 A · 갈색 B)입니다. 표는 표로 그립니다.</p>
        <div class="pz-cmpbar">
          <label>A <select class="inp pz-a" aria-label="비교 A"></select></label>
          <label>B <select class="inp pz-b" aria-label="비교 B"></select></label>
          <span class="grow"></span>
          <button class="btn sm pz-prev" type="button" aria-label="앞 쪽">‹</button>
          <label>쪽 <select class="inp pz-page" aria-label="쪽"></select></label>
          <button class="btn sm pz-next" type="button" aria-label="다음 쪽">›</button>
        </div>
        <div class="pz-pages" role="group" aria-label="쪽별 글자 수"></div>
        <div class="pz-cols"></div></div>
      <div class="card"><details class="pz-defbox"><summary><b>형식별 기본 도구</b> <span class="small muted">— 새로 넣는 파일에 쓸 도구(클라우드 도구는 기본으로 둘 수 없음)</span></summary>
        <div class="pz-defs" style="margin-top:10px"></div>
        <div class="row" style="margin-top:10px"><button class="btn sm primary pz-defsave" type="button">기본 도구 저장</button><span class="small muted pz-defmsg"></span></div></details></div>
    </div>
    <dialog class="pz-dlg"><form method="dialog"><div class="pz-dlg-b"></div><div class="acts"></div></form></dialog>
  </section>`);
  el.innerHTML = '';
  el.appendChild(root);
  const $ = s => root.querySelector(s);
  const dlg = $('dialog');

  function ask(title, html, buttons) {
    return new Promise(res => {
      $('.pz-dlg-b').innerHTML = `<h3>${esc(title)}</h3>${html}`;
      $('.acts').innerHTML = buttons.map((b, i) => `<button class="btn ${b.primary ? 'primary' : ''}" value="${i}" ${b.disabled ? 'disabled' : ''}>${esc(b.label)}</button>`).join('');
      dlg.onclose = () => res(buttons[Number(dlg.returnValue)]?.value ?? null);
      dlg.returnValue = '';
      if (dlg.showModal) dlg.showModal(); else dlg.setAttribute('open', '');
    });
  }

  // ------------------------------------------------------------ 불러오기
  async function load() {
    if (!st.docId) { $('.pz-docline').textContent = '자료를 고르세요.'; return; }
    try {
      const [doc, tools, res] = await Promise.all([
        json(`${BASE}/docs/${st.docId}`), json(`${BASE}/tools?doc_id=${st.docId}`), json(`${BASE}/docs/${st.docId}/results`)]);
      if (st.disposed) return;
      st.doc = doc; st.tools = tools.tools; st.results = res.results;
      drawDoc(); drawTools(); drawResults();
      await loadCompare();
      loadDefaults();
    } catch (e) {
      $('.pz-docline').innerHTML = `<span class="pz-err">${esc(e.message)}</span>`;
    }
  }

  async function loadCompare() {
    const q = new URLSearchParams();
    if (st.a) q.set('a', st.a);
    if (st.b) q.set('b', st.b);
    if (st.page != null) q.set('page', st.page);
    try {
      st.cmp = await json(`${BASE}/docs/${st.docId}/compare?${q}`);
    } catch (e) { toast('비교를 불러오지 못했습니다: ' + e.message); return; }
    st.a = st.cmp.a?.result_id || st.a; st.b = st.cmp.b?.result_id || st.b; st.page = st.cmp.page;
    st.results = st.cmp.results;
    drawResults(); drawCompare();
  }

  // ------------------------------------------------------------ 그리기
  function drawDoc() {
    const d = st.doc;
    const c = d.counts || {};
    $('.pz-docline').innerHTML = `<b style="color:var(--v-ink)">${esc(d.file_name)}</b> · ${esc(EXT_LABEL[d.ext] || d.ext)}
      · <span class="pill ${CF_PILL[d.confidentiality] || ''}">${esc(d.confidentiality)}</span>
      · 지금 청크: <span class="pill acc">${esc(d.tool || '기존 파서')}</span> ${fmt(c.chunks, 0)}개
      · 라벨 ${fmt(c.annotations, 0)}개(사용자 ${fmt(c.manual, 0)} · 승인 ${fmt(c.reviewed, 0)}) · 라벨에 연결된 측정값 ${fmt(c.linked_measurements, 0)}개
      ${d.file_exists ? '' : ' · <span class="pz-err">원본 파일 없음</span>'}`;
  }

  function optsHtml(t) {
    const cur = st.toolOpts[t.key] || {};
    return (t.options || []).map(o => {
      if (o.type === 'bool') return `<label><input type="checkbox" data-opt="${esc(o.key)}" ${(cur[o.key] ?? o.default) ? 'checked' : ''}> ${esc(o.label)}</label>`;
      const ch = (o.choices || []).map(c => Array.isArray(c) ? c : [c, c]);
      return `<label>${esc(o.label)} <select class="inp" data-opt="${esc(o.key)}">${ch.map(([v, l]) => `<option value="${esc(v)}" ${String(cur[o.key] ?? o.default) === String(v) ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></label>`;
    }).join('');
  }

  function toolCard(t) {
    const conf = st.doc?.confidentiality;
    const cloudBlocked = t.kind === 'cloud' && conf === '기밀';
    const running = st.running[t.key];
    const badge = !t.ready ? '<span class="pill warn">미설치</span>' : '<span class="pill ok">준비됨</span>';
    const kind = t.kind === 'cloud' ? '<span class="pill bad">클라우드</span>' : '<span class="pill">로컬</span>';
    const isDef = (t.default_for || []).includes(st.doc?.ext) ? '<span class="pill acc">기본</span>' : '';
    const ver = t.version ? `<span class="small muted mono">${esc(t.version)}</span>` : '';
    return `<div class="pz-tool ${t.kind === 'cloud' ? 'cloud' : ''} ${t.ready ? '' : 'off'}" data-tool="${esc(t.key)}">
      <div class="t"><b>${esc(t.name)}</b>${badge}${kind}${isDef}${ver}</div>
      <p>${esc(t.description)}</p><div class="str">강점: ${esc(t.strengths)}</div>
      ${t.kind === 'cloud' ? `<div class="warn">문서 파일이 Upstage 서버로 전송됩니다. '기밀' 문서는 불가${cloudBlocked ? ' — 이 문서는 기밀이라 실행할 수 없습니다.' : '.'}</div>` : ''}
      ${!t.ready ? `<div class="hint">${esc(t.hint || t.message || t.install_hint)}</div>` : t.detail ? `<p>${esc(t.detail)}</p>` : ''}
      ${t.ready && t.options?.length ? `<div class="opts">${optsHtml(t)}</div>` : ''}
      <div class="go"><button class="btn sm ${t.kind === 'cloud' ? '' : 'primary'}" type="button" data-run="${esc(t.key)}"
        ${!t.ready || cloudBlocked || running || t.supports_doc === false ? 'disabled' : ''}>${running ? '<span class="spin"></span> 실행 중' : '실행'}</button>
        ${running ? `<span class="pz-run">${esc(running)}</span>` : t.slow ? '<span class="pz-run">시간이 걸릴 수 있습니다</span>' : ''}</div></div>`;
  }

  function drawTools() {
    const mine = st.tools.filter(t => t.supports_doc !== false);
    const other = st.tools.filter(t => t.supports_doc === false);
    $('.pz-tools').innerHTML = mine.length ? mine.map(toolCard).join('') : '<p class="muted small">이 형식을 읽는 도구가 없습니다.</p>';
    const od = $('.pz-other');
    od.hidden = !other.length;
    od.querySelector('summary').textContent = `이 형식(${EXT_LABEL[st.doc?.ext] || st.doc?.ext || ''})을 읽지 못하는 도구 ${other.length}개`;
    $('.pz-tools-other').innerHTML = other.map(t => `<div class="pz-tool off"><div class="t"><b>${esc(t.name)}</b><span class="pill">${esc(t.formats.join(' '))}</span></div><p>${esc(t.description)}</p></div>`).join('');
  }

  function warnList(w) {
    if (!w || !w.length) return '<span class="muted">-</span>';
    return `<div class="pz-wl" title="${esc(w.join('\n'))}">${esc(w[0])}${w.length > 1 ? ` 외 ${w.length - 1}건` : ''}</div>`;
  }

  function drawResults() {
    const rs = st.results || [];
    if (!rs.length) { $('.pz-results').innerHTML = '<p class="muted small">아직 결과가 없습니다. 위에서 도구를 실행하세요.</p>'; return; }
    $('.pz-results').innerHTML = `<table class="pz-res"><thead><tr><th>도구</th><th>시각</th><th style="text-align:right">시간</th><th style="text-align:right">쪽</th>
      <th style="text-align:right">블록(제목·본문·표)</th><th style="text-align:right">표 셀</th><th style="text-align:right">글자</th><th style="text-align:right">OCR 쪽</th><th>경고</th><th>상태</th><th></th></tr></thead><tbody>${
      rs.map(r => {
        const s = r.stats || {};
        const ok = r.status === 'ok';
        return `<tr class="${r.chosen ? 'chosen' : ''}"><td><b>${esc(r.name)}</b>${r.kind === 'cloud' ? ' <span class="pill bad">클라우드</span>' : ''}<div class="small muted mono">${esc(r.tool_ver || '')}</div></td>
          <td class="small" style="white-space:nowrap">${esc(localTime(r.created_at))}</td><td class="n">${ms(s.duration_ms)}</td>
          <td class="n">${ok ? fmt(s.pages, 0) : '-'}</td>
          <td class="n">${ok ? `${fmt(s.blocks, 0)} <span class="muted">(${fmt(s.headings, 0)}·${fmt(s.texts, 0)}·${fmt(s.tables, 0)})</span>` : '-'}</td>
          <td class="n">${ok ? fmt(s.table_cells, 0) : '-'}</td><td class="n">${ok ? fmt(s.chars, 0) : '-'}</td><td class="n">${ok ? fmt(s.ocr_pages, 0) : '-'}</td>
          <td>${ok ? warnList(s.warnings) : `<div class="pz-err">${esc(r.error || '실패')}</div>`}</td>
          <td>${r.chosen ? '<span class="pill ok">지금 청크</span>' : ok ? '<span class="pill">대기</span>' : '<span class="pill bad">실패</span>'}</td>
          <td style="white-space:nowrap">${ok ? `<button class="btn sm" type="button" data-cmp="${r.result_id}">비교</button>
            <button class="btn sm ${r.chosen ? '' : 'primary'}" type="button" data-choose="${r.result_id}" ${r.chosen ? 'title="이미 이 결과로 청킹되어 있습니다. 다시 누르면 같은 결과로 다시 나눕니다."' : ''}>이 결과로 다시 청킹</button>` : ''}</td></tr>`;
      }).join('')}</tbody></table>`;
  }

  function resultName(rid) {
    const r = (st.results || []).find(x => x.result_id === rid);
    return r ? r.name : '-';
  }

  function drawCompare() {
    const c = st.cmp;
    const ok = (c?.results || []).filter(r => r.status === 'ok');
    const opt = sel => ['<option value="">(없음)</option>', ...ok.map(r => `<option value="${r.result_id}" ${r.result_id === sel ? 'selected' : ''}>${esc(r.name)}${r.chosen ? ' · 지금 청크' : ''}</option>`)].join('');
    $('.pz-a').innerHTML = opt(st.a); $('.pz-b').innerHTML = opt(st.b);
    const pages = c?.pages || [];
    $('.pz-page').innerHTML = pages.map(p => `<option value="${p}" ${p === c.page ? 'selected' : ''}>${p === 0 ? '쪽 정보 없음' : p}</option>`).join('') || '<option>-</option>';
    $('.pz-prev').disabled = !pages.length || pages.indexOf(c.page) <= 0;
    $('.pz-next').disabled = !pages.length || pages.indexOf(c.page) >= pages.length - 1;
    const pc = c?.page_chars || [];
    const max = Math.max(1, ...pc.flatMap(r => [r[st.a] || 0, r[st.b] || 0]));
    $('.pz-pages').innerHTML = pc.length > 1 ? pc.map(r => `<button type="button" data-page="${r.page}" aria-current="${r.page === c.page}" title="${r.page || '쪽 정보 없음'}쪽 — A ${fmt(r[st.a] || 0, 0)}자 · B ${fmt(r[st.b] || 0, 0)}자">
      <i class="a" style="height:${Math.round(30 * (r[st.a] || 0) / max)}px"></i><i class="b" style="height:${Math.round(30 * (r[st.b] || 0) / max)}px"></i></button>`).join('') : '';
    const col = (side, color, label) => {
      const s = c?.[side];
      if (!s) return `<div class="pz-col"><header><span class="sw" style="background:${color}"></span><b>${label}</b></header><div class="empty">${ok.length < 2 && side === 'b' ? '비교하려면 다른 도구를 하나 더 실행하세요.' : '결과를 고르세요.'}</div></div>`;
      const tables = s.blocks.filter(b => b.type === 'table').length;
      const chars = s.blocks.reduce((n, b) => n + (b.text || '').length + (b.more_chars || 0), 0);
      return `<div class="pz-col"><header><span class="sw" style="background:${color}"></span><b>${label} · ${esc(resultName(s.result_id))}</b>
        <span class="muted">블록 ${fmt(s.total, 0)} · 표 ${fmt(tables, 0)} · 글자 ${fmt(chars, 0)}</span></header>
        <div class="body">${s.blocks.length ? s.blocks.map(blockHtml).join('') : '<div class="empty">이 쪽에서 읽은 내용이 없습니다.</div>'}
        ${s.more_blocks ? `<div class="more">… 블록 ${fmt(s.more_blocks, 0)}개 더</div>` : ''}</div></div>`;
    };
    $('.pz-cols').innerHTML = col('a', 'var(--v-accent)', 'A') + col('b', 'var(--v-earth)', 'B');
  }

  // ------------------------------------------------------------ 기본 도구
  async function loadDefaults() {
    try { st.defaults = await json(`${BASE}/defaults`); } catch { return; }
    const names = Object.fromEntries(st.tools.map(t => [t.key, t]));
    $('.pz-defs').innerHTML = Object.entries(st.defaults.choices).map(([ext, keys]) => `<label>${esc(EXT_LABEL[ext] || ext)} <span class="mono">${esc(ext)}</span>
      <select class="inp" data-ext="${esc(ext)}">${keys.map(k => `<option value="${k}" ${st.defaults.defaults[ext] === k ? 'selected' : ''}>${esc(names[k]?.name || k)}${names[k] && !names[k].ready ? ' (미설치)' : ''}${st.defaults.builtin[ext] === k ? ' · 원래 기본' : ''}</option>`).join('')}</select></label>`).join('');
  }

  async function saveDefaults() {
    const body = {defaults: Object.fromEntries([...root.querySelectorAll('.pz-defs select')].map(s => [s.dataset.ext, s.value]))};
    try {
      st.defaults = await json(`${BASE}/defaults`, {method: 'POST', body});
      $('.pz-defmsg').textContent = '저장했습니다. 앞으로 넣는 파일부터 적용됩니다(미설치 도구는 기존 파서로 대신 읽습니다).';
      toast('기본 도구를 저장했습니다');
      const tools = await json(`${BASE}/tools?doc_id=${st.docId}`); st.tools = tools.tools; drawTools();
    } catch (e) { $('.pz-defmsg').textContent = e.message; }
  }

  // ------------------------------------------------------------ 실행·선택
  function readOpts(key) {
    const card = root.querySelector(`.pz-tool[data-tool="${CSS.escape(key)}"]`);
    const o = {};
    card?.querySelectorAll('[data-opt]').forEach(i => { o[i.dataset.opt] = i.type === 'checkbox' ? i.checked : i.value; });
    st.toolOpts[key] = o;
    return o;
  }

  async function run(key) {
    const t = st.tools.find(x => x.key === key);
    if (!t) return;
    const options = readOpts(key);
    let confirm_cloud = false;
    if (t.kind === 'cloud') {
      let est = {};
      try { est = await json(`${BASE}/docs/${st.docId}/estimate?tool=${key}&mode=${encodeURIComponent(options.mode || 'standard')}`); }
      catch (e) { toast(e.message); return; }
      if (est.blocked) { await ask('보낼 수 없습니다', `<p>${esc(est.message)}</p>`, [{label: '닫기', value: null}]); return; }
      const go = await ask('문서 파일을 Upstage로 보냅니다', `<p><b>${esc(st.doc.file_name)}</b>(보안 등급 <b>${esc(st.doc.confidentiality)}</b>) 파일 전체가 Upstage 서버로 전송됩니다.</p>
        <ul><li>예상 비용: ${esc(est.message || '-')}</li><li>파일 이름은 보내지 않습니다('document${esc(st.doc.ext)}'로 바꿔 보냄).</li>
        <li>결과는 이 PC에만 저장됩니다. 요금표: <a href="${esc(est.pricing_url || '#')}" target="_blank" rel="noopener">Upstage 요금</a> (${esc(est.checked || '')} 확인)</li></ul>`,
        [{label: '취소', value: false}, {label: '보내고 실행', value: true, primary: true}]);
      if (!go) return;
      confirm_cloud = true;
    }
    st.running[key] = '시작하는 중…'; drawTools();
    let job;
    try {
      job = await json(`${BASE}/docs/${st.docId}/run`, {method: 'POST', body: {tool: key, options, confirm_cloud}});
    } catch (e) { delete st.running[key]; drawTools(); toast('실행하지 못했습니다: ' + e.message); return; }
    const t0 = Date.now();
    const tick = async () => {
      if (st.disposed) return;
      try { job = await json(`${BASE}/jobs/${job.job_id}`); } catch (e) { job = {status: 'error', error: e.message}; }
      if (job.status === 'running') {
        st.running[key] = `${Math.round((Date.now() - t0) / 1000)}초 경과`; drawTools();
        const tm = setTimeout(() => { st.timers.delete(tm); tick(); }, POLL_MS); st.timers.add(tm);
        return;
      }
      delete st.running[key];
      if (job.status === 'done') { toast(`${t.name}: 블록 ${fmt(job.result?.stats?.blocks, 0)}개 (${ms(job.result?.stats?.duration_ms)})`); if (job.result?.result_id) st.b = job.result.result_id; }
      else toast(`${t.name} 실패: ${job.error || job.result?.error || ''}`);
      const res = await json(`${BASE}/docs/${st.docId}/results`).catch(() => null);
      if (res) st.results = res.results;
      drawTools(); drawResults(); loadCompare();
    };
    tick();
  }

  async function choose(rid) {
    const r = st.results.find(x => x.result_id === rid);
    const c = st.doc.counts || {};
    const go = await ask('이 결과로 다시 청킹할까요?', `<p><b>${esc(r?.name)}</b> 결과로 이 문서의 섹션·표·청크를 새로 만듭니다. 원본 파일과 자료 정보는 그대로입니다.</p>
      <ul><li>사전·AI 라벨 ${fmt((c.annotations || 0) - (c.manual || 0) - (c.reviewed || 0), 0)}개는 지우고 사전 라벨은 다시 만듭니다. AI 라벨은 'AI 라벨'을 다시 실행해야 합니다.</li>
      <li>사용자 라벨 ${fmt(c.manual, 0)}개와 승인한 라벨 ${fmt(c.reviewed, 0)}개는 같은 표기를 찾아 새 청크로 옮깁니다. 못 찾은 것은 끝나고 목록으로 알려 드립니다.</li>
      <li>라벨에 연결된 측정값 ${fmt(c.linked_measurements, 0)}개는 지우지 않습니다. 옮기지 못한 라벨의 측정값은 연결만 끊깁니다.</li>
      <li>CoA 측정값은 파서와 무관해 그대로 둡니다. 작업대 규칙이 있으면 새 청크에 다시 적용합니다.</li></ul>`,
      [{label: '취소', value: false}, {label: '다시 청킹', value: true, primary: true}]);
    if (!go) return;
    let rep;
    try { rep = await json(`${BASE}/docs/${st.docId}/choose`, {method: 'POST', body: {result_id: rid}}); }
    catch (e) { toast('다시 청킹하지 못했습니다: ' + e.message); return; }
    const lost = rep.manual_lost || [];
    await ask('다시 청킹했습니다', `<p>${esc(rep.message)}</p>
      <ul><li>청크 ${fmt(rep.chunks, 0)}개 · 섹션 ${fmt(rep.sections, 0)}개 · 표 ${fmt(rep.tables, 0)}개 · 새 사전 라벨 ${fmt(rep.annotations_dict, 0)}개</li>
      <li>옮긴 라벨 ${fmt(rep.manual_moved, 0)}개 · 못 옮긴 라벨 <b>${fmt(lost.length, 0)}</b>개 · 연결이 끊긴 측정값 <b>${fmt(rep.measurements_unlinked, 0)}</b>개</li></ul>
      ${lost.length ? `<p class="small"><b>못 옮긴 라벨</b> — 작업대 라벨 화면에서 다시 다세요:</p><ul>${lost.slice(0, 30).map(x => `<li><span class="mono">${esc(x.label_type)}</span> “${esc(x.surface)}”${x.measurements ? ` · 측정값 ${x.measurements}개 연결 끊김` : ''}</li>`).join('')}</ul>` : ''}`,
      [{label: '확인', value: true, primary: true}]);
    st.a = rid; st.b = '';
    await load();
    if (opts.onReparsed) opts.onReparsed(rep);
  }

  // ------------------------------------------------------------ 이벤트
  root.addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b || b.closest('dialog')) return;
    if (b.dataset.run) run(b.dataset.run);
    else if (b.dataset.choose) choose(b.dataset.choose);
    else if (b.dataset.cmp) {
      if (b.dataset.cmp !== st.a) { st.b = st.a; st.a = b.dataset.cmp; }
      loadCompare(); root.querySelector('.pz-cols').scrollIntoView({behavior: 'smooth', block: 'nearest'});
    } else if (b.dataset.page != null) { st.page = Number(b.dataset.page); loadCompare(); }
    else if (b.classList.contains('pz-reload')) load();
    else if (b.classList.contains('pz-defsave')) saveDefaults();
    else if (b.classList.contains('pz-prev') || b.classList.contains('pz-next')) {
      const ps = st.cmp?.pages || []; const i = ps.indexOf(st.page) + (b.classList.contains('pz-next') ? 1 : -1);
      if (ps[i] != null) { st.page = ps[i]; loadCompare(); }
    }
  });
  root.addEventListener('change', e => {
    const s = e.target;
    if (s.classList.contains('pz-a')) { st.a = s.value; loadCompare(); }
    else if (s.classList.contains('pz-b')) { st.b = s.value; loadCompare(); }
    else if (s.classList.contains('pz-page')) { st.page = Number(s.value); loadCompare(); }
    else if (s.dataset.opt) { const card = s.closest('.pz-tool'); if (card) readOpts(card.dataset.tool); }
  });

  load();
  return {
    refresh: load,
    setDoc(docId) { st.docId = docId; st.a = st.b = ''; st.page = null; st.results = []; load(); },
    dispose() { st.disposed = true; st.timers.forEach(clearTimeout); st.timers.clear(); el.innerHTML = ''; },
  };
}
