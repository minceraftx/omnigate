# omnigate 反爬层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完善 omnigate 的真实登录态链路，并加入"无头被拒自动转有头"重试。

**Architecture:** 反爬层靠真实 Edge 登录态（已实现 cookie 导出+注入）。本轮补两件事：① `doctor` 命令检测环境（Edge 可执行、调试端口、登录态可用性），让"为什么没登录"一目了然；② `open` 命令无头加载失败时自动转 headed 重试一次（探测性，不等验证码特征）。

**Tech Stack:** Python 3.13, CDP, Edge 150。

**环境事实（已验证）：**
- Edge 在 `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`
- 真实 Edge 需 `--remote-debugging-port=9222` 才能被注入登录态
- 物理 profile 复制不可靠（Windows 锁+加密），登录态走 CDP 导出注入

---

## 文件结构

```
omnigate/
├── cli.py              ← 加 doctor 命令
├── core.py             ← open 加转有头重试
├── browser/
│   ├── edge.py         ← 已有 find_edge
│   ├── cookies.py      ← 已有 find_debug_port
│   └── actions.py      ← 已有 BrowserSession
└── doctor.py           ← 新增：环境诊断
```

---

### Task 1: doctor 命令——环境诊断

**Files:**
- Create: `omnigate/doctor.py`
- Modify: `omnigate/cli.py`

- [ ] **Step 1: 写 doctor.py**

```python
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
    """Format diagnosis as human/AI-readable text."""
    lines = []
    lines.append(f"Edge executable: {'✓ ' + d['edge_path'] if d['edge_found'] else '✗ NOT FOUND'}")
    lines.append(f"Edge profile dir: {'✓ ' + d['profile_dir'] if d['profile_dir_found'] else '✗ NOT FOUND'}")
    if d["debug_port_found"]:
        lines.append(f"Login-state source: ✓ debug port {d['debug_port']}")
        lines.append("  → omnigate open 将注入你的 Edge 登录态")
    else:
        lines.append("Login-state source: ✗ no Edge with --remote-debugging-port found")
        lines.append("  → 页面将以未登录状态打开")
        lines.append("  → 要复用登录态，用此命令启动 Edge：")
        lines.append("    msedge.exe --remote-debugging-port=9222")
    return "\n".join(lines)
```

- [ ] **Step 2: cli.py 加 doctor 子命令**

在 `main()` 里 subparsers 定义处加：
```python
    sub.add_parser("doctor", help="Check environment: Edge, login-state source")
```

dispatch 处加：
```python
    if args.command == "doctor":
        from omnigate.doctor import diagnose, report
        print(report(diagnose()))
        return 0
```

- [ ] **Step 3: 手动验证**

Run: `python -m omnigate.cli doctor`
Expected: 显示 Edge 可执行 ✓、profile 目录 ✓、debug port 状态（当前无 → ✗ 并提示启动命令）

- [ ] **Step 4: Commit**

```bash
git add omnigate/doctor.py omnigate/cli.py
git commit -m "feat: doctor command for environment diagnostics"
```

**Exit criteria（子智能体验证）:**
1. `python -m omnigate.cli doctor` 运行无报错
2. 输出含 Edge executable 状态、profile dir、debug port 三项
3. 无 debug port 时提示 `--remote-debugging-port=9222` 启动命令
4. doctor.py 不启动任何浏览器（纯检测）

---

### Task 2: open 无头被拒自动转有头重试

**Files:**
- Modify: `omnigate/core.py`

- [ ] **Step 1: 加"加载成功"判定 helper**

在 core.py 加：
```python
def _page_loaded(b: "BrowserSession") -> bool:
    """A page is 'loaded enough' if it has a non-empty title OR body text."""
    try:
        title = b.title().strip()
        if title:
            return True
        text = b.text().strip()
        return bool(text)
    except Exception:
        return False
```

- [ ] **Step 2: open_page 加转有头重试**

修改 `open_page` 中 navigate 后：
```python
        b.navigate(url)
        # Retry once in headed mode if the headless page didn't load
        # (some sites reject headless; a real window is less suspicious).
        if headless and not _page_loaded(b):
            b.stop()
            b = BrowserSession(edge, free_port(), user_data_dir, headless=False)
            b.start()
            if use_login:
                try:
                    cookies = export_cookies_from_running_edge()
                    inject_cookies(b._require_session(), cookies)
                except RuntimeError:
                    pass
            b.navigate(url)
```

注意：`b` 变量在 try 块里被重新赋值，`finally` 里 `b.stop()` 需能引用新实例——检查现有结构。

- [ ] **Step 3: 手动验证**

Run: `python -m omnigate.cli open "https://example.com" --text`
Expected: 无头正常加载 → 不触发重试，输出 TITLE/TEXT

Run: `python -m omnigate.cli open "https://example.com" --headed`
Expected: 有头模式直接工作（headless=False 时 `if headless and not _page_loaded` 为 False，不重试）

- [ ] **Step 4: 验证转有头逻辑（mock 空页）**

临时脚本验证 `_page_loaded` 逻辑：
```bash
python -c "
from omnigate.core import _page_loaded
# 无真实浏览器，验证函数在空输入下返回 False 的逻辑分支
# 实际断言：title 为空时返回 False
"
```
（若 `_page_loaded` 需真实浏览器难测，则确认重试分支代码结构正确，用子智能体 code review 验证。）

- [ ] **Step 5: Commit**

```bash
git add omnigate/core.py
git commit -m "feat: auto-retry headed when headless page fails to load"
```

**Exit criteria（子智能体验证）:**
1. `open` 正常页面无头加载，不触发重试
2. headless=False 时不重试
3. 重试逻辑：无头加载失败 → 停止 → 有头重启 → 重新注入登录态 → 重导航
4. finally 清理逻辑对重试后的实例仍正确（无孤儿进程）
5. 代码 review 确认 `_page_loaded` 判定合理

---

## Self-Review

**Spec 覆盖：**
- 反爬 = 登录态完善 + 转有头重试 ✓（Task 1 doctor 诊断登录态，Task 2 转有头）
- 不注入反检测脚本 ✓（决策明确排除）
- 不承诺过 Cloudflare ✓（准出只测流程决策）

**粒度说明**：两个 Task 各自独立交付、独立验证。Task 1 纯检测零风险；Task 2 是 open 的小改动。

**Placeholder scan**：无 TBD。Task 2 Step 4 的 `_page_loaded` 单测困难已诚实标注，改用 code review 兜底。
