# 안내서 인포그래픽 HTML 생성기 — guidebook/assets/src/iNN-*.html 로 쓴다(외부 CDN·아이콘 글꼴 없음)
import pathlib

OUT = pathlib.Path(r"D:/04_ByOrbit/10_rnd_AI_byrobit/guidebook/assets/src")

CSS = """
:root{--brand:#2DA082;--deep:#1F7A63;--pale:#EAF4F0;--ink:#231F20;--gray:#6D6E71;--warn:#E07B39;--warnpale:#FCEFE5;--line:#CFE3DA;--soft:#F6F8F7}
*{box-sizing:border-box}
html,body{margin:0;background:#fff}
html{overflow:hidden}::-webkit-scrollbar{display:none}
body{font-family:'Pretendard','Malgun Gothic',sans-serif;color:var(--ink);width:1600px;padding:64px 72px 64px;font-size:32px;line-height:1.4;word-break:keep-all}
h1{font-size:56px;line-height:1.25;margin:0 0 10px;font-weight:800;letter-spacing:-0.5px}
.sub{font-size:32px;color:var(--gray);margin:0 0 40px}
.row{display:flex;align-items:stretch;gap:0}
.col{display:flex;flex-direction:column}
.box{background:#fff;border:3px solid var(--line);border-radius:22px;padding:24px 26px}
.box.b{border-color:var(--brand)}
.box.f{background:var(--brand);border-color:var(--brand);color:#fff}
.box.d{background:var(--deep);border-color:var(--deep);color:#fff}
.box.p{background:var(--pale);border-color:var(--pale)}
.box.w{border-color:var(--warn)}
.box.wf{background:var(--warnpale);border-color:var(--warn)}
.box.g{background:var(--soft);border-color:#E3E7E5}
.t{font-weight:800;font-size:36px;line-height:1.25}
.t2{font-weight:700;font-size:33px}
.s{font-size:31px;color:var(--gray);margin-top:6px}
.f .s,.d .s{color:#E6F4EE}
.tag{display:inline-block;font-size:31px;font-weight:700;padding:3px 14px;border-radius:14px;background:var(--pale);color:var(--deep);margin:4px 6px 0 0}
.tag.w{background:var(--warnpale);color:#B35A20}
.tag.g{background:#EEF0EF;color:var(--gray)}
.f .tag{background:rgba(255,255,255,.22);color:#fff}
.p .tag,.wf .tag{background:#fff}
.num{display:inline-grid;place-items:center;width:52px;height:52px;border-radius:50%;background:var(--brand);color:#fff;font-weight:800;font-size:30px;flex:none}
.arr{flex:none;display:flex;align-items:center;justify-content:center}
.ic{flex:none}
.note{font-size:31px;color:var(--gray);margin-top:28px}
.k{color:var(--deep);font-weight:800}
.wk{color:#B35A20;font-weight:800}
ul.l{margin:8px 0 0;padding-left:26px}ul.l li{margin:4px 0}
"""

def arrow(dir="r", length=70, color="#2DA082", w=8, label=""):
    if dir == "r":
        svg = f'<svg width="{length}" height="44" viewBox="0 0 {length} 44"><line x1="2" y1="22" x2="{length-20}" y2="22" stroke="{color}" stroke-width="{w}" stroke-linecap="round"/><path d="M{length-26} 8 L{length-2} 22 L{length-26} 36 Z" fill="{color}"/></svg>'
    elif dir == "l":
        svg = f'<svg width="{length}" height="44" viewBox="0 0 {length} 44"><line x1="22" y1="22" x2="{length-2}" y2="22" stroke="{color}" stroke-width="{w}" stroke-linecap="round"/><path d="M26 8 L2 22 L26 36 Z" fill="{color}"/></svg>'
    elif dir == "d":
        svg = f'<svg width="44" height="{length}" viewBox="0 0 44 {length}"><line x1="22" y1="2" x2="22" y2="{length-20}" stroke="{color}" stroke-width="{w}" stroke-linecap="round"/><path d="M8 {length-26} L22 {length-2} L36 {length-26} Z" fill="{color}"/></svg>'
    else:  # up
        svg = f'<svg width="44" height="{length}" viewBox="0 0 44 {length}"><line x1="22" y1="22" x2="22" y2="{length-2}" stroke="{color}" stroke-width="{w}" stroke-linecap="round"/><path d="M8 26 L22 2 L36 26 Z" fill="{color}"/></svg>'
    lab = f'<div style="font-size:31px;color:var(--gray);text-align:center;font-weight:700;margin-top:2px">{label}</div>' if label else ""
    return f'<div class="arr" style="flex-direction:column;padding:0 10px">{svg}{lab}</div>'

