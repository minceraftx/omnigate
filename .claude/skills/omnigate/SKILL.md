---
name: omnigate
description: Use when the task needs to open a webpage in a real browser (headless Edge), extract page title/text/screenshot, reuse a logged-in Edge session's cookies, or transcribe a video/audio URL (bilibili/YouTube/douyin) to text with a local ASR model. Triggers: "open this page", "get page content", "read a page that needs JS/login", "extract audio", "transcribe video", "summarize this video", "check environment/diagnose login".
---

# omnigate

CLI that drives a real Edge browser over CDP. Prefer it over `curl`/raw fetches when a page needs JavaScript rendering, needs your logged-in session, or is a video/audio URL. `omnigate` is already installed on PATH.

## When to Use

- Open a URL, get title/text/screenshot, with or without login state
- Page is JS-rendered or requires login (bilibili, xiaohongshu, YouTube comments, etc.)
- Extract audio from a video URL and transcribe to text (local Qwen3 ASR, offline)
- Diagnose why login-state isn't working (`doctor`)
- Check whether a page hit a CAPTCHA and needs a human

Do NOT use for: simple static pages where `curl` suffices, or when you must NOT open a browser window.

## Commands

```bash
# Diagnose environment: Edge found? login-state source available?
omnigate doctor

# Open a page: title + optional text + optional screenshot
omnigate open "<url>" --text --screenshot <path.png>

# Headed (visible window) — for debugging or when a human must see it
omnigate open "<url>" --headed

# Logged-out (skip login-state injection)
omnigate open "<url>" --no-login

# Scroll N times after load (lazy content)
omnigate open "<url>" --scroll 3 --text

# If a CAPTCHA blocks the page, pop a window for a human to solve:
omnigate open "<url>" --solve-captcha

# Cross-domain SSO site: inject ALL cookies (default is target-domain only)
omnigate open "<url>" --full-login

# Manage command-sequence scripts (experience memory)
omnigate script list
omnigate script show <name>
omnigate script save <name> --steps '[{"cmd":"navigate","url":"..."}]'
omnigate script run <name>        # replay a script (re-executes its steps)
omnigate script delete <name>

# Extract audio and transcribe (lazy-loads Qwen3 ASR, offline)
omnigate extract-audio "<url>" --out ./tmp/audio

# Extract audio only (no ASR model load)
omnigate extract-audio "<url>" --out ./tmp/audio --no-transcribe
```

Transcription backend is chosen automatically: the FunASR env (`D:\whisper\funasr\python.exe`, or set `FUNASR_PYTHON`) when present — Qwen3-ASR + fsmn-vad, no OOM on long videos — otherwise the built-in qwen_asr backend.

Script steps support: `navigate {url}`, `wait {selector}`, `click {selector}`, `input {selector,text,enter?}`, `extract {}`, `scroll {direction?}`. First step must be `navigate`. On replay, a missing element marks the script `STALE` (site changed) — re-record it and update the lesson.

**Write selectors from the real DOM, never guess.** To inspect a page's interactive elements, use the browser layer's `state` action (lists buttons/inputs/links with tag, text, id, class). Interaction uses CSS selectors, not indexes — more stable across site changes.

Output format: `TITLE: ...`, `TEXT: ...`, `SCREENSHOT: <path>`, `AUDIO: <path>`, `TEXT: <transcript>`, `[CAPTCHA] ...`.

## CAPTCHA protocol (stdout is the contract)

`open` auto-detects CAPTCHAs and reports them WITHOUT blocking (page content still returned). The model decides how to act — never guess.

```
[CAPTCHA] recaptcha url: <url>            ← detected, but page content also returned
[CAPTCHA] CAPTCHA_WINDOW_OPENED           ← after --solve-captcha, window popped
[CAPTCHA] CAPTCHA_RESOLVED - 继续          ← human solved, task continues
[CAPTCHA] CAPTCHA_TIMEOUT - <s>秒未解决     ← human didn't solve in time
```

When you see `[CAPTCHA]`:
1. First read the page TEXT. If the page is usable and only a stray element matched, treat it as a false positive and continue.
2. If the page is genuinely blocked, tell the user "encountered a CAPTCHA", then run `omnigate open "<url>" --solve-captcha` to pop a window for them.
3. On `CAPTCHA_TIMEOUT`, tell the user it wasn't solved and stop for instructions. Do not keep retrying blindly.

## Login-State Reuse (key value)

`omnigate open` injects cookies from the **running real Edge** via CDP. This gives logged-in access to sites. Requirement: the real Edge must be running WITH a debug port:

```
msedge.exe --remote-debugging-port=9222
```

If no debug-port Edge is running, pages open **logged-out** (still fine for public content). Prefer telling the user to relaunch Edge with the flag when login access matters.

**Domain-scoped by default (security)**: only cookies for the target site's domain are injected. For sites that rely on cross-domain SSO (e.g. Google account login on a third-party site), login may be incomplete — use `--full-login` to inject all cookies:

```bash
omnigate open "<url>" --full-login
```

**Request headers are real Edge's own** — omnigate drives a real Edge process, so UA / headers / TLS come from Edge itself (not a spoofed browser). This is the anti-bot value: the traffic looks like a genuine browser. Do not try to "add stealth headers" on top — that would make it LESS like a real browser.

## Experience Memory (渐进式披露)

omnigate keeps two knowledge stores. Before working with a site, check them:

- `omnigate/scripts/` — saved command-sequence scripts. If one exists for the task/site, reuse it.
- `omnigate/lessons/<site>.md` — lessons about a specific site (anti-bot, captchas, extraction tricks).

Rules:
1. Before working on a site, read `omnigate/lessons/<site>.md` if it exists, then decide how to proceed.
2. When you hit a new lesson (captcha, anti-bot, parse failure) and solve it, append the lesson to `omnigate/lessons/<site>.md`.
3. When you successfully complete a multi-step task, save the steps as a script: `omnigate script save <site>-<task> --steps '[...]'`.
4. If reusing a script fails (site changed), update the lesson and re-save the script.

Lesson file format (`omnigate/lessons/<site>.md`):
```markdown
# <site>
## Pitfalls
- description + solution
## Tips
- what actually works for this site
```

## Common Mistakes

- **Raw fetch won't see JS-rendered content.** If `curl`/WebFetch returns empty or a login wall, use `omnigate open`.
- **Physical profile copy doesn't work on Windows** (file locks). omnigate uses CDP cookie export+inject instead — do not "fix" this by copying profile files.
- **Do not transcribe a video by hand** (yt-dlp+whisper+model juggling). `omnigate extract-audio` does the whole pipeline offline.
- **Model is lazy-loaded** — `--no-transcribe` avoids the ~1.7B model entirely for audio-only needs.
- **Never auto-retry a CAPTCHA by guessing.** Read the page, decide, use `--solve-captcha` if genuinely blocked, stop on timeout.

## Notes

- ASR is fully offline (HF cache only); Qwen3-ASR-1.7B already cached on this machine. Backend auto-picks FunASR (when its env exists) over the built-in qwen_asr.
- Every `open` uses a fresh temp user-data dir and cleans up after itself.
- Compliance: learning/research only. Respect robots.txt and site rules.
