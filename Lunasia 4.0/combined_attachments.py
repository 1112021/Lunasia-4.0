# -*- coding: utf-8 -*-
"""组合发送：附件数据结构、校验与文件提取。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v", ".3gp"}
FILE_EXTS = {
    ".pdf", ".csv", ".xlsx", ".xls", ".docx", ".doc",
    ".py", ".java", ".js", ".jsx", ".ts", ".tsx", ".cpp", ".c", ".h", ".hpp", ".go", ".rs",
}

MAX_IMAGES = 5
MAX_VIDEOS = 1
MAX_FILES = 5
SAFE_VIDEO_MB = 8
MAX_VIDEO_DURATION_SEC = 30
MAX_VIDEO_SIZE_MB = 50


@dataclass
class CombinedAttachments:
    """待发送附件集合。"""

    image_paths: List[str] = field(default_factory=list)
    video_paths: List[str] = field(default_factory=list)
    file_paths: List[str] = field(default_factory=list)
    user_text: str = ""

    def has_images(self) -> bool:
        return bool(self.image_paths)

    def has_video(self) -> bool:
        return bool(self.video_paths)

    def has_files(self) -> bool:
        return bool(self.file_paths)

    def is_empty(self) -> bool:
        return not (self.has_images() or self.has_video() or self.has_files())

    def total_image_bytes(self) -> int:
        total = 0
        for p in self.image_paths:
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
        return total

    def image_batch_mode(self, config: dict) -> str:
        """single | sequential"""
        max_mb = float(config.get("vision_multi_image_batch_max_mb", 4))
        total_mb = self.total_image_bytes() / (1024 * 1024)
        if len(self.image_paths) <= 1:
            return "single"
        if total_mb <= max_mb:
            return "single"
        return "sequential"


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def classify_path(path: str) -> str:
    ext = _ext(path)
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in FILE_EXTS:
        return "file"
    return "unknown"


def validate_video_for_pending(path: str) -> Tuple[bool, str]:
    if not os.path.isfile(path):
        return False, "文件不存在"
    try:
        size_mb = os.path.getsize(path) / (1024 * 1024)
        if size_mb > MAX_VIDEO_SIZE_MB:
            return False, "文件内容过大"
    except OSError as e:
        return False, str(e)
    return True, ""


def video_needs_segmentation(path: str) -> Tuple[bool, str]:
    """与 process_video 阈值一致：时长>30s 或 原始>8MB 或 >50MB。"""
    if not os.path.isfile(path):
        return False, "文件不存在"
    try:
        size = os.path.getsize(path)
        size_mb = size / (1024 * 1024)
        if size_mb > MAX_VIDEO_SIZE_MB:
            return True, f"视频超过 {MAX_VIDEO_SIZE_MB}MB"
        if size_mb > SAFE_VIDEO_MB:
            return True, f"视频超过 {SAFE_VIDEO_MB}MB 安全阈值"
        try:
            import cv2

            cap = cv2.VideoCapture(path)
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                duration = frame_count / fps if fps > 0 else 0
                cap.release()
                if duration > MAX_VIDEO_DURATION_SEC:
                    return True, f"视频时长超过 {MAX_VIDEO_DURATION_SEC}s"
        except ImportError:
            pass
        except Exception:
            pass
    except OSError:
        return False, "无法读取视频"
    return False, ""


def format_user_chat_line(user_text: str, att: CombinedAttachments) -> str:
    parts: List[str] = []
    text = (user_text or "").strip()
    if text:
        parts.append(text)
    labels: List[str] = []
    if att.image_paths:
        names = ", ".join(os.path.basename(p) for p in att.image_paths)
        labels.append(f"上传图片: {names}")
    if att.video_paths:
        names = ", ".join(os.path.basename(p) for p in att.video_paths)
        labels.append(f"上传视频: {names}")
    if att.file_paths:
        names = ", ".join(os.path.basename(p) for p in att.file_paths)
        labels.append(f"上传文件: {names}")
    if labels:
        if parts:
            parts.append("[" + " ".join(labels) + "]")
        else:
            parts.extend(labels)
    return " ".join(parts) if parts else "请根据附件内容回答。"


def format_planner_attachment_hint(att: CombinedAttachments, config: dict) -> str:
    lines = ["【本轮组合发送附件】"]
    if att.image_paths:
        mode = att.image_batch_mode(config)
        total_mb = att.total_image_bytes() / (1024 * 1024)
        names = ", ".join(os.path.basename(p) for p in att.image_paths)
        lines.append(f"- 图片×{len(att.image_paths)}：{names}（batch_mode={mode}，总大小约 {total_mb:.2f}MB）")
    if att.video_paths:
        v = att.video_paths[0]
        seg, reason = video_needs_segmentation(v)
        name = os.path.basename(v)
        lines.append(
            f"- 视频×1：{name}（需分割={'是' if seg else '否'}；{reason or '直传视觉'}）"
        )
    if att.file_paths:
        names = ", ".join(os.path.basename(p) for p in att.file_paths)
        lines.append(f"- 文件×{len(att.file_paths)}：{names}")
    lines.append(
        "- 附件已随本轮提交；禁止 analyze_image/analyze_video/analyze_file 读取旧 recent_*。"
        " 使用 combined_* 步骤完成本轮。"
    )
    return "\n".join(lines)


def extract_files_text(file_paths: List[str], config: dict) -> str:
    if not file_paths:
        return ""
    max_chars = int(config.get("combined_send_file_extract_max_chars", 18000))
    from file_analysis_tool import FileAnalysisTool

    tool = FileAnalysisTool()
    chunks: List[str] = []
    used = 0
    truncated = False
    for fp in file_paths:
        name = os.path.basename(fp)
        try:
            result = tool.analyze_file(fp)
            if not result.success:
                body = f"（解析失败: {result.error}）"
            else:
                body = result.content or result.summary or ""
        except Exception as e:
            body = f"（解析异常: {e}）"
        header = f"\n--- 文件: {name} ---\n"
        piece = header + body
        if used + len(piece) > max_chars:
            remain = max_chars - used
            if remain > 100:
                chunks.append(piece[:remain] + "\n...(已截断)")
            truncated = True
            break
        chunks.append(piece)
        used += len(piece)
    text = "".join(chunks).strip()
    if truncated:
        text += "\n\n（部分文件内容因长度限制已截断）"
    return text


def register_recent_on_agent(agent, att: CombinedAttachments, file_extract: str = "") -> None:
    """发送前注册 recent_* 元数据（分析结果稍后填充）。"""
    agent.combined_send_payload = att
    if att.image_paths:
        agent.recent_image_analysis = {
            "image_path": att.image_paths[0],
            "image_paths": list(att.image_paths),
            "image_name": os.path.basename(att.image_paths[0]),
            "analysis": "",
            "combined": True,
        }
    else:
        agent.recent_image_analysis = None

    if att.video_paths:
        seg, _ = video_needs_segmentation(att.video_paths[0])
        agent.recent_video_analysis = {
            "video_path": att.video_paths[0],
            "video_name": os.path.basename(att.video_paths[0]),
            "analysis": "",
            "is_segmented": seg,
            "combined": True,
        }
    else:
        agent.recent_video_analysis = None

    if att.file_paths:
        agent.recent_file_analysis = {
            "file_name": ", ".join(os.path.basename(p) for p in att.file_paths),
            "file_paths": list(att.file_paths),
            "file_type": "COMBINED",
            "content": file_extract,
            "metadata": {"combined": True, "count": len(att.file_paths)},
            "summary": "",
            "analysis": "",
            "combined": True,
        }
    else:
        agent.recent_file_analysis = None
