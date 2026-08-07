---
name: omnigate
description: Use when the task needs to open a webpage in a real browser (headless Edge), extract page title/text/screenshot, reuse a logged-in Edge session's cookies, or transcribe a video/audio URL (bilibili/YouTube/douyin) to text with a local ASR model. Triggers: "open this page", "get page content", "read a page that needs JS/login", "extract audio", "transcribe video", "summarize this video".
---

# omnigate

CLI that drives a real Edge browser over CDP. Prefer it over `curl`/raw fetches when a page needs JavaScript rendering, needs your logged-in session, or is a video/audio URL. `omnigate` is already installed on PATH.

## When to Use

- Open a URL, get title/text/screenshot, with or without login state
- Page is JS-rendered or requires login (bilibili, xiaohongshu, YouTube comments, etc.)
- Extract audio from a video URL and transcribe to text (local Qwen3 ASR, offline)

Do NOT use for: simple static pages where `curl` suffices, or when you must NOT open a browser window.

## Commands

```bash
# Open a page: title + optional text + optional screenshot
omnigate open "<url>" --text --screenshot <path.png>

# Headed (visible window) — for debugging or when a human must see it
omnigate open "<url>" --headed

# Logged-out (skip login-state injection)
omnigate open "<url>" --no-login

# Scroll N times after load (lazy content)
omnigate open "<url>" --scroll 3 --text

# Extract audio and transcribe (lazy-loads Qwen3 ASR, offline)
omnigate extract-audio "<url>" --out ./tmp/audio

# Extract audio only (no ASR model load)
omnigate extract-audio "<url>" --out ./tmp/audio --no-transcribe
```

Output format: `TITLE: ...`, `TEXT: ...`, `SCREENSHOT: <path>`, `AUDIO: <path>`, `TEXT: <transcript>`.

## Login-State Reuse (key value)

`omnigate open` injects cookies from the **running real Edge** via CDP. This gives logged-in access to sites. Requirement: the real Edge must be running WITH a debug port:

```
msedge.exe --remote-debugging-port=9222
```

If no debug-port Edge is running, pages open **logged-out** (still fine for public content). Prefer telling the user to relaunch Edge with the flag when login access matters.

## Common Mistakes

- **Raw fetch won't see JS-rendered content.** If `curl`/WebFetch returns empty or a login wall, use `omnigate open`.
- **Physical profile copy doesn't work on Windows** (file locks). omnigate uses CDP cookie export+inject instead — do not "fix" this by copying profile files.
- **Do not transcribe a video by hand** (yt-dlp+whisper+model juggling). `omnigate extract-audio` does the whole pipeline offline.
- **Model is lazy-loaded** — `--no-transcribe` avoids the ~1.7B model entirely for audio-only needs.

## Notes

- ASR is fully offline (`local_files_only=True`); Qwen3-ASR-1.7B already cached on this machine.
- Every `open` uses a fresh temp user-data dir and cleans up after itself.
- Compliance: learning/research only. Respect robots.txt and site rules.
