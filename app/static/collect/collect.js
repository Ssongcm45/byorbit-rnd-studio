// 자료 수집 화면 — 공식 API·크롤러로 찾고 → 수집함에서 검토 → 자료함에 넣는다.
// 서버: /api/collect (app/routes_collect.py). 출처는 서버 registry가 알려 주는 대로 그린다(새 출처는 자동으로 나타남).
import {esc, fmt, h, makeApi} from '../viz/common.js';

const BASE = '/api/collect';
const GROUPS = ['해외 학술', '국내 학술', '국가 R&D·특허', '공공데이터', '크롤러'];
const STATUS = [['new', '새 항목'], ['accepted', '보관(나중에)'], ['rejected', '거절'], ['ingested', '자료함에 넣음']];
const TYPE_LABEL = {article: '논문', report: '보고서', patent: '특허', project: '과제', dataset: '데이터', thesis: '학위논문', web: '웹', other: '기타'};
const INTERVALS = [[6, '6시간'], [12, '12시간'], [24, '하루'], [72, '3일'], [168, '1주']];
const POLL_MS = 900;
let uid = 0;

function ensureCss(href) {
  const abs = new URL(href, import.meta.url).href;
  if ([...document.querySelectorAll('link[rel=stylesheet]')].some(l => l.href === abs)) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet'; l.href = abs;
  document.head.appendChild(l);
}

