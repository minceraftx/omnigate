# omnigate 安全修复任务书（2026-08-08）

> 来源：2026-08-08 全量安全扫描（静态模式扫描 + 全源文件人工审查 + 依赖 CVE 核对）。
> 本文件面向执行修复的开发 AI：每项含位置、证据、根因、修法、功能变化与验证方法。
> **先读第 1、2 节再动手。**

## 1. 背景与威胁模型

omnigate 是供 AI 代理调用的浏览器自动化 CLI（驱动 Edge、复用登录态、音视频转写）。
因此威胁模型与普通库不同，按优先级：

1. **本机其他进程/恶意网页连接无鉴权 CDP 端口**，窃取注入后的会话 Cookie。
2. **被提示词注入或犯错的 AI 调用方**滥用 CLI 参数读本地文件、覆盖文件、穿越脚本目录。
3. 临时 profile（含注入的 Cookie）清理失败残留磁盘。
4. 依赖声明过宽导致全新安装落到含 CVE 的版本。

**明确非目标**：Cookie 导出复用是对抗反爬登录墙的核心功能，不裁剪该能力本身（见决策 D1）。

## 2. 已确认的决策（勿越界）

| 编号 | 决策 | 含义 |
|---|---|---|
| D1（2026-08-08 修订） | F-02 Cookie 注入：**采纳选择性注入（方案 1+2）** | 按 FIX-07 实施：导出侧保持全量、注入侧按导航目标域过滤 + 落地补注，新增 `--full-login` 兜底。**禁止**在导出侧按域过滤（落地补注依赖全量快照）。 |
| D2 | F-04 URL 协议白名单：**维持现状** | open 继续接受任意 URL（含 file://），只做 README 标注（DOC-02）。**禁止**加 scheme 白名单。 |
| D3 | F-05 截图路径：**限制在工作目录内** | 按 FIX-03 实施。 |
| 其余 | F-01 / F-03 / F-06 / F-07 / F-08 全部修复 | 均为零功能变化或已确认的变化，按 FIX-01/02/04/05/06 实施。 |

## 3. 代码修复项

### FIX-01 ｜ F-01：CDP 调试端口去除 `--remote-allow-origins=*`（高危）

**位置**：`omnigate/browser/edge.py` `build_launch_args()`；`omnigate/browser/cdp.py` `CdpSession.connect()`；`tests/test_edge.py:28`。

**根因**：`--remote-allow-origins=*` 关闭了 Chrome 111+ 对调试 WebSocket 的 Origin 校验，本机任意进程、乃至任意网页（经浏览器内 WebSocket / DNS rebinding）都能连上调试端口执行任意 CDP 命令（读页面、跑 JS、`Network.getAllCookies` 导出全部 Cookie）。

**关键技术事实（已验证）**：websocket-client 默认会从 ws URL 派生并发送 `Origin: http://host:port` 头（见已安装包 `_handshake.py` 的 `suppress_origin` 分支），所以当初不得不加 `=*`。而 Chrome 对**不带 Origin 头**的非浏览器客户端连接是放行的——让 websocket-client 不发 Origin 即可两头兼顾。

**修法**：

1. `edge.py` `build_launch_args()`：删除 `"--remote-allow-origins=*",` 一行，其余参数不动。
2. `cdp.py` `connect()`：

   ```python
   def connect(self) -> None:
       # suppress_origin: websocket-client 默认发送派生 Origin 头，会被 Chrome 的
       # Origin 校验拒绝；不带 Origin 的非浏览器客户端连接则被放行。
       self._ws = websocket.create_connection(
           self.ws_url, timeout=self.timeout, suppress_origin=True
       )
   ```

3. `tests/test_edge.py` `test_includes_required_flags`：第 28 行 `assertIn("--remote-allow-origins=*", ...)` 改为：

   ```python
   self.assertNotIn("--remote-allow-origins", joined)
   ```

**功能变化**：无。omnigate 自身连接路径不变；仅浏览器页面/其他 origin 的 WS 客户端无法再连调试端口。

**验证**：`pytest` 全绿；手动 `omnigate open https://example.com --text` 正常返回标题与正文（覆盖 headless 连接、cookie 注入失败回退、页面读取全链路）。

---

### FIX-02 ｜ F-03：ScriptStore `load`/`delete` 路径遍历（中危）

**位置**：`omnigate/script_store.py`。

**证据/根因**：`save()` 消毒文件名（第 22 行），但 `load()`（31 行）/`delete()`（41 行）直接 `self.dir / f"{name}.json"`。传 `name="../../x"` 可读/删 scripts 目录外任意 `.json` 文件。当前读写不对称还导致 `save("my script")` 写的是 `myscript.json`，而 `load("my script")` 按原名找不到——统一消毒同时修复这个一致性缺陷。

