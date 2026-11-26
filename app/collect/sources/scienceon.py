"""KISTI ScienceON API Gateway — 국내외 논문(ARTI)·국가R&D 보고서(REPORT) 검색(키 + 토큰 발급 필요).

공식 문서(2026-11-25 확인)
- 토큰 안내: https://scienceon.kisti.re.kr/por/api/way/guide/tokenGuide.do
- 검색 공통: https://scienceon.kisti.re.kr/por/api/way/guide/searchAPIcommon.do
- 논문 검색: https://scienceon.kisti.re.kr/por/api/way/arti/serviceArtiSearchApi.do
- 보고서 검색: https://scienceon.kisti.re.kr/por/api/way/report/serviceReportSearchApi.do
- 오류 코드: https://scienceon.kisti.re.kr/por/api/way/guide/errorCodeGuide.do
- 자료실의 공식 토큰 발급 샘플(Java·Python, 2021-05-27): https://scienceon.kisti.re.kr/por/api/material/pdsList.do

토큰 흐름(공식 샘플 그대로)
1. plain = {"datetime":"YYYYMMDDHHMMSS","mac_address":"AA-BB-CC-DD-EE-FF"} (공백 없는 JSON, 현지 시각,
   MAC은 활용신청 때 등록한 값)
2. AES-256-CBC + PKCS7, 키 = 발급받은 32자 인증키(UTF-8), IV = 고정 문자열 "jvHJ1EFA0IXBrxxz"
3. URL-safe Base64 → URL 인코딩 → GET https://apigateway.kisti.re.kr/tokenrequest.do?client_id=…&accounts=…
4. 응답 JSON: access_token(2시간), access_token_expire, refresh_token(2주), … — 이 앱은 토큰을 메모리에만 두고
   만료되면 다시 발급한다(디스크에 저장하지 않음). 문서 예시가 표준 Base64(%2B·%2F)를 보이므로 E4006이면
   표준 Base64로 한 번 더 시도한다.
검색: GET https://apigateway.kisti.re.kr/openapicall.do?client_id&token&version=1.0&action=search&target=ARTI|REPORT
      &searchQuery={"BI":"검색어"}(URL 인코딩)&curPage=1&rowCount(≤100)[&sortField=pubyear]
응답(XML): MetaData > resultSummary > TotalCount·statusCode, recordList > record > item[@metaCode]
  ARTI: CN, DBCode, Title, Author(';' 구분), Pubyear, JournalName, Publisher, ISSN, VolNo1·VolNo2, PageInfo,
        Abstract, Keyword, DOI, FulltextURL, ContentURL(랜딩), FulltextFlag
  REPORT: CN(TRKO…), Title, Author, Publisher, Pubdate, Pubyear, Abstract, Keyword, FulltextURL, ContentURL, Pjn(과제번호)
오류: errorDetail > errorCode·errorMessage (예: E4102 클라이언트ID 값 오류 — 2026-11-25 실제 호출로 확인),
      토큰 오류는 JSON {"errorCode":"E4005",…}. 한도: 초당 2회(E4901) → 호출 간격 0.6초.
원문: FulltextURL은 ScienceON 원문 보기 화면인 경우가 많아, 주소가 .pdf로 끝날 때만 pdf_url로 넘긴다.
밖으로 나가는 것: 검색어, client_id, 암호화된 (시각·MAC 주소), 토큰. 키 셋은 환경 변수로만 받는다.
※ 실제 키로 미검증(문서·공식 샘플·키 없는 호출 응답으로만 확인).
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime

from .. import http
from ..base import Item, Source, SourceError
from .kci import _find, _t, mask

GATEWAY = "https://apigateway.kisti.re.kr"
TOKEN_URL = GATEWAY + "/tokenrequest.do"
SEARCH_URL = GATEWAY + "/openapicall.do"
IV = b"jvHJ1EFA0IXBrxxz"
ENV_CLIENT = "BYORBIT_SCIENCEON_CLIENT_ID"
ENV_KEY = "BYORBIT_SCIENCEON_KEY"
ENV_MAC = "BYORBIT_SCIENCEON_MAC"
http.set_interval("apigateway.kisti.re.kr", 0.6)


# ================================================================ AES-256-CBC (암호화만, 표준 라이브러리)
# 토큰 요청 한 줄을 암호화하는 데만 쓴다. FIPS-197 시험 벡터로 검사한다(tests/test_collect_kr.py).

def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x11B) & 0xFF if a & 0x100 else a


def _make_sbox() -> list[int]:
    sbox = [0] * 256
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)          # p *= 3
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09                                                   # q /= 3
        x = q ^ ((q << 1) | (q >> 7)) & 0xFF ^ ((q << 2) | (q >> 6)) & 0xFF \
            ^ ((q << 3) | (q >> 5)) & 0xFF ^ ((q << 4) | (q >> 4)) & 0xFF
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox


_SBOX = _make_sbox()


def _expand_key(key: bytes) -> list[list[int]]:
    nk, nr = len(key) // 4, {16: 10, 24: 12, 32: 14}[len(key)]
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = [_SBOX[b] for b in t[1:] + t[:1]]
            t[0] ^= rcon
            rcon = _xtime(rcon)
        elif nk > 6 and i % nk == 4:
            t = [_SBOX[b] for b in t]
        w.append([a ^ b for a, b in zip(w[i - nk], t)])
    return [sum(w[4 * r:4 * r + 4], []) for r in range(nr + 1)]


def _encrypt_block(block: bytes, rk: list[list[int]]) -> bytes:
    s = [b ^ k for b, k in zip(block, rk[0])]
    nr = len(rk) - 1
    for rnd in range(1, nr + 1):
        s = [_SBOX[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]              # ShiftRows(열 우선 배치)
        if rnd != nr:
            m = []
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                b = [_xtime(x) for x in a]
                m += [b[0] ^ a[3] ^ a[2] ^ b[1] ^ a[1], b[1] ^ a[0] ^ a[3] ^ b[2] ^ a[2],
                      b[2] ^ a[1] ^ a[0] ^ b[3] ^ a[3], b[3] ^ a[2] ^ a[1] ^ b[0] ^ a[0]]
            s = m
        s = [b ^ k for b, k in zip(s, rk[rnd])]
    return bytes(s)


def aes_cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    if len(key) not in (16, 24, 32) or len(iv) != 16:
        raise ValueError("AES 키는 16/24/32바이트, IV는 16바이트여야 합니다.")
    pad = 16 - len(data) % 16
    data += bytes([pad]) * pad                                           # PKCS7
    rk = _expand_key(key)
    out, prev = bytearray(), iv
    for i in range(0, len(data), 16):
        prev = _encrypt_block(bytes(a ^ b for a, b in zip(data[i:i + 16], prev)), rk)
        out += prev
    return bytes(out)


def make_accounts(auth_key: str, mac: str, now: datetime | None = None, urlsafe: bool = True) -> str:
    plain = json.dumps({"datetime": (now or datetime.now()).strftime("%Y%m%d%H%M%S"),
                        "mac_address": mac.strip().upper().replace(":", "-")}, separators=(",", ":"))
    key = auth_key.encode("utf-8")
    if len(key) != 32:
        raise SourceError("ScienceON 인증키는 32자여야 합니다. 설정 → API 키 관리의 BYORBIT_SCIENCEON_KEY 값을 확인하세요.")
    enc = aes_cbc_encrypt(key, IV, plain.encode("utf-8"))
    return (base64.urlsafe_b64encode if urlsafe else base64.b64encode)(enc).decode("ascii")


# ================================================================ 응답 해석

def _items(rec: ET.Element) -> dict[str, str]:
    out = {}
    for it in rec:
        code = it.get("metaCode")
        if code and code not in out:
            v = _t(it)
            if v:
                out[code] = v
    return out


def parse(xml_text: str, target: str) -> tuple[list[Item], int | None]:
    try:
        root = ET.fromstring(xml_text.strip().encode("utf-8"))
    except ET.ParseError as e:
        raise SourceError(f"ScienceON 응답을 읽지 못했습니다(XML 오류: {e}). 잠시 뒤 다시 시도하세요.") from None
    code = _t(_find(root, "errorCode"))
    if code:
        raise SourceError(f"ScienceON 오류 {code}: {_t(_find(root, 'errorMessage')) or ''}".strip()
                          + (" — 활용신청 승인·client_id·인증키·MAC 주소를 확인하세요." if code.startswith("E41") else ""))
    tc = _t(_find(root, "TotalCount"))
    total = int(tc) if tc and tc.isdigit() else None
    out = []
    for rec in root.iter("record"):
        f = _items(rec)
        cn = f.get("CN")
        if not (cn or f.get("Title")):
            continue
        ft = f.get("FulltextURL")
        pdf = ft if ft and urllib.parse.urlsplit(ft).path.lower().endswith(".pdf") else None
        authors = [a.strip() for a in (f.get("Author") or "").replace("|", ";").split(";") if a.strip()]
        is_report = target == "REPORT"
        extra = {"cn": cn, "db": f.get("DBCode"), "keyword": f.get("Keyword"), "fulltext_url": ft,
                 "fulltext_flag": f.get("FulltextFlag"), "issn": f.get("ISSN"), "pages": f.get("PageInfo"),
                 "volume": f.get("VolNo1"), "issue": f.get("VolNo2"), "과제번호": f.get("Pjn"),
                 "발행일": f.get("Pubdate")}
        out.append(Item(
            source="scienceon", source_id=cn or f["Title"][:80], title=f.get("Title") or "",
            doi=f.get("DOI"), authors=authors[:30], year=f.get("Pubyear") or (f.get("Pubdate") or "")[:4] or None,
            venue=(f.get("Publisher") if is_report else f.get("JournalName") or f.get("Publisher")),
            abstract=f.get("Abstract"),
            url=f.get("ContentURL") or (f"https://scienceon.kisti.re.kr/srch/selectPORSrchArticle.do?cn={cn}"
                                        if cn else None),
            pdf_url=pdf, oa=True if pdf else None,
            language="ko" if (cn or "").startswith(("JAKO", "TRKO", "DIKO", "CFKO")) else None,
            doc_type="report" if is_report else ("thesis" if (cn or "").startswith("DIKO") else "article"),
            extra={k: v for k, v in extra.items() if v},
        ).normalized())
    return out, total


# ================================================================ 출처

class ScienceON(Source):
    key = "scienceon"
    name = "ScienceON (KISTI)"
    group = "국내 학술"
    homepage = "https://scienceon.kisti.re.kr"
    terms_url = "https://scienceon.kisti.re.kr/por/api/way/guide/tokenGuide.do"
    needs_env = (ENV_CLIENT, ENV_KEY, ENV_MAC)
    key_help = ("ScienceON(https://scienceon.kisti.re.kr) 회원 가입·로그인 → API Gateway 'API 활용신청'"
                "(https://scienceon.kisti.re.kr/por/api/useRequest/useRequestList.do)에서 이 PC의 MAC 주소를 적어 신청 → "
                "승인되면 client_id(64자)와 인증키(32자)를 받습니다. 설정 → API 키 관리에서 BYORBIT_SCIENCEON_CLIENT_ID, "
                "BYORBIT_SCIENCEON_KEY, BYORBIT_SCIENCEON_MAC(신청 때 적은 MAC, 예: B4-2E-99-AD-48-7D) 세 값을 모두 넣으세요(또는 같은 이름의 환경 변수).")
    doc_types = ("article", "report", "thesis")
    env_labels = {ENV_CLIENT: "client_id (64자)", ENV_KEY: "인증키 (32자)", ENV_MAC: "MAC 주소 (신청 때 적은 값)"}

    def __init__(self):
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    def reset(self) -> None:
        """키가 바뀌면 메모리의 access_token을 버린다."""
        with self._lock:
            self._token = None

    def _secrets(self) -> tuple[str, str, str]:
        return self.env(ENV_CLIENT), self.env(ENV_KEY), self.env(ENV_MAC)

    def _issue(self, client: str, key: str, mac: str) -> str:
        last = None
        for urlsafe in (True, False):
            acc = make_accounts(key, mac, urlsafe=urlsafe)
            try:
                data = http.get_json(TOKEN_URL, {"client_id": client, "accounts": acc})
            except http.HttpError as e:
                raise SourceError(mask(f"ScienceON 토큰 발급 실패: {e}", client, key, acc)) from None
            tok = data.get("access_token") if isinstance(data, dict) else None
            if tok:
                exp = time.time() + 110 * 60                   # 2시간 유효 — 여유를 두고 1시간 50분
                try:
                    exp = min(exp, datetime.strptime(str(data.get("access_token_expire"))[:19],
                                                     "%Y-%m-%d %H:%M:%S").timestamp() - 300)
                except ValueError:
                    pass
                self._token = (tok, exp)
                return tok
            last = data if isinstance(data, dict) else {}
            if last.get("errorCode") != "E4006":
                break
        raise SourceError(mask(f"ScienceON 토큰 발급 실패({last.get('errorCode', '?')} "
                               f"{last.get('errorMessage', '')}). client_id·인증키·등록 MAC 주소·승인 상태를 확인하세요.",
                               client, key))

    def token(self, client: str, key: str, mac: str, force: bool = False) -> str:
        with self._lock:
            if not force and self._token and self._token[1] > time.time():
                return self._token[0]
            return self._issue(client, key, mac)

    def _search_target(self, target: str, query: str, rows: int, client: str, key: str, mac: str) -> list[Item]:
        for attempt in (1, 2):
            tok = self.token(client, key, mac, force=attempt == 2)
            params = {"client_id": client, "token": tok, "version": "1.0", "action": "search", "target": target,
                      "searchQuery": json.dumps({"BI": query}, ensure_ascii=False), "curPage": 1, "rowCount": rows}
            try:
                txt = http.get_text(SEARCH_URL, params, {"Accept": "application/xml"})
                items, _ = parse(txt, target)
                return items
            except http.HttpError as e:
                raise SourceError(mask(f"ScienceON 검색 실패: {e}", client, key, tok)) from None
            except SourceError as e:
                if attempt == 1 and "E4103" in str(e):          # 토큰 만료 → 새로 발급해 한 번 더
                    continue
                raise SourceError(mask(str(e), client, key, tok)) from None
        return []

    def search(self, query: str, *, limit: int = 25, since_year: int | None = None) -> list[Item]:
        client, key, mac = self._secrets()
        rows = max(1, min(int(limit), 100))
        arts = self._search_target("ARTI", query, rows, client, key, mac)
        try:
            reps = self._search_target("REPORT", query, rows, client, key, mac)
        except SourceError:
            reps = []                                           # 보고서 검색 실패는 논문 결과를 막지 않는다
        merged = []
        for pair in zip(arts, reps):
            merged.extend(pair)
        merged += arts[len(reps):] + reps[len(arts):]
        if since_year:
            merged = [i for i in merged if not i.year or i.year >= since_year]
        return merged[:limit]


SOURCE = ScienceON()
