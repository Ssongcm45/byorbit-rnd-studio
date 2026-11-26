"""성분의 분자 구조: 로컬 시드(SMILES) + RDKit 2D/3D, 없는 성분만 PubChem 보조(사용자가 누를 때만).

- 한글 표준명은 seed_data의 성분 개념과 같게 둔다(시소러스 동의어로 찾는다).
- 펙틴·셀룰로스·식이섬유·폴리페놀처럼 단일 분자가 아닌 것은 '대표 단위체/대표 화합물'로 잇고
  응답에 representative=True와 그 이유를 붙인다.
- 결과는 데이터 폴더 structures\\ 아래에 key.json / key.svg / key.sdf로 캐시한다.
- PubChem에는 영문 성분명 하나만 보낸다. 시료·공급처·로트 정보는 절대 넣지 않는다.
- RDKit은 함수 안에서만 import한다. 없으면 RDKitMissing을 던지고 API가 한글 안내를 돌려준다.
"""
from __future__ import annotations

import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .. import config

RDKIT_MISSING_MSG = ("분자 구조를 그리는 RDKit이 설치되어 있지 않습니다. install.bat를 다시 실행하거나 "
                     "가상환경에서 'pip install rdkit'를 실행한 뒤 앱을 다시 시작하세요.")

CLASS_KO = {
    "phenolic acid": "페놀산", "flavonol": "플라보놀", "flavonol glycoside": "플라보놀 배당체",
    "dihydrochalcone": "디하이드로칼콘", "flavan-3-ol": "플라반-3-올", "proanthocyanidin": "프로안토시아니딘",
    "flavanone glycoside": "플라바논 배당체", "anthocyanin": "안토시아닌", "hydrolysable tannin": "가수분해형 탄닌",
    "polymer unit": "고분자 단위체", "sugar": "당", "organic acid": "유기산", "terpene": "테르펜",
    "carotenoid": "카로티노이드", "alkaloid": "알칼로이드",
}


def _tannic_acid_smiles() -> str:
    """탄닌산(C76H52O46): 포도당 고리의 5개 OH에 디갈로일(m-digallate) 에스터가 붙은 대표 구조."""
    n = [10]

    def rn() -> str:
        n[0] += 1
        return f"%{n[0]}"

    def digalloyl() -> str:
        a, b = rn(), rn()
        return f"C(=O)c{a}cc(O)c(O)c(OC(=O)c{b}cc(O)c(O)c(O)c{b})c{a}"

    return (f"C(O{digalloyl()})[C@H]1O[C@@H](O{digalloyl()})[C@H](O{digalloyl()})"
            f"[C@@H](O{digalloyl()})[C@@H]1O{digalloyl()}")