**修法**：

1. 抽出共享消毒逻辑，三个方法统一使用：

   ```python
   @staticmethod
   def _safe_name(name: str) -> str:
       """Sanitize a script name to a safe filename stem (save/load/delete 共用)."""
       safe = "".join(c for c in name if c.isalnum() or c in "-_").strip()
       if not safe:
           raise ValueError(f"Invalid script name: {name}")
       return safe
   ```

2. `save()` 改用 `_safe_name(name)`（行为不变）。
3. `load()`/`delete()`：

   ```python
   def load(self, name: str) -> list[dict]:
       path = (self.dir / f"{self._safe_name(name)}.json").resolve()
       if path.parent != self.dir.resolve():
           raise ValueError(f"Invalid script name: {name}")
       if not path.exists():
           raise KeyError(f"Script not found: {name}")
       with open(path, encoding="utf-8") as f:
           return json.load(f)
   ```

   `delete()` 同构。resolve 校验是纵深防御（消毒后理论上不可能穿越），保留。

**功能变化**：`load`/`delete` 对含空格等特殊字符的名字按与 `save` 相同的规则归一化——属行为对齐，无回归。

**验证**：`pytest`；新增用例：`store.load("../../secret")` 抛 `ValueError` 或 `KeyError` 且不触及目录外文件；`store.delete("../x")` 不删除目录外文件；save→load→show→delete 正常名字往返。

---

### FIX-03 ｜ F-05：`--screenshot` 输出限制在工作目录内（中危，决策 D3）

**位置**：`omnigate/core.py` `open_page()`（154-156 行附近）。

**证据/根因**：`os.makedirs(os.path.dirname(screenshot) or ".", exist_ok=True)` + `open(path, "wb")` 直接写调用方路径，可建目录并覆盖任意可写文件。

**修法**：

1. `core.py` 增加：

   ```python
   def _resolve_output_path(path: str) -> str:
       """Resolve an output path, refusing anything outside the current working directory.

       realpath 同时消除 .. 与符号链接；不同盘符自然不满足前缀条件。
       """
       base = os.path.realpath(os.getcwd())
       target = os.path.realpath(path)
       if target != base and not target.startswith(base + os.sep):
           raise ValueError(f"Output path must be inside the working directory: {path}")
       return target
   ```

2. screenshot 分支改为：`shot = _resolve_output_path(screenshot)` 后再 `makedirs` + `b.screenshot(shot)`，`result["screenshot"]` 记录解析后路径。
3. CLI 无需改动：`ValueError` 向上抛出即可（与现有 RuntimeError 风格一致）。

**功能变化（已向用户确认）**：`--screenshot C:\other\x.png`、`--screenshot ..\x.png` 会被拒绝；cwd 内的相对/绝对路径不受影响（含现有的 `tmp/t2.png` 用法）。`--screenshot` 缺省（None）不受影响。

**验证**：新用例：cwd 内相对路径通过；`../x.png`、绝对路径出 cwd 抛 `ValueError`。手动：`omnigate open https://example.com --screenshot tmp/sec.png` 成功。

---

### FIX-04 ｜ F-06：`free_port()` TOCTOU 竞态加固（低危）

**位置**：`omnigate/browser/actions.py` `BrowserSession.start()`；`omnigate/core.py`。

**根因**：`cdp.py free_port()` 绑定 0 端口取号后即关闭 socket，Edge 稍后才绑定；窗口期端口可能被其他进程抢占，导致连上非 CDP 服务并以其为浏览器驱动。

**修法**：

1. `actions.py start()` 现有轮询拿到 `version` 后、开 tab 前加身份校验：

   ```python
   browser = (version or {}).get("Browser", "")
   if "Edge" not in browser:
       raise RuntimeError(
           f"Port {self.port} answered but is not Edge (Browser={browser!r})"
       )
   ```

2. `core.py`：`_launch_and_navigate` 抛出上述启动异常时，换 `free_port()` 重试一次（沿用现有 headed 回退的模式：stop 旧实例 → 新端口 → 重建）。注意保持"失败不残留孤儿进程"的现有保证。

**功能变化**：无。仅极端竞态下从"静默连错服务"变为"换端口重试/明确报错"。

**验证**：`pytest`；可用 mock 单测：`/json/version` 返回非 Edge 的 Browser 字段时 start 抛错。

---

### FIX-05 ｜ F-07：临时 profile 清理失败告警 + 启动时清残留（低危）

**位置**：`omnigate/core.py` `open_page()` finally 块（165 行附近）。

**根因**：`shutil.rmtree(temp_dir, ignore_errors=True)` 静默吞错；注入了会话 Cookie 的临时 profile 可能长期残留 `%TEMP%`。

**修法**：

