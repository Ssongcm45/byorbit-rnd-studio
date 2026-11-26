// pdfjs 껍데기 — 진짜 pdfjs의 모든 것을 그대로 내보내되, getDocument에만 cMap·표준 글꼴 설정을 더한다.
// 설정은 kordoc_bridge.mjs가 환경 변수 BYORBIT_PDFJS_OPTS(JSON: cMapUrl, cMapPacked, standardFontDataUrl)로 준다.
// 호출한 쪽이 같은 이름의 설정을 주면 그쪽을 따른다.
export * from 'kordoc-real-pdfjs';
import {getDocument as realGetDocument} from 'kordoc-real-pdfjs';

let extra = {};
try { extra = JSON.parse(process.env.BYORBIT_PDFJS_OPTS || '{}') } catch { extra = {} }

export function getDocument(src) {
  if (src && typeof src === 'object' && !(src instanceof Uint8Array) && !(src instanceof URL)) return realGetDocument({...extra, ...src});
  return realGetDocument(src);
}
