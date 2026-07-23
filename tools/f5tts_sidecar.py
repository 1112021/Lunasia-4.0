# -*- coding: utf-8 -*-
"""F5-TTS local sidecar. Run this file with the dedicated F5-TTS Python."""

from __future__ import annotations

import argparse
import base64
import gc
import glob
import json
import math
import os
import shutil
import threading
import time
import traceback
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def configure_ffmpeg_path():
    """Make WinGet FFmpeg visible even when the parent has a stale PATH."""
    if shutil.which("ffmpeg"):
        return shutil.which("ffmpeg")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    patterns = [
        os.path.join(
            local_app_data,
            "Microsoft",
            "WinGet",
            "Packages",
            "Gyan.FFmpeg_*",
            "ffmpeg-*",
            "bin",
            "ffmpeg.exe",
        ),
        os.path.join(PROJECT_ROOT, "tools", "ffmpeg", "bin", "ffmpeg.exe"),
    ]
    for pattern in patterns:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            bin_dir = os.path.dirname(matches[0])
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
            return matches[0]
    return ""


def install_safe_f5_asr_adapter():
    """Decode all inference audio without TorchCodec shared-library coupling."""
    import numpy as np
    import soundfile as sf
    import torch
    import torchaudio
    from scipy.signal import resample_poly
    from f5_tts.infer import utils_infer
    from transformers.pipelines import automatic_speech_recognition

    def soundfile_load(
        uri,
        frame_offset=0,
        num_frames=-1,
        normalize=True,
        channels_first=True,
        format=None,
        buffer_size=4096,
        backend=None,
    ):
        del normalize, format, buffer_size, backend
        frames = -1 if num_frames is None or int(num_frames) < 0 else int(num_frames)
        audio, sample_rate = sf.read(
            uri,
            start=max(0, int(frame_offset)),
            frames=frames,
            dtype="float32",
            always_2d=True,
        )
        if channels_first:
            audio = audio.T
        return torch.from_numpy(np.ascontiguousarray(audio)), sample_rate

    def transcribe_pcm(ref_audio, language=None):
        if utils_infer.asr_pipe is None:
            utils_infer.initialize_asr_pipeline(device=utils_infer.device)
        audio, sample_rate = sf.read(
            ref_audio, dtype="float32", always_2d=False
        )
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        target_rate = int(
            utils_infer.asr_pipe.feature_extractor.sampling_rate
        )
        if sample_rate != target_rate:
            divisor = math.gcd(int(sample_rate), target_rate)
            audio = resample_poly(
                audio,
                target_rate // divisor,
                int(sample_rate) // divisor,
            ).astype(np.float32, copy=False)
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        generate_kwargs = {"task": "transcribe"}
        if language:
            generate_kwargs["language"] = language
        return utils_infer.asr_pipe(
            {"array": audio, "sampling_rate": target_rate},
            chunk_length_s=30,
            batch_size=8,
            generate_kwargs=generate_kwargs,
            return_timestamps=False,
        )["text"].strip()

    # torchaudio 2.11 delegates file decoding to TorchCodec. F5 only needs
    # uncompressed PCM here, so SoundFile is both simpler and more stable.
    torchaudio.load = soundfile_load
    automatic_speech_recognition.is_torchcodec_available = lambda: False
    utils_infer.transcribe = transcribe_pcm


