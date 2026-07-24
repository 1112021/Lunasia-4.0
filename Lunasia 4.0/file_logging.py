# -*- coding: utf-8 -*-
"""
运行日志：按日写入 logs/YYYY-MM-DD.txt，接管 stdout/stderr。
终端输出与原先一致；文件每行行首附加时间戳。
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import sys
import threading
from datetime import date, datetime, timedelta
from queue import Empty, Queue
from typing import Optional, TextIO

# 项目根（与本模块同目录，即 main.py 所在目录）
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG_DIR_NAME = "logs"

_RUN_LOGGER_NAME = "lunesia.run"
_STOP = object()

# 简单脱敏（整段匹配后替换）
_SENSITIVE_PATTERNS = [
    (re.compile(r"\bsk-[a-zA-Z0-9]{8,}\b"), "sk-***"),
    (re.compile(r"\bBearer\s+[a-zA-Z0-9._\-]{8,}\b", re.I), "Bearer ***"),
]


def _sanitize_line(text: str) -> str:
    for pattern, repl in _SENSITIVE_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def resolve_log_dir(config: Optional[dict] = None) -> str:
    """解析运行日志目录（相对路径相对于项目根）。"""
    raw = ""
    if config:
        raw = (config.get("file_log_dir") or "").strip()
    if not raw:
        return os.path.join(PROJECT_ROOT, DEFAULT_LOG_DIR_NAME)
    if os.path.isabs(raw):
        return os.path.normpath(raw)
    return os.path.normpath(os.path.join(PROJECT_ROOT, raw))


class _DailyLineLoggingHandler(logging.Handler):
    """按自然日写入 .txt；当天首次写入时创建文件。"""

    def __init__(self, log_dir: str):
        super().__init__()
        self.log_dir = log_dir
        self._lock = threading.Lock()
        self._current_date: Optional[date] = None
        self._file: Optional[TextIO] = None

    def set_log_dir(self, log_dir: str) -> None:
        with self._lock:
            if os.path.normpath(log_dir) == os.path.normpath(self.log_dir):
                return
            self._close_file()
            self.log_dir = log_dir
            self._current_date = None

    def _close_file(self) -> None:
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
            except Exception:
                pass
            self._file = None
        self._current_date = None

    def _ensure_file(self, today: date) -> None:
        if self._file is not None and self._current_date == today:
            return
        self._close_file()
        os.makedirs(self.log_dir, exist_ok=True)
        path = os.path.join(self.log_dir, today.strftime("%Y-%m-%d") + ".txt")
        self._file = open(path, "a", encoding="utf-8", errors="replace")
        self._current_date = today

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        if msg is None:
            return
        self.write_line(msg)

    def write_line(self, line: str) -> None:
        if not line:
            return
        line = _sanitize_line(line)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            try:
                today = date.today()
                self._ensure_file(today)
                if self._file is not None:
                    self._file.write(f"{ts} | {line}")
                    if not line.endswith("\n"):
                        self._file.write("\n")
                    self._file.flush()
            except Exception:
                pass

    def flush(self) -> None:
        with self._lock:
            if self._file is not None:
                try:
                    self._file.flush()
                except Exception:
                    pass

    def close(self) -> None:
        with self._lock:
            self._close_file()
        super().close()


class _TeeStream:
    """转发到原始终端；完整行交给运行日志队列（文件侧加时间戳）。"""

    def __init__(self, original: Optional[TextIO], enqueue_line):
        self._original = original
        self._enqueue = enqueue_line
        self._buffer = ""
        self._lock = threading.Lock()

    def write(self, s: str) -> int:
        if s is None or s == "":
            return 0
        if self._original is not None:
            try:
                self._original.write(s)
            except Exception:
                pass
        with self._lock:
            self._buffer += s
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                self._enqueue(line + "\n")
        return len(s)

    def flush(self) -> None:
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass
        with self._lock:
            if self._buffer:
                pending = self._buffer
                self._buffer = ""
                self._enqueue(pending)

    def isatty(self) -> bool:
        if self._original is not None and hasattr(self._original, "isatty"):
            try:
                return self._original.isatty()
            except Exception:
                pass
        return False

    @property
    def encoding(self):
        if self._original is not None:
            return getattr(self._original, "encoding", "utf-8")
        return "utf-8"

    @property
    def errors(self):
        if self._original is not None:
            return getattr(self._original, "errors", "replace")
        return "replace"

    def reconfigure(self, *args, **kwargs):
        if self._original is not None and hasattr(self._original, "reconfigure"):
            return self._original.reconfigure(*args, **kwargs)
        return None

    def fileno(self):
        if self._original is not None:
            return self._original.fileno()
        raise OSError("no fileno")

    def __getattr__(self, name):
        if self._original is not None:
            return getattr(self._original, name)
        raise AttributeError(name)


class _RunLogController:
    def __init__(self) -> None:
        self._enabled = True
        self._log_dir = resolve_log_dir()
        self._retention_days = 0
        self._queue: Queue = Queue()
        self._worker: Optional[threading.Thread] = None
        self._handler: Optional[_DailyLineLoggingHandler] = None
        self._logger: Optional[logging.Logger] = None
        self._tee_out: Optional[_TeeStream] = None
        self._tee_err: Optional[_TeeStream] = None
        self._orig_stdout: Optional[TextIO] = None
        self._orig_stderr: Optional[TextIO] = None
        self._installed = False
        self._worker_lock = threading.Lock()

    def _enqueue_line(self, line: str) -> None:
        if not self._enabled:
            return
        try:
            self._queue.put_nowait(line)
        except Exception:
            pass

    def _worker_loop(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=0.25)
            except Empty:
                continue
            if item is _STOP:
                break
            if self._handler is not None:
                self._handler.write_line(item)

    def _start_worker(self) -> None:
        with self._worker_lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._worker_loop, name="lunesia-run-log", daemon=True
            )
            self._worker.start()

    def _stop_worker(self) -> None:
        if self._worker is None:
            return
        try:
            self._queue.put(_STOP)
        except Exception:
            pass
        if self._worker.is_alive():
            self._worker.join(timeout=3.0)
        self._worker = None
        # 排空剩余
        while True:
            try:
                item = self._queue.get_nowait()
            except Empty:
                break
            if item is not _STOP and self._handler is not None:
                self._handler.write_line(item)

    def _setup_logger(self) -> None:
        self._handler = _DailyLineLoggingHandler(self._log_dir)
        self._handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger = logging.getLogger(_RUN_LOGGER_NAME)
        self._logger.handlers.clear()
        self._logger.addHandler(self._handler)
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False

    def _install_tee(self) -> None:
        if self._orig_stdout is None:
            self._orig_stdout = sys.__stdout__ or sys.stdout
        if self._orig_stderr is None:
            self._orig_stderr = sys.__stderr__ or sys.stderr
        self._tee_out = _TeeStream(self._orig_stdout, self._enqueue_line)
        self._tee_err = _TeeStream(self._orig_stderr, self._enqueue_line)
        sys.stdout = self._tee_out
        sys.stderr = self._tee_err

    def _restore_stdio(self) -> None:
        if self._orig_stdout is not None:
            sys.stdout = self._orig_stdout
        if self._orig_stderr is not None:
            sys.stderr = self._orig_stderr
        self._tee_out = None
        self._tee_err = None

    def _purge_old_logs(self) -> None:
        days = int(self._retention_days or 0)
        if days <= 0:
            return
        log_dir = self._log_dir
        if not os.path.isdir(log_dir):
            return
        cutoff = date.today() - timedelta(days=days)
        try:
            for name in os.listdir(log_dir):
                if not name.endswith(".txt"):
                    continue
                stem = name[:-4]
                try:
                    file_date = datetime.strptime(stem, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if file_date < cutoff:
                    try:
                        os.remove(os.path.join(log_dir, name))
                    except OSError:
                        pass
        except OSError:
            pass

    def apply_config(self, config: Optional[dict] = None) -> None:
        cfg = config or {}
        enabled = bool(cfg.get("file_log_enabled", True))
        self._log_dir = resolve_log_dir(cfg)
        try:
            self._retention_days = int(cfg.get("file_log_retention_days", 0))
        except (TypeError, ValueError):
            self._retention_days = 0

        if enabled and not self._installed:
            self._enabled = True
            self._setup_logger()
            self._start_worker()
            self._install_tee()
            self._installed = True
            self._purge_old_logs()
        elif enabled and self._installed:
            self._enabled = True
            if self._handler is not None:
                self._handler.set_log_dir(self._log_dir)
            self._purge_old_logs()
        elif not enabled and self._installed:
            self._enabled = False
            self.flush()
            self._stop_worker()
            if self._handler is not None:
                self._handler.close()
            self._restore_stdio()
            self._installed = False
            if self._logger is not None:
                self._logger.handlers.clear()
            self._handler = None
        else:
            self._enabled = False

    def flush(self) -> None:
        if self._tee_out is not None:
            try:
                self._tee_out.flush()
            except Exception:
                pass
        if self._tee_err is not None:
            try:
                self._tee_err.flush()
            except Exception:
                pass
        if self._handler is not None:
            self._handler.flush()

    def shutdown(self) -> None:
        self.flush()
        self._stop_worker()
        if self._handler is not None:
            self._handler.close()
            self._handler = None


_controller = _RunLogController()


def setup_app_logging(config: Optional[dict] = None) -> None:
    """尽早调用：默认启用，使用项目根 logs/。"""
    _controller.apply_config(config or {"file_log_enabled": True})


def update_app_logging(config: Optional[dict] = None) -> None:
    """加载/保存配置后更新目录、开关与保留策略。"""
    _controller.apply_config(config)


def shutdown_app_logging() -> None:
    _controller.shutdown()


def get_default_log_dir() -> str:
    return resolve_log_dir()


atexit.register(shutdown_app_logging)
