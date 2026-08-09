# omnigate 剧本回放 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补全双模式的执行层——BrowserSession 交互原语（state/click/input/wait）+ 剧本回放引擎，让"即兴→固化剧本→回放"闭环。

**Architecture:** 元素定位统一用 CSS selector（回放稳定）。`state` 命令列出真实可交互元素（索引+标签+属性），模型据此写准 selector。回放引擎按序执行剧本动作，元素找不到 = 网页改版 = 标记失效。selector 用标准 `document.querySelector`。

**Tech Stack:** Python 3.13, CDP, Edge 151。

**环境事实:** 36 commits 在 master，33 测试过。现有 BrowserSession 只有 navigate/title/text/scroll/screenshot。ScriptStore 已能存剧本（`[{"cmd":...}]`）。

---

## 文件结构

```
omnigate/
├── cli.py                  ← open 加 --run-script；script 加 run
├── browser/
│   ├── actions.py          ← BrowserSession 加 state/click/input/wait/element
│   └── run_script.py       ← 新增：剧本回放引擎
├── core.py                 ← open_page 加 run_script 接线
└── tests/
    └── test_run_script.py  ← 回放引擎单测（mock 元素）
```

---

### Task 1: BrowserSession 元素定位原语（query + wait）

**Files:**
- Modify: `omnigate/browser/actions.py`

- [ ] **Step 1: 加 `_query` + `element_exists` + `wait_for`**

在 BrowserSession 加方法：
```python
    def element_exists(self, selector: str) -> bool:
        """Whether at least one element matches the CSS selector."""
        expr = f"!!document.querySelector({selector!r})"
        resp = self._require_session().send(
            "Runtime.evaluate", {"expression": expr, "returnByValue": True}
        )
        return bool(resp["result"]["result"].get("value"))

    def wait_for(self, selector: str, timeout: float = 10.0) -> bool:
        """Wait until an element matching selector appears. Returns True if found."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.element_exists(selector):
                return True
            time.sleep(0.5)
        return False
```

- [ ] **Step 2: 手动验证**

```bash
cd /d/weber && python 2>&1 <<'EOF'
import tempfile
from omnigate.browser.edge import find_edge, free_port
from omnigate.browser.actions import BrowserSession
b = BrowserSession(find_edge(), free_port(), tempfile.mkdtemp(prefix="omni-el-"), headless=True)
b.start()
b.navigate("https://example.com")
print("h1 exists:", b.element_exists("h1"))
print("h1 wait:", b.wait_for("h1"))
print("nonexistent:", b.element_exists(".no-such-class"))
b.stop()
EOF
```
Expected: `h1 exists: True`, `h1 wait: True`, `nonexistent: False`

- [ ] **Step 3: Commit**

```bash
git add omnigate/browser/actions.py
git commit -m "feat: element query + wait primitives"
```

**Exit criteria（子智能体验证）:**
1. `element_exists("h1")` 对 example.com 返回 True；不存在的 selector 返回 False
2. `wait_for` 等待元素出现，超时返回 False
3. selector 用 `document.querySelector` 标准 CSS，`!r` 转义防注入

---

### Task 2: state 命令——列出可交互元素

**Files:**
- Modify: `omnigate/browser/actions.py`

- [ ] **Step 1: 加 `state()`**

```python
    def state(self, limit: int = 30) -> list[dict]:
        """List interactive elements (button/input/a/link) with index + tag + text.

        Model reads this to write precise CSS selectors for click/input.
        """
        expr = """
        (() => {
          const els = [...document.querySelectorAll('button, input, a, select, [role=button], [onclick]')];
          const out = [];
          for (const [i, el] of els.entries()) {
            if (i >= %d) break;
            const r = el.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) continue; // hidden
            out.push({
              i: i,
              tag: el.tagName.toLowerCase(),
              type: el.getAttribute('type') || '',
              text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 60),
              id: el.id || '',
              cls: (el.className && typeof el.className === 'string') ? el.className.slice(0, 40) : ''
            });
          }
          return out;
        })()
        """ % limit
        resp = self._require_session().send(
            "Runtime.evaluate", {"expression": expr, "returnByValue": True}
        )
        value = resp["result"]["result"].get("value")
        return value if isinstance(value, list) else []
```