# key: (한글 표준명, 영문명, 동의어, SMILES, 분류, 부산물 R&D와의 관련 한 줄)
SEED: dict[str, tuple] = {
    "chlorogenic-acid": ("클로로겐산", "Chlorogenic acid", ["chlorogenic acid", "5-CQA", "5-카페오일퀸산", "클로로젠산"],
                         "C1[C@H]([C@H]([C@@H](C[C@@]1(C(=O)O)O)OC(=O)/C=C/C2=CC(=C(C=C2)O)O)O)O",
                         "phenolic acid", "사과박·커피박의 주요 페놀산. 열풍건조 시 열·산화로 쉽게 줄어 건조 방식 비교의 지표가 된다."),
    "quercetin": ("퀘르세틴", "Quercetin", ["quercetin", "케르세틴", "쿼세틴"],
                  "C1=CC(=C(C=C1C2=C(C(=O)C3=C(C=C(C=C3O2)O)O)O)O)O",
                  "flavonol", "양파 껍질·사과 껍질에 많은 플라보놀. 항산화 소재 후보 성분."),
    "phloridzin": ("플로리진", "Phloridzin", ["phloridzin", "phlorizin", "플로리찐", "플로리진(phlorizin)"],
                   "C1=CC(=CC=C1CCC(=O)C2=C(C=C(C=C2O[C@H]3[C@@H]([C@H]([C@@H]([C@H](O3)CO)O)O)O)O)O)O",
                   "dihydrochalcone", "사과(특히 사과박·씨)에 특이적인 디하이드로칼콘. 사과 유래 원료의 지표 성분."),
    "catechin": ("카테킨", "Catechin", ["catechin", "(+)-catechin", "(+)-카테킨"],
                 "C1[C@@H]([C@H](OC2=CC(=CC(=C21)O)O)C3=CC(=C(C=C3)O)O)O",
                 "flavan-3-ol", "포도박·밤 껍질 등의 플라반-3-올 단위. 축합형 탄닌의 구성 단위."),
    "epicatechin": ("에피카테킨", "Epicatechin", ["epicatechin", "(-)-epicatechin", "(-)-에피카테킨"],
                    "C1[C@H]([C@H](OC2=CC(=CC(=C21)O)O)C3=CC(=C(C=C3)O)O)O",
                    "flavan-3-ol", "사과·포도 부산물의 주요 플라반-3-올. 프로시아니딘 B2의 단위체."),
    "procyanidin-b2": ("프로시아니딘 B2", "Procyanidin B2", ["procyanidin B2", "프로시아니딘B2", "procyanidin b-2"],
                       "C1[C@H]([C@H](OC2=C1C(=CC(=C2[C@@H]3[C@H]([C@H](OC4=CC(=CC(=C34)O)O)C5=CC(=C(C=C5)O)O)O)O)O)"
                       "C6=CC(=C(C=C6)O)O)O",
                       "proanthocyanidin", "에피카테킨 2량체. 사과박·포도박 폴리페놀의 상당 부분을 차지하는 축합형 탄닌 계열."),
    "hesperidin": ("헤스페리딘", "Hesperidin", ["hesperidin", "헤스페리딘(hesperidin)"],
                   "C[C@H]1[C@@H]([C@H]([C@H]([C@@H](O1)OC[C@@H]2[C@H]([C@@H]([C@H]([C@@H](O2)OC3=CC(=C4C(=O)C"
                   "[C@H](OC4=C3)C5=CC(=C(C=C5)OC)O)O)O)O)O)O)O)O",
                   "flavanone glycoside", "감귤박의 대표 플라바논 배당체. 감귤 부산물 고부가화의 핵심 지표."),
    "naringin": ("나린진", "Naringin", ["naringin", "나린긴"],
                 "C[C@H]1[C@@H]([C@H]([C@H]([C@@H](O1)O[C@@H]2[C@H]([C@@H]([C@H](O[C@H]2OC3=CC(=C4C(=O)C[C@H]"
                 "(OC4=C3)C5=CC=C(C=C5)O)O)CO)O)O)O)O)O",
                 "flavanone glycoside", "자몽·감귤 껍질의 쓴맛 플라바논 배당체. 감귤박 소재화 시 쓴맛 관리 대상."),
    "gallic-acid": ("갈산", "Gallic acid", ["gallic acid", "몰식자산", "GA"],
                    "C1=C(C=C(C(=C1O)O)O)C(=O)O",
                    "phenolic acid", "총폴리페놀(Folin-Ciocalteu) 정량의 기준 물질(mg GAE/g). 탄닌의 구성 단위."),
    "caffeic-acid": ("카페산", "Caffeic acid", ["caffeic acid", "카페인산", "커피산"],
                     "C1=CC(=C(C=C1/C=C/C(=O)O)O)O",
                     "phenolic acid", "클로로겐산이 가수분해되면 나오는 페놀산. 커피박·사과박 추출물에서 함께 검출된다."),
    "cyanidin-3-glucoside": ("시아니딘-3-글루코시드", "Cyanidin 3-glucoside",
                             ["cyanidin-3-glucoside", "cyanidin 3-O-glucoside", "C3G", "쿠로마닌", "kuromanin",
                              "시아니딘 3-글루코시드"],
                             "C1=CC(=C(C=C1C2=[O+]C3=CC(=CC(=C3C=C2O[C@H]4[C@@H]([C@H]([C@@H]([C@H](O4)CO)O)O)O)O)O)O)O",
                             "anthocyanin", "포도박·적채 등의 대표 안토시아닌(양이온 형태). 열·pH에 민감해 건조 조건에 따라 색이 변한다."),
    "rutin": ("루틴", "Rutin", ["rutin", "quercetin-3-rutinoside", "루테오사이드"],
              "C[C@H]1[C@@H]([C@H]([C@H]([C@@H](O1)OC[C@@H]2[C@H]([C@@H]([C@H]([C@@H](O2)OC3=C(OC4=CC(=CC(=C4C3=O)O)O)"
              "C5=CC(=C(C=C5)O)O)O)O)O)O)O)O",
              "flavonol glycoside", "퀘르세틴의 루티노스 배당체. 메밀·감귤·사과 부산물에 분포."),
    "tannic-acid": ("탄닌산", "Tannic acid", ["tannic acid", "타닌산", "gallotannin", "갈로탄닌"],
                    _tannic_acid_smiles(),
                    "hydrolysable tannin", "밤 껍질·수피 탄닌의 대표 화합물(가수분해형). 가죽 무두질·접착제·항균 용도."),
    "galacturonic-acid": ("갈락투론산", "D-Galacturonic acid",
                          ["galacturonic acid", "D-galacturonic acid", "갈락투론산(펙틴 단위체)", "GalA"],
                          "[C@@H]1([C@H]([C@@H](O[C@@H]([C@@H]1O)O)C(=O)O)O)O",
                          "polymer unit", "펙틴 주사슬의 단위체. 사과박·감귤박 펙틴 함량·품질 판단의 기준."),
    "cellobiose": ("셀로비오스", "Cellobiose", ["cellobiose", "셀로비오스(셀룰로스 단위체)", "D-cellobiose"],
                   "C([C@@H]1[C@H]([C@@H]([C@H]([C@@H](O1)O[C@@H]2[C@H](O[C@H]([C@@H]([C@H]2O)O)O)CO)O)O)O)O",
                   "polymer unit", "셀룰로스의 반복 단위(β-1,4 포도당 2량체). 불용성 식이섬유·바이오복합재 필러의 골격."),
    "glucose": ("포도당", "D-Glucose", ["glucose", "D-glucose", "덱스트로스", "dextrose", "글루코스"],
                "C([C@@H]1[C@H]([C@@H]([C@H]([C@@H](O1)O)O)O)O)O",
                "sugar", "과실 착즙박의 잔존 유리당. 열풍건조 시 마이야르 갈변의 반응물."),
    "fructose": ("과당", "D-Fructose", ["fructose", "D-fructose", "프럭토스", "프룩토스"],
                 "C([C@@H]1[C@H]([C@@H]([C@](O1)(CO)O)O)O)O",
                 "sugar", "사과·배 착즙박에 많은 환원당. 건조 중 갈변과 흡습(끈적임)의 원인."),
    "sucrose": ("자당", "Sucrose", ["sucrose", "설탕", "수크로스", "슈크로스"],
                "C([C@@H]1[C@H]([C@@H]([C@H]([C@H](O1)O[C@]2([C@H]([C@@H]([C@H](O2)CO)O)O)CO)O)O)O)O",
                "sugar", "비환원당. 분무건조 시 유리전이온도가 낮아 벽면 부착의 원인이 된다."),
    "malic-acid": ("말산", "Malic acid", ["malic acid", "L-malic acid", "사과산"],
                   "C([C@@H](C(=O)O)O)C(=O)O",
                   "organic acid", "사과박의 주요 유기산. pH·신맛과 펙틴 겔화 조건에 영향."),
    "citric-acid": ("시트르산", "Citric acid", ["citric acid", "구연산"],
                    "C(C(=O)O)C(CC(=O)O)(C(=O)O)O",
                    "organic acid", "감귤박의 주요 유기산. 펙틴 추출 시 산 용매로도 쓰인다."),
    "ascorbic-acid": ("아스코르브산", "Ascorbic acid", ["ascorbic acid", "L-ascorbic acid", "비타민 C", "vitamin C", "비타민C"],
                      "C([C@@H]([C@@H]1C(=C(C(=O)O1)O)O)O)O",
                      "organic acid", "열·산소에 매우 약해 건조 방식별 열 손상 정도를 가늠하는 지표."),
    "limonene": ("리모넨", "Limonene", ["limonene", "D-limonene", "(R)-limonene", "d-리모넨"],
                 "CC1=CC[C@@H](CC1)C(=C)C",
                 "terpene", "감귤박 정유의 주성분(휘발성). 건조 중 손실되며 회수 시 향료·세정 용도."),
    "beta-carotene": ("베타카로틴", "beta-Carotene", ["beta-carotene", "β-carotene", "β-카로틴", "베타-카로틴"],
                      "CC1=C(C(CCC1)(C)C)/C=C/C(=C/C=C/C(=C/C=C/C=C(\\C)/C=C/C=C(\\C)/C=C/C2=C(CCCC2(C)C)C)/C)/C",
                      "carotenoid", "당근·감귤 부산물의 색소. 빛·산소·열에 산화되어 건조 후 퇴색의 원인."),
    "caffeine": ("카페인", "Caffeine", ["caffeine", "1,3,7-trimethylxanthine"],
                 "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
                 "alkaloid", "커피박에 남는 알칼로이드. 사료·퇴비 활용 시 잔류량 관리 대상."),
}

