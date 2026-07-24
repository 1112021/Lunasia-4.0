#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
待办调度模块
使用轻量轮询线程触发到点任务。
"""

import datetime
import threading
import time
from typing import Callable, Dict


class TodoScheduler:
    """简单的线程轮询调度器。"""

    def __init__(self, on_trigger: Callable[[str], None], poll_interval_seconds: int = 2):
        self.on_trigger = on_trigger
        self.poll_interval_seconds = max(1, int(poll_interval_seconds))
        self._lock = threading.Lock()
        self._scheduled: Dict[str, datetime.datetime] = {}
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="TodoScheduler", daemon=True)
        self._thread.start()

    def schedule(self, task_id: str, trigger_iso: str) -> None:
        try:
            trigger_time = datetime.datetime.fromisoformat(trigger_iso)
        except Exception:
            print(f"⚠️ [TodoScheduler] 任务 {task_id} 触发时间解析失败: {trigger_iso}")
            return
        # 统一为本地时区 aware datetime，避免 naive/aware 比较异常
        if trigger_time.tzinfo is None:
            local_tz = datetime.datetime.now().astimezone().tzinfo
            trigger_time = trigger_time.replace(tzinfo=local_tz)
        with self._lock:
            self._scheduled[task_id] = trigger_time
        print(f"🗓️ [TodoScheduler] 已加入调度: {task_id} -> {trigger_time.isoformat(timespec='seconds')}")

    def unschedule(self, task_id: str) -> None:
        with self._lock:
            self._scheduled.pop(task_id, None)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                now = datetime.datetime.now().astimezone()
                due_task_ids = []
                with self._lock:
                    for task_id, trigger_time in list(self._scheduled.items()):
                        if trigger_time <= now:
                            due_task_ids.append(task_id)
                            self._scheduled.pop(task_id, None)

                for task_id in due_task_ids:
                    print(f"⏰ [TodoScheduler] 命中触发时间: {task_id}（now={now.isoformat(timespec='seconds')}）")
                    try:
                        threading.Thread(
                            target=self.on_trigger,
                            args=(task_id,),
                            name=f"TodoTrigger-{task_id}",
                            daemon=True,
                        ).start()
                    except Exception:
                        print(f"⚠️ [TodoScheduler] 启动触发线程失败: {task_id}")
                        pass
            except Exception:
                # 调度主循环容错：单次异常不应导致线程退出
                print("⚠️ [TodoScheduler] 调度循环出现异常，已自动忽略并继续运行")
                pass
            time.sleep(self.poll_interval_seconds)

