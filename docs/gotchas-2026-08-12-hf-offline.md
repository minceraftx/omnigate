# HF 离线坑：local_files_only 只到模型不到 processor

2026-08-12，FunASR 转写集成时连踩三次（qwen_asr 两次 + FunASR 一次）。

## 症状

模型显存已占（checkpoint shards 加载完），但转写不跑——卡在 huggingface.co
联网重试（ConnectTimeout），或 `SSL: CERTIFICATE_VERIFY_FAILED` 直接报错。
30s 短音频正常；行为取决于模型加载顺序，与音频长度无关。

## 根因

qwen_asr 库（被 omnigate 直接用，也被 FunASR 内部包装）的 `from_pretrained`
只把 `local_files_only` 传给 `AutoModel`，**没传给 `AutoProcessor`**。无离线标记
时 transformers 默认联网 HEAD 检查 config/权重文件，机器无 HF 访问 → 卡死。

涉及位置：

- `omnigate/audio/transcribe.py`（qwen_asr 后端）
- `omnigate/audio/funasr_transcribe.py`（FunASR 后端）
- `D:\whisper\funasr\Lib\site-packages\funasr\models\qwen3_asr\model.py:156`
  （FunASR 内部调 `Qwen3ASRModel.from_pretrained`，同样不传 local_files_only）

## 修复（根治）

进程启动即设全局离线，必须在 import transformers/funasr 之前：

```python
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
```

`local_files_only` 单独传不可靠——库内部会漏传给子组件。环境变量是唯一全链路
生效的手段。

## 通用教训

任何 HF 生态库（transformers / whisper / funasr / qwen_asr）加载卡联网，先设
这两个环境变量，别指望 `local_files_only` 传到位。判断"离线已生效"用短音频回归：
正常应无任何 huggingface.co 日志。
