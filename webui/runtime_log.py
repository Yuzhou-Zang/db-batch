from __future__ import annotations

import contextvars
import re
import sys
import threading
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator, TextIO


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
LEVEL_RE = re.compile(r"\[(TRACE|DEBUG|INFO|SUCCESS|WARNING|ERROR)\]", re.IGNORECASE)
MAX_SESSION_LOG_ENTRIES = 5000

_log_context: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar(
    "runtime_log_context", default={}
)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _clean_line(value: str) -> str:
    return ANSI_ESCAPE_RE.sub("", value).rstrip("\r")


def _infer_level(message: str, fallback: str = "INFO") -> str:
    match = LEVEL_RE.search(message)
    if match:
        return match.group(1).upper()
    lowered = message.lower()
    if "traceback" in lowered or "exception" in lowered or "error" in lowered:
        return "ERROR"
    if "失败" in message or "错误" in message or "超时" in message:
        return "ERROR"
    if "警告" in message or "重试" in message or "额度" in message:
        return "WARNING"
    if "完成" in message or "成功" in message or "已保存" in message:
        return "SUCCESS"
    return fallback


class SessionLogStore:
    """保存本次服务启动后的日志，供管理页面增量读取。"""

    def __init__(self, max_entries: int = MAX_SESSION_LOG_ENTRIES) -> None:
        self.started_at = _now_iso()
        self._entries: deque[dict[str, Any]] = deque(maxlen=max_entries)
        self._next_id = 1
        self._lock = threading.Lock()

    def add(
        self,
        message: str,
        *,
        level: str | None = None,
        context: dict[str, str] | None = None,
        stream: str = "stdout",
    ) -> dict[str, Any] | None:
        message = _clean_line(message)
        if not message.strip():
            return None
        entry_context = dict(_log_context.get())
        if context:
            entry_context.update(
                {key: str(value) for key, value in context.items() if value not in (None, "")}
            )
        with self._lock:
            entry = {
                "id": self._next_id,
                "timestamp": _now_iso(),
                "level": (
                    level
                    or _infer_level(message, "ERROR" if stream == "stderr" else "INFO")
                ).upper(),
                "message": message,
                "stream": stream,
                **entry_context,
            }
            self._next_id += 1
            self._entries.append(entry)
            return dict(entry)

    def snapshot(self, after_id: int = 0) -> dict[str, Any]:
        with self._lock:
            entries = [dict(item) for item in self._entries if item["id"] > after_id]
            latest_id = self._next_id - 1
        return {
            "session_started_at": self.started_at,
            "latest_id": latest_id,
            "entries": entries,
        }


SESSION_LOG = SessionLogStore()
_original_stdout = sys.stdout
_original_stderr = sys.stderr
_capture_installed = False


class _CapturedStream:
    """把已有 print/loguru 输出原样送到终端，并逐行复制到会话日志。"""

    def __init__(self, original: TextIO, stream_name: str) -> None:
        self.original = original
        self.stream_name = stream_name
        self._local = threading.local()

    def write(self, value: str) -> int:
        written = self.original.write(value)
        buffer = getattr(self._local, "buffer", "") + value
        lines = buffer.split("\n")
        self._local.buffer = lines.pop()
        for line in lines:
            SESSION_LOG.add(line, stream=self.stream_name)
        return written

    def flush(self) -> None:
        self.original.flush()

    def isatty(self) -> bool:
        return bool(getattr(self.original, "isatty", lambda: False)())

    @property
    def encoding(self) -> str | None:
        return getattr(self.original, "encoding", None)

    def fileno(self) -> int:
        return self.original.fileno()


def install_stream_capture() -> None:
    global _capture_installed
    if _capture_installed:
        return
    sys.stdout = _CapturedStream(_original_stdout, "stdout")  # type: ignore[assignment]
    sys.stderr = _CapturedStream(_original_stderr, "stderr")  # type: ignore[assignment]
    _capture_installed = True


@contextmanager
def bind_log_context(**values: Any) -> Iterator[None]:
    current = dict(_log_context.get())
    current.update(
        {key: str(value) for key, value in values.items() if value not in (None, "")}
    )
    token = _log_context.set(current)
    try:
        yield
    finally:
        _log_context.reset(token)


def log_event(message: str, level: str = "INFO", **context: Any) -> None:
    """记录结构化事件；测试未安装 stdout 捕获时也能进入网页日志。"""

    entry = SESSION_LOG.add(message, level=level, context=context)
    if entry is None:
        return
    tags = []
    for key, label in (
        ("task_name", "任务"),
        ("job", "视频"),
        ("platform", "平台"),
        ("account_name", "账号"),
    ):
        if entry.get(key):
            tags.append(f"[{label}:{entry[key]}]")
    time_text = entry["timestamp"][11:23]
    console_line = f"[{time_text}] [{entry['level']}] {''.join(tags)} {message}\n"
    target = _original_stderr if entry["level"] == "ERROR" else _original_stdout
    target.write(console_line)
    target.flush()
