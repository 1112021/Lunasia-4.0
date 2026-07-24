# -*- coding: utf-8 -*-
"""Incremental Markdown fence parser for the chat UI.

The parser deliberately emits text immediately.  A fence is recognized only
when its complete line arrives; the consumer then retracts that one already
displayed line and inserts a code-card widget in its place.
"""

from __future__ import annotations

import re
from typing import Callable


_OPEN_FENCE = re.compile(r"^```([^\n]*)\n$")
_CLOSE_FENCE = re.compile(r"^```\s*\n$")


class StreamingFenceParser:
    """Parse text/code transitions while preserving immediate text rendering."""

    def __init__(
        self,
        *,
        on_text: Callable[[str], None],
        on_retract_text: Callable[[int], None],
        on_code_start: Callable[[str], None],
        on_code: Callable[[str], None],
        on_retract_code: Callable[[int], None],
        on_code_end: Callable[[], None],
    ) -> None:
        self._on_text = on_text
        self._on_retract_text = on_retract_text
        self._on_code_start = on_code_start
        self._on_code = on_code
        self._on_retract_code = on_retract_code
        self._on_code_end = on_code_end
        self._in_code = False
        self._current_line = ""

    @staticmethod
    def _language(info_line: str) -> str:
        tokens = info_line.strip().split()
        return (tokens[0].lower() if tokens else "text")

    def feed(self, text: str) -> None:
        """Consume only the newly received text."""
        if not text:
            return
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        pending = []
        pending_is_code = self._in_code

        def flush_pending() -> None:
            nonlocal pending
            if not pending:
                return
            rendered = "".join(pending)
            if pending_is_code:
                self._on_code(rendered)
            else:
                self._on_text(rendered)
            pending = []

        for char in text:
            # Events are batched within this incoming chunk, but never held
            # across chunks.  This avoids repainting a QPlainTextEdit per char.
            if pending and pending_is_code != self._in_code:
                flush_pending()
                pending_is_code = self._in_code
            pending.append(char)
            self._current_line += char

            # Fence state transitions are intentionally line-triggered.
            if char != "\n":
                continue

            flush_pending()
            line = self._current_line
            self._current_line = ""
            if not self._in_code:
                match = _OPEN_FENCE.fullmatch(line)
                if match:
                    self._on_retract_text(len(line))
                    self._on_code_start(self._language(match.group(1)))
                    self._in_code = True
            elif _CLOSE_FENCE.fullmatch(line):
                self._on_retract_code(len(line))
                self._on_code_end()
                self._in_code = False
            pending_is_code = self._in_code
        flush_pending()

    def finish(self) -> None:
        """Finish an interrupted stream; retain an unclosed code card."""
        if self._in_code:
            # A final closing fence commonly arrives without a trailing newline.
            # It has already been displayed in the code area, so remove it now.
            if self._current_line == "```":
                self._on_retract_code(3)
            self._on_code_end()
            self._in_code = False
        self._current_line = ""