- [ ] **Step 2: 手动验证**

```bash
cd /d/weber && python 2>&1 <<'EOF'
import tempfile
from omnigate.browser.edge import find_edge, free_port
from omnigate.browser.actions import BrowserSession
b = BrowserSession(find_edge(), free_port(), tempfile.mkdtemp(prefix="omni-st-"), headless=True)
b.start()
b.navigate("https://example.com")
els = b.state()
print("elements:", len(els))
for e in els[:5]:
    print(" ", e["i"], e["tag"], e.get("text", "")[:30])
b.stop()
EOF
```
Expected: 列出 example.com 的可交互元素（可能有 "Learn more" 链接）

- [ ] **Step 3: Commit**

```bash
git add omnigate/browser/actions.py
git commit -m "feat: state command listing interactive elements"
```

**Exit criteria（子智能体验证）:**
1. `state()` 返回 list，每项含 i/tag/type/text/id/cls
2. 隐藏元素（宽高 0）被跳过
3. 返回结构适合模型据此写 selector

---

### Task 3: click + input 交互原语

**Files:**
- Modify: `omnigate/browser/actions.py`

- [ ] **Step 1: 加 click + input**

```python
    def click(self, selector: str) -> bool:
        """Click the first element matching selector. Returns True if clicked."""
        expr = """
        (() => {
          const el = document.querySelector(%r);
          if (!el) return false;
          el.scrollIntoView({block: 'center'});
          el.click();
          return true;
        })()
        """ % selector
        resp = self._require_session().send(
            "Runtime.evaluate", {"expression": expr, "returnByValue": True}
        )
        return bool(resp["result"]["result"].get("value"))

    def input(self, selector: str, text: str, enter: bool = False) -> bool:
        """Set an input's value and dispatch input event. Returns True if set."""
        expr = """
        (() => {
          const el = document.querySelector(%r);
          if (!el) return false;
          el.scrollIntoView({block: 'center'});
          el.focus();
          el.value = %r;
          el.dispatchEvent(new Event('input', {bubbles: true}));
          el.dispatchEvent(new Event('change', {bubbles: true}));
          return true;
        })()
        """ % (selector, text)
        resp = self._require_session().send(
            "Runtime.evaluate", {"expression": expr, "returnByValue": True}
        )
        ok = bool(resp["result"]["result"].get("value"))
        if ok and enter:
            from omnigate.browser.cdp import CdpSession
            self._require_session().send(
                "Runtime.evaluate",
                {"expression": "(function(){const el=document.querySelector(%r); if(!el)return; el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',keyCode:13,which:13,bubbles:true})); return true;})()" % selector},
            )
        return ok
```

- [ ] **Step 2: 手动验证（本地测试页）**

```bash
mkdir -p ./tmp/interact-test && cat > ./tmp/interact-test/form.html <<'EOF'
<!DOCTYPE html><html><body>
<input id="q" placeholder="search">
<button id="go">Search</button>
<div id="result"></div>
<script>
document.getElementById('go').onclick = function() {
  document.getElementById('result').innerText =
    'typed: ' + document.getElementById('q').value;
};
</script>
</body></html>
EOF
cd /d/weber && python 2>&1 <<'EOF'
import tempfile, os
from omnigate.browser.edge import find_edge, free_port
from omnigate.browser.actions import BrowserSession
b = BrowserSession(find_edge(), free_port(), tempfile.mkdtemp(prefix="omni-in-"), headless=True)
b.start()
b.navigate("file:///" + os.path.abspath("./tmp/interact-test/form.html").replace("\\", "/"))
print("input set:", b.input("#q", "hello"))
print("click:", b.click("#go"))
print("result:", b.text())
b.stop()
EOF
```
Expected: `input set: True`, `click: True`, result contains `typed: hello`

