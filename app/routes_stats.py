"""통계 분석 API — /api/stats. 메인 앱이 app.include_router(routes_stats.router)로 붙인다.

데이터 고르기(실험·파일·예시) → 미리보기(정돈 표·코드북·결측) → 분석 실행(회귀·집단 비교·가정 점검·해석)
→ 내보내기(표 1·그림 1·가정 점검·재현 패키지·논문용 묶음). 모든 계산은 이 컴퓨터 안에서만 한다(밖으로 보내는 길 없음).
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .experiment import store
from .stats import analysis as A, data as D, export as E, report as R

router = APIRouter(prefix="/api/stats", tags=["통계 분석"])

MIME = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "html": "text/html; charset=utf-8",
        "csv": "text/csv; charset=utf-8", "tex": "application/x-tex; charset=utf-8", "md": "text/markdown; charset=utf-8",
        "png": "image/png", "svg": "image/svg+xml", "pdf": "application/pdf", "txt": "text/plain; charset=utf-8",
        "zip": "application/zip", "py": "text/x-python; charset=utf-8", "R": "text/plain; charset=utf-8", "do": "text/plain; charset=utf-8",
        "json": "application/json"}
FILES = ["table1.docx", "table1.html", "table1.csv", "table1.tex", "table1.md", "figure1.png", "figure1.svg", "figure1.pdf",
         "diagnostics.png", "diagnostics.svg", "diagnostics.pdf", "assumptions.docx", "assumptions.html", "caption.txt",
         "interpretation.txt", "methods.txt", "data.csv", "codebook.csv", "analysis.py", "analysis.R", "analysis.do",
         "reproduce.zip", "bundle.zip"]


class SourceIn(BaseModel):
    source: dict = {}


class RunIn(BaseModel):
    source: dict = {}
    spec: dict | None = None
    options: dict | None = None


class ExportIn(RunIn):
    lang: str = "ko"
    width: str = "double"
    zero: str | None = None


def _bad(ex: Exception):
    raise HTTPException(400, str(ex)) from ex


@router.get("/datasets")
def datasets():
    exps = [{"exp_id": e["exp_id"], "name": e["name"], "n_runs": e["n_runs"], "confidentiality": e["confidentiality"]}
            for e in store.list_experiments()]
    return {"experiments": exps,
            "demos": [{"levels": 2, "label": "예시: 사과박 펙틴 산 추출 — 구연산 vs 염산 (가짜 데이터)"},
                      {"levels": 3, "label": "예시: 사과박 펙틴 산 추출 — 구연산·염산·질산 (가짜 데이터)"}],
            "privacy": "모든 계산은 이 PC 안에서 합니다. 올린 파일은 메모리에만 1시간 두고, 자료함·받은편지함에 넣지 않습니다."}


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    try:
        content = await file.read(5 * 1024 * 1024 + 1)
        return D.upload(file.filename or "upload.csv", content)
    except D.DataError as ex:
        _bad(ex)


@router.post("/dataset/preview")
def dataset_preview(body: SourceIn):
    try:
        return E.json_safe(D.preview(D.load(body.source)))
    except D.DataError as ex:
        _bad(ex)


@router.post("/run")
def run(body: RunIn):
    try:
        r = A.run(body.source, body.spec, body.options)
    except (A.StatsError, D.DataError) as ex:
        _bad(ex)
    return E.json_safe(r.out)


@router.get("/results/{rid}")
def result(rid: str):
    try:
        return E.json_safe(A.get(rid).out)
    except A.StatsError as ex:
        raise HTTPException(404, str(ex)) from ex


def _file(r, name: str, lang: str, width: str, zero: str | None) -> tuple[bytes, str]:
    if lang not in ("ko", "en"):
        raise A.StatsError("언어는 ko 또는 en으로 고르세요.")
    if width not in ("single", "double"):
        raise A.StatsError("그림 폭은 single(85 mm) 또는 double(175 mm)로 고르세요.")
    if zero not in (None, "", "auto", "apa", "leading"):
        raise A.StatsError("숫자 앞 0 표기는 auto·apa·leading 중 하나로 고르세요.")
    zero = zero or None
    stem, _, ext = name.rpartition(".")
    if name not in FILES:
        raise A.StatsError(f"'{name}'는 내보낼 수 없는 파일입니다. {', '.join(FILES)} 중 하나를 고르세요.")
    try:
        if stem == "table1":
            data = {"docx": lambda: R.table1_docx(r, lang, zero), "html": lambda: R.table1_html(r, lang, zero, standalone=True).encode("utf-8"),
                    "csv": lambda: R.table1_csv(r, lang, zero).encode("utf-8"), "tex": lambda: R.table1_latex(r, lang, zero).encode("utf-8"),
                    "md": lambda: R.table1_markdown(r, lang, zero).encode("utf-8")}[ext]()
        elif stem == "figure1":
            data = R.figure1(r, lang, width, ext, zero)
        elif stem == "diagnostics":
            data = R.diagnostics(r, lang, ext)
        elif stem == "assumptions":
            data = R.assumptions_docx(r, lang) if ext == "docx" else R.assumptions_html(r, lang).encode("utf-8")
        elif name == "caption.txt":
            data = (R.caption(r, lang, zero) + "\n").encode("utf-8")
        elif name == "interpretation.txt":
            data = (" ".join(R.interpretation(r, lang, zero)) + "\n").encode("utf-8")
        elif name == "methods.txt":
            data = (r.out["methods"][lang] + "\n").encode("utf-8")
        elif name == "data.csv":
            data = E.data_csv(r)
        elif name == "codebook.csv":
            data = E.codebook_csv(r)
        elif name == "analysis.py":
            data = E.analysis_py(r).encode("utf-8")
        elif name == "analysis.R":
            data = E.analysis_r(r).encode("utf-8")
        elif name == "analysis.do":
            data = E.analysis_do(r).encode("utf-8")
        elif name == "reproduce.zip":
            data = E.reproduce_zip(r)
        else:
            data = E.bundle_zip(r, lang, width, zero)
    except ValueError as ex:  # 그릴 회귀·집단 비교가 없는 경우 등
        raise A.StatsError(str(ex)) from ex
    return data, MIME.get(ext, "application/octet-stream")


def _respond(r, name, lang, width, zero, download: bool):
    try:
        data, mime = _file(r, name, lang, width, zero)
    except A.StatsError as ex:
        _bad(ex)
    out_name = {"table1": "Table1", "figure1": "Figure1", "bundle": "논문용_묶음", "reproduce": "재현_패키지"}.get(name.rsplit(".", 1)[0], name.rsplit(".", 1)[0])
    out_name += "." + name.rsplit(".", 1)[1]
    disp = "attachment" if download else "inline"
    return Response(data, media_type=mime, headers={"Content-Disposition": f"{disp}; filename*=UTF-8''{quote(out_name)}",
                                                    "Cache-Control": "no-store"})


@router.get("/results/{rid}/files/{name}")
def result_file(rid: str, name: str, lang: str = "ko", width: str = "double", zero: str | None = None, download: bool = True):
    try:
        r = A.get(rid)
    except A.StatsError as ex:
        raise HTTPException(404, str(ex)) from ex
    return _respond(r, name, lang, width, zero, download)


@router.post("/export/{name}")
def export(name: str, body: ExportIn):
    """상태 없이 한 번에: 데이터·사양을 보내면 그 파일을 돌려준다."""
    try:
        r = A.run(body.source, body.spec, body.options)
    except (A.StatsError, D.DataError) as ex:
        _bad(ex)
    return _respond(r, name, body.lang, body.width, body.zero, True)
