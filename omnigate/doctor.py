"""Environment diagnostics for omnigate.

Answers "why is login not working?" by checking, in order:
Edge executable, running Edge with debug port, login-state export capability.
"""
from __future__ import annotations

from omnigate.browser.edge import find_edge, find_edge_profile_dir
from omnigate.browser.cookies import find_debug_port


def diagnose() -> dict:
    """Run all checks, return a dict of results."""
    edge = find_edge()
    profile_dir = find_edge_profile_dir()
    port = find_debug_port()

    result = {
        "edge_found": edge is not None,
        "edge_path": edge,
        "profile_dir_found": profile_dir is not None,
        "profile_dir": profile_dir,
        "debug_port_found": port is not None,
        "debug_port": port,
    }
    return result


def report(d: dict) -> str:
    """Format diagnosis as human/AI-readable text. Uses ASCII markers to avoid
    Windows GBK terminal encoding errors (✓/✗ are not representable)."""
    lines = []
    ok = "[OK]"
    no = "[MISSING]"
    lines.append(f"Edge executable: {ok} {d['edge_path']}" if d["edge_found"] else f"Edge executable: {no}")
    lines.append(f"Edge profile dir: {ok} {d['profile_dir']}" if d["profile_dir_found"] else f"Edge profile dir: {no}")
    if d["debug_port_found"]:
        lines.append(f"Login-state source: {ok} debug port {d['debug_port']}")
        lines.append("  -> omnigate open will inject your Edge login state")
    else:
        lines.append("Login-state source: [MISSING] no Edge with --remote-debugging-port found")
        lines.append("  -> pages open logged-out")
        lines.append("  -> to reuse login state, launch Edge with:")
        lines.append("     msedge.exe --remote-debugging-port=9222")
    return "\n".join(lines)