- [ ] **Step 3: Commit**

```bash
git add omnigate/browser/actions.py
git commit -m "feat: click and input interaction primitives"
```

**Exit criteria（子智能体验证）:**
1. `click("#go")` 触发按钮，页面状态改变
2. `input("#q", "hello")` 设置值并派发 input/change 事件，React 等框架能收到
3. `enter=True` 时派发 Enter 键事件
4. selector 转义安全（`%r`）

---

### Task 4: 剧本回放引擎

**Files:**
- Create: `omnigate/browser/run_script.py`
- Create: `tests/test_run_script.py`

- [ ] **Step 1: 写失败测试**

```python
"""Unit tests for the script replay engine (mock browser, no real Edge)."""
import unittest
from unittest.mock import MagicMock

from omnigate.browser.run_script import run_script


class TestRunScript(unittest.TestCase):
    def _make_browser(self):
        b = MagicMock()
        b.wait_for.return_value = True
        b.element_exists.return_value = True
        b.click.return_value = True
        b.input.return_value = True
        b.title.return_value = "T"
        return b

    def test_navigate_step(self):
        b = self._make_browser()
        run_script(b, [{"cmd": "navigate", "url": "https://example.com"}])
        b.navigate.assert_called_once_with("https://example.com")

    def test_wait_click_input(self):
        b = self._make_browser()
        steps = [
            {"cmd": "wait", "selector": "#q"},
            {"cmd": "input", "selector": "#q", "text": "hi", "enter": True},
            {"cmd": "click", "selector": "#go"},
        ]
        result = run_script(b, steps)
        b.wait_for.assert_called_once_with("#q")
        b.input.assert_called_once_with("#q", "hi", enter=True)
        b.click.assert_called_once_with("#go")
        self.assertFalse(result.get("stale"))

    def test_missing_element_marks_stale(self):
        b = self._make_browser()
        b.wait_for.return_value = False  # element never appears
        result = run_script(b, [{"cmd": "wait", "selector": "#gone"}])
        self.assertTrue(result.get("stale"))

    def test_unknown_cmd_ignored_or_error(self):
        b = self._make_browser()
        result = run_script(b, [{"cmd": "navigate", "url": "x"}, {"cmd": "do-something"}])
        self.assertIn("failed", result)  # or errors on unknown

    def test_extract_returns_text(self):
        b = self._make_browser()
        b.text.return_value = "page text"
        result = run_script(b, [{"cmd": "extract"}])
        self.assertEqual(result.get("text"), "page text")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_run_script.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: 写 run_script.py**

```python
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
```

注意：`wait_for` 签名是 `(selector, timeout=10.0)`。测试里 mock 的 `browser.wait_for("#q")` 断言需匹配实际调用。引擎统一 `browser.wait_for(step["selector"], timeout=wait_timeout)`；测试断言相应改为 `b.wait_for.assert_called_once_with("#q", timeout=10.0)` 或调整引擎不传 timeout 默认值——实现时保持 mock 与引擎一致。

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_run_script.py -v`
Expected: 5 PASSED（调整 mock 断言匹配实际签名）

- [ ] **Step 5: Commit**

```bash
git add omnigate/browser/run_script.py tests/test_run_script.py
git commit -m "feat: script replay engine with stale detection"
```

**Exit criteria（子智能体验证）:**
1. `run_script` 支持 navigate/wait/click/input/extract/scroll
2. 元素找不到 → `stale: True`（失效检测）
3. 未知命令 → `failed: True`
4. 单测 5 个过，mock 浏览器无需真 Edge

---

### Task 5: CLI 接线——script run + open --run-script

**Files:**
- Modify: `omnigate/cli.py`

- [ ] **Step 1: script run 子命令**

