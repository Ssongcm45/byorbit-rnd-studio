"""시험용 예시 자료 생성: 사과박 논문 PDF(한글), CoA 엑셀, HWPX 보고서, 텍스트 메모.

모든 수치는 동작 확인용 가상의 값이다. 실제 연구 근거로 쓰지 말 것.
python -m app.sample_files <출력 폴더>
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

PAPER = [
    ("h", "사과박 분말의 건조 방법에 따른 식이섬유 및 폴리페놀 특성 (예시 자료)"),
    ("p", "※ 이 문서는 ByOrbit R&D Studio 동작 확인용 가상 논문이며 수치는 실제가 아닙니다."),
    ("h", "Abstract"),
    ("p", "사과 착즙박(apple pomace)을 동결건조(FD)와 열풍건조(60 ℃)로 처리한 뒤 총식이섬유(TDF), "
          "총폴리페놀(TPC), 보수력(WHC)을 비교하였다."),
    ("h", "2. Materials and Methods"),
    ("p", "사과박은 착즙 공장에서 수거하여 동결건조 또는 열풍건조 후 분쇄하였다. 총식이섬유는 AOAC 991.43, "
          "총폴리페놀은 Folin-Ciocalteu법으로 측정하였다."),
    ("h", "3. Results"),
    ("p", "동결건조 사과박의 총식이섬유는 건량 기준 54.2 g/100 g으로 열풍건조(48.7 g/100 g)보다 높았다. "
          "총폴리페놀은 동결건조 시료가 9.8 mg GAE/g, 열풍건조 시료가 6.1 mg GAE/g이었다. "
          "보수력은 각각 7.4 g/g과 5.9 g/g으로 나타났다."),
    ("h", "4. Conclusions"),
    ("p", "동결건조는 사과박 분말의 식이섬유와 폴리페놀 보존에 유리하여 식품소재 용도에 적합하다."),
]


def make_pdf(path: Path) -> Path:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    y = 60
    for kind, text in PAPER:
        size = 13 if kind == "h" else 10
        width = 42 if kind == "h" else 52
        lines, cur = [], ""
        for w in text.split(" "):
            if cur and len(cur) + 1 + len(w) > width:
                lines.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}" if cur else w
        lines.append(cur)
        for ln in lines:
            page.insert_text((50, y), ln, fontname="korea", fontsize=size)
            y += size + 6
        y += 10
    # 표
    y += 6
    page.insert_text((50, y), "Table 1. 건조 방법별 성분", fontname="korea", fontsize=10)
    y += 8
    rows = [["시료", "TDF (g/100 g)", "TPC (mg GAE/g)", "WHC (g/g)"],
            ["동결건조", "54.2", "9.8", "7.4"], ["열풍건조", "48.7", "6.1", "5.9"]]
    x0, cw, rh = 50, 120, 20
    for ri, r in enumerate(rows):
        for ci, v in enumerate(r):
            rect = pymupdf.Rect(x0 + ci * cw, y + ri * rh, x0 + (ci + 1) * cw, y + (ri + 1) * rh)
            page.draw_rect(rect, color=(0, 0, 0), width=0.6)
            page.insert_text((rect.x0 + 4, rect.y1 - 6), v, fontname="korea", fontsize=9)
    doc.set_metadata({"title": "사과박 분말 건조 방법 비교(예시)"})
    doc.save(str(path))
    doc.close()
    return path


def make_coa(path: Path) -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "성적서"
    ws.append(["시험성적서 (예시)"])
    ws.append([])
    ws.append(["시료명", "사과박", "", "성적서번호", "R-2026-0417"])
    ws.append(["의뢰처", "○○농산", "", "Lot No", "AP-2610-03"])
    ws.append(["접수일", "2026-10-21", "", "전처리", "동결건조"])
    ws.append([])
    ws.append(["시험항목", "결과", "단위", "기준", "시험방법"])
    ws.append(["총식이섬유", 52.6, "g/100 g", "건량", "AOAC 991.43"])
    ws.append(["총폴리페놀", 8.9, "mg GAE/g", "건량", "Folin-Ciocalteu법"])
    ws.append(["수분", 6.2, "%", "습량", "상압가열건조법"])
    ws.append(["회분", "1.8", "%", "건량", ""])
    ws.append(["납", "불검출", "mg/kg", "", ""])
    ws.append([])
    ws.append(["비고", "본 성적서는 시험용 가상 자료임"])
    wb.save(str(path))
    return path


def make_hwpx(path: Path) -> Path:
    hp = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    hs = "http://www.hancom.co.kr/hwpml/2011/section"

    def p(t):
        return f'<hp:p><hp:run><hp:t>{t}</hp:t></hp:run></hp:p>'

    def cell(t):
        return f'<hp:tc><hp:subList>{p(t)}</hp:subList></hp:tc>'

    table = ('<hp:p><hp:run><hp:tbl>'
             + "".join("<hp:tr>" + "".join(cell(c) for c in r) + "</hp:tr>" for r in
                       [["용도", "요구 물성", "사과박 적합성"], ["비건가죽", "인장강도", "보통"],
                        ["바이오플라스틱 필러", "입도 100 µm 이하", "높음"]])
             + '</hp:tbl></hp:run></hp:p>')
    body = (f'<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="{hs}" xmlns:hp="{hp}">'
            + p("1. 과제 개요") + p("사과 포마스를 바이오복합재 필러와 비건가죽 원료로 쓰기 위한 사전 검토 (예시 보고서)")
            + p("2. 용도별 검토") + table
            + p("3. 결론") + p("입도를 100 µm 이하로 분쇄하면 바이오플라스틱 필러 적용 가능성이 높다.")
            + '</hs:sec>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", body)
        z.writestr("Contents/content.hpf", "<opf/>")
    return path


def make_txt(path: Path) -> Path:
    path.write_text("# 실험 메모 (예시)\n\n굴 패각을 900 ℃에서 소성하면 탄산칼슘이 산화칼슘으로 바뀐다.\n\n"
                    "커피박(SCG)은 유지 함량이 높아 추출 후 바이오복합재 필러로 검토할 수 있다.\n", encoding="utf-8")
    return path


def make_all(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    return {
        "pdf": make_pdf(out / "예시논문_사과박_건조방법.pdf"),
        "coa": make_coa(out / "예시CoA_사과박_AP-2610-03.xlsx"),
        "hwpx": make_hwpx(out / "예시보고서_사과박_용도검토.hwpx"),
        "txt": make_txt(out / "예시메모_패각_커피박.txt"),
    }


if __name__ == "__main__":
    for k, v in make_all(Path(sys.argv[1] if len(sys.argv) > 1 else "samples")).items():
        print(k, v)
