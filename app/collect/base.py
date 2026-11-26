"""자료 수집 공통 계약 — 모든 출처(공식 API·크롤러)가 이 형식을 따른다.

출처 모듈은 app/collect/sources/<key>.py 에 두고, 모듈 전역 SOURCE = <Source 하위 클래스 인스턴스>를 둔다.
registry가 이 폴더를 자동으로 훑어 등록하므로 다른 파일을 고칠 필요가 없다.

원칙
- 밖으로 나가는 것은 검색어(와 그 출처가 요구하는 API 키)뿐이다. 기밀 자료·CoA·시료 정보는 절대 보내지 않는다.
- API 키는 os.environ으로만 읽는다(needs_env). 값은 실제 환경 변수 또는 설정 → API 키 관리(OS 자격 증명 저장소,
  app/keys.py가 앱 시작 때 os.environ에 올림)에서 온다. 설정 파일·DB·로그에 키를 쓰지 않는다.
- 원문 PDF는 오픈 액세스(합법적으로 무료 공개된 것)만 pdf_url로 넘긴다. 유료 원문을 우회해 받지 않는다.
"""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass, field

DOC_TYPES = ("article", "report", "patent", "project", "dataset", "thesis", "web", "other")


@dataclass
class Item:
    """정규화된 수집 결과 한 건."""
    source: str                     # 출처 key (예: "openalex")
    source_id: str                  # 그 출처 안의 고유 ID
    title: str
    doi: str | None = None          # 소문자, "10." 으로 시작(https://doi.org/ 제거)
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None        # 학술지·발행기관·특허청 등
    abstract: str | None = None
    url: str | None = None          # 사람이 볼 랜딩 페이지
    pdf_url: str | None = None      # 오픈 액세스 원문 PDF(있을 때만)
    oa: bool | None = None          # 오픈 액세스 여부(모르면 None)
    language: str | None = None
    doc_type: str = "article"       # DOC_TYPES 중 하나
    license: str | None = None
    extra: dict = field(default_factory=dict)   # 출처별 추가 필드(과제번호, 출원번호 등)

    def normalized(self) -> "Item":
        self.doi = norm_doi(self.doi)
        self.title = clean_text(self.title) or "(제목 없음)"
        self.abstract = clean_text(self.abstract) if self.abstract else None
        if self.doc_type not in DOC_TYPES:
            self.doc_type = "other"
        if self.year is not None:
            try:
                self.year = int(str(self.year)[:4])
            except ValueError:
                self.year = None
        return self

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


class Source:
    """출처 기본형. 하위 클래스는 key·name·kind 등을 정하고 search()를 구현한다."""
    key: str = ""
    name: str = ""
    kind: str = "api"               # "api" | "crawler"
    group: str = ""                 # 화면 묶음: "해외 학술" | "국내 학술" | "국가 R&D·특허" | "공공데이터" | "크롤러"
    homepage: str = ""
    terms_url: str = ""             # 이용약관·API 정책
    needs_env: tuple[str, ...] = () # 필요한 API 키 환경 변수 이름
    key_help: str = ""              # 키 발급 안내(어디서·어떻게)
    optional_env: tuple[str, ...] = ()  # 없어도 되지만 넣으면 한도가 늘어나는 키(설정 → API 키 관리에 '선택'으로 보인다)
    optional_key_help: str = ""
    env_labels: dict = {}           # 키가 여럿일 때 화면 이름(예: ScienceON client_id·인증키·MAC)
    doc_types: tuple[str, ...] = ("article",)

    def status(self) -> dict:
        missing = [e for e in self.needs_env if not os.environ.get(e)]
        if missing:
            return {"ready": False, "missing_env": missing,
                    "message": f"API 키가 필요합니다: 설정 → API 키 관리에서 {', '.join(missing)}를 넣으세요"
                               f"(또는 같은 이름의 환경 변수). {self.key_help}".strip()}
        return {"ready": True, "missing_env": [], "message": "사용 가능"}

    def env(self, name: str) -> str:
        v = os.environ.get(name, "")
        if not v:
            raise MissingKey(f"{self.name}: 키 {name}가 없습니다. 설정 → API 키 관리에서 넣으세요. {self.key_help}".strip())
        return v

    def reset(self) -> None:
        """키가 바뀌면 부른다(메모리에 둔 토큰 등을 버린다). 기본은 할 일 없음."""

    def search(self, query: str, *, limit: int = 25, since_year: int | None = None) -> list[Item]:
        raise NotImplementedError

    def info(self) -> dict:
        return {"key": self.key, "name": self.name, "kind": self.kind, "group": self.group,
                "homepage": self.homepage, "terms_url": self.terms_url, "needs_env": list(self.needs_env),
                "key_help": self.key_help, "doc_types": list(self.doc_types), **self.status()}


class MissingKey(Exception):
    pass


class SourceError(Exception):
    """출처 호출 실패. 메시지는 사용자에게 그대로 보여 줄 한국어(무엇을 하면 되는지 포함)."""


# ---------------------------------------------------------------- 정규화 도우미

_DOI = re.compile(r"10\.\d{4,9}/\S+", re.I)


def norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    m = _DOI.search(str(doi).strip())
    return m.group(0).rstrip(".,;)").lower() if m else None


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", str(s))           # JATS·HTML 태그
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", s).strip()


def title_key(title: str) -> str:
    """중복 판정용 제목 열쇠: 소문자·기호 제거·공백 제거 후 해시."""
    t = unicodedata.normalize("NFKC", title or "").lower()
    t = re.sub(r"[^0-9a-z가-힣]+", "", t)
    return hashlib.sha1(t.encode("utf-8")).hexdigest()[:20]
