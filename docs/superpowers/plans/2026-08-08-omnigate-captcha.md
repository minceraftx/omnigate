# omnigate 验证码兜底 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 检测页面验证码 → 非阻塞告知大模型 → 大模型确认后弹窗给人解决 → 轮询恢复。

**Architecture:** "CLI 即协议"——stdout 是模型可见的状态。检测用规则（DOM 特征）。检测到验证码**不自动弹窗**，命令继续返回页面内容并输出 `⚠ CAPTCHA` 事件。大模型判断：误报忽略，确认受阻则调 `--solve-captcha` 显式弹窗。弹窗 = headless→headed 重启 + 重注入登录态 + 重导航。轮询特征消失即继续，3 分钟超时。

**协议（stdout 契约，模型可见）：**
```
⚠ CAPTCHA: {type: recaptcha} url: <url>
⚠ CAPTCHA_WINDOW_OPENED — 请人工解决
⚠ CAPTCHA_RESOLVED — 继续
⚠ CAPTCHA_TIMEOUT — 3分钟未解决
```

**Tech Stack:** Python 3.13, CDP, Edge 150。

**环境事实:** Edge 150；登录态 CDP 导出注入（物理复制不可靠）；Edge 需 `--remote-debugging-port` 才能注入。

---

## 文件结构

```
omnigate/
├── cli.py                  ← 加 --solve-captcha 参数
├── browser/
│   ├── captcha.py          ← 新增：验证码检测 + 事件格式
│   ├── actions.py          ← BrowserSession 加重新注入 helper
│   └── cdp.py              ← 已有
├── core.py                 ← open 集成检测；solve-captcha 流程
└── tests/
    └── test_captcha.py     ← 单元测试（检测器，无浏览器）
```

---

### Task 1: 验证码检测器（纯逻辑）

**Files:**
- Create: `omnigate/browser/captcha.py`
- Create: `tests/test_captcha.py`

- [ ] **Step 1: 写失败测试**