1. finally 块改为显式告警：

   ```python
   try:
       shutil.rmtree(temp_dir)
   except OSError as exc:
       print(f"[omnigate] warning: temp profile cleanup failed: {temp_dir} ({exc})",
             file=sys.stderr)
   ```

2. 新增 `_cleanup_stale_temp_dirs(max_age_hours: float = 24)`：遍历 `tempfile.gettempdir()` 下 `omnigate-run-*` / `omnigate-profile-*` 目录，mtime 超过阈值的 best-effort `shutil.rmtree`（单个失败跳过，不 follow 符号链接）；在 `open_page()` 开头调用。24h 窗口是为了不误删并行运行中的其他 omnigate 实例。

**功能变化**：无。仅多了 stderr 告警与惰性垃圾回收。

**验证**：新用例：构造超期假目录被清、未超期保留；rmtree 抛错时只告警不抛出。

---

### FIX-06 ｜ F-08：收紧依赖声明下界（低危）

**位置**：`pyproject.toml`。

**修法**：

```toml
dependencies = [
    "websocket-client>=1.9",
    "requests>=2.32.4",
]

[build-system]
requires = ["setuptools>=78.1.1"]
```

**根因**：`requests>=2.28` 允许全新安装落到受 CVE-2024-35195 / CVE-2024-47081 影响的 2.31.x；`setuptools>=68` 同理（CVE-2025-47273 修于 78.1.1）。当前环境（requests 2.32.4 / setuptools 78.1.1）已满足新下界，零安装影响。

**验证**：`pip install -e .` 不重装/降级任何包。

---

### FIX-07 ｜ F-02：按导航目标过滤注入 Cookie + 落地补注（高危，决策 D1 修订）

**位置**：`omnigate/browser/cookies.py`、`omnigate/browser/actions.py`、`omnigate/core.py`、`omnigate/cli.py`、`tests/`（新增用例）。

**根因**：`Network.getAllCookies` 全量导出真实 Edge 所有站点 Cookie，并默认（`use_login=True`）全部注入自动化实例的临时 profile——注入面、落盘残留面、被恶意页面利用面都过宽。

**设计要点（方案 1+2，已向用户确认）**：

- **导出侧保持全量**（数据源不变，无需任何"预判分类"）；
- **注入侧按导航目标过滤**：每次导航前只注入目标域子集。匹配方向是"Cookie 域是不是目标 host 的祖先域"，只需后缀比较，**不需要 eTLD+1 / public-suffix 计算**；
- **落地补注**：导航后读最终 `location.href`，被 302 到其他域（典型 SSO 跳转）时对新域补注并 reload 一次；
- `--full-login` 一键恢复现状（全量注入），兜底 SSO 等异常场景。

**背景技术事实（已验证，勿走弯路）**：CDP `Network.setCookies` 写的是浏览器 Cookie 库，**启动后任意时刻可注入**，导航之后也可补注（reload 即生效），无需重启实例。现有代码本来就是"先 start 后 inject"。

**修法**：

1. `cookies.py` 新增过滤函数：

   ```python
   from urllib.parse import urlparse

   def cookies_for_url(cookies: list[dict[str, Any]], url: str) -> list[dict[str, Any]]:
       """Return the subset of cookies applicable to the URL's host.

       匹配方向：cookie domain == host，或 cookie domain 是 host 的祖先域
       （'.bilibili.com' 覆盖 www/passport/api.bilibili.com）。
       反向不匹配（子域 cookie 不发给父域）；异名域（evilbilibili.com）不匹配。
       """
       host = urlparse(url).hostname or ""
       return [
           c for c in cookies
           if host == (d := str(c.get("domain", "")).lstrip("."))
           or host.endswith("." + d)
       ]
   ```

2. `core.py` 新增编排函数（一次导出、按需多次注入；注入失败沿用现有"降级为未登录"的容错）：

   ```python
   def _navigate_with_login(b, url: str, full_login: bool) -> None:
       """Inject domain-scoped cookies, navigate, top-up on cross-domain landing.

       full_login=True：全量注入（现状行为），无需补注。
       默认：先注入 url 目标域子集再导航；落地 host 变化时补注新域并 reload 一次。
       """
       import time as _time
       from urllib.parse import urlparse
       from omnigate.browser.cookies import (
           cookies_for_url, export_cookies_from_running_edge, inject_cookies,
       )

       cookies = export_cookies_from_running_edge()

       def _inject(target_url: str) -> int:
           subset = cookies if full_login else cookies_for_url(cookies, target_url)
           return inject_cookies(b._require_session(), subset)

       _inject(url)
       b.navigate(url)
       if full_login:
           return
       try:
           resp = b._require_session().send(
               "Runtime.evaluate", {"expression": "location.href", "returnByValue": True}
           )
           landed = resp["result"]["result"].get("value") or ""
       except Exception:
           return  # 读不到落点就不补，保持原行为
       if urlparse(landed).hostname and urlparse(landed).hostname != urlparse(url).hostname:
           _inject(landed)
           b._require_session().send("Page.reload", {})
           _time.sleep(2)
   ```

