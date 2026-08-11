"""Tests for transcription backend dispatch (audio/transcribe.py).

Both backends do heavy work (subprocess / model load), so these tests mock at
the boundary: the FunASR environment probe, subprocess.run, and the qwen_asr
backend function.
"""
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from omnigate.audio import transcribe


class TestResolveBackend(unittest.TestCase):
    def test_auto_picks_funasr_when_env_found(self):
        with mock.patch.object(transcribe, "_find_funasr_python",
                               return_value=r"D:\whisper\funasr\python.exe"):
            self.assertEqual(transcribe.resolve_backend("auto"), "funasr")

    def test_auto_falls_back_to_qwen_asr_without_funasr(self):
        with mock.patch.object(transcribe, "_find_funasr_python", return_value=None):
            self.assertEqual(transcribe.resolve_backend("auto"), "qwen_asr")

    def test_explicit_backend_ok(self):
        self.assertEqual(transcribe.resolve_backend("funasr"), "funasr")
        self.assertEqual(transcribe.resolve_backend("qwen_asr"), "qwen_asr")

    def test_unknown_backend_raises(self):
        with self.assertRaises(ValueError):
            transcribe.resolve_backend("whisper")


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


class TestTranscribeDispatch(unittest.TestCase):
    def test_dispatches_to_funasr(self):
        with mock.patch.object(transcribe, "resolve_backend", return_value="funasr"), \
             mock.patch.object(transcribe, "_transcribe_funasr", return_value="funasr text"):
            self.assertEqual(transcribe.transcribe_wav("x.wav"), "funasr text")

    def test_dispatches_to_qwen_asr(self):
        with mock.patch.object(transcribe, "resolve_backend", return_value="qwen_asr"), \
             mock.patch.object(transcribe, "_transcribe_qwen_asr", return_value="qwen text"):
            self.assertEqual(transcribe.transcribe_wav("x.wav"), "qwen text")
