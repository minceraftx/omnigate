# omnigate 双模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 scripts/（剧本库）+ lessons/（教训库）+ 渐进式披露。让模型"用过一次就会"——试错经验沉淀，重复网站不重复踩坑。

**Architecture:** 三层架构：
1. **脚本命令**（omnigate CLI 执行）
2. **模型规章**（SKILL.md 规则）
3. **模型探索**（lessons/ 教训积累）

剧本 = A 型（命令序列 JSON），教训文件 = 模型试错后写的网站经验。SKILL.md 渐进式披露——只写"有这些文件，用某网站前自己读对应文件"，不塞全部内容。**内容由模型维护，代码只建结构 + 引导。**

**Tech Stack:** Python 3.13。文件结构为主，代码量少。

---

## 文件结构

```
omnigate/
├── __init__.py
├── cli.py                  ← 加 script 子命令（list/run/delete）
├── scripts/                ← 新增：剧本库（模型维护）
│   └── .gitkeep
├── lessons/                ← 新增：教训库（模型维护）
│   └── .gitkeep
└── script_store.py         ← 新增：剧本存取逻辑
```

---

### Task 1: scripts/ 和 lessons/ 目录 + .gitkeep

**Files:**
- Create: `omnigate/scripts/.gitkeep`
- Create: `omnigate/lessons/.gitkeep`

- [ ] **Step 1: 建目录**

```bash
mkdir -p omnigate/scripts omnigate/lessons
touch omnigate/scripts/.gitkeep omnigate/lessons/.gitkeep
```

- [ ] **Step 2: Commit**

```bash
git add omnigate/scripts/.gitkeep omnigate/lessons/.gitkeep
git commit -m "feat: scripts and lessons directories"
```

**Exit criteria（子智能体验证）:**
1. `omnigate/scripts/` 和 `omnigate/lessons/` 存在
2. .gitkeep 已跟踪，目录进 git

---

### Task 2: script_store.py 剧本存取

**Files:**
- Create: `omnigate/script_store.py`
- Create: `tests/test_script_store.py`

- [ ] **Step 1: 写失败测试**

