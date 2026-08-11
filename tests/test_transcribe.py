"""Tests for transcription backend dispatch (audio/transcribe.py).

Backends do heavy work (subprocess / model load), so these tests mock at the
boundary: the config file, the availability probes, subprocess.run, and the
model libraries.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omnigate.audio import transcribe


class TestResolveBackend(unittest.TestCase):
    def test_auto_picks_funasr_when_env_found(self):
        with mock.patch.object(transcribe, "_load_config", return_value={}), \
             mock.patch.object(transcribe, "_find_funasr_python",
                               return_value=r"D:\whisper\funasr\python.exe"):
            self.assertEqual(transcribe.resolve_backend("auto"), "funasr")

    def test_auto_falls_back_to_qwen_asr_without_funasr(self):
        with mock.patch.object(transcribe, "_load_config", return_value={}), \
             mock.patch.object(transcribe, "_find_funasr_python", return_value=None), \
             mock.patch.object(transcribe, "_qwen_asr_available", return_value=True):
            self.assertEqual(transcribe.resolve_backend("auto"), "qwen_asr")

    def test_auto_with_no_backend_available_raises(self):
        with mock.patch.object(transcribe, "_load_config", return_value={}), \
             mock.patch.object(transcribe, "_find_funasr_python", return_value=None), \
             mock.patch.object(transcribe, "_qwen_asr_available", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "No ASR backend available"):
                transcribe.resolve_backend("auto")

    def test_config_backend_used_on_auto(self):
        with mock.patch.object(transcribe, "_load_config",
                               return_value={"asr_backend": "whisper"}):
            self.assertEqual(transcribe.resolve_backend("auto"), "whisper")

    def test_explicit_backend_overrides_config(self):
        with mock.patch.object(transcribe, "_load_config",
                               return_value={"asr_backend": "whisper"}):
            self.assertEqual(transcribe.resolve_backend("funasr"), "funasr")

    def test_explicit_backend_ok(self):
        self.assertEqual(transcribe.resolve_backend("funasr"), "funasr")
        self.assertEqual(transcribe.resolve_backend("qwen_asr"), "qwen_asr")
        self.assertEqual(transcribe.resolve_backend("whisper"), "whisper")

    def test_unknown_backend_raises(self):
        with self.assertRaises(ValueError):
            transcribe.resolve_backend("siri")


class TestConfigFile(unittest.TestCase):
    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(transcribe, "_CONFIG_DIR", Path(td)), \
                 mock.patch.object(transcribe, "_CONFIG_PATH", Path(td) / "config.json"):
                transcribe._save_config({"asr_backend": "whisper"})
                self.assertEqual(transcribe._load_config(), {"asr_backend": "whisper"})

    def test_load_missing_config_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(transcribe, "_CONFIG_PATH", Path(td) / "none.json"):
                self.assertEqual(transcribe._load_config(), {})


class TestTranscribeFunasr(unittest.TestCase):
    def _wav(self):
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        self.addCleanup(os.unlink, path)
        return path

    def test_runs_subprocess_with_funasr_python(self):
        wav = self._wav()
        calls = {}

        def fake_run(cmd, **kwargs):
            calls["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="你好", stderr="")

        with mock.patch.object(transcribe.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(transcribe, "_find_funasr_python",
                               return_value="py.exe"):
            text = transcribe._transcribe_funasr(wav)
        self.assertEqual(text, "你好")
        self.assertEqual(calls["cmd"][0], "py.exe")
        self.assertTrue(calls["cmd"][1].endswith("funasr_transcribe.py"))
        self.assertEqual(calls["cmd"][2], os.path.abspath(wav))

    def test_nonzero_exit_raises(self):
        wav = self._wav()

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

        with mock.patch.object(transcribe.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(transcribe, "_find_funasr_python", return_value="py.exe"):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                transcribe._transcribe_funasr(wav)

    def test_empty_output_raises(self):
        wav = self._wav()

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout="   ", stderr="")

        with mock.patch.object(transcribe.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(transcribe, "_find_funasr_python", return_value="py.exe"):
            with self.assertRaisesRegex(RuntimeError, "empty"):
                transcribe._transcribe_funasr(wav)

    def test_missing_funasr_python_raises(self):
        wav = self._wav()
        with mock.patch.object(transcribe, "_find_funasr_python", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "FUNASR_PYTHON"):
                transcribe._transcribe_funasr(wav)


class TestTranscribeWhisper(unittest.TestCase):
    def test_uses_whisper_in_process(self):
        fake_model = mock.Mock()
        fake_model.transcribe.return_value = {"text": "你好世界"}
        fake_whisper = mock.MagicMock(load_model=mock.MagicMock(return_value=fake_model))
        with mock.patch.object(transcribe, "_whisper_available", return_value=True), \
             mock.patch.dict("sys.modules", {"whisper": fake_whisper}):
            text = transcribe._transcribe_whisper("x.wav")
        self.assertEqual(text, "你好世界")
        fake_whisper.load_model.assert_called_once_with("large-v3", device="cuda:0")
        fake_model.transcribe.assert_called_once()

    def test_missing_whisper_raises(self):
        with mock.patch.object(transcribe, "_whisper_available", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "openai-whisper"):
                transcribe._transcribe_whisper("x.wav")


class TestTranscribeDispatch(unittest.TestCase):
    def test_dispatches_to_funasr(self):
        with mock.patch.object(transcribe, "resolve_backend", return_value="funasr"), \
             mock.patch.object(transcribe, "_transcribe_funasr", return_value="funasr text"):
            self.assertEqual(transcribe.transcribe_wav("x.wav"), "funasr text")

    def test_dispatches_to_whisper(self):
        with mock.patch.object(transcribe, "resolve_backend", return_value="whisper"), \
             mock.patch.object(transcribe, "_transcribe_whisper", return_value="whisper text"):
            self.assertEqual(transcribe.transcribe_wav("x.wav"), "whisper text")

    def test_dispatches_to_qwen_asr(self):
        with mock.patch.object(transcribe, "resolve_backend", return_value="qwen_asr"), \
             mock.patch.object(transcribe, "_transcribe_qwen_asr", return_value="qwen text"):
            self.assertEqual(transcribe.transcribe_wav("x.wav"), "qwen text")