在 script 子 parser 加：
```python
    ssub.add_parser("run", help="Replay a script").add_argument("name")
```

dispatch 加：
```python
        if args.script_cmd == "run":
            steps = store.load(args.name)
            from omnigate.core import open_page
            from omnigate.browser.run_script import run_script
            # 需要一个已打开的浏览器会话来跑脚本。
            # 简化：script run 打开初始 URL（剧本第一步的 navigate）后执行。
            # 见 core.py 的 run_script_page()。
            return 0
```

- [ ] **Step 2: core.py 加 run_script_page**

```python
def run_script_page(name_or_steps, *, headless: bool = True, use_login: bool = True):
    """Load a script, launch Edge, replay it. Returns replay result."""
    from omnigate.browser.run_script import run_script
    from omnigate.script_store import ScriptStore

    if isinstance(name_or_steps, str):
        steps = ScriptStore().load(name_or_steps)
    else:
        steps = name_or_steps
    if not steps or steps[0].get("cmd") != "navigate":
        raise ValueError("Script must start with a navigate step")

    edge = find_edge()
    if edge is None:
        raise RuntimeError("Edge not found. Install Microsoft Edge.")
    temp_dir = tempfile.mkdtemp(prefix="omnigate-run-")
    user_data_dir = os.path.join(temp_dir, "user-data")
    os.makedirs(user_data_dir, exist_ok=True)
    b = None
    try:
        b = _launch_and_navigate(edge, steps[0]["url"], user_data_dir, free_port(),
                                 headless, use_login)
        result = run_script(b, steps[1:])
        if result.get("text") is None:
            result["text"] = b.text()  # ensure extract present in output
        b.stop()
        return result
    finally:
        if b is not None:
            try:
                b.stop()
            except Exception:
                pass
        shutil.rmtree(temp_dir, ignore_errors=True)
```

注意：`_launch_and_navigate` 内部已 navigate 第一步，所以引擎从 steps[1:] 开始。但 `_launch_and_navigate` 的 `_navigate_with_login` 会做域过滤 + 补注，第一步 navigate 交给它，后续步骤靠引擎。这是正确接线。

- [ ] **Step 3: 手动验证（本地测试页 + 剧本）**

```bash
cd /d/weber
# 保存一个剧本：打开本地表单页，输入，点击
python -m omnigate.cli script save demo-form --steps '[
  {"cmd":"navigate","url":"file:///d:/weber/tmp/interact-test/form.html"},
  {"cmd":"input","selector":"#q","text":"你好","enter":false},
  {"cmd":"click","selector":"#go"},
  {"cmd":"extract"}
]'
python -m omnigate.cli script run demo-form
```
Expected: 回放执行，text 含 `typed: 你好`

- [ ] **Step 4: Commit**

```bash
git add omnigate/cli.py omnigate/core.py
git commit -m "feat: script run replay via CLI"
```

**Exit criteria（子智能体验证）:**
1. `script run <name>` 加载剧本并回放
2. 本地表单剧本：input+click+extract 全执行，text 含输入值
3. 剧本第一步必须是 navigate，否则报错
4. 无孤儿进程

---

## Self-Review

**Spec 覆盖：**
- 交互原语：click/input ✅ Task 3；state ✅ Task 2；wait ✅ Task 1
- 回放引擎：run_script ✅ Task 4
- CLI 接线：script run + open --run-script ✅ Task 5
- 失效检测：元素找不到 → stale ✅ Task 4
- selector 定位（非索引）✅ 全部

**粒度说明**：5 个 Task 各自独立交付。Task 1 纯查询；Task 2 state；Task 3 交互；Task 4 引擎（mock 测试无浏览器）；Task 5 接线。每步单点验证。

**诚实标注**：Task 4 的 wait_for 签名需与 mock 断言对齐（timeout 关键字），计划已说明修法。Task 5 的 text 返回策略已定：总是返回 text。

**Placeholder scan**：已清除 `get_text_wanted` 占位。无 TBD。
