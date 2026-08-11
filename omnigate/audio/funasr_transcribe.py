"""FunASR transcription backend for omnigate.

Runs under a separate python env that has FunASR installed (this repo's own
env does not, to keep its torch/transformers untouched). Called either
directly:

    D:\\whisper\\funasr\\python.exe funasr_transcribe.py <wav_path>

or by transcribe.transcribe_wav(backend="funasr") via subprocess. Prints the
transcript text to stdout.

Pure transcription: no forced aligner, no speaker labels (faster, less VRAM).
fsmn-vad splits long audio into speech segments automatically, so peak VRAM
stays flat no matter the recording length — unlike qwen_asr's native
chunking, which OOMs a 16GB GPU on a full video.
"""
import os
import sys

# Force fully-offline HF BEFORE importing anything. FunASR wraps qwen_asr,
# which does not forward local_files_only to AutoModel/AutoProcessor — without
# these env vars every load tries a network HEAD and hangs on machines without
# HuggingFace access. With them, everything resolves from the local cache.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def transcribe(wav_path: str) -> str:
    """Transcribe a wav file with Qwen3-ASR via FunASR. Returns text."""
    from funasr import AutoModel

    model = AutoModel(
        model="Qwen/Qwen3-ASR-1.7B",
        vad_model="fsmn-vad",
        hub="hf",
        device="cuda:0",
        dtype="bf16",
        disable_update=True,
    )
    results = model.generate(input=wav_path, language="Chinese")
    return results[0]["text"]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.stderr.write(f"usage: {sys.argv[0]} <wav_path>\n")
        sys.exit(2)
    sys.stdout.reconfigure(encoding="utf-8")
    print(transcribe(sys.argv[1]))
