// R&D Studio V0.5 — 시각화 작업 공간 (ES 모듈, 빌드 없음)
//   import {mountViz, openStructure} from '/static/viz/viz.js';
//   mountViz(document.querySelector('#vizRoot'), {api, initial:{tab:'flow'|'drying'|'molecule', term, method, project}});
//   openStructure('클로로겐산')  // 다른 화면(측정값·라벨)에서 분자 구조로 바로 가기
import {makeApi} from './common.js';
import {mountFlow} from './flow.js';
import {mountDrying} from './drying.js';
import {mountMolecule} from './molecule.js';

const TABS = [['flow', '흐름'], ['drying', '건조 방식'], ['molecule', '분자 구조']];
let current = null;      // 마운트된 작업 공간
let pendingTerm = null;  // 마운트 전에 openStructure가 불리면 보관

function ensureCss(){
  if (document.querySelector('link[data-bv-css]')) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet'; l.href = new URL('./viz.css', import.meta.url).href; l.dataset.bvCss = '1';
  document.head.appendChild(l);
}

/**
 * 시각화 작업 공간을 el 안에 그린다.
 * @param {HTMLElement} el
 * @param {{api?: Function|string, initial?: {tab?: string, term?: string, method?: string, project?: string}, toast?: Function}} opt
 *   api: 호스트 화면의 api(path, opt) 함수(JSON 반환) 또는 기본 주소 문자열. 없으면 같은 주소로 fetch.
 */
export function mountViz(el, {api, initial = {}, toast} = {}){
  ensureCss();
  const ctx = {api: makeApi(api), project: initial.project || '', toast, initialMethod: initial.method};
  el.classList.add('bv');
  el.innerHTML = `<div class="wrap">
    <div class="tabs" role="tablist" aria-label="시각화">${TABS.map(([k, l]) =>
      `<button role="tab" id="bvTab-${k}" aria-controls="bvPanel-${k}" aria-selected="false" tabindex="-1" data-tab="${k}">${l}</button>`).join('')}</div>
    ${TABS.map(([k]) => `<div role="tabpanel" id="bvPanel-${k}" aria-labelledby="bvTab-${k}" hidden data-panel="${k}"></div>`).join('')}
  </div>`;
  const mounted = {};
  const panel = k => el.querySelector(`[data-panel="${k}"]`);
  function select(k){
    if (!TABS.some(t => t[0] === k)) k = 'flow';
    el.querySelectorAll('[role=tab]').forEach(b => { const on = b.dataset.tab === k; b.setAttribute('aria-selected', on); b.tabIndex = on ? 0 : -1 });
    el.querySelectorAll('[role=tabpanel]').forEach(p => p.hidden = p.dataset.panel !== k);
    if (!mounted[k]) mounted[k] = ({flow: mountFlow, drying: mountDrying, molecule: mountMolecule})[k](panel(k), ctx);
    api_.tab = k;
    return mounted[k];
  }
  el.querySelectorAll('[role=tab]').forEach((b, i, all) => {
    b.onclick = () => select(b.dataset.tab);
    b.onkeydown = ev => {
      const d = ev.key === 'ArrowRight' ? 1 : ev.key === 'ArrowLeft' ? -1 : 0;
      if (d) { const n = all[(i + d + all.length) % all.length]; n.focus(); select(n.dataset.tab) }
    };
  });
  const api_ = {
    tab: null, select,
    openStructure(term){ select('molecule').open(term) },
    openDrying(method){ const d = select('drying'); method && d.pick(method) },
    setProject(p){ ctx.project = p || ''; mounted.flow?.setProject(ctx.project) },
    refresh(){ Object.values(mounted).forEach(m => m.refresh?.()) },
  };
  current = api_;
  const term = pendingTerm || initial.term;
  pendingTerm = null;
  if (term) api_.openStructure(term); else select(initial.tab || 'flow');
  return api_;
}

/** 다른 화면에서 성분 구조로 바로 가기. 호스트는 'byorbit:open-structure' 이벤트를 받아 시각화 화면으로 전환하면 된다. */
export function openStructure(term){
  window.dispatchEvent(new CustomEvent('byorbit:open-structure', {detail: {term}}));
  if (current) current.openStructure(term); else pendingTerm = term;
}