class F5Runtime:
    def __init__(self, args):
        self.args = args
        self.model = None
        self.model_name = ""
        self.device = ""
        self.idle_unload_seconds = 0
        self.last_inference_finished = 0.0
        self.inference_lock = threading.Lock()
        self.model_lock = threading.RLock()
        self.cancelled_ids = set()
        self.running_request_id = ""
        self.stop_event = threading.Event()
        self.ffmpeg_path = configure_ffmpeg_path()
        install_safe_f5_asr_adapter()
        os.makedirs(self.args.temp_dir, exist_ok=True)
        self.cleanup_thread = threading.Thread(
            target=self._maintenance_loop, daemon=True
        )
        self.cleanup_thread.start()

    def _safe_reference(self, path: str) -> str:
        path = os.path.abspath(os.path.expanduser(path or ""))
        managed_root = os.path.abspath(os.path.join(PROJECT_ROOT, "assets", "tts"))
        try:
            if os.path.commonpath([path, managed_root]) != managed_root:
                raise ValueError("参考音频必须位于项目 assets/tts 托管目录")
        except ValueError:
            raise ValueError("参考音频路径无效")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"参考音频不存在：{path}")
        return path

    def load_model(self, model_name: str, device: str, cpu_fallback=False):
        with self.model_lock:
            if (
                self.model is not None
                and self.model_name == model_name
                and self.device == device
            ):
                return
            self._unload_locked()
            from f5_tts.api import F5TTS

            try:
                try:
                    self.model = F5TTS(model=model_name, device=device)
                except TypeError:
                    self.model = F5TTS(model=model_name)
            except Exception:
                if device != "cuda" or not cpu_fallback:
                    raise
                self._unload_locked()
                try:
                    self.model = F5TTS(model=model_name, device="cpu")
                except TypeError:
                    self.model = F5TTS(model=model_name)
                device = "cpu"
            self.model_name = model_name
            self.device = device

    def warmup(self, payload: dict):
        model_name = str(payload.get("model") or "F5TTS_v1_Base")
        device = str(payload.get("device") or "cuda")
        self.idle_unload_seconds = max(
            0, int(payload.get("idle_unload_seconds") or 0)
        )
        self.load_model(
            model_name, device, bool(payload.get("cpu_fallback", True))
        )
        return {
            "ok": True,
            "ready": True,
            "model": self.model_name,
            "device": self.device,
            "ffmpeg": self.ffmpeg_path or shutil.which("ffmpeg") or "",
            "asr_decoder": "soundfile-pcm",
        }

    def cancel(self, request_id: str):
        if request_id:
            self.cancelled_ids.add(request_id)
        elif self.running_request_id:
            self.cancelled_ids.add(self.running_request_id)

    def _is_cancelled(self, request_id: str) -> bool:
        return bool(request_id and request_id in self.cancelled_ids)

    @staticmethod
    def _duration(path: str) -> float:
        try:
            with wave.open(path, "rb") as wav_file:
                rate = wav_file.getframerate()
                return (
                    wav_file.getnframes() / float(rate)
                    if rate
                    else 0.0
                )
        except Exception:
            return 0.0

    def synthesize(self, payload: dict):
        request_id = str(payload.get("request_id") or uuid.uuid4().hex)
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("合成文本为空")
        ref_audio = self._safe_reference(str(payload.get("ref_audio") or ""))
        ref_text = str(payload.get("ref_text") or "")
        model_name = str(payload.get("model") or "F5TTS_v1_Base")
        device = str(payload.get("device") or "cuda")
        self.idle_unload_seconds = max(
            0, int(payload.get("idle_unload_seconds") or 0)
        )
        output_path = os.path.join(
            self.args.temp_dir, f"{int(time.time())}_{request_id}.wav"
        )

        with self.inference_lock:
            if self._is_cancelled(request_id):
                return {"ok": False, "cancelled": True, "request_id": request_id}
            self.running_request_id = request_id
            try:
                self.load_model(
                    model_name, device, bool(payload.get("cpu_fallback", True))
                )
                kwargs = {
                    "ref_file": ref_audio,
                    "ref_text": ref_text,
                    "gen_text": text,
                    "file_wave": output_path,
                    "speed": float(payload.get("speed") or 1.0),
                    "nfe_step": int(payload.get("nfe_step") or 32),
                    "cfg_strength": float(payload.get("cfg_strength") or 2.0),
                    "show_info": lambda *_args, **_kwargs: None,
                }
                self.model.infer(**kwargs)
                if self._is_cancelled(request_id):
                    self._delete_file(output_path)
                    return {
                        "ok": False,
                        "cancelled": True,
                        "request_id": request_id,
                    }
                if not os.path.isfile(output_path):
                    raise RuntimeError("F5-TTS 未生成 WAV 文件")
                size = os.path.getsize(output_path)
                result = {
                    "ok": True,
                    "request_id": request_id,
                    "bytes": size,
                    "duration_sec": self._duration(output_path),
                    "sample_rate": 24000,
                }
                if size <= self.args.inline_max_bytes:
                    with open(output_path, "rb") as audio_file:
                        result["data_b64"] = base64.b64encode(
                            audio_file.read()
                        ).decode("ascii")
                    result["format"] = "base64_wav"
                    self._delete_file(output_path)
                else:
                    result["format"] = "file_path"
                    result["path"] = output_path
                return result
            finally:
                self.last_inference_finished = time.monotonic()
                self.running_request_id = ""
                self.cancelled_ids.discard(request_id)

    @staticmethod
    def _delete_file(path: str):
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass

    def unload(self):
        with self.model_lock:
            self._unload_locked()

    def _unload_locked(self):
        self.model = None
        self.model_name = ""
        self.device = ""
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def _cleanup_expired(self):
        cutoff = time.time() - self.args.ttl_minutes * 60
        try:
            for name in os.listdir(self.args.temp_dir):
                path = os.path.join(self.args.temp_dir, name)
                if (
                    name.lower().endswith(".wav")
                    and os.path.isfile(path)
                    and os.path.getmtime(path) < cutoff
                ):
                    self._delete_file(path)
        except OSError:
            pass

    def _maintenance_loop(self):
        interval = max(30, self.args.scan_minutes * 60)
        while not self.stop_event.wait(interval):
            self._cleanup_expired()
            if (
                self.idle_unload_seconds > 0
                and self.model is not None
                and self.last_inference_finished > 0
                and time.monotonic() - self.last_inference_finished
                >= self.idle_unload_seconds
                and not self.inference_lock.locked()
            ):
                self.unload()

    def health(self):
        return {
            "ok": True,
            "service": "f5tts-sidecar",
            "ready": self.model is not None,
            "busy": self.inference_lock.locked(),
            "model": self.model_name,
            "device": self.device,
        }


