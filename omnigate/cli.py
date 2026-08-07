"""omnigate CLI entry point.

AI-facing command set. Each command maps to a core orchestrator function.
Design note: core logic lives in functions so commands can be re-skinned
(e.g. registered as a skill later) without changing behavior.
"""
import argparse


def main(argv: list[str] | None = None) -> int:
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
            solve_captcha=args.solve_captcha,
        )
        print(f"TITLE: {result['title']}")
        if result.get("text"):
            print(f"TEXT:\n{result['text']}")
        if result.get("screenshot"):
            print(f"SCREENSHOT: {result['screenshot']}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