# 단일 분자가 아닌 성분 → 대표 단위체/대표 화합물
REPRESENTATIVE: dict[str, tuple] = {
    # 표기들: (대상 key, 개념 한글명, 설명)
    "펙틴": ("galacturonic-acid", "펙틴",
             "펙틴은 갈락투론산이 길게 이어진 다당류라 단일 분자 구조가 없습니다. 주사슬 단위체인 갈락투론산을 대표로 보여줍니다."),
    "셀룰로스": ("cellobiose", "셀룰로스",
                 "셀룰로스는 포도당이 β-1,4로 수천 개 이어진 고분자입니다. 반복 단위인 셀로비오스를 대표로 보여줍니다."),
    "식이섬유": ("cellobiose", "식이섬유",
                 "식이섬유는 셀룰로스·헤미셀룰로스·펙틴·리그닌 등의 혼합물입니다. 가장 흔한 불용성 섬유인 셀룰로스의 "
                 "반복 단위(셀로비오스)를 대표로 보여줍니다. 펙틴(수용성)은 갈락투론산을 보세요."),
    "폴리페놀": ("gallic-acid", "폴리페놀",
                 "폴리페놀(총폴리페놀, TPC)은 수많은 페놀 화합물의 합계입니다. Folin-Ciocalteu 정량의 기준 물질인 "
                 "갈산(mg GAE/g의 GA)을 대표로 보여줍니다."),
    "안토시아닌": ("cyanidin-3-glucoside", "안토시아닌",
                   "안토시아닌은 색소 계열 전체를 가리킵니다. 가장 흔한 시아니딘-3-글루코시드를 대표로 보여줍니다."),
    "탄닌": ("tannic-acid", "탄닌",
             "탄닌은 가수분해형·축합형을 아우르는 계열 이름입니다. 가수분해형의 대표 화합물인 탄닌산을 보여줍니다. "
             "축합형(포도박·사과박)은 프로시아니딘 B2를 보세요."),
}
REP_SYNONYMS = {
    "펙틴": ["pectin", "펙틴질"],
    "셀룰로스": ["cellulose", "셀룰로오스", "섬유소"],
    "식이섬유": ["dietary fiber", "dietary fibre", "tdf", "총식이섬유", "총 식이섬유", "불용성 식이섬유", "idf"],
    "폴리페놀": ["polyphenol", "polyphenols", "총폴리페놀", "총 폴리페놀", "총페놀", "총 페놀", "tpc",
                 "total phenolic content", "total phenolics", "페놀 화합물"],
    "안토시아닌": ["anthocyanin", "anthocyanins", "총안토시아닌"],
    "탄닌": ["tannin", "tannins", "타닌", "총탄닌"],
}