class Handler(BaseHTTPRequestHandler):
    runtime: F5Runtime = None
    server_version = "LunasiaF5TTS/1.0"

    def log_message(self, fmt, *args):
        print("[F5-TTS] " + (fmt % args), flush=True)

    def _json_body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send(self, status: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, self.runtime.health())
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        try:
            payload = self._json_body()
            if self.path == "/warmup":
                result = self.runtime.warmup(payload)
            elif self.path == "/synthesize":
                result = self.runtime.synthesize(payload)
            elif self.path == "/cancel":
                self.runtime.cancel(str(payload.get("request_id") or ""))
                result = {"ok": True}
            elif self.path == "/unload":
                self.runtime.unload()
                result = {"ok": True, "ready": False}
            elif self.path == "/shutdown":
                result = {"ok": True}
                self._send(200, result)
                self.runtime.stop_event.set()
                threading.Thread(
                    target=self.server.shutdown, daemon=True
                ).start()
                return
            else:
                self._send(404, {"ok": False, "error": "not found"})
                return
            self._send(200, result)
        except Exception as exc:
            traceback.print_exc()
            self._send(500, {"ok": False, "error": str(exc)})


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument(
        "--temp-dir",
        default=os.path.join(PROJECT_ROOT, "chat_logs", "tts_cache"),
    )
    parser.add_argument("--inline-max-bytes", type=int, default=1048576)
    parser.add_argument("--ttl-minutes", type=int, default=30)
    parser.add_argument("--scan-minutes", type=int, default=5)
    return parser.parse_args()


def main():
    args = parse_args()
    args.temp_dir = os.path.abspath(args.temp_dir)
    runtime = F5Runtime(args)
    Handler.runtime = runtime
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        f"F5-TTS sidecar listening on http://{args.host}:{args.port}",
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        runtime.stop_event.set()
        runtime.unload()
        server.server_close()


if __name__ == "__main__":
    main()
