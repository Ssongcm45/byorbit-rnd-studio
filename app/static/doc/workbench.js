// 문서 작업대 — 파싱 | 청크 | 라벨 | 배운 것
// export function mountWorkbench(el, {api, toast, docId, chunkId, tab, onClose}) → {open(docId, {chunkId, tab}), close(), destroy()}
// api(path, {method, body})는 index.html과 같은 꼴(JSON 본문, 실패하면 detail을 담은 Error).

const LT_KO = {BYPRODUCT:'부산물', COMMODITY:'원물', PROCESS:'공정', CONSTITUENT:'성분', PROPERTY:'물성', UNIT:'단위',
  METHOD:'시험법', APPLICATION:'용도', VALUE:'수치', CONDITION:'조건', OTHER:'기타'};
const LT_ORDER = Object.keys(LT_KO);
const METHOD_KO = {human:'사람', dict:'사전', llm:'AI', regex:'규칙'};
const STATUS_KO = {accepted:'승인', rejected:'거절', pending:'검토 대기', auto:'자동'};
const FLAG_KO = {short:'짧음', long:'김', broken:'끊김', table_split:'표 나뉨', noise:'잡음', dup:'중복', ocr_low:'OCR 낮음', attention:'라벨 확인'};
const TAB_KO = [['parse','파싱'],['chunks','청크'],['labels','라벨'],['learned','배운 것']];
const SCHEMES = ['부산물','원물','공정','성분','물성','단위','시험법','용도'];

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const lineAt = (text, pos) => { const a = text.lastIndexOf('\n', pos - 1) + 1; let b = text.indexOf('\n', pos); if (b < 0) b = text.length; return text.slice(a, b) };

function ensureCss(){
  if (document.querySelector('link[data-wb-css]')) return;
  const l = document.createElement('link'); l.rel = 'stylesheet'; l.dataset.wbCss = '1';
  l.href = new URL('./workbench.css', import.meta.url).href; document.head.appendChild(l);
}