# ---------- 아이콘(단순 SVG 도형) ----------
G, D, W, K = "#2DA082", "#1F7A63", "#E07B39", "#6D6E71"
def ic(name, size=64, c=G):
    s = size
    body = {
        "doc": f'<rect x="14" y="6" width="36" height="52" rx="5" fill="#fff" stroke="{c}" stroke-width="4"/><line x1="22" y1="22" x2="42" y2="22" stroke="{c}" stroke-width="4"/><line x1="22" y1="32" x2="42" y2="32" stroke="{c}" stroke-width="4"/><line x1="22" y1="42" x2="36" y2="42" stroke="{c}" stroke-width="4"/>',
        "docs": f'<rect x="20" y="4" width="32" height="44" rx="5" fill="#fff" stroke="{c}" stroke-width="4"/><rect x="10" y="14" width="32" height="44" rx="5" fill="#fff" stroke="{c}" stroke-width="4"/><line x1="17" y1="30" x2="35" y2="30" stroke="{c}" stroke-width="4"/><line x1="17" y1="40" x2="30" y2="40" stroke="{c}" stroke-width="4"/>',
        "search": f'<circle cx="27" cy="27" r="16" fill="none" stroke="{c}" stroke-width="5"/><line x1="39" y1="39" x2="54" y2="54" stroke="{c}" stroke-width="6" stroke-linecap="round"/>',
        "lock": f'<rect x="12" y="28" width="40" height="28" rx="6" fill="{c}"/><path d="M20 28 V20 a12 12 0 0 1 24 0 V28" fill="none" stroke="{c}" stroke-width="5"/><circle cx="32" cy="41" r="4" fill="#fff"/>',
        "repeat": f'<path d="M14 30 a18 18 0 0 1 32 -11" fill="none" stroke="{c}" stroke-width="5" stroke-linecap="round"/><path d="M42 10 L48 20 L37 22 Z" fill="{c}"/><path d="M50 34 a18 18 0 0 1 -32 11" fill="none" stroke="{c}" stroke-width="5" stroke-linecap="round"/><path d="M22 54 L16 44 L27 42 Z" fill="{c}"/>',
        "table": f'<rect x="8" y="12" width="48" height="40" rx="5" fill="#fff" stroke="{c}" stroke-width="4"/><line x1="8" y1="25" x2="56" y2="25" stroke="{c}" stroke-width="4"/><line x1="8" y1="38" x2="56" y2="38" stroke="{c}" stroke-width="3"/><line x1="26" y1="12" x2="26" y2="52" stroke="{c}" stroke-width="3"/>',
        "person": f'<circle cx="32" cy="20" r="11" fill="{c}"/><path d="M10 58 a22 20 0 0 1 44 0 Z" fill="{c}"/>',
        "bot": f'<rect x="10" y="18" width="44" height="34" rx="10" fill="{c}"/><circle cx="24" cy="35" r="5" fill="#fff"/><circle cx="40" cy="35" r="5" fill="#fff"/><line x1="32" y1="18" x2="32" y2="8" stroke="{c}" stroke-width="4"/><circle cx="32" cy="7" r="4" fill="{c}"/>',
        "check": f'<circle cx="32" cy="32" r="26" fill="{c}"/><path d="M19 33 L28 42 L46 23" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>',
        "pc": f'<rect x="6" y="10" width="52" height="34" rx="5" fill="#fff" stroke="{c}" stroke-width="4"/><rect x="24" y="44" width="16" height="7" fill="{c}"/><rect x="16" y="51" width="32" height="5" rx="2" fill="{c}"/>',
        "cloud": f'<path d="M18 48 h30 a12 12 0 0 0 0 -24 a16 16 0 0 0 -30 -2 a12 12 0 0 0 0 26 Z" fill="#fff" stroke="{c}" stroke-width="4"/>',
        "db": f'<ellipse cx="32" cy="14" rx="20" ry="7" fill="#fff" stroke="{c}" stroke-width="4"/><path d="M12 14 v34 a20 7 0 0 0 40 0 v-34" fill="none" stroke="{c}" stroke-width="4"/><path d="M12 31 a20 7 0 0 0 40 0" fill="none" stroke="{c}" stroke-width="4"/>',
        "chart": f'<line x1="10" y1="54" x2="56" y2="54" stroke="{c}" stroke-width="4"/><line x1="10" y1="54" x2="10" y2="8" stroke="{c}" stroke-width="4"/><rect x="18" y="34" width="8" height="18" fill="{c}"/><rect x="31" y="24" width="8" height="28" fill="{c}"/><rect x="44" y="14" width="8" height="38" fill="{c}"/>',
        "flask": f'<path d="M24 6 h16 M27 6 v18 L12 52 a4 4 0 0 0 4 6 h32 a4 4 0 0 0 4 -6 L37 24 V6" fill="#fff" stroke="{c}" stroke-width="4" stroke-linejoin="round"/><path d="M17 44 h30 l4 8 h-38 Z" fill="{c}"/>',
        "eye": f'<path d="M4 32 Q32 6 60 32 Q32 58 4 32 Z" fill="#fff" stroke="{c}" stroke-width="4"/><circle cx="32" cy="32" r="9" fill="{c}"/>',
        "tag": f'<path d="M8 10 h22 l26 26 l-20 20 l-26 -26 Z" fill="#fff" stroke="{c}" stroke-width="4" stroke-linejoin="round"/><circle cx="20" cy="22" r="4" fill="{c}"/>',
        "key": f'<circle cx="20" cy="32" r="11" fill="none" stroke="{c}" stroke-width="5"/><line x1="31" y1="32" x2="58" y2="32" stroke="{c}" stroke-width="5"/><line x1="50" y1="32" x2="50" y2="42" stroke="{c}" stroke-width="5"/><line x1="42" y1="32" x2="42" y2="40" stroke="{c}" stroke-width="5"/>',
        "chat": f'<path d="M8 12 h48 v30 h-30 l-12 10 v-10 h-6 Z" fill="#fff" stroke="{c}" stroke-width="4" stroke-linejoin="round"/><line x1="18" y1="24" x2="46" y2="24" stroke="{c}" stroke-width="4"/><line x1="18" y1="33" x2="38" y2="33" stroke="{c}" stroke-width="4"/>',
        "gear": f'<circle cx="32" cy="32" r="12" fill="none" stroke="{c}" stroke-width="6"/>' + "".join(f'<rect x="29" y="4" width="6" height="12" rx="2" fill="{c}" transform="rotate({a} 32 32)"/>' for a in range(0, 360, 45)),
        "inbox": f'<path d="M8 36 L16 12 h32 l8 24 v16 H8 Z" fill="#fff" stroke="{c}" stroke-width="4" stroke-linejoin="round"/><path d="M8 36 h14 a10 8 0 0 0 20 0 h14" fill="none" stroke="{c}" stroke-width="4"/>',
        "warn": f'<path d="M32 6 L60 56 H4 Z" fill="{c}"/><rect x="29" y="22" width="6" height="18" rx="2" fill="#fff"/><circle cx="32" cy="47" r="3.5" fill="#fff"/>',
        "book": f'<path d="M6 12 q13 -6 26 2 v42 q-13 -8 -26 -2 Z" fill="#fff" stroke="{c}" stroke-width="4" stroke-linejoin="round"/><path d="M58 12 q-13 -6 -26 2 v42 q13 -8 26 -2 Z" fill="#fff" stroke="{c}" stroke-width="4" stroke-linejoin="round"/>',
        "ruler": f'<rect x="4" y="22" width="56" height="20" rx="4" fill="#fff" stroke="{c}" stroke-width="4"/>' + "".join(f'<line x1="{x}" y1="22" x2="{x}" y2="{32 if i%2 else 30}" stroke="{c}" stroke-width="3"/>' for i, x in enumerate(range(12, 56, 8))),
        "cube": f'<path d="M32 6 L56 18 V46 L32 58 L8 46 V18 Z" fill="#fff" stroke="{c}" stroke-width="4" stroke-linejoin="round"/><path d="M8 18 L32 30 L56 18 M32 30 V58" fill="none" stroke="{c}" stroke-width="4"/>',
        "q": f'<circle cx="32" cy="32" r="26" fill="#fff" stroke="{c}" stroke-width="4"/><path d="M23 25 a9 9 0 1 1 12 8 c-3 1 -3 3 -3 6" fill="none" stroke="{c}" stroke-width="5" stroke-linecap="round"/><circle cx="32" cy="46" r="3.5" fill="{c}"/>',
        "target": f'<circle cx="32" cy="32" r="26" fill="#fff" stroke="{c}" stroke-width="4"/><circle cx="32" cy="32" r="16" fill="none" stroke="{c}" stroke-width="4"/><circle cx="32" cy="32" r="6" fill="{c}"/>',
        "box": f'<path d="M6 20 L32 8 L58 20 V48 L32 60 L6 48 Z" fill="#fff" stroke="{c}" stroke-width="4" stroke-linejoin="round"/><path d="M6 20 L32 32 L58 20 M32 32 V60" fill="none" stroke="{c}" stroke-width="4"/>',
        "scissors": f'<circle cx="16" cy="46" r="8" fill="none" stroke="{c}" stroke-width="4"/><circle cx="16" cy="18" r="8" fill="none" stroke="{c}" stroke-width="4"/><line x1="22" y1="40" x2="56" y2="14" stroke="{c}" stroke-width="4"/><line x1="22" y1="24" x2="56" y2="50" stroke="{c}" stroke-width="4"/>',
        "globe": f'<circle cx="32" cy="32" r="25" fill="#fff" stroke="{c}" stroke-width="4"/><ellipse cx="32" cy="32" rx="11" ry="25" fill="none" stroke="{c}" stroke-width="3"/><line x1="7" y1="32" x2="57" y2="32" stroke="{c}" stroke-width="3"/>',
        "spider": f'<circle cx="32" cy="34" r="10" fill="{c}"/>' + "".join(f'<path d="M32 34 L{x} {y}" stroke="{c}" stroke-width="4" stroke-linecap="round"/>' for x, y in [(8, 18), (6, 34), (8, 52), (56, 18), (58, 34), (56, 52)]),
        "code": f'<rect x="4" y="10" width="56" height="44" rx="6" fill="#fff" stroke="{c}" stroke-width="4"/><path d="M22 24 L14 32 L22 40 M42 24 L50 32 L42 40 M36 22 L28 42" fill="none" stroke="{c}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>',
    }[name]
    if c == "#fff":  # 진한 칸 위: 흰 원판 위에 진한 초록 아이콘
        inner = ic(name, int(s * 0.66), "#1F7A63")
        return f'<span class="ic" style="display:inline-grid;place-items:center;width:{s}px;height:{s}px;border-radius:50%;background:#fff">{inner}</span>'
    return f'<svg class="ic" width="{s}" height="{s}" viewBox="0 0 64 64">{body}</svg>'


