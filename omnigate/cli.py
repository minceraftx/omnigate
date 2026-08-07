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

    args = parser.parse_args(argv)

    if args.command == "version":
        from omnigate import __version__
        print(__version__)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