_lock = threading.RLock()
_svg_mem: dict[str, str] = {}


class RDKitMissing(RuntimeError):
    pass


class NotFound(LookupError):
    pass


class FetchError(RuntimeError):
    pass


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _compact(s: str) -> str:
    return re.sub(r"[\s\-_·()]+", "", _norm(s))


def slug(s: str) -> str:
    s = re.sub(r"[^0-9a-z]+", "-", str(s).lower()).strip("-")
    return s[:80] or "compound"


def rdkit_available() -> bool:
    try:
        import rdkit  # noqa: F401
        return True
    except ImportError:
        return False


def _rd():
    try:
        from rdkit import Chem, RDLogger
        RDLogger.DisableLog("rdApp.*")
        return Chem
    except ImportError as e:  # pragma: no cover - 설치 환경에 따라
        raise RDKitMissing(RDKIT_MISSING_MSG) from e


# ---------------------------------------------------------------- 캐시

def cache_dir() -> Path:
    d = config.path("structures")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _cached_entries() -> dict[str, dict]:
    out = {}
    d = config.path("structures")
    if not d.exists():
        return out
    for f in d.glob("*.json"):
        try:
            e = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(e, dict) and e.get("key") and e.get("smiles"):
            out[e["key"]] = e
    return out


def _seed_entry(key: str) -> dict:
    ko, en, syn, smi, cls, note = SEED[key]
    return {"key": key, "ko": ko, "en": en, "synonyms": list(syn), "smiles": smi, "class": cls,
            "class_ko": CLASS_KO.get(cls, cls), "note": note, "source": "로컬 시드"}