const localTime = s => {
  if (!s) return '-';
  const d = new Date(s.replace(' ', 'T') + (/[zZ+]/.test(s.slice(10)) ? '' : 'Z'));
  return isNaN(d) ? s : d.toLocaleString('ko-KR', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'});
};

/** mountCollect(el, {api, toast, project}) → {refresh(), setProject(p), dispose()}
 *  api: 호스트 화면의 api(path, opt) 함수(없으면 같은 주소로 fetch). project: 문자열 또는 () => 문자열. */
export function mountCollect(el, opts = {}) {
  ensureCss('../viz/viz.css');
  ensureCss('./collect.css');
  const {json} = makeApi(opts.api);
  const id = 'co' + (++uid);
  const st = {sources: [], groups: GROUPS, chosen: null, status: 'new', page: 1, filters: {q: '', source: '', doc_type: '', oa: false},
    items: [], counts: {}, total: 0, pages: 1, sel: new Set(), job: null, timers: new Set(), disposed: false,
    project: opts.project, queries: [], sched: null, sites: null, sitesErr: null, backends: null, last: null};
  const project = () => (typeof st.project === 'function' ? st.project() : st.project) || '';
  const inBv = !!el.closest('.bv');

  const root = h(`<section class="co" aria-labelledby="${id}-t">
    <div class="wrap" style="padding-top:0">
      <div class="info co-notice"><b>외부로 나가는 것: 검색어(와 API 키)만.</b> 자료함·CoA·시료·실험 데이터는 보내지 않습니다. 원문 PDF는 오픈 액세스일 때만 받습니다.</div>
      <div class="card co-top">
        <div><h2 id="${id}-t">자료 찾기</h2>
          <p class="sub">공식 API와 크롤러에서 찾은 결과는 바로 자료함에 들어가지 않고 <b>수집함</b>에 모입니다. 검토한 뒤 자료함에 넣으세요. 같은 자료는 DOI·출처 ID·제목으로 하나로 합칩니다.</p></div>
        <form class="co-search" autocomplete="off">
          <input class="inp co-q" type="search" placeholder="예: apple pomace drying, 사과박 식이섬유" aria-label="검색어" required>
          <label class="small muted">발행 연도 <input class="inp n co-since" type="number" min="1900" max="2100" placeholder="전체" aria-label="이 연도 이후"> 이후</label>
          <label class="small muted">출처당 <select class="inp co-limit" aria-label="출처당 건수"><option>10</option><option selected>20</option><option>50</option><option>100</option></select>건</label>
          <button class="btn primary co-go" type="submit">검색</button>
          <button class="btn co-save" type="button" title="이 검색어·출처를 저장해 다시 쓰거나 자동으로 돌립니다">검색 저장</button>
        </form>
        <div class="co-groups" aria-label="출처"></div>
        <div class="co-prog" aria-live="polite" hidden></div>
      </div>
      <div class="co-main">
        <div class="card co-inbox">
          <div class="row"><h2 class="grow">수집함</h2><button class="btn sm co-reload" type="button">새로 고침</button></div>
          <p class="sub">제목을 누르면 원문 페이지가 새 창으로 열립니다. '자료함에 넣기'는 오픈 액세스 PDF가 있으면 원문을, 없으면 서지·초록을 넣습니다.</p>
          <div class="co-tabs" role="group" aria-label="상태"></div>
          <div class="co-filters">
            <input class="inp co-fq" type="search" placeholder="수집함 안에서 찾기" aria-label="수집함 안에서 찾기">
            <select class="inp co-fsrc" aria-label="출처"><option value="">모든 출처</option></select>
            <select class="inp co-ftype" aria-label="종류"><option value="">모든 종류</option>${Object.entries(TYPE_LABEL).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
            <label class="small co-switch"><input type="checkbox" class="co-foa"> 오픈 액세스만</label>
          </div>
          <div class="co-bulk">
            <label class="co-switch"><input type="checkbox" class="co-all" aria-label="이 쪽 전체 선택"> 전체</label>
            <span class="sel">선택 0건</span>
            <button class="btn sm primary" type="button" data-bulk="ingest" disabled>자료함에 넣기</button>
            <button class="btn sm" type="button" data-bulk="later" disabled>나중에</button>
            <button class="btn sm" type="button" data-bulk="reject" disabled>거절</button>
            <button class="btn sm" type="button" data-bulk="new" disabled hidden>새 항목으로</button>
            <label class="small muted" style="margin-left:auto">보안 등급 <select class="inp co-conf" style="height:26px"><option selected>일반</option><option>내부</option><option>기밀</option></select></label>
          </div>
          <div class="co-list" aria-live="polite"></div>
          <div class="co-pages"></div>
        </div>
        <div class="co-side">
          <div class="card co-queries"><div class="row"><h2 class="grow">저장 검색</h2>
            <label class="small co-switch" title="모든 자동 검색을 잠시 멈춥니다"><input type="checkbox" class="co-pause"> 자동 실행 멈춤</label></div>
            <p class="sub">자동으로 켠 검색은 앱이 켜져 있는 동안 정한 간격마다 돌고, 새 결과는 수집함에 쌓입니다.</p>
            <div class="co-q-list"></div></div>
          <div class="card co-crawl"><div class="row"><h2 class="grow">크롤러 사이트</h2><button class="btn sm co-addsite" type="button">사이트 추가</button></div>
            <p class="sub">API가 없는 공개 자료 페이지를 훑습니다. robots.txt와 이용약관을 지키고, 막힌 곳은 자동으로 뺍니다.</p>
            <div class="co-sites"></div></div>
          <div class="card"><h2>최근 수집 기록</h2><div class="co-jobs"></div></div>
        </div>
      </div>
    </div>
  </section>`);
  const shell = inBv ? root : h('<div class="bv"></div>');
  if (!inBv) shell.appendChild(root);
  const toastEl = h('<div class="co-toast" role="status"></div>');
  shell.appendChild(toastEl);
  el.appendChild(shell);
  const $ = s => root.querySelector(s);
  const toast = m => {
    if (typeof opts.toast === 'function') return opts.toast(m);
    toastEl.textContent = m; toastEl.classList.add('on');
    clearTimeout(toastEl._h); toastEl._h = setTimeout(() => toastEl.classList.remove('on'), 3200);
  };
  const later = (fn, ms) => { const t = setTimeout(() => { st.timers.delete(t); if (!st.disposed) fn() }, ms); st.timers.add(t); return t };
  const srcName = k => st.sources.find(s => s.key === k)?.name || k;

  // ---------------------------------------------------------------- 출처
  async function loadSources() {
    try {
      const r = await json(`${BASE}/sources`);
      st.sources = r.sources; st.groups = r.groups?.length ? r.groups : GROUPS;
      if (!st.chosen) st.chosen = new Set(r.sources.filter(s => s.ready && s.group === '해외 학술').map(s => s.key));
      renderSources(); renderSourceFilter();
    } catch (e) { $('.co-groups').innerHTML = `<p class="err">출처 목록을 불러오지 못했습니다: ${esc(e.message)}. 앱이 켜져 있는지 확인하고 새로 고치세요.</p>` }
  }

  function renderSources() {
    const box = $('.co-groups');
    box.innerHTML = '';
    for (const g of st.groups) {
      const list = st.sources.filter(s => (s.group || '기타') === g);
      const ready = list.filter(s => s.ready);
      const on = ready.filter(s => st.chosen.has(s.key)).length;
      const gid = `${id}-g${st.groups.indexOf(g)}`;
      const card = h(`<div class="co-group" role="group" aria-labelledby="${gid}">
        <div class="gh" id="${gid}"><label class="co-switch"><input type="checkbox" class="co-gall"${ready.length ? '' : ' disabled'}${ready.length && on === ready.length ? ' checked' : ''}> ${esc(g)}</label>
          <span class="cnt">${ready.length ? `${on}/${ready.length}` : ''}</span></div></div>`);
      const all = card.querySelector('.co-gall');
      all.indeterminate = on > 0 && on < ready.length;
      all.addEventListener('change', () => { for (const s of ready) all.checked ? st.chosen.add(s.key) : st.chosen.delete(s.key); renderSources() });
      if (!list.length) card.appendChild(h(`<div class="none">${g === '크롤러' ? '크롤러 준비 중' : '아직 연결된 출처가 없습니다'}</div>`));
      for (const s of list) {
        // 키가 없는 출처는 짧게 '키 필요: 변수'만 보이고, 긴 발급 안내는 접어 둔다(카드가 넘치지 않게)
        const hint = s.ready ? (s.description || '') :
          (s.missing_env?.length ? `키 필요: ${s.missing_env.join(', ')}` : (s.message || '사용할 준비가 되지 않았습니다'));
        const help = !s.ready && s.key_help ? `<details class="co-keyhelp"><summary>키 발급 안내</summary><small>${esc(s.key_help)}</small></details>` : '';
        const row = h(`<label class="co-src${s.ready ? '' : ' off'}" title="${esc(s.ready ? (s.homepage || '') : (s.message || ''))}">
          <input type="checkbox" value="${esc(s.key)}"${s.ready ? '' : ' disabled'}${s.ready && st.chosen.has(s.key) ? ' checked' : ''}>
          <span><span class="nm">${esc(s.name)}</span>${hint ? `<small class="${s.ready ? '' : 'key'}">${esc(hint)}</small>` : ''}${help}</span></label>`);
        row.querySelector('input').addEventListener('change', e => { e.target.checked ? st.chosen.add(s.key) : st.chosen.delete(s.key); renderSources() });
        card.appendChild(row);
      }
      box.appendChild(card);
    }
  }

  function renderSourceFilter() {
    const sel = $('.co-fsrc'), cur = sel.value;
    sel.innerHTML = '<option value="">모든 출처</option>' + st.sources.map(s => `<option value="${esc(s.key)}">${esc(s.name)}</option>`).join('');
    sel.value = cur;
  }

  // ---------------------------------------------------------------- 검색·진행
  function currentSearch() {
    const since = Number($('.co-since').value) || null;
    return {query: $('.co-q').value.trim(), sources: [...(st.chosen || [])], limit_per_source: Number($('.co-limit').value), since_year: since};
  }

  $('.co-search').addEventListener('submit', async e => {
    e.preventDefault();
    const body = currentSearch();
    if (!body.query) return toast('검색어를 입력하세요.');
    if (!body.sources.length) return toast('출처를 하나 이상 고르세요.');
    $('.co-go').disabled = true;
    try {
      const j = await json(`${BASE}/search`, {method: 'POST', body: {...body, project: project()}});
      watchJob(j);
    } catch (err) { toast('검색을 시작하지 못했습니다: ' + err.message); $('.co-go').disabled = false }
  });

  function watchJob(j) {
    st.job = j; renderProgress();
    if (j.status !== 'running') { $('.co-go').disabled = false; return onJobDone(j) }
    later(async () => {
      try { watchJob(await json(`${BASE}/jobs/${j.job_id}`)) } catch (e) { toast('진행 상황을 읽지 못했습니다: ' + e.message); $('.co-go').disabled = false }
    }, POLL_MS);
  }

  function renderProgress() {
    const j = st.job, box = $('.co-prog');
    if (!j) { box.hidden = true; return }
    box.hidden = false;
    const per = j.stats?.sources || {};
    const keys = Object.keys(per).length ? Object.keys(per) : (j.sources || []);
    const tot = j.stats?.total;
    box.innerHTML = `<div class="small"><b>"${esc(j.query || '')}"</b> ${j.status === 'running' ? '검색 중…' : '검색 끝'}${tot ? ` — 찾음 ${fmt(tot.found, 0)} · 새 항목 ${fmt(tot.new, 0)} · 이미 있음 ${fmt(tot.dup, 0)}${tot.errors ? ` · 실패 ${tot.errors}곳` : ''}` : ''}</div>` +
      keys.map(k => {
        const s = per[k] || {status: 'running'};
        const pill = s.status === 'done' ? '<span class="pill ok">완료</span>' : s.status === 'error' ? '<span class="pill bad">실패</span>' :
          '<span class="pill warn"><span class="spin" aria-hidden="true">◐</span> 찾는 중</span>';
        return `<div class="pr"><b>${esc(srcName(k))}</b>${pill}<span class="nums">${s.status === 'done' ? `찾음 ${fmt(s.found, 0)} · 새 ${fmt(s.new, 0)} · 중복 ${fmt(s.dup, 0)}` : ''}</span>${s.error ? `<span class="e">${esc(s.error)}</span>` : ''}</div>`;
      }).join('');
  }

  function onJobDone(j) {
    const t = j.stats?.total;
    if (j.kind === 'ingest') {
      toast(`자료함에 ${j.stats?.done ?? 0}건 넣음${j.stats?.failed ? ` · 실패 ${j.stats.failed}건` : ''}`);
    } else if (t) toast(`새 항목 ${t.new}건${t.dup ? ` · 이미 있던 ${t.dup}건은 합쳤습니다` : ''}${t.errors ? ` · ${t.errors}곳 실패(아래 이유 참고)` : ''}`);
    st.status === 'new' || j.kind === 'ingest' ? loadItems() : setStatus('new');
    loadJobs(); loadQueries();
  }

  // ---------------------------------------------------------------- 수집함
  function renderTabs() {
    $('.co-tabs').innerHTML = STATUS.map(([k, v]) => `<button type="button" data-st="${k}" aria-pressed="${st.status === k}">${v}<b>${fmt(st.counts[k] || 0, 0)}</b></button>`).join('');
    for (const b of root.querySelectorAll('.co-tabs button')) b.addEventListener('click', () => setStatus(b.dataset.st));
    const show = {new: ['ingest', 'later', 'reject'], accepted: ['ingest', 'reject', 'new'], rejected: ['ingest', 'new'], ingested: []}[st.status] || [];
    for (const b of root.querySelectorAll('[data-bulk]')) b.hidden = !show.includes(b.dataset.bulk);
    root.querySelector('.co-bulk').hidden = !show.length;
  }
  function setStatus(s) { st.status = s; st.page = 1; st.sel.clear(); loadItems() }

  async function loadItems() {
    const f = st.filters;
    const q = new URLSearchParams({status: st.status, page: st.page, q: f.q, source: f.source, doc_type: f.doc_type, oa: f.oa ? 'true' : 'false'});
    try {
      const r = await json(`${BASE}/items?${q}`);
      if (st.disposed) return;
      Object.assign(st, {items: r.items, counts: r.counts, total: r.total, pages: r.pages});
      for (const iid of [...st.sel]) if (!r.items.some(i => i.item_id === iid)) st.sel.delete(iid);
      renderTabs(); renderItems();
    } catch (e) { $('.co-list').innerHTML = `<p class="err">수집함을 불러오지 못했습니다: ${esc(e.message)}. 새로 고침을 눌러 다시 시도하세요.</p>` }
  }

  function badges(it) {
    const out = [];
    for (const k of it.found_in || [it.source]) out.push(`<span class="pill src" title="찾은 출처">${esc(srcName(k))}</span>`);
    out.push(`<span class="pill type">${esc(TYPE_LABEL[it.doc_type] || it.doc_type || '기타')}</span>`);
    if (it.pdf_url) out.push('<span class="pill oa" title="오픈 액세스 원문 PDF를 받을 수 있습니다">OA · PDF</span>');
    else if (it.extra?.fulltext_xml) out.push('<span class="pill oa" title="오픈 액세스 본문 전체를 글로 넣습니다">OA · 전문</span>');
    else if (it.oa) out.push('<span class="pill oa">오픈 액세스</span>');
    else out.push('<span class="pill off" title="원문은 유료이거나 확인되지 않았습니다. 넣으면 서지·초록만 들어갑니다">서지·초록</span>');
    if (it.license) out.push(`<span class="pill off" title="라이선스">${esc(String(it.license).replace(/^https?:\/\/(www\.)?/, '').slice(0, 40))}</span>`);
    if (it.doi) out.push(`<a href="https://doi.org/${encodeURI(it.doi)}" target="_blank" rel="noopener noreferrer">doi:${esc(it.doi)}</a>`);
    return out.join('');
  }

  function renderItems() {
    const box = $('.co-list');
    if (!st.items.length) {
      const msg = st.status === 'new' ? '새 항목이 없습니다. 위에서 검색어를 넣고 출처를 골라 검색하세요.' :
        st.status === 'accepted' ? "보관한 항목이 없습니다. 새 항목에서 '나중에'를 누르면 여기에 모입니다." :
        st.status === 'rejected' ? '거절한 항목이 없습니다.' : "아직 자료함에 넣은 항목이 없습니다. 새 항목에서 '자료함에 넣기'를 누르세요.";
      box.innerHTML = `<div class="empty">${(st.filters.q || st.filters.source || st.filters.doc_type || st.filters.oa) ? '조건에 맞는 항목이 없습니다. 필터를 풀어 보세요.' : msg}</div>`;
    } else {
      box.innerHTML = '';
      for (const it of st.items) box.appendChild(itemCard(it));
    }
    const pg = $('.co-pages');
    pg.innerHTML = st.pages > 1 ? `<button class="btn sm" type="button" data-p="-1"${st.page <= 1 ? ' disabled' : ''}>이전</button>
      <span>${fmt(st.page, 0)} / ${fmt(st.pages, 0)}쪽 · ${fmt(st.total, 0)}건</span>
      <button class="btn sm" type="button" data-p="1"${st.page >= st.pages ? ' disabled' : ''}>다음</button>` : (st.total ? `<span class="muted">${fmt(st.total, 0)}건</span>` : '');
    for (const b of pg.querySelectorAll('[data-p]')) b.addEventListener('click', () => { st.page += Number(b.dataset.p); loadItems() });
    renderBulk();
  }

  function itemCard(it) {
    const authors = (it.authors || []);
    const meta = [authors.slice(0, 4).join(', ') + (authors.length > 4 ? ` 외 ${authors.length - 4}명` : ''), it.venue, it.year].filter(Boolean).map(esc).join(' · ');
    const ing = it.status === 'ingested';
    const card = h(`<article class="co-item${st.sel.has(it.item_id) ? ' chk' : ''}${ing ? ' done' : ''}">
      <input type="checkbox" aria-label="선택"${st.sel.has(it.item_id) ? ' checked' : ''}${ing ? ' disabled' : ''}>
      <div>
        ${it.url ? `<a class="t" href="${esc(it.url)}" target="_blank" rel="noopener noreferrer">${esc(it.title)}</a>` : `<span class="t">${esc(it.title)}</span>`}
        <div class="m">${meta || '저자·발행 정보 없음'}</div>
        <div class="b">${badges(it)}</div>
        ${it.abstract ? `<details><summary>초록 보기</summary><p>${esc(it.abstract)}</p></details>` : '<div class="m">초록 없음 — 원문 페이지에서 확인하세요.</div>'}
        <div class="acts">${ing ? `<span class="pill ok">자료함에 있음</span>` : `
          <button class="btn sm primary" type="button" data-a="ingest">자료함에 넣기</button>
          ${it.status !== 'rejected' ? '<button class="btn sm" type="button" data-a="reject">거절</button>' : '<button class="btn sm" type="button" data-a="new">되살리기</button>'}
          ${it.status === 'new' ? '<button class="btn sm" type="button" data-a="later">나중에</button>' : ''}`}</div>
      </div></article>`);
    card.querySelector('input').addEventListener('change', e => {
      e.target.checked ? st.sel.add(it.item_id) : st.sel.delete(it.item_id);
      card.classList.toggle('chk', e.target.checked); renderBulk();
    });
    for (const b of card.querySelectorAll('[data-a]')) b.addEventListener('click', () => act(it, b.dataset.a, b));
    return card;
  }

  async function act(it, a, btn) {
    btn.disabled = true;
    try {
      if (a === 'ingest') {
        btn.textContent = it.pdf_url ? '원문 받는 중…' : '넣는 중…';
        const r = await json(`${BASE}/items/${it.item_id}/ingest`, {method: 'POST', body: {project: project(), confidentiality: $('.co-conf').value}});
        toast(r.message + (r.error ? ` (처리 오류: ${r.error})` : ''));
      } else {
        const status = {reject: 'rejected', later: 'accepted', new: 'new'}[a];
        await json(`${BASE}/items/${it.item_id}/status`, {method: 'POST', body: {status}});
        toast({reject: '거절했습니다.', later: "보관했습니다. '보관(나중에)'에서 다시 볼 수 있습니다.", new: '새 항목으로 되돌렸습니다.'}[a]);
      }
      st.sel.delete(it.item_id);
      loadItems();
    } catch (e) { toast('실패: ' + e.message); btn.disabled = false }
  }

  function renderBulk() {
    const n = st.sel.size;
    $('.co-bulk .sel').textContent = `선택 ${fmt(n, 0)}건`;
    for (const b of root.querySelectorAll('[data-bulk]')) b.disabled = !n;
    const selectable = st.items.filter(i => i.status !== 'ingested');
    const all = $('.co-all');
    all.checked = !!selectable.length && selectable.every(i => st.sel.has(i.item_id));
    all.indeterminate = n > 0 && !all.checked;
    all.disabled = !selectable.length;
  }

  $('.co-all').addEventListener('change', e => {
    for (const i of st.items) if (i.status !== 'ingested') e.target.checked ? st.sel.add(i.item_id) : st.sel.delete(i.item_id);
    renderItems();
  });
  for (const b of root.querySelectorAll('[data-bulk]')) b.addEventListener('click', async () => {
    const ids = [...st.sel], action = b.dataset.bulk;
    if (!ids.length) return;
    b.disabled = true;
    try {
      const r = await json(`${BASE}/items/bulk`, {method: 'POST', body: {ids, action, project: project(), confidentiality: $('.co-conf').value}});
      st.sel.clear();
      if (r.background) { toast(`${ids.length}건을 자료함에 넣는 중입니다…`); watchJob(r) } else {
        toast(`${r.done}건 처리${r.failed ? ` · 실패 ${r.failed}건: ${r.errors[0]?.error || ''}` : ''}`); loadItems();
      }
    } catch (e) { toast('실패: ' + e.message) } finally { b.disabled = false }
  });

  let ftimer;
  $('.co-fq').addEventListener('input', e => { clearTimeout(ftimer); ftimer = setTimeout(() => { st.filters.q = e.target.value.trim(); st.page = 1; loadItems() }, 250) });
  $('.co-fsrc').addEventListener('change', e => { st.filters.source = e.target.value; st.page = 1; loadItems() });
  $('.co-ftype').addEventListener('change', e => { st.filters.doc_type = e.target.value; st.page = 1; loadItems() });
  $('.co-foa').addEventListener('change', e => { st.filters.oa = e.target.checked; st.page = 1; loadItems() });
  $('.co-reload').addEventListener('click', () => { loadItems(); loadJobs() });

  // ---------------------------------------------------------------- 저장 검색
  async function loadQueries() {
    try {
      const r = await json(`${BASE}/queries`);
      if (st.disposed) return;
      st.queries = r.queries; st.sched = r.scheduler; renderQueries();
    } catch (e) { $('.co-q-list').innerHTML = `<p class="err">저장 검색을 불러오지 못했습니다: ${esc(e.message)}</p>` }
  }

  function renderQueries() {
    $('.co-pause').checked = !!st.sched?.paused;
    const box = $('.co-q-list');
    if (!st.queries.length) { box.innerHTML = "<div class=\"empty\">저장한 검색이 없습니다. 위에서 검색어와 출처를 정한 뒤 '검색 저장'을 누르세요.</div>"; return }
    box.innerHTML = '';
    for (const q of st.queries) {
      const t = q.last_job?.total;
      const el = h(`<div class="co-qi">
        <div class="row"><span class="nm grow">${esc(q.name)}</span>${q.running ? '<span class="pill warn">실행 중</span>' : ''}</div>
        <div class="muted">"${esc(q.query)}" · ${q.sources.map(srcName).map(esc).join(', ')}${q.since_year ? ` · ${q.since_year}년 이후` : ''} · 출처당 ${q.limit_per_source}건</div>
        <div class="muted">마지막 실행 ${esc(localTime(q.last_run_at))}${t ? ` (새 ${t.new}건${t.errors ? `, 실패 ${t.errors}곳` : ''})` : ''}${q.auto && q.next_run_at ? ` · 다음 ${esc(localTime(q.next_run_at))}` : ''}</div>
        <div class="row">
          <label class="co-switch"><input type="checkbox" class="qa"${q.auto ? ' checked' : ''}> 자동</label>
          <select class="inp qi" style="height:26px" aria-label="자동 실행 간격"${q.auto ? '' : ' disabled'}>${INTERVALS.map(([v, l]) => `<option value="${v}"${v === q.interval_h ? ' selected' : ''}>${l}마다</option>`).join('')}${INTERVALS.some(([v]) => v === q.interval_h) ? '' : `<option value="${q.interval_h}" selected>${q.interval_h}시간마다</option>`}</select>
          <span class="grow"></span>
          <button class="btn sm" type="button" data-q="load" title="검색 칸에 불러오기">불러오기</button>
          <button class="btn sm primary" type="button" data-q="run"${q.running ? ' disabled' : ''}>지금 실행</button>
          <button class="btn sm" type="button" data-q="del" aria-label="저장 검색 지우기">지우기</button>
        </div></div>`);
      const upd = async body => {
        try { await json(`${BASE}/queries`, {method: 'POST', body: {query_id: q.query_id, ...body}}); loadQueries() } catch (e) { toast('저장하지 못했습니다: ' + e.message) }
      };
      el.querySelector('.qa').addEventListener('change', e => upd({auto: e.target.checked}));
      el.querySelector('.qi').addEventListener('change', e => upd({interval_h: Number(e.target.value)}));
      el.querySelector('[data-q=load]').addEventListener('click', () => {
        $('.co-q').value = q.query; $('.co-since').value = q.since_year || '';
        $('.co-limit').value = String(q.limit_per_source); if (!$('.co-limit').value) $('.co-limit').value = '20';
        st.chosen = new Set(q.sources); renderSources(); $('.co-q').focus();
      });
      el.querySelector('[data-q=run]').addEventListener('click', async e => {
        e.target.disabled = true;
        try { const j = await json(`${BASE}/queries/${q.query_id}/run`, {method: 'POST'}); toast(`'${q.name}' 실행 중…`); watchJob(j) } catch (err) { toast('실행하지 못했습니다: ' + err.message); e.target.disabled = false }
      });
      el.querySelector('[data-q=del]').addEventListener('click', async () => {
        if (!confirm(`저장 검색 '${q.name}'을 지울까요? 이미 모은 수집함 항목은 남습니다.`)) return;
        try { await json(`${BASE}/queries/${q.query_id}`, {method: 'DELETE'}); toast('지웠습니다.'); loadQueries() } catch (e) { toast('지우지 못했습니다: ' + e.message) }
      });
      box.appendChild(el);
    }
  }

  $('.co-save').addEventListener('click', async () => {
    const s = currentSearch();
    if (!s.query) return toast('저장할 검색어를 먼저 입력하세요.');
    if (!s.sources.length) return toast('출처를 하나 이상 고르세요.');
    const name = prompt('저장 검색 이름', s.query.slice(0, 40));
    if (name === null) return;
    try {
      await json(`${BASE}/queries`, {method: 'POST', body: {...s, name, project: project() || null, auto: false, interval_h: 24}});
      toast("저장했습니다. '자동'을 켜면 앱이 켜져 있는 동안 정한 간격마다 돕니다."); loadQueries();
    } catch (e) { toast('저장하지 못했습니다: ' + e.message) }
  });
  $('.co-pause').addEventListener('change', async e => {
    try { st.sched = await json(`${BASE}/scheduler`, {method: 'POST', body: {paused: e.target.checked}}); toast(e.target.checked ? '자동 실행을 멈췄습니다.' : '자동 실행을 다시 켰습니다.') } catch (err) { toast('바꾸지 못했습니다: ' + err.message) }
  });

  // ---------------------------------------------------------------- 크롤러 사이트 (app.collect.crawler에 위임)
  // 가져오기 방식: direct(이 PC, HTTP) · browser(이 PC, 헤드리스 Chrome) · apify(클라우드, 유료). 규칙(robots·간격·쪽수)은 같다.
  const BACKENDS = [['direct', '기본(HTTP)'], ['browser', '브라우저(Chrome)'], ['apify', 'Apify(클라우드·유료)']];
  const APIFY_NOTICE = 'Apify를 쓰면 사이트 주소와 크롤 설정이 Apify 클라우드로 나가고 크레딧(유료)이 듭니다. 검색어는 보내지 않고, 받은 페이지에서 이 PC가 거릅니다.';
  const notReadyLabel = k => k === 'apify' ? '키 없음' : '미설치';

  async function loadSites() {
    const [sr, br] = await Promise.allSettled([json(`${BASE}/sites`), json(`${BASE}/sites/backends`)]);
    if (sr.status === 'fulfilled') { st.sites = sr.value.sites || []; st.sitesErr = null } else { st.sites = null; st.sitesErr = sr.reason?.message || '' }
    st.backends = br.status === 'fulfilled' ? (br.value.backends || null) : null;
    if (!st.disposed) renderSites();
  }

  const bReady = k => k === 'direct' || !st.backends || !!st.backends[k]?.ready;
  const bMsg = k => st.backends?.[k]?.message || '';

  function backendOptions(cur) {
    return BACKENDS.map(([k, label]) => {
      const ok = bReady(k);
      return `<option value="${k}"${k === cur ? ' selected' : ''}${!ok && k !== cur ? ' disabled' : ''}>${esc(label)}${ok ? '' : ` — ${notReadyLabel(k)}`}</option>`;
    }).join('');
  }

  function backendBadge(k) {
    if (k === 'direct') return '';
    const label = BACKENDS.find(b => b[0] === k)?.[1] || k;
    return bReady(k) ? `<span class="pill type" title="${esc(bMsg(k))}">${esc(label)}</span>` : `<span class="pill warn" title="${esc(bMsg(k))}">${esc(label)} · ${notReadyLabel(k)}</span>`;
  }

  // 방식별 옵션 칸(브라우저: 기다릴 요소·대기, Apify: 안내·비용 상한). prefix는 폼 이름 앞머리.
  function backendFields(k, s = {}) {
    const hint = !bReady(k) ? `<p class="co-bhint">${esc(bMsg(k))}</p>` : '';
    if (k === 'browser') return `${hint}<div class="two"><label>기다릴 요소(CSS, 선택)<input class="inp" name="wait_for" value="${esc(s.wait_for || '')}" placeholder="table tbody tr, #list li"></label>
      <label>대기 상한(ms)<input class="inp" name="wait_ms" type="number" min="0" max="15000" step="500" value="${esc(s.wait_ms ?? '')}" placeholder="8000"></label></div>
      <p class="small muted">이 PC에서 헤드리스 Chrome으로 그린 뒤 읽습니다. http/https 주소만 열고, 이미지·글꼴·영상은 받지 않습니다.</p>`;
    if (k === 'apify') return `${hint}<p class="co-notice">${esc(APIFY_NOTICE)}</p>
      <div class="two"><label>실행 1회 비용 상한(USD)<input class="inp" name="max_charge_usd" type="number" min="0.05" max="5" step="0.05" value="${esc(s.max_charge_usd ?? 0.5)}"></label>
      <label>기다릴 요소(CSS, 선택)<input class="inp" name="wait_for" value="${esc(s.wait_for || '')}" placeholder="table tbody tr"></label></div>`;
    return '<p class="small muted">이 PC에서 HTML을 바로 받습니다(자바스크립트로 그리는 목록은 못 읽음 → 브라우저 방식).</p>';
  }

  function readBackend(form) {
    const g = n => form.querySelector(`[name=${n}]`)?.value?.trim() ?? '';
    const backend = form.querySelector('[name=backend]').value;
    const out = {backend, wait_for: g('wait_for') || null, wait_ms: g('wait_ms') === '' ? null : Number(g('wait_ms'))};
    if (backend === 'apify') out.max_charge_usd = Number(g('max_charge_usd')) || 0.5;
    return out;
  }

  function renderSites() {
    const box = $('.co-sites');
    $('.co-addsite').disabled = !st.sites;
    if (!st.sites) {
      box.innerHTML = `<div class="empty">${/준비 중/.test(st.sitesErr || '') ? '크롤러 준비 중입니다. 공식 API 출처로 먼저 검색하세요.' : `크롤러 사이트를 불러오지 못했습니다: ${esc(st.sitesErr || '')}`}</div>`;
      return;
    }
    if (!st.sites.length) { box.innerHTML = "<div class=\"empty\">등록된 사이트가 없습니다. '사이트 추가'로 공개 자료 페이지를 넣으세요.</div>"; return }
    box.innerHTML = '';
    for (const s of st.sites) {
      const bk = s.backend || 'direct';
      const el = h(`<div class="co-site">
        <div class="row"><span class="nm grow">${esc(s.name || s.id)}</span>${backendBadge(bk)}${s.default ? '<span class="pill off">기본</span>' : '<span class="pill src">내가 추가</span>'}
          ${s.enabled ? '<span class="pill ok">켜짐</span>' : '<span class="pill off">꺼짐</span>'}</div>
        <div class="muted">${esc(s.group || '')}${s.group ? ' · ' : ''}${(s.start_urls || []).slice(0, 2).map(esc).join(', ')}${(s.start_urls || []).length > 2 ? ' …' : ''}</div>
        <div class="muted small co-chk"></div>
        <div class="row">
          <label class="co-switch"><input type="checkbox" class="se"${s.enabled ? ' checked' : ''}> 사용</label><span class="grow"></span>
          <button class="btn sm" type="button" data-s="test" title="최대 3쪽만 훑어 찾은 제목을 보여 줍니다(수집함에 넣지 않음)">시험 수집</button>
          <button class="btn sm" type="button" data-s="check">robots 확인</button>
          <button class="btn sm" type="button" data-s="del">${s.default ? '끄기' : '지우기'}</button>
        </div>
        <details class="co-bk"${bk !== 'direct' ? ' open' : ''}><summary>가져오기 방식: ${esc(BACKENDS.find(b => b[0] === bk)?.[1] || bk)}</summary>
          <form class="co-form co-bform" autocomplete="off">
            <label>방식<select class="inp" name="backend" aria-label="가져오기 방식">${backendOptions(bk)}</select></label>
            <div class="co-bopts">${backendFields(bk, s)}</div>
            <div class="row"><span class="grow"></span><button class="btn sm primary" type="submit">방식 저장</button></div>
          </form></details>
        <div class="co-test" hidden></div></div>`);
      const bform = el.querySelector('.co-bform');
      bform.querySelector('[name=backend]').addEventListener('change', e => { bform.querySelector('.co-bopts').innerHTML = backendFields(e.target.value, s) });
      bform.addEventListener('submit', async e => {
        e.preventDefault();
        const b = readBackend(bform);
        if (!bReady(b.backend)) return toast(`${notReadyLabel(b.backend)}: ${bMsg(b.backend)}`);
        if (b.backend === 'apify' && b.backend !== bk && !confirm(APIFY_NOTICE + '\n\n이 사이트를 Apify 방식으로 바꿀까요?')) return;
        try { await json(`${BASE}/sites`, {method: 'POST', body: {...s, ...b}}); toast('가져오기 방식을 저장했습니다.'); loadSites() } catch (err) { toast('저장하지 못했습니다: ' + err.message) }
      });
      el.querySelector('.se').addEventListener('change', async e => {
        try { await json(`${BASE}/sites`, {method: 'POST', body: {...s, enabled: e.target.checked}}); loadSites() } catch (err) { toast('바꾸지 못했습니다: ' + err.message); e.target.checked = !e.target.checked }
      });
      el.querySelector('[data-s=check]').addEventListener('click', async e => {
        e.target.disabled = true;
        const out = el.querySelector('.co-chk');
        out.textContent = '확인 중…';
        try {
          const r = await json(`${BASE}/sites/${encodeURIComponent(s.id)}/check`, {method: 'POST'});
          out.innerHTML = `${r.robots_ok ? '<span class="pill ok">robots 허용</span>' : '<span class="pill bad">robots 막힘</span>'}${r.backend && r.backend !== 'direct' ? (r.backend_ready ? ' <span class="pill ok">방식 준비됨</span>' : ` <span class="pill warn">${notReadyLabel(r.backend)}</span>`) : ''} ${esc(r.message || '')}${r.terms_url ? ` · <a href="${esc(r.terms_url)}" target="_blank" rel="noopener noreferrer">이용약관</a>` : ''}`;
        } catch (err) { out.textContent = '확인하지 못했습니다: ' + err.message } finally { e.target.disabled = false }
      });
      el.querySelector('[data-s=test]').addEventListener('click', async e => {
        const out = el.querySelector('.co-test');
        if (!bReady(bk)) { out.hidden = false; out.innerHTML = `<p class="co-bhint">${notReadyLabel(bk)} — ${esc(bMsg(bk))}</p>`; return }
        if (bk === 'apify' && !confirm(APIFY_NOTICE + '\n\n시험 수집(최대 3쪽)도 크레딧이 듭니다. 실행할까요?')) return;
        e.target.disabled = true; out.hidden = false;
        out.innerHTML = `<div class="muted">시험 수집 중… (최대 3쪽${bk === 'direct' ? '' : bk === 'browser' ? ', 브라우저라 수십 초 걸릴 수 있음' : ', Apify 실행이라 몇 분 걸릴 수 있음'})</div>`;
        try {
          const q = (root.querySelector('.co-q')?.value || '').trim();
          const r = await json(`${BASE}/sites/${encodeURIComponent(s.id)}/test`, {method: 'POST', body: {query: q, max_pages: 3}});
          const list = (r.items || []).slice(0, 12).map(i => `<li><a href="${esc(i.url || '#')}" target="_blank" rel="noopener noreferrer">${esc(i.title)}</a>${i.date || i.year ? ` <span class="muted">${esc(i.date || i.year)}</span>` : ''}</li>`).join('');
          out.innerHTML = `<div class="row"><b class="grow">시험 수집 ${r.pages}쪽 · ${(r.items || []).length}건${r.query ? ` · "${esc(r.query)}"` : ''}</b><button class="btn sm" type="button" data-t="close">닫기</button></div>
            ${list ? `<ol>${list}</ol>` : '<p class="muted">찾은 항목이 없습니다. 링크 패턴·허용 경로를 확인하거나, 목록이 자바스크립트로 그려지면 브라우저 방식을 고르세요.</p>'}
            ${(r.messages || []).length ? `<details><summary>메시지 ${r.messages.length}개</summary><ul>${r.messages.map(m => `<li>${esc(m)}</li>`).join('')}</ul></details>` : ''}`;
          out.querySelector('[data-t=close]').addEventListener('click', () => { out.hidden = true });
        } catch (err) { out.innerHTML = `<p class="err">시험 수집 실패: ${esc(err.message)}</p>` } finally { e.target.disabled = false }
      });
      el.querySelector('[data-s=del]').addEventListener('click', async () => {
        if (!s.default && !confirm(`사이트 '${s.name}'을 지울까요?`)) return;
        try { await json(`${BASE}/sites/${encodeURIComponent(s.id)}`, {method: 'DELETE'}); toast(s.default ? '기본 사이트는 지우지 않고 껐습니다.' : '지웠습니다.'); loadSites() } catch (e) { toast('실패: ' + e.message) }
      });
      box.appendChild(el);
    }
  }

  $('.co-addsite').addEventListener('click', () => {
    if (root.querySelector('.co-form.co-add')) return root.querySelector('.co-form.co-add [name=name]').focus();
    const groups = st.groups.filter(g => g !== '크롤러');
    const f = h(`<form class="co-form co-add" autocomplete="off">
      <label>이름<input class="inp" name="name" required placeholder="예: 농촌진흥청 연구보고서"></label>
      <label>묶음<select class="inp" name="group">${groups.map(g => `<option>${esc(g)}</option>`).join('')}<option>기타</option></select></label>
      <label>시작 주소(한 줄에 하나)<textarea class="inp" name="start_urls" required placeholder="https://..."></textarea></label>
      <label>허용 주소 접두어(한 줄에 하나, 비우면 시작 주소와 같은 사이트만)<textarea class="inp" name="allow_prefixes"></textarea></label>
      <label>자료 링크 패턴(정규식)<input class="inp" name="link_pattern" placeholder="/board/view\\?id=\\d+" required></label>
      <div class="two"><label>제목 위치(선택)<input class="inp" name="title_hint" placeholder="h1, .title"></label>
        <label>날짜 패턴(선택)<input class="inp" name="date_pattern" placeholder="\\d{4}-\\d{2}-\\d{2}"></label></div>
      <div class="two"><label>PDF 링크 패턴(선택)<input class="inp" name="pdf_pattern" placeholder="\\.pdf$"></label>
        <label>요청 간격(초)<input class="inp" name="interval_s" type="number" min="1" value="5"></label></div>
      <label>가져오기 방식<select class="inp" name="backend">${backendOptions('direct')}</select></label>
      <div class="co-bopts">${backendFields('direct')}</div>
      <div class="row"><label class="co-switch"><input type="checkbox" name="enabled" checked> 바로 사용</label><span class="grow"></span>
        <button class="btn sm" type="button" data-c="cancel">취소</button><button class="btn sm primary" type="submit">추가</button></div>
      <p class="small muted" style="margin:0">추가하면 robots.txt를 확인합니다. 막힌 사이트는 검색에서 빠집니다.</p>
    </form>`);
    const lines = v => v.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
    f.querySelector('[name=backend]').addEventListener('change', e => { f.querySelector('.co-bopts').innerHTML = backendFields(e.target.value) });
    f.querySelector('[data-c=cancel]').addEventListener('click', () => f.remove());
    f.addEventListener('submit', async e => {
      e.preventDefault();
      const d = Object.fromEntries(new FormData(f));
      try { new RegExp(d.link_pattern) } catch { return toast('자료 링크 패턴이 올바른 정규식이 아닙니다. 다시 확인하세요.') }
      const b = readBackend(f);
      if (!bReady(b.backend)) return toast(`${notReadyLabel(b.backend)}: ${bMsg(b.backend)}`);
      if (b.backend === 'apify' && !confirm(APIFY_NOTICE + '\n\n이 사이트를 Apify 방식으로 추가할까요?')) return;
      const site = {name: d.name.trim(), group: d.group, start_urls: lines(d.start_urls), allow_prefixes: lines(d.allow_prefixes),
        link_pattern: d.link_pattern, title_hint: d.title_hint || null, date_pattern: d.date_pattern || null, pdf_pattern: d.pdf_pattern || null,
        interval_s: Number(d.interval_s) || 5, enabled: !!f.querySelector('[name=enabled]').checked, default: false, ...b};
      if (!site.start_urls.every(u => /^https?:\/\//.test(u))) return toast('시작 주소는 http:// 또는 https://로 시작해야 합니다.');
      try {
        const saved = await json(`${BASE}/sites`, {method: 'POST', body: site});
        f.remove(); toast('추가했습니다. robots.txt를 확인합니다…'); await loadSites();
        if (saved?.id) root.querySelector(`.co-site:nth-child(${(st.sites || []).findIndex(s => s.id === saved.id) + 1}) [data-s=check]`)?.click();
      } catch (err) { toast('추가하지 못했습니다: ' + err.message) }
    });
    $('.co-sites').before(f);
    f.querySelector('[name=name]').focus();
  });

  // ---------------------------------------------------------------- 최근 기록
  async function loadJobs() {
    try {
      const r = await json(`${BASE}/jobs?limit=8`);
      const box = $('.co-jobs');
      if (!r.jobs.length) { box.innerHTML = '<div class="muted">아직 수집 기록이 없습니다.</div>'; return }
      box.innerHTML = r.jobs.map(j => {
        const t = j.stats?.total;
        const pill = j.status === 'running' ? '<span class="pill warn">진행 중</span>' : j.status === 'done' ? (t?.errors ? '<span class="pill warn">일부 실패</span>' : '<span class="pill ok">완료</span>') : '<span class="pill bad">실패</span>';
        const what = j.kind === 'ingest' ? `자료함 넣기 ${j.stats?.done ?? 0}/${j.stats?.total ?? 0}건` : `"${esc(j.query || '')}"${t ? ` · 새 ${t.new} · 중복 ${t.dup}` : ''}`;
        return `<div class="j">${pill}<span class="q">${what}</span><span class="muted">${esc(localTime(j.started_at))}${j.query_id ? ' · 저장 검색' : ''}</span></div>`;
      }).join('');
    } catch (e) { $('.co-jobs').innerHTML = `<p class="err">기록을 불러오지 못했습니다: ${esc(e.message)}</p>` }
  }

  async function refresh() {
    await loadSources();
    await Promise.all([loadItems(), loadQueries(), loadSites(), loadJobs()]);
  }
  const ready = refresh();

  return {
    refresh,
    setProject(p) { st.project = p },
    async search(query, sources) {
      await ready;
      if (sources) { st.chosen = new Set(sources.filter(k => st.sources.some(s => s.key === k && s.ready))); renderSources() }
      $('.co-q').value = query; $('.co-search').requestSubmit();
    },
    dispose() { st.disposed = true; for (const t of st.timers) clearTimeout(t); shell.remove() },
  };
}
