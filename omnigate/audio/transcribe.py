"""Audio extraction + transcription.

extract_audio: use yt-dlp to pull a video's audio stream to a local wav file.
transcribe_wav: lazily load Qwen3 ASR and transcribe a wav file.

The ASR model is NOT imported at module load — it only loads inside
transcribe_wav, so running browser tasks never pays the model's memory cost.
"""
from __future__ import annotations

import os


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


def transcribe_wav(
    wav_path: str,
    model_name: str = "Qwen/Qwen3-ASR-1.7B",
    device: str = "cuda:0",
) -> str:
    """Transcribe a wav file with Qwen3 ASR (lazy-loaded).

    Loads from the local HuggingFace cache only (no network) — this project
    runs fully offline once the model is downloaded once. Returns text.
    """
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
    result = model.transcribe(audio=(wav, sr))
    return result[0].text