def entry(key: str) -> dict | None:
    if key in SEED:
        return _seed_entry(key)
    return _cached_entries().get(key)


def all_entries() -> list[dict]:
    out = [_seed_entry(k) for k in SEED]
    seen = set(SEED)
    for k, e in sorted(_cached_entries().items()):
        if k not in seen:
            out.append(e)
    return out


# ---------------------------------------------------------------- 찾기

def _index() -> dict[str, str]:
    idx: dict[str, str] = {}
    for e in all_entries():
        for s in [e["ko"], e.get("en") or "", e["key"], *e.get("synonyms", [])]:
            if s:
                idx.setdefault(_norm(s), e["key"])
                idx.setdefault(_compact(s), e["key"])
    return idx


def _rep_index() -> dict[str, str]:
    idx = {}
    for ko, syns in REP_SYNONYMS.items():
        for s in [ko, *syns]:
            idx[_norm(s)] = ko
            idx[_compact(s)] = ko
    return idx


def _expand(term: str) -> list[str]:
    """시소러스(DB)로 동의어를 넓힌다. DB가 없거나 비어 있어도 원래 말은 남긴다."""
    try:
        from .. import thesaurus
        return thesaurus.expand(term)
    except Exception:  # noqa: BLE001 - DB 없음 등
        return [term]


def _match(terms: list[str]) -> tuple[str, str] | None:
    """('key', key) 또는 ('rep', 개념명)"""
    idx, rep = _index(), _rep_index()
    for t in terms:
        for k in (_norm(t), _compact(t)):
            if k in idx:
                return ("key", idx[k])
    for t in terms:
        for k in (_norm(t), _compact(t)):
            if k in rep:
                return ("rep", rep[k])
    return None


def resolve(term: str) -> dict | None:
    """용어 → 구조 항목. 시드 이름·동의어 → 시소러스 동의어 → 캐시(PubChem) 순서.
    단일 분자가 아니면 대표 단위체로 잇고 representative=True와 설명을 붙인다. 없으면 None."""
    term = (term or "").strip()
    if not term:
        return None
    hit = _match([term]) or _match(_expand(term))
    if not hit:
        return None
    kind, val = hit
    if kind == "key":
        e = entry(val)
        return {**e, "representative": False, "query": term} if e else None
    key, concept, why = REPRESENTATIVE[val]
    e = entry(key)
    return {**e, "representative": True, "represents": concept, "representative_note": why, "query": term}


def suggestions(term: str, limit: int = 8) -> list[dict]:
    """부분 일치 후보(검색 상자 자동 완성용)."""
    k = _norm(term)
    if not k:
        return []
    out = []
    for e in all_entries():
        names = [e["ko"], e.get("en") or "", *e.get("synonyms", [])]
        if any(k in _norm(n) for n in names if n):
            out.append({"key": e["key"], "ko": e["ko"], "en": e.get("en")})
        if len(out) >= limit:
            break
    for ko, syns in REP_SYNONYMS.items():
        if len(out) >= limit:
            break
        if any(k in _norm(s) for s in [ko, *syns]):
            out.append({"key": REPRESENTATIVE[ko][0], "ko": ko, "en": None, "representative": True})
    return out


