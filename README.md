# omnigate

Browser capability library for AI agents. Drive a real Edge browser (reusing
your login state), extract page content, and optionally transcribe audio with
a local ASR model.

## Install

```bash
pip install -e .
pip install yt-dlp qwen-asr  # only if using audio extraction/transcription
```

## Usage

```bash
# Diagnose environment: Edge found? login-state source available?
omnigate doctor

# Open a page, get title + text
omnigate open "https://example.com" --text

# Screenshot
omnigate open "https://example.com" --screenshot shot.png

# Headed (pop a window) for manual/visual tasks
omnigate open "https://example.com" --headed

# Open without login-state injection (logged-out)
omnigate open "https://example.com" --no-login

# List interactive elements (helps write CSS selectors for scripts)
omnigate open "https://example.com" --state

# Cross-domain SSO site: inject ALL cookies (default is target-domain only)
omnigate open "https://example.com" --full-login

# If a CAPTCHA blocks the page, pop a window for a human to solve
omnigate open "https://example.com" --solve-captcha

# Experience memory: command-sequence scripts
omnigate script list
omnigate script show <name>
omnigate script save <name> --steps '[{"cmd":"navigate","url":"..."}]'
omnigate script run <name>   # replay a script (re-executes its steps)
omnigate script delete <name>

# Extract audio and transcribe (lazy-loads Qwen3 ASR)
omnigate extract-audio "https://www.bilibili.com/video/BVxxxx" --out ./tmp/audio

# Extract audio only (no model load)
omnigate extract-audio "https://..." --out ./tmp/audio --no-transcribe
```

Script steps support: `navigate {url}`, `wait {selector}`, `click {selector}`, `input {selector,text,enter?}`, `extract {}`, `scroll {direction?}`. The first step must be `navigate`. On replay, a missing element marks the script `STALE` (site changed) — re-record and update the lesson.

## How it works

- **Browser layer**: launches a headless Edge instance over the Chrome
  DevTools Protocol (CDP). Your real Edge is never touched.
- **Login-state reuse**: attaches the running real Edge over CDP
  (`Network.getAllCookies`), exports cookies, and injects them into the
  headless instance (`Network.setCookies`). The running Edge must expose a
  debug port:
  ```
  msedge.exe --remote-debugging-port=9222
  ```
  If no debug-port Edge is reachable, pages open logged-out (a logged-out
  session still works for public content).
- **Audio**: `extract-audio` pulls the audio stream with yt-dlp to a wav file,
  then transcribes with Qwen3-ASR-1.7B running locally on CUDA. The ASR model
  is lazy-loaded — browser tasks never pay its memory cost, and it loads from
  the local cache only (fully offline).

## CAPTCHA protocol

`open` auto-detects CAPTCHAs and reports them **without blocking** (page content still returned). The model decides how to act:

```
[CAPTCHA] recaptcha url: <url>           ← detected, page content also returned
[CAPTCHA] CAPTCHA_WINDOW_OPENED          ← after --solve-captcha, window popped
[CAPTCHA] CAPTCHA_RESOLVED - 继续         ← human solved, task continues
[CAPTCHA] CAPTCHA_TIMEOUT - <s>秒未解决    ← human didn't solve in time
```

On a `[CAPTCHA]` line, first read the page text (may be a false positive); if genuinely blocked, run `--solve-captcha` to pop a window for a human.

## Experience Memory (double-mode)

omnigate keeps two knowledge stores so the model "learns once, never re-learns":

- `omnigate/scripts/` — saved command-sequence scripts. Reuse an existing script before improvising.
- `omnigate/lessons/<site>.md` — lessons about a site (anti-bot, captchas, extraction tricks). Written by the model after solving a new problem.

The skill uses **progressive disclosure**: it only points at these stores and the model reads the relevant file before working on a site.

## Notes & limitations

- On Windows, copying the Edge profile's cookie file does not survive a
  running Edge (file locks) nor a closed one (SQLite buffering + Edge v127+
  encryption). That is why login-state reuse goes through CDP cookies, not
  file copies.
- Physical profile copy still happens behind the scenes for non-login state;
  locked files are skipped individually rather than aborting the whole launch.

## Security Model

- omnigate exports cookies from the running Edge (`Network.getAllCookies`) as
  the login-state source, but by default **only injects cookies for the
  target site's domain** into the automation instance. Cross-domain SSO sites
  can opt into full injection with `--full-login`.
- The login-state source (an Edge launched with
  `--remote-debugging-port=9222`) is unauthenticated and local-only: **use a
  dedicated Edge profile for the login-state source** (only logged into the
  sites automation needs); do not keep your everyday browser on a debug port.
- Any agent able to invoke omnigate retains access to whatever the
  login-state source is logged into — **expose omnigate only to trusted
  callers**.
- `open` accepts arbitrary URLs, including `file://` (readable local files,
  surfaced via `--text`/`--screenshot`) and intranet addresses. Current
  callers are trusted agents with full local permission, so no scheme
  allowlist is enforced; **if omnigate is ever exposed to a restricted agent
  without file access, add an http/https scheme allowlist first**.
- The automation instance uses a fresh temp profile, deleted on exit; cleanup
  failures warn on stderr.

## Compliance

This tool is for learning and research. Respect target sites' robots.txt and
applicable laws. Do not use for abusive scraping, credential stuffing, or
anything that harms other users or services.