```python
"""Unit tests for captcha detection logic (no browser needed)."""
import unittest

from omnigate.browser.captcha import detect_captcha_features, CAPTCHA_PATTERNS


class TestDetectCaptchaFeatures(unittest.TestCase):
    def test_recaptcha_iframe(self):
        html = '<iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>'
        result = detect_captcha_features(html)
        self.assertIn("recaptcha", result)

    def test_turnstile(self):
        html = '<iframe src="https://challenges.cloudflare.com/turnstile/"></iframe>'
        result = detect_captcha_features(html)
        self.assertIn("turnstile", result)

    def test_plain_page_no_captcha(self):
        html = "<html><body><h1>Hello</h1></body></html>"
        result = detect_captcha_features(html)
        self.assertEqual(result, [])

    def test_returns_list_of_matches(self):
        html = '<iframe src="/recaptcha/"></iframe><div id="hcaptcha"></div>'
        result = detect_captcha_features(html)
        self.assertTrue(set(result) & {"recaptcha", "hcaptcha"})

    def test_case_insensitive(self):
        html = '<iframe src="/RECAPTCHA/"></iframe>'
        result = detect_captcha_features(html)
        self.assertIn("recaptcha", result)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_captcha.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: 写 captcha.py**

```python
"""Captcha detection via page DOM features.

Detection is rule-based (cheap, reliable) — the model never decides "is this
a captcha", only "do I act on it". 输出到 stdout 即协议。
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
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_captcha.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add omnigate/browser/captcha.py tests/test_captcha.py
git commit -m "feat: captcha detection via DOM features"
```

**Exit criteria（子智能体验证）:**
1. `python -m pytest tests/test_captcha.py -v` → 5 passed
2. `detect_captcha_features` 对 recaptcha/turnstile/hcaptcha/普通页/大小写，返回符合预期
3. `captcha_event` 输出格式 = `⚠ CAPTCHA: ... url: ...`
4. 纯逻辑无浏览器依赖

---

### Task 2: BrowserSession 加 "重注入登录态" helper

**Files:**
- Modify: `omnigate/browser/actions.py`

- [ ] **Step 1: 加 inject_login helper**

在 BrowserSession 加方法：
```python
    def inject_login(self) -> int:
        """Re-export cookies from running Edge and inject them. Returns count."""
        from omnigate.browser.cookies import export_cookies_from_running_edge, inject_cookies
        cookies = export_cookies_from_running_edge()
        return inject_cookies(self._require_session(), cookies)
```

- [ ] **Step 2: 手动验证（复用已知链路）**

```bash
cd /d/weber && python 2>&1 <<'EOF'
import tempfile, time
from omnigate.browser.edge import find_edge, free_port, launch_edge
from omnigate.browser.cdp import CdpSession, http_get_json
from omnigate.browser.cookies import export_cookies_from_running_edge

# 模拟用户 Edge（9222）种 cookie
tmp = tempfile.mkdtemp(prefix="omni-v-src-")
proc = launch_edge(find_edge(), 9222, tmp, headless=True)
deadline = time.time() + 30
while time.time() < deadline:
    try: http_get_json("http://127.0.0.1:9222/json/version"); break
    except Exception: time.sleep(0.5)
tab = http_get_json("http://127.0.0.1:9222/json/new?about:blank", method="PUT")
s = CdpSession(tab["webSocketDebuggerUrl"]); s.connect()
s.send("Network.setCookie", {"name":"t","value":"1","url":"https://example.com"})
s.close()

# 目标实例 inject_login
from omnigate.browser.actions import BrowserSession
from omnigate.browser.edge import free_port
b = BrowserSession(find_edge(), free_port(), tempfile.mkdtemp(prefix="omni-v-dst-"), headless=True)
b.start()
n = b.inject_login()
resp = b._require_session().send("Network.getAllCookies")
print("injected:", n, "has_t:", any(c["name"]=="t" for c in resp["result"]["cookies"]))
b.stop()
EOF
```
Expected: injected>0, has_t True

- [ ] **Step 3: Commit**

```bash
git add omnigate/browser/actions.py
git commit -m "feat: BrowserSession.inject_login helper"
```

**Exit criteria（子智能体验证）:**
1. `inject_login` 存在，复用 export+inject 链路
2. 模拟用户 Edge 种 cookie → 目标实例 inject_login → has_t True
3. 无孤儿进程

---

### Task 3: open 集成验证码检测（非阻塞输出）

**Files:**
- Modify: `omnigate/core.py`
- Modify: `omnigate/cli.py`（open 加 --solve-captcha 参数）

- [ ] **Step 1: open_page 加检测 + 事件输出**

在 core.py 的 open_page 中，navigate 后加：
```python
        b.navigate(url)
        # Captcha detection: non-blocking, inform model via stdout protocol.
        from omnigate.browser.captcha import detect_captcha_features, captcha_event
        page_html = ""
        try:
            resp = b._require_session().send(
                "Runtime.evaluate",
                {"expression": "document.documentElement.outerHTML", "returnByValue": True},
            )
            page_html = resp["result"]["result"].get("value", "")
        except Exception:
            pass
        features = detect_captcha_features(page_html)
        if features:
            print(captcha_event(features, url))
        result: dict = {"url": url, "title": b.title()}
```

- [ ] **Step 2: cli.py open 加 --solve-captcha**

subparser 加：
```python
    p.add_argument("--solve-captcha", action="store_true",
                   help="如果检测到验证码，立即弹窗人工解决（默认只告知不弹窗）")
```

dispatch 里把参数传进 open_page（新增 `solve_captcha=args.solve_captcha`）。

- [ ] **Step 3: 手动验证（本地假验证码页）**

造一个本地假验证码测试页：
```bash
mkdir -p ./tmp/captcha-test
cat > ./tmp/captcha-test/captcha.html <<'EOF'
<!DOCTYPE html><html><body>
<h1>内容</h1>
<iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>
</body></html>
EOF
```
注意：本地 file:// 页面的 outerHTML 会被检测。用 `omnigate open file:///.../captcha.html --text` 测：
```bash
python -m omnigate.cli open "file:///$(pwd)/tmp/captcha-test/captcha.html" --text
```
Expected: 输出 `⚠ CAPTCHA: recaptcha url: file://...` + TITLE/TEXT（命令不阻塞，继续返回）

- [ ] **Step 4: Commit**

```bash
git add omnigate/core.py omnigate/cli.py
git commit -m "feat: captcha detection in open, non-blocking protocol output"
```

**Exit criteria（子智能体验证）:**
1. 打开含 recaptcha iframe 的本地测试页 → stdout 有 `⚠ CAPTCHA: recaptcha`
2. 命令不阻塞，仍输出 TITLE/TEXT
3. 普通页面（无验证码）→ 无 CAPTCHA 行
4. `--solve-captcha` 参数存在且传入 open_page

---

### Task 4: --solve-captcha 显式弹窗流程

**Files:**
- Modify: `omnigate/core.py`
- Modify: `omnigate/browser/actions.py`（加 headed 重启 helper）

- [ ] **Step 1: 加 headed 重启 helper**

BrowserSession 加：
```python
    def relaunch_headed(self) -> None:
        """Stop the headless instance and restart it headed with the same
        user-data-dir (keeps injected state where possible) and login re-injected."""
        self.stop()
        self.headless = False
        self.start()
        self.inject_login()
```

- [ ] **Step 2: core.py 加 solve_captcha 流程**

open_page 加逻辑（当 solve_captcha=True 且检测到验证码）：
```python
        if features and solve_captcha:
            print("⚠ 检测到验证码，正在弹出窗口请人工解决...")
            b.relaunch_headed()
            b.navigate(url)
            print("⚠ CAPTCHA_WINDOW_OPENED — 请人工解决")
            # 轮询等待解决
            import time as _time
            deadline = _time.time() + 180
            while _time.time() < deadline:
                _time.sleep(3)
                try:
                    resp = b._require_session().send(
                        "Runtime.evaluate",
                        {"expression": "document.documentElement.outerHTML", "returnByValue": True},
                    )
                    html_now = resp["result"]["result"].get("value", "")
                except Exception:
                    html_now = ""
                if not detect_captcha_features(html_now):
                    print("⚠ CAPTCHA_RESOLVED — 继续")
                    break
            else:
                print("⚠ CAPTCHA_TIMEOUT — 3分钟未解决")
```

- [ ] **Step 3: 手动验证（本地假验证码页 + 模拟人解决）**

流程测试：打开假验证码页 --solve-captcha → 轮询 → 需要模拟"人解决"（验证码 iframe 消失）。
由于本地页无法真正被人改，用临时脚本在轮询中注入"移除 iframe"模拟解决：
（子智能体可验证轮询逻辑代码结构 + 超时分支，或临时脚本 mock）

- [ ] **Step 4: Commit**

```bash
git add omnigate/core.py omnigate/browser/actions.py
git commit -m "feat: solve-captcha headed popup flow with polling"
```

**Exit criteria（子智能体验证）:**
1. `relaunch_headed` 存在：stop→headless=False→start→inject_login
2. solve_captcha 流程：检测→弹窗→轮询→RESOLVED/TIMEOUT
3. 轮询 3 分钟超时正确
4. 代码 review 确认重启后重导航回 URL

---

## Self-Review

**Spec 覆盖：**
- 检测 = DOM 特征规则（非模型判断）✓ Task 1
- 非阻塞 = 检测到不弹窗，输出事件，继续返回内容 ✓ Task 3
- 模型决策 = CLI 即协议，skill 指导模型 ✓（协议已定义）
- 显式弹窗 = --solve-captcha ✓ Task 4
- 轮询 = 消失即继续，3 分钟超时 ✓ Task 4
- 重注入登录态 = relaunch_headed 里 inject_login ✓ Task 4

**粒度说明**：4 个 Task 各自独立交付。Task 1 纯逻辑；Task 2 helper；Task 3 检测集成；Task 4 弹窗流程。每步单点验证。

**诚实标注**：Task 4 的"人解决"无法用真实本地页模拟（验证码被人手点掉），用临时脚本注入"移除 iframe"模拟，或 code review 验证轮询逻辑。
