"""omnigate CLI entry point.

AI-facing command set. Each command maps to a core orchestrator function.
Design note: core logic lives in functions so commands can be re-skinned
(e.g. registered as a skill later) without changing behavior.
"""
import argparse
import sys


def _force_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 so non-ASCII page content
    (CJK, emoji, Korean) never trips the Windows GBK default code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="omnigate",
        description="Browser capability library for AI agents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="Show version")
    sub.add_parser("doctor", help="Check environment: Edge, login-state source")

    p = sub.add_parser("extract-audio", help="Extract audio from a video URL and transcribe")
    p.add_argument("url", help="Video URL (bilibili/youtube/douyin...)")
    p.add_argument("--out", default="./tmp/audio", help="Output dir for audio + transcript")
    p.add_argument("--no-transcribe", action="store_true",
                   help="Skip transcription (only extract audio)")

    p = sub.add_parser("open", help="Open a URL in headless Edge, return content")
    p.add_argument("url", help="URL to open")
    p.add_argument("--headed", dest="headless", action="store_false", default=True,
                   help="Show a browser window instead of headless")
    p.add_argument("--screenshot", default=None, help="Save screenshot to path")
    p.add_argument("--text", action="store_true", help="Also extract page text")
    p.add_argument("--scroll", type=int, default=0, help="Scroll N times after load")
    p.add_argument("--no-login", action="store_true",
                   help="Skip login-state injection (open logged-out)")
    p.add_argument("--solve-captcha", action="store_true",
                   help="如果检测到验证码，立即弹窗人工解决（默认只告知不弹窗）")
    p.add_argument("--full-login", action="store_true",
                   help="注入全量 Cookie（默认只注入目标站点域；跨域 SSO 站点用此项）")
    p.add_argument("--state", action="store_true",
                   help="列出页面可交互元素（供写 CSS selector）")

    p = sub.add_parser("script", help="Manage command-sequence scripts")
    ssub = p.add_subparsers(dest="script_cmd", required=True)
    ssub.add_parser("list", help="List scripts")
    ssub.add_parser("show", help="Show a script").add_argument("name")
    psave = ssub.add_parser("save", help="Save a script")
    psave.add_argument("name")
    psave.add_argument("--steps", required=True, help="JSON array of steps")
    ssub.add_parser("delete", help="Delete a script").add_argument("name")
    ssub.add_parser("run", help="Replay a script").add_argument("name")

    args = parser.parse_args(argv)

    if args.command == "version":
        from omnigate import __version__
        print(__version__)
        return 0

    if args.command == "doctor":
        from omnigate.doctor import diagnose, report
        print(report(diagnose()))
        return 0

    if args.command == "extract-audio":
        from omnigate.audio.transcribe import extract_audio, transcribe_wav
        path = extract_audio(args.url, args.out)
        print(f"AUDIO: {path}")
        if not args.no_transcribe:
            text = transcribe_wav(path)
            print(f"TEXT: {text}")
        return 0

    if args.command == "open":
        from omnigate.core import open_page
        result = open_page(
            args.url, headless=args.headless,
            screenshot=args.screenshot, get_text=args.text,
            scroll_count=args.scroll, use_login=not args.no_login,
            solve_captcha=args.solve_captcha, full_login=args.full_login,
            get_state=args.state,
        )
        print(f"TITLE: {result['title']}")
        if result.get("state"):
            for e in result["state"]:
                print(f"  [{e['i']}] <{e['tag']}> text={e.get('text','')!r} id={e.get('id','')!r} cls={e.get('cls','')!r}")
        if result.get("text"):
            print(f"TEXT:\n{result['text']}")
        if result.get("screenshot"):
            print(f"SCREENSHOT: {result['screenshot']}")
        return 0

    if args.command == "script":
        import json
        from omnigate.script_store import ScriptStore
        store = ScriptStore()
        if args.script_cmd == "list":
            for name in store.list_names():
                print(name)
            return 0
        if args.script_cmd == "show":
            print(json.dumps(store.load(args.name), ensure_ascii=False, indent=2))
            return 0
        if args.script_cmd == "save":
            import json
            steps = json.loads(args.steps)
            store.save(args.name, steps)
            print(f"saved: {args.name}")
            return 0
        if args.script_cmd == "delete":
            store.delete(args.name)
            print(f"deleted: {args.name}")
            return 0
        if args.script_cmd == "run":
            from omnigate.core import run_script_page
            result = run_script_page(args.name)
            print(f"STALE: {result.get('stale', False)}")
            print(f"FAILED: {result.get('failed', False)}")
            if result.get("text"):
                print(f"TEXT:\n{result['text']}")
            if result.get("error"):
                print(f"ERROR: {result['error']}")
            return 1 if result.get("failed") or result.get("stale") else 0

    return 0


if __name__ == "__main__":
    _force_utf8_stdio()
    raise SystemExit(main())
