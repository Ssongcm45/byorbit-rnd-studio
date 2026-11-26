// kordoc 다리용 Node 모듈 고리(module.register) — kordoc이 부르는 pdfjs를 얇은 껍데기(kordoc_pdfjs_shim.mjs)로 바꿔
// getDocument에 cMap·표준 글꼴 위치를 넣어 준다(kordoc은 이 설정 없이 불러서 한글 CID 글꼴 PDF를 못 읽는다).
// 껍데기는 진짜 pdfjs를 'kordoc-real-pdfjs'라는 이름으로 다시 불러 모든 것을 그대로 내보낸다.
const SPEC = 'pdfjs-dist/legacy/build/pdf.mjs';
const SHIM = new URL('./kordoc_pdfjs_shim.mjs', import.meta.url).href;
let real = null;

export async function resolve(specifier, context, next) {
  if (specifier === SPEC && context.parentURL !== SHIM) {
    const r = await next(specifier, context);
    real = r.url;
    return {url: SHIM, shortCircuit: true};
  }
  if (specifier === 'kordoc-real-pdfjs') {
    if (!real) throw new Error('pdfjs-dist 위치를 아직 모릅니다');
    return {url: real, shortCircuit: true};
  }
  return next(specifier, context);
}
