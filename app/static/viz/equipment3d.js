// 건조 설비 3D 모델 — three.js 절차적 형상(외부 모델 파일 없음)
//   createEquipment3D(box, lib, {method, variant, parts, getState, onPick, cut, labels})
//     → {select(id), setCut(on), setRotate(on), setLabels(on), resetView(), dispose()}
// 방식마다 빌더 함수 하나(BUILD), 배관·플랜지·프레임·모터·게이지·제어반·트레이 도우미는 공용.
const TAU = Math.PI * 2;
const NS = 'http://www.w3.org/2000/svg';
const rnd = seed => () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const lerp = (a, b, t) => a + (b - a) * t;
const sat = t => t < 0 ? 0 : t > 1 ? 1 : t;
const clamp = (v, a, b) => v < a ? a : v > b ? b : v;
const FONT = '"Malgun Gothic","맑은 고딕",system-ui,sans-serif';

function canvasTex(T3, w, h, draw, color = true){
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  draw(c.getContext('2d'), w, h);
  const t = new T3.CanvasTexture(c);
  t.colorSpace = color ? T3.SRGBColorSpace : T3.NoColorSpace; t.anisotropy = 4;
  return t;
}
const rep = (T3, t, x, y) => { t.wrapS = t.wrapT = T3.RepeatWrapping; t.repeat.set(x, y); return t };

// 반사용 환경(스튜디오 조명 느낌의 그라데이션 + 소프트박스)
function envTexture(T3){
  return canvasTex(T3, 512, 256, (g, w, h) => {
    const gr = g.createLinearGradient(0, 0, 0, h);
    gr.addColorStop(0, '#ffffff'); gr.addColorStop(.42, '#e3e8ee'); gr.addColorStop(.5, '#aab2bb'); gr.addColorStop(.58, '#7d848c'); gr.addColorStop(1, '#4b5056');
    g.fillStyle = gr; g.fillRect(0, 0, w, h);
    g.fillStyle = '#ffffff';
    for (const [x, y, bw, bh] of [[40, 40, 90, 34], [210, 26, 120, 30], [380, 46, 80, 40], [300, 92, 60, 14]]) g.fillRect(x, y, bw, bh);
  });
}

function materials(T3){
  const std = o => new T3.MeshStandardMaterial(o), phys = o => new T3.MeshPhysicalMaterial(o);
  const brushed = rep(T3, canvasTex(T3, 256, 256, (g, w, h) => {
    g.fillStyle = '#c8c8c8'; g.fillRect(0, 0, w, h);
    const r = rnd(5);
    for (let i = 0; i < 900; i++) { const v = 150 + r() * 105 | 0; g.fillStyle = `rgba(${v},${v},${v},.35)`; g.fillRect(r() * w - 40, r() * h, 40 + r() * 160, 1) }
  }, false), 3, 3);
  const perf = rep(T3, canvasTex(T3, 128, 128, (g, w, h) => {
    g.fillStyle = '#d4d8dc'; g.fillRect(0, 0, w, h); g.fillStyle = '#3b4047';
    for (let y = 4; y < h; y += 8) for (let x = (y / 8) % 2 ? 8 : 4; x < w; x += 8) { g.beginPath(); g.arc(x, y, 2.2, 0, TAU); g.fill() }
  }), 8, 8);
  const net = rep(T3, canvasTex(T3, 64, 64, (g, w, h) => {
    g.fillStyle = '#000'; g.fillRect(0, 0, w, h); g.strokeStyle = '#fff'; g.lineWidth = 2;
    for (let i = 0; i <= w; i += 8) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, h); g.stroke(); g.beginPath(); g.moveTo(0, i); g.lineTo(w, i); g.stroke() }
  }, false), 24, 14);
  const fins = rep(T3, canvasTex(T3, 64, 64, (g, w, h) => {
    g.fillStyle = '#5f666e'; g.fillRect(0, 0, w, h); g.fillStyle = '#2b3036';
    for (let x = 0; x < w; x += 4) g.fillRect(x, 0, 1.5, h);
  }), 6, 1);
  const pv = rep(T3, canvasTex(T3, 128, 128, (g, w, h) => {
    g.fillStyle = '#c9d2dc'; g.fillRect(0, 0, w, h);
    for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) { g.fillStyle = '#163a66'; g.fillRect(x * 32 + 2, y * 32 + 2, 28, 28); g.fillStyle = '#2a5c94'; g.fillRect(x * 32 + 2, y * 32 + 15, 28, 1) }
  }), 3, 2);
  const stripe = canvasTex(T3, 64, 64, (g, w, h) => { for (let i = 0; i < 4; i++) { g.fillStyle = i % 2 ? '#f4f4f4' : '#e0571f'; g.fillRect(0, i * 16, w, 16) } });
  return {
    tex: {net},
    steel: std({color: 0xdfe3e8, metalness: .9, roughness: .42, roughnessMap: brushed}),
    steelDark: std({color: 0x8f969e, metalness: .85, roughness: .38}),
    perf: std({map: perf, metalness: .55, roughness: .45, side: T3.DoubleSide}),
    paint: std({color: 0xe8eaed, metalness: .05, roughness: .5}),
    white: std({color: 0xf4f5f6, metalness: 0, roughness: .6}),
    frame: std({color: 0x3c4652, metalness: .35, roughness: .5}),
    motor: std({color: 0x35618f, metalness: .3, roughness: .45}),
    pump: std({color: 0x4f5965, metalness: .35, roughness: .45}),
    dark: std({color: 0x24282e, metalness: .2, roughness: .65}),
    rubber: std({color: 0x121316, roughness: .92}),
    copper: std({color: 0xc47c48, metalness: 1, roughness: .3}),
    insul: std({color: 0x1d2024, roughness: .95}),
    wool: std({color: 0xd8c07a, roughness: 1}),
    clad: std({color: 0xc9ced3, metalness: .7, roughness: .5}),
    glass: phys({color: 0xe8f6ff, roughness: .04, transparent: true, opacity: .14, depthWrite: false, side: T3.DoubleSide, clearcoat: 1}),
    acrylic: phys({color: 0xd9f0ff, roughness: .05, transparent: true, opacity: .2, depthWrite: false, side: T3.DoubleSide, clearcoat: 1}),
    film: phys({color: 0xeef7ff, roughness: .2, transparent: true, opacity: .2, depthWrite: false, side: T3.DoubleSide}),
    heater: std({color: 0x4a3b33, metalness: .6, roughness: .45, emissive: 0xff4510, emissiveIntensity: 0}),
    finHot: std({color: 0xb9bec4, metalness: .8, roughness: .4, emissive: 0xff5a1f, emissiveIntensity: 0}),
    frost: std({color: 0xf6fbff, roughness: .95, transparent: true, opacity: .93}),
    ice: std({color: 0xd6f1ff, roughness: .1, metalness: .1, transparent: true, opacity: .9, emissive: 0x9fd6ff, emissiveIntensity: .25}),
    product: std({color: 0xffffff, roughness: .88}),
    hoseRed: std({color: 0xb8402c, roughness: .6}), hoseBlue: std({color: 0x2f6fb0, roughness: .6}), hose: std({color: 0x2a2d31, roughness: .7}),
    silicone: phys({color: 0xf2efe6, roughness: .3, transparent: true, opacity: .6}),
    red: std({color: 0xc4302b, roughness: .45}), yellow: std({color: 0xf2c230, roughness: .5}),
    green: std({color: 0x2e9b57, roughness: .5, emissive: 0x2e9b57, emissiveIntensity: .5}),
    wood: std({color: 0x9b7650, roughness: .85}),
    absorber: std({color: 0x15171a, roughness: .7, metalness: .2}),
    tarp: std({color: 0x2f6ea8, roughness: .7, side: T3.DoubleSide}),
    pv: std({map: pv, metalness: .3, roughness: .25}),
    concrete: std({color: 0xb9b5ad, roughness: .95}),
    powder: std({color: 0xe4cfa2, roughness: 1}),
    water: phys({color: 0x6fb3e8, transparent: true, opacity: .55, roughness: .1}),
    compressor: std({color: 0x24332b, metalness: .4, roughness: .5}),
    fins: std({map: fins, metalness: .6, roughness: .5}),
    oil: std({color: 0xd9a21b, emissive: 0x8a5a00, emissiveIntensity: .4}),
    net: std({color: 0x8d969f, alphaMap: net, alphaTest: .3, side: T3.DoubleSide, metalness: .4, roughness: .5}),
    netCover: std({color: 0xf2f2f2, alphaMap: net, transparent: true, depthWrite: false, side: T3.DoubleSide, roughness: .8}),
    sock: std({map: stripe, side: T3.DoubleSide, roughness: .8}),
  };
}