```python
"""Unit tests for script store (no browser needed)."""
import os
import tempfile
import unittest

from omnigate.script_store import ScriptStore


class TestScriptStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="omni-script-")
        self.store = ScriptStore(self.tmp)

    def test_save_and_list(self):
        self.store.save("bilibili-summary", [{"cmd": "navigate", "url": "https://bilibili.com"}])
        names = self.store.list_names()
        self.assertIn("bilibili-summary", names)

    def test_load_roundtrip(self):
        steps = [{"cmd": "navigate", "url": "x"}, {"cmd": "extract", "field": "text"}]
        self.store.save("t", steps)
        loaded = self.store.load("t")
        self.assertEqual(loaded, steps)

    def test_delete(self):
        self.store.save("t", [{"cmd": "navigate", "url": "x"}])
        self.store.delete("t")
        self.assertNotIn("t", self.store.list_names())

    def test_missing_raises(self):
        with self.assertRaises(KeyError):
            self.store.load("does-not-exist")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_script_store.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: 写 script_store.py**

```python
"""Script store: save/load/delete named command-sequence scripts (JSON).

Scripts live in omnigate/scripts/<name>.json. A script is a list of command
dicts, e.g. [{"cmd": "navigate", "url": "..."}, {"cmd": "extract", "field": "text"}].
Content is maintained by the model (recorded from successful improv runs);
this module only handles persistence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


class ScriptStore:
    def __init__(self, scripts_dir: str | None = None):
        default = Path(__file__).parent / "scripts"
        self.dir = Path(scripts_dir) if scripts_dir else default
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, steps: list[dict]) -> Path:
        """Save a script. Sanitizes name to a safe filename."""
        safe = "".join(c for c in name if c.isalnum() or c in "-_").strip()
        if not safe:
            raise ValueError(f"Invalid script name: {name}")
        path = self.dir / f"{safe}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(steps, f, ensure_ascii=False, indent=2)
        return path

    def load(self, name: str) -> list[dict]:
        path = self.dir / f"{name}.json"
        if not path.exists():
            raise KeyError(f"Script not found: {name}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def list_names(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.json"))

    def delete(self, name: str) -> None:
        path = self.dir / f"{name}.json"
        if path.exists():
            path.unlink()
        else:
            raise KeyError(f"Script not found: {name}")
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_script_store.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add omnigate/script_store.py tests/test_script_store.py
git commit -m "feat: script store for command-sequence scripts"
```

**Exit criteria（子智能体验证）:**
1. `python -m pytest tests/test_script_store.py -v` → 4 passed
2. save/load/list/delete 全通，roundtrip 一致
3. 脚本文件名安全化（非法字符清理）
4. 纯文件操作，无浏览器依赖

---

### Task 3: cli.py 加 script 子命令

**Files:**
- Modify: `omnigate/cli.py`

- [ ] **Step 1: 加 script 子命令（list/save/load/delete）**

```python
    p = sub.add_parser("script", help="Manage command-sequence scripts")
    ssub = p.add_subparsers(dest="script_cmd", required=True)
    ssub.add_parser("list", help="List scripts")
    ssub.add_parser("show", help="Show a script").add_argument("name")
    ssub.add_parser("save", help="Save steps from --steps JSON").add_argument("name")
    ssub.add_parser("delete", help="Delete a script").add_argument("name")
    p.add_argument("--steps", default=None, help="JSON array of steps for save")
```

dispatch:
```python
    if args.command == "script":
        from omnigate.script_store import ScriptStore
        store = ScriptStore()
        if args.script_cmd == "list":
            for name in store.list_names():
                print(name)
            return 0
        if args.script_cmd == "show":
            import json
            print(json.dumps(store.load(args.name), ensure_ascii=False, indent=2))
            return 0
        if args.script_cmd == "save":
            if not args.steps:
                print("ERROR: --steps required for save", file=__import__("sys").stderr)
                return 1
            import json
            steps = json.loads(args.steps)
            store.save(args.name, steps)
            print(f"saved: {args.name}")
            return 0
        if args.script_cmd == "delete":
            store.delete(args.name)
            print(f"deleted: {args.name}")
            return 0
```

- [ ] **Step 2: 手动验证**

```bash
python -m omnigate.cli script save demo --steps '[{"cmd":"navigate","url":"https://example.com"}]'
python -m omnigate.cli script list
python -m omnigate.cli script show demo
python -m omnigate.cli script delete demo
python -m omnigate.cli script list
```
Expected: save→list 有 demo→show 显示 JSON→delete→list 空

- [ ] **Step 3: Commit**

```bash
git add omnigate/cli.py
git commit -m "feat: script CLI subcommands"
```

**Exit criteria（子智能体验证）:**
1. script list/save/show/delete 四个子命令工作
2. save 需要 --steps，缺了报错 exit 1
3. 脚本存到 omnigate/scripts/

---

### Task 4: SKILL.md 渐进式披露 + lessons 引导

**Files:**
- Modify: `C:\Users\Administrator\.claude\skills\omnigate\SKILL.md`
- Modify: `d:\weber\.claude\skills\omnigate\SKILL.md`（项目镜像）

- [ ] **Step 1: SKILL.md 加"经验记忆"章节**

在 SKILL.md 加：
```markdown
## Experience Memory (渐进式披露)

omnigate 有脚本库和教训库，用网站前先读：

- `omnigate/scripts/` — 剧本（命令序列 JSON）。已存该网站的剧本先看/复用。
- `omnigate/lessons/<site>.md` — 该网站的教训（反爬、验证码、提取技巧）。

规则：
1. 用某网站前，先读 `lessons/<site>.md`（存在的话），再决定怎么操作。
2. 遇到新坑（验证码、反爬、解析失败）并解决后，把经验追加到 `lessons/<site>.md`。
3. 跑通一个新任务的步骤序列，存成 `omnigate script save <site>-<task> --steps '[...]'`。
4. 复用已有剧本时，如果失败（网页改版），更新教训 + 重存剧本。

教训文件格式（lessons/<site>.md）：
```markdown
# <site>
## 坑
- 描述 + 解法
## 技巧
- 该站特有的有效做法
```
```

- [ ] **Step 2: 同步两个 SKILL.md**

复制用户级到项目级：
```bash
cp "C:\Users\Administrator\.claude\skills\omnigate\SKILL.md" "d:\weber\.claude\skills\omnigate\SKILL.md"
```

- [ ] **Step 3: Commit**

```bash
cd /d/weber && git add .claude/skills/omnigate/SKILL.md
git commit -m "feat: progressive disclosure + experience memory in skill"
```

**Exit criteria（子智能体验证）:**
1. SKILL.md 含 "Experience Memory" 章节，规则 1-4 明确
2. 规则指导模型：用网站前读 lessons、遇新坑记录、跑通存剧本、剧本失效更新
3. 用户级和项目级 SKILL.md 一致
4. 教训文件格式定义清晰

---

## Self-Review

**Spec 覆盖：**
- scripts/ 剧本库（A 型命令序列）✓ Task 1-3
- lessons/ 教训库 ✓ Task 1, 4
- 渐进式披露（SKILL.md 只指路不塞内容）✓ Task 4
- 三层架构（命令+规章+探索）✓ 全部
- 内容由模型维护 ✓（代码只建结构+引导）

**粒度说明**：4 个 Task 各自独立。Task 1 目录；Task 2 存取逻辑；Task 3 CLI；Task 4 skill 披露。每步单点验证。

**Placeholder scan**：无 TBD。所有代码完整。
