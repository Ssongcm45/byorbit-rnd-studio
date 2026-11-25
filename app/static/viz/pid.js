// 공정 흐름도(P&ID 스타일, SVG) — 3D 모델과 같은 부품 id(data-part). 계기 값은 [data-gv=계기키]에 채운다.
import {esc} from './common.js';

const pts = p => p.map(q => q.join(',')).join(' ');

export function pidSvg(method, variant, equip){
  const nm = id => (equip.parts.find(p => p.id === id) || {}).name || id;
  const short = id => nm(id).replace(/\s*\(.*?\)\s*/g, ' ').trim();
  // 부품 묶음(누르면 같은 부품 설명) — 이름 라벨 포함
  const A = (id, inner, lx, ly, anchor = 'middle') => equip.parts.some(p => p.id === id)
    ? `<g class="pid-part" data-part="${id}" tabindex="0" role="button" aria-label="${esc(nm(id))}">${inner}${lx != null ? `<text class="pid-name" x="${lx}" y="${ly}" text-anchor="${anchor}">${esc(short(id))}</text>` : ''}</g>` : inner;
  // 흐름선: 색 선 + 움직이는 점선(방향) + 화살촉, 선택적 라벨
  const ln = (p, cls, label, lp, anchor = 'start') => `<polyline class="pid-ln ${cls}" points="${pts(p)}" marker-end="url(#pidA-${cls})"/><polyline class="pid-flow" points="${pts(p)}"/>`
    + (label ? `<text class="pid-stream ${cls}" x="${lp[0]}" y="${lp[1]}" text-anchor="${anchor}">${esc(label)}</text>` : '');
  const inst = (x, y, tag, part, key, to, vp = 'r') => {
    const [a, b] = tag.split('-');
    return (to ? `<path class="pid-sig" d="M${to[0]},${to[1]} L${x},${y}"/>` : '')
      + A(part, `<g class="pid-inst"><circle cx="${x}" cy="${y}" r="19"/><line x1="${x - 19}" x2="${x + 19}" y1="${y}" y2="${y}"/><text x="${x}" y="${y - 5}" class="t1">${a}</text><text x="${x}" y="${y + 13}" class="t2">${b || ''}</text></g>`)
      + (vp === 'b' ? `<text class="pid-val" data-gv="${key}" x="${x}" y="${y + 33}" text-anchor="middle">-</text>`
        : `<text class="pid-val" data-gv="${key}" x="${x + 24}" y="${y + 5}">-</text>`);
  };
  const vessel = (x, y, w, h, rx = 8) => `<rect class="pid-v" x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}"/>`;
  const valve = (x, y, vert = false) => vert
    ? `<path class="pid-v" d="M${x - 10},${y - 14} L${x + 10},${y + 14} L${x - 10},${y + 14} L${x + 10},${y - 14} Z"/>`
    : `<path class="pid-v" d="M${x - 14},${y - 10} L${x + 14},${y + 10} L${x + 14},${y - 10} L${x - 14},${y + 10} Z"/><line class="pid-s" x1="${x}" y1="${y}" x2="${x}" y2="${y - 22}"/><path class="pid-v" d="M${x - 11},${y - 22} a11,11 0 0 1 22,0 Z"/>`;
  const pump = (x, y, r = 22) => `<circle class="pid-v" cx="${x}" cy="${y}" r="${r}"/><path class="pid-s" d="M${x - r * .55},${y - r * .55} L${x + r * .8},${y} L${x - r * .55},${y + r * .55}"/><line class="pid-s" x1="${x - r}" y1="${y + r + 4}" x2="${x + r}" y2="${y + r + 4}"/>`;
  const comp = (x, y, r = 22) => `<circle class="pid-v" cx="${x}" cy="${y}" r="${r}"/><path class="pid-s" d="M${x - 15},${y - 13} L${x + 15},${y - 6} M${x - 15},${y + 13} L${x + 15},${y + 6}"/>`;
  const fan = (x, y, r = 22) => `<circle class="pid-v" cx="${x}" cy="${y}" r="${r}"/>` + [0, 120, 240].map(a => `<path class="pid-s" transform="rotate(${a} ${x} ${y})" d="M${x},${y} q${r * .5},${-r * .2} ${r * .75},${-r * .55}"/>`).join('');
  const heater = (x, y, w, h) => `<rect class="pid-v" x="${x}" y="${y}" width="${w}" height="${h}" rx="3"/><path class="pid-hotz" d="M${x + 6},${y + h / 2} ${Array.from({length: 6}, (_, i) => `L${x + 6 + (w - 12) * (i + .5) / 6},${y + (i % 2 ? h - 7 : 7)}`).join(' ')} L${x + w - 6},${y + h / 2}"/>`;
  const filter = (x, y, w, h) => `<rect class="pid-v" x="${x}" y="${y}" width="${w}" height="${h}" rx="2"/><line class="pid-s" stroke-dasharray="4 3" x1="${x}" y1="${y + h}" x2="${x + w}" y2="${y}"/>`;
  const damper = (x, y) => `<circle class="pid-v" cx="${x}" cy="${y}" r="4"/><line class="pid-s" x1="${x - 13}" y1="${y + 8}" x2="${x + 13}" y2="${y - 8}"/>`;
  const panel = (x, y) => A('panel', `<rect class="pid-v" x="${x}" y="${y}" width="78" height="56" rx="6"/><rect class="pid-scr" x="${x + 8}" y="${y + 8}" width="62" height="28" rx="2"/><text class="pid-name" x="${x + 39}" y="${y + 49}" text-anchor="middle">HMI</text>`, x + 39, y - 7);
  const coil = (x, y, w, h, n = 7) => `<path class="pid-coil" d="M${x},${y + h} ${Array.from({length: n}, (_, i) => `L${x + w * (i + .5) / n},${y + (i % 2 ? h : 0)}`).join(' ')} L${x + w},${y}"/>`;
  const sun = (x, y) => `<circle class="pid-sun" cx="${x}" cy="${y}" r="20"/>` + Array.from({length: 8}, (_, i) => `<line class="pid-sunr" transform="rotate(${i * 45} ${x} ${y})" x1="${x}" y1="${y - 27}" x2="${x}" y2="${y - 36}"/>`).join('');
  const prod = (x, y, w) => `<rect class="pid-prod" x="${x}" y="${y}" width="${w}" height="9" rx="3"/>`;

  const D = {
    '동결건조'(){
      let s = A('chamber', vessel(110, 90, 240, 270), 268, 82);
      s += A('door', `<rect class="pid-door" x="99" y="112" width="11" height="226" rx="3"/>`, 92, 372, 'end');
      s += A('shelves', [0, 1, 2, 3].map(i => `<rect class="pid-shelf" x="128" y="${148 + i * 55}" width="204" height="7" rx="2"/>`).join(''));
      s += A('trays', [0, 1, 2, 3].map(i => prod(140, 137 + i * 55, 180)).join(''), 240, 358);
      s += `<text class="pid-note" x="230" y="388" text-anchor="middle">선반 열매체(실리콘 오일) −50 ~ +50 ℃</text>`;
      s += A('duct', ln([[350, 200], [394, 200]], 'vap') + ln([[426, 200], [470, 200]], 'vap'), 372, 228);
      s += A('valve', valve(410, 200), 410, 165);
      s += `<text class="pid-stream vap" x="432" y="190">수증기</text>`;
      s += A('condenser', vessel(470, 135, 210, 130, 40) + coil(500, 170, 150, 60), 575, 127);
      s += A('refrig', comp(575, 390), 575, 432);
      s += ln([[560, 368], [560, 265]], 'ref') + ln([[590, 265], [590, 368]], 'ref', '냉매', [598, 330]);
      s += ln([[650, 135], [650, 70], [850, 70], [850, 364]], 'vac', '진공 배기', [700, 62]);
      s += A('vacpump', pump(850, 390), 850, 436) + ln([[874, 390], [950, 390]], 'exh', '배기', [910, 380]);
      s += inst(230, 40, 'PI-101', 'gauge', 'p_ch', [230, 90]);
      s += inst(55, 175, 'TIC-102', 'shelves', 't_shelf', [128, 175], 'b');
      s += inst(405, 315, 'TI-103', 'trays', 't_prod', [320, 305]);
      s += inst(745, 200, 'TI-104', 'condenser', 't_cond', [680, 200]);
      return s + panel(870, 160);
    },
    '열풍건조'(){
      let s = A('cabinet', `<rect class="pid-v pid-wall" x="120" y="70" width="520" height="350" rx="6"/>`, 380, 440);
      s += A('door', `<rect class="pid-door2" x="134" y="84" width="350" height="322" rx="4"/>`, 150, 100, 'start');
      s += A('trolley', `<rect class="pid-s" fill="none" x="152" y="118" width="316" height="276" rx="2"/>` + [170, 450].map(x => `<circle class="pid-v" cx="${x}" cy="404" r="6"/>`).join(''));
      s += A('trays', Array.from({length: 8}, (_, i) => `<line class="pid-tray" x1="160" x2="460" y1="${140 + i * 34}" y2="${140 + i * 34}"/>` + prod(172, 131 + i * 34, 276)).join(''));
      s += A('duct', `<line class="pid-perf" x1="500" y1="110" x2="500" y2="400"/><line class="pid-s" x1="140" y1="106" x2="500" y2="106"/>`, 512, 395, 'start');
      s += A('heater', heater(525, 200, 90, 70), 570, 290);
      s += A('fan', fan(570, 140), 615, 145, 'start');
      [160, 228, 296, 364].forEach((y, i) => s += ln([[520, y], [175, y]], 'hot', i ? '' : '열풍 → 트레이 사이(횡류)', [330, 152]));
      s += ln([[150, 390], [140, 390], [140, 92], [548, 92], [560, 118]], 'airc') + `<text class="pid-stream airc" transform="rotate(-90 110 250)" x="110" y="250" text-anchor="middle">되돌아오는 습한 공기</text>`;
      s += A('inlet', ln([[600, 18], [600, 66]], 'airc') + damper(600, 42), 612, 30, 'start');
      s += `<text class="pid-stream airc" x="612" y="60">외기</text>`;
      s += A('exhaust', ln([[200, 70], [200, 14]], 'wet') + damper(200, 42), 212, 30, 'start');
      s += `<text class="pid-stream wet" x="212" y="60">습한 공기 배기</text>`;
      s += inst(700, 235, 'TIC-201', 'heater', 't_in', [615, 235]);
      s += inst(430, 38, 'RHI-202', 'sensor', 'rh', [430, 92]);
      s += inst(700, 340, 'TI-203', 'trays', 't_prod', [460, 330]);
      return s + panel(820, 150);
    },
    '진공건조'(){
      let s = A('chamber', vessel(110, 100, 260, 250, 6), 112, 92, 'start');
      s += A('door', `<rect class="pid-door" x="99" y="120" width="11" height="210" rx="3"/><circle class="pid-v" cx="104" cy="225" r="7"/>`, 92, 345, 'end');
      const ys = [170, 240, 310];
      s += A('plates', ys.map(y => `<rect class="pid-plate" x="128" y="${y}" width="224" height="8" rx="2"/>`).join(''));
      s += A('trays', ys.map(y => prod(142, y - 11, 196)).join(''), 380, 330, 'start');
      s += A('circulator', vessel(150, 395, 120, 50, 6), 210, 470);
      s += ln([[180, 395], [180, 350]], 'hot', '온수 공급', [130, 385], 'end') + ln([[240, 350], [240, 395]], 'hotr');
      s += ln([[370, 150], [470, 150]], 'vap', '수증기', [390, 140]);
      s += A('condenser', vessel(470, 110, 60, 180, 26) + coil(478, 140, 44, 120, 9), 500, 102);
      s += ln([[600, 250], [530, 250]], 'wat', '냉각수', [560, 244]) + ln([[530, 200], [600, 200]], 'wat');
      s += ln([[500, 290], [500, 330]], 'liq') + vessel(480, 330, 40, 46, 8) + `<text class="pid-note" x="500" y="392" text-anchor="middle">응축수</text>`;
      s += ln([[500, 110], [500, 66], [760, 66], [760, 362]], 'vac', '진공 배기', [600, 58]);
      s += A('vacpump', pump(760, 388), 760, 436) + ln([[784, 388], [860, 388]], 'exh', '배기', [820, 378]);
      s += A('valve', ln([[310, 28], [310, 98]], 'airc') + valve(310, 64, true), 322, 40, 'start');
      s += `<text class="pid-stream airc" x="322" y="22">공기·질소(해제)</text>`;
      s += inst(185, 45, 'PI-301', 'gauge', 'p_ch', [185, 100], 'b');
      s += inst(250, 45, 'TY-301', 'gauge', 'boil', [204, 45], 'b');
      s += inst(330, 425, 'TIC-302', 'circulator', 't_plate', [270, 420]);
      s += inst(420, 285, 'TI-303', 'trays', 't_prod', [352, 290]);
      return s + panel(860, 160);
    },
    '분무건조'(){
      let s = A('feedtank', vessel(40, 80, 70, 110, 14), 75, 72);
      s += ln([[110, 165], [162, 165]], 'liq');
      s += A('feedpump', pump(185, 165, 20), 185, 205);
      s += ln([[205, 165], [240, 165], [240, 22], [470, 22], [470, 38]], 'liq', '원료액', [300, 16]);
      s += A('filter', filter(30, 360, 50, 60), 55, 440);
      s += ln([[80, 390], [118, 390]], 'airc');
      s += A('blower', fan(140, 390), 140, 440);
      s += ln([[162, 390], [200, 390]], 'airc');
      s += A('heater', heater(200, 360, 70, 60), 235, 440);
      s += ln([[270, 390], [300, 390], [300, 62], [392, 62]], 'hot', '열풍 180 ℃', [306, 230]);
      s += A('chamber', `<path class="pid-v" d="M380,62 H560 V230 L482,370 H458 L380,230 Z"/>`, 470, 300);
      s += A('atomizer', `<circle class="pid-v" cx="470" cy="50" r="13"/><text class="pid-name" x="470" y="55" text-anchor="middle">M</text><line class="pid-s" x1="470" y1="63" x2="470" y2="84"/><line class="pid-s" x1="456" y1="84" x2="484" y2="84"/>`, 452, 46, 'end');
      s += `<path class="pid-spray" d="M462,90 L420,170 M470,90 L470,190 M478,90 L520,170"/>`;
      s += ln([[470, 370], [470, 420], [640, 420], [640, 200], [668, 200]], 'pow', '분말 + 습한 공기', [482, 412]);
      s += A('cyclone', `<path class="pid-v" d="M672,170 H728 V240 L706,310 H694 L672,240 Z"/>`, 724, 300, 'start');
      s += ln([[700, 310], [700, 340]], 'pow');
      s += A('jar', vessel(682, 340, 36, 48, 6) + `<rect class="pid-prod" x="686" y="366" width="28" height="18" rx="2"/>`, 700, 404);
      s += ln([[700, 170], [700, 120], [820, 120], [820, 148]], 'wet');
      s += A('bagfilter', vessel(790, 148, 60, 170, 8) + [802, 820, 838].map(x => `<line class="pid-s" stroke-dasharray="5 4" x1="${x}" y1="160" x2="${x}" y2="300"/>`).join(''), 820, 336);
      s += ln([[850, 300], [900, 300], [900, 356]], 'wet');
      s += A('exhaust', fan(920, 378), 920, 422);
      s += ln([[942, 378], [970, 378], [970, 30]], 'exh', '배기', [960, 40], 'end');
      s += inst(225, 250, 'TIC-401', 'ti_in', 't_in', [300, 250]);
      s += inst(560, 455, 'TI-402', 'ti_out', 't_out', [560, 420]);
      s += inst(170, 110, 'FIC-403', 'feedpump', 'feed', [185, 145], 'b');
      s += inst(580, 40, 'SI-404', 'atomizer', 'rpm', [484, 50]);
      return s + panel(700, 20);
    },
    '자연건조'(){
      if (variant === 'solar') {
        let s = A('pv', `<rect class="pid-v" x="40" y="60" width="90" height="40" rx="3" transform="rotate(-12 85 80)"/>`, 85, 128);
        s += `<path class="pid-elec" d="M85,130 V300 H98"/>`;
        s += A('sun', sun(520, 60), 560, 66, 'start');
        s += `<path class="pid-rad" d="M490,92 L300,270 M520,95 L560,220 M548,90 L720,220"/>`;
        s += A('fan', fan(120, 300), 120, 345);
        s += ln([[60, 300], [98, 300]], 'airc', '외기', [40, 290]);
        s += ln([[142, 300], [160, 300]], 'airc');
        s += A('collector', `<rect class="pid-v" x="160" y="280" width="220" height="44" rx="3"/><rect class="pid-abs" x="166" y="310" width="208" height="8"/>`, 270, 345);
        s += ln([[175, 296], [365, 296]], 'hot', '데워진 공기', [200, 274]);
        s += A('cover', `<path class="pid-v pid-film" d="M380,324 V300 Q600,170 820,300 V324 Z"/>`, 600, 210);
        s += A('trays', prod(400, 304, 400), 600, 345);
        s += ln([[390, 290], [800, 290]], 'wet');
        s += A('chimney', vessel(820, 140, 34, 184, 4), 837, 345);
        s += ln([[837, 140], [837, 60]], 'wet', '습한 공기', [850, 80]);
        s += inst(70, 420, 'TI-501', 'station', 't_air', null, 'b') + inst(140, 420, 'RHI-503', 'station', 'rh', null, 'b');
        s += inst(620, 400, 'TI-502', 'cover', 't_dry', [620, 324]);
        s += inst(650, 40, 'RI-504', 'sun', 'solar', [580, 60]);
        return s + A('station', `<rect class="pid-v" x="40" y="375" width="130" height="80" rx="6" fill-opacity="0"/>`, 105, 470);
      }
      let s = A('sun', sun(120, 80), 120, 136);
      s += `<path class="pid-rad" d="M140,105 L300,270 M150,98 L480,270 M160,92 L660,270"/>`;
      s += A('wind', ln([[30, 230], [240, 230]], 'airc') + ln([[30, 330], [240, 330]], 'airc'), 60, 220, 'start');
      const rack = x => `<path class="pid-v" d="M${x - 70},300 L${x + 70},290 L${x + 70},296 L${x - 70},306 Z"/><line class="pid-s" x1="${x - 60}" y1="305" x2="${x - 60}" y2="370"/><line class="pid-s" x1="${x + 60}" y1="294" x2="${x + 60}" y2="370"/>` + `<path class="pid-prod" d="M${x - 62},296 L${x + 62},286 L${x + 62},292 L${x - 62},302 Z"/>`;
      s += A('racks', [300, 480, 660].map(rack).join(''), 480, 395);
      s += A('net', `<path class="pid-net" d="M585,305 Q660,200 735,292"/>`, 660, 225);
      s += A('tarp', `<circle class="pid-v" cx="300" cy="282" r="8"/>`, 300, 266);
      [300, 480, 660].forEach(x => s += ln([[x, 280], [x + 20, 240]], 'wet'));
      s += `<text class="pid-stream wet" x="500" y="235">수증기</text><line class="pid-s" x1="20" y1="370" x2="980" y2="370"/>`;
      s += A('station', `<rect class="pid-v" x="830" y="200" width="70" height="60" rx="4"/><line class="pid-s" x1="865" y1="260" x2="865" y2="370"/>`, 865, 190);
      s += inst(800, 300, 'TI-501', 'station', 't_air', [830, 240], 'b') + inst(930, 300, 'RHI-503', 'station', 'rh', [900, 240], 'b');
      s += inst(240, 60, 'RI-504', 'sun', 'solar', [140, 80]);
      return s;
    },
  };
  const colors = {vap: 'var(--cold)', hot: 'var(--hot)', hotr: '#c98a5a', airc: '#7f9cba', wet: 'var(--vapor)', liq: 'var(--v-accent)', pow: 'var(--v-earth)', vac: 'var(--v-ink)', ref: 'var(--cold)', wat: '#3a8fd0', exh: 'var(--v-muted)'};
  const defs = Object.entries(colors).map(([k, c]) => `<marker id="pidA-${k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="${c}"/></marker>`).join('');
  return `<svg class="pid" viewBox="0 0 1000 480" role="group" aria-label="${esc(method)} 공정 흐름도(P&amp;ID). 기호를 누르면 부품 설명이 나옵니다."><defs>${defs}</defs>${(D[method] || (() => ''))()}</svg>`;
}
