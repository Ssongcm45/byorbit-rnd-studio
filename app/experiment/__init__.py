"""내 실험 — 공정 흐름(원료 → 전처리 → 건조 → 분말화 → 추출 …) 위에서 내 조건·결과를 기록하고 예측과 비교·보정한다.

- steps.py: 단위 공정 목록과 질량·수분·성분 흐름 모델(건조는 app/viz/predict.py에 맡긴다)
- store.py: 흐름(workflow.graph_json)·실험·런·값 저장
- sim.py: 흐름 모의, 예측 대 실측 비교, 민감도
- importer.py: CSV·XLSX 가져오기(열 대응) / CSV 내보내기
- calib.py: 내 실험 실측을 건조 예측의 보정 근거로 쓰기(미리보기·적용)
- plan.py: 다음 실험 조건 제안
"""
