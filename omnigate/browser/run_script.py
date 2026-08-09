"""Script replay engine: execute a list of command dicts against a browser.

A script is [{"cmd": "...", ...}] with commands:
  navigate {url}
  wait     {selector}
  click    {selector}
  input    {selector, text, enter?}
  extract  {}            -> capture page text
  scroll   {direction?}
If a required element never appears, the script is marked "stale"
(site changed) so the caller can fall back to improv.
"""
from __future__ import annotations


def run_script(browser, steps: list[dict], wait_timeout: float = 10.0) -> dict:
    """Execute script steps. Returns {"text":..., "stale": bool, "failed": bool}."""
    result: dict = {"stale": False, "failed": False}
    for step in steps:
        cmd = step.get("cmd")
        if cmd == "navigate":
            browser.navigate(step["url"])
        elif cmd == "wait":
            if not browser.wait_for(step["selector"], timeout=wait_timeout):
                result["stale"] = True
                break
        elif cmd == "click":
            if not browser.element_exists(step["selector"]):
                result["stale"] = True
                break
            browser.click(step["selector"])
        elif cmd == "input":
            if not browser.element_exists(step["selector"]):
                result["stale"] = True
                break
            browser.input(step["selector"], step["text"], enter=step.get("enter", False))
        elif cmd == "extract":
            result["text"] = browser.text()
        elif cmd == "scroll":
            browser.scroll(step.get("direction", "down"))
        else:
            result["failed"] = True
            result["error"] = f"Unknown command: {cmd}"
            break
    return result