3. `core.py` 接线：`_launch_and_navigate()` 与 `_solve_captcha_popup()` 中的 `inject_cookies(...)` / `b.inject_login()` 调用点，在 `use_login` 时统一改走 `_navigate_with_login(b, url, full_login)`；`open_page()` 签名加 `full_login: bool = False` 并透传。注意保持"失败不残留孤儿进程"的现有保证。
4. `cli.py` `open` 子命令加参数并透传：

   ```python
   p.add_argument("--full-login", action="store_true",
                  help="注入全量 Cookie（默认只注入目标站点域；跨域 SSO 站点用此项）")
   ```

5. `actions.py` `inject_login()` 可保留原签名作兼容包装，或改为委托给 core 的编排——二选一，保持只有一个注入入口。

**功能变化（已向用户确认）**：

- 默认注入从"全量"变为"目标域子集"：bilibili/youtube/douyin 等单域目标站行为不变；依赖跨域 SSO（如 Google 账号登录第三方站）的站点登录态可能不完整，需 `--full-login`。
- 全量 Cookie 只在内存中转，不再写入临时 profile——落盘残留面（配合 FIX-05）与页面可利用面消除。
- `--no-login` 语义不变；`use_login` 默认值不变。

**已知限制（诚实记录）**：SSO 跳转链的**中间站** Cookie 不会被携带（补注只覆盖最终落点）；跳转链复杂的站点直接用 `--full-login`。Cookie 快照时效与现状相同，不引入新问题。

**验证**：

- 新单测 `cookies_for_url`：父域 Cookie 匹配子域（`.bilibili.com` → `www.bilibili.com`）；子域 Cookie 不匹配父域（`api.bilibili.com` ↛ `bilibili.com`）；异名域不匹配（`evilbilibili.com` ↛ `www.bilibili.com`）；空 host / 缺 domain 字段不炸。
- 回归：`omnigate open <已登录单域站点> --text` 登录态保留；`--full-login` 行为与修复前一致。
- 集成：本地 302 测试页（A 域跳 B 域）验证落地补注 + reload 只发生一次。

## 4. 仅文档标注项（决策 D2，不改代码）

### DOC-01 ｜ F-02：README 安全模型标注（随 FIX-07 落地更新）

README 新增「安全模型 / Security Model」小节，要点：

- omnigate 经 CDP `Network.getAllCookies` 导出运行中 Edge 的全部 Cookie 作为登录态源；**默认只把与目标站点同域的 Cookie 注入自动化实例**（FIX-07），跨域 SSO 站点可用 `--full-login` 恢复全量注入。
- 登录态源（`--remote-debugging-port=9222` 的 Edge）无鉴权、面向本机所有进程：**建议用一个独立的 Edge profile 专门做登录态源**（只登录自动化需要的站点），不要让日常主浏览器常驻调试端口。
- 任何能调用 omnigate 的代理仍持有登录态源所登录站点的访问能力，**只把 omnigate 暴露给可信调用方**。
- 自动化实例使用临时 profile，用完即删；清理失败会 stderr 告警（FIX-05）。

### DOC-02 ｜ F-04：open 任意 URL 的风险标注

同一小节追加：

- `open` 接受任意 URL，包括 `file://`（可读本地文件并经 `--text`/`--screenshot` 输出）与内网地址。当前调用方均为有完整本机权限的可信代理，故不加协议白名单；**若未来暴露给无文件权限的受限代理，需先补 scheme 白名单（仅 http/https）再开放**。

## 5. 验收清单

- [ ] `pytest` 全绿（含更新后的 `test_edge.py` 与各 FIX 新增用例）
- [ ] `omnigate doctor` 输出正常
- [ ] `omnigate open https://example.com --text` 正常返回（FIX-01 核心回归）
- [ ] `omnigate open https://example.com --screenshot tmp/sec.png` 成功；`--screenshot ../x.png` 被拒绝（FIX-03）
- [ ] `omnigate script save/load/show/delete` 正常名字往返；`load "../../x"` 被拒（FIX-02）
- [ ] `cookies_for_url` 单测通过；已登录单域站点登录态保留；`--full-login` 行为同修复前（FIX-07）
- [ ] `pip install -e .` 无依赖变动（FIX-06）
- [ ] README 含安全模型小节（DOC-01/DOC-02）

**实施禁区重申**：Cookie 过滤只许发生在**注入侧**——导出侧必须保持全量快照（落地补注依赖它），不得在导出时按域裁剪（D1）；不得给 `open` 加 URL 白名单（D2）。