# ---------------------------------------------------------------- RDKit: 성질·2D·3D

def _mol(e: dict):
    Chem = _rd()
    m = Chem.MolFromSmiles(e["smiles"])
    if m is None:
        raise ValueError(f"'{e['ko']}'의 SMILES를 해석하지 못했습니다.")
    return m


def properties(e: dict) -> dict:
    _rd()
    from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors
    m = _mol(e)
    return {
        "formula": rdMolDescriptors.CalcMolFormula(m),
        "mw": round(Descriptors.MolWt(m), 2),
        "exact_mass": round(Descriptors.ExactMolWt(m), 4),
        "logp": round(Crippen.MolLogP(m), 2),
        "hbd": Lipinski.NumHDonors(m),
        "hba": Lipinski.NumHAcceptors(m),
        "tpsa": round(rdMolDescriptors.CalcTPSA(m), 1),
        "rotatable_bonds": rdMolDescriptors.CalcNumRotatableBonds(m),
        "heavy_atoms": m.GetNumHeavyAtoms(),
        "charge": sum(a.GetFormalCharge() for a in m.GetAtoms()),
    }


# 밝은·어두운 화면 모두에서 읽히는 중간 톤 원소 색. 탄소·수소(검정)는 currentColor로 바꿔 CSS를 따른다.
_PALETTE = {8: (0.85, 0.27, 0.22), 7: (0.27, 0.47, 0.88), 16: (0.83, 0.62, 0.08), 15: (0.9, 0.5, 0.1),
            17: (0.2, 0.65, 0.3), 9: (0.2, 0.65, 0.3), 35: (0.6, 0.25, 0.15)}


def svg(e: dict, width: int = 460, height: int = 340) -> str:
    """투명 배경 2D 구조 SVG. 캐시: key.svg"""
    key = e["key"]
    f = cache_dir() / f"{key}.svg"
    if key in _svg_mem:
        return _svg_mem[key]
    if f.exists():
        _svg_mem[key] = f.read_text(encoding="utf-8")
        return _svg_mem[key]
    _rd()
    from rdkit.Chem import rdDepictor
    from rdkit.Chem.Draw import rdMolDraw2D
    m = _mol(e)
    rdDepictor.SetPreferCoordGen(True)
    rdDepictor.Compute2DCoords(m)
    heavy = m.GetNumHeavyAtoms()
    if heavy > 70:
        width, height = 640, 520
    d = rdMolDraw2D.MolDraw2DSVG(width, height)
    o = d.drawOptions()
    o.clearBackground = False
    o.addStereoAnnotation = False
    o.bondLineWidth = 2 if heavy <= 70 else 1
    o.minFontSize = 13 if heavy <= 70 else 10
    o.padding = 0.06
    o.updateAtomPalette(_PALETTE)
    rdMolDraw2D.PrepareAndDrawMolecule(d, m)
    d.FinishDrawing()
    s = d.GetDrawingText()
    s = re.sub(r"<\?xml[^>]*\?>\s*", "", s)
    s = s.replace("#000000", "currentColor").replace("#000", "currentColor")
    s = re.sub(r"<svg ", f'<svg role="img" aria-label="{html.escape(e["ko"])} 2D 구조식" class="mol2d" ', s, count=1)
    s = re.sub(r"width='\d+px' height='\d+px'", f"width='100%' style='max-height:{height}px'", s, count=1)
    with _lock:
        _write(f, s)
        _svg_mem[key] = s
    return s


def _embed(m, max_attempts: int):
    from rdkit.Chem import AllChem
    p = AllChem.ETKDGv3()
    p.randomSeed = 0xB0B17
    p.maxIterations = max_attempts  # 실패 시 재시도 상한
    if m.GetNumHeavyAtoms() > 60:
        p.useRandomCoords = True     # 큰 분자는 무작위 좌표에서 시작하는 편이 빠르고 잘 된다
    cid = AllChem.EmbedMolecule(m, p)
    return cid