export function mountWorkbench(el, opts = {}){
  ensureCss();
  const api = opts.api, toast = opts.toast || (m => console.log(m));
  const S = {docId: null, doc: null, tab: opts.tab || 'chunks', chunks: [], sel: null, filter: false,
    lab: {chunk: null, idx: -1, sel: null, edit: null, concept: null}, run: null, runTimer: null, parse: null, report: null};
  el.innerHTML = `<div class="wb" id="wbRoot"></div>`;
  const root = el.querySelector('.wb');
  const $ = s => root.querySelector(s), $$ = s => [...root.querySelectorAll(s)];
  const visible = () => root.offsetParent !== null;
  const fail = e => toast(e.message || String(e));

  // ------------------------------------------------------------ 뼈대
  function frame(){
    root.innerHTML = `
      <div class="whead">
        <h1 id="wbTitle">문서 작업대</h1><span id="wbConf"></span><span class="grow"></span>
        <button class="btn sm" id="wbUndo" title="이 자료의 마지막 청크 작업을 되돌립니다">↶ 되돌리기</button>
        <button class="btn sm" id="wbClose">닫기</button>
      </div>
      <div class="tabs" role="tablist">${TAB_KO.map(([k,n]) => `<button role="tab" id="wbt-${k}" aria-controls="wbp-${k}" data-tab="${k}">${n}</button>`).join('')}</div>
      ${TAB_KO.map(([k]) => `<section role="tabpanel" id="wbp-${k}" aria-labelledby="wbt-${k}" hidden></section>`).join('')}
      <div class="pop" id="wbPop" hidden role="dialog" aria-label="라벨 붙이기"></div>`;
    $$('.tabs button').forEach(b => b.onclick = () => setTab(b.dataset.tab));
    $('#wbClose').onclick = () => opts.onClose ? opts.onClose() : null;
    $('#wbUndo').onclick = undo;
  }

  function setTab(t){
    S.tab = t;
    $$('.tabs button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === t)));
    $$('[role=tabpanel]').forEach(p => p.hidden = p.id !== 'wbp-' + t);
    hidePop();
    ({parse: renderParse, chunks: renderChunks, labels: renderLabels, learned: renderLearned})[t]?.();
  }

  async function open(docId, o = {}){
    if (!docId){ frame(); $('#wbTitle').textContent = '문서 작업대';
      $$('[role=tabpanel]').forEach(p => p.hidden = true);
      $('#wbp-chunks').hidden = false; $('#wbp-chunks').innerHTML = `<div class="card empty">자료함에서 자료의 “작업대” 버튼을 누르면 여기서 청크와 라벨을 고칠 수 있습니다.</div>`;
      return }
    if (S.docId !== docId){ S.docId = docId; S.sel = null; S.lab.chunk = null; S.parse = null; S.report = null; frame() }
    if (o.chunkId){ S.sel = o.chunkId; S.lab.chunk = o.chunkId }
    try { await loadDoc() } catch(e){ root.innerHTML = `<div class="card empty">${esc(e.message)}<div class="row" style="justify-content:center;margin-top:10px"><button class="btn" id="wbBack">자료함으로</button></div></div>`;
      root.querySelector('#wbBack').onclick = () => opts.onClose && opts.onClose(); return }
    setTab(o.tab || S.tab || 'chunks');
  }

  async function loadDoc(){
    S.doc = await api(`/api/wb/docs/${S.docId}`);
    $('#wbTitle').textContent = S.doc.file_name;
    const c = S.doc.confidentiality;
    $('#wbConf').innerHTML = `<span class="pill ${c==='기밀'?'bad':c==='내부'?'warn':''}">${esc(c)}</span>`;
  }

  async function undo(){
    try { const r = await api(`/api/wb/docs/${S.docId}/undo`, {method:'POST'}); toast(`되돌렸습니다 (${opName(r.undone)})`);
      await loadDoc(); refresh() } catch(e){ fail(e) }
  }
  const opName = o => ({edit:'글 고치기', split:'나누기', merge:'합치기', type:'종류', section:'섹션', heading:'제목 올리기',
    drop:'청크 지우기', drop_line:'잡음 줄 지우기', rules:'규칙 적용'})[o] || o;
  function refresh(){ ({parse: renderParse, chunks: renderChunks, labels: renderLabels, learned: renderLearned})[S.tab]?.() }

  // ------------------------------------------------------------ 파싱 (P 묶음의 parse.js를 지연 로드)
  async function renderParse(){
    const p = $('#wbp-parse');
    if (S.parse === S.docId) return;
    p.innerHTML = `<div class="card"><div class="empty">파서 도구를 불러오는 중…</div></div>`;
    try {
      const m = await import(new URL('./parse.js', import.meta.url).href);
      if (typeof m.mountParse !== 'function') throw new Error('mountParse 없음');
      p.innerHTML = '<div></div>';
      m.mountParse(p.firstElementChild, {api, toast, docId: S.docId,
        onReparsed: async () => { toast('다시 파싱했습니다 — 청크를 새로 읽습니다'); S.sel = null; S.lab.chunk = null; await loadDoc() }});
      S.parse = S.docId;
    } catch(e){
      p.innerHTML = `<div class="card"><h2>파서 도구 준비 중</h2><p class="sub">파서 선택·다시 파싱 화면이 아직 설치되지 않았습니다. 청크·라벨 탭은 그대로 쓸 수 있습니다.</p>
        <p class="small muted" style="margin:0">자세히: ${esc(e.message)}</p></div>`;
    }
  }

  // ------------------------------------------------------------ 청크
  async function renderChunks(){
    const p = $('#wbp-chunks');
    let r;
    try { r = await api(`/api/wb/docs/${S.docId}/chunks`) } catch(e){ p.innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return }
    S.chunks = r.chunks;
    if (!S.sel || !S.chunks.find(c => c.chunk_id === S.sel)) S.sel = (S.chunks.find(c => c.flags.length) || S.chunks[0] || {}).chunk_id;
    const sum = Object.entries(r.summary).map(([k,n]) => `<span class="flag ${k==='broken'||k==='table_split'?'info':''}">${FLAG_KO[k]||k} ${n}</span>`).join(' ');
    p.innerHTML = `
      <div class="card"><div class="row"><h2 class="grow">청크 ${S.chunks.length}개 <span class="small muted">· 문제 표시 ${r.flagged_chunks}개 · 짧음 &lt;${r.min_len}자 · 김 &gt;${r.max_len}자</span></h2>
        <label class="small"><input type="checkbox" id="wbOnlyFlag" ${S.filter?'checked':''}> 문제 있는 것만</label></div>
        <div class="flags">${sum || '<span class="small muted">눈에 띄는 문제가 없습니다.</span>'}</div></div>
      <div class="cgrid">
        <div class="clist" id="wbList" role="listbox" aria-label="청크 목록"></div>
        <div style="display:grid;gap:12px;min-width:0"><div class="card" id="wbEd"></div><div class="card" id="wbRules"></div></div>
      </div>`;
    $('#wbOnlyFlag').onchange = e => { S.filter = e.target.checked; drawList() };
    drawList(); drawEditor(); drawRules();
  }

  function drawList(){
    const list = S.chunks.filter(c => !S.filter || c.flags.length);
    $('#wbList').innerHTML = list.length ? list.map(c => `<button class="citem" role="option" data-id="${c.chunk_id}" aria-current="${c.chunk_id===S.sel}" aria-selected="${c.chunk_id===S.sel}">
      <div class="m"><b>#${c.ord+1}</b>${c.page?`<span>p.${c.page}</span>`:''}<span>${c.chunk_type==='table'?'표':'본문'}</span><span>${c.length}자</span>
        ${c.annotations?`<span>라벨 ${c.annotations}</span>`:''}<span class="grow"></span></div>
      <div class="m" style="overflow-wrap:anywhere">${esc(c.heading||'')}</div>
      <div class="t">${esc(c.text.slice(c.prefix_len, c.prefix_len + 140))}</div>
      ${c.flags.length?`<div class="flags">${c.flags.map(f=>`<span class="flag ${f.level==='info'?'info':''}">${FLAG_KO[f.code]||f.code}</span>`).join('')}</div>`:''}</button>`).join('')
      : '<div class="empty">문제 표시가 있는 청크가 없습니다.</div>';
    $$('#wbList .citem').forEach(b => b.onclick = () => { S.sel = b.dataset.id; S.report = null; drawList(); drawEditor() });
  }

  function drawEditor(){
    const c = S.chunks.find(x => x.chunk_id === S.sel), ed = $('#wbEd');
    if (!c){ ed.innerHTML = '<div class="empty">왼쪽에서 청크를 고르세요.</div>'; return }
    const secs = S.doc.sections || [];
    ed.innerHTML = `
      <div class="row"><h2 class="grow">#${c.ord+1} ${esc(c.heading||'')}</h2><span class="small muted">${c.page?`p.${c.page} · `:''}${c.length}자 · 라벨 ${c.annotations}</span></div>
      ${c.flags.length ? `<ul class="flaglist" style="margin:6px 0 8px">${c.flags.map(f => `<li><span class="flag ${f.level==='info'?'info':''}">${FLAG_KO[f.code]||f.code}</span><span>${esc(f.msg)}</span>
        ${(f.lines||[]).map(l => `<button class="btn sm" data-noise="${esc(l.line)}" title="${esc(l.why)}">“${esc(l.line.slice(0,30))}” 지우기</button>`).join('')}</li>`).join('')}</ul>` : ''}
      <label class="small muted" for="wbText">본문 (커서를 둔 자리·줄이 나누기·제목·잡음 줄 지우기의 기준입니다)</label>
      <textarea class="inp" id="wbText" rows="12" spellcheck="false">${esc(c.text)}</textarea>
      <div class="tools" style="margin-top:8px">
        <button class="btn sm primary" id="wbSave">글 저장</button>
        <button class="btn sm" id="wbSplit" title="커서 위치에서 두 청크로">커서에서 나누기</button>
        <button class="btn sm" id="wbMergeP">↑ 이전과 합치기</button><button class="btn sm" id="wbMergeN">↓ 다음과 합치기</button>
        <button class="btn sm" id="wbHead" title="커서가 있는 줄을 새 섹션 제목으로">커서 줄을 제목으로</button>
        <button class="btn sm" id="wbNoise" title="커서가 있는 줄을 지웁니다(머리글·바닥글·쪽 번호)">커서 줄 지우기(잡음)</button>
        <button class="btn sm bad" id="wbDrop">청크 지우기(잡음)</button>
      </div>
      <div class="row" style="margin-top:8px">
        <label class="small">종류 <select class="inp" id="wbType"><option value="text" ${c.chunk_type==='text'?'selected':''}>본문</option><option value="table" ${c.chunk_type==='table'?'selected':''}>표</option></select></label>
        <label class="small">섹션 <select class="inp" id="wbSec" style="max-width:260px">${secs.map(s => `<option value="${s.section_id}" ${s.section_id===c.section_id?'selected':''}>${esc(s.heading)}</option>`).join('')}<option value="__new">+ 새 섹션…</option></select></label>
        <button class="btn sm" id="wbLabelHere">이 청크 라벨 보기</button>
      </div>
      <div class="report" id="wbReport" style="margin-top:8px"></div>`;
    showReport();
    const ta = $('#wbText');
    const run = async (path, body, msg) => {
      try { const r = await api(`/api/wb/chunks/${c.chunk_id}/${path}`, {method:'POST', body}); S.report = r.report; toast(msg(r));
        S.sel = r.chunk_ids ? r.chunk_ids[0] : c.chunk_id;
        await loadDoc(); await renderChunks() } catch(e){ fail(e) }
    };
    $('#wbSave').onclick = () => run('edit', {text: ta.value}, () => '글을 저장했습니다');
    $('#wbSplit').onclick = () => run('split', {pos: ta.selectionStart}, () => '나눴습니다 — 뒤쪽 조각은 아래 새 청크입니다');
    $('#wbMergeP').onclick = () => run('merge', {direction:'prev'}, () => '이전 청크와 합쳤습니다');
    $('#wbMergeN').onclick = () => run('merge', {direction:'next'}, () => '다음 청크와 합쳤습니다');
    $('#wbHead').onclick = () => run('heading', {line: lineAt(ta.value, ta.selectionStart)}, () => '새 섹션 제목으로 올렸습니다');
    $('#wbNoise').onclick = () => run('drop-line', {line: lineAt(ta.value, ta.selectionStart)}, r => `잡음 줄 ${r.removed_lines}개를 지웠습니다`);
    $$('#wbEd [data-noise]').forEach(b => b.onclick = () => run('drop-line', {line: b.dataset.noise}, r => `잡음 줄 ${r.removed_lines}개를 지웠습니다`));
    $('#wbDrop').onclick = async () => {
      if (!confirm('이 청크를 잡음으로 지울까요? 사전·AI 라벨은 함께 지워지고, “되돌리기”로 되살릴 수 있습니다.')) return;
      try { await api(`/api/wb/chunks/${c.chunk_id}/drop`, {method:'POST', body:{force:false}}) }
      catch(e){ if (!/그래도 지우기/.test(e.message)) return fail(e);
        if (!confirm(e.message + '\n\n그래도 지울까요?')) return;
        try { await api(`/api/wb/chunks/${c.chunk_id}/drop`, {method:'POST', body:{force:true}}) } catch(e2){ return fail(e2) } }
      toast('청크를 지웠습니다 — 되돌리기로 되살릴 수 있습니다'); S.sel = null; await loadDoc(); renderChunks();
    };
    $('#wbType').onchange = e => run('type', {chunk_type: e.target.value}, () => '종류를 바꿨습니다');
    $('#wbSec').onchange = e => {
      if (e.target.value === '__new'){ const h = prompt('새 섹션 제목'); if (!h){ e.target.value = c.section_id; return }
        return run('section', {heading: h}, () => '새 섹션으로 옮겼습니다') }
      run('section', {section_id: e.target.value}, () => '섹션을 바꿨습니다');
    };
    $('#wbLabelHere').onclick = () => { S.lab.chunk = c.chunk_id; setTab('labels') };
  }

  function showReport(){
    const r = S.report, box = $('#wbReport'); if (!box) return;
    if (!r){ box.innerHTML = ''; return }
    const parts = [];
    if (r.shifted) parts.push(`라벨 ${r.shifted}개 위치 옮김`);
    if (r.moved) parts.push(`라벨 ${r.moved}개 다른 청크로 옮김`);
    box.innerHTML = (parts.length ? `<div class="info">${parts.join(' · ')}</div>` : '') +
      (r.dropped?.length ? `<div class="notice" style="margin-top:6px"><b>지운 사전·AI 라벨 ${r.dropped.length}개</b> — 표기가 본문에서 사라졌습니다: ${r.dropped.slice(0,8).map(d => esc(d.surface)).join(', ')}</div>` : '') +
      (r.flagged?.length ? `<div class="notice" style="margin-top:6px"><b>위치 확인이 필요한 사람 라벨 ${r.flagged.length}개</b> — 지우지 않고 남겨 두었습니다. 라벨 탭에서 자리를 다시 잡으세요: ${r.flagged.slice(0,8).map(d => esc(d.surface)).join(', ')}</div>` : '');
  }

  // 규칙 제안·적용
  async function drawRules(){
    const box = $('#wbRules');
    let pr, rules;
    try { [pr, rules] = await Promise.all([api(`/api/wb/docs/${S.docId}/rules/proposals`), api(`/api/wb/rules?doc_id=${S.docId}`)]) }
    catch(e){ box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return }
    const scopes = pr.scopes;
    const scopeSel = (i, def) => `<select class="inp" data-scope="${i}">${scopes.map((s,k) => `<option value="${k}" ${s.type===def?'selected':''}>${esc(s.label)}</option>`).join('')}</select>`;
    const defScope = p => p.kind === 'noise' ? 'file_pattern' : p.kind === 'heading' ? 'title_prefix' : 'format';
    box.innerHTML = `<h2>규칙 배우기</h2><p class="sub">이 자료에서 고친 것(잡음 줄·제목·합치기·나누기)으로 규칙을 제안합니다. 범위를 골라 저장하면 비슷한 자료에도 쓸 수 있습니다. 모델을 다시 학습시키지 않습니다.</p>
      <div style="display:grid;gap:8px">${pr.proposals.length ? pr.proposals.map((p,i) => `<div class="prop">
        <div class="row"><span class="pill acc">${esc(p.kind_label)}</span><b class="grow">${esc(p.note)}</b></div>
        ${p.pattern?`<div class="small">줄 모양 <code>${esc(p.pattern)}</code></div>`:''}${Object.keys(p.params||{}).length?`<div class="small">값 <code>${esc(JSON.stringify(p.params))}</code></div>`:''}
        <div class="small muted">${p.evidence.map(esc).join(' · ')}</div>
        <div class="row"><label class="small">범위 ${scopeSel(i, defScope(p))}</label><span class="grow"></span>
          <button class="btn sm" data-pv="${i}">미리보기(이 자료)</button><button class="btn sm primary" data-acc="${i}">규칙으로 저장</button></div></div>`).join('')
        : '<div class="info">아직 제안할 것이 없습니다. 잡음 줄을 지우거나, 줄을 제목으로 올리거나, 짧은 조각을 합치면 여기에 규칙 후보가 생깁니다.</div>'}</div>
      <h3>이 자료에 맞는 규칙 ${rules.length}개</h3>
      ${rules.length ? `<table><thead><tr><th>규칙</th><th>범위</th><th>적용</th><th></th></tr></thead><tbody>${rules.map(r => `<tr>
        <td><span class="pill ${r.origin==='learned'?'earth':''}">${r.origin==='learned'?'배움':'직접'}</span> ${esc(r.kind_label)}${r.pattern?` <code class="small">${esc(r.pattern)}</code>`:''}${r.enabled?'':' <span class="pill">꺼짐</span>'}</td>
        <td class="small">${esc(r.scope_label)}</td><td class="small">${r.hits}회</td></tr>`).join('')}</tbody></table>
        <div class="row" style="margin-top:8px"><span class="grow small muted">켜진 규칙을 이 자료에 적용합니다. 한 번의 “되돌리기”로 모두 되돌릴 수 있습니다.</span>
          <button class="btn sm" id="wbRulePv">미리보기</button><button class="btn sm primary" id="wbRuleApply">이 자료에 적용</button></div>`
        : '<p class="small muted">아직 없습니다. 위 제안을 저장하거나 “배운 것” 탭에서 직접 만들 수 있습니다.</p>'}
      <div id="wbDiff" style="margin-top:8px"></div>`;
    const pick = i => scopes[+box.querySelector(`[data-scope="${i}"]`).value];
    box.querySelectorAll('[data-pv]').forEach(b => b.onclick = async () => {
      const p = pr.proposals[+b.dataset.pv];
      try { showDiff(await api(`/api/wb/docs/${S.docId}/rules/preview`, {method:'POST', body:{rules:[p]}})) } catch(e){ fail(e) }
    });
    box.querySelectorAll('[data-acc]').forEach(b => b.onclick = async () => {
      const i = +b.dataset.acc, p = pr.proposals[i], sc = pick(i);
      if (!confirm(`'${p.kind_label}' 규칙을 저장할까요?\n범위: ${sc.label}\n\n저장한 규칙은 “배운 것” 탭에서 끄거나 지울 수 있습니다.`)) return;
      try { await api('/api/wb/rules/accept', {method:'POST', body:{proposal:p, scope:{type:sc.type, value:sc.value}}}); toast('규칙을 저장했습니다'); drawRules() } catch(e){ fail(e) }
    });
    const pv = box.querySelector('#wbRulePv'), ap = box.querySelector('#wbRuleApply');
    if (pv) pv.onclick = async () => { try { showDiff(await api(`/api/wb/docs/${S.docId}/rules/preview`, {method:'POST', body:{}})) } catch(e){ fail(e) } };
    if (ap) ap.onclick = async () => {
      try { const r = await api(`/api/wb/docs/${S.docId}/rules/apply`, {method:'POST', body:{}}); S.report = r.report;
        toast(r.total ? `규칙 적용: ${r.total}곳을 바꿨습니다` : '바꿀 곳이 없었습니다'); await loadDoc(); renderChunks() } catch(e){ fail(e) }
    };
  }

  function showDiff(r){
    const box = $('#wbDiff'); if (!box) return;
    box.innerHTML = `<div class="info"><b>미리보기</b> — ${r.total}곳이 바뀝니다 · 청크 ${r.before}개 → ${r.after}개 (아직 저장하지 않았습니다)</div>
      <div class="diff" style="margin-top:6px">${(r.changes||[]).slice(0,80).map(c => `<div><span class="pill">${esc(c.action)}</span> #${c.ord+1} ${c.before?`<del>${esc(c.before.slice(0,120))}</del>`:''}${c.after?`${c.before?' → ':''}<ins>${esc(c.after.slice(0,120))}</ins>`:''}</div>`).join('') || '<div>바뀌는 곳이 없습니다.</div>'}</div>`;
  }

  // ------------------------------------------------------------ 라벨
  async function renderLabels(){
    const p = $('#wbp-labels');
    if (!S.chunks.length){ try { S.chunks = (await api(`/api/wb/docs/${S.docId}/chunks`)).chunks } catch(e){ p.innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return } }
    if (!S.lab.chunk || !S.chunks.find(c => c.chunk_id === S.lab.chunk)) S.lab.chunk = (S.chunks.find(c => c.chunk_id === S.sel) || S.chunks[0] || {}).chunk_id;
    p.innerHTML = `
      <div class="card"><div class="row"><h2 class="grow">자동 라벨</h2>
        <button class="btn sm" id="wbDictDoc" title="배운 동의어·부정 사례를 반영해 사전 라벨을 다시 붙입니다(승인·거절한 것은 그대로)">사전 라벨 다시 (자료 전체)</button>
        <button class="btn sm" id="wbDictOne">사전 라벨 다시 (이 청크)</button>
        <button class="btn sm primary" id="wbAiDoc">AI 라벨 (자료 전체)</button><button class="btn sm" id="wbAiOne">AI 라벨 (이 청크)</button>
        <button class="btn sm" id="wbExPv" title="AI 라벨을 돌릴 때 프롬프트에 붙는 사례를 그대로 봅니다">AI에 보낼 사례 보기</button></div>
        <div id="wbRun" style="margin-top:8px" hidden><div class="bar" role="progressbar" aria-valuemin="0"><i class="ok"></i><i class="err"></i><i class="skip"></i></div><p class="small muted" id="wbRunText" style="margin:4px 0 0"></p></div>
        <div id="wbExBox"></div></div>
      <div class="lgrid">
        <div class="card" style="min-width:0">
          <div class="row"><button class="btn sm" id="wbPrev" title="이전 청크 ( [ )">◀</button>
            <select class="inp grow" id="wbChunkSel" aria-label="청크 고르기">${S.chunks.map(c => `<option value="${c.chunk_id}" ${c.chunk_id===S.lab.chunk?'selected':''}>#${c.ord+1} ${esc((c.heading||'').slice(0,30))} · ${c.annotations}개${c.lost?' · 확인 필요':''}</option>`).join('')}</select>
            <button class="btn sm" id="wbNext" title="다음 청크 ( ] )">▶</button></div>
          <div class="legend" style="margin:8px 0">${LT_ORDER.map(t => `<span><i style="--c:var(--lt-${t})"></i>${LT_KO[t]}</span>`).join('')}<span class="muted">· 점선 = 검토 대기·자동</span></div>
          <div class="ltext" id="wbLText" tabindex="0" aria-label="청크 본문 — 글을 선택한 뒤 L 키 또는 '선택에 라벨'"></div>
          <div class="row" style="margin-top:8px">
            <button class="btn sm primary" id="wbLabelSel">선택에 라벨 (L)</button>
            <span class="grow"></span>
            <label class="small" for="wbSurf">표기로 붙이기</label><input class="inp" id="wbSurf" placeholder="본문 글자 그대로" style="width:180px">
            <input class="inp" id="wbOcc" type="number" min="1" value="1" style="width:60px" title="같은 표기가 여러 번이면 몇 번째">
            <button class="btn sm" id="wbSurfGo">라벨</button></div>
          <p class="small muted" style="margin:6px 0 0">단축키: <kbd>J</kbd>/<kbd>K</kbd> 라벨 이동 · <kbd>A</kbd> 승인 · <kbd>R</kbd> 거절 · <kbd>L</kbd> 선택에 라벨 · <kbd>E</kbd> 고치기 · <kbd>[</kbd>/<kbd>]</kbd> 이전·다음 청크</p>
          <div id="wbOffer" style="margin-top:8px"></div>
        </div>
        <div class="card" style="min-width:0"><h2>이 청크의 라벨</h2><div id="wbLList"></div></div>
      </div>`;
    $('#wbChunkSel').onchange = e => { S.lab.chunk = e.target.value; S.lab.idx = -1; drawLabelChunk() };
    $('#wbPrev').onclick = () => stepChunk(-1); $('#wbNext').onclick = () => stepChunk(1);
    $('#wbLabelSel').onclick = labelSelection;
    $('#wbSurfGo').onclick = labelBySurface;
    $('#wbSurf').onkeydown = e => { if (e.key === 'Enter') labelBySurface() };
    $('#wbDictDoc').onclick = () => dictLabel(null); $('#wbDictOne').onclick = () => dictLabel([S.lab.chunk]);
    $('#wbAiDoc').onclick = () => aiLabel(null); $('#wbAiOne').onclick = () => aiLabel([S.lab.chunk]);
    $('#wbExPv').onclick = examplesPreview;
    drawLabelChunk();
    try { const runs = await api(`/api/wb/docs/${S.docId}/ai-runs?limit=1`); if (runs[0] && runs[0].status === 'running') watchRun(runs[0].run_id) } catch {}
  }

  function stepChunk(d){
    const i = S.chunks.findIndex(c => c.chunk_id === S.lab.chunk), n = S.chunks[i + d]; if (!n) return;
    S.lab.chunk = n.chunk_id; S.lab.idx = -1; $('#wbChunkSel').value = n.chunk_id; drawLabelChunk();
  }

  async function drawLabelChunk(){
    if (!S.lab.chunk){ $('#wbLText').innerHTML = '<span class="muted">청크가 없습니다.</span>'; return }
    let c; try { c = await api(`/api/wb/chunks/${S.lab.chunk}`) } catch(e){ fail(e); return }
    S.lab.data = c;
    const anns = c.annotations;
    const placed = anns.filter(a => a.status !== 'rejected' && a.span_start != null).sort((a,b) => a.span_start - b.span_start || b.span_end - a.span_end);
    let html = '', pos = 0;
    for (const a of placed){
      if (a.span_start < pos) continue;
      html += esc(c.text.slice(pos, a.span_start)) + `<span class="an ${a.status}" data-ann="${a.ann_id}" style="--c:var(--lt-${a.label_type})" title="${esc(LT_KO[a.label_type]||a.label_type)}${a.concept?' → '+esc(a.concept):''} · ${METHOD_KO[a.method]||a.method} · ${STATUS_KO[a.status]||a.status}">${esc(c.text.slice(a.span_start, a.span_end))}</span>`;
      pos = a.span_end;
    }
    $('#wbLText').innerHTML = html + esc(c.text.slice(pos));
    $$('#wbLText .an').forEach(s => s.onclick = () => { const i = S.lab.list.findIndex(a => a.ann_id === s.dataset.ann); focusLabel(i) });
    drawLabelList();
  }

  function valText(a){ try { const o = JSON.parse(a.normalized_value || 'null'); return o ? `${o.target||''} ${o.value} ${o.unit||''}${o.basis?' ('+o.basis+')':''}`.trim() : '' } catch { return '' } }

  function drawLabelList(){
    const anns = S.lab.data.annotations;
    S.lab.list = anns;
    const lost = anns.filter(a => a.span_start == null);
    $('#wbLList').innerHTML = (lost.length ? `<div class="notice" style="margin-bottom:8px"><b>위치 확인 필요 ${lost.length}개</b> — 청크를 고치는 중 표기를 찾지 못한 사람 라벨입니다. “고치기”에서 본문을 다시 선택해 자리를 잡거나 지우세요.</div>` : '') +
      (anns.length ? `<table><thead><tr><th>표기</th><th>라벨</th><th>상태</th><th></th></tr></thead><tbody>${anns.map((a,i) => `<tr data-i="${i}" class="${a.status==='rejected'?'rej':''}">
        <td style="overflow-wrap:anywhere"><span class="an" style="--c:var(--lt-${a.label_type})">${esc(a.surface_text)}</span>${a.span_start==null?' <span class="pill warn">위치 확인</span>':''}</td>
        <td><span class="pill" style="color:var(--lt-${a.label_type})">${LT_KO[a.label_type]||a.label_type}</span><div class="small">${esc(a.concept||'')}${valText(a)?`<div class="mono">${esc(valText(a))}</div>`:''}${a.meas_id?'<span class="pill ok">측정값</span>':''}</div></td>
        <td class="small">${METHOD_KO[a.method]||a.method}<br>${STATUS_KO[a.status]||a.status}${a.confidence!=null&&a.method!=='human'?` · ${a.confidence}`:''}</td>
        <td><div class="tools">${a.status==='pending'||a.status==='auto'?`<button class="btn sm ok" data-act="accepted">승인</button><button class="btn sm bad" data-act="rejected">거절</button>`:''}
          ${a.status==='rejected'?`<button class="btn sm" data-act="pending">되돌리기</button>`:''}
          <button class="btn sm" data-act="edit">고치기</button><button class="btn sm bad" data-act="del">지우기</button></div></td></tr>`).join('')}</tbody></table>`
      : '<div class="empty">라벨이 없습니다. 본문을 선택하고 L을 누르거나, “사전 라벨 다시”·“AI 라벨”을 써 보세요.</div>');
    $$('#wbLList tr[data-i]').forEach(tr => {
      tr.onclick = () => focusLabel(+tr.dataset.i, false);
      tr.querySelectorAll('[data-act]').forEach(b => b.onclick = e => { e.stopPropagation(); act(S.lab.list[+tr.dataset.i], b.dataset.act) });
    });
    if (S.lab.idx >= 0) focusLabel(S.lab.idx, false);
  }

  function focusLabel(i, scroll = true){
    const list = S.lab.list || []; if (!list.length){ S.lab.idx = -1; return }
    S.lab.idx = Math.max(0, Math.min(i, list.length - 1));
    $$('#wbLList tr.lf').forEach(t => t.classList.remove('lf')); $$('#wbLText .an.focus').forEach(t => t.classList.remove('focus'));
    const tr = $(`#wbLList tr[data-i="${S.lab.idx}"]`); if (tr){ tr.classList.add('lf'); if (scroll) tr.scrollIntoView({block:'nearest'}) }
    const sp = $(`#wbLText [data-ann="${list[S.lab.idx].ann_id}"]`); if (sp){ sp.classList.add('focus'); if (scroll) sp.scrollIntoView({block:'nearest'}) }
  }

  async function act(a, what){
    if (!a) return;
    try {
      if (what === 'edit') return openPop({edit: a});
      if (what === 'del'){
        const neg = a.method === 'dict' && confirm(`'${a.surface_text}' 사전 라벨을 지웁니다.\n이 문맥에서 사전이 다시 붙이지 않도록 '부정 사례'로 배울까요? (확인 = 배우기, 취소 = 그냥 지우기)`);
        if (a.method !== 'dict' && !confirm(`'${a.surface_text}' 라벨을 지울까요?${a.meas_id?' 이 라벨에서 올린 측정값도 지워집니다.':''}`)) return;
        await api(`/api/wb/labels/${a.ann_id}?learn_negative=${neg}`, {method:'DELETE'}); toast(neg ? '지우고 부정 사례로 배웠습니다' : '지웠습니다');
      } else {
        const r = await api(`/api/wb/labels/${a.ann_id}/review`, {method:'POST', body:{status: what, learn: true}});
        toast(what === 'accepted' ? (r.measurement_id ? '승인 — 측정값 표에 올렸습니다' : '승인했습니다')
          : what === 'rejected' ? (r.negative_example ? '거절 — 이 문맥에서 사전 라벨을 다시 붙이지 않도록 배웠습니다(배운 것 탭에서 끌 수 있음)' : '거절했습니다')
          : '되돌렸습니다');
      }
      const keep = S.lab.idx; await drawLabelChunk(); focusLabel(what === 'accepted' || what === 'rejected' ? keep + 1 : keep);
    } catch(e){ fail(e) }
  }

  // 선택 → 오프셋
  function selectionOffsets(){
    const box = $('#wbLText'), sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
    const r = sel.getRangeAt(0);
    if (!box.contains(r.startContainer) || !box.contains(r.endContainer)) return null;
    const pre = document.createRange(); pre.selectNodeContents(box); pre.setEnd(r.startContainer, r.startOffset);
    const start = pre.toString().length, len = r.toString().length;
    let s = start, e = start + len; const t = S.lab.data.text;
    while (s < e && /\s/.test(t[s])) s++; while (e > s && /\s/.test(t[e - 1])) e--;
    return e > s ? {start: s, end: e, rect: r.getBoundingClientRect()} : null;
  }

  async function labelSelection(){
    const o = selectionOffsets();
    if (!o) return toast('본문에서 라벨을 붙일 글을 먼저 선택하세요. 키보드로는 “표기로 붙이기”를 쓰세요.');
    try { const sug = await api(`/api/wb/suggest?chunk_id=${S.lab.chunk}&start=${o.start}&end=${o.end}`); openPop({sug, rect: o.rect}) } catch(e){ fail(e) }
  }

  async function labelBySurface(){
    const surf = $('#wbSurf').value; if (!surf.trim()) return toast('표기를 넣으세요(본문 글자 그대로)');
    const t = S.lab.data.text, n = Math.max(1, +$('#wbOcc').value || 1);
    let k = -1; for (let i = 0; i < n; i++){ k = t.indexOf(surf, k + 1); if (k < 0) break }
    if (k < 0) return toast(`'${surf}'을(를) 이 청크에서 찾지 못했습니다(${n}번째). 본문 글자를 그대로 넣으세요.`);
    try { const sug = await api(`/api/wb/suggest?chunk_id=${S.lab.chunk}&start=${k}&end=${k + surf.length}`); openPop({sug, rect: $('#wbSurf').getBoundingClientRect()}) } catch(e){ fail(e) }
  }

  // 라벨 붙이기·고치기 팝업
  function openPop({sug, edit, rect}){
    const pop = $('#wbPop');
    const a = edit || null;
    let v = {}; if (a){ try { v = JSON.parse(a.normalized_value || '{}') || {} } catch {} }
    const surface = a ? a.surface_text : sug.surface;
    const lt = a ? a.label_type : (sug.label_type || 'OTHER');
    S.lab.edit = a; S.lab.sel = sug || null; S.lab.concept = a ? (a.concept_id ? {concept_id: a.concept_id, pref_label: a.concept} : null) : (sug.concepts?.[0]?.exact ? sug.concepts[0] : null);
    const val = a ? v : (sug.value || {});
    pop.innerHTML = `<div class="row"><b class="grow">${a ? '라벨 고치기' : '라벨 붙이기'}</b><button class="btn sm" data-x>닫기</button></div>
      <div class="small" style="overflow-wrap:anywhere">표기: <span class="an" style="--c:var(--lt-${lt})">${esc(surface)}</span></div>
      <div class="kv"><b>종류</b><select class="inp" id="wpType">${LT_ORDER.map(t => `<option value="${t}" ${t===lt?'selected':''}>${LT_KO[t]} (${t})</option>`).join('')}</select>
        <b>개념</b><input class="inp" id="wpQ" placeholder="표준명·동의어로 찾기" value="${esc(S.lab.concept?.pref_label || (a ? '' : (lt === 'VALUE' && sug.target ? sug.target : surface)))}"></div>
      <div class="cands" id="wpC" role="listbox" aria-label="개념 후보"></div>
      <div class="row small"><span class="muted">맞는 개념이 없으면</span><select class="inp" id="wpScheme" style="height:26px">${SCHEMES.map(s => `<option>${s}</option>`).join('')}</select><button class="btn sm" id="wpNew">새 개념으로</button></div>
      <div class="kv" id="wpVal"><b>값</b><input class="inp" id="wpV" value="${esc(val.value ?? '')}" inputmode="decimal">
        <b>단위</b><input class="inp" id="wpU" value="${esc(val.unit ?? '')}"><b>항목</b><input class="inp" id="wpT" value="${esc(val.target ?? (sug?.target || ''))}" placeholder="예: 식이섬유">
        <b>기준</b><input class="inp" id="wpB" value="${esc(val.basis ?? '')}" placeholder="건량·습량"></div>
      ${a && a.span_start == null ? '<div class="notice">위치를 잃은 라벨입니다. 본문에서 글을 다시 선택한 뒤 “선택한 자리로”를 누르세요. <button class="btn sm" id="wpRespan">선택한 자리로</button></div>' : ''}
      <div class="row"><span class="small muted grow">${a ? (a.method !== 'human' ? '고치면 “고친 라벨”로 승인되고 AI 사례로 남습니다.' : '') : '사람 라벨은 바로 승인됩니다. 수치는 측정값으로 올라갑니다.'}</span><button class="btn primary sm" id="wpSave">저장 (Enter)</button></div>`;
    pop.hidden = false;
    const r = rect || $('#wbLText').getBoundingClientRect();
    const top = Math.min(window.innerHeight - pop.offsetHeight - 12, (r.bottom || 80) + 8);
    pop.style.top = Math.max(12, top) + 'px'; pop.style.left = Math.max(12, Math.min(window.innerWidth - pop.offsetWidth - 12, r.left || 12)) + 'px';
    const showVal = () => { pop.querySelector('#wpVal').style.display = pop.querySelector('#wpType').value === 'VALUE' ? '' : 'none' };
    pop.querySelector('#wpType').onchange = showVal; showVal();
    pop.querySelector('[data-x]').onclick = hidePop;
    let qt; const q = pop.querySelector('#wpQ');
    const search = async () => {
      const term = q.value.trim(); const box = pop.querySelector('#wpC');
      if (!term){ box.innerHTML = ''; return }
      let m = []; try { m = (await api('/api/wb/concepts?q=' + encodeURIComponent(term))).matches } catch {}
      if (!S.lab.concept && !a && m[0]?.exact && pop.querySelector('#wpType').value === 'VALUE') S.lab.concept = m[0];  // 수치: 항목 개념을 미리 고른다
      box.innerHTML = m.slice(0, 8).map((h,i) => `<button type="button" data-i="${i}" aria-pressed="${S.lab.concept?.concept_id===h.concept_id}"><b>${esc(h.pref_label)}</b><span class="pill">${esc(h.scheme||'')}</span><span class="small muted" style="overflow-wrap:anywhere">${esc(h.labels.slice(0,5).join(' · '))}</span></button>`).join('')
        || '<span class="small muted">찾은 개념이 없습니다.</span>';
      box.querySelectorAll('button').forEach(b => b.onclick = () => { S.lab.concept = m[+b.dataset.i]; box.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === b))) });
    };
    q.oninput = () => { clearTimeout(qt); qt = setTimeout(search, 200) }; search();
    pop.querySelector('#wpNew').onclick = async () => {
      const label = q.value.trim(); if (!label) return toast('새 개념의 표준명을 개념 칸에 넣으세요');
      if (!confirm(`'${label}'을(를) 새 개념(${pop.querySelector('#wpScheme').value}, 내 확장)으로 만들까요?`)) return;
      try { const r = await api('/api/wb/concepts', {method:'POST', body:{label, scheme: pop.querySelector('#wpScheme').value}});
        S.lab.concept = {concept_id: r.concept_id, pref_label: r.pref_label}; toast(r.exists ? '이미 있는 개념을 골랐습니다' : '새 개념을 만들었습니다'); search() } catch(e){ fail(e) }
    };
    const rs = pop.querySelector('#wpRespan');
    if (rs) rs.onclick = async () => { const o = selectionOffsets(); if (!o) return toast('본문에서 글을 먼저 선택하세요');
      try { await api(`/api/wb/labels/${a.ann_id}`, {method:'PATCH', body:{start:o.start, end:o.end}}); toast('자리를 다시 잡았습니다'); hidePop(); drawLabelChunk() } catch(e){ fail(e) } };
    pop.querySelector('#wpSave').onclick = savePop;
    pop.onkeydown = e => { if (e.key === 'Escape'){ hidePop(); e.stopPropagation() } else if (e.key === 'Enter' && e.target.tagName === 'INPUT'){ e.preventDefault(); savePop() } };
    pop.querySelector('#wpType').focus();
  }

  function hidePop(){ const p = root.querySelector('#wbPop'); if (p) p.hidden = true }

  async function savePop(){
    const pop = $('#wbPop'), g = s => pop.querySelector(s).value.trim();
    const type = g('#wpType'), isVal = type === 'VALUE';
    const body = {label_type: type, concept_id: S.lab.concept?.concept_id || null};
    if (isVal) Object.assign(body, {value: g('#wpV') || null, unit: g('#wpU') || null, target: g('#wpT') || null, basis: g('#wpB') || null});
    try {
      let r;
      if (S.lab.edit){
        if (!body.concept_id) delete body.concept_id;
        r = await api(`/api/wb/labels/${S.lab.edit.ann_id}`, {method:'PATCH', body});
        toast(r.negative_example ? '고쳤습니다 — 사전의 옛 개념은 이 문맥에서 다시 붙이지 않도록 배웠습니다' : '고쳤습니다');
      } else {
        r = await api('/api/wb/labels', {method:'POST', body:{chunk_id: S.lab.chunk, start: S.lab.sel.start, end: S.lab.sel.end, surface: S.lab.sel.surface, ...body}});
        toast(r.measurement_id ? '라벨을 붙이고 측정값 표에 올렸습니다' : '라벨을 붙였습니다');
      }
      hidePop(); window.getSelection()?.removeAllRanges();
      offer(r.offer_synonym, r.ann_id || S.lab.edit?.ann_id);
      await drawLabelChunk(); S.chunks = []; // 다음에 청크 목록 다시 읽기
    } catch(e){ fail(e) }
  }

  function offer(o, annId){
    const box = $('#wbOffer'); if (!box) return;
    if (!o){ box.innerHTML = ''; return }
    box.innerHTML = `<div class="offer"><span class="grow">${esc(o.message)}</span><button class="btn sm primary" id="wbLearnSyn">동의어로 배우기</button><button class="btn sm" id="wbNoSyn">아니요</button></div>`;
    box.querySelector('#wbNoSyn').onclick = () => box.innerHTML = '';
    box.querySelector('#wbLearnSyn').onclick = async () => {
      if (!confirm(`'${o.surface}'을(를) '${o.pref_label}'의 동의어로 배울까요?\n사전 라벨·검색이 이 표기도 찾게 됩니다. “배운 것” 탭에서 지울 수 있습니다.`)) return;
      try { const r = await api('/api/wb/learn/synonym', {method:'POST', body:{concept_id:o.concept_id, surface:o.surface, ann_id:annId}});
        toast(r.already ? '이미 아는 표기입니다' : `'${r.surface}' → '${r.concept}' 동의어로 배웠습니다`); box.innerHTML = '' } catch(e){ fail(e) }
    };
  }

  async function dictLabel(ids){
    try { const r = await api(`/api/wb/docs/${S.docId}/dict-label`, {method:'POST', body:{chunk_ids: ids}});
      toast(`사전 라벨 다시: ${r.chunks}개 청크 · 지움 ${r.removed} · 붙임 ${r.added}`); S.chunks = []; renderLabels() } catch(e){ fail(e) }
  }

  async function aiLabel(ids){
    if (!confirm(`Claude Code가 ${ids ? '이 청크' : '이 자료의 청크'}를 읽고 라벨을 제안합니다.\n본문과 '참고 사례'(기밀 자료는 식별 정보를 가리거나 빼서)가 Anthropic으로 전송됩니다. 계속할까요?`)) return;
    try { const r = await api(`/api/wb/docs/${S.docId}/ai-label`, {method:'POST', body:{chunk_ids: ids, force: !!ids}}); toast('AI 라벨링 시작'); watchRun(r.run_id) } catch(e){ fail(e) }
  }

  async function watchRun(id){
    clearTimeout(S.runTimer); S.run = id;
    let r; try { r = await api('/api/wb/ai-runs/' + id) } catch { return }
    const box = $('#wbRun'); if (!box) return;
    box.hidden = false;
    const pct = n => r.total ? (100 * n / r.total) + '%' : '0';
    const [a, b, c] = box.querySelectorAll('.bar i'); a.style.width = pct(r.ok); b.style.width = pct(r.error); c.style.width = pct(r.skipped);
    box.querySelector('.bar').setAttribute('aria-valuemax', r.total); box.querySelector('.bar').setAttribute('aria-valuenow', r.done);
    const live = r.status === 'running' || r.status === 'cancelling';
    $('#wbRunText').textContent = `AI 라벨 ${live ? '진행 중' : r.status === 'done' ? '완료' : r.status} · ${r.done}/${r.total} 청크 · 성공 ${r.ok} · 오류 ${r.error} · 건너뜀 ${r.skipped} · 검토 대기 ${r.pending_labels}건`
      + (!live && r.error ? ' · 자료함의 “재시도”로 남은 청크만 다시 할 수 있습니다' : '');
    if (live) S.runTimer = setTimeout(() => watchRun(id), 2000); else { S.chunks = []; if (S.tab === 'labels') drawLabelChunk() }
  }

  async function examplesPreview(){
    const box = $('#wbExBox');
    try { const r = await api(`/api/wb/docs/${S.docId}/examples-preview?chunk_ids=${S.lab.chunk || ''}`);
      box.innerHTML = `<h3>AI에 보낼 참고 사례 (${esc(r.engine)} · 기밀 규칙 ${r.rule === 'block' ? '보내지 않기' : '가림'}${r.excluded_confidential ? ` · 기밀 사례 ${r.excluded_confidential}개 뺌` : ''})</h3>
        ${r.section ? `<pre class="sec">${esc(r.section)}</pre>` : '<p class="small muted">보낼 사례가 없습니다. 사람 라벨을 붙이거나 고치면 사례가 생깁니다.</p>'}` } catch(e){ fail(e) }
  }

  // ------------------------------------------------------------ 배운 것
  async function renderLearned(){
    const p = $('#wbp-learned');
    let L; try { L = await api('/api/wb/learned') } catch(e){ p.innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return }
    const tog = (k, id, on) => `<label class="small"><input type="checkbox" data-tog="${k}" data-id="${id}" ${on?'checked':''}> 켜짐</label>`;
    p.innerHTML = `
      <div class="info">작업대에서 배운 것은 모두 이 PC에만 있습니다. 모델을 다시 학습시키지 않고, 규칙·동의어·사례로만 씁니다. 끄면 바로 쓰이지 않습니다.</div>
      <div class="card"><h2>청크 규칙 ${L.rules.length}개</h2><p class="sub">켜진 규칙은 범위가 맞는 자료를 다시 파싱하거나 “이 자료에 적용”할 때 쓰입니다.</p>
        ${L.rules.length ? `<table><thead><tr><th>규칙</th><th>범위</th><th>적용</th><th>적용한 자료</th><th></th></tr></thead><tbody>${L.rules.map(r => `<tr>
          <td><span class="pill ${r.origin==='learned'?'earth':''}">${r.origin==='learned'?'배움':'직접'}</span> <b>${esc(r.kind_label)}</b>${r.pattern?`<div><code class="small mono" style="word-break:break-all">${esc(r.pattern)}</code></div>`:''}${Object.keys(r.params||{}).length?`<div class="small mono">${esc(JSON.stringify(r.params))}</div>`:''}${r.note?`<div class="small muted">${esc(r.note)}</div>`:''}</td>
          <td class="small">${esc(r.scope_label)}</td><td class="small">${r.hits}회</td>
          <td class="small">${r.docs.map(d => esc(d.file_name)).slice(0,4).join('<br>') || '—'}</td>
          <td><div class="tools">${tog('rule', r.rule_id, r.enabled)}<button class="btn sm" data-edit-rule="${r.rule_id}">고치기</button><button class="btn sm bad" data-del-rule="${r.rule_id}">지우기</button></div></td></tr>`).join('')}</tbody></table>` : '<p class="small muted">아직 없습니다.</p>'}
        <details style="margin-top:8px"><summary class="small">규칙 직접 만들기</summary>
          <div class="row" style="margin-top:6px"><select class="inp" id="nrKind"><option value="noise">잡음 줄</option><option value="heading">제목 줄</option><option value="merge_short">짧은 조각 합치기</option><option value="table">표 묶기</option><option value="length">청크 길이</option></select>
            <input class="inp grow" id="nrPat" placeholder="줄 모양(정규식) 예: ^-\\s*\\d+\\s*-$"><input class="inp" id="nrParams" placeholder='값 예: {"min_len":120}' style="width:200px">
            <select class="inp" id="nrScope">${(S.doc?.scopes||[{type:'global',value:null,label:'모든 자료'}]).map((s,i) => `<option value="${i}" ${s.type==='global'?'selected':''}>${esc(s.label)}</option>`).join('')}</select>
            <button class="btn sm primary" id="nrGo">만들기</button></div></details></div>
      <div class="card"><h2>배운 동의어 ${L.synonyms.length}개</h2><p class="sub">사전 라벨·검색이 이 표기도 개념으로 찾습니다.</p>
        ${L.synonyms.length ? `<table><thead><tr><th>표기</th><th>개념</th><th>배운 때</th><th></th></tr></thead><tbody>${L.synonyms.map(s => `<tr><td><b>${esc(s.label)}</b></td><td>${esc(s.pref_label_ko)} <span class="pill">${esc(s.scheme||'')}</span></td><td class="small muted">${esc(s.at)}</td>
          <td><button class="btn sm bad" data-del-syn="${s.label_id}">지우기</button></td></tr>`).join('')}</tbody></table>` : '<p class="small muted">아직 없습니다. 라벨 탭에서 사전이 모르는 표기에 개념을 붙이면 “동의어로 배우기”를 권합니다.</p>'}</div>
      <div class="card"><h2>부정 사례 ${L.negatives.length}개</h2><p class="sub">거절한 사전 라벨입니다. 사전 라벨링이 같은 문맥(앞이나 뒤 낱말이 같을 때)에서 이 표기에 그 개념을 다시 붙이지 않습니다.</p>
        ${L.negatives.length ? `<table><thead><tr><th>표기 → 개념</th><th>문맥</th><th>범위</th><th></th></tr></thead><tbody>${L.negatives.map(e => `<tr><td><b>${esc(e.surface)}</b> → ${esc(e.concept||e.label_type)}</td>
          <td class="small" style="overflow-wrap:anywhere">${esc((e.context||'').slice(0,90))}<div class="muted">${esc(e.file_name||'')}</div></td>
          <td><select class="inp" data-negscope="${e.ex_id}" style="height:26px"><option value="context" ${e.value.scope!=='everywhere'?'selected':''}>같은 문맥</option><option value="everywhere" ${e.value.scope==='everywhere'?'selected':''}>어디서나</option></select></td>
          <td><div class="tools">${tog('ex', e.ex_id, e.enabled)}<button class="btn sm bad" data-del-ex="${e.ex_id}">지우기</button></div></td></tr>`).join('')}</tbody></table>` : '<p class="small muted">아직 없습니다.</p>'}</div>
      <div class="card"><h2>라벨 사례 ${L.examples.length}개</h2><p class="sub">사람이 붙이거나 고친 라벨입니다. AI 라벨을 돌릴 때 관련 높은 것 최대 8개를 프롬프트 끝에 붙입니다. <b>기밀</b> 자료의 사례는 CoA 규칙에 따라 로트·공급처·시료번호를 [가림]으로 바꾸거나(가림) 아예 보내지 않습니다(보내지 않기).</p>
        ${L.examples.length ? `<table><thead><tr><th>표기 → 라벨</th><th>문맥</th><th>등급</th><th></th></tr></thead><tbody>${L.examples.map(e => `<tr><td><b>${esc(e.surface)}</b> → ${LT_KO[e.label_type]||e.label_type}${e.concept?` · ${esc(e.concept)}`:''}${e.value.value?`<div class="mono small">${esc([e.value.target,e.value.value,e.value.unit,e.value.basis].filter(Boolean).join(' '))}</div>`:''}<div class="small muted">${esc(e.note||'')}</div></td>
          <td class="small" style="overflow-wrap:anywhere">${esc((e.context||'').slice(0,90))}<div class="muted">${esc(e.file_name||'')}</div></td>
          <td><span class="pill ${e.confidentiality==='기밀'?'bad':''}">${esc(e.confidentiality)}</span></td>
          <td><div class="tools">${tog('ex', e.ex_id, e.enabled)}<button class="btn sm bad" data-del-ex="${e.ex_id}">지우기</button></div></td></tr>`).join('')}</tbody></table>` : '<p class="small muted">아직 없습니다.</p>'}</div>`;
    const again = () => renderLearned();
    p.querySelectorAll('[data-tog]').forEach(x => x.onchange = async () => {
      try { if (x.dataset.tog === 'rule') await api(`/api/wb/rules/${x.dataset.id}`, {method:'PATCH', body:{enabled: x.checked}});
        else await api(`/api/wb/examples/${x.dataset.id}`, {method:'PATCH', body:{enabled: x.checked}});
        toast(x.checked ? '켰습니다' : '껐습니다 — 이제 쓰이지 않습니다') } catch(e){ fail(e); x.checked = !x.checked }
    });
    p.querySelectorAll('[data-negscope]').forEach(x => x.onchange = async () => { try { await api(`/api/wb/examples/${x.dataset.negscope}`, {method:'PATCH', body:{scope: x.value}}); toast('범위를 바꿨습니다') } catch(e){ fail(e) } });
    p.querySelectorAll('[data-del-rule]').forEach(b => b.onclick = async () => { if (!confirm('이 규칙을 지울까요? 이미 적용한 변경은 그대로 남습니다.')) return;
      try { await api(`/api/wb/rules/${b.dataset.delRule}`, {method:'DELETE'}); toast('지웠습니다'); again() } catch(e){ fail(e) } });
    p.querySelectorAll('[data-edit-rule]').forEach(b => b.onclick = async () => {
      const r = L.rules.find(x => x.rule_id === b.dataset.editRule);
      const body = {};
      if (r.pattern != null){ const pat = prompt('줄 모양(정규식)', r.pattern); if (pat == null) return; body.pattern = pat }
      else { const pj = prompt('값(JSON)', JSON.stringify(r.params)); if (pj == null) return; try { body.params = JSON.parse(pj) } catch { return toast('값은 JSON이어야 합니다. 예: {"min_len":120}') } }
      try { await api(`/api/wb/rules/${r.rule_id}`, {method:'PATCH', body}); toast('고쳤습니다'); again() } catch(e){ fail(e) }
    });
    p.querySelectorAll('[data-del-syn]').forEach(b => b.onclick = async () => { if (!confirm('이 동의어를 지울까요? 사전 라벨·검색이 더는 이 표기를 찾지 않습니다.')) return;
      try { await api(`/api/wb/synonyms/${b.dataset.delSyn}`, {method:'DELETE'}); toast('지웠습니다'); again() } catch(e){ fail(e) } });
    p.querySelectorAll('[data-del-ex]').forEach(b => b.onclick = async () => { if (!confirm('이 사례를 지울까요?')) return;
      try { await api(`/api/wb/examples/${b.dataset.delEx}`, {method:'DELETE'}); toast('지웠습니다'); again() } catch(e){ fail(e) } });
    const go = p.querySelector('#nrGo');
    if (go) go.onclick = async () => {
      let params = {}; const raw = p.querySelector('#nrParams').value.trim();
      if (raw){ try { params = JSON.parse(raw) } catch { return toast('값은 JSON이어야 합니다. 예: {"min_len":120}') } }
      const sc = (S.doc?.scopes || [{type:'global', value:null}])[+p.querySelector('#nrScope').value];
      try { await api('/api/wb/rules', {method:'POST', body:{kind: p.querySelector('#nrKind').value, pattern: p.querySelector('#nrPat').value || null, params, scope:{type: sc.type, value: sc.value}}});
        toast('규칙을 만들었습니다'); again() } catch(e){ fail(e) }
    };
  }

  // ------------------------------------------------------------ 단축키 (라벨 탭, 입력칸 밖에서만)
  function onKey(e){
    if (!visible() || S.tab !== 'labels' || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    if (!$('#wbPop').hidden){ if (e.key === 'Escape') hidePop(); return }
    const k = e.key.toLowerCase(), a = (S.lab.list || [])[S.lab.idx];
    if (k === 'j' || e.key === 'ArrowDown'){ focusLabel(S.lab.idx + 1); e.preventDefault() }
    else if (k === 'k' || e.key === 'ArrowUp'){ focusLabel(S.lab.idx - 1); e.preventDefault() }
    else if (k === 'a' && a && (a.status === 'pending' || a.status === 'auto')){ act(a, 'accepted'); e.preventDefault() }
    else if (k === 'r' && a && a.status !== 'rejected'){ act(a, 'rejected'); e.preventDefault() }
    else if (k === 'e' && a){ act(a, 'edit'); e.preventDefault() }
    else if (k === 'l'){ labelSelection(); e.preventDefault() }
    else if (e.key === '['){ stepChunk(-1); e.preventDefault() }
    else if (e.key === ']'){ stepChunk(1); e.preventDefault() }
  }
  document.addEventListener('keydown', onKey);

  frame();
  open(opts.docId, {chunkId: opts.chunkId, tab: opts.tab});
  return {
    open, setTab,
    close(){ hidePop(); clearTimeout(S.runTimer) },
    destroy(){ document.removeEventListener('keydown', onKey); clearTimeout(S.runTimer); el.innerHTML = '' },
    get state(){ return S },
  };
}
