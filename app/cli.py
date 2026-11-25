"""명령줄: python -m app.cli <init|serve|ingest|search|check-claude|ask|mcp|samples>"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from . import config, db


def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="byorbit", description="ByOrbit R&D Studio 개인용")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="데이터 폴더·DB·시드·MCP 설정 만들기")
    s = sub.add_parser("serve", help="로컬 웹앱 실행")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--no-watch", action="store_true")
    i = sub.add_parser("ingest", help="파일·폴더 넣기")
    i.add_argument("paths", nargs="+")
    i.add_argument("--project")
    i.add_argument("--confidentiality", default="내부", choices=["일반", "내부", "기밀"])
    q = sub.add_parser("search", help="자료 검색")
    q.add_argument("query")
    q.add_argument("--project")
    c = sub.add_parser("check-claude", help="Claude Code 연결 점검")
    c.add_argument("--no-smoke", action="store_true", help="실제 호출 없이 설치·설정만 확인")
    a = sub.add_parser("ask", help="Claude Code로 자료에 질문")
    a.add_argument("prompt")
    a.add_argument("--role", default="librarian")
    sub.add_parser("mcp", help="MCP 서버(stdio) 실행 — Claude Code가 부르는 용도")
    sp = sub.add_parser("samples", help="예시 자료를 받은편지함에 넣기")
    sp.add_argument("--project", default=None)
    args = ap.parse_args(argv)

    if args.cmd == "init":
        r = db.init(seed=True)
        from .engines import claude_code
        r["mcp_config"] = str(claude_code.write_mcp_config())
        _print(r)
    elif args.cmd == "serve":
        import uvicorn

        from .server import app
        db.init(seed=True)
        app.state.no_watch = args.no_watch
        port = args.port or int(config.load_settings().get("port", 8765))
        url = f"http://127.0.0.1:{port}/"
        print(f"ByOrbit R&D Studio — {url}  (데이터: {config.data_home()})  끝내려면 Ctrl+C")
        if not args.no_browser:
            import threading
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    elif args.cmd == "ingest":
        from .ingest import pipeline
        db.init(seed=True)
        files = []
        for p in map(Path, args.paths):
            files += [f for f in p.rglob("*") if f.is_file()] if p.is_dir() else [p]
        for f in files:
            try:
                r = pipeline.ingest_file(f, args.project, args.confidentiality)
                print(f"✓ {f.name}: 청크 {r['chunks']} · 라벨 {r['annotations']} · 측정값 {r['measurements']}"
                      + (f" · 오류 {r['error']}" if r.get("error") else ""))
            except pipeline.Duplicate:
                print(f"- {f.name}: 이미 들어온 파일")
            except Exception as e:  # noqa: BLE001
                print(f"✗ {f.name}: {e}")
    elif args.cmd == "search":
        from . import search
        db.init(seed=True)
        r = search.search(args.query, project=args.project)
        print("검색어 확장:", " / ".join(", ".join(g) for g in r["expanded"]))
        for h in r["results"]:
            print(f"[{h['score']}] {h['file_name']} p.{h['page'] or '-'}  {h['snippet']}")
    elif args.cmd == "check-claude":
        from .engines import claude_code
        db.init(seed=True)
        r = claude_code.check(smoke=not args.no_smoke)
        _print(r)
        sys.exit(0 if r.get("ok") else 1)
    elif args.cmd == "ask":
        from . import engines
        db.init(seed=True)
        r = engines.get().run(args.prompt, role=args.role, write=False)
        print(r.get("result") or r.get("error"))
    elif args.cmd == "mcp":
        from .mcp_server import main as mcp_main
        mcp_main()
    elif args.cmd == "samples":
        from .sample_files import make_samples
        db.init(seed=True)
        out = config.path("inbox", args.project) if args.project else config.path("inbox")
        _print({k: str(v) for k, v in make_samples(out).items()})


if __name__ == "__main__":
    main()
