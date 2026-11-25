"""로컬 OCR(RapidOCR, 선택 설치) 시험.

(a) OCR 엔진을 모킹해 — 실제 설치 없이 — 스캔 PDF 쪽 처리, 이미지 처리, 표 복원, 신뢰도 거르기,
    미설치 시 안내 메시지를 확인한다.
(b) 진짜 설치돼 있으면(= rapidocr를 import 할 수 있으면) 실제 엔진으로 한국어+숫자 인식을 확인한다.
    미설치 환경(다른 묶음 작업자 등)에서는 건너뛴다.
"""
from __future__ import annotations

import importlib.util

import pytest

from app.ingest import parsers


# ---------------------------------------------------------------- 공통 도우미

def _box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _line(text, box, score=0.95):
    return {"text": text, "box": box, "score": score}


class _FakeOcrResult:
    def __init__(self, txts, boxes, scores):
        self.txts, self.boxes, self.scores = txts, boxes, scores


# ---------------------------------------------------------------- (a) 모킹: PDF 스캔 쪽

def test_pdf_scanned_page_ocr(tmp_path, monkeypatch):
    import pymupdf

    monkeypatch.setattr(parsers, "ocr_available", lambda: True)
    canned = [
        _line("총식이섬유 52.6 g/100g", _box(10, 10, 300, 40), 0.98),
        _line("동결건조 사과박 시료입니다.", _box(10, 50, 300, 80), 0.9),
    ]
    monkeypatch.setattr(parsers, "_ocr_lines", lambda image: canned)

    doc = pymupdf.open()
    doc.new_page()  # 글자 없는 쪽 → 스캔본으로 판정되어 OCR 대상이 된다
    f = tmp_path / "스캔본.pdf"
    doc.save(str(f))
    doc.close()

    out = parsers.parse_pdf(f)
    texts = [b["text"] for b in out["blocks"] if b["type"] == "text"]
    assert any("총식이섬유" in t for t in texts)
    assert all(b.get("page") == 1 for b in out["blocks"])
    assert out["meta"]["ocr_pages"] == [1]
    assert out["meta"]["needs_ocr"] is False  # OCR로 채웠으니 "OCR 필요" 안내는 안 뜬다
    assert out["meta"]["ocr_mean_conf"] == pytest.approx((0.98 + 0.9) / 2, abs=1e-4)


def test_pdf_scanned_page_without_ocr_keeps_needs_ocr(tmp_path, monkeypatch):
    import pymupdf

    monkeypatch.setattr(parsers, "ocr_available", lambda: False)
    called = {"n": 0}
    monkeypatch.setattr(parsers, "_ocr_lines", lambda image: called.__setitem__("n", called["n"] + 1) or [])

    doc = pymupdf.open()
    doc.new_page()
    f = tmp_path / "스캔본2.pdf"
    doc.save(str(f))
    doc.close()

    out = parsers.parse_pdf(f)
    assert out["meta"]["needs_ocr"] is True        # OCR 미설치 — 기존 "OCR 필요" 안내 유지
    assert "ocr_pages" not in out["meta"]
    assert called["n"] == 0                        # OCR 미설치면 엔진을 부르지 않는다


# ---------------------------------------------------------------- (a) 모킹: 이미지 → 블록

def test_image_to_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(parsers, "ocr_available", lambda: True)
    canned = [
        _line("사과박 CoA 요약", _box(10, 10, 200, 40), 0.97),
        _line("수분 함량이 낮습니다.", _box(10, 60, 220, 90), 0.93),
    ]
    monkeypatch.setattr(parsers, "_ocr_lines", lambda image: canned)

    f = tmp_path / "메모사진.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    out = parsers.parse_image(f)

    joined = " ".join(b.get("text", "") for b in out["blocks"])
    assert "사과박" in joined and "수분" in joined
    assert out["meta"]["ocr"] is True
    assert out["meta"]["ocr_lines"] == 2
    assert out["meta"]["ocr_mean_conf"] == pytest.approx((0.97 + 0.93) / 2, abs=1e-4)


# ---------------------------------------------------------------- (a) 모킹: 표 복원

