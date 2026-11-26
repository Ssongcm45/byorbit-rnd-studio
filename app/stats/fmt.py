"""논문용 숫자 표기 (APA 7 기준을 기본으로).

- p: 소수 셋째 자리, p < .001, 반올림하면 .050이 되는 .0495 ≤ p < .05는 넷째 자리까지(유의 여부가 뒤집혀 보이지 않게), > .999.
- 1을 넘을 수 없는 값(p, R², β, r)은 영어 APA에서 앞의 0을 뺀다(.034). 한국어 학술지 관행은 0을 쓴다(0.034) — zero 옵션으로 고른다.
- 음수 부호는 표·그림에서 '−'(U+2212), CSV는 '-'.
"""
from __future__ import annotations

import math

MINUS = "−"


def zero_for(lang: str, zero: str | None) -> bool:
    """True면 앞의 0을 쓴다(0.034). zero: 'auto'(한국어=씀, 영어=뺌) | 'apa'(뺌) | 'leading'(씀)."""
    if zero == "apa":
        return False
    if zero == "leading":
        return True
    return lang == "ko"


def dec_for(se: float | None, lo: int = 2, hi: int = 4) -> int:
    """SE 크기에 맞춘 소수 자리: SE 0.012 → 3, 0.25 → 2, 1.3 → 2."""
    if se is None or not math.isfinite(se) or se <= 0:
        return lo
    return max(lo, min(hi, 1 - math.floor(math.log10(se))))


def n(x, d: int = 2, minus: str = MINUS) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    s = f"{x:.{d}f}"
    if s.startswith("-"):
        s = s[1:] if float(s) == 0 else minus + s[1:]
    return s


def bounded(x, d: int = 2, lead: bool = False, minus: str = MINUS) -> str:
    """1을 넘지 않는 값(R², β, r, p): lead=False면 '0.' → '.'"""
    s = n(x, d, minus)
    if not lead:
        s = s.replace("0.", ".", 1) if s.lstrip(minus + "-").startswith("0.") else s
    return s


def p_val(p, lead: bool = False) -> str:
    """'< .001' · '.034' · '.0495' · '> .999' (등호 없음)"""
    if p is None or not math.isfinite(p):
        return "—"
    if p < 0.001:
        return "< " + ("0.001" if lead else ".001")
    if p > 0.999:
        return "> " + ("0.999" if lead else ".999")
    d = 4 if 0.0495 <= p < 0.05 else 3
    return bounded(p, d, lead)


def p_txt(p, lead: bool = False, sym: str = "p") -> str:
    """'p < .001' · 'p = .034'"""
    v = p_val(p, lead)
    return f"{sym} {v}" if v[:1] in "<>" else f"{sym} = {v}"


def df_str(df) -> str:
    """정수면 정수, 아니면 소수 한 자리(Welch df)."""
    if df is None:
        return "—"
    return str(int(round(df))) if abs(df - round(df)) < 1e-9 else f"{df:.1f}"


def ci(lo, hi, d: int = 2, minus: str = MINUS) -> str:
    return f"[{n(lo, d, minus)}, {n(hi, d, minus)}]"


def josa(word: str, pair: tuple[str, str]) -> str:
    """받침 있으면 pair[0](이·은·을·과), 없으면 pair[1](가·는·를·와). 한글이 아니면 끝 글자 소리를 어림한다."""
    w = (word or "").rstrip(" )")
    ch = w[-1:]
    if "가" <= ch <= "힣":
        return pair[0] if (ord(ch) - 0xAC00) % 28 else pair[1]
    return pair[0] if ch.lower() in "lmn0136789" else pair[1]


def w(word: str, kind: str) -> str:
    """단어 + 조사. kind: 이 | 은 | 을 | 과 | 로"""
    pairs = {"이": ("이", "가"), "은": ("은", "는"), "을": ("을", "를"), "과": ("과", "와"), "로": ("으로", "로")}
    if kind == "로":
        ch = (word or "")[-1:]
        if "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 not in (0, 8):
            return word + "으로"
        return word + "로"
    return word + josa(word, pairs[kind])


def mid_en(label: str) -> str:
    """영어 문장 가운데: 'Citric acid' → 'citric acid', 'HCl'은 그대로."""
    if not label or any(c.isupper() for c in label[1:].split(" ")[0]) or label.split(" ")[0].isupper():
        return label
    return label[0].lower() + label[1:]
