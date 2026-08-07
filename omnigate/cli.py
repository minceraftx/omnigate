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

    p = sub.add_parser("extract-audio", help="Extract audio from a video URL and transcribe")
    p.add_argument("url", help="Video URL (bilibili/youtube/douyin...)")
    p.add_argument("--out", default="./tmp/audio", help="Output dir for audio + transcript")
    p.add_argument("--no-transcribe", action="store_true",
                   help="Skip transcription (only extract audio)")

    args = parser.parse_args(argv)

    if args.command == "version":
        from omnigate import __version__
        print(__version__)
        return 0

    if args.command == "extract-audio":
        from omnigate.audio.transcribe import extract_audio, transcribe_wav
        path = extract_audio(args.url, args.out)
        print(f"AUDIO: {path}")
        if not args.no_transcribe:
            text = transcribe_wav(path)
            print(f"TEXT: {text}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