def test_image_table_reconstruction(tmp_path, monkeypatch):
    """CoA 사진처럼 2열(항목·값)로 줄맞춰진 OCR 상자는 표로 묶인다."""
    monkeypatch.setattr(parsers, "ocr_available", lambda: True)
    canned = [
        _line("시험항목", _box(10, 10, 90, 30)),
        _line("결과", _box(200, 10, 260, 30)),
        _line("총식이섬유", _box(10, 50, 90, 70)),
        _line("52.6 g/100g", _box(200, 50, 280, 70)),
        _line("납", _box(10, 90, 90, 110)),
        _line("불검출", _box(200, 90, 280, 110)),
    ]
    monkeypatch.setattr(parsers, "_ocr_lines", lambda image: canned)

    f = tmp_path / "coa사진.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0fake")
    out = parsers.parse_image(f)

    assert len(out["blocks"]) == 1
    tbl = out["blocks"][0]
    assert tbl["type"] == "table"
    assert tbl["rows"] == [
        ["시험항목", "결과"],
        ["총식이섬유", "52.6 g/100g"],
        ["납", "불검출"],
    ]
    assert "총식이섬유" in tbl["text"] and "52.6 g/100g" in tbl["text"]


def test_single_column_lines_are_not_a_table(tmp_path, monkeypatch):
    """한 열로만 늘어선 글자는 표가 아니라 단락으로 묶인다."""
    monkeypatch.setattr(parsers, "ocr_available", lambda: True)
    canned = [
        _line("요약 메모", _box(10, 10, 150, 30)),
        _line("사과박 수분 함량 재측정 필요", _box(10, 36, 250, 56)),
    ]
    monkeypatch.setattr(parsers, "_ocr_lines", lambda image: canned)

    f = tmp_path / "메모.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    out = parsers.parse_image(f)
    assert all(b["type"] == "text" for b in out["blocks"])
    assert any("재측정" in b["text"] for b in out["blocks"])


# ---------------------------------------------------------------- (a) 모킹: 미설치 안내

def test_image_unsupported_without_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr(parsers, "ocr_available", lambda: False)
    f = tmp_path / "사진.jpeg"
    f.write_bytes(b"\xff\xd8\xff\xe0fake")
    with pytest.raises(parsers.UnsupportedFile) as exc:
        parsers.parse(f)
    assert "install-ocr.bat" in str(exc.value)


def test_image_extensions_are_supported():
    assert {".png", ".jpg", ".jpeg", ".tif", ".tiff"} <= parsers.SUPPORTED


# ---------------------------------------------------------------- (a) 모킹: 신뢰도 거르기

def test_ocr_lines_drops_low_confidence(monkeypatch):
    fake_result = _FakeOcrResult(
        txts=["좋은 인식", "나쁜 인식"],
        boxes=[_box(0, 0, 100, 20), _box(0, 30, 100, 50)],
        scores=[0.95, 0.2],
    )
    monkeypatch.setattr(parsers, "_get_ocr_engine", lambda: (lambda image: fake_result))
    lines = parsers._ocr_lines("dummy")
    assert len(lines) == 1
    assert lines[0]["text"] == "좋은 인식"
    assert lines[0]["score"] == pytest.approx(0.95)


# ---------------------------------------------------------------- (b) 실제 설치: 한국어 + 숫자 인식

_HAS_RAPIDOCR = importlib.util.find_spec("rapidocr") is not None


@pytest.mark.skipif(not _HAS_RAPIDOCR, reason="rapidocr 미설치 — install-ocr.bat으로 설치하면 이 시험도 실행된다")
def test_real_ocr_korean_and_numbers(tmp_path):
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=500, height=120)
    page.insert_text((20, 60), "총식이섬유 52.6 g/100g", fontsize=28, fontname="korea")
    pix = page.get_pixmap(dpi=250)
    f = tmp_path / "실측시험.png"
    pix.save(str(f))
    doc.close()

    assert parsers.ocr_available()
    out = parsers.parse_image(f)
    joined = "".join(b.get("text", "") for b in out["blocks"]).replace(" ", "")
    # 숫자는 항상 정확해야 한다. 한국어는 모델 성능에 따라 달라질 수 있어 핵심 토큰만 확인한다.
    assert "52.6" in joined
    assert "g/100g" in joined or "g/100 g" in joined
    assert "총식이섬유" in joined
    assert out["meta"]["ocr_mean_conf"] > 0.5
