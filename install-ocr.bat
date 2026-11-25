@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto venv_ok
echo [!] .venv가 없습니다. 먼저 install.bat을 실행해 기본 설치를 끝내세요.
pause
exit /b 1

:venv_ok
echo.
echo === ByOrbit R^&D Studio - 로컬 OCR(RapidOCR) 설치 ===
echo 스캔 PDF와 CoA 사진(.png/.jpg/.jpeg/.tif/.tiff)을 이 PC에서만 글자로 바꿉니다. 이미지는 PC 밖으로 나가지 않습니다.
echo.
echo [1/2] 패키지 설치 (requirements-ocr.txt: rapidocr, onnxruntime)...
".venv\Scripts\python.exe" -m pip install -r requirements-ocr.txt
if errorlevel 1 goto pip_fail

echo.
echo [2/2] 자가 점검(이미지 생성 -^> 한국어 OCR)...
echo       처음 실행이면 한국어 인식 모델을 인터넷에서 자동으로 내려받습니다(약 20~25MB).
echo       내려받은 모델은 .venv\Lib\site-packages\rapidocr\models\ 에 저장되며, 다음부터는 다시 받지 않습니다.
set PYTHONUTF8=1
".venv\Scripts\python.exe" -c "from app.ingest import parsers as p; import pymupdf; doc=pymupdf.open(); pg=doc.new_page(width=400, height=100); pg.insert_text((20,55), '자가점검 123', fontsize=28, fontname='korea'); png=pg.get_pixmap(dpi=250).tobytes('png'); lines=p._ocr_lines(png); text=' '.join(ln['text'] for ln in lines); print('OCR 자가점검 결과:', text or '(인식 결과 없음)'); raise SystemExit(0 if text else 1)"
if errorlevel 1 goto check_fail

echo.
echo 설치가 끝났습니다. 이제 스캔 PDF와 CoA 사진이 받은편지함에 들어오면 자동으로 글자 인식됩니다.
pause
exit /b 0

:pip_fail
echo [!] 패키지 설치 실패
pause
exit /b 1

:check_fail
echo [!] 자가 점검 실패 — 위 오류 메시지를 확인하세요.
pause
exit /b 1