def page(title, sub, body, extra_css=""):
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{title}</title>
<style>{CSS}{extra_css}</style></head><body><h1>{title}</h1><p class="sub">{sub}</p>{body}</body></html>"""


FIG = {}

# ---------------- i01 ----------------
probs = [("docs", "자료가 흩어져 있다", "논문 PDF·CoA 엑셀·한글 보고서·메모가 폴더 여기저기에"),
         ("search", "수치를 다시 찾는다", "‘식이섬유 몇 g이었지?’ 매번 파일을 열어 찾기"),
         ("lock", "기밀이 걱정된다", "CoA의 로트번호·공급처가 AI로 나가면 어쩌지?"),
         ("repeat", "같은 정리를 반복한다", "비교표·보고서 초안을 매번 손으로 다시 만들기")]
sols = [("inbox", "한곳에 모아 자동 처리", "끌어다 놓거나 받은편지함 폴더에 넣으면 읽고 나눠 저장"),
        ("table", "동의어까지 찾고 수치는 표로", "‘사과 포마스’로 찾아도 사과박이 나오고, 값은 측정값 표에"),
        ("pc", "내 PC 안에 두고 가려서 보냄", "원본과 DB는 PC 밖으로 안 나감. AI에는 식별 정보를 [가림]"),
        ("bot", "AI가 정리를 돕는다", "라벨 제안·근거 달린 답변·리포트 초안·논문용 표와 그림")]
def pcard(i, t, s, cls, col):
    return f'<div class="box {cls}" style="display:flex;gap:20px;align-items:center;min-height:150px">{ic(i, 66, col)}<div><div class="t">{t}</div><div class="s">{s}</div></div></div>'
FIG["i01-why"] = page("연구원의 하루, 무엇이 힘들까?", "흩어진 자료·숨은 수치·기밀 걱정·반복 작업을 이 도구가 한 번에 덜어 줍니다.",
    f'''<div style="display:grid;grid-template-columns:1fr 110px 1fr;row-gap:20px;align-items:stretch">
  <div class="t2" style="color:#B35A20">지금의 문제</div><div></div><div class="t2" style="color:var(--deep)">R&amp;D Studio V0.5가 하는 일</div>
  {''.join(pcard(*p, "wf", W) + arrow("r", 80) + pcard(*s, "b", G) for p, s in zip(probs, sols))}
</div>''')

# ---------------- i02 ----------------
steps = [("doc", "자료 넣기", "PDF·HWPX·XLSX·TXT"), ("scissors", "청크", "알맞은 조각으로"), ("tag", "라벨", "부산물·성분·수치 표시"),
         ("table", "측정값", "승인한 수치만 표로"), ("chat", "검색·AI 답변·리포트", "근거 번호를 달아서")]
main = "".join((f'<div class="box {"f" if i==4 else "b"}" style="flex:1;text-align:center;padding:22px 12px">{ic(s[0], 60, "#fff" if i==4 else G)}<div class="t" style="margin-top:8px">{s[1]}</div><div class="s">{s[2]}</div></div>' + (arrow("r", 50) if i < 4 else "")) for i, s in enumerate(steps))
sides = [("globe", "수집", "논문·특허·보고서를 찾아 수집함에 모음", "고른 자료는 ‘자료 넣기’로"),
         ("flask", "실험", "공정 흐름을 고치고 내 데이터로 예측과 비교·보정", "측정값을 보정 근거로 씀"),
         ("chart", "분석", "회귀·t검정, 논문용 표 1·그림 1·해석 세 문장", "실험 데이터를 그대로 분석"),
         ("cube", "시각화", "흐름 지도·건조 설비 3D·분자 구조", "측정값을 방식별로 비교")]
side = "".join(f'<div class="box p" style="flex:1;padding:22px 22px">{ic(a, 54, D)}<div class="t" style="margin-top:6px">{b}</div><div class="s">{c}</div><div class="tag" style="margin-top:10px">{d}</div></div>' for a, b, c, d in sides)
FIG["i02-overview"] = page("한 장으로 보는 R&amp;D Studio", "위 줄은 자료가 흘러가는 길, 아래 네 화면은 그 옆에서 돕는 도구입니다.",
    f'''<div class="row" style="align-items:stretch">{main}</div>
<div style="border-top:3px dashed var(--line);margin:40px 0 24px"></div>
<div class="t2" style="color:var(--deep);margin:0 0 14px">옆에서 돕는 화면</div>
<div class="row" style="gap:20px">{side}</div>
<p class="note">위 줄은 자료함·검색·라벨 검토·측정값·개념·AI에 묻기 화면이 맡고, 아래 줄은 수집·실험·분석·시각화 탭입니다.</p>''')

# ---------------- i03 ----------------
layers = [
 ("eye", "브라우저 화면", "자료함·검색·실험 등 11개 탭", "설치 없이 익숙한 창에서 쓰려고. 주소 127.0.0.1 — 이 PC에서만 열림", "b", G),
 ("gear", "FastAPI 서버 (Python)", "파싱·청킹·라벨·검색·통계 계산을 하는 앱 본체", "계산을 모두 PC 안에서 하려고", "b", G),
 ("db", "SQLite DB · 데이터 폴더", "rd.sqlite(표 39개 + 전문검색), inbox·library·reports", "파일 하나라 백업이 폴더 복사로 끝남", "b", G),
 ("key", "MCP 서버 byorbit-rd", "AI가 쓸 수 있는 앱 도구 7개(자료 찾기·라벨 저장 등)", "AI가 원본 파일을 직접 못 읽고, 가린 내용만 받게", "p", D),
 ("bot", "Claude Code · Codex", "이 PC에 설치된 AI 실행기 — 라벨·답변·리포트", "셸·파일 읽기 같은 내장 도구를 끄고 앱 도구만 허용", "p", D),
 ("cloud", "외부 서비스", "AI 모델(Anthropic), 학술 API(OpenAlex 등), PubChem·식품 DB(선택)", "꼭 필요한 것만 최소로 밖에 보냄", "wf", W),
]
lay = ""
for i, (icn, name, what, why, cls, col) in enumerate(layers):
    lay += f'''<div class="box {cls}" style="display:grid;grid-template-columns:80px 400px 1fr;gap:22px;align-items:center;padding:20px 28px">{ic(icn, 64, col)}
 <div class="t">{name}</div>
 <div><div><span class="tag">무엇</span> {what}</div><div style="margin-top:4px"><span class="tag {'w' if cls=='wf' else 'g'}">왜</span> {why}</div></div></div>'''
    if i < len(layers) - 1:
        lay += f'<div style="display:flex;justify-content:center;margin:-2px 0">{arrow("d", 40, "#9DB8AD", 6)}</div>'
    if i == 4:
        pass
FIG["i03-architecture"] = page("기술은 몇 층으로 되어 있을까?", "위에서 아래로 갈수록 화면에서 멀어집니다. 주황색 층만 PC 밖입니다.",
    f'''<div>{lay}</div>
<p class="note"><span class="k">초록 테두리</span> = 이 PC 안의 앱 · <span class="k">연한 초록</span> = AI와 앱을 잇는 부분(이 PC 안) · <span class="wk">주황</span> = PC 밖 서비스</p>''')

# ---------------- i04 ----------------
stay = [("doc", "원본 파일", "library 폴더의 PDF·엑셀·한글 파일"), ("db", "DB", "rd.sqlite — 청크·라벨·측정값 전부"),
        ("lock", "CoA 식별 정보", "로트번호·공급처·시료번호"), ("flask", "실험·분석 데이터", "내 실험 런, 통계 계산")]
go = [("chat", "질문 + 본문 일부", "AI(Anthropic)로. CoA 식별 정보는 [가림]", ""),
      ("search", "검색어", "학술·공공 API로. 자료함 내용은 안 보냄", ""),
      ("key", "API 키", "그 키를 준 출처에만. 키는 환경 변수에만 보관", ""),
      ("globe", "선택 기능", "PubChem(영문 성분명 하나) · 식품 DB(식품명·성분값) · Upstage(문서 파일, 기밀은 차단)", "켤 때만")]
st = "".join(f'<div class="box b" style="display:flex;gap:18px;align-items:center;padding:18px 22px">{ic(a, 56, G)}<div><div class="t">{b}</div><div class="s">{c}</div></div></div>' for a, b, c in stay)
gg = "".join(f'<div class="row" style="align-items:center">{arrow("r", 90, W)}<div class="box wf" style="flex:1;display:flex;gap:18px;align-items:center;padding:18px 22px">{ic(a, 56, W)}<div><div class="t">{b} {f"<span class=tag style=background:#fff;color:#B35A20>{d}</span>" if d else ""}</div><div class="s">{c}</div></div></div></div>' for a, b, c, d in go)
st = "".join(f'<div class="box b" style="padding:16px 18px">{ic(a, 50, G)}<div class="t" style="margin-top:4px;font-size:31px">{b}</div><div class="s" style="font-size:31px">{c}</div></div>' for a, b, c in stay)
gg = "".join(f'<div class="box wf" style="display:flex;gap:16px;align-items:center;padding:16px 20px">{ic(a, 52, W)}<div><div class="t" style="font-size:31px">{b} {f"<span class=tag>{d}</span>" if d else ""}</div><div class="s" style="font-size:31px">{c}</div></div></div>' for a, b, c, d in go)
FIG["i04-security"] = page("무엇이 PC 밖으로 나가고, 무엇이 남을까?", "점선이 이 PC의 경계입니다. 밖으로 나가는 길은 앱과 AI 실행기를 거치는 오른쪽 하나뿐이고, 필요한 것만 나갑니다.",
    f'''<div class="row" style="gap:0;align-items:center">
 <div style="flex:0 0 860px;border:5px dashed var(--brand);border-radius:30px;padding:24px 26px 26px;background:#FBFDFC">
   <div style="display:flex;align-items:center;gap:14px;margin-bottom:16px">{ic("pc", 54, D)}<div class="t" style="color:var(--deep)">이 PC 안</div></div>
   <div class="row" style="gap:22px;align-items:center">
     <div style="flex:1"><div class="t2" style="margin-bottom:10px">여기 머무는 것 <span class="tag">밖으로 안 나감</span></div>
       <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">{st}</div></div>
     <div class="box d" style="flex:0 0 220px;text-align:center;padding:22px 14px">{ic("bot", 60, "#fff")}<div class="t" style="margin-top:6px;font-size:31px">앱 · AI 실행기</div><div class="s" style="font-size:31px">보낼 것을 고르고 가린다</div></div>
   </div></div>
 {arrow("r", 96, W, 9, "필요한 것만")}
 <div class="col" style="flex:1;gap:14px"><div class="t2" style="color:#B35A20">PC 밖으로 나가는 것</div>{gg}</div>
</div>
<p class="note">‘보내지 않기’ 규칙을 고르면 기밀(CoA) 본문과 측정값은 AI에도 전혀 넘기지 않습니다. 오류 메시지에서도 API 키는 가립니다.</p>''')

# ---------------- i05 ----------------
impl = [("큰 일", "여러 파일에 걸친 새 기능", "예: M2 묶음 A·B·D"),
        ("단순한 일", "정해진 틀을 따라 하는 일", "예: M2 묶음 C(로컬 OCR 설치)"),
        ("정밀한 일", "계산·보안처럼 꼼꼼함이 중요한 일", "필요할 때 따로 맡김")]
im = "".join(f'<div class="box b" style="display:flex;gap:16px;align-items:center;padding:18px 20px">{ic("bot", 56, G)}<div><div class="t">구현 AI <span style="color:var(--deep)">({a})</span></div><div class="s">{b}</div><div class="tag g" style="margin-top:6px">{c}</div></div></div>' for a, b, c in impl)
FIG["i05-ai-team"] = page("AI 팀은 어떻게 나뉘어 일했을까?", "사람은 방향을 정하고 승인합니다. AI끼리 역할을 나눠 만들고, 메인 AI가 다시 확인합니다.",
    f'''<div class="row" style="align-items:center">
 <div class="box wf" style="flex:0 0 250px;text-align:center;padding:26px 16px">{ic("person", 74, W)}<div class="t" style="margin-top:6px">사람</div><div class="s">요청하고<br>결정하고<br>승인한다</div></div>
 {arrow("r", 60, W)}
 <div class="box d" style="flex:0 0 330px;padding:26px 22px">{ic("bot", 70, "#fff")}<div class="t" style="margin-top:6px">메인 AI</div><ul class="l" style="font-size:31px;color:#E6F4EE"><li>기획·질문</li><li>계약 문서(PLAN) 쓰기</li><li>파일별로 나눠 맡기기</li><li>결과 다시 확인</li></ul></div>
 {arrow("r", 60)}
 <div class="col" style="flex:1;gap:14px">{im}</div>
</div>
<div style="display:flex;justify-content:flex-end;padding-right:300px;margin:10px 0">{arrow("d", 56, D)}</div>
<div class="row" style="align-items:stretch;justify-content:flex-end">
 <div class="box p" style="flex:0 0 330px;padding:20px 22px">{ic("check", 54, D)}<div class="t" style="margin-top:4px">커밋</div><div class="s">사람이 확인한 뒤에만 저장소에 기록</div></div>
 {arrow("l", 60, D)}
 <div class="box p" style="flex:0 0 660px;padding:20px 24px;display:flex;gap:18px;align-items:center">{ic("eye", 58, D)}<div><div class="t">메인 AI의 검증</div><div class="s">자동 시험(pytest) 실행 · 화면을 직접 찍어 보기 · DOI를 Crossref와 원문으로 대조</div></div></div>
</div>
<p class="note">구현 AI의 “다 됐습니다” 보고는 그대로 믿지 않습니다. 메인 AI가 시험과 화면으로 다시 확인합니다.</p>''')

# ---------------- i06 (순환) ----------------
cyc = [("chat", "요청", "‘건조 방식을 그림으로 보고 싶어’"),
       ("q", "질문으로 결정", "구조는 로컬? PubChem은? → 사람이 고름"),
       ("doc", "계약 문서", "PLAN 문서에 할 일·파일·규칙을 적음"),
       ("scissors", "나눠 맡기기", "파일마다 담당 AI를 정해 겹치지 않게"),
       ("eye", "검증", "시험 실행 · 화면 확인 · 출처 원문 대조"),
       ("person", "사용자 확인", "결과를 보고 고칠 점을 말함"),
       ("check", "커밋", "확인된 것만 저장소에 기록")]
import math
RX, R = 520, 450; cx, cy = 728, 545; nodes = ""; W_, H_ = 400, 190
pos = []
for i in range(7):
    a = -math.pi / 2 + i * 2 * math.pi / 7
    x, y = cx + RX * math.cos(a), cy + R * math.sin(a)
    pos.append((x, y))
for i, ((icn, t, s), (x, y)) in enumerate(zip(cyc, pos)):
    cls = "f" if i == 6 else ("wf" if i in (1, 5) else "b")
    colr = "#fff" if i == 6 else (W if i in (1, 5) else G)
    nodes += f'<div class="box {cls}" style="position:absolute;left:{x-W_/2:.0f}px;top:{y-H_/2:.0f}px;width:{W_}px;height:{H_}px;display:flex;gap:14px;align-items:center;padding:14px 18px"><div class="num" style="{"background:#fff;color:var(--brand)" if i==6 else ("background:var(--warn)" if i in (1,5) else "")}">{i+1}</div><div><div class="t" style="font-size:31px">{t}</div><div class="s" style="font-size:31px;margin-top:2px">{s}</div></div></div>'
# 화살표: 원 위 호
arcs = ""
for i in range(7):
    a1 = -math.pi / 2 + i * 2 * math.pi / 7 + 0.30
    a2 = -math.pi / 2 + (i + 1) * 2 * math.pi / 7 - 0.30
    x1, y1 = cx + RX * math.cos(a1), cy + R * math.sin(a1)
    x2, y2 = cx + RX * math.cos(a2), cy + R * math.sin(a2)
    arcs += f'<path d="M{x1:.0f} {y1:.0f} A{RX} {R} 0 0 1 {x2:.0f} {y2:.0f}" fill="none" stroke="#9FD3C1" stroke-width="10" marker-end="url(#ah)"/>'
FIG["i06-build-loop"] = page("기능 하나는 이렇게 만들어졌다", "요청에서 커밋까지 일곱 단계를 돌고, 다음 요청에서 다시 시작합니다.",
    f'''<div style="position:relative;width:1456px;height:1100px">
<svg width="1456" height="900" style="position:absolute;left:0;top:0"><defs><marker id="ah" markerWidth="5" markerHeight="5" refX="2.5" refY="2.5" orient="auto"><path d="M0 0 L5 2.5 L0 5 Z" fill="#9FD3C1"/></marker></defs>{arcs}</svg>
<div style="position:absolute;left:{cx-210}px;top:{cy-80}px;width:420px;text-align:center"><div class="t" style="font-size:38px;color:var(--deep)">한 바퀴 = 기능 하나</div><div class="s" style="font-size:31px">주황 단계는 사람이 직접 하는 일</div></div>
{nodes}</div>''')

# ---------------- i07 ----------------
p1 = [("doc", "파싱", "도구를 골라 글·표를 꺼냄", ["PyMuPDF", "pdfplumber", "RapidOCR", "Docling", "kordoc", "Upstage(클라우드)"]),
      ("gear", "정규화", "글자·단위·줄바꿈 정리", []),
      ("scissors", "청킹", "제목 단위로 알맞은 조각", []),
      ("tag", "사전 라벨", "시소러스로 부산물·성분·단위 표시", []),
      ("db", "적재", "DB와 전문검색에 저장", [])]
r1 = "".join((f'<div class="box b" style="flex:{2.1 if i==0 else 1};padding:20px 18px">{ic(a, 54, G)}<div class="t" style="margin-top:6px">{b}</div><div class="s">{c}</div>{"".join(f"<span class=tag>{t}</span>" for t in tags)}</div>' + (arrow("r", 44) if i < 4 else "")) for i, (a, b, c, tags) in enumerate(p1))
p2 = [("bot", "AI 라벨", "청크 5개씩 묶어 AI가 수치 라벨을 제안", "d"), ("person", "사람 검토", "승인·거절 (단축키 A·R)", "wf"), ("table", "측정값", "승인한 수치만 표로 올라감", "f")]
r2 = "".join((f'<div class="box {cls}" style="flex:1;padding:20px 22px;display:flex;gap:16px;align-items:center">{ic(a, 58, "#fff" if cls in ("d","f") else W)}<div><div class="t">{b}</div><div class="s">{c}</div></div></div>' + (arrow("r", 50, D) if i < 2 else "")) for i, (a, b, c, cls) in enumerate(p2))
FIG["i07-pipeline"] = page("자료 한 개가 처리되는 길", "넣기만 하면 윗줄은 자동으로 진행됩니다. 아랫줄은 AI가 돕고 사람이 확정합니다.",
    f'''<div class="t2" style="color:var(--deep);margin-bottom:12px">① 자동 처리 (자료함에 넣으면 바로)</div>
<div class="row" style="align-items:stretch">{r1}</div>
<div style="display:flex;justify-content:flex-end;padding-right:110px;margin:12px 0">{arrow("d", 60, D)}</div>
<div class="t2" style="color:var(--deep);margin-bottom:12px">② AI가 돕고 사람이 확정</div>
<div class="row" style="align-items:stretch">{r2}</div>
<div class="box g" style="margin-top:28px;display:flex;gap:16px;align-items:center;padding:16px 22px">{ic("table", 48, K)}<div style="font-size:31px"><b>CoA 엑셀</b>은 예외: 양식(시험항목·결과)을 알아보면 시료와 측정값을 처리 단계에서 바로 넣고 등급을 ‘기밀’로 둡니다.</div></div>''')

# ---------------- i08 ----------------
def lane(title, color, src, mids, dest):
    m = "".join(f'<div class="box p" style="padding:14px 18px"><div class="t2">{a}</div><div class="s" style="margin-top:2px">{b}</div></div>' for a, b in mids)
    return f'''<div class="row" style="align-items:center">
<div class="box wf" style="flex:0 0 330px;padding:22px">{ic(src[0], 56, W)}<div class="t" style="margin-top:6px">{src[1]}</div><div class="s">{src[2]}</div></div>
{arrow("r", 64)}
<div class="col" style="flex:1;gap:12px"><div class="t2" style="color:var(--deep)">{title}</div>{m}</div>
{arrow("r", 64)}
<div class="box f" style="flex:0 0 330px;padding:22px">{ic(dest[0], 56, "#fff")}<div class="t" style="margin-top:6px">{dest[1]}</div><div class="s">{dest[2]}</div></div></div>'''
FIG["i08-learning"] = page("고치면 배운다", "사람이 고친 것을 규칙·동의어·사례로 남겨 다음 문서에 자동으로 씁니다. AI 모델 자체를 다시 학습시키지는 않습니다.",
    lane("규칙으로 배움", G, ("scissors", "청크를 고친다", "잡음 줄 지우기·제목으로 올리기·합치기·나누기"),
         [("잡음 줄 · 제목 줄", "‘- 3 -’ 같은 쪽 번호, ‘2. 재료 및 방법’ 같은 제목 꼴"), ("짧은 조각 합치기 · 표 묶기 · 청크 길이", "범위를 골라 저장: 이 자료만 ~ 모든 자료")],
         ("repeat", "다음 문서에 자동", "비슷한 자료를 다시 파싱할 때 규칙 적용"))
    + '<div style="height:34px"></div>' +
    lane("사전·사례로 배움", G, ("tag", "라벨을 고친다", "개념 붙이기·사전 라벨 거절·사람 라벨"),
         [("동의어", "사전이 모르던 표기를 그 개념의 다른 이름으로 등록"), ("부정 사례", "거절한 사전 라벨은 같은 문맥에서 다시 안 붙임"), ("AI 예시", "사람이 붙인 라벨 중 관련 높은 것 최대 8개를 AI 라벨러에게")],
         ("repeat", "다음 라벨·검색에 반영", "사전 라벨·검색·AI 라벨이 바로 달라짐"))
    + '<p class="note">배운 것은 모두 ‘배운 것’ 탭에서 보고 끄거나 지울 수 있습니다. 규칙·동의어·부정 사례는 PC 밖으로 나가지 않습니다.</p>')

# ---------------- i09 ----------------
srcs = f'''<div class="col" style="flex:0 0 500px;gap:16px">
 <div class="box b" style="padding:18px 22px">{ic("globe", 50, G)}<div class="t" style="margin-top:4px">공식 API — 해외 학술 <span class="tag">키 불필요</span></div><div class="s">OpenAlex · Crossref · Europe PMC · Semantic Scholar</div></div>
 <div class="box b" style="padding:18px 22px">{ic("key", 50, G)}<div class="t" style="margin-top:4px">공식 API — 국내 <span class="tag w">키 필요</span></div><div class="s">KCI · ScienceON · NTIS · KIPRIS · 공공데이터(식약처·농사로)</div></div>
 <div class="box b" style="padding:18px 22px">{ic("spider", 50, G)}<div class="t" style="margin-top:4px">크롤러 — API가 없는 공개 목록</div><div class="s">기본(이 PC에서 HTTP) · 브라우저(헤드리스 Chrome) · Apify(클라우드·유료, 선택)</div><div class="s" style="font-size:31px">robots.txt·이용약관을 지키고 사이트마다 간격을 둠</div></div>
</div>'''
FIG["i09-collect"] = page("논문·자료를 모으는 길", "찾은 결과는 바로 자료함에 들어가지 않고, 수집함에서 사람이 고른 뒤에 들어갑니다.",
    f'''<div class="row" style="align-items:center">{srcs}{arrow("r", 64)}
 <div class="box d" style="flex:1;padding:22px">{ic("inbox", 58, "#fff")}<div class="t" style="margin-top:6px">수집함</div><div class="s">같은 자료는 하나로 합침</div><div class="tag" style="background:rgba(255,255,255,.2);color:#fff">DOI → 출처 ID → 제목</div></div>
 {arrow("r", 56)}
 <div class="box wf" style="flex:0 0 200px;padding:22px">{ic("person", 54, W)}<div class="t" style="margin-top:6px">검토</div><div class="s">넣기<br>나중에<br>거절</div></div>
 {arrow("r", 56)}
 <div class="box f" style="flex:0 0 250px;padding:22px">{ic("docs", 54, "#fff")}<div class="t" style="margin-top:6px">자료함</div><div class="s">오픈 액세스면 원문 PDF, 아니면 서지·초록</div></div>
</div>
<div class="box g" style="margin-top:30px;display:flex;gap:18px;align-items:center;padding:16px 22px">{ic("repeat", 48, K)}<div style="font-size:31px"><b>저장 검색</b>: 검색을 저장하면 앱이 켜져 있는 동안 정한 주기(예: 하루마다)로 새 자료를 찾아 수집함에 쌓습니다. 밖으로 나가는 것은 <b>검색어</b>(와 그 출처의 키)뿐입니다.</div></div>''')

# ---------------- i10 ----------------
ex = [("flask", "공정 흐름 편집", "원료 → 세척 → 압착 → 분쇄 → 건조 → 체분리 → 저장. 단계 추가·삭제·순서·값 고치기", "b", G),
      ("table", "내 데이터", "런(한 번의 시험)마다 조건과 잰 값. 표 입력 또는 CSV·XLSX 가져오기", "b", G),
      ("chart", "예측과 비교", "잔차 = 실측 − 예측, 패리티 그림, MAE·RMSE", "b", G),
      ("gear", "보정", "미리보기로 전·후를 나란히 본 뒤 ‘적용’해야 반영", "wf", W),
      ("target", "다음 실험 제안", "비어 있는 온도 채우기·요인 배치 (‘제안’ 표시)", "f", "#fff")]
ee = ""
for i, (a, b, c, cls, col) in enumerate(ex):
    ee += f'<div class="box {cls}" style="flex:1;padding:20px 18px">{ic(a, 54, col)}<div class="t" style="margin-top:6px">{b}</div><div class="s">{c}</div></div>'
    if i < 4:
        ee += arrow("r", 40)
FIG["i10-experiment"] = page("내 실험 데이터로 모델을 맞추는 순환", "예측은 출발점일 뿐입니다. 내가 잰 값으로 비교하고 보정해서 다음 실험을 고릅니다.",
    f'''<div class="row" style="align-items:stretch">{ee}</div>
<div style="position:relative;height:120px">
<svg width="1456" height="120" style="position:absolute;left:0;top:0"><path d="M1330 6 V70 Q1330 100 1300 100 H420 Q390 100 390 70 V22" fill="none" stroke="#1F7A63" stroke-width="8" stroke-linecap="round"/><path d="M374 34 L390 6 L406 34 Z" fill="#1F7A63"/></svg>
<div style="position:absolute;left:640px;top:58px;background:#fff;padding:0 16px;font-size:31px;font-weight:800;color:var(--deep)">새 런을 실험해 데이터에 더하고 다시 비교</div></div>
<p class="note" style="margin-top:6px">건조 단계는 ‘건조 방식’ 탭과 같은 예측 엔진을 씁니다. 세척·압착·분쇄·추출·저장의 계수는 대부분 <span class="wk">가정</span>이라, 내 값을 넣으면 ‘내 입력’으로 바뀝니다.</p>''')

# ---------------- i11 ----------------
sx = [("table", "데이터", ["내 실험", "CSV·XLSX", "예시(가짜)"], "b", G),
      ("chart", "회귀 · t검정", ["수율 ~ 온도 + 시간 + 산 종류", "산 종류별 Welch t검정"], "b", G),
      ("check", "가정 점검", ["정규성·등분산", "다중공선성(VIF)·영향점", "통과·주의·실패와 기준값"], "wf", W),
      ("doc", "논문용 산출물", ["표 1 (APA 형식)", "그림 1 (300 dpi)", "해석 세 문장(한·영)"], "f", "#fff"),
      ("code", "재현 파일", ["Python · R · Stata", "data.csv · codebook.csv"], "d", "#fff")]
xx = ""
for i, (a, b, items, cls, col) in enumerate(sx):
    xx += f'<div class="box {cls}" style="flex:1;padding:20px 18px">{ic(a, 54, col)}<div class="t" style="margin-top:6px">{b}</div><ul class="l" style="font-size:31px">{"".join(f"<li>{t}</li>" for t in items)}</ul></div>'
    if i < 4:
        xx += arrow("r", 38)
FIG["i11-stats"] = page("통계 분석은 이렇게 흘러간다", "계산은 모두 이 PC 안에서 합니다. 숫자는 표·그림·문장에 같은 값으로 들어갑니다.",
    f'''<div class="row" style="align-items:stretch">{xx}</div>
<div class="row" style="gap:20px;margin-top:30px">
<div class="box p" style="flex:1;padding:18px 22px;font-size:31px"><b>t검정과 회귀의 산 효과가 다른 이유</b><br>t검정은 온도·시간을 무시한 단순 차이, 회귀는 온도·시간을 같게 놓은 뒤의 차이입니다. 화면에 두 값을 나란히 보여 줍니다.</div>
<div class="box wf" style="flex:1;padding:18px 22px;font-size:31px"><b>주의</b><br>Python 스크립트는 앱과 같은 숫자를 시험으로 확인했지만, <b>R·Stata 스크립트는 이 PC에 R·Stata가 없어 실행해 보지 못했습니다.</b></div>
</div>''')

# ---------------- i12 ----------------
bd = [("book", "문헌", "DOI 확인", G, "",
       "논문에서 가져온 값. DOI를 Crossref와 원문으로 확인했습니다.", "조건이 그 논문이 다룬 범위 안일 때", "범위 밖이면 ‘외삽’ 경고 — 오차가 커집니다"),
      ("ruler", "실측", "n", D, "",
       "내 CoA·내 실험에서 잰 값. n은 몇 개를 쟀는지입니다.", "n이 클수록, 같은 원료·같은 방법일 때", "n ≤ 2이면 ‘보정 신뢰도 낮음’"),
      ("gear", "설비 사양", "", K, "",
       "건조기 출력·용량 같은 설비 값. 설정 파일 equipment.json에 있음.", "내 설비 값으로 고쳐 넣었을 때", "기본값 그대로라면 내 설비와 다를 수 있음"),
      ("q", "가정", "", W, "",
       "근거를 찾지 못해 일반적인 크기로 잡은 값입니다.", "대략의 방향을 볼 때만", "숫자 자체를 믿지 말고 내 측정으로 바꾸기")]
bb = ""
for a, n, sub, col, _, what, trust, doubt in bd:
    pale = {G: "var(--pale)", D: "#E2EFEA", K: "#EEF0EF", W: "var(--warnpale)"}[col]
    bb += f'''<div class="box" style="flex:1;border-color:{col};padding:0;overflow:hidden;display:flex;flex-direction:column">
<div style="background:{col};color:#fff;padding:18px 22px;display:flex;gap:14px;align-items:center">{ic(a, 54, "#fff")}<div><div class="t" style="font-size:38px">{n}</div>{f'<div style="font-size:31px;opacity:.9">{sub}</div>' if sub else ''}</div></div>
<div style="padding:18px 22px;flex:1">{what}
<div style="margin-top:14px;background:{pale};border-radius:14px;padding:12px 14px"><b style="color:var(--deep)">믿을 때</b><br>{trust}</div>
<div style="margin-top:10px;background:var(--warnpale);border-radius:14px;padding:12px 14px"><b style="color:#B35A20">의심할 때</b><br>{doubt}</div></div></div>'''
FIG["i12-evidence"] = page("예측값 옆의 근거 배지 4가지", "예측 화면의 값마다 붙는 배지입니다. 배지를 보면 그 숫자를 얼마나 믿을지 알 수 있습니다.",
    f'<div class="row" style="gap:20px;align-items:stretch">{bb}</div><p class="note">예측값은 측정값이 아닙니다. 중요한 결정 전에는 실제 시험으로 확인하세요.</p>')

# ---------------- i13 ----------------
el = [("target", "목적", "무엇에 쓰려고?", "팀 회의에서 건조 방법을 고르려고", G),
      ("lock", "조건", "지켜야 할 것", "자료함의 논문·CoA만 근거로, 수치마다 근거 번호", D),
      ("doc", "결과물", "어떤 모양으로?", "표 1개 + 세 문장 요약", W),
      ("check", "확인 방법", "맞는지 어떻게 보나?", "수치마다 출처 청크를 달아 원문과 대조", K)]
ee = ""
for i, (a, n, q, e, col) in enumerate(el):
    ee += f'''<div class="box" style="flex:1;border-color:{col};padding:22px">
<div style="display:flex;gap:14px;align-items:center"><div class="num" style="background:{col}">{i+1}</div><div class="t" style="font-size:38px">{n}</div></div>
<div style="margin-top:10px;display:flex;gap:14px;align-items:center">{ic(a, 52, col)}<div class="s" style="margin:0">{q}</div></div>
<div style="margin-top:12px;font-size:31px">예) {e}</div></div>'''
FIG["i13-prompt"] = page("좋은 AI 요청의 4요소", "AI에게 일을 맡길 때 이 네 가지를 한 번에 말하면 다시 묻고 고치는 일이 줄어듭니다.",
    f'''<div class="row" style="gap:20px;align-items:stretch">{ee}</div>
<div class="box p" style="margin-top:32px;padding:26px 30px;font-size:31px;line-height:1.7">
<div class="t2" style="color:var(--deep);margin-bottom:8px">이렇게 이어 쓰면 하나의 요청</div>
“<span style="border-bottom:5px solid {G}">팀 회의에서 건조 방법을 고르려고 하니</span>
<span style="border-bottom:5px solid {D}">자료함의 논문과 CoA만 근거로 쓰고 수치마다 근거 번호를 달아서</span>
<span style="border-bottom:5px solid {W}">동결건조와 열풍건조의 식이섬유·폴리페놀 차이를 표 1개와 세 문장으로 정리해 줘.</span>
<span style="border-bottom:5px solid {K}">내가 원문과 맞춰 볼 수 있게 출처 청크도 함께 보여 줘.</span>”</div>''')

exec(open(OUT / "gen_info_extra.py", encoding="utf-8").read())

for name, html in FIG.items():
    (OUT / f"{name}.html").write_text(html, encoding="utf-8")
    print("wrote", name)
