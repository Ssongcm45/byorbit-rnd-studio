# gen_info.py 끝에서 exec로 읽는 추가 인포그래픽(i14·i15·i16). gen_info.py의 page·ic·arrow·FIG·색 상수를 그대로 쓴다.
# i15의 관계는 표준 시드(seed-2)를 새 데이터 폴더에 적재해 조회한 실제 값이다(사과박의 broader·derivedFrom·generatedBy·contains, 과실 착즙박의 형제·상위).

# ---------------- i14 ----------------
def chip(t, cls=""):
    return f'<span class="tag {cls}" style="font-size:31px">{t}</span>'

p_onto = f'''<div class="box b" style="flex:1;padding:24px 24px">
<div style="display:flex;gap:14px;align-items:center">{ic("book", 60, G)}<div><div class="t" style="font-size:40px">온톨로지</div><div class="s" style="margin:0">분류와 관계의 규칙 = 도서관 분류표</div></div></div>
<div style="margin-top:18px;font-size:31px;line-height:1.5">
<div><b>농업</b></div><div style="padding-left:30px">└ <b>과실 착즙박</b></div><div style="padding-left:66px">└ <b style="color:var(--deep)">사과박</b></div>
</div>
<div style="margin-top:16px;background:var(--pale);border-radius:14px;padding:14px 16px;font-size:31px;line-height:1.45">
부산물 —<b>원료</b>→ 원물<br>부산물 —<b>발생 공정</b>→ 공정<br>부산물 —<b>함유 성분</b>→ 성분</div>
<div class="s" style="margin-top:14px">체계 9개 · 관계 4종</div></div>'''

p_thes = f'''<div class="box b" style="flex:1;padding:24px 24px">
<div style="display:flex;gap:14px;align-items:center">{ic("chat", 60, G)}<div><div class="t" style="font-size:40px">시소러스</div><div class="s" style="margin:0">표준명 + 동의어 = 유의어 사전</div></div></div>
<div style="margin-top:18px;font-size:31px"><span class="tag" style="font-size:33px;background:var(--brand);color:#fff">사과박</span> <span style="color:var(--gray)">표준명</span></div>
<div style="margin-top:12px;line-height:1.9">{chip("사과 착즙박")}{chip("사과 포마스")}{chip("apple marc")}{chip("사과찌꺼기")}{chip("Apple pomace")}</div>
<div style="margin-top:10px;font-size:31px">숨은 표기 {chip("사과퍼미스", "g")}</div>
<div class="s" style="margin-top:14px">어느 이름으로 찾아도 같은 개념</div></div>'''

p_kg = f'''<div class="box b" style="flex:1;padding:24px 24px">
<div style="display:flex;gap:14px;align-items:center">{ic("globe", 60, G)}<div><div class="t" style="font-size:40px">지식그래프</div><div class="s" style="margin:0">점과 선 = 지하철 노선도</div></div></div>
<svg width="100%" viewBox="0 0 420 300" style="margin-top:12px">
<g stroke-width="5" fill="none">
<line x1="210" y1="150" x2="70" y2="50" stroke="#E07B39"/><line x1="210" y1="150" x2="350" y2="50" stroke="#2DA082"/>
<line x1="210" y1="150" x2="70" y2="255" stroke="#6D6E71" stroke-dasharray="10 8"/><line x1="210" y1="150" x2="350" y2="255" stroke="#1F7A63" stroke-dasharray="10 8"/></g>
<g font-family="Pretendard,Malgun Gothic" font-size="27" text-anchor="middle" font-weight="700">
<rect x="140" y="125" width="140" height="50" rx="12" fill="#1F7A63"/><text x="210" y="160" fill="#fff">사과박</text>
<rect x="10" y="25" width="120" height="50" rx="12" fill="#fff" stroke="#E07B39" stroke-width="4"/><text x="70" y="60" fill="#231F20">사과</text>
<rect x="290" y="25" width="120" height="50" rx="12" fill="#fff" stroke="#2DA082" stroke-width="4"/><text x="350" y="60" fill="#231F20">펙틴</text>
<rect x="0" y="230" width="140" height="50" rx="12" fill="#F6F8F7" stroke="#6D6E71" stroke-width="4"/><text x="70" y="265" fill="#231F20">논문</text>
<rect x="280" y="230" width="140" height="50" rx="12" fill="#F6F8F7" stroke="#1F7A63" stroke-width="4"/><text x="350" y="265" fill="#231F20">측정값</text></g></svg>
<div style="font-size:31px;line-height:1.45;margin-top:6px">원료·함유 성분(시드) + <b>언급</b>(자료) + <b>측정</b>(측정값)</div></div>'''

