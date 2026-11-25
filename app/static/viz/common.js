// 시각화 공용 도우미
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const NS = 'http://www.w3.org/2000/svg';

export const METHOD_COLOR = {
  '동결건조':'var(--m-fd)', '열풍건조':'var(--m-ha)', '진공건조':'var(--m-vd)', '분무건조':'var(--m-sd)', '자연건조':'var(--m-sun)', '미상':'var(--m-unk)'
};

export function reducedMotion(){
  return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** api 옵션: 함수(path, opt) → JSON(호스트 화면의 api)이거나, 문자열(기본 주소)이거나, 없으면 같은 주소로 fetch.
 *  반환: {json(path,opt), text(path)} */
export function makeApi(api){
  const base = typeof api === 'string' ? api.replace(/\/$/, '') : '';
  const json = typeof api === 'function' ? api : async (path, opt={}) => {
    const r = await fetch(base + path, opt.body && !(opt.body instanceof FormData)
      ? {...opt, headers:{'Content-Type':'application/json'}, body:JSON.stringify(opt.body)} : opt);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || r.statusText);
    return j;
  };
  const text = async path => {
    const r = await fetch(base + path);
    const t = await r.text();
    if (!r.ok) { let m = r.statusText; try { m = JSON.parse(t).detail || m } catch {} throw new Error(m) }
    return t;
  };
  return {json, text};
}

export function h(html){
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export function fmt(n, d=2){
  if (n === null || n === undefined || Number.isNaN(n)) return '-';
  return Number(n).toLocaleString('ko-KR', {maximumFractionDigits:d});
}

let _scripts = {};
export function loadScript(url){
  if (!_scripts[url]) _scripts[url] = new Promise((res, rej) => {
    const s = document.createElement('script');
    s.src = url; s.async = true; s.onload = () => res(); s.onerror = () => { delete _scripts[url]; rej(new Error('불러오기 실패: ' + url)) };
    document.head.appendChild(s);
  });
  return _scripts[url];
}

export const vendorUrl = p => new URL('../vendor/' + p, import.meta.url).href;
