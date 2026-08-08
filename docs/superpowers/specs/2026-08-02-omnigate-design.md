# omnigate 设计文档

日期：2026-08-02
状态：已获用户批准

## 一句话定位

omnigate 是一个"浏览器能力库"——给 AI 一套操控真实 Edge 浏览器的 CLI 工具集，附带可选音频转写插件。AI 依据用户需求自主判断怎么用，不做任务分流。

## 背景与技术选型历程

最初设想过"两层架构"：BrowserAct 做破门层 + VideoNote 做消化层。摸底后推翻：

- **BrowserAct 排除**：闭源 PyPI 包（wheel 解包确认核心全是 .pyd 编译二进制），只认 Chrome，且核心反爬（stealth/验证码/代理）全在云端 API。用户机器只有 Edge，无 Chrome，无法使用。
- **Browser Use 研究过**：纯 CDP 开源，但反爬能力几乎为零，且需要 LLM 驱动每个动作（每次操作调一次模型，费 token）。
- **最终选择**：自研轻量 CDP 层，复用 Edge 登录态，只做"浏览器操控工具集"。模型懒加载，不常驻。

## 架构

```
omnigate (CLI 工具集, Python)
│
├── browser/   ← 核心：CDP 操控 Edge
│   ├── 启动：复制 Edge 主档案 → 无头独立实例
│   ├── 操控：open / navigate / click / read / scroll / screenshot
│   └── 提取：get-text / get-markdown
│
├── audio/     ← 可选插件：extract-audio 提取当前页音频 → 接本地 Qwen3 ASR
│
└── cli.py     ← 入口：AI 调用的命令集
```

## 核心决策

### A. 范围：最小闭环 + 双模式骨架
- 不做反爬（JS 层反检测后置）
- 不做验证码兜底（同机弹窗方案后置）
- 先证明"浏览器操控 + 音频提取"两条路都通

### B. 浏览器底座：裸 CDP，不锁死
- 直接发 CDP 命令操控 Edge，零依赖
- 已实测验证：Edge 150 CDP 全链路通（新标签页→导航→截图→读标题）
- 预留双执行器：剧本模式（固定流程）+ 即兴模式（LLM 驱动，后置）

### C. Edge 登录态复用：复制主档案 → 无头独立跑
- 复制用户 Edge 主档案（含 cookie/登录态）到临时目录
- 启动无头独立实例，加载复制来的登录态
- 不跳窗口、不误伤用户正在使用的 Edge、登录态继承
- 用户明确：不建专用 profile，直接复制主档案

### D. 反爬：后置，不排期
- 研究结论：Chromium 上 JS/CDP 层反检测可行（学 Camoufox stealth 思路）
- Edge 内核闭源，C++ 引擎级反检测做不了
- 真实 Edge 登录态 + 真实指纹本身就是最强反爬

### E. 验证码兜底：同机弹窗，后置

参考调研：BrowserAct 用云端 remote-assist URL 移交（因为 headless 跑服务器）；opencli 用 bind 抢用户已开标签。我们全本地，不需要云端 URL，也不用抢用户浏览器——独立实例重启即可。

实现机制（后置，但原理先定）：
```
默认 headless 跑（不打扰用户）
  │
  ├─ 轮询检测卡住：
  │    DOM 特征（iframe[src*=recaptcha/hcaptcha]、#captcha、
  │    Cloudflare challenge）或行为特征（同一步重试 N 次无进展）
  │
  ├─ 触发弹窗：
  │    终止无头实例 → 用同一 user-data-dir 以 headed 重启
  │    （cookie/登录态/页面状态都在档案里，不丢）
  │
  ├─ 用户看到弹出 Edge 窗口，操作验证码
  │
  ├─ AI 轮询：验证码消失（DOM 检测 / URL 变化）
  │
  └─ 恢复：继续任务（档案还在，状态没丢）
```

技术要点：
- CDP 不能原地"无头转有头"，但**重启不丢状态**——`user-data-dir` 存全部 cookie/登录态，重启后重新导航回去
- 检测卡住两层：DOM 特征 + 行为特征（重试无进展）
- 比 BrowserAct 简单：本地一台机器无需远程 URL；比 opencli 简单：独立实例无需抢标签

### F. 音频转写：可选插件，懒加载
- `extract-audio` 从当前页/URL 提取音频
- 接用户本地 Qwen3 ASR（Qwen/Qwen3-ASR-1.7B）
- 模型懒加载——不转写就不加载，不占内存

### G. 入口：纯 CLI + 核心独立
- `omnigate <command> [args]`，AI 敲命令
- 核心逻辑独立成函数，方便以后 skill 化
- 不做 MCP/API（费 token，无必要）

### H. 不分流
- 视频网站照常当普通网页操控（读评论、看内容）
- 音频提取是可选插件，AI 依据需求自己判断是否使用

## 关键技术点

### Edge CDP 启动参数
```
msedge.exe --remote-debugging-port=<port> --remote-allow-origins=* --user-data-dir=<temp_dir>
```
- `--remote-allow-origins=*` 必须（Edge 137+ 否则 WS 握手 403）
- 无头模式加 `--headless=new`

### CDP 调用方式（已验证）
```
GET  /json/version          → 版本/协议确认
PUT  /json/new?about:blank  → 新建标签页（必须 PUT 不是 GET）
WS   /devtools/page/...     → WebSocket 发命令
     Page.navigate          → 导航
     Page.captureScreenshot → 截图
     Runtime.evaluate       → 执行 JS / 读标题
```

### Qwen3 ASR 调用（用户提供代码）
```python
import numpy as np, soundfile as sf, torch
from qwen_asr import Qwen3ASRModel

wav, sr = sf.read("音频.wav", dtype="float32")
if wav.ndim > 1: wav = wav.mean(axis=1)
model = Qwen3ASRModel.from_pretrained(
    "Qwen/Qwen3-ASR-1.7B", dtype=torch.bfloat16,
    device_map="cuda:0", max_inference_batch_size=32, max_new_tokens=1024)
r = model.transcribe(audio=(wav, sr))
print(r[0].text)
```

## 错误处理

- Edge 未安装/无法启动 → 明确报错提示
- CDP 连接失败 → 重试 + 检查端口占用
- 音频提取失败（无音轨/平台限制）→ 报错但不阻塞浏览器操控
- Qwen3 模型加载失败 → 提示检查 CUDA/模型缓存

## 测试策略

- 手动验证为主（用户机器实机测试）
- 浏览器层：开页面 → 截图 → 读文本，三项验证
- 音频层：提取 → 转写 → 输出文本
- 登录态：验证能访问需登录站点

## 项目结构

```
d:\weber\
├── omnigate/
│   ├── __init__.py
│   ├── cli.py          ← CLI 入口
│   ├── core.py         ← 核心逻辑（独立函数）
│   ├── browser/
│   │   ├── __init__.py
│   │   ├── cdp.py      ← CDP 连接与命令
│   │   ├── edge.py     ← Edge 启动/profile 复制
│   │   └── actions.py  ← 高级操作（点击/滚动/提取）
│   └── audio/
│       ├── __init__.py
│       └── transcribe.py  ← 拉流 + Qwen3 转写
├── pyproject.toml
└── README.md
```