FIG["i14-onto-thesaurus-kg"] = page("개념 지도를 이루는 세 가지", "규칙(온톨로지)으로 틀을 잡고, 이름(시소러스)을 맞추고, 연결(지식그래프)로 봅니다. 예는 모두 이 앱의 표준 시드입니다.",
    f'<div class="row" style="gap:22px;align-items:stretch">{p_onto}{p_thes}{p_kg}</div>')

# ---------------- i15 ----------------
EC = {"broader": "#1F7A63", "derivedFrom": "#E07B39", "generatedBy": "#6D6E71", "contains": "#2DA082"}
nodes = {  # 이름: (x, y, 종류)
    "사과박": (728, 470, "center"),
    "과실 착즙박": (728, 250, "cat"), "농업": (728, 70, "cat"),
    "배박": (1250, 120, "sib"), "포도박": (1250, 250, "sib"), "감귤박": (1250, 380, "sib"),
    "사과": (200, 400, "com"), "착즙": (200, 560, "proc"),
}
cons = ["식이섬유", "펙틴", "폴리페놀", "당류", "말산", "클로로겐산", "퀘르세틴", "에피카테킨", "플로리진", "프로시아니딘 B2"]
for i, n in enumerate(cons):
    row, col = divmod(i, 5)
    nodes[n] = (150 + col * 289, 760 + row * 140, "con")
edges = [("사과박", "과실 착즙박", "broader"), ("과실 착즙박", "농업", "broader"),
         ("배박", "과실 착즙박", "broader"), ("포도박", "과실 착즙박", "broader"), ("감귤박", "과실 착즙박", "broader"),
         ("사과박", "사과", "derivedFrom"), ("사과박", "착즙", "generatedBy")] + [("사과박", c, "contains") for c in cons]
svg = "".join(f'<line x1="{nodes[a][0]}" y1="{nodes[a][1]}" x2="{nodes[b][0]}" y2="{nodes[b][1]}" stroke="{EC[t]}" stroke-width="{6 if t != "contains" else 4}" opacity="{1 if t != "contains" else .75}"/>' for a, b, t in edges)
STY = {"center": "background:var(--deep);color:#fff;border-color:var(--deep);font-size:40px;padding:14px 28px",
       "cat": "background:var(--pale);border-color:#1F7A63",
       "sib": "background:#fff;border-color:#1F7A63;color:var(--gray)",
       "com": "background:var(--warnpale);border-color:#E07B39",
       "proc": "background:#EEF0EF;border-color:#6D6E71",
       "con": "background:#fff;border-color:#2DA082"}
nd = "".join(f'<div style="position:absolute;left:{x}px;top:{y}px;transform:translate(-50%,-50%);border:4px solid;border-radius:16px;padding:10px 20px;font-weight:800;font-size:33px;white-space:nowrap;{STY[k]}">{n}</div>' for n, (x, y, k) in nodes.items())
leg = "".join(f'<span style="display:inline-flex;align-items:center;gap:10px;margin-right:30px"><span style="display:inline-block;width:56px;height:8px;background:{EC[k]};border-radius:4px"></span>{t}</span>'
              for k, t in [("broader", "상위 분류"), ("derivedFrom", "원료"), ("generatedBy", "발생 공정"), ("contains", "함유 성분")])
FIG["i15-kg-example"] = page("사과박 둘레의 실제 관계", "표준 시드(seed-2)를 그대로 그렸습니다. 내 자료가 쌓이면 여기에 ‘언급’과 ‘측정’ 선이 더해집니다.",
    f'''<div style="position:relative;width:1456px;height:940px">
<svg width="1456" height="940" style="position:absolute;left:0;top:0">{svg}</svg>{nd}
<div style="position:absolute;left:1250px;top:470px;transform:translate(-50%,-50%);font-size:31px;color:var(--gray);text-align:center">같은 과실 착즙박</div>
<div style="position:absolute;left:330px;top:680px;transform:translate(-50%,-50%);font-size:31px;color:var(--deep);font-weight:700">아래: 함유 성분 10가지</div></div>
<div style="font-size:31px;margin-top:10px">{leg}</div>''')

# ---------------- i16 ----------------
def tbox(icn, t, s, cls="b", col=G, extra=""):
    return f'<div class="box {cls}" style="display:flex;gap:16px;align-items:center;padding:20px 22px;{extra}">{ic(icn, 60, col)}<div><div class="t" style="font-size:36px">{t}</div><div class="s" style="margin-top:4px">{s}</div></div></div>'
