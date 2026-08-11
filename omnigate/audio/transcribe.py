"""Audio extraction + transcription.

extract_audio: use yt-dlp to pull a video's audio stream to a local wav file.
transcribe_wav: transcribe a wav file to text, picking a backend.

Backends are a small lookup table — resolve_backend picks one and each backend
is one _transcribe_<name> function (add a backend with one row + one function,
not if/elif sprawl):

  - funasr  : runs funasr_transcribe.py in the FunASR env (D:\\whisper\\funasr)
              via subprocess. Qwen3-ASR + fsmn-vad, so long audio never OOMs.
              The separate env keeps this repo's torch/transformers untouched.
  - whisper : in-process openai-whisper (same env). large-v3 cached locally.
  - qwen_asr: in-process qwen_asr lib (long audio split into fixed segments).

Backend selection is deterministic, never silent: an explicit `backend`
argument wins, else a saved config (~/.omnigate/config.json, via `omnigate asr
set`), else `auto` (funasr if its env exists, then qwen_asr). A configured
backend that is unavailable raises a clear error instead of guessing.

Models load lazily inside a transcribe call only — browser tasks never pay the
memory cost.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

_BACKENDS = ("funasr", "qwen_asr", "whisper")
_FUNASR_PYTHON_DEFAULT = r"D:\whisper\funasr\python.exe"
_CONFIG_DIR = Path(os.path.expanduser("~")) / ".omnigate"
_CONFIG_PATH = _CONFIG_DIR / "config.json"
_WHISPER_MODEL_DEFAULT = "large-v3"


def extract_audio(url: str, output_dir: str) -> str:
    """Download audio from a video URL to output_dir as wav.

    Returns the path to the extracted wav file.
    Raises RuntimeError on failure.
    """
    os.makedirs(output_dir, exist_ok=True)
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("yt-dlp not installed. Run: pip install yt-dlp") from exc

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "noplaylist": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_id = info.get("id", "audio")
    wav_path = os.path.join(output_dir, f"{video_id}.wav")
    if not os.path.exists(wav_path):
        raise RuntimeError(f"Audio extraction failed, expected {wav_path}")
    return wav_path


# --- config (persisted backend choice) ---

def _load_config() -> dict:
    """Load ~/.omnigate/config.json; missing/invalid -> {}."""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_config(cfg: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def _find_funasr_python() -> str | None:
    """Path to a python that has FunASR installed, or None if not found."""
    env = os.environ.get("FUNASR_PYTHON", "").strip()
    if env:
        return env
    return _FUNASR_PYTHON_DEFAULT if os.path.exists(_FUNASR_PYTHON_DEFAULT) else None


def _funasr_available() -> bool:
    return _find_funasr_python() is not None


def _qwen_asr_available() -> bool:
    return importlib.util.find_spec("qwen_asr") is not None


def _whisper_available() -> bool:
    return importlib.util.find_spec("whisper") is not None


def backend_status() -> list[tuple[str, bool, str]]:
    """[(backend, available, note), ...] — for `omnigate asr status`."""
    return [
        ("funasr", _funasr_available(), _find_funasr_python() or "missing"),
        ("qwen_asr", _qwen_asr_available(), "in-process"),
        ("whisper", _whisper_available(), f"in-process ({_WHISPER_MODEL_DEFAULT} cached)"),
    ]


def resolve_backend(backend: str = "auto") -> str:
    """Resolve a backend: explicit arg > saved config > auto-detection.

    'auto' without config: funasr if its env exists, else qwen_asr. A saved
    config value or explicit backend is used as-is; unavailability is reported
    by the transcribe call with a clear error, never silently swapped.
    """
    if backend == "auto":
        backend = _load_config().get("asr_backend", "auto")
    if backend == "auto":
        if _funasr_available():
            return "funasr"
        if _qwen_asr_available():
            return "qwen_asr"
        raise RuntimeError(
            "No ASR backend available: FunASR env not found and qwen_asr not installed."
        )
    if backend not in _BACKENDS:
        raise ValueError(
            f"Unknown transcription backend: {backend!r}. Known: auto, {', '.join(_BACKENDS)}"
        )
    return backend


def transcribe_wav(
    wav_path: str,
    backend: str = "auto",
    model_name: str = "Qwen/Qwen3-ASR-1.7B",
    device: str = "cuda:0",
    segment_seconds: float = 120.0,
) -> str:
    """Transcribe a wav file to text via the selected backend.

    Returns the transcript text. Raises RuntimeError on failure.
    """
    be = resolve_backend(backend)
    if be == "funasr":
        return _transcribe_funasr(wav_path)
    if be == "whisper":
        return _transcribe_whisper(wav_path)
    return _transcribe_qwen_asr(wav_path, model_name, device, segment_seconds)


def _transcribe_funasr(wav_path: str) -> str:
    """Transcribe via the FunASR env (separate python, run as a subprocess)."""
    funasr_python = _find_funasr_python()
    if funasr_python is None:
        raise RuntimeError(
            "FunASR backend requested but no FunASR python found. "
            f"Set FUNASR_PYTHON or install one at {_FUNASR_PYTHON_DEFAULT}."
        )
    script = os.path.join(os.path.dirname(__file__), "funasr_transcribe.py")
    proc = subprocess.run(
        [funasr_python, script, os.path.abspath(wav_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"FunASR transcription failed ({proc.returncode}): "
            f"{proc.stderr[-500:].strip()}"
        )
    text = proc.stdout.strip()
    if not text:
        raise RuntimeError("FunASR transcription returned empty output")
    return text


def _transcribe_whisper(
    wav_path: str,
    model_size: str = _WHISPER_MODEL_DEFAULT,
    device: str = "cuda:0",
) -> str:
    """Transcribe with openai-whisper in-process (model cached locally)."""
    if not _whisper_available():
        raise RuntimeError(
            "Whisper backend requested but openai-whisper is not installed "
            "in this environment. Run: pip install openai-whisper"
        )
    import whisper

    model = whisper.load_model(model_size, device=device)
    result = model.transcribe(os.path.abspath(wav_path))
    text = result.get("text", "").strip()
    if not text:
        raise RuntimeError("Whisper transcription returned empty output")
    return text


def _transcribe_qwen_asr(
    wav_path: str,
    model_name: str = "Qwen/Qwen3-ASR-1.7B",
    device: str = "cuda:0",
    segment_seconds: float = 120.0,
) -> str:
    """In-process qwen_asr backend, long audio split into segments.

    Loads from the local HuggingFace cache only (no network). qwen_asr only
    forwards local_files_only to the model, not to AutoProcessor (which would
    try a network HEAD and hang), so HF offline is forced via env vars. The
    120s segments keep peak VRAM flat for long recordings.
    """
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    import numpy as np
    import soundfile as sf
    import torch
    from qwen_asr import Qwen3ASRModel

    wav, sr = sf.read(wav_path, dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)

    model = Qwen3ASRModel.from_pretrained(
        model_name,
        dtype=torch.bfloat16,
        device_map=device,
        max_inference_batch_size=32,
        max_new_tokens=1024,
        local_files_only=True,
    )

    seg_len = int(segment_seconds * sr)
    texts: list[str] = []
    for start in range(0, len(wav), seg_len):
        seg = wav[start:start + seg_len]
        result = model.transcribe(audio=(seg, sr))
        texts.append(result[0].text)
    return "\n".join(t for t in texts if t)