def sdf(e: dict, time_budget_s: float = 25.0) -> dict:
    """3D 좌표(ETKDGv3 + MMFF). 캐시: key.sdf. 실패하면 {'ok': False, 'message'} — 2D만 보여준다."""
    key = e["key"]
    f = cache_dir() / f"{key}.sdf"
    fail = cache_dir() / f"{key}.3dfail"
    if f.exists():
        return {"ok": True, "sdf": f.read_text(encoding="utf-8"), "cached": True}
    if fail.exists():
        return {"ok": False, "message": fail.read_text(encoding="utf-8")}
    Chem = _rd()
    from rdkit.Chem import AllChem
    m = Chem.AddHs(_mol(e))
    t0 = time.time()
    heavy = m.GetNumHeavyAtoms()
    cid = -1
    for attempt, n in enumerate((0 if heavy <= 60 else 200, 1000)):
        cid = _embed(m, n)
        if cid >= 0 or time.time() - t0 > time_budget_s:
            break
    if cid < 0:
        msg = (f"'{e['ko']}'은(는) 분자가 커서(무거운 원자 {heavy}개) 3D 좌표를 제한 시간 안에 만들지 못했습니다. "
               "2D 구조식을 보세요.")
        _write(fail, msg)
        return {"ok": False, "message": msg}
    opt = "MMFF94"
    try:
        if AllChem.MMFFHasAllMoleculeParams(m):
            iters = 2000 if heavy <= 60 else 600
            AllChem.MMFFOptimizeMolecule(m, maxIters=iters)
        else:
            AllChem.UFFOptimizeMolecule(m, maxIters=1000)
            opt = "UFF"
    except Exception:  # noqa: BLE001 - 최적화 실패해도 ETKDG 좌표는 쓸 만하다
        opt = "ETKDG(최적화 생략)"
    m.SetProp("_Name", e.get("en") or e["key"])
    m.SetProp("BYORBIT_KO", e["ko"])
    m.SetProp("BYORBIT_METHOD", f"ETKDGv3 + {opt}")
    block = Chem.MolToMolBlock(m) + "".join(f">  <{k}>\n{m.GetProp(k)}\n\n" for k in ("BYORBIT_KO", "BYORBIT_METHOD")) + "$$$$\n"
    with _lock:
        _write(f, block)
    return {"ok": True, "sdf": block, "cached": False, "method": f"ETKDGv3 + {opt}",
            "seconds": round(time.time() - t0, 2)}


def three_d_status(key: str) -> str:
    d = config.path("structures")
    if (d / f"{key}.sdf").exists():
        return "ready"
    if (d / f"{key}.3dfail").exists():
        return "failed"
    return "not_generated"


def detail(key: str) -> dict:
    e = entry(key)
    if not e:
        raise NotFound(key)
    out = {**e, "rdkit": rdkit_available(), "three_d": three_d_status(key)}
    if out["rdkit"]:
        out["props"] = properties(e)
    else:
        out["props"] = None
        out["message"] = RDKIT_MISSING_MSG
    return out


def listing() -> dict:
    items = []
    for e in all_entries():
        items.append({"key": e["key"], "ko": e["ko"], "en": e.get("en"), "class": e.get("class"),
                      "class_ko": e.get("class_ko"), "source": e.get("source"),
                      "three_d": three_d_status(e["key"])})
    reps = [{"term": ko, "key": v[0], "note": v[2]} for ko, v in REPRESENTATIVE.items()]
    return {"items": items, "representatives": reps, "rdkit": rdkit_available(),
            "message": None if rdkit_available() else RDKIT_MISSING_MSG}


# ---------------------------------------------------------------- PubChem (사용자가 누를 때만)

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{}/property/{}/JSON"
_PROPS = "IsomericSMILES,CanonicalSMILES,IUPACName,MolecularFormula"
_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,'()\[\]\-+.αβγ]{1,99}$")


def english_name(term: str) -> str | None:
    """한글 용어 → 영문 표준명(시드 → 개념 DB의 pref_label_en). 이미 영문이면 그대로."""
    term = (term or "").strip()
    if _NAME_OK.match(term):
        return term
    e = resolve(term)
    if e and e.get("en") and not e.get("representative"):
        return e["en"]
    try:
        from .. import thesaurus, db
        for h in thesaurus.lookup(term):
            if not h.get("exact"):
                continue
            r = db.one("SELECT pref_label_en FROM concept WHERE concept_id=?", (h["concept_id"],))
            if r and r["pref_label_en"] and _NAME_OK.match(r["pref_label_en"]):
                return r["pref_label_en"]
    except Exception:  # noqa: BLE001
        pass
    return None