FIG["i16-dev-cloud-map"] = page("이 프로젝트와 개발 도구·클라우드", "실선은 실제로 쓰는 것, 점선은 소개만 하고 쓰지 않는 것입니다.",
    f'''<div style="display:grid;grid-template-columns:1fr 90px 1fr;row-gap:26px;align-items:center">
<div style="border:4px dashed var(--brand);border-radius:26px;padding:22px;display:flex;flex-direction:column;gap:18px">
  <div class="t2" style="color:var(--deep)">내 PC</div>
  {tbox("pc", "R&amp;D Studio V0.5", "Python 앱 + SQLite DB · 127.0.0.1에서만 열림", "f", "#fff")}
  {tbox("repeat", "git", "변경 기록(커밋) — 사람이 요청할 때만")}
</div>
{arrow("r", 80)}
{tbox("lock", "GitHub", "비공개 저장소에 기록을 올려 둠")}
<div style="display:flex;gap:16px;align-items:center;padding-left:40px">{arrow("d", 80)}<div style="font-size:31px;color:var(--gray)">식품 영양 DB 연결(선택)<br>식품명·성분값만 묻습니다</div></div><div></div><div></div>
<div style="border:4px solid var(--warn);border-radius:26px;padding:22px;display:flex;flex-direction:column;gap:18px;background:var(--warnpale)">
  <div class="t2" style="color:#B35A20">식품 MCP (옆 프로젝트, 선택 연결)</div>
  {tbox("cloud", "Vercel", "식품 MCP 원격 서버(Next.js)", "w", W)}
  {tbox("db", "Neon", "식품 영양 DB(Postgres)", "w", W)}
</div>
<div></div>
<div style="display:flex;flex-direction:column;gap:18px">
  {tbox("db", "Supabase", "DB·로그인·파일 — 팀용 버전 후보", "g", K, "border-style:dashed")}
  {tbox("globe", "Cloudflare", "도메인·CDN·터널 — 이 앱을 인터넷에 열지 않음", "g", K, "border-style:dashed")}
  <div style="font-size:31px;color:var(--gray)">점선 = 선택(미사용)</div>
</div>
</div>
<div class="note">DB 접속 주소(DATABASE_URL)는 식품 MCP 프로젝트의 .env.local에만 있습니다. 이 앱의 설정·코드·저장소에는 키가 없습니다.</div>''')

# ---------------- i17 ----------------
def mbox(n, icn, t, s, use, cls="b", col=G, extra=""):
    return f'''<div class="box {cls}" style="flex:1;padding:20px 22px;{extra}">
<div style="display:flex;gap:12px;align-items:center"><div class="num" style="background:{col}">{n}</div>{ic(icn, 52, col)}<div class="t" style="font-size:36px">{t}</div></div>
<div style="font-size:31px;margin-top:10px;line-height:1.45">{s}</div>
<div style="margin-top:10px">{use}</div></div>'''
qs = [("공식 API가 있나?", "공식 API"), ("서버가 그려 주는 목록인가?", "직접 크롤러"),
      ("자바스크립트로 그리는 화면인가?", "브라우저(Playwright)"), ("대량·막힘·관리를 맡길까?", "Apify")]
flow = ""
for i, (q, a) in enumerate(qs):
    flow += f'''<div style="display:flex;align-items:center;gap:14px;margin:8px 0">
<div class="box p" style="flex:0 0 560px;padding:14px 20px;font-size:32px;font-weight:700">{q}</div>
<div style="font-size:31px;color:var(--deep);font-weight:800">예 →</div>
<div class="box f" style="flex:0 0 360px;padding:14px 20px;font-size:32px;font-weight:800">{a}</div>
<div style="font-size:31px;color:var(--gray)">{"아니오 ↓" if i < 3 else ""}</div></div>'''
FIG["i17-crawl-methods"] = page("자료를 모으는 네 가지 방법", "위에서부터 차례로 묻고, ‘예’가 나오는 곳을 씁니다. 어느 방법이든 robots.txt·약관·간격을 지킵니다.",
    f'''<div>{flow}</div>
<div class="box wf" style="margin:8px 0 26px;padding:14px 20px;font-size:31px">처음 보는 사이트를 한 번 둘러보기만 → <b>Playwright MCP</b>(내 Claude Code, 기밀 없는 폴더에서. 이 앱 안에서는 쓰지 않음)</div>
<div class="row" style="gap:16px;align-items:stretch">
{mbox(1, "key", "공식 API", "검색어를 정해진 창구에 보냄", chip("무료 대부분") + chip("가장 안전"))}
{mbox(2, "spider", "직접 크롤러", "HTML 목록을 천천히 읽음", chip("설치 없음") + chip("JS 못 읽음", "g"))}
{mbox(3, "pc", "브라우저", "헤드리스 Chrome이 화면을 그려 읽음", chip("JS 읽음") + chip("느림", "g"))}
{mbox(4, "cloud", "Apify", "클라우드 서버가 대신 크롤링", chip("유료", "w") + chip("미검증", "g"), "wf", W)}
</div>''')
