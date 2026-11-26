// kordoc 다리 — Python(kordoc_tool.py)이 subprocess로 부른다. 결과를 JSON 한 덩어리로 stdout에 쓴다.
// 사용: node kordoc_bridge.mjs <kordoc dist/index.js 경로> <문서 경로> [옵션 JSON]
//       node kordoc_bridge.mjs <kordoc dist/index.js 경로> --version
// 문서는 이 PC 안에서만 읽는다(네트워크를 쓰지 않는다). 이미지 바이너리는 결과에서 뺀다.
import { pathToFileURL } from 'node:url';

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

try {
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
