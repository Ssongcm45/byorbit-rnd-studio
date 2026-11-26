// kordoc 다리 — Python(kordoc_tool.py)이 subprocess로 부른다. 결과를 JSON 한 덩어리로 stdout에 쓴다.
// 사용: node kordoc_bridge.mjs <kordoc dist/index.js 경로> <문서 경로> [옵션 JSON]
//       node kordoc_bridge.mjs <kordoc dist/index.js 경로> --version
// 문서는 이 PC 안에서만 읽는다(네트워크를 쓰지 않는다). 이미지 바이너리는 결과에서 뺀다.
import { pathToFileURL } from 'node:url';
import { createRequire, register } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

const [, , entry, file, optJson] = process.argv;
const MARK = '@@KORDOC_JSON@@';

// pdfjs 등이 console.log로 경고를 찍는다 — 결과 JSON과 섞이지 않게 모두 stderr로 돌린다
const toErr = (...a) => process.stderr.write(a.map(String).join(' ') + '\n');
console.log = console.info = console.warn = console.debug = toErr;

function out(obj) {
  process.stdout.write('\n' + MARK + JSON.stringify(obj) + '\n');
}

function strip(blocks) {
  return (blocks || []).map(b => {
    const { imageData, style, bbox, ...rest } = b;
    if (rest.children) rest.children = strip(rest.children);
    if (imageData) rest.image = { mimeType: imageData.mimeType, filename: imageData.filename || null };
    if (bbox) rest.bbox = bbox;
    return rest;
  });
}

// 한글 CID 글꼴 PDF: kordoc은 pdfjs getDocument에 cMap 설정을 주지 않는다 → pdfjs-dist가 있으면
// 모듈 고리로 getDocument를 감싸 cMapUrl(pdfjs-dist/cmaps/)·cMapPacked·standardFontDataUrl을 넣는다(파일은 이 PC에서만 읽음).
async function wirePdfjs() {
  try {
    const req = createRequire(entry);
    const pkg = req.resolve('pdfjs-dist/package.json');
    const dir = path.dirname(pkg).split(path.sep).join('/');
    const cmaps = dir + '/cmaps/';
    if (!fs.existsSync(cmaps)) return null;
    const fonts = dir + '/standard_fonts/';
    process.env.BYORBIT_PDFJS_OPTS = JSON.stringify({cMapUrl: cmaps, cMapPacked: true,
      ...(fs.existsSync(fonts) ? {standardFontDataUrl: fonts} : {})});
    register('./kordoc_pdfjs_hooks.mjs', import.meta.url);
    return cmaps;
  } catch { return null }   // pdfjs-dist가 없으면 HWP·HWPX만(그대로)
}

try {
  const cmaps = await wirePdfjs();
  if (cmaps) toErr('[kordoc bridge] pdfjs cMap: ' + cmaps);
  const k = await import(pathToFileURL(entry).href);
  if (file === '--version') {
    out({ success: true, version: k.VERSION });
  } else {
    const opt = optJson ? JSON.parse(optJson) : {};
    const po = {};
    if (opt.pages) po.pages = opt.pages;
    if (opt.removeHeaderFooter) po.removeHeaderFooter = true;
    const r = await k.parse(file, po);
    if (!r.success) {
      out({ success: false, error: r.error, code: r.code || null, fileType: r.fileType, version: k.VERSION });
    } else {
      out({
        success: true, version: k.VERSION, fileType: r.fileType, pageCount: r.pageCount ?? null,
        isImageBased: !!r.isImageBased, metadata: r.metadata || {}, warnings: r.warnings || [],
        outline: r.outline || [], blocks: strip(r.blocks),
      });
    }
  }
} catch (e) {
  out({ success: false, error: String(e && e.message || e), code: 'BRIDGE_ERROR' });
}
