"""Captcha detection via page DOM features.

Detection is rule-based (cheap, reliable) — the model never decides "is this
a captcha", only "do I act on it". stdout is the protocol for the model.
"""
from __future__ import annotations

# Captcha markers found in iframe src / element ids / class names.
# All lowercase; matched case-insensitively against page HTML/URLs.
CAPTCHA_PATTERNS = (
    "recaptcha",
    "hcaptcha",
    "turnstile",
    "captcha",
    "g-recaptcha",
    "cf-chl",
)


def detect_captcha_features(html_or_text: str) -> list[str]:
    """Return the captcha markers found in the given page HTML/text.

    Empty list = no captcha detected. Non-empty = captcha present.
    """
    low = (html_or_text or "").lower()
    found = []
    for pat in CAPTCHA_PATTERNS:
        if pat in low and pat not in found:
            found.append(pat)
    return found


def captcha_event(features: list[str], url: str) -> str:
    """Format the stdout protocol line for a detected captcha."""
    return f"⚠ CAPTCHA: {', '.join(features)} url: {url}"