export function createEquipment3D(box, lib, opt){
  const {T3, OrbitControls} = lib;
  const {method, variant, getState, onPick} = opt;
  const renderer = new T3.WebGLRenderer({antialias: true, alpha: true});  // WebGL이 없으면 여기서 예외 → 호출 측이 P&ID로 대체
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = T3.PCFSoftShadowMap; renderer.shadowMap.autoUpdate = false;
  renderer.toneMapping = T3.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
  renderer.localClippingEnabled = true;
  const canvas = renderer.domElement; canvas.className = 'eq-canvas';
  canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', '건조 설비 3D 모델 — 끌어서 돌리고, 휠로 확대합니다. 부품은 오른쪽 목록으로도 고를 수 있습니다.');
  box.appendChild(canvas);
  const size = () => [box.clientWidth || 600, box.clientHeight || 420];
  renderer.setSize(...size());

  const scene = new T3.Scene();
  const pmrem = new T3.PMREMGenerator(renderer);
  const envT = envTexture(T3); const env = pmrem.fromEquirectangular(envT).texture; envT.dispose(); pmrem.dispose();
  scene.environment = env; scene.environmentIntensity = .9;
  const cam = new T3.PerspectiveCamera(36, size()[0] / size()[1], .05, 80);
  const controls = new OrbitControls(cam, canvas);
  controls.enableDamping = true; controls.dampingFactor = .08; controls.maxPolarAngle = Math.PI * .49; controls.minPolarAngle = .1;
  controls.autoRotateSpeed = .7;

  const hemi = new T3.HemisphereLight(0xf2f6ff, 0x7d7468, .55); scene.add(hemi);
  const key = new T3.DirectionalLight(0xffffff, 2.0); key.position.set(4, 7, 5); key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048); Object.assign(key.shadow.camera, {left: -5, right: 5, top: 5, bottom: -5, near: .5, far: 25});
  key.shadow.bias = -.0004; key.shadow.normalBias = .02; key.shadow.radius = 4;
  scene.add(key, key.target);
  const fill = new T3.DirectionalLight(0xdfe8ff, .5); fill.position.set(-5, 3, -2); scene.add(fill);

  const dark = () => window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const floorMat = new T3.MeshStandardMaterial({color: 0xd9dee5, roughness: .95});
  const floor = new T3.Mesh(new T3.CircleGeometry(12, 64), floorMat); floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; floor.userData.noHit = true;
  const grid = new T3.GridHelper(14, 56, 0x000000, 0x000000); grid.material.transparent = true; grid.material.opacity = .08; grid.position.y = .001;
  scene.add(floor, grid);
  let ground = false;
  const theme = () => {
    const d = dark();
    floorMat.color.set(ground ? (d ? 0x3a4a2e : 0x86a061) : (d ? 0x2a323d : 0xd9dee5));
    grid.material.color.set(d ? 0xffffff : 0x000000); grid.material.opacity = d ? .07 : .08; grid.visible = !ground;
  };
  const mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  mq?.addEventListener?.('change', theme);

  const M = materials(T3);
  const shellMats = [];
  const shell = m => { const c = m.clone(); c.side = T3.DoubleSide; c.clipShadows = true; shellMats.push(c); return c };
  const S = {steel: shell(M.steel), paint: shell(M.paint), wool: shell(M.wool), glass: shell(M.glass), film: shell(M.film), dark: shell(M.dark), clad: shell(M.clad)};
  let clipZ = 0;
  const plane = new T3.Plane(new T3.Vector3(0, 0, -1), 0);

  const root = new T3.Group(); scene.add(root);
  const parts = new Map(), fronts = [], updaters = [], dials = [], hmis = [];
  const V = (x, y, z) => new T3.Vector3(x, y, z);
  const dm = new T3.Object3D();
  const geoCache = new Map();
  const cached = (k, f) => { let g = geoCache.get(k); if (!g) geoCache.set(k, g = f()); return g };

  // ------------------------------------------------------------ 형상 도우미
  function mesh(geo, mat, parent, p, r){
    const m = new T3.Mesh(geo, mat);
    if (p) m.position.set(p[0], p[1], p[2]);
    if (r) m.rotation.set(r[0] || 0, r[1] || 0, r[2] || 0);
    m.castShadow = m.receiveShadow = true; parent.add(m); return m;
  }
  function grp(parent, p, r){
    const g = new T3.Group();
    if (p) g.position.set(p[0], p[1], p[2]);
    if (r) g.rotation.set(r[0] || 0, r[1] || 0, r[2] || 0);
    parent.add(g); return g;
  }
  const box_ = (w, h, d) => cached(`b${w},${h},${d}`, () => new T3.BoxGeometry(w, h, d));
  const cyl = (rt, rb, h, s = 40, open = false) => cached(`c${rt},${rb},${h},${s},${open}`, () => new T3.CylinderGeometry(rt, rb, h, s, 1, open));
  const sph = (r, ws = 24, hs = 16) => cached(`s${r},${ws}`, () => new T3.SphereGeometry(r, ws, hs));
  const torus = (r, t, arc = TAU) => cached(`t${r},${t},${arc}`, () => new T3.TorusGeometry(r, t, 10, 48, arc));
  const capsule = (r, l) => cached(`cap${r},${l}`, () => new T3.CapsuleGeometry(r, l, 8, 24));
  const lathe = (pts, s = 72) => new T3.LatheGeometry(pts.map(([r, y]) => new T3.Vector2(r, y)), s);
  function rrect(s, w, h, cr, x0 = -w / 2, y0 = -h / 2){
    s.moveTo(x0 + cr, y0); s.lineTo(x0 + w - cr, y0); s.quadraticCurveTo(x0 + w, y0, x0 + w, y0 + cr);
    s.lineTo(x0 + w, y0 + h - cr); s.quadraticCurveTo(x0 + w, y0 + h, x0 + w - cr, y0 + h);
    s.lineTo(x0 + cr, y0 + h); s.quadraticCurveTo(x0, y0 + h, x0, y0 + h - cr); s.lineTo(x0, y0 + cr); s.quadraticCurveTo(x0, y0, x0 + cr, y0);
    return s;
  }
  // 모서리가 둥근 상자(베벨 압출)
  function rbox(w, h, d, r = .015){
    return cached(`rb${w},${h},${d},${r}`, () => {
      r = Math.max(0, Math.min(r, w / 2 - 1e-3, h / 2 - 1e-3, d / 2 - 1e-3));
      const iw = w - 2 * r, ih = h - 2 * r;
      const s = rrect(new T3.Shape(), iw, ih, Math.min(r * .6, iw / 2, ih / 2));
      const g = new T3.ExtrudeGeometry(s, {depth: Math.max(d - 2 * r, 1e-3), bevelEnabled: r > 0, bevelThickness: r, bevelSize: r, bevelSegments: 3, curveSegments: 4});
      g.center(); return g;
    });
  }
  // 구멍 뚫린 판(문틀·관찰창 문) — holes: {w,h,x,y} 사각 / {r,x,y} 원
  function plate(w, h, d, holes = []){
    const s = rrect(new T3.Shape(), w, h, .02);
    for (const o of holes) {
      const p = new T3.Path();
      if (o.r) p.absarc(o.x || 0, o.y || 0, o.r, 0, TAU, true);
      else rrect(p, o.w, o.h, .01, (o.x || 0) - o.w / 2, (o.y || 0) - o.h / 2);
      s.holes.push(p);
    }
    const g = new T3.ExtrudeGeometry(s, {depth: d, bevelEnabled: true, bevelThickness: .004, bevelSize: .004, bevelSegments: 2, curveSegments: 24});
    g.translate(0, 0, -d / 2); return g;
  }
  // 꺾인 점들을 둥근 엘보로 잇는 배관 경로
  function pathOf(pts, bend){
    const P = pts.map(p => V(...p)), path = new T3.CurvePath();
    let prev = P[0];
    for (let i = 1; i < P.length; i++) {
      const a = P[i];
      if (i < P.length - 1) {
        const b = P[i + 1], d1 = a.clone().sub(prev), d2 = b.clone().sub(a);
        const r = Math.min(bend, d1.length() / 2, d2.length() / 2);
        const p1 = a.clone().sub(d1.normalize().multiplyScalar(r)), p2 = a.clone().add(d2.normalize().multiplyScalar(r));
        if (p1.distanceTo(prev) > 1e-4) path.add(new T3.LineCurve3(prev.clone(), p1));
        path.add(new T3.QuadraticBezierCurve3(p1, a.clone(), p2));
        prev = p2;
      } else path.add(new T3.LineCurve3(prev.clone(), a.clone()));
    }
    return path;
  }
  const tube = (pts, r, bend = r * 3, rs = 14) => { const path = pathOf(pts, bend); return new T3.TubeGeometry(path, Math.max(16, Math.ceil(path.getLength() * 70)), r, rs, false) };
  const pipe = (parent, pts, r, mat = M.steel, bend) => mesh(tube(pts, r, bend ?? r * 3), mat, parent);
  const AX = {x: [0, 0, Math.PI / 2], y: [0, 0, 0], z: [Math.PI / 2, 0, 0]};
  // 볼트 체결 플랜지(hole=true면 가운데가 뚫린 고리)
  function flange(parent, p, axis, r, n = 8, mat = M.steel, hole = false){
    const g = grp(parent, p, AX[axis]);
    if (hole) mesh(cached(`fr${r}`, () => lathe([[r, -r * .15], [r * 1.55, -r * .15], [r * 1.55, r * .15], [r, r * .15], [r, -r * .15]], 48)), mat, g);
    else mesh(cyl(r * 1.55, r * 1.55, r * .3, 40), mat, g);
    if (n) {
      const im = new T3.InstancedMesh(cyl(r * .12, r * .12, r * .62, 6), M.steelDark, n); im.castShadow = true;
      for (let i = 0; i < n; i++) { const a = (i + .5) / n * TAU; dm.position.set(Math.cos(a) * r * 1.3, 0, Math.sin(a) * r * 1.3); dm.rotation.set(0, 0, 0); dm.scale.set(1, 1, 1); dm.updateMatrix(); im.setMatrixAt(i, dm.matrix) }
      g.add(im);
    }
    return g;
  }
  // 사각 파이프 프레임(다리 + 상하 레일 + 수평 조절 발)
  function frame(parent, p, w, d, h, {t = .04, mat = M.frame, rails = [.12], feet = true} = {}){
    const g = grp(parent, p), f = feet ? .035 : 0;
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
      const x = sx * (w / 2 - t / 2), z = sz * (d / 2 - t / 2);
      mesh(box_(t, h - f, t), mat, g, [x, f + (h - f) / 2, z]);
      if (feet) { mesh(cyl(t * .3, t * .3, f, 10), M.steelDark, g, [x, f / 2, z]); mesh(cyl(t * .8, t * .8, .012, 16), M.rubber, g, [x, .006, z]) }
    }
    for (const y of [h - t / 2, ...rails.map(r => r + f)]) for (const s of [-1, 1]) {
      mesh(box_(w - 2 * t, t, t), mat, g, [0, y, s * (d / 2 - t / 2)]);
      mesh(box_(t, t, d - 2 * t), mat, g, [s * (w / 2 - t / 2), y, 0]);
    }
    return g;
  }
  // 전동기(냉각 핀·팬 커버·단자함) — 축은 국소 +x. dir: 'x'(수평) | 'up' | 'down'
  function motor(parent, p, r, len, {yaw = 0, dir = 'x', mat = M.motor, feet = dir === 'x'} = {}){
    const g = grp(parent, p); g.rotation.set(0, yaw, dir === 'up' ? Math.PI / 2 : dir === 'down' ? -Math.PI / 2 : 0);
    mesh(cached(`mot${r},${len}`, () => {
      const pts = [[0, 0], [r * .9, 0], [r, r * .08]], n = 9, a = len * .1, b = len * .92, s = (b - a) / n;
      for (let i = 0; i < n; i++) { const y = a + i * s; pts.push([r, y], [r * 1.08, y + s * .15], [r * 1.08, y + s * .55], [r, y + s * .7]) }
      pts.push([r, b], [r * .92, len], [r * .3, len + r * .05], [0, len + r * .05]);
      const gg = lathe(pts, 40); gg.rotateZ(-Math.PI / 2); return gg;
    }), mat, g);
    mesh(cyl(r * 1.04, r * 1.04, r * .5, 32), M.dark, g, [-r * .25, 0, 0], [0, 0, Math.PI / 2]);
    mesh(cyl(r * .15, r * .15, r * .8, 16), M.steel, g, [len + r * .4, 0, 0], [0, 0, Math.PI / 2]);
    mesh(rbox(r * .7, r * .45, r * .7, r * .06), mat, g, [len * .5, r * 1.2, 0]);
    if (feet) mesh(box_(len * .7, r * .12, r * 1.9), mat, g, [len * .5, -r * 1.02, 0]);
    return g;
  }
  // 로터리 베인 진공 펌프(모터 + 펌프 몸체 + 오일창 + 배기 필터). 흡입구 = p + (.04, .35, 0)
  function vanePump(parent, p){
    const g = grp(parent, p);
    mesh(rbox(.66, .03, .26, .006), M.frame, g, [-.13, .015, 0]);
    for (const x of [-.4, .14]) for (const z of [-.1, .1]) mesh(cyl(.018, .018, .02, 12), M.rubber, g, [x, .035, z]);
    motor(g, [-.42, .15, 0], .085, .3, {feet: false});
    mesh(box_(.3, .05, .14), M.motor, g, [-.27, .06, 0]);
    mesh(cyl(.075, .075, .06, 24), M.dark, g, [-.07, .15, 0], [0, 0, Math.PI / 2]);
    mesh(rbox(.2, .2, .19, .025), M.pump, g, [.07, .15, 0]);
    mesh(cyl(.026, .026, .012, 20), M.oil, g, [.07, .1, .096], [Math.PI / 2, 0, 0]);
    mesh(cyl(.042, .042, .16, 24), M.steelDark, g, [.19, .32, 0]);
    mesh(cyl(.02, .02, .1, 16), M.steel, g, [.04, .29, 0]);
    flange(g, [.04, .34, 0], 'y', .022, 4);
    return g;
  }
  function handwheel(parent, p, r, rot = [0, 0, 0], mat = M.dark){
    const g = grp(parent, p, rot);
    mesh(torus(r, r * .1), mat, g);
    for (let i = 0; i < 3; i++) mesh(box_(r, r * .12, r * .12), M.steel, grp(g, null, [0, 0, i * TAU / 3]), [r / 2, 0, 0]);
    mesh(cyl(r * .2, r * .2, r * .3, 16), M.steel, g, null, [Math.PI / 2, 0, 0]);
    return g;
  }
  // 버터플라이 밸브(공압 구동기 또는 핸들). axis: 'x' | 'z'. 반환값.disc = 판(개도 애니메이션)
  function butterfly(parent, p, axis, r, {act = true} = {}){
    const g = grp(parent, p, axis === 'x' ? null : [0, Math.PI / 2, 0]);
    mesh(cyl(r * 1.45, r * 1.45, r * .55, 40), M.steelDark, g, null, [0, 0, Math.PI / 2]);
    mesh(cyl(r * .12, r * .12, r * .9, 12), M.steel, g, [0, r * 1.85, 0]);
    if (act) { mesh(rbox(r * 1.2, r * .7, r * 1.2, r * .08), M.clad, g, [0, r * 2.5, 0]); mesh(cyl(r * .38, r * .38, r * 2, 24), M.motor, g, [0, r * 2.55, r * .2], [Math.PI / 2, 0, 0]) }
    else mesh(box_(r * 2.2, r * .15, r * .3), M.red, g, [r * .9, r * 2.2, 0]);
    g.disc = mesh(cyl(r * .95, r * .95, r * .05, 32), M.steel, g, null, [0, 0, Math.PI / 2]);
    return g;
  }
  // 아날로그 다이얼 게이지 — 앞면 +z. spec: {key, min, max, log, ticks:[[v,'라벨']], unit, title, scale}
  function dial(parent, p, rot, r, spec){
    const g = grp(parent, p, rot);
    const frac = v => {
      if (v == null || Number.isNaN(v)) return 0;
      if (spec.scale) v = spec.scale(v);
      if (spec.log) { const a = Math.log10(spec.min), b = Math.log10(spec.max); return sat((Math.log10(Math.max(v, spec.min)) - a) / (b - a)) }
      return sat((v - spec.min) / (spec.max - spec.min));
    };
    const ang = f => (-135 + 270 * f) * Math.PI / 180;
    const tex = canvasTex(T3, 256, 256, c => {
      c.fillStyle = '#f4f3ee'; c.beginPath(); c.arc(128, 128, 127, 0, TAU); c.fill();
      c.strokeStyle = c.fillStyle = '#1b1f24'; c.textAlign = 'center'; c.textBaseline = 'middle';
      for (let i = 0; i <= 40; i++) { const a = ang(i / 40), r1 = i % 5 ? 101 : 92; c.lineWidth = i % 5 ? 1.5 : 3; c.beginPath(); c.moveTo(128 + Math.sin(a) * r1, 128 - Math.cos(a) * r1); c.lineTo(128 + Math.sin(a) * 111, 128 - Math.cos(a) * 111); c.stroke() }
      c.font = '700 21px Consolas, monospace';
      for (const [v, s] of spec.ticks) { const a = ang(spec.log ? frac(v) : sat((v - spec.min) / (spec.max - spec.min))); c.fillText(s, 128 + Math.sin(a) * 73, 128 - Math.cos(a) * 73) }
      c.font = `700 24px ${FONT}`; c.fillText(spec.unit, 128, 172);
      c.font = `600 17px ${FONT}`; c.fillStyle = '#5b6470'; c.fillText(spec.title || '', 128, 200);
    });
    mesh(cyl(r * 1.08, r * 1.08, r * .4, 40), M.dark, g, [0, 0, -r * .2], [Math.PI / 2, 0, 0]);
    mesh(torus(r * 1.04, r * .07), M.steel, g);
    mesh(cached(`circ${r}`, () => new T3.CircleGeometry(r, 48)), new T3.MeshStandardMaterial({map: tex, roughness: .5}), g, [0, 0, .002]);
    const nd = mesh(cached(`nd${r}`, () => new T3.BoxGeometry(r * .06, r * .85, .004).translate(0, r * .32, 0)), M.red, g, [0, 0, .012]);
    mesh(cyl(r * .08, r * .08, .01, 16), M.dark, g, [0, 0, .016], [Math.PI / 2, 0, 0]);
    const gl = mesh(cached(`circ${r}`, () => new T3.CircleGeometry(r, 48)), M.glass, g, [0, 0, .024]); gl.userData.noHit = true;
    let cur = -ang(0); nd.rotation.z = cur;
    dials.push({key: spec.key, set: v => { const t = -ang(frac(v)); cur += (t - cur) * .12; nd.rotation.z = cur }});
    return g;
  }
  // 제어반 HMI — 화면은 캔버스 텍스처로 계기값을 그린다(4 Hz)
  function hmi(parent, p, rot, w, h, title, keys){
    const g = grp(parent, p, rot);
    mesh(rbox(w + .05, h + .1, .05, .012), M.dark, g, [0, -.025, 0]);
    const cw = 512, chh = Math.round(512 * h / w);
    const cv = document.createElement('canvas'); cv.width = cw; cv.height = chh; const c = cv.getContext('2d');
    const tex = new T3.CanvasTexture(cv); tex.colorSpace = T3.SRGBColorSpace; tex.anisotropy = 4;
    const scr = mesh(cached(`pl${w},${h}`, () => new T3.PlaneGeometry(w, h)), new T3.MeshBasicMaterial({map: tex, toneMapped: false}), g, [0, 0, .026]);
    scr.castShadow = false;
    [M.green, M.yellow, M.steel].forEach((m, i) => mesh(cyl(.011, .011, .012, 16), m, g, [-w / 2 + .03 + i * .04, -h / 2 - .045, .028], [Math.PI / 2, 0, 0]));
    mesh(cyl(.02, .02, .022, 20), M.red, g, [w / 2 - .03, -h / 2 - .045, .03], [Math.PI / 2, 0, 0]);
    mesh(cyl(.026, .026, .006, 20), M.yellow, g, [w / 2 - .03, -h / 2 - .045, .022], [Math.PI / 2, 0, 0]);
    let last = '';
    hmis.push(st => {
      const rows = keys ? st.rows.filter(r => keys.includes(r.key)) : st.rows;
      const k = JSON.stringify(rows) + st.sub; if (k === last) return; last = k;
      const bg = c.createLinearGradient(0, 0, 0, chh); bg.addColorStop(0, '#13243a'); bg.addColorStop(1, '#0a1422');
      c.fillStyle = bg; c.fillRect(0, 0, cw, chh);
      const hh = Math.min(46, chh * .2);
      c.fillStyle = '#1d4f9c'; c.fillRect(0, 0, cw, hh);
      c.textBaseline = 'middle'; c.textAlign = 'left'; c.fillStyle = '#fff'; c.font = `700 ${hh * .5 | 0}px ${FONT}`; c.fillText(title, 14, hh / 2);
      c.textAlign = 'right'; c.fillStyle = '#cfe0ff'; c.font = `600 ${hh * .4 | 0}px ${FONT}`; c.fillText(st.sub || '', cw - 14, hh / 2);
      const rh = (chh - hh - 6) / Math.max(rows.length, 1);
      rows.forEach((r, i) => {
        const y = hh + 4 + rh * i + rh / 2;
        if (i) { c.fillStyle = 'rgba(255,255,255,.08)'; c.fillRect(10, y - rh / 2, cw - 20, 1) }
        c.textAlign = 'left'; c.fillStyle = '#7fb0e8'; c.font = `600 ${Math.min(17, rh * .3) | 0}px Consolas, monospace`; c.fillText(r.tag, 14, y - rh * .2);
        c.fillStyle = '#b9c6d6'; c.font = `500 ${Math.min(19, rh * .32) | 0}px ${FONT}`; c.fillText(r.label, 14, y + rh * .2);
        c.textAlign = 'right'; c.fillStyle = r.cond ? '#ffd27a' : '#ffffff'; c.font = `700 ${Math.min(34, rh * .5) | 0}px Consolas, monospace`; c.fillText(r.text, cw - 14, y);
      });
      tex.needsUpdate = true;
    });
    return g;
  }
  function tray(parent, p, w, d, {h = .03, perf = false, mat = M.steel} = {}){
    const g = grp(parent, p);
    mesh(box_(w, .004, d), perf ? M.perf : mat, g, [0, .002, 0]);
    for (const s of [-1, 1]) { mesh(box_(w, h, .006), mat, g, [0, h / 2, s * (d / 2 - .003)]); mesh(box_(.006, h, d), mat, g, [s * (w / 2 - .003), h / 2, 0]) }
    return g;
  }
  // 시료 조각(인스턴스) — set(크기 비율, 갈변 0~1)
  function chunks(parent, p, w, d, n, seed, color, sz = .03){
    const R = rnd(seed), im = new T3.InstancedMesh(cached('chunk', () => new T3.DodecahedronGeometry(1, 0)), M.product, n);
    im.castShadow = im.receiveShadow = true; im.position.set(...p); parent.add(im);
    const base = Array.from({length: n}, () => ({x: (R() - .5) * (w - sz * 2), z: (R() - .5) * (d - sz * 2), s: sz * (.7 + R() * .6), ry: R() * TAU, rx: R() * .6, j: R()}));
    const c0 = new T3.Color(color), c = new T3.Color();
    let lastS = -1, lastB = -1;
    const set = (s = 1, brown = 0) => {
      if (Math.abs(s - lastS) > .004) { lastS = s; base.forEach((b, i) => { dm.position.set(b.x, b.s * s * .5, b.z); dm.rotation.set(b.rx, b.ry, 0); dm.scale.set(b.s * s, b.s * s * .6, b.s * s); dm.updateMatrix(); im.setMatrixAt(i, dm.matrix) }); im.instanceMatrix.needsUpdate = true }
      if (Math.abs(brown - lastB) > .01) { lastB = brown; base.forEach((b, i) => { c.copy(c0).offsetHSL((b.j - .5) * .03, (b.j - .5) * .1 - brown * .08, (b.j - .5) * .12 - brown * .16); im.setColorAt(i, c) }); im.instanceColor.needsUpdate = true }
    };
    set(1, 0);
    return {im, base, set};
  }
  // 시료 위 얼음 결정 — 반환 함수(양 0~1)
  function crystals(ch, n, sz = .012){
    const im = new T3.InstancedMesh(cached('oct', () => new T3.OctahedronGeometry(1, 0)), M.ice, n);
    im.position.copy(ch.im.position); ch.im.parent.add(im);
    const R = rnd(n + 3), pts = Array.from({length: n}, (_, i) => { const b = ch.base[i % ch.base.length]; return {x: b.x + (R() - .5) * b.s * 1.4, y: b.s * .55 + R() * .006, z: b.z + (R() - .5) * b.s * 1.4, s: sz * (.6 + R() * .8), r: R() * TAU} });
    let last = -1;
    return v => {
      if (Math.abs(v - last) < .005) return; last = v;
      pts.forEach((q, i) => { dm.position.set(q.x, q.y, q.z); dm.rotation.set(q.r, q.r * 2, 0); dm.scale.setScalar(q.s * v + 1e-5); dm.updateMatrix(); im.setMatrixAt(i, dm.matrix) });
      im.instanceMatrix.needsUpdate = true;
    };
  }
  class Helix extends T3.Curve {
    constructor(r, x0, x1, turns, cy, cz){ super(); Object.assign(this, {r, x0, x1, turns, cy, cz}) }
    getPoint(t, o = new T3.Vector3()){ const a = t * this.turns * TAU; return o.set(lerp(this.x0, this.x1, t), this.cy + Math.cos(a) * this.r, this.cz + Math.sin(a) * this.r) }
  }
  const curve = pts => new T3.CatmullRomCurve3(pts.map(p => V(...p)), false, 'centripetal');
  const along = (curves, spread = .03) => { const J = [], R = rnd(91); return (i, t, o) => { curves[i % curves.length].getPoint(t, o); o.add(J[i] ||= V(R() - .5, R() - .5, R() - .5).multiplyScalar(spread * 2)) } };
  const env01 = t => Math.min(1, t * 10, (1 - t) * 10);
  const HC = [[0, new T3.Color(0x7da2c6)], [.5, new T3.Color(0xf0c04a)], [1, new T3.Color(0xe5522a)]];
  const heatColor = (c, f) => { f = sat(f); const i = f < .5 ? 0 : 1; return c.lerpColors(HC[i][1], HC[i + 1][1], (f - HC[i][0]) / (HC[i + 1][0] - HC[i][0])) };
  // 입자 흐름(인스턴스 1개 = 그리기 1회). key: 상태의 애니메이션 값(0~1)이 보이는 입자 비율
  function flow({n, size, color = 0xffffff, key, path, tint, scale, speed = [.15, .3], geo, opacity = .85}){
    const im = new T3.InstancedMesh(geo || cached('pS', () => new T3.IcosahedronGeometry(1, 1)),
      new T3.MeshBasicMaterial({color: 0xffffff, transparent: true, opacity, depthWrite: false, toneMapped: false}), n);
    im.frustumCulled = false; im.userData.noHit = true; root.add(im);
    const R = rnd(n * 31 + 7), seed = [], sp = [], off = [], c = new T3.Color(color), v = V(0, 0, 0);
    for (let i = 0; i < n; i++) { seed.push(R()); sp.push(lerp(speed[0], speed[1], R())); off.push(R()); im.setColorAt(i, c) }
    updaters.push((st, time) => {
      const rate = key ? (st.a[key] ?? 0) : 1;
      for (let i = 0; i < n; i++) {
        const t = (time * sp[i] + off[i]) % 1;
        let s = seed[i] < rate ? size : 0;
        if (s) { path(i, t, v, seed[i], st); s *= scale ? scale(i, t, st) : env01(t); dm.position.copy(v) } else dm.position.set(0, -50, 0);
        dm.rotation.set(0, 0, 0); dm.scale.setScalar(Math.max(s, 1e-5)); dm.updateMatrix(); im.setMatrixAt(i, dm.matrix);
        if (tint && s) { tint(i, t, c, st); im.setColorAt(i, c) }
      }
      im.instanceMatrix.needsUpdate = true; if (tint) im.instanceColor.needsUpdate = true;
    });
    return im;
  }
  const on = f => updaters.push(f);
  const spin = (obj, axis, speed, k) => on((st, time, dt) => { obj.rotation[axis] += dt * speed * (k ? st.a[k] ?? 0 : 1) });
  function part(id, anchor){
    const g = new T3.Group(); g.userData.part = id; root.add(g);
    parts.set(id, {g, anchor: V(...anchor)}); return g;
  }
  const front = o => { fronts.push(o); return o };

  const K = {T3, M, S, V, root, part, front, on, spin, mesh, grp, box: box_, cyl, sph, torus, capsule, lathe, rbox, plate, tube, pipe, flange, frame,
    motor, vanePump, handwheel, butterfly, dial, hmi, tray, chunks, crystals, flow, curve, along, heatColor, Helix, env01, cached,
    light: {key, hemi, fill}, setGround(on){ ground = on; theme() }, setEnv(v){ scene.environmentIntensity = v }, anchor: id => parts.get(id)?.anchor,
    setClip(z){ clipZ = z; plane.constant = z }};
  const view = (BUILD[method] || BUILD['동결건조'])(K, variant);
  theme();

  // 라벨 중심(태양 제외 부품의 경계 상자)
  const bb = new T3.Box3();
  parts.forEach((P, id) => { if (id !== 'sun') bb.expandByObject(P.g) });
  const bbOk = [bb.min.x, bb.min.y, bb.min.z, bb.max.x, bb.max.y, bb.max.z].every(Number.isFinite);
  const center = bbOk ? bb.getCenter(V(0, 0, 0)) : V(...view.target);
  const bbPad = bb.clone().expandByScalar(.6);

  // ------------------------------------------------------------ 시점
  function resetView(){
    controls.target.set(...view.target);
    // 세로로 긴 화면(휴대폰)에서는 좌우가 잘리지 않게 뒤로 물러난다
    const [w, h] = size(), k = Math.max(1, Math.pow(1.45 / (w / h), .85));
    cam.position.set(...view.pos).sub(controls.target).multiplyScalar(k).add(controls.target);
    const d = cam.position.distanceTo(controls.target);
    controls.minDistance = d * .3 / k; controls.maxDistance = d * 2.2;
    controls.update();
  }
  resetView();

  // ------------------------------------------------------------ 절개 보기
  let cut = !!opt.cut, selId = null;
  const hlCache = new Map();
  function applyCut(){
    for (const m of shellMats) { m.clippingPlanes = cut ? [plane] : []; m.needsUpdate = true }
    fronts.forEach(o => o.visible = !cut);
    renderer.shadowMap.needsUpdate = true;
  }
  applyCut();

  // ------------------------------------------------------------ 선택(강조)
  const hl = m => {
    if (!m.emissive) return m;
    let c = hlCache.get(m);
    if (!c) { c = m.clone(); c.emissive = new T3.Color(0x3b82f6); c.emissiveIntensity = .6; if (c.transparent) c.opacity = Math.min(1, c.opacity * 2.2); hlCache.set(m, c) }
    return c;
  };
  function select(id){
    if (selId) parts.get(selId)?.g.traverse(o => { if (o.isMesh && o.userData.m0) { o.material = o.userData.m0; delete o.userData.m0 } });
    selId = id || null;
    const P = id && parts.get(id);
    if (P) P.g.traverse(o => { if (o.isMesh && !o.userData.noHit && !o.userData.m0) { o.userData.m0 = o.material; o.material = hl(o.material) } });
    labels.forEach(l => { l.b.classList.toggle('sel', l.id === selId); l.dot.classList.toggle('sel', l.id === selId) });
  }

  // ------------------------------------------------------------ 클릭·가림 판정
  const raycaster = new T3.Raycaster(), ndc = new T3.Vector2();
  let hitList = [];
  const rebuildHits = () => { hitList = []; root.traverse(o => { if (o.isMesh && !o.userData.noHit && !(o.material.transparent && !o.isInstancedMesh)) hitList.push(o) }) };
  rebuildHits();
  const visibleChain = o => { for (; o; o = o.parent) if (!o.visible) return false; return true };
  const partOf = o => { for (; o; o = o.parent) if (o.userData.part) return o.userData.part; return null };
  const firstHit = () => raycaster.intersectObjects(hitList, false).find(h =>
    visibleChain(h.object) && !(cut && h.object.material.clippingPlanes?.length && h.point.z > clipZ + 1e-3));
  let down = null;
  canvas.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY] });
  canvas.addEventListener('pointerup', e => {
    if (!down) return;
    const moved = Math.hypot(e.clientX - down[0], e.clientY - down[1]); down = null;
    if (moved > 5) return;
    const r = canvas.getBoundingClientRect();
    ndc.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
    raycaster.setFromCamera(ndc, cam); raycaster.far = Infinity;
    const id = partOf(firstHit()?.object);
    if (id) onPick(id);
  });

  // ------------------------------------------------------------ 부품 라벨(HTML, 3D 점에 고정)
  const layer = document.createElement('div'); layer.className = 'eq-labels'; box.appendChild(layer);
  const svg = document.createElementNS(NS, 'svg'); svg.setAttribute('class', 'eq-leaders'); layer.appendChild(svg);
  const labels = [];
  for (const info of opt.parts || []) {
    const P = parts.get(info.id); if (!P) continue;
    const dot = document.createElement('span'); dot.className = 'eq-dot';
    const b = document.createElement('button'); b.type = 'button'; b.className = 'eq-lbl'; b.tabIndex = -1;
    b.textContent = info.name.replace(/\s*\(.*?\)\s*/g, ' ').trim(); b.dataset.part = info.id;
    b.onclick = () => onPick(info.id);
    const ln = document.createElementNS(NS, 'line'); svg.appendChild(ln);
    layer.append(dot, b);
    labels.push({id: info.id, P, dot, b, ln, w: 0, h: 0, occ: false});
  }
  let labelsOn = opt.labels !== false;
  layer.hidden = !labelsOn;
  const v3 = V(0, 0, 0), cen = V(0, 0, 0);
  function layoutLabels(){
    layer.hidden = !labelsOn; if (!labelsOn) return;
    const [w, h] = size();
    cen.copy(center).project(cam);
    const cx = (cen.x * .5 + .5) * w, cy = (-cen.y * .5 + .5) * h;
    const items = [];
    for (const l of labels) {
      v3.copy(l.P.anchor).project(cam);
      const x = (v3.x * .5 + .5) * w, y = (-v3.y * .5 + .5) * h;
      const show = v3.z < 1 && x > -10 && x < w + 10 && y > -10 && y < h + 10 && visibleChain(l.P.g);
      if (!show) { l.dot.style.display = l.b.style.display = 'none'; l.ln.setAttribute('visibility', 'hidden'); continue }
      if (!l.w) { l.b.style.display = ''; l.w = l.b.offsetWidth; l.h = l.b.offsetHeight }
      let dx = x - cx, dy = y - cy; const n = Math.hypot(dx, dy) || 1; dx /= n; dy /= n;
      const lx = x + dx * 30, ly = y + dy * 22;
      items.push({l, x, y, bx: dx >= 0 ? lx : lx - l.w, by: ly - l.h / 2, right: dx < 0});
    }
    items.sort((a, b) => a.by - b.by);
    for (let i = 0; i < items.length; i++) {
      const b = items[i];
      for (let j = 0, guard = 0; j < i && guard < 60; j++) {
        const a = items[j];
        if (b.bx < a.bx + a.l.w + 4 && a.bx < b.bx + b.l.w + 4 && b.by < a.by + a.l.h + 3 && a.by < b.by + b.l.h + 3) { b.by = a.by + a.l.h + 3; j = -1; guard++ }
      }
    }
    for (const it of items) {
      const {l} = it;
      it.bx = clamp(it.bx, 2, w - l.w - 2); it.by = clamp(it.by, 2, h - l.h - 2);
      l.dot.style.display = l.b.style.display = '';
      l.dot.style.transform = `translate(${it.x.toFixed(1)}px,${it.y.toFixed(1)}px)`;
      l.b.style.transform = `translate(${it.bx.toFixed(1)}px,${it.by.toFixed(1)}px)`;
      const ex = it.bx + l.w / 2 < it.x ? it.bx + l.w : it.bx, ey = it.by + l.h / 2;
      l.ln.setAttribute('x1', it.x.toFixed(1)); l.ln.setAttribute('y1', it.y.toFixed(1));
      l.ln.setAttribute('x2', ex.toFixed(1)); l.ln.setAttribute('y2', ey.toFixed(1)); l.ln.setAttribute('visibility', 'visible');
      l.b.classList.toggle('occ', l.occ); l.dot.classList.toggle('occ', l.occ); l.ln.classList.toggle('occ', l.occ);
    }
  }
  const dir = V(0, 0, 0);
  function occlusion(){
    for (const l of labels) {
      dir.copy(l.P.anchor).sub(cam.position); const d = dir.length(); dir.normalize();
      raycaster.set(cam.position, dir); raycaster.far = Math.max(.01, d - .05);
      const h = firstHit(); l.occ = !!h && partOf(h.object) !== l.id;
    }
  }

  // ------------------------------------------------------------ 렌더 루프(화면 밖·숨은 탭이면 멈춤)
  let alive = true, broken = false, raf = 0, inView = true, last = performance.now(), time = 0, fc = 0, hmiT = 0;
  const sunMoves = method === '자연건조';
  function loop(now){
    raf = 0;
    if (!alive || broken) return;
    if (!box.isConnected) { dispose(); return }
    if (!inView || document.hidden) return;
    raf = requestAnimationFrame(loop);
    try {
      const dt0 = Math.min(.05, (now - last) / 1000); last = now;
      const st = getState(); if (!st) return;
      const dt = st.playing ? dt0 : 0; time += dt;
      for (const u of updaters) u(st, time, dt);
      for (const d of dials) d.set(st.g[d.key]);
      if (now - hmiT > 250) { hmiT = now; for (const h of hmis) h(st) }
      controls.update();
      if (bbOk) controls.target.clamp(bbPad.min, bbPad.max);
      if (++fc % (sunMoves ? 4 : 24) === 1) renderer.shadowMap.needsUpdate = true;
      renderer.render(scene, cam);
      if (labelsOn) { if (fc % 12 === 1) occlusion(); layoutLabels() }
    } catch (e) {
      // 그리기 중 오류가 나면 멈추고 호출 측(P&ID 대체)에 알린다 — 같은 오류를 매 프레임 반복하지 않게
      console.error(e); cancelAnimationFrame(raf); raf = 0; broken = true; opt.onError?.(e);
    }
  }
  const kick = () => { if (alive && !broken && !raf) { last = performance.now(); raf = requestAnimationFrame(loop) } };
  const io = 'IntersectionObserver' in window ? new IntersectionObserver(es => { inView = es[es.length - 1].isIntersecting; if (inView) kick() }) : null;
  io?.observe(box);
  const onVis = () => { if (!document.hidden) kick() };
  document.addEventListener('visibilitychange', onVis);
  const ro = new ResizeObserver(() => { const [w, h] = size(); if (!w || !h) return; renderer.setSize(w, h); cam.aspect = w / h; cam.updateProjectionMatrix(); labels.forEach(l => l.w = 0); kick() });
  ro.observe(box);
  controls.addEventListener('change', kick);
  kick();

  function dispose(){
    if (!alive) return; alive = false;
    cancelAnimationFrame(raf); io?.disconnect(); ro.disconnect(); document.removeEventListener('visibilitychange', onVis); mq?.removeEventListener?.('change', theme);
    controls.dispose();
    const mats = new Set(), texs = new Set();
    scene.traverse(o => { o.geometry?.dispose(); const ms = Array.isArray(o.material) ? o.material : o.material ? [o.material] : []; ms.forEach(m => mats.add(m)); o.userData.m0 && mats.add(o.userData.m0) });
    Object.values(M).forEach(m => m.isMaterial && mats.add(m)); shellMats.forEach(m => mats.add(m)); hlCache.forEach(m => mats.add(m));
    mats.forEach(m => { for (const k in m) if (m[k] && m[k].isTexture) texs.add(m[k]); m.dispose() });
    texs.forEach(t => t.dispose()); geoCache.forEach(g => g.dispose()); env.dispose();
    renderer.dispose(); renderer.forceContextLoss(); canvas.remove(); layer.remove();
  }
  return {
    select,
    setCut(on){ cut = on; const s = selId; select(null); hlCache.forEach(m => m.dispose()); hlCache.clear(); applyCut(); select(s); kick() },
    setRotate(on){ controls.autoRotate = on; kick() },
    setLabels(on){ labelsOn = on; layoutLabels(); kick() },
    resetView(){ resetView(); kick() },
    dispose,
  };
}