def fetch_pubchem(name_en: str | None = None, term: str | None = None, urlopen=None) -> dict:
    """PubChem PUG REST에서 성분명 하나로 구조를 받아 캐시에 저장한다. 성분명 외에는 아무것도 보내지 않는다."""
    name = (name_en or "").strip() or None
    if not name and term:
        found = resolve(term)
        if found:
            return {**found, "already": True, "message": f"'{found['ko']}'은(는) 이미 로컬에 있습니다. PubChem에 묻지 않았습니다."}
        name = english_name(term)
        if not name:
            raise FetchError(f"'{term}'의 영문 표준명을 모릅니다. PubChem에는 영문 성분명만 보낼 수 있으니 "
                             "영문명(예: chlorogenic acid)을 넣어 다시 시도하세요.")
    if not name:
        raise FetchError("가져올 성분의 영문명을 넣으세요. 예: ferulic acid")
    if not _NAME_OK.match(name):
        raise FetchError(f"'{name}'은(는) 성분명으로 쓸 수 없는 글자가 있습니다. 영문·숫자·괄호·하이픈만 넣으세요.")
    existing = resolve(name)
    if existing:
        return {**existing, "already": True, "message": f"'{existing['ko']}'은(는) 이미 로컬에 있습니다. PubChem에 묻지 않았습니다."}
    url = PUBCHEM.format(urllib.parse.quote(name, safe=""), _PROPS)
    req = urllib.request.Request(url, headers={"User-Agent": "RD-Studio/0.5 (local research tool)", "Accept": "application/json"})
    opener = urlopen or urllib.request.urlopen
    try:
        with opener(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        if ex.code == 404:
            raise FetchError(f"PubChem에서 '{name}'을(를) 찾지 못했습니다. 철자나 다른 영문명(IUPAC명·일반명)으로 다시 시도하세요.") from ex
        raise FetchError(f"PubChem 응답 오류({ex.code}). 잠시 후 다시 시도하세요.") from ex
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        raise FetchError("PubChem에 연결하지 못했습니다(10초 제한). 인터넷 연결을 확인하거나 나중에 다시 시도하세요.") from ex
    except (json.JSONDecodeError, UnicodeDecodeError) as ex:
        raise FetchError("PubChem 응답을 읽지 못했습니다. 잠시 후 다시 시도하세요.") from ex
    props = ((data or {}).get("PropertyTable") or {}).get("Properties") or []
    if not props:
        raise FetchError(f"PubChem에서 '{name}'의 구조를 받지 못했습니다. 다른 영문명으로 다시 시도하세요.")
    p = props[0]
    smi = p.get("IsomericSMILES") or p.get("SMILES") or p.get("CanonicalSMILES") or p.get("ConnectivitySMILES")
    if not smi:
        raise FetchError(f"PubChem 결과에 '{name}'의 SMILES가 없습니다.")
    cid = p.get("CID")
    key = slug(name)
    if key in SEED:
        key = f"pubchem-{key}"
    e = {"key": key, "ko": (term if term and not _NAME_OK.match(term) else name), "en": name,
         "synonyms": [s for s in {name, term or ""} if s], "smiles": smi, "class": None, "class_ko": "PubChem",
         "note": f"PubChem에서 가져온 구조입니다(IUPAC: {p.get('IUPACName') or '-'}). 대표 구조가 맞는지 확인하세요.",
         "source": f"PubChem CID {cid}", "cid": cid, "iupac": p.get("IUPACName"),
         "formula_pubchem": p.get("MolecularFormula"), "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if rdkit_available():
        Chem = _rd()
        if Chem.MolFromSmiles(smi) is None:
            raise FetchError(f"PubChem이 준 '{name}'의 구조를 RDKit이 해석하지 못했습니다.")
    with _lock:
        _write(cache_dir() / f"{key}.json", json.dumps(e, ensure_ascii=False, indent=2))
    return {**e, "representative": False, "already": False,
            "message": f"PubChem CID {cid}에서 구조를 받아 저장했습니다. 다음부터는 이 PC에서 바로 보여줍니다."}
