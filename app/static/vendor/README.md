# 고정 버전 외부 라이브러리 (오프라인 동작용)

CDN을 쓰지 않고 이 폴더의 파일을 그대로 씁니다. 버전을 바꿀 때는 아래 주소의 버전 숫자만 바꿔 다시 받고 이 표를 고칩니다.
받은 날: 2026-11-24

| 파일 | 라이브러리·버전 | 라이선스 | 받은 주소 | SHA-256 |
|---|---|---|---|---|
| `3dmol/3Dmol-min.js` | 3Dmol.js 2.4.2 | BSD-3-Clause (`3dmol/LICENSE`) | https://cdn.jsdelivr.net/npm/3dmol@2.4.2/build/3Dmol-min.js | `06b6d2fc7d418e8bef62a32cca44373ff21b2b787bd377613dd4039394a4e9ff` |
| `3dmol/LICENSE` | | | https://cdn.jsdelivr.net/npm/3dmol@2.4.2/LICENSE | |
| `three/three.module.min.js` | three.js r170 (0.170.0) | MIT (`three/LICENSE`) | https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.min.js | `08fd7545d13d2c7fb65ab691530a802dafefd638596501854f267d0fb13c39e7` |
| `three/OrbitControls.js` | three.js r170 examples | MIT | https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/controls/OrbitControls.js | (수정본 — 아래 참고) |
| `three/LICENSE` | | | https://cdn.jsdelivr.net/npm/three@0.170.0/LICENSE | |

## 수정 사항

- `three/OrbitControls.js`: 빌드 도구·import map 없이 쓰려고 첫 import 문의 `from 'three'`를
  `from './three.module.min.js'`로 한 줄 바꿨습니다. 나머지는 원본 그대로입니다.

## 쓰는 곳

- `app/static/viz/molecule.js` — 3Dmol.js(분자 3D 보기). `<script>`로 필요할 때만 불러옵니다.
- `app/static/viz/drying.js` — three.js + OrbitControls(건조 입자 3D 단면). 필요할 때만 `import()`합니다.