// ================================================================ 방식별 빌더
const BUILD = {
  // ---------------------------------------------------------- 파일럿 동결건조기
  '동결건조'(K){
    const {T3, M, S, part, front, on, mesh, grp, box, cyl, capsule, lathe, rbox, plate, pipe, flange, motor, vanePump, butterfly, dial, hmi, tray, chunks, crystals, flow, curve, along, Helix} = K;
    const BW = 2.1, BH = .78, BD = .9;
    // 하부 캐비닛 = 냉동기 수납부
    const rf = part('refrig', [.5, .52, .05]);
    mesh(rbox(BW - .02, .07, BD - .04, .01), M.dark, rf, [0, .035, 0]);
    mesh(rbox(BW, .03, BD, .01), S.paint, rf, [0, BH - .015, 0]);
    mesh(box(BW - .04, BH - .1, .02), S.paint, rf, [0, BH / 2 + .02, -BD / 2 + .01]);
    for (const s of [-1, 1]) mesh(box(.02, BH - .1, BD), S.paint, rf, [s * (BW / 2 - .01), BH / 2 + .02, 0]);
    mesh(box(BW - .04, BH - .1, .02), S.paint, rf, [0, BH / 2 + .02, BD / 2 - .01]);
    for (let i = 0; i < 7; i++) mesh(box(.42, .014, .012), S.dark, rf, [.62, .2 + i * .055, BD / 2 + .004]);
    for (const x of [.3, .68]) {
      mesh(capsule(.11, .14), M.compressor, rf, [x, .33, -.12]);
      for (const dx of [-.07, .07]) mesh(cyl(.02, .02, .04, 12), M.rubber, rf, [x + dx, .09, -.12]);
    }
    mesh(cyl(.07, .07, .4, 24), M.steelDark, rf, [-.3, .2, -.2], [0, 0, Math.PI / 2]);
    mesh(rbox(.05, .5, .62, .005), M.fins, rf, [-.9, .42, 0]);
    pipe(rf, [[.3, .5, -.12], [.3, .62, -.12], [.68, .62, -.12], [.68, .5, -.12]], .012, M.copper);
    pipe(rf, [[-.1, .2, -.2], [.2, .2, -.2], [.2, .58, -.2], [.3, .58, -.2]], .01, M.copper);
    pipe(rf, [[.5, .62, -.12], [.5, 1.06, -.12]], .02, M.insul);
    pipe(rf, [[.84, .5, -.05], [.84, 1.06, -.05]], .02, M.insul);
    // 건조 챔버
    const CX = -.5, CW = .9, CH = 1.0, CD = .8, CY = BH + CH / 2, T = .03;
    const ch = part('chamber', [CX - .3, CY + CH / 2 + .02, -.3]);
    mesh(box(CW, T, CD), S.steel, ch, [CX, CY + CH / 2 - T / 2, 0]);
    mesh(box(CW, T, CD), S.steel, ch, [CX, CY - CH / 2 + T / 2, 0]);
    for (const s of [-1, 1]) mesh(box(T, CH, CD), S.steel, ch, [CX + s * (CW / 2 - T / 2), CY, 0]);
    mesh(box(CW, CH, T), S.steel, ch, [CX, CY, -CD / 2 + T / 2]);
    mesh(plate(CW + .06, CH + .06, .04, [{w: CW - .08, h: CH - .08}]), S.steel, ch, [CX, CY, CD / 2 + .02]);
    // 투명 도어(절개 보기에서 숨김)
    const dr = front(part('door', [CX + .33, CY + .3, CD / 2 + .08]));
    mesh(rbox(CW - .01, CH - .01, .035, .012), M.acrylic, dr, [CX, CY, CD / 2 + .065]);
    mesh(plate(CW - .01, CH - .01, .006, [{w: CW - .07, h: CH - .07}]), M.rubber, dr, [CX, CY, CD / 2 + .045]);
    for (const dy of [-.33, .33]) { mesh(cyl(.022, .022, .13, 16), M.steel, dr, [CX - CW / 2 - .045, CY + dy, CD / 2 + .07]); mesh(rbox(.12, .045, .03, .006), M.steel, dr, [CX - CW / 2 + .01, CY + dy, CD / 2 + .085]) }
    mesh(rbox(.03, .28, .03, .01), M.steelDark, dr, [CX + CW / 2 - .07, CY, CD / 2 + .135]);
    for (const dy of [-.1, .1]) mesh(cyl(.01, .01, .05, 10), M.steel, dr, [CX + CW / 2 - .07, CY + dy, CD / 2 + .105], [Math.PI / 2, 0, 0]);
    // 가열 선반 4단 + 열매체 호스 + 트레이·시료·얼음
    const ys = [0, 1, 2, 3].map(i => BH + .14 + i * .2);
    const sh = part('shelves', [CX + .42, ys[2], .22]);
    const tr = part('trays', [CX - .12, ys[3] + .06, .2]);
    const shelfMat = M.steel.clone(); shelfMat.emissive = new T3.Color(0); shelfMat.emissiveIntensity = .3;
    const ices = [];
    ys.forEach((y, i) => {
      mesh(rbox(.8, .028, .62, .006), shelfMat, sh, [CX, y, 0]);
      pipe(sh, [[CX + .36, y - .005, -.3], [CX + .36, y - .005, -.335], [CX + .395, y - .07, -.345]], .009, M.hose, .03);
      tray(tr, [CX, y + .014, 0], .74, .56, {h: .03});
      const c = chunks(tr, [CX, y + .018, 0], .7, .52, 70, 11 + i, 0xc29a62, .026);
      ices.push(crystals(c, 90));
    });
    mesh(cyl(.014, .014, .88, 16), M.steel, sh, [CX + .395, BH + .48, -.345]);
    for (const x of [CX - .41, CX + .41]) mesh(cyl(.01, .01, .92, 10), M.steel, sh, [x, BH + .48, .33]);
    pipe(tr, [[CX + .1, ys[1] + .03, .1], [CX + .2, ys[1] + .14, .2], [CX + .41, ys[1] + .14, .25]], .003, M.dark, .05);
    const cold = new T3.Color(0x2b6cb0), warm = new T3.Color(0xd9541e);
    on(st => { shelfMat.emissive.lerpColors(cold, warm, sat(((st.g.t_shelf ?? 0) + 45) / 80)); ices.forEach(f => f(st.a.ice ?? 0)) });
    // 진공 게이지(챔버 위)
    const top = CY + CH / 2;
    const ga = part('gauge', [CX - .22, top + .38, .06]);
    mesh(cyl(.02, .02, .12, 16), M.steel, ga, [CX - .22, top + .06, .05]);
    flange(ga, [CX - .22, top + .12, .05], 'y', .02, 4);
    mesh(cyl(.035, .035, .1, 24), M.steelDark, ga, [CX - .22, top + .18, .05]);
    dial(ga, [CX - .22, top + .31, .06], [-.15, 0, 0], .075, {key: 'p_ch', min: 1, max: 1e5, log: true, ticks: [[1, '1'], [10, '10'], [100, '100'], [1e3, '1k'], [1e4, '10k'], [1e5, '100k']], unit: 'Pa', title: '챔버 압력'});
    // 증기 덕트 + 메인 밸브
    const DY = CY + .05, KX0 = .31, KX1 = 1.0, KR = .3;
    const du = part('duct', [.2, DY + .16, .12]);
    pipe(du, [[CX + CW / 2, DY, 0], [KX0 - .05, DY, 0]], .085);
    flange(du, [CX + CW / 2 + .015, DY, 0], 'x', .085, 8); flange(du, [KX0 - .07, DY, 0], 'x', .085, 8);
    const va = part('valve', [.06, DY + .32, .1]);
    flange(va, [-.01, DY, 0], 'x', .085, 8); flange(va, [.13, DY, 0], 'x', .085, 8);
    butterfly(va, [.06, DY, 0], 'x', .085);
    // 콘덴서(가로형 원통) + 냉각 코일 + 성에
    const cn = part('condenser', [.95, DY + .38, .1]);
    mesh(cyl(KR, KR, KX1 - KX0, 56, true), S.steel, cn, [(KX0 + KX1) / 2, DY, 0], [0, 0, Math.PI / 2]);
    mesh(lathe([[0, .09], [.12, .085], [.22, .06], [.28, .03], [KR, 0]], 56), S.steel, cn, [KX0, DY, 0], [0, 0, Math.PI / 2]);
    flange(cn, [KX1 + .02, DY, 0], 'x', KR * .72, 12, S.steel, true);
    mesh(cyl(KR * .82, KR * .82, .015, 48), M.acrylic, cn, [KX1 + .045, DY, 0], [0, 0, Math.PI / 2]);
    const helix = new Helix(.21, KX0 + .06, KX1 - .08, 9, DY, 0);
    mesh(new T3.TubeGeometry(helix, 360, .012, 8, false), M.copper, cn);
    const frosts = [[.02, .06], [.028, .3], [.036, .55], [.045, .8]].map(([r, th]) => { const m = mesh(new T3.TubeGeometry(helix, 360, r, 8, false), M.frost, cn); m.visible = false; return [m, th] });
    on(st => frosts.forEach(([m, th]) => m.visible = (st.a.frost ?? 0) > th));
    for (const x of [.45, .86]) mesh(rbox(.08, DY - KR - BH + .01, .5, .01), M.frame, cn, [x, BH + (DY - KR - BH) / 2, 0]);
    pipe(cn, [[.92, DY - KR + .02, .08], [.92, BH + .06, .08], [.92, BH + .06, .42]], .012, M.steel, .04);
    mesh(K.sph(.024), M.steel, cn, [.92, BH + .06, .33]); mesh(box(.012, .012, .08), M.red, cn, [.92, BH + .1, .33]);
    // 진공 펌프 + 진공 배관
    const vp = part('vacpump', [1.62, .5, .1]);
    vanePump(vp, [1.6, 0, 0]);
    pipe(vp, [[.85, DY + KR - .03, 0], [.85, DY + KR + .14, 0], [1.64, DY + KR + .14, 0], [1.64, .36, 0]], .022, M.steel, .08);
    flange(vp, [.85, DY + KR + .02, 0], 'y', .022, 4);
    // 제어반(스윙 암 HMI)
    const pn = part('panel', [-1.32, 1.68, .3]);
    pipe(pn, [[CX - CW / 2, 1.42, -.15], [-1.3, 1.42, -.15], [-1.3, 1.42, .1]], .02, M.steel, .06);
    hmi(pn, [-1.3, 1.45, .17], [-.08, .4, 0], .46, .3, '동결건조 레시피');
    // 수증기 흐름: 트레이 위 → 덕트 → 콘덴서 코일
    const R = rnd(77), curves = [];
    for (let i = 0; i < 28; i++) {
      const k = i % 4, y = ys[k] + .06, x = CX + (R() - .5) * .6, z = (R() - .5) * .45;
      curves.push(curve([[x, y, z], [x + .05, y + .08, z * .8], [CX + .36, DY + (R() - .5) * .08, z * .3], [CX + CW / 2 + .05, DY, 0], [.2, DY, 0], [.45 + R() * .45, DY + (R() - .5) * .3, (R() - .5) * .3]]));
    }
    flow({n: 170, size: .011, color: 0xe3eef8, key: 'vapor', speed: [.12, .2], path: along(curves, .02)});
    return {pos: [2.4, 2.05, 3.5], target: [.15, 1.05, 0]};
  },

  // ---------------------------------------------------------- 캐비닛형 열풍 트레이 건조기
  '열풍건조'(K){
    const {T3, M, S, part, front, on, spin, mesh, grp, box, cyl, rbox, pipe, motor, hmi, tray, chunks, flow, curve, along, heatColor} = K;
    const W = 1.5, H = 1.85, D = 1.1, Y0 = .1, T = .06, TOP = Y0 + H;
    const cab = part('cabinet', [-.6, TOP + .02, -.42]);
    for (const x of [-1, 1]) for (const z of [-1, 1]) mesh(box(.06, Y0, .06), S.dark, cab, [x * (W / 2 - .06), Y0 / 2, z * (D / 2 - .06)]);
    // 벽 = 단열재 심 + 바깥 도장 철판 + 안쪽 스테인리스
    const wall = (sz, p, ax, sign) => {
      mesh(box(...sz), S.wool, cab, p);
      const i = 'xyz'.indexOf(ax), thin = [...sz]; thin[i] = .004;
      const o = [...p], n = [...p]; o[i] += sign * (sz[i] / 2 + .002); n[i] -= sign * (sz[i] / 2 + .002);
      mesh(box(...thin), S.paint, cab, o); mesh(box(...thin), S.steel, cab, n);
    };
    wall([W, H, T], [0, Y0 + H / 2, -D / 2 + T / 2], 'z', -1);
    wall([T, H, D - 2 * T], [-W / 2 + T / 2, Y0 + H / 2, T / 2 * 0], 'x', -1);
    wall([T, H, D - 2 * T], [W / 2 - T / 2, Y0 + H / 2, 0], 'x', 1);
    wall([W - 2 * T, T, D - 2 * T], [0, TOP - T / 2, 0], 'y', 1);
    wall([W - 2 * T, T, D - 2 * T], [0, Y0 + T / 2, 0], 'y', -1);
    mesh(box(.45, H, T), S.paint, cab, [.525, Y0 + H / 2, D / 2 - T / 2]);
    // 도어
    const dr = front(part('door', [-.6, 1.3, D / 2 + .05]));
    mesh(rbox(1.05, H - .02, T, .012), M.paint, dr, [-.225, Y0 + H / 2, D / 2 - T / 2 + .004]);
    for (const y of [.5, 1.55]) mesh(cyl(.022, .022, .16, 16), M.steel, dr, [-W / 2 + .01, y, D / 2 + .01]);
    for (const y of [.75, 1.35]) { mesh(rbox(.06, .12, .03, .008), M.steelDark, dr, [.22, y, D / 2 + .02]); mesh(rbox(.035, .16, .025, .01), M.dark, dr, [.22, y - .04, D / 2 + .045]) }
    mesh(box(.16, .1, .004), M.dark, dr, [-.5, 1.7, D / 2 + .004]);
    // 분배판(타공) + 천장 칸막이 + 팬 칸막이
    const du = part('duct', [.3, .55, .36]);
    mesh(box(.006, 1.42, D - 2 * T), M.perf, du, [.3, Y0 + T + .71, 0]);
    mesh(box(.9, .006, D - 2 * T), M.steel, du, [-.15, 1.62, 0]);
    mesh(K.plate(.39, D - 2 * T, .006, [{r: .19}]), M.steel, du, [.495, 1.62, 0], [-Math.PI / 2, 0, 0]);
    // 순환 송풍기(축류) + 위쪽 모터
    const fa = part('fan', [.5, 2.32, .1]);
    mesh(cyl(.2, .2, .09, 40, true), M.steelDark, fa, [.495, 1.67, 0]);
    const rot = grp(fa, [.495, 1.67, 0]);
    mesh(cyl(.045, .045, .06, 20), M.dark, rot);
    for (let i = 0; i < 6; i++) mesh(box(.13, .006, .06), M.clad, grp(rot, null, [0, i * Math.PI / 3, 0]), [.1, 0, 0], [.4, 0, 0]);
    spin(rot, 'y', 16, 'fan');
    motor(fa, [.495, TOP + .26, 0], .075, .22, {dir: 'down'});
    // 히터 뱅크(핀 튜브 2열 × 3단)
    const ht = part('heater', [.68, 1.4, .4]);
    const pos = [];
    for (const x of [.42, .57]) for (const y of [1.3, 1.41, 1.52]) pos.push([x, y]);
    const finN = 38, fins = new T3.InstancedMesh(cyl(.034, .034, .003, 20), M.finHot, pos.length * finN);
    const dm = new T3.Object3D();
    pos.forEach(([x, y], k) => {
      mesh(cyl(.011, .011, D - 2 * T - .04, 12), M.heater, ht, [x, y, 0], [Math.PI / 2, 0, 0]);
      for (let i = 0; i < finN; i++) { dm.position.set(x, y, -.44 + i * .0238); dm.rotation.set(Math.PI / 2, 0, 0); dm.updateMatrix(); fins.setMatrixAt(k * finN + i, dm.matrix) }
      mesh(cyl(.016, .016, .05, 6), M.steelDark, ht, [x, y, -D / 2 - .02], [Math.PI / 2, 0, 0]);
    });
    fins.castShadow = true; ht.add(fins);
    mesh(rbox(.3, .18, .08, .01), M.paint, ht, [.5, 1.41, -D / 2 - .05]);
    on(st => { const h = st.a.heat ?? 0; M.heater.emissiveIntensity = 2.6 * h; M.finHot.emissiveIntensity = .4 * h });
    // 트레이 대차
    const tl = part('trolley', [-.62, .2, .45]);
    K.frame(tl, [-.2, .26, 0], .84, .84, 1.28, {t: .025, mat: M.steel, rails: [0], feet: false});
    for (const x of [-.58, .18]) for (const z of [-.38, .38]) { mesh(cyl(.04, .04, .03, 20), M.rubber, tl, [x, .2, z], [0, 0, Math.PI / 2]); mesh(box(.05, .06, .05), M.steelDark, tl, [x, .245, z]) }
    pipe(tl, [[-.55, 1.0, .42], [-.55, 1.0, .48], [.15, 1.0, .48], [.15, 1.0, .42]], .012, M.steel, .03);
    // 타공 트레이 8단 + 시료(수축·갈변)
    const trp = part('trays', [-.2, 1.42, .42]);
    const chs = [];
    for (let i = 0; i < 8; i++) {
      const y = .34 + i * .15;
      for (const s of [-1, 1]) mesh(box(.02, .006, .82), M.steel, tl, [-.2 + s * .405, y - .004, 0]);
      tray(trp, [-.2, y, 0], .8, .8, {h: .025, perf: true});
      chs.push(chunks(trp, [-.2, y + .004, 0], .76, .76, 55, 30 + i, 0xa8743f, .028));
    }
    on(st => { const m = st.a.moisture ?? 1; chs.forEach(c => c.set(.55 + .45 * m, sat((1 - m) * 1.6))) });
    // 외기 흡입 댐퍼(위 오른쪽 뒤)
    const inl = part('inlet', [.5, TOP + .32, -.3]);
    mesh(rbox(.26, .14, .22, .01), M.paint, inl, [.5, TOP + .07, -.33]);
    mesh(box(.32, .01, .3), M.paint, inl, [.5, TOP + .24, -.33], [.2, 0, 0]);
    for (const x of [.36, .64]) mesh(box(.01, .1, .01), M.steelDark, inl, [x, TOP + .18, -.33]);
    const blades = [0, 1, 2].map(i => mesh(box(.22, .035, .006), M.steelDark, inl, [.5, TOP + .035 + i * .035, -.218]));
    // 배기 연통 + 댐퍼 + 갓
    const ex = part('exhaust', [-.5, TOP + .62, -.25]);
    mesh(cyl(.075, .075, .5, 32, true), M.steel, ex, [-.5, TOP + .25, -.25]);
    K.flange(ex, [-.5, TOP + .01, -.25], 'y', .075, 6, M.steel, true);
    const disc = mesh(cyl(.07, .07, .006, 24), M.steelDark, ex, [-.5, TOP + .16, -.25]);
    mesh(box(.12, .012, .012), M.red, ex, [-.43, TOP + .16, -.25]);
    mesh(cyl(.005, .14, .07, 32), M.steel, ex, [-.5, TOP + .6, -.25]);
    for (let i = 0; i < 3; i++) { const a = i * Math.PI * 2 / 3; mesh(box(.006, .08, .006), M.steel, ex, [-.5 + Math.cos(a) * .07, TOP + .53, -.25 + Math.sin(a) * .07]) }
    on(st => { const d = st.a.damper ?? .5; blades.forEach(b => b.rotation.x = (1 - d) * 1.2); disc.rotation.x = (1 - d) * 1.3 });
    // 온습도 센서
    const se = part('sensor', [-.1, TOP + .2, .05]);
    mesh(rbox(.1, .12, .06, .01), M.white, se, [-.1, TOP + .06, .05]);
    mesh(cyl(.008, .008, .3, 10), M.steel, se, [-.1, TOP - .12, .05]);
    mesh(cyl(.014, .014, .05, 12), M.dark, se, [-.1, 1.74, .05]);
    // 제어반(오른쪽 옆면)
    const pn = part('panel', [W / 2 + .06, 1.5, -.12]);
    mesh(rbox(.06, .52, .42, .01), M.paint, pn, [W / 2 + .03, 1.2, -.12]);
    hmi(pn, [W / 2 + .07, 1.28, -.12], [0, Math.PI / 2, 0], .32, .21, '열풍 건조 제어');
    mesh(cyl(.035, .035, .02, 20), M.yellow, pn, [W / 2 + .065, .98, -.12], [0, 0, Math.PI / 2]);
    mesh(box(.02, .06, .015), M.red, pn, [W / 2 + .08, .98, -.12]);
    // 공기 흐름: 송풍기 → 히터 → 분배판 → 트레이 사이(횡류) → 왼쪽 → 천장 위 → 송풍기
    const curves = [];
    for (let k = 0; k < 8; k++) {
      const y = .34 + k * .15 + .075;
      for (const z of [-.3, -.1, .1, .3]) curves.push(curve([[.49, 1.6, z * .5], [.5, 1.35, z], [.42, y + .02, z], [.3, y, z], [-.2, y, z], [-.6, y + .02, z], [-.66, Math.min(y + .25, 1.55), z], [-.66, 1.7, z], [-.1, 1.78, z * .7], [.4, 1.76, z * .3]]));
    }
    const tempAt = t => t < .12 ? .45 + .55 * t / .12 : t < .28 ? 1 : t < .55 ? 1 - .5 * (t - .28) / .27 : .5 - .1 * (t - .55) / .45;
    flow({n: 320, size: .012, key: 'fan', speed: [.06, .09], path: along(curves, .03), tint: (i, t, c, st) => heatColor(c, tempAt(t) * sat(((st.g.t_in ?? 60) - 15) / 50))});
    flow({n: 50, size: .02, color: 0xdfe8f0, key: 'vapor', speed: [.25, .4], opacity: .55,
      path: (i, t, o, s) => o.set(-.5 + (s - .5) * .08 + Math.sin(t * 6 + s * 9) * .05 * t, TOP + .62 + t * .7, -.25 + ((s * 7) % 1 - .5) * .08),
      scale: (i, t) => (1 + t * 1.5) * Math.min(1, (1 - t) * 4, t * 8)});
    flow({n: 30, size: .012, color: 0x8fb8de, key: 'damper', speed: [.3, .45], path: along([curve([[.5, TOP + .45, .0], [.5, TOP + .3, -.15], [.5, TOP + .1, -.33], [.5, 1.8, -.33], [.5, 1.7, -.2]])], .05)});
    return {pos: [2.9, 2.2, 3.9], target: [0, 1.05, 0]};
  },

  // ---------------------------------------------------------- 진공 선반 건조기
  '진공건조'(K){
    const {T3, M, S, part, front, on, mesh, box, cyl, lathe, rbox, plate, pipe, flange, frame, vanePump, handwheel, dial, hmi, tray, chunks, flow, curve, along} = K;
    const CX = -.25, CW = 1.0, CH = .9, CD = .8, Y0 = .58, CY = Y0 + CH / 2, T = .035, TOP = Y0 + CH;
    const ch = part('chamber', [CX - .3, TOP + .06, -.3]);
    frame(ch, [CX, 0, 0], CW - .04, CD - .1, Y0, {rails: [.12]});
    mesh(box(CW, T, CD), S.steel, ch, [CX, TOP - T / 2, 0]);
    mesh(box(CW, T, CD), S.steel, ch, [CX, Y0 + T / 2, 0]);
    for (const s of [-1, 1]) mesh(box(T, CH, CD), S.steel, ch, [CX + s * (CW / 2 - T / 2), CY, 0]);
    mesh(box(CW, CH, T), S.steel, ch, [CX, CY, -CD / 2 + T / 2]);
    for (const x of [CX - .3, CX, CX + .3]) mesh(box(.03, .04, CD), S.steel, ch, [x, TOP + .02, 0]);
    for (const s of [-1, 1]) for (const y of [CY - .22, CY + .22]) mesh(box(.04, .03, CD), S.steel, ch, [CX + s * (CW / 2 + .02), y, 0]);
    mesh(plate(CW + .08, CH + .08, .05, [{w: CW - .1, h: CH - .1}]), S.steel, ch, [CX, CY, CD / 2 + .025]);
    // 두꺼운 도어 + 볼트 체결 관찰창 + 스윙 볼트 핸들
    const dr = front(part('door', [CX + .25, CY + .3, CD / 2 + .12]));
    mesh(plate(CW + .06, CH + .06, .07, [{r: .16, x: 0, y: .06}]), M.paint, dr, [CX, CY, CD / 2 + .085]);
    mesh(cyl(.17, .17, .02, 48), M.glass, dr, [CX, CY + .06, CD / 2 + .09], [Math.PI / 2, 0, 0]);
    flange(dr, [CX, CY + .06, CD / 2 + .13], 'z', .16, 12, M.steel, true);
    for (const dy of [-.28, .28]) { mesh(cyl(.035, .035, .16, 20), M.steelDark, dr, [CX - CW / 2 - .07, CY + dy, CD / 2 + .08]); mesh(rbox(.1, .06, .05, .008), M.steelDark, dr, [CX - CW / 2 - .02, CY + dy, CD / 2 + .1]) }
    for (const dy of [-.26, .26]) { mesh(cyl(.012, .012, .1, 10), M.steel, dr, [CX + CW / 2 - .04, CY + dy, CD / 2 + .15], [Math.PI / 2, 0, 0]); handwheel(dr, [CX + CW / 2 - .04, CY + dy, CD / 2 + .2], .045) }
    // 온수 재킷 선반 3단
    const ys = [Y0 + .14, Y0 + .4, Y0 + .66];
    const pl = part('plates', [CX + .45, ys[1], .3]);
    const tr = part('trays', [CX - .1, ys[2] + .07, .25]);
    const plMat = M.steel.clone(); plMat.emissive = new T3.Color(0xd9541e); plMat.emissiveIntensity = 0;
    const chs = [];
    for (const [i, y] of ys.entries()) {
      mesh(rbox(.82, .04, .6, .008), plMat, pl, [CX, y, .02]);
      pipe(pl, [[CX - .41, y, -.2], [CX - .45, y, -.2]], .01, M.hoseRed);
      pipe(pl, [[CX - .41, y, -.26], [CX - .45, y, -.26]], .01, M.hoseBlue);
      tray(tr, [CX, y + .02, .02], .78, .54, {h: .035});
      chs.push(chunks(tr, [CX, y + .024, .02], .74, .5, 55, 40 + i, 0xa97a45, .026));
    }
    mesh(cyl(.013, .013, .74, 12), M.hoseRed, pl, [CX - .45, Y0 + .4, -.2]);
    mesh(cyl(.013, .013, .74, 12), M.hoseBlue, pl, [CX - .45, Y0 + .4, -.26]);
    on(st => { const h = st.a.heat ?? 0; plMat.emissiveIntensity = .28 * h; const m = st.a.moisture ?? 1; chs.forEach(c => c.set(.7 + .3 * m, sat((1 - m) * 1.2))) });
    flow({n: 220, size: .008, color: 0xd5ecff, key: 'bubble', speed: [.5, .9], opacity: .75,
      path: (i, t, o, s) => o.set(CX + ((s * 13.7) % 1 - .5) * .7, ys[i % 3] + .05 + t * .07, .02 + ((s * 7.3) % 1 - .5) * .46),
      scale: (i, t) => (.6 + t * 1.3) * (t < .92 ? 1 : 0)});
    // 압력계 + 진공 해제 밸브(위)
    const ga = part('gauge', [CX - .25, TOP + .36, .2]);
    mesh(cyl(.016, .016, .14, 12), M.steel, ga, [CX - .25, TOP + .07, .2]);
    dial(ga, [CX - .25, TOP + .22, .22], [-.2, 0, 0], .08, {key: 'p_ch', min: 0, max: 101.325, scale: v => v / 1000, ticks: [[0, '0'], [20, '20'], [40, '40'], [60, '60'], [80, '80'], [100, '100']], unit: 'kPa', title: '챔버 압력'});
    const va = part('valve', [CX + .15, TOP + .2, .25]);
    mesh(cyl(.014, .014, .08, 12), M.steel, va, [CX + .15, TOP + .04, .2]);
    mesh(K.sph(.03), M.steel, va, [CX + .15, TOP + .1, .2]);
    mesh(cyl(.025, .025, .04, 20), M.dark, va, [CX + .15, TOP + .15, .2]);
    mesh(cyl(.018, .018, .06, 16), M.white, va, [CX + .2, TOP + .1, .2], [0, 0, Math.PI / 2]);
    // 응축기(세로형) + 냉각수 + 응축수 플라스크
    const KXc = .62, KZ = -.15;
    const cn = part('condenser', [KXc + .2, 1.25, KZ + .1]);
    pipe(cn, [[CX + CW / 2, 1.3, KZ], [KXc, 1.3, KZ], [KXc, 1.2, KZ]], .03, M.steel, .08);
    flange(cn, [CX + CW / 2 + .015, 1.3, KZ], 'x', .03, 6);
    mesh(cyl(.13, .13, .45, 40), M.steel, cn, [KXc, .925, KZ]);
    mesh(lathe([[0, .05], [.08, .045], [.12, .025], [.13, 0]], 40), M.steel, cn, [KXc, 1.15, KZ]);
    mesh(lathe([[.13, 0], [.12, -.025], [.08, -.045], [0, -.05]], 40), M.steel, cn, [KXc, .7, KZ]);
    for (let i = 0; i < 3; i++) { const a = i * Math.PI * 2 / 3 + .5; mesh(box(.025, .7, .025), M.frame, cn, [KXc + Math.cos(a) * .14, .35, KZ + Math.sin(a) * .14]) }
    pipe(cn, [[KXc, .78, KZ - .12], [KXc, .78, -.6]], .016, M.hoseBlue);
    pipe(cn, [[KXc, 1.06, KZ - .12], [KXc, 1.06, -.6]], .016, M.hoseBlue);
    pipe(cn, [[KXc, .65, KZ], [KXc, .52, KZ]], .012, M.steel);
    mesh(lathe([[0, 0], [.08, 0], [.09, .02], [.09, .2], [.06, .24], [.035, .26], [.035, .29]], 40), M.glass, cn, [KXc, .22, KZ]);
    const water = mesh(cyl(.082, .082, .2, 32), M.water, cn, [KXc, .32, KZ]);
    on(st => { const f = Math.max(.03, sat((1 - (st.a.moisture ?? 1)) / .4)); water.scale.y = f; water.position.y = .222 + .1 * f });
    // 진공 펌프
    const vp = part('vacpump', [1.25, .52, KZ + .1]);
    vanePump(vp, [1.2, 0, KZ]);
    pipe(vp, [[KXc + .13, .95, KZ], [1.24, .95, KZ], [1.24, .36, KZ]], .022, M.steel, .07);
    // 온수 순환기
    const ci = part('circulator', [-1.18, .7, .1]);
    mesh(rbox(.36, .56, .44, .02), M.white, ci, [-1.18, .3, -.05]);
    mesh(rbox(.3, .03, .36, .01), M.dark, ci, [-1.18, .595, -.05]);
    hmi(ci, [-1.18, .44, .175], [0, 0, 0], .2, .1, '온수', ['t_plate']);
    pipe(ci, [[-1.1, .6, -.15], [-1.1, .72, -.2], [CX - CW / 2 - .005, .72, -.2]], .018, M.hoseRed, .08);
    pipe(ci, [[-1.25, .6, -.2], [-1.25, .66, -.26], [CX - CW / 2 - .005, .66, -.26]], .018, M.hoseBlue, .06);
    // 제어반
    const pn = part('panel', [CX + CW / 2 + .12, 1.02, .02]);
    mesh(rbox(.04, .26, .34, .008), M.paint, pn, [CX + CW / 2 + .02, .86, -.17]);
    hmi(pn, [CX + CW / 2 + .045, .86, -.17], [0, Math.PI / 2, 0], .3, .2, '진공 건조 제어');
    // 수증기: 트레이 → 오른쪽 포트 → 응축기
    const R = rnd(55), curves = [];
    for (let i = 0; i < 24; i++) { const y = ys[i % 3] + .07, x = CX + (R() - .5) * .6, z = (R() - .5) * .4; curves.push(curve([[x, y, z], [x + .05, y + .1, z], [CX + .4, 1.3, KZ * .6], [CX + CW / 2 + .05, 1.3, KZ], [KXc - .05, 1.3, KZ], [KXc, 1.15, KZ], [KXc + (R() - .5) * .12, .8, KZ + (R() - .5) * .12]])) }
    flow({n: 130, size: .011, color: 0xe3eef8, key: 'vapor', speed: [.15, .25], path: along(curves, .015)});
    return {pos: [2.3, 1.75, 3.0], target: [0, .9, 0]};
  },

  // ---------------------------------------------------------- 파일럿 분무건조기
  '분무건조'(K){
    const {T3, M, S, part, on, spin, mesh, grp, box, cyl, lathe, rbox, pipe, flange, frame, motor, dial, hmi, flow, curve, along, heatColor, env01} = K;
    const rAt = y => y >= 1.86 ? .5 : y <= 1.06 ? .07 : .07 + (y - 1.06) / .8 * .43;
    // 건조탑(원통 + 원뿔, 회전체)
    const chm = part('chamber', [-.5, 2.25, .3]);
    mesh(lathe([[.04, .9], [.045, 1.0], [.07, 1.06], [.5, 1.86], [.5, 2.56], [.49, 2.6], [.17, 2.64], [.17, 2.65]], 72), S.steel, chm);
    for (const [x, z] of [[-.58, -.58], [.58, -.58], [-.58, .58], [.58, .58]]) { mesh(box(.06, 1.9, .06), M.frame, chm, [x, .95, z]); mesh(cyl(.045, .045, .02, 12), M.rubber, chm, [x, .01, z]) }
    for (const y of [1.87, .45]) for (const s of [-1, 1]) { mesh(box(1.22, y > 1 ? .07 : .04, .05), M.frame, chm, [0, y, s * .58]); mesh(box(.05, y > 1 ? .07 : .04, 1.22), M.frame, chm, [s * .58, y, 0]) }
    for (const [x, z] of [[0, .53], [0, -.53], [.53, 0], [-.53, 0]]) mesh(box(.08, .05, .08), M.steel, chm, [x, 1.9, z]);
    mesh(cyl(.22, .22, .14, 48), S.steel, chm, [0, 2.72, 0]);
    flange(chm, [0, 2.79, 0], 'y', .14, 12, M.steel, true);
    // 회전 원판 분무기
    const at = part('atomizer', [.15, 3.12, .1]);
    mesh(cyl(.1, .1, .03, 32), M.steel, at, [0, 2.82, 0]);
    motor(at, [0, 2.84, 0], .085, .26, {dir: 'up'});
    mesh(cyl(.012, .012, .32, 12), M.steel, at, [0, 2.66, 0]);
    const wheel = grp(at, [0, 2.52, 0]);
    mesh(cyl(.055, .055, .025, 32), M.steel, wheel);
    for (let i = 0; i < 8; i++) mesh(box(.05, .02, .006), M.steelDark, grp(wheel, null, [0, i * Math.PI / 4, 0]), [.03, 0, 0]);
    spin(wheel, 'y', 30, 'atom');
    // 공기 필터 → 급기 송풍기 → 가열기 → 열풍 덕트
    const fi = part('filter', [-2.35, .8, .12]);
    frame(fi, [-2.35, 0, 0], .34, .4, .2, {rails: [], t: .03});
    mesh(rbox(.36, .44, .42, .015), M.paint, fi, [-2.35, .42, 0]);
    mesh(box(.004, .36, .34), M.fins, fi, [-2.535, .42, 0]);
    const volute = K.cached('volute', () => {
      const s = new T3.Shape(); s.moveTo(.14, .32); s.lineTo(.14, 0);
      for (let i = 1; i <= 48; i++) { const a = i / 48 * Math.PI * 2, r = .14 * (1 + .45 * a / (Math.PI * 2)); s.lineTo(Math.cos(a) * r, Math.sin(a) * r) }
      s.lineTo(.203, .32); s.lineTo(.14, .32);
      const g = new T3.ExtrudeGeometry(s, {depth: .14, bevelEnabled: true, bevelThickness: .006, bevelSize: .006, bevelSegments: 2}); g.translate(0, 0, -.07); return g;
    });
    const blower = (g, x, y) => {
      mesh(volute, M.motor, g, [x, y, 0], [0, Math.PI / 2, 0]);
      flange(g, [x - .085, y, 0], 'x', .07, 6);
      mesh(box(.42, y - .22, .3), M.frame, g, [x + .12, (y - .22) / 2, 0]);
      motor(g, [x + .09, y, 0], .07, .2, {feet: false});
    };
    const bl = part('blower', [-1.85, .86, .2]);
    blower(bl, -1.85, .42);
    pipe(bl, [[-2.17, .42, 0], [-1.935, .42, 0]], .07, M.steel);
    const he = part('heater', [-1.62, 1.75, -.1]);
    pipe(he, [[-1.85, .74, -.17], [-1.85, 1.04, -.17]], .065, M.clad);
    mesh(rbox(.3, .62, .3, .02), M.clad, he, [-1.85, 1.35, -.17]);
    mesh(rbox(.12, .18, .14, .01), M.paint, he, [-1.66, 1.42, -.17]);
    for (const y of [1.08, 1.62]) flange(he, [-1.85, y, -.17], 'y', .07, 8);
    pipe(he, [[-1.85, 1.66, -.17], [-1.85, 2.72, -.17], [-.6, 2.72, -.17], [-.6, 2.72, 0], [-.22, 2.72, 0]], .07, M.clad, .2);
    const ti = part('ti_in', [-1.0, 3.06, -.1]);
    mesh(cyl(.012, .012, .12, 10), M.steel, ti, [-1.0, 2.84, -.17]);
    dial(ti, [-1.0, 2.95, -.15], null, .06, {key: 't_in', min: 0, max: 250, ticks: [[0, '0'], [50, '50'], [100, '100'], [150, '150'], [200, '200'], [250, '250']], unit: '℃', title: '입구'});
    // 원료액 탱크 → 연동 펌프 → 분무기
    const FX = -.3, PX = .25;
    const ft = part('feedtank', [FX - .05, 1.12, 1.0]);
    mesh(lathe([[0, .3], [.06, .31], [.2, .42], [.2, .86], [.21, .87], [.21, .89], [0, .89]], 48), M.steel, ft, [FX, 0, .95]);
    for (let i = 0; i < 3; i++) { const a = i * Math.PI * 2 / 3 + .3; mesh(cyl(.015, .015, .42, 10), M.steel, ft, [FX + Math.cos(a) * .17, .21, .95 + Math.sin(a) * .17]) }
    motor(ft, [FX, .89, .95], .05, .14, {dir: 'up', mat: M.white});
    const fp = part('feedpump', [PX + .03, .95, 1.15]);
    frame(fp, [PX, 0, .95], .34, .3, .55, {rails: [.15], t: .03});
    mesh(rbox(.2, .14, .16, .015), M.white, fp, [PX, .62, .95]);
    mesh(cyl(.075, .075, .05, 32), M.dark, fp, [PX, .62, 1.05], [Math.PI / 2, 0, 0]);
    const rotor = grp(fp, [PX, .62, 1.08]);
    for (let i = 0; i < 3; i++) { const a = i * Math.PI * 2 / 3; mesh(cyl(.015, .015, .03, 16), M.steel, rotor, [Math.cos(a) * .045, Math.sin(a) * .045, 0], [Math.PI / 2, 0, 0]) }
    spin(rotor, 'z', 4, 'spray');
    pipe(fp, [[FX, .3, .95], [FX, .24, .95], [PX - .15, .24, 1.1], [PX - .07, .58, 1.1], [PX, .69, 1.1]], .008, M.silicone, .05);
    pipe(fp, [[PX + .07, .6, 1.1], [.66, .6, 1.1], [.66, .6, .66], [.66, 2.9, .66], [.12, 2.9, .12], [.05, 2.86, .05]], .008, M.silicone, .08);
    // 출구 덕트 → 사이클론 → 수집병, 사이클론 → 백 필터 → 배기 송풍기
    const CXc = 1.3, CXb = 1.95;
    const cy = part('cyclone', [CXc + .2, 2.08, .15]);
    mesh(lathe([[.035, .98], [.035, 1.05], [.17, 1.55], [.17, 1.96], [.06, 1.99], [.06, 2.0]], 56), S.steel, cy, [CXc, 0, 0]);
    pipe(cy, [[0, .9, 0], [0, .72, 0], [.95, .72, 0], [.95, .72, -.13], [.95, 1.82, -.13], [CXc - .16, 1.82, -.13]], .05, M.steel, .12);
    for (let i = 0; i < 3; i++) { const a = i * Math.PI * 2 / 3 + .4; mesh(box(.035, 1.52, .035), M.frame, cy, [CXc + Math.cos(a) * .24, .76, Math.sin(a) * .24]) }
    mesh(K.torus(.24, .015), M.frame, cy, [CXc, 1.52, 0], [Math.PI / 2, 0, 0]);
    mesh(K.sph(.035), M.steel, cy, [CXc, .94, 0]); mesh(box(.1, .012, .015), M.red, cy, [CXc + .05, .97, 0]);
    pipe(cy, [[CXc, 1.85, 0], [CXc, 2.22, 0], [CXb, 2.22, 0], [CXb, 2.06, 0]], .055, M.steel, .12);
    const to = part('ti_out', [.5, 1.05, .1]);
    mesh(cyl(.01, .01, .1, 10), M.steel, to, [.5, .8, 0]);
    dial(to, [.5, .9, .03], null, .055, {key: 't_out', min: 0, max: 150, ticks: [[0, '0'], [30, '30'], [60, '60'], [90, '90'], [120, '120'], [150, '150']], unit: '℃', title: '출구'});
    const ja = part('jar', [CXc + .15, .62, .1]);
    mesh(lathe([[0, .6], [.09, .6], [.1, .62], [.1, .82], [.07, .86], [.05, .88], [.05, .91]], 40), M.glass, ja, [CXc, 0, 0]);
    mesh(K.torus(.055, .01), M.steel, ja, [CXc, .9, 0], [Math.PI / 2, 0, 0]);
    const pw = mesh(cyl(.092, .092, .2, 32), M.powder, ja, [CXc, .7, 0]);
    on(st => { const f = Math.max(.02, st.a.powder ?? 0); pw.scale.y = f; pw.position.y = .605 + .1 * f });
    const bf = part('bagfilter', [CXb + .28, 1.9, .1]);
    mesh(lathe([[.03, .55], [.03, .6], [.24, .92], [.24, 1.95], [.2, 2.02], [.06, 2.06]], 56), S.steel, bf, [CXb, 0, 0]);
    for (const [x, z] of [[-.2, -.2], [.2, -.2], [-.2, .2], [.2, .2]]) mesh(box(.035, 1.05, .035), M.frame, bf, [CXb + x, .525, z]);
    for (let i = 0; i < 3; i++) mesh(rbox(.05, .06, .05, .006), M.dark, bf, [CXb - .1 + i * .1, 2.0, .12]);
    pipe(bf, [[CXb - .15, 2.0, .2], [CXb + .15, 2.0, .2]], .015, M.steel);
    const exf = part('exhaust', [2.62, .9, .2]);
    blower(exf, 2.6, .42);
    pipe(exf, [[CXb + .24, 1.8, 0], [2.42, 1.8, 0], [2.42, .42, 0], [2.515, .42, 0]], .06, M.steel, .1);
    pipe(exf, [[2.6, .74, -.17], [2.6, 2.95, -.17]], .065, M.steel);
    mesh(cyl(.005, .13, .07, 32), M.steel, exf, [2.6, 3.02, -.17]);
    // 제어반
    const pn = part('panel', [-1.0, 1.62, -.95]);
    mesh(rbox(.5, 1.45, .28, .02), M.white, pn, [-1.0, .73, -1.05]);
    hmi(pn, [-1.0, 1.15, -.905], null, .36, .24, '분무 건조 제어');
    [M.green, M.yellow, M.red].forEach((m, i) => mesh(cyl(.03, .03, .06, 16), m, pn, [-.87, 1.5 + i * .065, -1.05]));
    // 입자: 액적(원판에서 퍼져 떨어지며 마름), 열풍 소용돌이, 분말(사이클론 나선), 배기
    const blue = new T3.Color(0x5fa8e6), tan = new T3.Color(0xd9b98a);
    flow({n: 320, size: .014, key: 'spray', speed: [.35, .55], tint: (i, t, c) => c.lerpColors(blue, tan, sat(t * 1.5)), scale: (i, t) => (1 - .5 * t) * env01(t),
      path: (i, t, o, s) => {
        const th = s * Math.PI * 14.6 + t * 2.2; let r, y;
        if (t < .1) { const u = t / .1; r = .06 + .36 * Math.pow(u, .7); y = 2.52 - .04 * u }
        else { const u = (t - .1) / .9; y = 2.48 - 1.42 * Math.pow(u, 1.1); r = Math.min(.42 * (.85 + .15 * s), rAt(y) * .85) }
        o.set(Math.cos(th) * r, y, Math.sin(th) * r);
      }});
    flow({n: 140, size: .012, key: 'heat', speed: [.3, .45], opacity: .6, tint: (i, t, c) => heatColor(c, 1 - .55 * t),
      path: (i, t, o, s) => { const th = s * Math.PI * 6.2 + t * 5, y = 2.62 - 1.5 * t, r = Math.min(lerp(.18, .44, sat(t * 4)), rAt(y) * .9); o.set(Math.cos(th) * r, y, Math.sin(th) * r) }});
    const duct = curve([[0, .95, 0], [0, .74, 0], [.5, .72, 0], [.95, .74, -.05], [.96, 1.5, -.13], [1.08, 1.82, -.13], [CXc - .15, 1.82, -.1]]);
    flow({n: 150, size: .008, color: 0xcfae78, key: 'spray', speed: [.18, .26],
      path: (i, t, o, s) => {
        if (t < .45) return duct.getPoint(t / .45, o);
        const u = (t - .45) / .55, y = 1.8 - 1.0 * u, R = y > 1.55 ? .15 : y > 1.05 ? .035 + (y - 1.05) / .5 * .12 : .03, th = -1.2 + u * Math.PI * 10 + s;
        o.set(CXc + Math.cos(th) * R, y, Math.sin(th) * R);
      }});
    flow({n: 50, size: .009, color: 0xc9d3dc, key: 'fan', speed: [.25, .35], opacity: .6, path: along([curve([[CXc, 1.7, 0], [CXc, 2.2, 0], [CXb, 2.22, 0], [CXb, 1.9, 0], [CXb + .3, 1.8, 0], [2.42, 1.2, 0], [2.6, .8, -.1], [2.6, 2.9, -.17]])], .03)});
    return {pos: [3.9, 3.0, 5.9], target: [.2, 1.4, 0]};
  },

  // ---------------------------------------------------------- 자연건조(노지 / 하우스형 태양열)
  '자연건조'(K, variant){
    const {T3, M, S, part, on, spin, mesh, grp, box, cyl, rbox, pipe, chunks, flow, curve, along, heatColor} = K;
    K.setGround(true);
    // 태양: 단계에 따라 호를 따라 움직이고, 주 조명이 따라간다(밤에는 달빛)
    const su = part('sun', [0, 4, -3]);
    const sunMat = new T3.MeshBasicMaterial({color: 0xffd36b, toneMapped: false});
    const sun = mesh(K.sph(.32, 32, 16), sunMat, su); sun.castShadow = false;
    const halo = new T3.Sprite(new T3.SpriteMaterial({map: (() => { const c = document.createElement('canvas'); c.width = c.height = 128; const g = c.getContext('2d'); const r = g.createRadialGradient(64, 64, 8, 64, 64, 64); r.addColorStop(0, 'rgba(255,220,130,.9)'); r.addColorStop(1, 'rgba(255,200,100,0)'); g.fillStyle = r; g.fillRect(0, 0, 128, 128); return new T3.CanvasTexture(c) })(), blending: T3.AdditiveBlending, depthWrite: false, toneMapped: false, transparent: true}));
    halo.scale.set(2.4, 2.4, 1); su.add(halo); halo.userData.noHit = true;
    const {key, hemi} = K.light, warm = new T3.Color(0xffc27a), white = new T3.Color(0xffffff), moon = new T3.Color(0x9fb4ff), sunPos = K.anchor('sun');
    on(st => {
      const s = st.a.sun ?? .5, night = st.a.night ?? 0, a = Math.PI * sat(s);
      sunPos.set(-4.8 * Math.cos(a), .3 + 1.75 * Math.sin(a), -4.6);
      sun.position.copy(sunPos); halo.position.copy(sunPos); su.visible = s <= 1 && night < .5;
      if (night > .5 || s > 1) { key.position.set(3, 5, 2); key.color.copy(moon); key.intensity = .3; hemi.intensity = .18; K.setEnv(.28) }
      else { key.position.copy(sunPos); key.color.lerpColors(warm, white, Math.sin(a)); key.intensity = .6 + 2.0 * Math.sin(a); hemi.intensity = .35 + .25 * Math.sin(a); K.setEnv(.55 + .35 * Math.sin(a)) }
    });
    // 백엽상(온습도계)
    const SX = -2.0, SZ = -1.45;
    const stn = part('station', [SX, 1.72, SZ]);
    mesh(cyl(.03, .03, 1.2, 12), M.white, stn, [SX, .6, SZ]);
    mesh(rbox(.36, .4, .32, .01), M.white, stn, [SX, 1.4, SZ]);
    for (let i = 0; i < 6; i++) mesh(box(.34, .03, .01), M.white, stn, [SX, 1.24 + i * .06, SZ + .165], [.6, 0, 0]);
    mesh(box(.44, .02, .4), M.white, stn, [SX, 1.62, SZ]);
    const chs = [];
    on(st => { const m = st.a.moisture ?? 1; chs.forEach(c => c.set(.55 + .45 * m, sat((1 - m) * 1.5))) });

    if (variant === 'solar') {
      // 하우스형 태양열 건조기(터널형): 송풍기 → 집열부 → 투명 아치 건조부 → 배기구
      const base = K.root;
      for (const x of [-2.1, -1.0, 0, 1.1, 2.1]) for (const z of [-.42, .42]) mesh(box(.04, .45, .04), M.frame, base, [x, .225, z]);
      for (const z of [-.43, .43]) mesh(box(4.4, .05, .04), M.frame, base, [0, .43, z]);
      mesh(box(4.4, .02, .9), M.paint, base, [0, .46, 0]);
      const co = part('collector', [-1.4, .78, .45]);
      mesh(box(1.65, .01, .86), M.absorber, co, [-1.375, .48, 0]);
      for (const s of [-1, 1]) mesh(box(1.65, .18, .02), M.paint, co, [-1.375, .56, s * .44]);
      mesh(box(1.65, .006, .9), S.glass, co, [-1.375, .65, 0], [0, 0, -.03]);
      const cv = part('cover', [.9, 1.0, .3]);
      mesh(new T3.CylinderGeometry(.45, .45, 2.75, 40, 1, true, 0, Math.PI), S.film, cv, [.825, .47, 0], [0, 0, Math.PI / 2]);
      for (let i = 0; i < 7; i++) mesh(K.torus(.45, .008, Math.PI), M.steel, cv, [-.53 + i * .455, .47, 0], [0, Math.PI / 2, 0]);
      mesh(new T3.CircleGeometry(.45, 32, 0, Math.PI), S.film, cv, [2.2, .47, 0], [0, Math.PI / 2, 0]);
      const tr = part('trays', [.3, .62, .35]);
      mesh(box(2.6, .004, .8), M.net, tr, [.85, .55, 0]);
      chs.push(chunks(tr, [.85, .555, 0], 2.5, .74, 260, 21, 0x9c6a3a, .028));
      const fa = part('fan', [-2.32, .9, .2]);
      mesh(rbox(.16, .3, .36, .01), M.paint, fa, [-2.3, .58, 0]);
      mesh(K.torus(.12, .012), M.dark, fa, [-2.39, .58, 0], [0, Math.PI / 2, 0]);
      const rot = grp(fa, [-2.39, .58, 0]);
      for (let i = 0; i < 5; i++) mesh(box(.006, .1, .04), M.dark, grp(rot, null, [i * Math.PI * 2 / 5, 0, 0]), [0, .055, 0], [0, .4, 0]);
      spin(rot, 'x', 14, 'fan');
      const pv = part('pv', [-2.75, 1.5, .6]);
      mesh(cyl(.025, .025, 1.1, 12), M.steel, pv, [-2.75, .55, .6]);
      const pg = grp(pv, [-2.75, 1.15, .6], [-.6, 0, 0]);
      mesh(box(.7, .025, .45), M.pv, pg); mesh(box(.72, .02, .47), M.steel, pg, [0, -.015, 0]);
      pipe(pv, [[-2.72, 1.1, .6], [-2.72, .7, .6], [-2.36, .7, .15]], .006, M.dark, .05);
      const cm = part('chimney', [2.35, 1.45, .1]);
      mesh(rbox(.16, .25, .3, .01), M.paint, cm, [2.28, .62, 0]);
      mesh(cyl(.07, .07, .6, 24), M.steel, cm, [2.3, 1.0, 0]);
      mesh(cyl(.005, .13, .07, 24), M.steel, cm, [2.3, 1.36, 0]);
      const curves = [-.3, -.1, .1, .3].map(z => curve([[-2.65, .58, z * .5], [-2.3, .58, z], [-2.0, .55, z], [-.6, .56, z], [-.3, .66, z * .9], [1.0, .7, z], [2.05, .66, z * .6], [2.3, .8, 0], [2.3, 1.4, 0]]));
      flow({n: 220, size: .013, key: 'fan', speed: [.07, .1], path: along(curves, .04),
        tint: (i, t, c, st) => heatColor(c, (t < .45 ? lerp(.2, 1, t / .45) : lerp(1, .5, (t - .45) / .55)) * sat((st.g.solar ?? 0) / 700 + .15))});
      flow({n: 70, size: .012, color: 0xe3eef8, key: 'vapor', speed: [.3, .5], opacity: .6, path: (i, t, o, s) => o.set(-.3 + ((s * 13.1) % 1) * 2.4, .58 + t * .3, ((s * 5.7) % 1 - .5) * .6)});
      return {pos: [3.3, 2.3, 4.6], target: [0, .6, 0]};
    }
    // 노지 천일건조: 망 건조대 3개, 방충망, 비가림 덮개, 바람(풍향자루)
    mesh(rbox(5.6, .03, 2.8, .01), M.concrete, K.root, [0, .015, 0]);
    const rk = part('racks', [-1.85, 1.15, .3]);
    const tilt = .165, xs = [-1.85, 0, 1.85];
    for (const [i, x] of xs.entries()) {
      for (const sx of [-1, 1]) { mesh(box(.05, .75, .05), M.wood, rk, [x + sx * .78, .375, .43]); mesh(box(.05, .9, .05), M.wood, rk, [x + sx * .78, .45, -.43]) }
      for (const z of [-.43, .43]) mesh(box(1.6, .03, .03), M.wood, rk, [x, .2, z]);
      const sg = grp(rk, [x, .83, 0], [tilt, 0, 0]);
      mesh(box(1.62, .04, .05), M.wood, sg, [0, 0, .46]); mesh(box(1.62, .04, .05), M.wood, sg, [0, 0, -.46]);
      for (const sx of [-1, 1]) mesh(box(.05, .04, .92), M.wood, sg, [sx * .79, 0, 0]);
      mesh(box(1.56, .004, .88), M.net, sg, [0, .01, 0]);
      chs.push(chunks(sg, [0, .012, 0], 1.5, .82, 130, 60 + i, 0x9c6a3a, .03));
    }
    const nt = part('net', [1.85, 1.55, .35]);
    mesh(new T3.CylinderGeometry(.52, .52, 1.72, 28, 1, true, 0, Math.PI), M.netCover, nt, [1.85, .86, 0], [0, 0, Math.PI / 2]);
    const tp = part('tarp', [-1.85, 1.2, -.55]);
    mesh(cyl(.06, .06, 1.62, 20), M.tarp, tp, [-1.85, 1.0, -.55], [0, 0, Math.PI / 2]);
    const drapes = xs.map(x => { const m = mesh(box(1.72, .01, 1.02), M.tarp, tp, [x, .92, 0], [tilt, 0, 0]); m.visible = false; return m });
    on(st => drapes.forEach(d => d.visible = (st.a.night ?? 0) > .5));
    const wd = part('wind', [-2.75, 2.15, -.1]);
    mesh(cyl(.02, .02, 2.0, 10), M.steel, wd, [-2.9, 1.0, -.2]);
    const sock = mesh(new T3.CylinderGeometry(.12, .05, .5, 16, 1, true).translate(0, -.25, 0), M.sock, wd, [-2.9, 1.95, -.2]);
    on(st => { sock.rotation.z = Math.PI / 2 - (1 - (st.a.wind ?? .5)) * 1.0 });
    flow({n: 140, size: .02, color: 0xc8d6e2, key: 'wind', speed: [.18, .28], opacity: .5, geo: K.cached('streak', () => new T3.BoxGeometry(10, 1, 1)),
      path: (i, t, o, s) => o.set(-3.2 + 6.4 * t, .25 + ((s * 17.3) % 1) * 1.5 + Math.sin(t * 9 + s * 20) * .05, -1.6 + ((s * 7.7) % 1) * 3.2)});
    flow({n: 90, size: .012, color: 0xe3eef8, key: 'vapor', speed: [.25, .4], opacity: .6,
      path: (i, t, o, s) => { const x = xs[i % 3] + ((s * 13.1) % 1 - .5) * 1.4; o.set(x + t * .3, .9 + t * .5, ((s * 5.7) % 1 - .5) * .7) }});
    return {pos: [4.0, 2.6, 5.8], target: [0, .75, -.2]};
  },
};
