# -*- coding: utf-8 -*-
"""Local F5-TTS sidecar lifecycle and HTTP client."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import OrderedDict
from typing import Optional
from urllib.parse import urlparse


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _project_path(path: str) -> str:
    path = os.path.expandvars(os.path.expanduser(str(path or "").strip()))
    if not path:
        return ""
    return path if os.path.isabs(path) else os.path.abspath(os.path.join(PROJECT_ROOT, path))


def ensure_managed_reference(source: str, managed_path: str) -> str:
    """Copy a selected voice reference into the project-managed voice directory."""
    source = _project_path(source)
    target = _project_path(managed_path)
    if not source or not os.path.isfile(source):
        return target if target and os.path.isfile(target) else ""
    source_ext = os.path.splitext(source)[1].lower()
    if source_ext and source_ext != os.path.splitext(target)[1].lower():
        target = os.path.splitext(target)[0] + source_ext
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.abspath(source) != os.path.abspath(target):
        shutil.copy2(source, target)
    return target


class F5TTSSidecarClient:
    def __init__(self, config: dict):
        self.config = dict(config or {})
        self.base_url = self.config.get(
            "f5tts_base_url", "http://127.0.0.1:18765"
        ).rstrip("/")
        self.process: Optional[subprocess.Popen] = None
        self._owned_process = False
        self._lock = threading.RLock()
        self._cache = OrderedDict()
        self._active_request_id = ""
        self._log_handle = None

    def update_config(self, config: dict) -> None:
        with self._lock:
            old_url = self.base_url
            new_config = dict(config or {})
            new_url = new_config.get(
                "f5tts_base_url", "http://127.0.0.1:18765"
            ).rstrip("/")
            self._cache.clear()
            if old_url != new_url and self._owned_process:
                self.shutdown()
            self.config = new_config
            self.base_url = new_url
            if old_url != new_url and not self._owned_process:
                self.process = None

    def _request(self, method: str, path: str, payload=None, timeout=10):
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                detail = payload.get("error") or str(payload)
            except Exception:
                detail = str(exc)
            raise RuntimeError(
                f"F5-TTS Sidecar HTTP {exc.code}: {detail}"
            ) from exc

    def health(self, timeout=1.5) -> dict:
        try:
            return self._request("GET", "/health", timeout=timeout)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _sidecar_command(self):
        python_path = _project_path(
            self.config.get(
                "f5tts_python_path", "tools/f5tts_env/Scripts/python.exe"
            )
        )
        script_path = os.path.join(PROJECT_ROOT, "tools", "f5tts_sidecar.py")
        if not os.path.isfile(python_path):
            raise FileNotFoundError(
                f"未找到 F5-TTS Python 环境：{python_path}"
            )
        return [
            python_path,
            script_path,
            "--host",
            "127.0.0.1",
            "--port",
            str(self._port()),
            "--temp-dir",
            os.path.join(PROJECT_ROOT, "chat_logs", "tts_cache"),
            "--inline-max-bytes",
            str(int(self.config.get("f5tts_result_inline_max_bytes", 1048576))),
            "--ttl-minutes",
            str(int(self.config.get("f5tts_temp_ttl_minutes", 30))),
            "--scan-minutes",
            str(int(self.config.get("f5tts_temp_scan_minutes", 5))),
        ]

    def _port(self) -> int:
        try:
            return int(urlparse(self.base_url).port or 18765)
        except (TypeError, ValueError):
            return 18765

    def _is_local_url(self) -> bool:
        return (urlparse(self.base_url).hostname or "").lower() in {
            "127.0.0.1",
            "localhost",
            "::1",
        }

    def ensure_started(self, warmup=False, timeout=45) -> dict:
        current = self.health()
        if current.get("ok"):
            if warmup:
                return self.warmup(timeout=max(timeout, 120))
            return current
        if not self._is_local_url():
            return {
                "ok": False,
                "error": "F5-TTS Sidecar 仅允许使用 localhost/127.0.0.1",
            }
        with self._lock:
            current = self.health()
            if current.get("ok"):
                return self.warmup(timeout=max(timeout, 120)) if warmup else current
            command = self._sidecar_command()
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            log_dir = os.path.join(PROJECT_ROOT, "logs")
            os.makedirs(log_dir, exist_ok=True)
            self._log_handle = open(
                os.path.join(log_dir, "f5tts_sidecar.log"),
                "a",
                encoding="utf-8",
                buffering=1,
            )
            self.process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
            self._owned_process = True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                return {
                    "ok": False,
                    "error": f"F5-TTS sidecar 启动失败（退出码 {self.process.returncode}）",
                }
            current = self.health()
            if current.get("ok"):
                return self.warmup(timeout=max(timeout, 120)) if warmup else current
            time.sleep(0.35)
        return {"ok": False, "error": "等待 F5-TTS sidecar 启动超时"}

    def model_options(self) -> dict:
        residency = self.config.get("f5tts_residency_mode", "resident")
        return {
            "model": self.config.get("f5tts_model", "F5TTS_v1_Base"),
            "device": self.config.get("f5tts_device", "cuda"),
            "cpu_fallback": bool(
                self.config.get("f5tts_cpu_fallback_enabled", True)
            ),
            "idle_unload_seconds": (
                int(self.config.get("f5tts_idle_unload_minutes", 10)) * 60
                if residency == "idle_unload"
                else 0
            ),
        }

    def warmup(self, timeout=240) -> dict:
        payload = self.model_options()
        return self._request("POST", "/warmup", payload, timeout=timeout)

    def unload(self, timeout=15) -> dict:
        try:
            return self._request("POST", "/unload", {}, timeout=timeout)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def cancel(self) -> None:
        request_id = self._active_request_id
        try:
            self._request(
                "POST", "/cancel", {"request_id": request_id}, timeout=2
            )
        except Exception:
            pass

    def _reference_path(self) -> str:
        managed = self.config.get(
            "f5tts_ref_audio", "assets/tts/user/lunasia_ref.wav"
        )
        source = self.config.get("f5tts_ref_audio_source", "")
        path = ensure_managed_reference(source, managed)
        if not path:
            path = _project_path(managed)
        return path

    def _cache_key(self, text: str):
        ref_path = self._reference_path()
        try:
            ref_version = (
                os.path.getmtime(ref_path),
                os.path.getsize(ref_path),
            )
        except OSError:
            ref_version = (0, 0)
        return (
            text,
            ref_path,
            ref_version,
            self.config.get("f5tts_ref_text", ""),
            float(self.config.get("tts_speaking_rate", 1.0)),
            int(self.config.get("f5tts_nfe_step", 32)),
            float(self.config.get("f5tts_cfg_strength", 2.0)),
            self.config.get("f5tts_model", "F5TTS_v1_Base"),
        )

    def _materialize_bytes(self, data: bytes) -> str:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        try:
            temp_file.write(data)
            return temp_file.name
        finally:
            temp_file.close()

    def synthesize(self, text: str, timeout=300) -> Optional[str]:
        key = self._cache_key(text)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return self._materialize_bytes(cached)

        start = self.ensure_started(warmup=False)
        if not start.get("ok"):
            raise RuntimeError(start.get("error", "F5-TTS sidecar 不可用"))

        request_id = uuid.uuid4().hex
        self._active_request_id = request_id
        payload = {
            "request_id": request_id,
            "text": text,
            "ref_audio": self._reference_path(),
            "ref_text": self.config.get("f5tts_ref_text", ""),
            "speed": float(self.config.get("tts_speaking_rate", 1.0)),
            "nfe_step": int(self.config.get("f5tts_nfe_step", 32)),
            "cfg_strength": float(self.config.get("f5tts_cfg_strength", 2.0)),
            **self.model_options(),
        }
        try:
            result = self._request(
                "POST", "/synthesize", payload, timeout=timeout
            )
        finally:
            self._active_request_id = ""
        if not result.get("ok"):
            if result.get("cancelled"):
                return None
            raise RuntimeError(result.get("error", "F5-TTS 合成失败"))

        response_format = result.get("format")
        if response_format == "base64_wav":
            audio_bytes = base64.b64decode(result.get("data_b64", ""))
            max_items = max(0, int(self.config.get("f5tts_cache_max_items", 24)))
            if max_items:
                with self._lock:
                    self._cache[key] = audio_bytes
                    self._cache.move_to_end(key)
                    while len(self._cache) > max_items:
                        self._cache.popitem(last=False)
            return self._materialize_bytes(audio_bytes)
        if response_format == "file_path":
            path = os.path.abspath(result.get("path", ""))
            allowed = os.path.abspath(
                os.path.join(PROJECT_ROOT, "chat_logs", "tts_cache")
            )
            try:
                safe_path = os.path.commonpath([path, allowed]) == allowed
            except ValueError:
                safe_path = False
            if not safe_path:
                raise RuntimeError("sidecar 返回了不安全的音频路径")
            if not os.path.isfile(path):
                raise RuntimeError("sidecar 返回的音频文件不存在")
            return path
        raise RuntimeError("sidecar 返回了未知音频格式")

    def shutdown(self) -> None:
        self.cancel()
        if self._owned_process:
            try:
                self._request("POST", "/shutdown", {}, timeout=3)
            except Exception:
                pass
            process = self.process
            if process is not None:
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
        self.process = None
        self._owned_process = False
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None

