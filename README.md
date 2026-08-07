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
# Open a page, get title + text
omnigate open "https://example.com" --text

# Screenshot
omnigate open "https://example.com" --screenshot shot.png

# Headed (pop a window) for manual/visual tasks
omnigate open "https://example.com" --headed

# Open without login-state injection (logged-out)
omnigate open "https://example.com" --no-login

# Extract audio and transcribe (lazy-loads Qwen3 ASR)
omnigate extract-audio "https://www.bilibili.com/video/BVxxxx" --out ./tmp/audio

# Extract audio only (no model load)
omnigate extract-audio "https://..." --out ./tmp/audio --no-transcribe
```

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

## Notes & limitations

- On Windows, copying the Edge profile's cookie file does not survive a
  running Edge (file locks) nor a closed one (SQLite buffering + Edge v127+
  encryption). That is why login-state reuse goes through CDP cookies, not
  file copies.
- Physical profile copy still happens behind the scenes for non-login state;
  locked files are skipped individually rather than aborting the whole launch.

## Compliance

This tool is for learning and research. Respect target sites' robots.txt and
applicable laws. Do not use for abusive scraping, credential stuffing, or
anything that harms other users or services.
