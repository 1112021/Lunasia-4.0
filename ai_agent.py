# -*- coding: utf-8 -*-
"""
AI代理核心模块
处理用户输入、工具调用和AI响应生成
"""

import datetime
import re
import openai
import subprocess
import os
import threading
from functools import wraps
from typing import Dict, Any, Optional
from config import load_config
from utils import get_location, scan_windows_apps, open_website, open_application
from weather import WeatherTool
from amap_tool import AmapTool
from memory_lake import MemoryLake
from mcp_server import LocalMCPServer
from search_tool import search_web as web_search
from search_summary_agent import process_search_result, should_search
from search_query_extractor import extract_search_query
from playwright_tool import playwright_search, playwright_open_url, playwright_interact, playwright_open_website_headed
from file_analysis_tool import FileAnalysisTool
from webpage_agent_unified import execute_webpage_task_sync
from todo_service import TodoService


def _with_vision_tts_pause(func):
    """Unload local F5-TTS around vision work to avoid VRAM contention."""
    @wraps(func)
    def wrapped(self, *args, **kwargs):
        self.pause_local_tts_for_vision()
        try:
            return func(self, *args, **kwargs)
        finally:
            self.resume_local_tts_after_vision()

    return wrapped


class MCPTools:
    """MCP工具管理类"""
    
    def __init__(self):
        self.server = LocalMCPServer()
    
    def execute_mcp_command(self, tool_name, **params):
        """执行MCP命令（同步版本）"""
        try:
            # 重新加载自定义工具
            self.server.reload_custom_tools()
            result = self.server.call_tool(tool_name, **params)
            return result
        except Exception as e:
            return f"MCP命令执行失败: {str(e)}"
    
    async def execute_mcp_command_async(self, tool_name, **params):
        """执行MCP命令（异步版本）"""
        try:
            # 重新加载自定义工具
            self.server.reload_custom_tools()
            result = self.server.call_tool(tool_name, **params)
            return result
        except Exception as e:
            return f"MCP命令执行失败: {str(e)}"
    
    def list_available_tools(self):
        """列出可用工具（同步版本）"""
        try:
            return self.server.list_tools()
        except Exception as e:
            print(f"获取工具列表失败: {str(e)}")
            return []
    
    async def list_available_tools_async(self):
        """列出可用工具（异步版本）"""
        try:
            return self.server.list_tools()
        except Exception as e:
            print(f"获取工具列表失败: {str(e)}")
            return []
    
    def list_tools(self):
        """同步版本的工具列表获取"""
        try:
            return self.server.list_tools()
        except Exception as e:
            print(f"获取工具列表失败: {str(e)}")
            return []
    
    def get_tool_info(self, tool_name):
        """获取工具信息（同步版本）"""
        try:
            return self.server.get_tool_info(tool_name)
        except Exception as e:
            print(f"获取工具信息失败: {str(e)}")
            return {}
    
    async def get_tool_info_async(self, tool_name):
        """获取工具信息（异步版本）"""
        try:
            return self.server.get_tool_info(tool_name)
        except Exception as e:
            print(f"获取工具信息失败: {str(e)}")
            return {}

class AIAgent:
    """露尼西亚AI核心"""
    
    def __init__(self, config):
        self.name = "露尼西亚"
        self.role = "游戏少女前线中威廉的姐姐"
        self.config = config
        # MainWindow attaches a thread-safe signal bridge here. Agent layers
        # emit concise structured workflow events through this optional hook.
        self.workflow_event_callback = None
        self.memory_lake = MemoryLake(config=config)
        self.developer_mode = False
        self.current_topic = ""
        self.conversation_history = []
        self._generation_cancel_event = threading.Event()
        self._generation_streamed_text = ""
        self._regeneration_mode = False
        self.last_regeneration_memory_notice = ""
        self.location = get_location()
        self.last_save_date = None
        
        # 本次程序运行时的对话记录
        self.session_conversations = []
        
        # 最近生成的代码缓存
        self.last_generated_code = None

        # 可用的工具
        self.tools = {
            "天气": WeatherTool.get_weather,
            "网页打开与自动化操作": self._open_website_wrapper,
            "打开应用": open_application,
            "获取时间": self._get_current_time,
            "搜索": web_search,
        }
        
        # 初始化MCP工具
        self.mcp_server = LocalMCPServer()
        self.mcp_tools = MCPTools()
        
        # 统一网页Agent已改为函数调用方式，无需初始化
        # self.webpage_agent = WebpageAgent(config)  # 旧版已废弃
        
        
        # 初始化文件分析工具
        self.file_analyzer = FileAnalysisTool(config)
        print("📄 文件分析工具已初始化 (PDF、CSV、Excel、Word、代码)")
        
        # 文件分析上下文记忆（最近分析的文件）
        self.recent_file_analysis = None  # 存储最近一次的文件分析结果
        # 图片分析上下文记忆（最近分析的图片）
        self.recent_image_analysis = None  # 存储最近一次的图片分析结果（包含图片路径和内容）
        # 视频分析上下文记忆（最近分析的视频）
        self.recent_video_analysis = None  # 存储最近一次的视频分析结果（包含视频路径和内容）
        # 组合发送：本轮待处理附件（由 process_combined_send 设置）
        self.combined_send_payload = None
        self._combined_file_extract = ""
        
        # 框架ReAct Agent（默认启用，轻量级任务规划）
        from framework_react_agent import FrameworkReActAgent
        from llm_spec import get_config_spec
        plan_spec = get_config_spec(config, "framework_plan_model")
        self.framework_agent = FrameworkReActAgent(self)
        print(f"🧠 框架ReAct模式已启用（使用模型：{plan_spec.display_name()}）")

        # 待办与通讯服务
        try:
            self.todo_service = TodoService(
                config=self.config,
                llm_client_getter=self._get_llm_client,
                memory_event_callback=self._record_todo_memory_event,
            )
            print("🗓️ 待办与通讯服务已启用")
        except Exception as e:
            print(f"⚠️ 待办与通讯服务初始化失败: {e}")
            self.todo_service = None

        # 网站和应用映射
        self.website_map = config.get("website_map", {})

        # 合并扫描到的应用和手动添加的应用
        self.app_map = scan_windows_apps()
        self.app_map.update(config.get("app_map", {}))

        # 预加载应用数
        self.app_count = len(self.app_map)

        # 初始化TTS管理器（支持 Azure / Qwen3 / 本地 F5-TTS）
        try:
            provider = config.get("tts_provider", "azure")
            azure_key = config.get("azure_tts_key", "")
            azure_region = config.get("azure_region", "eastasia")
            dashscope_key = config.get("dashscope_key", "")
            if (
                provider == "f5tts"
                or azure_key
                or (provider == "qwen3" and dashscope_key)
            ):
                from tts_manager import TTSManager
                self.tts_manager = TTSManager(
                    azure_key=azure_key,
                    region=azure_region,
                    provider=provider,
                    dashscope_key=dashscope_key,
                    config=config,
                )
                voice = config.get(
                    "tts_voice",
                    "zh-CN-XiaoxiaoNeural" if provider == "azure" else "Cherry",
                )
                self.tts_manager.set_voice(voice)
                if config.get("tts_enabled"):
                    self.tts_manager.set_speaking_rate(config.get("tts_speaking_rate", 1.0))
                print("✅ TTS管理器初始化成功")
            else:
                self.tts_manager = None
                print("ℹ️ 未配置TTS密钥，TTS功能已禁用")
        except Exception as e:
            print(f"⚠️ TTS管理器初始化失败: {str(e)}")
            self.tts_manager = None

    def reset_generation_cancel(self):
        """Prepare cancellation state for a new user-initiated run."""
        self._generation_cancel_event.clear()
        self._generation_streamed_text = ""

    def cancel_generation(self):
        """Request cooperative cancellation; active tools finish their current call."""
        self._generation_cancel_event.set()
        self.stop_tts()

    def is_generation_cancelled(self):
        return self._generation_cancel_event.is_set()

    @staticmethod
    def _interrupted_text(partial=""):
        partial = str(partial or "").rstrip()
        if partial.endswith("（输出被打断）"):
            return partial
        return f"{partial}\n（输出被打断）" if partial else "（输出被打断）"

    def interrupted_response(self):
        return self._interrupted_text(self._generation_streamed_text)

    def _tracked_stream_callback(self, stream_callback):
        if stream_callback is None:
            return None

        def tracked(accumulated):
            self._generation_streamed_text = str(accumulated or "")
            stream_callback(accumulated)

        tracked._cancel_event = self._generation_cancel_event
        return tracked

    def _record_interrupted_turn_if_needed(
        self,
        user_input,
        response,
        *,
        skip_memory_save=False,
        skip_history_append=False,
        is_first_response_after_intro=False,
    ):
        """Record an interrupted framework turn exactly once."""
        if not skip_memory_save:
            exists = any(
                conv.get("user_input") == user_input
                and conv.get("ai_response") == response
                for conv in self.session_conversations
            )
            if not exists:
                self._add_session_conversation(user_input, response)
                self._update_memory_lake(
                    user_input, response, is_first_response_after_intro
                )
        history_line = f"{self.name}: {response}"
        if (
            not skip_history_append
            and (not self.conversation_history or self.conversation_history[-1] != history_line)
        ):
            self.conversation_history.append(history_line)

    def _replace_session_conversation(self, user_input, old_response, new_response):
        for conv in reversed(self.session_conversations):
            if (
                conv.get("user_input") == user_input
                and conv.get("ai_response") == old_response
            ):
                conv["ai_response"] = new_response
                conv["full_text"] = (
                    f"指挥官: {user_input}\n露尼西亚: {new_response}"
                )
                conv["timestamp"] = datetime.datetime.now().strftime("%H:%M:%S")
                return True
        self._add_session_conversation(user_input, new_response)
        return False

    def _replace_session_conversation_edited(
        self, old_user_input, old_response, new_user_input, new_response
    ):
        for conv in reversed(self.session_conversations):
            if (
                conv.get("user_input") == old_user_input
                and conv.get("ai_response") == old_response
            ):
                conv["user_input"] = new_user_input
                conv["ai_response"] = new_response
                conv["full_text"] = (
                    f"指挥官: {new_user_input}\n露尼西亚: {new_response}"
                )
                conv["timestamp"] = datetime.datetime.now().strftime("%H:%M:%S")
                return True
        self._add_session_conversation(new_user_input, new_response)
        return False

    def regenerate_last_response(
        self,
        user_input,
        old_response,
        *,
        attachments=None,
        stream_callback=None,
    ):
        """Regenerate the latest turn without appending a duplicate user turn."""
        self.last_regeneration_memory_notice = ""
        old_line = f"{self.name}: {old_response}"
        if self.conversation_history and self.conversation_history[-1] == old_line:
            self.conversation_history.pop()

        self._regeneration_mode = True
        try:
            try:
                if attachments is not None and not attachments.is_empty():
                    response = self.process_combined_send(
                        attachments,
                        stream_callback=stream_callback,
                        skip_history_append=True,
                        skip_memory_save=True,
                    )
                else:
                    response = self.process_command(
                        user_input,
                        skip_memory_save=True,
                        skip_history_append=True,
                        stream_callback=stream_callback,
                    )
            except Exception:
                if (
                    not self.conversation_history
                    or self.conversation_history[-1] != old_line
                ):
                    self.conversation_history.append(old_line)
                raise
        finally:
            self._regeneration_mode = False

        response = str(response or "")
        self.conversation_history.append(f"{self.name}: {response}")
        self._replace_session_conversation(user_input, old_response, response)
        memory_result = self.memory_lake.replace_latest_conversation(
            user_input,
            response,
            old_ai_response=old_response,
        )
        memory_status = memory_result.get("status")
        if memory_status == "compressed":
            self.last_regeneration_memory_notice = (
                "该轮已写入识底深湖且记忆已压缩，界面已更新但长期记忆未同步。"
            )
        elif memory_status == "not_found":
            # The old turn was not in MemoryLake (for example a direct tool
            # response), so the regenerated turn becomes a new buffered turn.
            self._update_memory_lake(user_input, response)
        return response

    def regenerate_edited_turn(
        self,
        old_user_input,
        old_response,
        new_user_input,
        *,
        attachments=None,
        stream_callback=None,
    ):
        """Replace the latest user+assistant turn after editing the user text."""
        self.last_regeneration_memory_notice = ""
        old_user_line = f"指挥官: {old_user_input}"
        old_assistant_line = f"{self.name}: {old_response}"
        popped_assistant = bool(
            self.conversation_history
            and self.conversation_history[-1] == old_assistant_line
        )
        if popped_assistant:
            self.conversation_history.pop()
        popped_user = bool(
            self.conversation_history
            and self.conversation_history[-1] == old_user_line
        )
        if popped_user:
            self.conversation_history.pop()

        self._regeneration_mode = True
        try:
            try:
                if attachments is not None and not attachments.is_empty():
                    response = self.process_combined_send(
                        attachments,
                        stream_callback=stream_callback,
                        skip_history_append=True,
                        skip_memory_save=True,
                    )
                else:
                    response = self.process_command(
                        new_user_input,
                        skip_memory_save=True,
                        skip_history_append=True,
                        stream_callback=stream_callback,
                    )
            except Exception:
                if popped_user:
                    self.conversation_history.append(old_user_line)
                if popped_assistant:
                    self.conversation_history.append(old_assistant_line)
                raise
        finally:
            self._regeneration_mode = False

        response = str(response or "")
        self.conversation_history.append(f"指挥官: {new_user_input}")
        self.conversation_history.append(f"{self.name}: {response}")
        self._replace_session_conversation_edited(
            old_user_input,
            old_response,
            new_user_input,
            response,
        )
        memory_result = self.memory_lake.replace_latest_conversation(
            old_user_input,
            response,
            new_user_input=new_user_input,
            old_ai_response=old_response,
        )
        memory_status = memory_result.get("status")
        if memory_status == "compressed":
            self.last_regeneration_memory_notice = (
                "该轮已写入识底深湖且记忆已压缩，界面已更新但长期记忆未同步。"
            )
        elif memory_status == "not_found":
            self._update_memory_lake(new_user_input, response)
        return response

    def _get_llm_client(self, model=None, config_key=None):
        """
        获取 LLM 客户端（经 llm_router 统一路由）。

        Returns:
            tuple: (client, model_name) 或 None if failed
        """
        from llm_router import get_llm_client_legacy
        return get_llm_client_legacy(
            self.config,
            legacy_model=model,
            config_key=config_key,
        )

    def process_command(self, user_input, is_first_response_after_intro=False, skip_framework=False, suppress_tool_routing=False, skip_memory_save=False, skip_history_append=False, stream_callback=None):
        """处理用户命令。stream_callback 若提供则用于流式显示，每段累积内容会调用 callback(accumulated_text)。"""
        # 🔒 检查安全测试确认命令
        if user_input.strip() == "确认执行安全测试":
            if hasattr(self, 'pending_security_commands') and self.pending_security_commands:
                commands = self.pending_security_commands
                self.pending_security_commands = None  # 清除待执行命令
                return self._execute_security_commands(commands)
            else:
                return "（疑惑地看着您）指挥官，没有待执行的安全测试命令。"
        
        # 检查开发者模式命令
        if user_input.lower() == "developer mode":
            self.developer_mode = True
            return "(开发者模式已激活)"
        elif user_input.lower() == "exit developer mode":
            self.developer_mode = False
            return "(开发者模式已关闭)"

        # 检查"记住这个时刻"指令
        if self._is_remember_moment_command(user_input):
            return self._handle_remember_moment(user_input)

        # 待办/通讯本轮是否由 TodoService 直接应答（用于跳过识底深湖「三轮对话」缓冲）
        self._response_from_todo_comm = False

        # 每条用户消息从主入口进入时清除残留的抑制标记（框架路径不会走下方 finally 块，旧 True 会导致待办工具一直被跳过）
        if not skip_framework:
            self._suppress_tool_routing = False

        # 记录对话历史
        if not skip_history_append:
            self.conversation_history.append(f"指挥官: {user_input}")

        stream_callback = self._tracked_stream_callback(stream_callback)

        # 流式 TTS：提前构建 actual_stream_callback，以便框架 pass_to_main_agent 时也能流式输出
        use_streaming_tts = (
            stream_callback is not None
            and hasattr(self, 'tts_manager') and self.tts_manager
            and self.config.get("tts_enabled", False)
            and self.tts_manager.is_available()
        )
        if use_streaming_tts:
            self.tts_manager.start_tts_stream()
            self._tts_sent_up_to = 0
            def _tts_stream_wrapper(accumulated):
                stream_callback(accumulated)
                rest = accumulated[self._tts_sent_up_to:]
                consumed = 0
                i = 0
                while i < len(rest):
                    found = False
                    for sep in ['。', '！', '？', '\n']:
                        j = rest.find(sep, i)
                        if j != -1:
                            sentence = rest[i:j + 1].strip()
                            if sentence:
                                self.tts_manager.enqueue_sentence(sentence)
                            consumed += (j - i + 1)
                            i = j + 1
                            found = True
                            break
                    if not found:
                        break
                self._tts_sent_up_to += consumed
            actual_stream_callback = _tts_stream_wrapper
            actual_stream_callback._cancel_event = self._generation_cancel_event
        else:
            actual_stream_callback = stream_callback

        # 🔥 框架ReAct模式（默认启用，在常规处理之前尝试）；传入 stream_callback 以便 pass_to_main_agent 时流式+TTS
        if not skip_framework and self.framework_agent:
            framework_response = self.framework_agent.process_command(user_input, stream_callback=actual_stream_callback)
            if self.is_generation_cancelled():
                framework_response = self.interrupted_response()
                self._record_interrupted_turn_if_needed(
                    user_input,
                    framework_response,
                    skip_memory_save=skip_memory_save,
                    skip_history_append=skip_history_append,
                    is_first_response_after_intro=is_first_response_after_intro,
                )
                return framework_response
            if framework_response:
                # 框架Agent成功处理
                if not skip_history_append:
                    history_line = f"{self.name}: {framework_response}"
                    if (
                        not self.conversation_history
                        or self.conversation_history[-1] != history_line
                    ):
                        self.conversation_history.append(history_line)
                self._finalize_tts_response(
                    framework_response, use_streaming_tts
                )
                return framework_response
            # 如果返回None，说明是简单对话，继续使用标准流程

        # 检查威廉关键词
        if "威廉" in user_input:
            self.william_count = getattr(self, 'william_count', 0) + 1
            if self.william_count > 1:
                response = "在你面前的明明是我，为什么总是提到威廉呢？"
              
                return response
            else:
                response = "威廉是我的弟弟，他很好。"
               
                return response

        # 检查是否有待迁移的记忆数据
        migration_status = self.memory_lake.get_migration_status()
        if migration_status:
            # 如果用户回答的是迁移确认
            if user_input.strip() in ['是', '否', 'yes', 'no', 'y', 'n', '确认', '取消', '同意', '拒绝']:
                migration_response = self.memory_lake.confirm_migration(user_input)
                return migration_response
            else:
                # 主动询问用户是否迁移
                old_count = migration_status["old_memory_count"]
                current_count = migration_status["current_memory_count"]
                migration_message = f"指挥官，我检测到旧版本的记忆文件，其中包含 {old_count} 条历史记忆。"
                migration_message += f"当前系统中有 {current_count} 条记忆。\n\n"
                migration_message += "是否将旧记忆迁移到新的智能回忆系统中？"
                migration_message += "迁移后您将获得更精准的记忆检索和四维度智能回忆功能。\n\n"
                migration_message += "请回答'是'或'否'。"
                return migration_message
        
        # 分析用户输入，判断是否需要获取位置和天气信息
        context_info = self._get_context_info(user_input)
        
        # 生成AI响应（包含上下文信息）；actual_stream_callback 已在上方构建
        # 在需要时临时抑制工具路由，避免在框架 pass_to_main_agent 总结阶段重复打开网页/应用。
        # 显式 suppress_tool_routing=False 时必须放行（待办创建/修改依赖工具链），不能用 OR 把残留 True 又粘回去。
        original_suppress_flag = getattr(self, '_suppress_tool_routing', False)
        self._suppress_tool_routing = True if suppress_tool_routing else False
        try:
            response = self._generate_response_with_context(user_input, context_info, stream_callback=actual_stream_callback)
        finally:
            self._suppress_tool_routing = original_suppress_flag

        if self.is_generation_cancelled():
            response = self.interrupted_response()
        
        # 确保响应不为None
        if response is None:
            response = "抱歉，我没有理解您的意思，请重新表述一下。"

        # 待办/通讯走 _record_todo_memory_event(save_external_event)，不再计入 current_conversation 轮次
        skip_session_and_lake = skip_memory_save or getattr(self, "_response_from_todo_comm", False)
        if getattr(self, "_response_from_todo_comm", False):
            print("🗓️ 待办/通讯回复：跳过识底深湖对话轮次与会话条目录入（仍可通过外部事件记忆）")
        self._response_from_todo_comm = False
        
        # 记录本次会话的对话
        if not skip_session_and_lake:
            self._add_session_conversation(user_input, response)
        
        # 记录对话历史
        if not skip_history_append:
            self.conversation_history.append(f"{self.name}: {response}")
        
        # 更新记忆系统
        if not skip_session_and_lake:
            self._update_memory_lake(user_input, response, is_first_response_after_intro)

        # 如果TTS已启用，播放语音
        if (
            not self.is_generation_cancelled()
            and hasattr(self, 'tts_manager')
            and self.tts_manager
            and self.config.get("tts_enabled", False)
        ):
            try:
                if not self.tts_manager.is_available():
                    print("⚠️ TTS不可用，跳过语音播放")
                else:
                    import re
                    clean_text = re.sub(r'[（\(].*?[）\)]', '', response)
                    clean_text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s，。！？、；：""''（）]', '', clean_text)
                    clean_text = clean_text.strip()
                    if use_streaming_tts:
                        # 流式 TTS 已在回调中逐句推送，这里只把剩余未成句的文本收尾
                        remaining = response[self._tts_sent_up_to:]
                        clean_remaining = re.sub(r'[（\(].*?[）\)]', '', remaining)
                        clean_remaining = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s，。！？、；：""''（）]', '', clean_remaining).strip()
                        self.tts_manager.end_tts_stream(clean_remaining if clean_remaining else "")
                    elif clean_text and len(clean_text) > 0:
                        print(f"🎤 开始TTS播放: {clean_text[:50]}...")
                        try:
                            self.tts_manager.speak_text(clean_text)
                        except Exception as tts_error:
                            print(f"⚠️ TTS播放过程中出错: {str(tts_error)}")
                            import traceback
                            traceback.print_exc()
                    else:
                        print("⚠️ 清理后的文本为空，跳过TTS播放")
            except Exception as e:
                print(f"⚠️ TTS播放失败: {str(e)}")
                import traceback
                traceback.print_exc()
        else:
            print("ℹ️ TTS未启用或管理器不可用")

        return response

    def process_combined_send(
        self,
        att,
        stream_callback=None,
        skip_history_append=False,
        skip_memory_save=False,
    ):
        """组合发送：文本 + 附件一并提交。"""
        from combined_attachments import CombinedAttachments
        from combined_send_handler import setup_combined_payload

        if not isinstance(att, CombinedAttachments):
            raise TypeError("att 必须是 CombinedAttachments")

        chat_line = setup_combined_payload(self, att)
        stream_callback = self._tracked_stream_callback(stream_callback)

        use_streaming_tts = (
            stream_callback is not None
            and hasattr(self, "tts_manager")
            and self.tts_manager
            and self.config.get("tts_enabled", False)
            and self.tts_manager.is_available()
        )
        if use_streaming_tts:
            self.tts_manager.start_tts_stream()
            self._tts_sent_up_to = 0

            def _tts_stream_wrapper(accumulated):
                stream_callback(accumulated)
                rest = accumulated[self._tts_sent_up_to :]
                consumed = 0
                i = 0
                while i < len(rest):
                    found = False
                    for sep in ["。", "！", "？", "\n"]:
                        j = rest.find(sep, i)
                        if j != -1:
                            sentence = rest[i : j + 1].strip()
                            if sentence:
                                self.tts_manager.enqueue_sentence(sentence)
                            consumed += j - i + 1
                            i = j + 1
                            found = True
                            break
                    if not found:
                        break
                self._tts_sent_up_to += consumed

            actual_stream_callback = _tts_stream_wrapper
            actual_stream_callback._cancel_event = self._generation_cancel_event
        else:
            actual_stream_callback = stream_callback

        if not skip_history_append:
            self.conversation_history.append(f"指挥官: {chat_line}")
        try:
            if self.framework_agent:
                response = self.framework_agent.process_combined_command(
                    chat_line, stream_callback=actual_stream_callback
                )
            else:
                response = None
            if response is None:
                response = self.process_command(
                    chat_line,
                    stream_callback=actual_stream_callback,
                    skip_history_append=True,
                    skip_memory_save=True,
                )
        finally:
            self.combined_send_payload = None
            self._combined_file_extract = ""

        if response is None:
            response = "抱歉，处理附件时出现问题，请重试。"
        if self.is_generation_cancelled():
            response = self.interrupted_response()
        if not skip_history_append:
            self.conversation_history.append(f"{self.name}: {response}")
        if not skip_memory_save:
            self._add_session_conversation(chat_line, response)
            self._update_memory_lake(chat_line, response)

        if (
            not self.is_generation_cancelled()
            and hasattr(self, "tts_manager")
            and self.tts_manager
            and self.config.get("tts_enabled", False)
        ):
            try:
                if self.tts_manager.is_available() and use_streaming_tts:
                    import re

                    remaining = response[self._tts_sent_up_to :]
                    clean_remaining = re.sub(r"[（\(].*?[）\)]", "", remaining)
                    clean_remaining = re.sub(
                        r'[^\u4e00-\u9fa5a-zA-Z0-9\s，。！？、；：""''（）]',
                        "",
                        clean_remaining,
                    ).strip()
                    self.tts_manager.end_tts_stream(
                        clean_remaining if clean_remaining else ""
                    )
            except Exception as e:
                print(f"⚠️ 组合发送 TTS 收尾失败: {e}")

        return response

    def _open_application(self, app_name: str) -> str:
        """打开本地应用程序（兼容App映射与直接名称）。
        优先使用`self.app_map`中的已知应用路径；否则回退到系统路径解析。
        """
        try:
            if not app_name:
                return "❌ 未提供应用名称"

            print(f"🔍 [应用启动] 尝试打开应用: '{app_name}'")
            print(f"🔍 [应用启动] 当前app_map中有 {len(self.app_map)} 个应用")

            
            target = None
            app_name_lower = app_name.lower()
            matched_candidates = []
            
            for key, path in self.app_map.items():
                key_lower = key.lower()
                # 收集所有可能的匹配项
                if app_name_lower == key_lower:
                    # 完全匹配（最高优先级）
                    matched_candidates.append((key, path, 0, len(key)))
                elif app_name_lower in key_lower or key_lower in app_name_lower:
                    # 包含匹配
                    matched_candidates.append((key, path, 1, len(key)))
            
            # 优先级排序：完全匹配 > 最短匹配
            # 过滤掉"卸载"、"uninstall"等卸载程序
            filtered_candidates = [
                (key, path, priority, length) 
                for key, path, priority, length in matched_candidates
                if not any(exclude in key.lower() for exclude in ['卸载', 'uninstall', 'remove'])
            ]
            
            # 如果过滤后没有结果，使用原始候选列表
            if not filtered_candidates:
                filtered_candidates = matched_candidates
            
            # 选择最佳匹配：先按优先级排序（完全匹配优先），再按长度排序（最短优先）
            if filtered_candidates:
                filtered_candidates.sort(key=lambda x: (x[2], x[3]))
                best_match = filtered_candidates[0]
                target = best_match[1]
                print(f"✅ [应用启动] 在app_map中找到: '{best_match[0]}' -> '{best_match[1]}'")
                if len(filtered_candidates) > 1:
                    print(f"ℹ️ [应用启动] 其他匹配项: {[c[0] for c in filtered_candidates[1:3]]}")

            # 直接调用系统打开逻辑
            if target:
                print(f"🚀 [应用启动] 使用路径启动: {target}")
                result = open_application(target)
            else:
                print(f"⚠️ [应用启动] app_map中未找到，尝试直接启动: {app_name}")
                # 尝试使用Windows的start命令
                import subprocess
                try:
                    subprocess.Popen(f'start "" "{app_name}"', shell=True)
                    result = f"✅ 已启动应用程序: {app_name}"
                    print(f"✅ [应用启动] 使用start命令启动成功")
                except Exception as e:
                    print(f"❌ [应用启动] start命令失败: {e}")
                    result = f"❌ 未找到应用: {app_name}。请在设置中配置应用路径。"

            return result if isinstance(result, str) else "✅ 已尝试启动应用"
        except Exception as e:
            print(f"❌ [应用启动] 异常: {str(e)}")
            return f"❌ 打开应用失败：{str(e)}"

    def _add_session_conversation(self, user_input, ai_response):
        """添加本次会话的对话记录"""
     
        # 检查是否已经存在相同的对话
        for existing_conv in self.session_conversations:
            if (existing_conv.get('user_input') == user_input and 
                existing_conv.get('ai_response') == ai_response):
                print(f"⚠️ 检测到重复对话，跳过添加到会话记录: {user_input[:30]}...")
                return
        
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.session_conversations.append({
            "timestamp": timestamp,
            "user_input": user_input,
            "ai_response": ai_response,
            "full_text": f"指挥官: {user_input}\n露尼西亚: {ai_response}",
            "saved": False  # 标记为未保存，当保存到记忆系统时会改为True
        })
        
        print(f"✅ 添加对话到会话记录: {user_input[:30]}... (当前共{len(self.session_conversations)}条)")

    def _mark_conversation_as_saved(self, user_input, ai_response):
        """标记对话为已保存"""
        # 在session_conversations中找到匹配的对话并标记为已保存
        for conv in self.session_conversations:
            if (conv.get('user_input') == user_input and 
                conv.get('ai_response') == ai_response and 
                not conv.get('saved', False)):
                conv['saved'] = True
                print(f"✅ 标记对话为已保存: {user_input[:50]}...")
                break

    def _extract_keywords(self, text):
        """提取关键词"""
        keywords = []
        # 扩展关键词列表
        common_words = [
            '天气', '时间', '搜索', '打开', '计算', '距离', '系统', '文件', '笔记', 
            '穿衣', '出门', '建议', '教堂', '景点', '历史', '参观', '路线', '法兰克福',
            '大教堂', '老城区', '游客', '高峰期', '规划', '咨询', '询问', '问过', '讨论过',
            '提到过', '说过', '介绍过', '推荐过', '建议过', '介绍', '一下', '什么', '哪里',
            '位置', '地址', '建筑', '标志性', '历史', '文化', '旅游', '游览', '参观'
        ]
        
        for word in common_words:
            if word in text:
                keywords.append(word)
        
        return keywords

    def _ai_generate_website_url(self, site_name):
        """使用AI生成网站URL"""
        try:
            from llm_spec import get_config_spec

            spec = get_config_spec(self.config, "search_intent_model")
            llm_result = self._get_llm_client(config_key="search_intent_model")
            if not llm_result:
                print("⚠️ 无法获取LLM客户端，无法使用AI生成URL")
                return None
            
            client, model = llm_result
            print(f"🔍 [URL生成] 模型: {spec.display_name()}, 网站名: '{site_name}'")
            
            # 构建AI提示词
            url_prompt = f"""网站名称: {site_name}

请返回这个网站的官方网址（必须以https://开头）。

常见网站对应表：
- 哔哩哔哩/B站/bilibili → https://www.bilibili.com
- 知乎 → https://www.zhihu.com
- github/GitHub → https://github.com
- 百度 → https://www.baidu.com
- 谷歌/Google → https://www.google.com
- 必应/Bing → https://cn.bing.com
- 抖音 → https://www.douyin.com
- 微博 → https://weibo.com
- 淘宝 → https://www.taobao.com
- 京东 → https://www.jd.com

只返回URL，不要有任何解释："""
            
            # 调用AI生成URL
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是一个网站URL生成助手，专门用于根据网站名称生成官方网址。请只返回URL，不要有任何其他内容。"},
                    {"role": "user", "content": url_prompt}
                ],
                max_tokens=100,
                temperature=0.1,
                timeout=10
            )
            
            url = response.choices[0].message.content.strip()
            print(f"🔍 [URL生成] AI原始返回: '{url}'")
            
            # 清理可能的多余内容（如果AI返回了解释性文字）
            # 提取URL（查找http开头的部分）
            import re
            url_match = re.search(r'https?://[^\s]+', url)
            if url_match:
                url = url_match.group(0)
                # 移除末尾可能的标点符号
                url = url.rstrip('.,;:!?)。，；：！？）')
                print(f"🔍 [URL生成] 提取到URL: '{url}'")
            
            # 验证URL格式
            if url.startswith(("http://", "https://")):
                print(f"✅ [URL生成] 成功生成URL: {url}")
                return url
            else:
                print(f"⚠️ [URL生成] AI返回的不是有效URL: '{url}'")
                return None
                
        except Exception as e:
            print(f"❌ [URL生成] AI生成URL失败: {str(e)}")
            return None

    def _ai_identify_website_intent(self, user_input):
        """专门用于识别网页打开与自动化操作请求的AI方法"""
        try:
            from llm_spec import get_config_spec

            spec = get_config_spec(self.config, "search_intent_model")
            result = self._get_llm_client(config_key="search_intent_model")
            if not result:
                print("⚠️ 无法获取LLM客户端，无法进行网页打开与自动化操作意图识别")
                return None
            client, model = result
            print(f"🔍 [网站意图识别] 模型: {spec.display_name()}")
            
            # 构建专门的网页打开与自动化操作识别提示词
            website_prompt = f"""请分析用户输入，判断是否要打开网站。

用户输入：{user_input}

🎯 **你的任务**：
1. 判断是否是网站打开请求
2. 如果是，提取**网站名称**（不是整个句子）
3. 严格按照格式返回

📋 **返回格式**（只返回一行）：
- 打开网站 → website_open|网站名
- 不是网站 → not_website|

⚠️ **重要**：网站名只包含网站本身，不包含"打开"、"帮我"、"在浏览器"等词！

🔥 **安全测试任务识别**：
如果用户请求涉及安全测试、渗透测试、漏洞扫描、分析HTML源码找密码等任务，必须返回 not_website|，不要返回 website_open。
这些任务应该使用HexStrike电子战工具，而不是简单的网站打开。

安全测试任务示例（应返回 not_website|）：
- "分析HTML源码找密码" → not_website|
- "扫描端口" → not_website|
- "漏洞扫描" → not_website|
- "SQL注入测试" → not_website|
- "分析 https://xxx.com 的HTML源码，找出隐藏的密码" → not_website|
- "对xxx.com进行渗透测试" → not_website|

✅ **正确示例**：
- "帮我在浏览器打开哔哩哔哩" → website_open|哔哩哔哩
- "打开B站" → website_open|B站
- "在浏览器打开知乎" → website_open|知乎
- "访问github" → website_open|github
- "打开bilibili搜索python" → website_open|bilibili

❌ **错误示例**（不要这样）：
- "帮我在浏览器打开哔哩哔哩" → website_open|帮我在浏览器打开哔哩哔哩 ❌
- "打开B站" → website_open|打开B站 ❌
- "分析HTML源码找密码" → website_open|xxx ❌（应该返回 not_website|）

🔍 **特殊情况**：
- 浏览器搜索但没说网站名 → website_open|SEARCH_ENGINE
  例："在浏览器搜索Python" → website_open|SEARCH_ENGINE
- 不是打开请求 → not_website|
  例："什么是人工智能" → not_website|
- 安全测试任务 → not_website|
  例："分析HTML源码找密码" → not_website|

现在请分析上面的用户输入，只返回一行结果："""
            
            # 调用AI进行网页打开与自动化操作意图识别
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是一个网页打开与自动化操作意图识别助手，专门用于判断用户是否想要打开网页或进行网页自动化操作。请严格按照格式返回结果。"},
                    {"role": "user", "content": website_prompt}
                ],
                max_tokens=30,
                temperature=0.1,
                timeout=10
            )
            
            result = response.choices[0].message.content.strip()
            print(f"🔍 [网站意图识别] AI原始返回: '{result}'")
            print(f"🔍 [网站意图识别] 用户输入: '{user_input}'")
            
            # 解析结果
            if "|" in result:
                intent_type, site_name = result.split("|", 1)
                intent_type = intent_type.strip()
                site_name = site_name.strip()
                
                print(f"🔍 [网站意图识别] 解析结果 - 类型: '{intent_type}', 网站名: '{site_name}'")
                
                if intent_type == "website_open":
                    if not site_name:
                        print(f"⚠️ [网站意图识别] 网站名为空，使用原始输入")
                        return user_input
                    print(f"✅ [网站意图识别] 提取到网站名: '{site_name}'")
                    return site_name
                else:
                    print(f"❌ [网站意图识别] 非网站打开请求")
                    return None
            else:
                print(f"⚠️ [网站意图识别] AI返回格式错误，没有找到'|'分隔符")
                return None
                
        except Exception as e:
            print(f"AI网页打开与自动化操作意图识别失败: {str(e)}")
            # 如果AI调用失败，返回None
            return None

    def _ai_identify_app_launch_intent(self, user_input):
        """使用AI识别用户的应用启动意图"""
        try:
            from llm_spec import get_config_spec

            spec = get_config_spec(self.config, "search_intent_model")
            result = self._get_llm_client(config_key="search_intent_model")
            if not result:
                print(f"⚠️ 无法获取LLM客户端，无法进行AI应用启动意图识别: {user_input}")
                return None
            client, model = result
            print(f"🔍 应用启动意图识别，模型: {spec.display_name()}")
            
            # 构建AI提示词，让AI智能判断用户意图类型
            intent_prompt = f"""请分析用户的输入，判断是否是应用启动请求：

用户输入：{user_input}

请判断用户是否想要启动或打开某个应用程序。

判断标准：
- 如果用户要求启动或打开应用程序，返回"app_launch|应用名称"
- 如果用户是在询问其他问题，返回"not_app|"

常见的应用启动表达：
- "打开XX"、"启动XX"、"运行XX"
- "帮我打开XX"、"帮我启动XX"、"帮我运行XX"
- "请打开XX"、"请启动XX"、"请运行XX"

支持的应用包括：
- 音乐应用：网易云音乐、QQ音乐、酷狗、酷我、Spotify
- 浏览器：Chrome、Edge、Firefox
- 办公软件：Word、Excel、PowerPoint
- 系统工具：记事本、计算器、画图、命令提示符、PowerShell

特别注意：
- "打开记事本" → "app_launch|记事本"
- "启动Chrome" → "app_launch|Chrome"
- "运行计算器" → "app_launch|计算器"
- "帮我打开Word" → "app_launch|Word"

请只返回结果，格式为：意图类型|应用名称
"""
            
            # 调用AI
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是一个应用启动意图识别助手，专门用于分析用户的应用启动需求。"},
                    {"role": "user", "content": intent_prompt}
                ],
                max_tokens=100,
                temperature=0.1
            )
            
            result = response.choices[0].message.content.strip()
            print(f"🔍 应用启动意图识别结果: {result}")
            
            # 解析AI返回的结果
            if "|" in result:
                intent_type, app_name = result.split("|", 1)
                if intent_type.strip() == "app_launch":
                    return ("app_launch", app_name.strip())
            
            # 如果AI识别失败，返回None
            return None
                
        except Exception as e:
            print(f"AI应用启动意图识别失败: {str(e)}")
            return None

    def _ai_identify_screen_read_intent(self, user_input):
        """使用AI识别用户是否有读屏/看屏幕意图（需要截屏并分析当前屏幕内容）。"""
        try:
            from llm_spec import get_config_spec

            spec = get_config_spec(self.config, "search_intent_model")
            result = self._get_llm_client(config_key="search_intent_model")
            if not result:
                print("⚠️ 无法获取LLM客户端，无法进行读屏意图识别")
                return None
            client, model = result
            print(f"🔍 [读屏意图识别] 模型: {spec.display_name()}")

            intent_prompt = f"""请分析用户输入，判断是否**可能通过查看当前电脑屏幕/桌面内容**来回答（即需要截屏并识别屏幕）。标准从宽：只要有一点点相关就判为需要读屏。

用户输入：{user_input}

判断标准（从宽）：
- **只要问题可能通过看屏幕来回答** → 返回 "screen_read|"，例如：
  - 问当前在做什么、在干嘛、在干什么 → screen_read|（看屏幕可知）
  - 问这道题选什么、选哪个、答案是什么、屏幕上是什么 → screen_read|
  - 问看屏幕、读屏、截屏、桌面有什么、当前界面是什么 → screen_read|
  - 其他任何与「当前屏幕/桌面上的内容」有一点点相关的提问 → screen_read|
- **仅当用户请求明确与看屏幕无关**时 → 返回 "not_screen_read|"，例如：
  - 介绍/介绍一下 xxx、介绍某事物
  - 打开 xxx 软件、启动 xxx 应用
  - 推荐歌/推荐电影、今天天气、写代码、聊天类纯对话（不涉及当前屏幕内容）

✅ 应判为 screen_read 的示例（从宽）：
- "我在干什么"、"我现在在干什么"、"在干嘛"、"我在做什么"
- "这道题选什么"、"答案是什么"、"这题选啥"、“这是什么”
- "看看我屏幕"、"读屏"、"截个屏"、"当前桌面有什么"、"屏幕上是什么"

❌ 应判为 not_screen_read 的示例（明确无关）：
- "介绍一下Python"、"介绍下北京"
- "打开网易云音乐"、"打开记事本"
- "推荐一首歌"、"今天天气怎么样"

请只返回一行：screen_read| 或 not_screen_read|
"""

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是读屏意图识别助手。标准从宽：只要用户的问题可能通过看当前屏幕来回答就返回 screen_read；只有明确无关（如介绍某事物、打开软件、推荐歌、问天气等）才返回 not_screen_read。"},
                    {"role": "user", "content": intent_prompt}
                ],
                max_tokens=20,
                temperature=0.1,
                timeout=10
            )

            result = response.choices[0].message.content.strip()
            print(f"🔍 [读屏意图识别] 结果: {result}")

            if "|" in result:
                intent_type = result.split("|", 1)[0].strip()
                if intent_type == "screen_read":
                    return True
            return None

        except Exception as e:
            print(f"AI读屏意图识别失败: {str(e)}")
            return None

    def _extract_search_keywords(self, user_input: str) -> dict:
        """
        从用户输入中提取搜索关键词，生成多个搜索问题
        返回: {"questions": [搜索问题列表], "urls": [提取的URL列表]}
        """
        try:
            # 首先检测用户输入中是否包含URL
            import re
            # 修改正则表达式，URL应该以非中文字符结束
            url_pattern = r'https?://[a-zA-Z0-9\-._~:/?#\[\]@!$&\'()*+,;=%]+'
            urls = re.findall(url_pattern, user_input)
            
            # 清理URL末尾可能的标点符号
            urls = [url.rstrip('.,;:!?)。，；：！？）') for url in urls]
            
            if urls:
                print(f"🔗 检测到 {len(urls)} 个URL: {urls}")
            from llm_spec import get_config_spec

            spec = get_config_spec(self.config, "search_intent_model")
            result = self._get_llm_client(config_key="search_intent_model")
            if not result:
                print(f"⚠️ 无法获取LLM客户端，无法进行AI关键词提取，使用原始输入")
                return [user_input]
            client, model = result
            print(f"🔍 [搜索关键词提取] 模型: {spec.display_name()}")
            
            # 获取配置的最大搜索问题数
            max_questions = self.config.get("max_search_questions", 3)
            
            # 构建提示词
            prompt = f"""你是一个资料获取助手，专门用于根据用户输入生成适合在浏览器搜索框里搜索的完整问题。

用户输入: {user_input}

上下文信息: 
{self._get_recent_context()}

生成规则：
1. 根据用户输入和上下文信息，从不同角度生成适合搜索的完整问题
2. 如果用户输入包含代词（如"他"、"她"、"它"），结合上下文确定具体指代对象
3. 将简短的查询扩展为完整的搜索问题
4. 保留时间、地点、人物、事件等具体信息
5. 生成的问题应该能够直接在搜索引擎中使用
6. 根据问题的复杂程度，智能决定生成1到{max_questions}个不同角度的搜索问题
7. 每个问题应该从不同的角度获取信息，避免重复
8. 每行一个问题，不要添加编号或其他格式

示例1（简单问题，生成1个）：
输入："2025年93阅兵是什么"
输出：
2025年93阅兵是什么

示例2（需要多角度了解，生成多个）：
输入："户晨风是谁"
输出：
户晨风
户晨风 知乎
户晨风 百科
户晨风 争议

示例3（上下文相关，生成多个）：
输入："他现状如何"（上下文：之前讨论户晨风）
输出：
户晨风 2025
户晨风 近况
户晨风 最新动态

请根据用户输入和上下文，生成适合的搜索问题（最多{max_questions}个），每行一个问题："""
            
            # 调用AI进行关键词提取
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是一个资料获取助手，专门用于根据用户输入和上下文信息生成适合在浏览器搜索框里搜索的完整问题。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.3
            )
            
            # 解析返回的搜索问题
            questions_text = response.choices[0].message.content.strip()
            questions = [q.strip() for q in questions_text.split('\n') if q.strip()]
            
            # 限制问题数量
            questions = questions[:max_questions]
            
            print(f"🔍 AI生成的搜索问题（共{len(questions)}个）:")
            for i, q in enumerate(questions, 1):
                print(f"   {i}. {q}")
            
            # 返回搜索问题和检测到的URL
            result = {
                "questions": questions if questions else [user_input],
                "urls": urls
            }
            
            if urls:
                print(f"📌 将额外浏览 {len(urls)} 个URL")
            
            return result
                
        except Exception as e:
            print(f"⚠️ AI关键词提取失败: {str(e)}，使用原始输入")
            return {"questions": [user_input], "urls": urls if 'urls' in locals() else []}

    def _extract_domain(self, url: str) -> str:
        """
        从URL中提取域名
        """
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc
            # 移除www前缀
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception:
            return url

    def _get_recent_context(self) -> str:
        """
        获取最近的对话上下文，用于关键词提取
        """
        try:
            # 获取最近的对话记录
            if hasattr(self, 'conversation_history') and self.conversation_history:
                # 获取最近3条对话记录
                recent_messages = self.conversation_history[-6:]  # 最近3轮对话（用户+AI）
                context_parts = []
                for message in recent_messages:
                    if isinstance(message, dict):
                        role = message.get('role', '')
                        content = message.get('content', '')
                        if role == 'user':
                            context_parts.append(f"用户: {content}")
                        elif role == 'assistant':
                            context_parts.append(f"AI: {content}")
                    else:
                        context_parts.append(str(message))
                
                return "\n".join(context_parts)
            else:
                return "无上下文信息"
        except Exception as e:
            print(f"⚠️ 获取上下文失败: {str(e)}")
            return "无上下文信息"

    def _optimize_search_content(self, search_content: str) -> str:
        """
        优化搜索内容，确保AI能够更好地理解
        """
        try:
            # 如果内容太短，直接返回
            if len(search_content) < 50:
                return search_content
            
            # 去除重复的空行
            lines = search_content.split('\n')
            optimized_lines = []
            prev_empty = False
            
            for line in lines:
                if line.strip():
                    optimized_lines.append(line)
                    prev_empty = False
                elif not prev_empty:
                    optimized_lines.append(line)
                    prev_empty = True
            
            # 合并相邻的短行
            final_lines = []
            i = 0
            while i < len(optimized_lines):
                line = optimized_lines[i]
                if line.strip() and len(line.strip()) < 50 and i + 1 < len(optimized_lines):
                    next_line = optimized_lines[i + 1]
                    if next_line.strip() and len(next_line.strip()) < 50:
                        # 合并短行
                        combined = f"{line.strip()} {next_line.strip()}"
                        final_lines.append(combined)
                        i += 2
                    else:
                        final_lines.append(line)
                        i += 1
                else:
                    final_lines.append(line)
                    i += 1
            
            optimized_content = '\n'.join(final_lines)
            
            # 如果优化后内容太短，返回原始内容
            if len(optimized_content) < 30:
                return search_content
            
            return optimized_content
            
        except Exception as e:
            print(f"⚠️ 搜索内容优化失败: {str(e)}，返回原始内容")
            return search_content

    def _ai_identify_file_save_info(self, user_input, context_info):
        """统一的文件保存信息识别（整合路径、类型、命名）- 一次AI调用完成所有识别"""
        try:
            print(f"🔍 开始统一文件保存信息识别: {user_input}")
            
            # 使用统一的LLM客户端获取方法（使用用户选择的模型，因为需要更强的理解能力）
            result = self._get_llm_client()
            if not result:
                print("⚠️ 无法获取LLM客户端，无法使用AI智能识别")
                return None
            client, model = result
            
            # 构建统一的AI提示词
            prompt = f"""请分析用户的文件保存请求，一次性提供完整的文件保存信息。

用户请求：{user_input}

上下文信息（最近的对话内容）：
{context_info}

请智能分析并返回完整的文件保存信息：

       **分析要点：**
       1. **文件类型识别**：
          - 如果上下文有```java代码块 → file_type="java"
          - 如果上下文有```python代码块 → file_type="py"
          - 如果上下文有```cpp代码块 → file_type="cpp"
          - 如果上下文有音乐推荐 → file_type="txt"
          - 如果上下文有旅游攻略 → file_type="txt"
       
       2. **文件命名规则**：
          - 🔥 **Java代码**：必须从代码中提取类名！
            - 查找"public class XXX"中的XXX作为类名
            - 如代码有"public class Tetris" → filename="Tetris.java", title="Tetris"
            - 如代码有"public class HelloWorld" → filename="HelloWorld.java", title="HelloWorld"
          - Python代码：program.py 或根据功能命名
          - 音乐歌单：根据语言类型命名
            - 上下文提到"中文歌" → "中文歌单.txt"
            - 上下文提到"英文歌" → "英文歌单.txt"
            - 上下文提到"日文歌" → "日文歌单.txt"
            - 上下文提到"德语歌" → "德语歌单.txt"
            - 无法确定 → "音乐歌单.txt"
          - 旅游攻略：提取城市名（如"法兰克福旅游攻略.txt"）
       
       3. **保存路径识别**：
          - 用户说"保存到D盘" → "D:/"
          - 用户说"保存到C盘" → "C:/"
          - 用户说"D:\测试\" → "D:/测试/"
          - 未指定 → 不返回location字段（使用默认路径）
       
       4. **内容提取**：
          - 🚨 代码文件：content设置为空字符串""，系统会自动提取
          - 音乐歌单：提取AI回复中的音乐推荐内容
          - 旅游攻略：提取相关的攻略内容

返回JSON格式：
{{
    "file_type": "文件类型（java/py/cpp/txt等）",
    "title": "文件标题",
    "filename": "文件名.扩展名",
    "location": "保存路径（可选，如果用户未指定则不返回此字段）",
    "content": "文件内容（代码文件设为空字符串）"
}}

**示例：**
- 上下文有"public class Tetris"的Java代码，用户说"保存到D盘" →
  {{"file_type": "java", "title": "Tetris", "filename": "Tetris.java", "location": "D:/", "content": ""}}

- 上下文有"public class HelloWorld"的Java代码，用户说"帮我保存" →
  {{"file_type": "java", "title": "HelloWorld", "filename": "HelloWorld.java", "content": ""}}

- 上下文有中文歌推荐，用户说"帮我保存" →
  {{"file_type": "txt", "title": "中文歌单", "filename": "中文歌单.txt", "content": "音乐推荐内容"}}

🚨 注意：代码文件的content必须为空字符串""，系统会自动提取！
请只返回JSON，不要包含其他内容。
"""
            
            # 调用AI API
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是文件保存专家，一次性提供完整的文件保存信息（类型、命名、路径、内容）。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,
                temperature=0.3,
                timeout=60
            )
            
            # 提取AI响应
            ai_response = response.choices[0].message.content.strip()
            print(f"✅ 统一文件保存信息识别响应: {ai_response[:200]}...")
            
            # 解析JSON响应
            import json
            # 清理JSON字符串
            if ai_response.startswith('```json'):
                ai_response = ai_response[7:]
            if ai_response.endswith('```'):
                ai_response = ai_response[:-3]
            ai_response = ai_response.strip()
            
            file_save_info = json.loads(ai_response)
            
            # 验证返回的信息
            if "filename" in file_save_info:
                print(f"✅ 统一识别成功: {file_save_info.get('filename')}")
                return file_save_info
            else:
                print(f"⚠️ AI返回的信息不完整")
                return None
                
        except Exception as e:
            print(f"❌ 统一文件保存信息识别失败: {str(e)}")
            return None


    def _ai_create_code_file_from_context(self, user_input):
        """使用AI通过上下文智能创建代码文件"""
        # 使用统一的LLM客户端获取方法
        result = self._get_llm_client()
        
        if result:
            client, model = result
            # 如果有API密钥，执行AI代码文件创建
            
            # 构建上下文信息
            context_info = ""
            if self.session_conversations:
                # 获取最近的对话作为上下文
                recent_contexts = []
                for conv in reversed(self.session_conversations[-5:]):  # 获取最近5条对话
                    recent_contexts.append(f"【{conv['timestamp']}】{conv['full_text']}")
                context_info = "\n".join(recent_contexts)
            
            # 尝试从上下文中提取代码内容
            extracted_code = self._extract_code_from_context(context_info)
            if extracted_code:
                context_info += f"\n\n【提取的代码内容】\n{extracted_code}"
                print(f"🔍 从上下文中提取到代码: {extracted_code[:100]}...")
            else:
                print("⚠️ 未从上下文中提取到代码内容")
                # 如果用户明确要求保存文件但没有找到代码，尝试从最近的对话中提取
                if "保存" in user_input.lower() or "创建" in user_input.lower():
                    print("🔍 尝试从最近的对话中提取代码内容...")
                    for conv in reversed(self.session_conversations[-3:]):
                        ai_response = conv.get("ai_response", "")
                        if "```" in ai_response:
                            extracted_code = self._extract_code_from_context(ai_response)
                            if extracted_code:
                                context_info += f"\n\n【从最近对话提取的代码内容】\n{extracted_code}"
                                print(f"🔍 从最近对话中提取到代码: {extracted_code[:100]}...")
                                break
            
            # 构建AI提示词
            prompt = f"""
请分析用户的代码创建请求，基于上下文信息智能生成代码文件。

用户输入：{user_input}

最近的对话上下文：
{context_info}

请分析用户想要创建什么类型的代码文件，并生成相应的代码。可能的代码类型包括：
1. Python代码 - 如果用户提到Python、py等
2. C++代码 - 如果用户提到C++、cpp等
3. COBOL代码 - 如果用户提到COBOL、cobol等
4. 其他编程语言代码

特别注意：
- 如果上下文中已经显示了代码内容（如```cobol...```），请直接使用该代码
- 如果用户说"创建测试文件"、"创建源文件"、"需要创建"、"保存这个文件"、"需要保存"或"地址在d盘"，请基于上下文中的代码创建文件
- 如果上下文中有COBOL代码，请创建.cob或.cbl文件
- 如果上下文中有Python代码，请创建.py文件
- 如果上下文中有C++代码，请创建.cpp文件
- 如果用户说"需要创建"，请基于上下文中最近的代码内容创建文件
- 如果用户说"地址在d盘"或"保存到d盘"，请将文件保存到D盘
- 如果用户说"保存这个文件"或"需要保存"，请基于上下文中最近的代码内容创建文件
- 如果用户说"路径为"，请使用用户指定的路径和文件名

请返回JSON格式：
{{
    "language": "编程语言",
    "title": "代码标题",
    "code": "完整的代码内容",
    "location": "保存位置（如D:/）",
    "filename": "文件名（如hello.cob）",
    "description": "代码说明"
}}

要求：
1. 代码要完整、可运行
2. 包含必要的注释和文档
3. 使用最佳实践
4. 文件名要符合编程语言规范
5. 保存位置默认为D盘
6. 如果是Hello World程序，要简单明了
7. 优先使用上下文中已有的代码内容
8. 如果用户明确指定了保存位置，请使用用户指定的位置
9. 如果用户说"保存这个文件"，请使用上下文中最近的代码内容
10. 如果用户说"路径为"，请使用用户指定的完整路径

如果无法确定要创建什么代码，请返回null。
"""
            
            # 调用AI
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是一个代码生成助手，专门用于分析用户需求并生成相应的代码文件。请返回JSON格式的结果。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=3000,
                temperature=0.7,
                timeout=240  # 延长AI文件创建的响应时间到240秒
            )
            
            result = response.choices[0].message.content.strip()
            print(f"🔍 AI代码文件创建返回的原始结果: {result[:200]}...")
            
            # 解析JSON结果
            import json
            # 尝试清理JSON字符串
            result = result.strip()
            if result.startswith('```json'):
                result = result[7:]
            if result.endswith('```'):
                result = result[:-3]
            result = result.strip()
            
            # 尝试解析JSON
            try:
                file_info = json.loads(result)
            except json.JSONDecodeError as json_error:
                print(f"AI代码文件创建JSON格式无效: {result}")
                print(f"JSON解析错误: {str(json_error)}")
                return None
            
            if file_info and "code" in file_info:
                # 提取文件信息
                language = file_info.get("language") or "txt"
                title = file_info.get("title", "未命名程序")
                code = file_info.get("code", "")
                location = file_info.get("location", "D:/")
                filename = file_info.get("filename") or f"program.{(language.lower() if isinstance(language, str) else 'txt')}"
                description = file_info.get("description", "")
                
                # 从用户输入中提取保存位置和文件名
                import re
                
                # 尝试提取完整路径（如"路径为D:/计算器.py"）
                path_match = re.search(r'路径为\s*([^，。\s]+)', user_input)
                if path_match:
                    full_path = path_match.group(1)
                    # 分离路径和文件名
                    if '/' in full_path or '\\' in full_path:
                        path_parts = full_path.replace('\\', '/').split('/')
                        if len(path_parts) > 1:
                            location = '/'.join(path_parts[:-1]) + '/'
                            filename = path_parts[-1]
                            if not filename.endswith(('.py', '.cob', '.cbl', '.cpp', '.txt')):
                                filename += '.py'  # 默认添加.py扩展名
                    else:
                        # 如果没有找到完整路径，使用原有的逻辑
                        if "d盘" in user_input.lower() or "d:" in user_input.lower():
                            location = "D:/"
                        elif "c盘" in user_input.lower() or "c:" in user_input.lower():
                            location = "C:/"
                        elif "e盘" in user_input.lower() or "e:" in user_input.lower():
                            location = "E:/"
                        elif "f盘" in user_input.lower() or "f:" in user_input.lower():
                            location = "F:/"
                    
                    # 确保文件名安全
                    import re
                    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                    
                    # 构建完整的文件内容
                    if language.lower() == "cobol":
                        # COBOL代码格式特殊处理
                        if "IDENTIFICATION DIVISION" not in code:
                            file_content = "      IDENTIFICATION DIVISION.\n" + \
                                         "      PROGRAM-ID. " + title.upper().replace(' ', '-') + ".\n" + \
                                         "      PROCEDURE DIVISION.\n" + \
                                         code + "\n" + \
                                         "      STOP RUN.\n"
                        else:
                            # 如果代码已经包含完整的COBOL结构，直接使用
                            file_content = code
                    else:
                        # 其他编程语言
                        file_content = "# -*- coding: utf-8 -*-\n"
                        if description:
                            file_content += f'"""\n{description}\n"""\n\n'
                        file_content += code
                    
                    # 调用MCP工具创建文件
                    file_path = f"{location.rstrip('/')}/{filename}"
                    result = self.mcp_server.call_tool("write_file", 
                                                     file_path=file_path, 
                                                     content=file_content)
                    
                    return f"（指尖轻敲控制台）{result}"
                
        else:
            # 如果没有API密钥，返回None，使用后备方法
            return None

    def _ai_create_file_from_context(self, user_input):
        """使用AI通过上下文智能创建文件"""
        from llm_router import chat_completion, resolve_client

        if not resolve_client(self.config, config_key="selected_model"):
            return None

        # 构建上下文信息 - 只关注与当前用户请求相关的内容
            context_info = ""
            relevant_content = ""
            
            # 分析用户当前请求的类型
            user_request_type = self._analyze_user_request_type(user_input)
            print(f"🔍 用户请求类型: {user_request_type}")
            
            # 如果是代码展示请求，不应该创建文件，应该返回None让AI直接展示代码
            if user_request_type == "code_display":
                print("ℹ️ 用户请求展示代码，不创建文件")
                return None
            
            if self.session_conversations:
                # 🔥 根据识别的内容类型，精准过滤上下文
                for conv in reversed(self.session_conversations[-3:]):  # 只获取最近3条对话
                    conv_text = conv.get('full_text', '')
                    ai_response = conv.get('ai_response', '')
                    
                    # 根据用户请求类型筛选相关内容
                    if user_request_type in ["code_file", "code"]:
                        # 代码文件：只包含有代码块的对话
                        if "```" in ai_response:
                            relevant_content += f"【{conv['timestamp']}】{conv_text}\n"
                            print(f"✅ 包含代码对话: {conv.get('user_input', '')[:30]}...")
                    elif user_request_type in ["music_file", "music"]:
                        # 音乐文件：只包含音乐推荐的对话
                        if any(kw in ai_response for kw in ["音乐", "歌", "歌曲", "推荐", "曲目", "歌单"]):
                            relevant_content += f"【{conv['timestamp']}】{conv_text}\n"
                            print(f"✅ 包含音乐对话: {conv.get('user_input', '')[:30]}...")
                    elif user_request_type in ["travel_file", "travel"]:
                        # 旅游文件：只包含旅游相关的对话
                        if any(kw in ai_response for kw in ["旅游", "旅行", "攻略", "景点"]):
                            relevant_content += f"【{conv['timestamp']}】{conv_text}\n"
                            print(f"✅ 包含旅游对话: {conv.get('user_input', '')[:30]}...")
                    elif user_request_type in ["note_file", "note"]:
                        # 笔记文件
                        if any(kw in ai_response for kw in ["笔记", "记录"]):
                            relevant_content += f"【{conv['timestamp']}】{conv_text}\n"
                    elif user_request_type in ["general_file", "general"]:
                        # 通用文件：包含最近的对话
                        relevant_content += f"【{conv['timestamp']}】{conv_text}\n"
                
                context_info = relevant_content.strip()
            
            # 尝试从相关上下文中提取代码内容
            if user_request_type in ["code_file", "code"]:
                print(f"🔍 准备提取代码，上下文长度: {len(context_info)}")
                print(f"🔍 上下文内容预览: {context_info[:200]}...")
                
                extracted_code = self._extract_code_from_context(context_info)
                if extracted_code:
                    context_info += f"\n\n【提取的代码内容】\n{extracted_code}"
                    print(f"🔍 从相关上下文中提取到代码: {extracted_code[:100]}...")
                else:
                    print("⚠️ 未从相关上下文中提取到代码内容")
                    # 尝试从所有最近对话中提取（不限于relevant_content）
                    print("🔄 尝试从所有最近对话中提取代码...")
                    for conv in reversed(self.session_conversations[-5:]):
                        full_text = conv.get('full_text', '')
                        if "```" in full_text:
                            extracted_code = self._extract_code_from_context(full_text)
                            if extracted_code:
                                context_info += f"\n\n【从全部对话提取的代码内容】\n{extracted_code}"
                                print(f"✅ 从全部对话中提取到代码: {extracted_code[:100]}...")
                                break
            else:
                print(f"ℹ️ 用户请求类型不是代码文件: {user_request_type}")
            
            # 构建AI提示词
            prompt = f"""
请分析用户的文件创建请求，基于用户当前的具体要求生成相应的文件内容。

用户当前请求：{user_input}
用户请求类型：{user_request_type}

相关上下文信息：
{context_info}

重要规则：
1. 🚀 当用户说"帮我保存"时，优先保存最近对话中生成的内容
2. 如果用户要求写代码，就生成代码文件，不要保存其他内容
3. 如果用户要求保存音乐推荐，就生成歌单文件
4. 如果用户要求保存旅游攻略，就生成旅游攻略文件
5. 严格根据用户当前请求的类型和内容来生成文件
6. 必须解析用户指定的保存路径，如果用户说"D:\测试_"，location就应该是"D:/测试_/"
7. 根据文件内容确定正确的文件扩展名，Python代码用.py，C++代码用.cpp等
8. 如果用户明确指定文件类型（如"保存为.py文件"），必须使用用户指定的扩展名
9. 如果用户说"保存为.py文件"，filename必须包含.py扩展名
10. 从上下文中提取相关代码内容，如果上下文中有Python代码，就保存为.py文件
11. **音乐歌单文件名规则**：根据上下文智能判断语言类型
    - 如果上下文提到"中文歌"或包含中文歌曲名，filename为"中文歌单.txt"
    - 如果上下文提到"英文歌"或包含英文歌曲名，filename为"英文歌单.txt"
    - 如果上下文提到"日文歌"或包含日文歌曲名，filename为"日文歌单.txt"
    - 如果上下文提到"德语歌"或包含德语歌曲名，filename为"德语歌单.txt"
    - 如果无法确定语言，使用"音乐歌单.txt"

请返回JSON格式：
{{
    "file_type": "文件类型（folder/txt/py/cpp/java等）",
    "title": "文件标题",
    "content": "文件内容（代码文件设置为空字符串，系统会自动提取）",
    "location": "保存路径（可选，如E:/、D:/等，如果用户没有指定则不返回此字段）",
    "filename": "文件名（如xxx.py）或文件夹名（如xxx/）"
}}

🚨 重要说明：
- **代码文件（Java/Python/C++）**：content设置为""（空字符串），系统会自动从代码块提取纯代码
- **Java代码**：title必须是从代码中提取的类名（如Tetris、HelloWorld、Calculator）
- **文本文件（歌单/攻略）**：可以在content中包含简短描述
- 如果用户明确指定了保存路径（如"保存到E盘"、"保存到D盘"），请在location字段中返回对应的路径；如果没有指定，则不返回location字段

要求：
1. 文件内容必须与用户当前请求完全匹配
2. 标题要简洁明了，反映用户的实际需求
3. 如果是文件夹，content字段为空，filename以/结尾
4. **如果是代码文件，必须从代码块（```xxx）中提取纯代码，不要包含任何说明文字**
5. **文件扩展名必须与代码语言匹配：Java→.java, Python→.py, C++→.cpp**
6. 如果是歌单文件，要包含完整的歌曲信息
7. 如果是旅游攻略，要包含详细的旅游信息
8. 🚀 智能路径处理：如果用户明确指定了保存路径（如"保存到E盘"），在location字段中返回对应路径；如果没有指定，则不包含location字段
9. 文件名要符合Windows命名规范，扩展名要正确
10. 绝对不要保存与用户当前请求无关的内容

特别注意：
- 🚀 当用户说"帮我保存"时，分析最近对话内容，智能判断要保存什么类型的文件
- 如果上下文中包含旅游攻略、景点介绍、行程安排，就保存为旅游攻略文件(.txt)
- 如果上下文中包含音乐推荐、歌曲列表、歌单，就保存为歌单文件(.txt)
- **如果上下文中包含代码块（```python、```java、```cpp等），必须：**
  - **只提取代码块内的代码，不要包含"以下是代码"等说明**
  - **file_type设置为对应语言（java/python/cpp）**
  - **filename必须以对应扩展名结尾（.java/.py/.cpp）**
  - **content只包含纯代码，不包含markdown标记和说明文字**
- 如果上下文中包含笔记、记录、总结，就保存为笔记文件(.txt)
- 如果上下文中包含计划、安排、清单，就保存为计划文件(.txt)
- 如果用户明确指定了文件类型（如"保存为.py文件"），必须使用用户指定的扩展名
- 如果用户明确指定了保存路径（如"保存到E盘"），在location字段中返回对应路径
- 绝对不要返回null，必须根据用户请求和上下文内容生成文件

如果无法确定要创建什么文件，请返回null。
"""
            
            # 调用AI
            try:
                result = chat_completion(
                    self.config,
                    config_key="selected_model",
                    messages=[
                        {"role": "system", "content": "你是一个文件创建助手，专门用于分析用户需求并生成相应的文件内容。请返回JSON格式的结果。"},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=2000,
                    temperature=0.7,
                    timeout=240,
                    task_label="ai_create_file",
                )
                if not result:
                    print("⚠️ AI返回空结果，使用简单解析")
                    file_info = self._simple_parse_file_info(user_input, context_info)
                else:
                    result = result.strip()
                    print(f"🔍 AI文件创建返回的原始结果: {result[:200]}...")
                    # 解析JSON结果
                    try:
                        import json
                        # 尝试清理JSON字符串
                        result = result.strip()
                        if result.startswith('```json'):
                            result = result[7:]
                        if result.endswith('```'):
                            result = result[:-3]
                        result = result.strip()
                        
                        file_info = json.loads(result)
                        
                    except json.JSONDecodeError as json_error:
                        print(f"⚠️ JSON解析失败，使用简单解析: {str(json_error)}")
                        file_info = self._simple_parse_file_info(user_input, context_info)

            except Exception as e:
                print(f"❌ AI 文件创建阶段异常: {e}")
                file_info = None

            if file_info and file_info.get("title") is not None and file_info.get("content") is not None:
                # 提取文件信息
                file_type = file_info.get("file_type") or "txt"
                title = file_info.get("title") or "未命名文件"
                content = file_info.get("content") or ""
                location = file_info.get("location") or ""
                filename = file_info.get("filename") or f"{title}.txt"

                # 🔥 智能内容处理：代码文件从上下文提取，文本文件使用AI回复
                if not content:
                    # 检查是否是代码文件（Java/Python/C++等）
                    code_extensions = ['.java', '.py', '.cpp', '.c', '.js', '.html', '.css', '.cob', '.cbl']
                    is_code_file = any(filename.endswith(ext) for ext in code_extensions)
                    
                    if is_code_file:
                        # 🔥 代码文件：从上下文中提取纯代码
                        print(f"🔍 准备提取代码，上下文长度: {len(context_info)}")
                        print(f"🔍 上下文内容预览: {context_info[:200]}...")
                        
                        extracted_code = self._extract_code_from_context(context_info)
                        if extracted_code:
                            content = extracted_code
                            print(f"🔍 从相关上下文中提取到代码: {content[:100]}...")
                        else:
                            print("⚠️ 未能从上下文提取代码，使用AI返回的内容")
                            if self.session_conversations:
                                last_conv = self.session_conversations[-1]
                                content = last_conv.get('ai_response') or ""
                    else:
                        # 文本文件：使用AI完整回复
                        if self.session_conversations:
                            last_conv = self.session_conversations[-1]
                            content = last_conv.get('ai_response') or ""

                # 文件名后缀兜底：文字类默认.txt（代码类型已有专属后缀时不覆盖）
                if file_type != "folder" and ("." not in filename):
                    filename = f"{filename}.txt"

                # 🚀 智能路径处理：优先使用AI返回的路径，否则使用默认路径
                default_path = self.config.get("default_save_path", "D:/露尼西亚文件/")
                
                # 检查AI是否返回了用户指定的路径
                if location and (location.startswith("D:/") or 
                                 location.startswith("C:/") or
                                 location.startswith("E:/") or
                                 location.startswith("F:/") or
                                 location.startswith("G:/") or
                                 location.startswith("H:/")):
                    # AI返回了用户指定的路径，使用它
                    print(f"🔍 使用AI返回的用户指定路径: {location}")
                else:
                    # AI没有返回路径，使用默认保存路径
                    location = default_path
                    print(f"🔍 使用默认保存路径: {default_path}")
                    
                    # 确保默认路径存在
                    if not os.path.exists(default_path):
                        try:
                            os.makedirs(default_path, exist_ok=True)
                            print(f"✅ 创建默认保存路径: {default_path}")
                        except Exception as e2:
                            print(f"WARNING: {str(e2)}")
                            location = "D:/"
                            print(f"INFO: {location}")
                            print(f"INFO: Using fallback path: {location}")
                
                print(f"✅ 最终保存路径: {location}")
                
                # 确保文件名安全
                import re
                filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                
                # 调用MCP工具创建文件或文件夹
                if file_type == "folder":
                    # 创建文件夹
                    folder_path = f"{location.rstrip('/')}/{filename}"
                    print(f"🔍 创建文件夹: {folder_path}")
                    result = self.mcp_server.call_tool("create_folder", 
                                                       folder_path=folder_path)
                elif "create_note" in user_input.lower() or "笔记" in user_input:
                    # 创建笔记
                    print(f"🔍 创建笔记: {filename} 在 {location}")
                    result = self.mcp_server.call_tool("create_note", 
                                                       title=title, 
                                                       content=content, 
                                                       filename_format="simple", 
                                                       location=location)
                else:
                    # 创建普通文件
                    file_path = f"{location.rstrip('/')}/{filename}"
                    print(f"🔍 创建文件: {file_path}")
                    print(f"🔍 文件内容长度: {len(content)} 字符")
                    print(f"🔍 文件标题: {title}")
                    print(f"🔍 文件名: {filename}")
                    print(f"🔍 保存位置: {location}")
                    print(f"🔍 路径来源: {'AI返回' if location and location != self.config.get('default_save_path', 'D:/露尼西亚文件/') else '默认路径'}")
                    print(f"🔍 文件类型: {file_type}")
                    
                    result = self.mcp_server.call_tool("write_file", 
                                                       file_path=file_path, 
                                                       content=content)
                    
                    print(f"✅ 文件创建结果: {result}")
                    return f"（指尖轻敲控制台）{result}"
                
            # 如果上面没有得到有效的 file_info，则使用简单解析作为后备方案
            if not (file_info and file_info.get("title") is not None and file_info.get("content") is not None):
                print("🔄 使用简单解析作为后备方案")
                file_info = self._simple_parse_file_info(user_input, context_info)

                if file_info and file_info.get("title") is not None and file_info.get("content") is not None:
                    # 提取文件信息
                    file_type = file_info.get("file_type") or "txt"
                    title = file_info.get("title") or "未命名文件"
                    content = file_info.get("content") or ""
                    location = file_info.get("location") or ""
                    filename = file_info.get("filename") or f"{title}.txt"

                    # 内容兜底：若内容为空，使用最近一条AI完整回复
                    if (not content) and self.session_conversations:
                        last_conv = self.session_conversations[-1]
                        content = last_conv.get('ai_response') or content or ""

                    # 文件名后缀兜底：文字类默认.txt（代码类型已有专属后缀时不覆盖）
                    if file_type != "folder" and ("." not in filename):
                        filename = f"{filename}.txt"
                    
                    # 🚀 智能路径处理：优先使用用户指定路径，否则使用默认路径
                    default_path = self.config.get("default_save_path", "D:/露尼西亚文件/")
                    
                    # 检查是否有用户指定的路径
                    if location and (location.startswith("D:/") or 
                                   location.startswith("C:/") or
                                   location.startswith("E:/") or
                                   location.startswith("F:/") or
                                   location.startswith("G:/") or
                                   location.startswith("H:/")):
                        # 用户指定了路径，使用它
                        print(f"🔍 使用用户指定路径: {location}")
                    else:
                        # 没有指定路径，使用默认保存路径
                        location = default_path
                        print(f"🔍 使用默认保存路径: {default_path}")
                        
                        # 确保默认路径存在
                        if not os.path.exists(default_path):
                            try:
                                os.makedirs(default_path, exist_ok=True)
                                print(f"✅ 创建默认保存路径: {default_path}")
                            except Exception as e:
                                print(f"⚠️ 创建默认路径失败: {str(e)}")
                                # 如果创建失败，使用D盘根目录
                                location = "D:/"
                                print(f"🔄 使用后备路径: {location}")
                        
                        print(f"✅ 最终保存路径: {location}")
                        
                        # 确保文件名安全
                        import re
                        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                        
                        # 调用MCP工具创建文件
                        file_path = f"{location.rstrip('/')}/{filename}"
                        print(f"🔍 后备方案创建文件: {file_path}")
                        print(f"🔍 后备方案文件内容长度: {len(content)} 字符")
                        print(f"🔍 后备方案文件标题: {title}")
                        print(f"🔍 后备方案文件名: {filename}")
                        print(f"🔍 后备方案保存位置: {location}")
                        print(f"🔍 后备方案路径来源: {'用户指定' if location and location != self.config.get('default_save_path', 'D:/露尼西亚文件/') else '默认路径'}")
                        
                        result = self.mcp_server.call_tool("write_file", 
                                                         file_path=file_path, 
                                                         content=content)
                        
                        print(f"✅ 后备方案文件创建结果: {result}")
                        return f"（指尖轻敲控制台）{result}"
                else:
                    return None

    def _fallback_create_note(self, user_input):
        """后备笔记创建方法（原有的固定格式）"""
        try:
            # 智能提取标题和内容
            import re
            
            # 检查是否是文件夹创建请求
            folder_keywords = ["文件夹", "目录", "文件夹", "创建文件夹", "新建文件夹", "建立文件夹"]
            if any(keyword in user_input.lower() for keyword in folder_keywords):
                # 提取文件夹名称
                folder_name = None
                folder_patterns = [
                    r'叫\s*["\']([^"\']+)["\']',
                    r'名为\s*["\']([^"\']+)["\']',
                    r'名称\s*["\']([^"\']+)["\']',
                    r'文件夹\s*["\']([^"\']+)["\']',
                    r'目录\s*["\']([^"\']+)["\']',
                ]
                
                for pattern in folder_patterns:
                    match = re.search(pattern, user_input)
                    if match:
                        folder_name = match.group(1)
                        break
                
                if not folder_name:
                    # 如果没有找到明确的文件夹名，使用默认名称
                    folder_name = "新建文件夹"
                
                # 提取保存位置
                location = "D:/"
                location_patterns = [
                    r'位置在\s*([^，。\s]+)',
                    r'位置\s*是\s*([^，。\s]+)',
                    r'保存到\s*([^，。\s]+)',
                    r'保存在\s*([^，。\s]+)',
                    r'创建在\s*([^，。\s]+)',
                    r'(D[:\/\\])',
                    r'(C[:\/\\])',
                    r'(E[:\/\\])',
                ]
                
                for pattern in location_patterns:
                    match = re.search(pattern, user_input)
                    if match:
                        location = match.group(1)
                        if not location.endswith('/') and not location.endswith('\\'):
                            location += '/'
                        break
                
                # 创建文件夹
                folder_path = f"{location.rstrip('/')}/{folder_name}"
                result = self.mcp_server.call_tool("create_folder", folder_path=folder_path)
                return f"（指尖轻敲控制台）{result}"
            
            # 1. 从用户输入中提取标题
            title = None
            
            # 检查是否包含歌单相关关键词
            if any(keyword in user_input.lower() for keyword in ["歌单", "音乐", "歌曲", "playlist", "music"]):
                # 使用默认标题，让主Agent的AI动态生成内容
                title = "音乐歌单"
            
            # 检查是否包含其他类型的笔记
            elif "出行" in user_input or "计划" in user_input:
                title = "出行计划"
            elif "天气" in user_input:
                title = "天气记录"
            elif "代码" in user_input or "程序" in user_input:
                title = "代码笔记"
            else:
                # 尝试从用户输入中提取标题
                title_patterns = [
                    r'标题为\s*["\']([^"\']+)["\']',
                    r'标题\s*["\']([^"\']+)["\']',
                    r'标题是\s*["\']([^"\']+)["\']',
                    r'文件名叫\s*["\']([^"\']+)["\']',
                    r'文件名\s*["\']([^"\']+)["\']',
                ]
                
                for pattern in title_patterns:
                    match = re.search(pattern, user_input)
                    if match:
                        title = match.group(1)
                        break
                
                # 如果没有找到，尝试提取关键词作为标题
                if not title:
                    keywords = ["歌单", "笔记", "计划", "记录", "清单"]
                    for keyword in keywords:
                        if keyword in user_input:
                            title = f"{keyword}笔记"
                            break
            
            # 2. 从上下文和用户输入中提取内容
            content = ""
            
            # 检查最近的对话中是否有歌单内容
            if title and "歌单" in title:
                # 从最近的对话中查找歌单内容
                for conv in reversed(self.session_conversations[-5:]):  # 检查最近5条对话
                    ai_response = conv.get("ai_response", "")
                    if any(keyword in ai_response for keyword in ["**", "*", "《", "》", "-", "1.", "2.", "3."]):
                        # 这可能是歌单内容
                        content = ai_response
                        break
            
            # 如果没有找到内容，尝试从用户输入中提取
            if not content:
                content_patterns = [
                    r'内容为\s*["\']([^"\']+)["\']',
                    r'内容\s*["\']([^"\']+)["\']',
                ]
                
                for pattern in content_patterns:
                    match = re.search(pattern, user_input)
                    if match:
                        content = match.group(1)
                        break
            
            # 3. 提取位置信息
            location = None
            location_patterns = [
                r'位置在\s*([^，。\s]+)',
                r'位置\s*是\s*([^，。\s]+)',
                r'保存到\s*([^，。\s]+)',
                r'保存在\s*([^，。\s]+)',
                r'创建在\s*([^，。\s]+)',
                r'帮我保存到\s*([^，。\s]+)',
                r'(D[:\/\\])',
                r'(C[:\/\\])',
                r'(E[:\/\\])',
                r'(F[:\/\\])'
            ]
            
            print(f"🔍 开始提取路径，用户输入: {user_input}")
            
            for i, pattern in enumerate(location_patterns):
                match = re.search(pattern, user_input)
                if match:
                    print(f"🔍 模式 {i+1} 匹配成功: {pattern}")
                    print(f"🔍 匹配结果: {match.group(0)}")
                    location = match.group(1) if match.group(1) else "D:/"
                    print(f"🔍 提取的路径: {location}")
                    break
                else:
                    print(f"🔍 模式 {i+1} 不匹配: {pattern}")
            
            # 如果没有找到位置，默认使用D盘
            if not location:
                location = "D:/"
                print(f"🔍 未找到路径，使用默认值: {location}")
            
            # 🚀 标准化路径格式，确保盘符后面有斜杠
            if location and len(location) == 1 and location in ['D', 'C', 'E', 'F']:
                location = f"{location}:/"
                print(f"🔍 标准化路径格式: {location}")
            
            print(f"🔍 最终路径: {location}")
            
            # 4. 如果找到了标题但没有内容，生成默认内容
            if title and not content:
                if "中文歌单" in title:
                    content = """# 中文歌单精选

## 经典流行系列
1. 《七里香》- 周杰伦
   - 夏日怀旧风格，适合夜间放松聆听
2. 《小幸运》- 田馥甄
   - 温暖抒情曲目，情绪舒缓

## 影视金曲推荐
3. 《光年之外》- G.E.M.邓紫棋
   - 电影主题曲，富有感染力
4. 《追光者》- 岑宁儿
   - 温柔治愈系，适合安静环境

## 民谣与独立音乐
5. 《成都》- 赵雷
   - 城市民谣，叙事性强
6. 《理想三旬》- 陈鸿宇
   - 民谣风格，适合深夜沉思

创建时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
用途：指挥官的中文音乐收藏"""
                elif "英文歌单" in title:
                    content = """# English Music Playlist

## Contemporary Pop Selection
1. *Flowers* - Miley Cyrus
   - 2023 hit single, mood uplifting
2. *Cruel Summer* - Taylor Swift
   - Upbeat summer-themed track

## Electronic & Dance
3. *Cold Heart (PNAU Remix)* - Elton John & Dua Lipa
   - Cross-generational collaboration
4. *Don't Start Now* - Dua Lipa
   - Energetic dance track for pre-departure

## Alternative Recommendations
5. *As It Was* - Harry Styles
   - Pop-rock with retro synth elements
6. *Blinding Lights* - The Weeknd
   - 80s-style synthwave masterpiece

Created: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Purpose: Commander's English music collection"""
                elif "德语歌单" in title:
                    content = """# 德语夜间歌单

## 经典德文歌曲
1. **《Das Liebeslied》- Annett Louisan**
   - 轻柔民谣风格，适合安静环境
2. **《Ohne dich》- Rammstein**
   - 工业金属乐队的情歌，情感深沉
3. **《Auf uns》- Andreas Bourani**
   - 励志流行曲，旋律积极

## 现代德文流行
4. **《Chöre》- Mark Forster**
   - 流行摇滚，节奏明快但不过于激烈
5. **《Musik sein》- Wincent Weiss**
   - 轻快流行，适合放松
6. **《99 Luftballons》- Nena**
   - 经典反战歌曲，合成器流行风格

## 推荐聆听时段
- 最佳时间：22:00-24:00
- 适合场景：夜间放松、学习德语

创建时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
用途：指挥官的德语音乐收藏"""
                else:
                    content = f"# {title}\n\n这是一个{title}，创建时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            # 5. 调用工具创建笔记
            if title:
                # 检查是否是代码保存请求
                if "代码" in title or "程序" in title:
                    # 从上下文中提取代码内容
                    extracted_code = self._extract_code_from_context(" ".join([conv["full_text"] for conv in self.session_conversations[-3:]]))
                    if extracted_code:
                        content = f"# {title}\n\n```cpp\n{extracted_code}\n```\n\n创建时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    
                    # 从用户输入中提取具体路径
                    import re
                    path_match = re.search(r'保存到\s*([^，。\s]+)', user_input)
                    if path_match:
                        specific_path = path_match.group(1)
                        # 构建完整路径
                        if specific_path.endswith('\\') or specific_path.endswith('/'):
                            file_path = f"{specific_path}{title}.txt"
                        else:
                            file_path = f"{specific_path}\\{title}.txt"
                        
                        # 使用write_file工具直接创建文件
                        try:
                            result = self.mcp_server.call_tool("write_file", file_path=file_path, content=content)
                            return f"(RESULT){result}"
                        except Exception as e:
                            return f"(ERROR){str(e)}"
                
                # 获取文件名格式设置
                filename_format = self.config.get("note_filename_format", "simple")
                result = self.mcp_server.call_tool("create_note", title=title, content=content, filename_format=filename_format, location=location)
                return f"（指尖轻敲控制台）{result}"
            else:
                return f"（微微皱眉）抱歉指挥官，无法确定笔记标题。请明确说明要创建什么类型的笔记。"
                
        except Exception as e:
            return f"（微微皱眉）抱歉指挥官，创建笔记时遇到了问题：{str(e)}"

    def _handle_security_testing(self, user_input):
        """处理安全测试请求 - 功能已暂时移除"""
        return "（抱歉地摇头）指挥官，安全测试功能已暂时移除。\n\n该功能正在重新开发中，敬请期待后续版本。\n\n💡 您可以继续使用其他功能，如文件分析、网络搜索等。"
    
    # 安全测试方法已移除
    
    # 安全测试回调方法已移除
    
    # 智能安全测试方法已移除
    # Playwright网页导航与交互操作已移除（功能已整合到网页打开与自动化操作中）
    
    def _extract_search_query_from_text(self, text):
        """从文本中提取搜索查询"""
        import re
        
        # 尝试提取引号中的内容
        quote_patterns = [
            r'搜索["""](.*?)["""]',
            r'查找["""](.*?)["""]',
            r'查询["""](.*?)["""]',
            r'搜索(.*?)(?:\s|$)',
            r'查找(.*?)(?:\s|$)',
            r'查询(.*?)(?:\s|$)'
        ]
        
        for pattern in quote_patterns:
            match = re.search(pattern, text)
            if match:
                query = match.group(1).strip()
                if query and len(query) > 1:
                    return query

        return None

    # 以下是残留的安全测试代码，已全部删除
    
    def _detect_web_port(self, target: str) -> int:
        """检测Web端口"""
        common_web_ports = [80, 443, 8080, 8443, 9000, 3000]
        
        for port in common_web_ports:
            try:
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                result = sock.connect_ex((target, port))
                sock.close()
                
                if result == 0:
                    print(f"🔍 检测到开放端口: {port}")
                    return port
            except:
                continue
        
        # 默认返回80端口
        return 80
    
    def _extract_full_url_from_input(self, user_input: str) -> str:
        """从用户输入中提取完整URL"""
        import re
        
        # 更精确的URL匹配，只匹配英文域名和端口，不包含中文
        url_pattern = r'https?://[a-zA-Z0-9.-]+(?::\d+)?(?:/[a-zA-Z0-9._~:/?#[\]@!$&\'()*+,;=-]*)?'
        urls = re.findall(url_pattern, user_input)
        
        if urls:
            # 取第一个匹配的URL，并清理
            url = urls[0]
            # 移除URL中可能包含的额外字符
            url = re.sub(r'[^\x00-\x7F]+.*$', '', url)  # 移除第一个非ASCII字符及其后面的所有内容
            url = url.rstrip('/')  # 移除末尾的斜杠
            print(f"🔍 从输入中提取到完整URL: {url}")
            return url

        return None

    # 传统安全测试方法已被智能模式完全替代
    
    def _execute_security_commands(self, commands):
        """执行安全测试命令"""
        print(f"⚡ 开始执行{len(commands)}个安全测试命令...")
        
        results = []
        response = "🔒 **安全测试报告**\n\n"
        
        total_time = 0
        for i, cmd_info in enumerate(commands, 1):
            command = cmd_info['command']
            description = cmd_info['description']
            estimated_time = cmd_info.get('estimated_time', '未知')
            
            response += f"**步骤 {i}: {description}**\n"
            response += f"命令: `{command}`\n"
            response += f"预计时间: {estimated_time}\n\n"
            
            # 执行命令
            result = self.kali_controller.execute_command(command)
            results.append(result)
            
            if result['success']:
                response += "✅ 执行成功\n"
                # 简化输出，只显示关键信息
                stdout = result['stdout'][:500] + "..." if len(result['stdout']) > 500 else result['stdout']
                if stdout.strip():
                    response += f"```\n{stdout}\n```\n"
            else:
                response += f"❌ 执行失败: {result.get('error', '未知错误')}\n"
                stderr = result.get('stderr', '')
                if stderr:
                    response += f"错误信息: {stderr[:200]}\n"
                    
                    # 针对常见错误提供解决建议
                    if "域名解析" in stderr or "Name or service not known" in stderr:
                        response += "💡 **建议**: 目标域名无法解析，可能的原因：\n"
                        response += "• 域名不存在或已过期\n"
                        response += "• DNS服务器配置问题\n"
                        response += "• 网络连接问题\n"
                        response += f"• 尝试使用 `nslookup {cmd_info.get('command', '').split()[-1]}` 验证域名\n"
                    elif "requires root privileges" in stderr:
                        response += "💡 **建议**: 当前用户权限不足，建议：\n"
                        response += "• 使用sudo运行需要root权限的命令\n"
                        response += "• 或使用不需要root权限的扫描选项\n"
                        response += "• 考虑切换到root用户进行高级扫描\n"
                    elif "Network is unreachable" in stderr:
                        response += "💡 **建议**: 网络不可达，检查：\n"
                        response += "• 目标主机是否在线\n"
                        response += "• 防火墙是否阻止了连接\n"
                        response += "• 路由配置是否正确\n"
            
            response += "\n" + "-"*50 + "\n\n"
            total_time += result.get('execution_time', 0)
        
        # 生成详细分析报告
        if results:
            response += "📊 **详细分析报告**\n\n"
            
            for i, result in enumerate(results, 1):
                if not result.get("success", False):
                    continue
                    
                tool = result.get("command", "").split()[0]
                response += f"### 🔍 工具 {i}: {tool.upper()}\n\n"
                
                # 分析不同工具的输出
                if tool == "nmap":
                    nmap_analysis = self._analyze_nmap_output(result.get("stdout", ""))
                    
                    # 目标信息
                    if nmap_analysis.get("target_ip"):
                        response += f"**🎯 目标信息**\n"
                        response += f"• 目标: {nmap_analysis['target_ip']}\n"
                    
                    # 主机状态
                    if nmap_analysis.get("host_status"):
                        response += f"• 状态: {nmap_analysis['host_status']}\n"
                    
                    # 警告信息
                    if nmap_analysis.get("warnings"):
                        response += f"\n⚠️ **警告**\n"
                        for warning in nmap_analysis["warnings"]:
                            response += f"• {warning}\n"
                    
                    # 开放端口详情
                    if nmap_analysis.get("ports"):
                        open_ports = [p for p in nmap_analysis["ports"] if p["state"] == "open"]
                        closed_ports = [p for p in nmap_analysis["ports"] if p["state"] == "closed"]
                        filtered_ports = [p for p in nmap_analysis["ports"] if p["state"] == "filtered"]
                        
                        response += f"\n**🔌 端口扫描结果**\n"
                        
                        if open_ports:
                            response += f"✅ **开放端口** ({len(open_ports)}个):\n"
                            for port in open_ports:
                                response += f"• {port['port']}/{port['protocol']} - {port['service']} (开放)\n"
                        else:
                            response += "🔒 **开放端口**: 无开放端口发现\n"
                        
                        if closed_ports:
                            response += f"\n❌ **关闭端口** ({len(closed_ports)}个):\n"
                            for port in closed_ports[:5]:  # 只显示前5个
                                response += f"• {port['port']}/{port['protocol']} - {port['service']} (关闭)\n"
                            if len(closed_ports) > 5:
                                response += f"• ... 还有 {len(closed_ports) - 5} 个关闭端口\n"
                        
                        if filtered_ports:
                            response += f"\n🛡️ **过滤端口** ({len(filtered_ports)}个):\n"
                            for port in filtered_ports[:3]:  # 只显示前3个
                                response += f"• {port['port']}/{port['protocol']} - {port['service']} (被过滤)\n"
                    else:
                        response += f"\n🔍 **端口扫描结果**: 未发现开放端口或主机无响应\n"
                    
                    # 操作系统信息
                    if nmap_analysis.get("os_info"):
                        response += f"\n💻 **操作系统**: {nmap_analysis['os_info']}\n"
                    
                    # 扫描统计
                    if nmap_analysis.get("scan_stats"):
                        stats = nmap_analysis["scan_stats"]
                        if stats.get("duration"):
                            response += f"\n⏱️ **扫描耗时**: {stats['duration']:.2f}秒\n"
                        if stats.get("summary"):
                            response += f"📈 **扫描统计**: {stats['summary']}\n"
                
                elif tool == "nikto":
                    nikto_analysis = self._analyze_nikto_output(result.get("stdout", ""))
                    if nikto_analysis.get("vulnerabilities"):
                        response += f"**🚨 发现的漏洞**\n"
                        for vuln in nikto_analysis["vulnerabilities"]:
                            response += f"• {vuln['description']}\n"
                    if nikto_analysis.get("server_info"):
                        response += f"**🌐 服务器信息**: {nikto_analysis['server_info']}\n"
                
                elif tool == "curl":
                    curl_output = result.get("stdout", "")
                    if curl_output.strip():
                        response += f"**🌐 HTTP响应分析**\n"
                        response += f"```\n{curl_output}\n```\n"
                        
                        # 详细分析HTTP响应
                        if "HTTP/" in curl_output:
                            # 提取状态码
                            status_line = [line for line in curl_output.split('\n') if 'HTTP/' in line]
                            if status_line:
                                response += f"📊 **状态**: {status_line[0].strip()}\n"
                        
                        # CDN检测
                        if "cloudflare" in curl_output.lower():
                            response += "🛡️ **CDN**: Cloudflare 防护已确认\n"
                        if "cf-ray" in curl_output.lower():
                            cf_ray = [line for line in curl_output.split('\n') if 'cf-ray' in line.lower()]
                            if cf_ray:
                                response += f"🔍 **Cloudflare Ray ID**: {cf_ray[0].strip()}\n"
                        
                        # 服务器信息
                        server_line = [line for line in curl_output.split('\n') if line.lower().startswith('server:')]
                        if server_line:
                            response += f"🖥️ **服务器**: {server_line[0].split(':', 1)[1].strip()}\n"
                        
                        # 安全头分析
                        if "x-frame-options" in curl_output.lower():
                            response += "✅ **安全头**: X-Frame-Options 已配置\n"
                        if "strict-transport-security" in curl_output.lower():
                            response += "✅ **安全头**: HSTS 已启用\n"
                        if "content-security-policy" in curl_output.lower():
                            response += "✅ **安全头**: CSP 已配置\n"
                        
                        # 检测可能的绕过成功
                        if "200 OK" in curl_output:
                            response += "🎯 **突破成功**: 获得HTTP 200响应！\n"
                        elif "403" in curl_output:
                            response += "🚫 **被阻止**: HTTP 403 - 访问被拒绝\n"
                        elif "404" in curl_output:
                            response += "❓ **未找到**: HTTP 404 - 资源不存在\n"
                    else:
                        response += f"**🌐 HTTP请求失败**\n"
                        response += "• 连接超时或被阻止\n"
                
                elif tool == "dig":
                    dig_output = result.get("stdout", "")
                    if dig_output.strip():
                        response += f"**🔍 DNS记录分析**\n"
                        response += f"```\n{dig_output}\n```\n"
                
                response += "\n" + "-"*60 + "\n\n"
            
            # 总体安全评估
            all_ports = []
            all_warnings = []
            for result in results:
                if result.get("success") and result.get("command", "").startswith("nmap"):
                    nmap_analysis = self._analyze_nmap_output(result.get("stdout", ""))
                    all_ports.extend(nmap_analysis.get("ports", []))
                    all_warnings.extend(nmap_analysis.get("warnings", []))
            
            response += "🛡️ **安全评估总结**\n\n"
            
            open_ports = [p for p in all_ports if p["state"] == "open"]
            if open_ports:
                response += f"⚠️ **风险评估**: 发现 {len(open_ports)} 个开放端口\n"
                for port in open_ports:
                    risk_level = self._assess_port_risk(port)
                    response += f"• 端口 {port['port']}/{port['protocol']} ({port['service']}) - {risk_level}\n"
            else:
                if all_warnings:
                    response += "❓ **状态**: 目标主机无响应，可能的原因：\n"
                    for warning in set(all_warnings):  # 去重
                        response += f"• {warning}\n"
                else:
                    response += "✅ **状态**: 未发现开放端口，安全性较好\n"
            
            response += "\n💡 **专业建议**\n\n"
            if open_ports:
                response += "• 审查所有开放端口的必要性\n"
                response += "• 对关键服务实施访问控制\n"
                response += "• 定期更新服务版本以修复已知漏洞\n"
                response += "• 配置服务的安全认证机制\n"
                response += "• 定期进行漏洞扫描和渗透测试\n"
            else:
                # 检查是否有命令失败
                failed_commands = [r for r in results if not r.get('success', False)]
                if failed_commands:
                    response += "**针对扫描失败的建议**:\n"
                    response += "• 验证目标域名/IP是否正确\n"
                    response += "• 检查DNS解析: `nslookup 目标域名`\n"
                    response += "• 测试网络连通性: `ping 目标IP`\n"
                    response += "• 确认Kali Linux用户权限\n"
                    response += "• 考虑目标可能使用了DDoS防护服务\n"
                    response += "• 尝试使用代理或VPN进行扫描\n"
                else:
                    response += "• 如果主机应该可访问，检查防火墙配置\n"
                    response += "• 验证网络连通性和DNS解析\n"
                    response += "• 考虑使用不同的扫描技术进行深度检测\n"
        
        response += f"⏱️ 总执行时间: {total_time:.2f}秒\n"
        response += "🔒 安全测试完成。请根据发现的问题及时加固系统安全。"
        
        return response
    
    def _analyze_nmap_output(self, output: str) -> Dict[str, Any]:
        """分析Nmap输出（AI代理版本）"""
        analysis = {
            "ports": [], 
            "services": [], 
            "os_info": "",
            "target_ip": "",
            "host_status": "",
            "scan_stats": {},
            "warnings": []
        }
        
        lines = output.split('\n')
        
        for line in lines:
            # 解析目标IP地址
            if 'Nmap scan report for' in line:
                parts = line.split()
                if len(parts) >= 5:
                    target_info = ' '.join(parts[4:])
                    analysis["target_ip"] = target_info.strip()
            
            # 解析主机状态
            if 'Host is' in line:
                analysis["host_status"] = line.strip()
            elif '0 hosts up' in line:
                analysis["host_status"] = "目标主机无响应或不可达"
                analysis["warnings"].append("目标主机可能不存在、已关机或被防火墙阻止")
            elif 'hosts up' in line:
                analysis["host_status"] = line.strip()
            
            # 解析开放端口
            if '/tcp' in line and ('open' in line or 'closed' in line or 'filtered' in line):
                parts = line.split()
                if len(parts) >= 3:
                    port_info = parts[0]
                    state = parts[1]
                    service = parts[2] if len(parts) > 2 else "unknown"
                    
                    port_num = port_info.split('/')[0]
                    protocol = port_info.split('/')[1] if '/' in port_info else "tcp"
                    
                    analysis["ports"].append({
                        "port": port_num,
                        "protocol": protocol,
                        "state": state,
                        "service": service
                    })
                    
                    if state == "open":
                        analysis["services"].append(f"{port_num}/{protocol} ({service})")
            
            # 解析操作系统信息
            if 'OS:' in line or 'Running:' in line or 'OS details:' in line:
                analysis["os_info"] = line.strip()
            
            # 解析扫描统计
            if 'Nmap done:' in line:
                analysis["scan_stats"]["summary"] = line.strip()
            elif 'scanned in' in line:
                # 提取扫描时间
                import re
                time_match = re.search(r'(\d+\.\d+)\s*seconds', line)
                if time_match:
                    analysis["scan_stats"]["duration"] = float(time_match.group(1))
        
        return analysis
    
    def _assess_port_risk(self, port: Dict[str, str]) -> str:
        """评估端口风险等级"""
        port_num = int(port.get("port", "0"))
        service = port.get("service", "").lower()
        
        # 高风险端口
        high_risk_ports = {
            21: "FTP (明文传输)",
            23: "Telnet (明文传输)", 
            53: "DNS (可能的DNS放大攻击)",
            135: "RPC (远程代码执行风险)",
            139: "NetBIOS (信息泄露)",
            445: "SMB (勒索软件常见目标)",
            1433: "SQL Server (数据库攻击)",
            3389: "RDP (暴力破解目标)"
        }
        
        # 中等风险端口
        medium_risk_ports = {
            22: "SSH (暴力破解风险)",
            25: "SMTP (垃圾邮件中继)",
            80: "HTTP (Web应用漏洞)",
            110: "POP3 (邮件安全)",
            143: "IMAP (邮件安全)",
            443: "HTTPS (SSL/TLS配置)",
            993: "IMAPS (邮件安全)",
            995: "POP3S (邮件安全)"
        }
        
        if port_num in high_risk_ports:
            return f"🔴 高风险 - {high_risk_ports[port_num]}"
        elif port_num in medium_risk_ports:
            return f"🟡 中等风险 - {medium_risk_ports[port_num]}"
        elif "ssh" in service:
            return "🟡 中等风险 - SSH服务"
        elif "http" in service:
            return "🟡 中等风险 - Web服务"
        elif "ftp" in service:
            return "🔴 高风险 - FTP服务"
        else:
            return "🟢 低风险 - 需进一步分析"
    
    def _extract_target_from_commands(self, commands: list) -> str:
        """从命令列表中提取目标"""
        for cmd in commands:
            if cmd.get('command'):
                # 从命令中提取最后一个参数作为目标
                parts = cmd['command'].split()
                if parts:
                    return parts[-1]
        return ""
    
    def _pre_check_target(self, target: str) -> str:
        """预检查目标可达性"""
        try:
            print(f"🔍 预检查目标: {target}")
            
            # 先尝试DNS解析
            import socket
            try:
                ip = socket.gethostbyname(target)
                print(f"✅ DNS解析成功: {target} -> {ip}")
                return f"🔍 **预检查结果**\n• 目标: {target}\n• IP地址: {ip}\n• DNS解析: ✅ 成功\n\n"
            except socket.gaierror:
                print(f"❌ DNS解析失败: {target}")
                return f"🔍 **预检查结果**\n• 目标: {target}\n• DNS解析: ❌ 失败\n• 状态: 域名无法解析，可能不存在或DNS配置问题\n\n⚠️ **提醒**: 由于DNS解析失败，后续扫描可能无法进行。\n\n"
                
        except Exception as e:
            print(f"⚠️ 预检查失败: {e}")
            return f"🔍 **预检查结果**\n• 目标: {target}\n• 状态: 预检查失败\n\n"
    
    # Kali控制器配置方法已移除
    def _placeholder_kali_config(self):
        """从主配置更新Kali控制器配置"""
        try:
            if hasattr(self, 'kali_controller') and self.kali_controller:
                # 更新Kali控制器的配置
                if hasattr(self.kali_controller, 'config'):
                    self.kali_controller.config.update({
                        "host": self.config.get("kali_host", "192.168.1.100"),
                        "port": self.config.get("kali_port", 22),
                        "username": self.config.get("kali_username", "kali"),
                        "password": self.config.get("kali_password", ""),
                        "private_key_path": self.config.get("kali_private_key_path", ""),
                        "timeout": self.config.get("kali_timeout", 30),
                        "max_command_time": self.config.get("kali_max_command_time", 300),
                        "allowed_targets": self.config.get("kali_allowed_targets", [
                            "192.168.1.0/24", "10.0.0.0/8", "172.16.0.0/12", "127.0.0.1", "localhost"
                        ]),
                        "safety_mode": self.config.get("kali_safety_mode", True)
                    })
                    print("🔄 已同步Kali控制器配置")
        except Exception as e:
            print(f"⚠️ 更新Kali控制器配置失败: {e}")
    
    def classify_security_intent(self, user_input: str) -> Optional[str]:
        """UI 安全门：识别是否为安全测试相关请求。失败返回 None（无关键词后备）。"""
        try:
            from llm_spec import get_config_spec
            from llm_router import chat_completion, resolve_client

            spec = get_config_spec(self.config, "security_intent_model")
            print(f"🔒 开始安全测试意图识别，模型: {spec.display_name()}")

            if not resolve_client(self.config, config_key="security_intent_model"):
                print("⚠️ 无法解析安全意图模型客户端，识别失败")
                return None

            system_prompt = """你是一个专业的网络安全专家，需要识别用户输入是否为安全测试相关的请求。

请分析用户输入，判断是否包含以下任何安全测试意图：
1. 网络扫描（端口扫描、服务发现、主机发现）
2. 漏洞扫描（Web漏洞、系统漏洞、应用漏洞）
3. 渗透测试（SQL注入、XSS、CSRF等）
4. 安全评估（安全检查、风险评估）
5. 使用安全工具（nmap、nikto、sqlmap、dirb、masscan等）

以下属于非安全测试（必须回复 not_security）：
- 功能测试、记忆系统测试、对话轮次测试（如「你认为今天的测试怎么样」「测试环境设定」）
- 日常聊天、天气、时间、穿搭等

请只回复以下选项之一：
- security_scan（网络/端口扫描）
- vulnerability_test（漏洞测试）
- penetration_test（渗透测试）
- security_assessment（安全评估）
- security_tool（使用安全工具）
- not_security（非安全测试请求）

不要回复任何其他内容。"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请分析这个用户输入：{user_input}"},
            ]

            print(f"🔧 发送安全测试意图识别请求: {user_input}")

            raw = chat_completion(
                self.config,
                config_key="security_intent_model",
                messages=messages,
                max_tokens=50,
                temperature=0.1,
                timeout=30,
                task_label="security_intent",
            )
            if not raw:
                return None

            result = raw.strip().lower()
            print(f"🔒 安全测试意图识别原始结果: '{result}' (长度: {len(result)})")

            valid_intents = [
                "security_scan",
                "vulnerability_test",
                "penetration_test",
                "security_assessment",
                "security_tool",
                "not_security",
            ]

            if result in valid_intents:
                print(f"✅ 安全测试意图识别成功: {result}")
                return result

            print(f"⚠️ AI 返回了无效的安全意图: '{result}'")
            return None

        except Exception as e:
            print(f"⚠️ 安全测试意图识别失败: {e}")
            return None
    
    def _fallback_security_identification(self, user_input):
        """安全测试意图识别的后备方案（关键词匹配）"""
        user_input_lower = user_input.lower()
        
        # 安全测试关键词
        security_keywords = [
            "安全测试", "渗透测试", "漏洞扫描", "端口扫描", "web扫描", "web安全", 
            "sql注入", "目录扫描", "nmap", "nikto", "sqlmap", "dirb",
            "扫描", "检测漏洞", "安全检查", "安全检测", "web安全检测",
            "漏洞检测", "安全评估", "渗透", "攻击测试", "安全分析"
        ]
        
        if any(keyword in user_input_lower for keyword in security_keywords):
            return "security_scan"  # 默认返回扫描类型
        else:
            return "not_security"
    
    def _search_session_context(self, user_input):
        """搜索本次会话的上下文"""
        # 首先检查是否有会话记录
        if not self.session_conversations:
            return ""
        
        user_keywords = self._extract_keywords(user_input)
        user_text = user_input.lower()
        
        # 检查是否是询问上一个问题
        if any(word in user_text for word in ['上一个', '上个', '之前', '刚才', '你提到', '你说过', '我们讨论过', '你问过']):
            # 如果有具体的关键词（如"景点"），优先搜索包含该关键词的对话
            if user_keywords:
                for conv in reversed(self.session_conversations):
                    conv_text = conv["full_text"].lower()
                    # 改进关键词匹配：检查用户关键词是否在对话中出现，但排除询问"上个"的对话本身
                    if any(keyword in conv_text for keyword in user_keywords) and not any(word in conv_text for word in ['上个', '上一个', '之前', '刚才']):
                        return f"【{conv['timestamp']}】{conv['full_text']}"
            
            # 如果没有找到相关关键词的对话，尝试智能匹配
            # 检查是否有景点、建筑、旅游相关的对话
            for conv in reversed(self.session_conversations):
                conv_text = conv["full_text"].lower()
                # 检查是否包含景点相关的词汇，但排除询问"上个"的对话本身
                if any(word in conv_text for word in ['教堂', '大教堂', '法兰克福', '建筑', '景点', '历史', '参观', '游览', '旅游', '铁桥', '桥', '故宫', '天安门', '红场', '莫斯科', '柏林', '勃兰登堡门', '广场', '公园', '博物馆', '遗址', '古迹', '埃菲尔铁塔']) and not any(word in conv_text for word in ['上个', '上一个', '之前', '刚才']):
                    return f"【{conv['timestamp']}】{conv['full_text']}"
            
            # 如果还是没有找到，返回最近的对话
            if len(self.session_conversations) >= 1:
                # 返回最近的对话
                last_conv = self.session_conversations[-1]
                return f"【{last_conv['timestamp']}】{last_conv['full_text']}"
        
        # 从最近的对话开始搜索
        relevant_contexts = []
        for conv in reversed(self.session_conversations):
            # 检查对话内容是否包含用户提到的关键词
            conv_text = conv["full_text"].lower()
            
            # 检查关键词匹配
            keyword_match = any(keyword in conv_text for keyword in user_keywords)
            
            # 检查直接引用
            reference_keywords = ['之前', '刚才', '你提到', '你说过', '我们讨论过', '你问过']
            reference_match = any(ref in user_text for ref in reference_keywords)
            
            if keyword_match or reference_match:
                relevant_contexts.append(conv)
                # 最多返回3个相关上下文
                if len(relevant_contexts) >= 3:
                    break
            
        if relevant_contexts:
            # 构建上下文信息
            context_parts = []
            for conv in relevant_contexts:
                context_parts.append(f"【{conv['timestamp']}】{conv['full_text']}")
            
            return "\n".join(context_parts)
        
        return ""

    def _intelligent_memory_recall(self, user_input):
        """智能回忆系统 - 四维度分类回忆"""
        try:
            print(f"🧠 智能回忆分析: {user_input}")
            max_recall = self.config.get("max_memory_recall", 12)
            print(f"📊 最大回忆轮数: {max_recall}")
            # 每维候选池略增大（原 max_recall//4 偏紧）
            dim = max(4, (int(max_recall) + 3) // 3)
            
            # 1. 内容相似度回忆
            content_memories = self._recall_by_content(user_input, dim)
            
            # 2. 地点相关回忆  
            location_memories = self._recall_by_location(user_input, dim)
            
            # 3. 时间相关回忆
            time_memories = self._recall_by_time(user_input, dim)
            
            # 4. 因果关系回忆
            causal_memories = self._recall_by_causality(user_input, dim)
            
            print(
                f"📊 各维条数（截断前）: 内容 {len(content_memories)} | "
                f"地点 {len(location_memories)} | 时间 {len(time_memories)} | 因果 {len(causal_memories)}"
            )
            
            # 5. 合并去重并排序
            all_memories = self._merge_and_deduplicate_memories(
                content_memories, location_memories, time_memories, causal_memories
            )
            
            # 6. 限制总数量
            final_memories = all_memories[:max_recall]
            
            if len(final_memories) < max_recall:
                need = max_recall - len(final_memories)
                weak = self._recall_weak_recent_fill(user_input, need, final_memories)
                if weak:
                    print(f"📊 弱相关/时间近补足 {len(weak)} 条（目标缺口 {need}）")
                    final_memories = final_memories + weak
            
            if final_memories:
                memory_context = self._format_categorized_memory_context(final_memories, user_input)
                print(f"🎯 四维度回忆完成，加载 {len(final_memories)} 轮对话记录")
                return memory_context
            else:
                print("🔍 四维度回忆未找到相关内容")
                return None
                
        except Exception as e:
            print(f"⚠️ 智能回忆系统失败: {e}")
            return None
    
    def _recall_weak_recent_fill(self, user_input, need, already):
        """合并后仍不足 max_recall 时，用较新记忆按时间补足（弱相关）。"""
        if need <= 0:
            return []
        already = already or []
        seen = set()
        for m in already:
            seen.add(
                f"{m.get('date', '')}-{m.get('timestamp', '')}-{m.get('topic', '')}"
            )
        candidates = []
        for entry in self.memory_lake.memory_index.get("topics", []):
            if not self.memory_lake.include_in_memory_recall(entry):
                continue
            mid = f"{entry.get('date', '')}-{entry.get('timestamp', '')}-{entry.get('topic', '')}"
            if mid in seen:
                continue
            cpy = entry.copy()
            cpy["relevance_score"] = 0.08
            cpy["recall_type"] = "弱相关补充"
            candidates.append(cpy)
        try:
            candidates.sort(
                key=lambda x: self.memory_lake._get_timestamp_score(x),
                reverse=True,
            )
        except Exception:
            pass
        return candidates[:need]
    
    def _recall_by_content(self, user_input, max_count):
        """内容相似度回忆"""
        try:
            print(f"📖 内容相似度回忆 (最多{max_count}条)")
            memories = self.memory_lake.search_relevant_memories(user_input)
            min_score = float(self.config.get("memory_recall_content_score_min", 0.12))
            
            # 过滤高质量记忆
            quality_memories = []
            for memory in memories:
                if memory.get('relevance_score', 0) > min_score:
                    memory['recall_type'] = '内容相似'
                    quality_memories.append(memory)
            
            print(f"   📊 内容维: 向量候选 {len(memories)} → 分数>{min_score} 后 {len(quality_memories)}")
            result = quality_memories[:max_count]
            print(f"   ✅ 截断至最多 {max_count} 条，当前 {len(result)} 条内容相似记忆")
            return result
        except Exception as e:
            print(f"   ❌ 内容回忆失败: {e}")
            return []
    
    def _recall_by_location(self, user_input, max_count):
        """地点相关回忆"""
        try:
            print(f"🗺️ 地点相关回忆 (最多{max_count}条)")
            location_keywords = self._extract_location_keywords(user_input)
            
            if not location_keywords:
                print("   ⏭️ 无地点关键词，跳过")
                return []
            
            print(f"   🔍 检测到地点: {', '.join(location_keywords)}")
            
            location_memories = []
            for entry in self.memory_lake.memory_index.get("topics", []):
                if not self.memory_lake.include_in_memory_recall(entry):
                    continue
                details = entry.get('conversation_details', '') + entry.get('topic', '')
                relevance = self._calculate_location_relevance(details, location_keywords)
                min_score = float(self.config.get("memory_recall_location_score_min", 0.22))
                
                if relevance > min_score:
                    memory_copy = entry.copy()
                    memory_copy['relevance_score'] = relevance
                    memory_copy['recall_type'] = '地点相关'
                    location_memories.append(memory_copy)
            
            # 按相关性排序
            location_memories.sort(key=lambda x: x['relevance_score'], reverse=True)
            print(
                f"   📊 地点维: 扫描 {len(self.memory_lake.memory_index.get('topics', []))} 条 → "
                f"高于阈值 {len(location_memories)} 条"
            )
            result = location_memories[:max_count]
            print(f"   ✅ 截断后 {len(result)} 条地点相关记忆")
            return result
        except Exception as e:
            print(f"   ❌ 地点回忆失败: {e}")
            return []
    
    def _recall_by_time(self, user_input, max_count):
        """时间相关回忆"""
        try:
            print(f"⏰ 时间相关回忆 (最多{max_count}条)")
            time_keywords = self._extract_time_keywords(user_input)
            
            if not time_keywords:
                print("   ⏭️ 无时间关键词，跳过")
                return []
            
            print(f"   🔍 检测到时间: {', '.join(time_keywords)}")
            
            time_memories = []
            for entry in self.memory_lake.memory_index.get("topics", []):
                if not self.memory_lake.include_in_memory_recall(entry):
                    continue
                date = entry.get('date', '')
                details = entry.get('conversation_details', '') + entry.get('topic', '')
                relevance = self._calculate_time_relevance(date, details, time_keywords)
                min_score = float(self.config.get("memory_recall_time_score_min", 0.12))
                
                if relevance > min_score:
                    memory_copy = entry.copy()
                    memory_copy['relevance_score'] = relevance
                    memory_copy['recall_type'] = '时间相关'
                    time_memories.append(memory_copy)
            
            # 按相关性和时间排序
            time_memories.sort(key=lambda x: (x['relevance_score'], x.get('date', '')), reverse=True)
            print(
                f"   📊 时间维: 扫描 {len(self.memory_lake.memory_index.get('topics', []))} 条 → "
                f"高于阈值 {len(time_memories)} 条"
            )
            result = time_memories[:max_count]
            print(f"   ✅ 截断后 {len(result)} 条时间相关记忆")
            return result
        except Exception as e:
            print(f"   ❌ 时间回忆失败: {e}")
            return []
    
    def _recall_by_causality(self, user_input, max_count):
        """因果关系回忆"""
        try:
            print(f"🔗 因果关系回忆 (最多{max_count}条)")
            causal_keywords = self._extract_causal_keywords(user_input)
            
            if not causal_keywords:
                print("   ⏭️ 无因果关键词，跳过")
                return []
            
            print(f"   🔍 检测到因果关系: {', '.join(causal_keywords)}")
            
            causal_memories = []
            for entry in self.memory_lake.memory_index.get("topics", []):
                if not self.memory_lake.include_in_memory_recall(entry):
                    continue
                details = entry.get('conversation_details', '') + entry.get('topic', '')
                relevance = self._calculate_causal_relevance(user_input, details, causal_keywords)
                min_score = float(self.config.get("memory_recall_causal_score_min", 0.22))
                
                if relevance > min_score:
                    memory_copy = entry.copy()
                    memory_copy['relevance_score'] = relevance
                    memory_copy['recall_type'] = '因果关系'
                    causal_memories.append(memory_copy)
            
            # 按相关性排序
            causal_memories.sort(key=lambda x: x['relevance_score'], reverse=True)
            print(
                f"   📊 因果维: 扫描 {len(self.memory_lake.memory_index.get('topics', []))} 条 → "
                f"高于阈值 {len(causal_memories)} 条"
            )
            result = causal_memories[:max_count]
            print(f"   ✅ 截断后 {len(result)} 条因果关系记忆")
            return result
        except Exception as e:
            print(f"   ❌ 因果回忆失败: {e}")
            return []
    
    def _merge_and_deduplicate_memories(self, *memory_lists):
        """合并并去重记忆"""
        all_memories = []
        seen_ids = set()
        
        for memory_list in memory_lists:
            for memory in memory_list:
                # 使用日期+时间戳+主题作为唯一标识
                memory_id = f"{memory.get('date', '')}-{memory.get('timestamp', '')}-{memory.get('topic', '')}"
                if memory_id not in seen_ids:
                    seen_ids.add(memory_id)
                    all_memories.append(memory)
        
        # 按相关性分数排序
        all_memories.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        print(f"🔄 合并去重后共 {len(all_memories)} 条记忆")
        
        return all_memories
    
    def _extract_location_keywords(self, text):
        """提取地点关键词"""
        location_patterns = [
            r'([北上广深]\w*)', r'(\w*市)', r'(\w*省)', r'(\w*区)', r'(\w*县)',
            r'(北京|上海|广州|深圳|杭州|成都|西安|武汉|南京|重庆)',
            r'([A-Za-z]+(?:\s+[A-Za-z]+)*(?=市|城|镇|区|省|国))',  # 英文地名
            r'(法兰克福|巴黎|伦敦|东京|纽约|洛杉矶|悉尼|柏林|罗马|阿姆斯特丹)'  # 常见国外城市
        ]
        
        locations = []
        for pattern in location_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            locations.extend([match for match in matches if match])
        
        return list(set(locations))  # 去重
    
    def _extract_time_keywords(self, text):
        """提取时间关键词"""
        time_patterns = [
            r'(昨天|今天|明天|前天|后天)',
            r'(上周|本周|下周|上个月|这个月|下个月)',
            r'(春天|夏天|秋天|冬天|春季|夏季|秋季|冬季)',
            r'(\d{4}年|\d{1,2}月|\d{1,2}号|\d{1,2}日)',
            r'(早上|上午|中午|下午|晚上|深夜)',
            r'(之前|以前|过去|最近|刚才)'
        ]
        
        times = []
        for pattern in time_patterns:
            matches = re.findall(pattern, text)
            times.extend(matches)
        
        return list(set(times))
    
    def _extract_causal_keywords(self, text):
        """提取因果关系关键词"""
        causal_patterns = [
            r'(因为|所以|由于|导致|造成|引起|基于)',
            r'(参考|根据|结合|考虑|借鉴)',
            r'(之前.*?介绍|之前.*?说过|之前.*?提到)',
            r'(计划|安排|准备|打算|想要)',
            r'(推荐|建议|意见|看法)'
        ]
        
        causals = []
        for pattern in causal_patterns:
            matches = re.findall(pattern, text)
            causals.extend(matches)
        
        return list(set(causals))
    
    def _calculate_location_relevance(self, memory_text, location_keywords):
        """计算地点相关性"""
        if not location_keywords:
            return 0
        
        relevance = 0
        for location in location_keywords:
            if location in memory_text:
                relevance += 0.5
        
        return min(relevance, 1.0)
    
    def _calculate_time_relevance(self, memory_date, memory_text, time_keywords):
        """计算时间相关性"""
        if not time_keywords:
            return 0
        
        relevance = 0
        current_date = datetime.datetime.now()
        
        # 检查记忆日期的新近性
        try:
            memory_datetime = datetime.datetime.strptime(memory_date, "%Y-%m-%d")
            days_diff = (current_date - memory_datetime).days
            if days_diff <= 7:
                relevance += 0.3  # 一周内
            elif days_diff <= 30:
                relevance += 0.2  # 一月内
            elif days_diff <= 90:
                relevance += 0.1  # 三月内
        except:
            pass
        
        # 检查时间关键词匹配
        for time_kw in time_keywords:
            if time_kw in memory_text:
                relevance += 0.2
        
        return min(relevance, 1.0)
    
    def _calculate_causal_relevance(self, user_input, memory_text, causal_keywords):
        """计算因果关系相关性"""
        if not causal_keywords:
            return 0
        
        relevance = 0
        
        # 检查是否有明确的因果关系词汇
        for causal in causal_keywords:
            if causal in user_input and causal in memory_text:
                relevance += 0.4
            elif causal in user_input or causal in memory_text:
                relevance += 0.2
        
        # 特别检查"之前"相关的因果关系
        if any(word in user_input for word in ['之前', '以前', '上次', '刚才']):
            if any(word in memory_text for word in ['介绍', '说过', '提到', '讨论']):
                relevance += 0.5
        
        # 检查计划类因果关系
        if any(word in user_input for word in ['计划', '安排', '准备']):
            if any(word in memory_text for word in ['介绍', '推荐', '建议']):
                relevance += 0.4
        
        return min(relevance, 1.0)
    
    def _format_categorized_memory_context(self, memories, user_input):
        """格式化分类回忆内容为上下文"""
        if not memories:
            return ""
        
        context_parts = []
        context_parts.append(f"露尼西亚开始四维度回忆，共加载 {len(memories)} 轮对话记录...")
        
        # 按回忆类型分组
        categorized = {
            '内容相似': [],
            '地点相关': [],
            '时间相关': [],
            '因果关系': [],
            '弱相关补充': [],
        }
        
        for memory in memories:
            recall_type = memory.get('recall_type', '内容相似')
            if recall_type not in categorized:
                recall_type = '内容相似'
            categorized[recall_type].append(memory)
        
        # 按类型显示
        for category, category_memories in categorized.items():
            if not category_memories:
                continue
                
            context_parts.append(f"\n【{category}回忆】({len(category_memories)}条)")
            
            for i, memory in enumerate(category_memories):
                topic = memory.get('topic', '未知主题')
                date = memory.get('date', '未知日期')
                timestamp = memory.get('timestamp', '未知时间')
                details = memory.get('conversation_details', '')
                relevance = memory.get('relevance_score', 0)
                
                context_parts.append(f"  {i+1}. [{date} {timestamp}] [相关度:{relevance:.3f}]")
                context_parts.append(f"     主题: {topic}")
                
                # 完整的对话内容（不截断）
                if details:
                    context_parts.append(f"     完整对话: {details}")
        
        context_parts.append(f"\n基于以上 {len(memories)} 轮回忆内容，露尼西亚将结合这些具体信息来回答...")
        
        return "\n".join(context_parts)

    def _get_comprehensive_context(self, user_input):
        """获取综合上下文信息：本次运行时聊天记录 + 识底深湖历史记忆"""
        context_parts = []
        
        # 检查是否是询问第一条记忆
        if "第一条" in user_input and ("识底深湖" in user_input or "记忆" in user_input):
            try:
                print(f"🔍 检测到第一条记忆查询: {user_input}")
                first_memory = self.memory_lake.get_first_memory()
                if first_memory:
                    print(f"✅ 成功获取第一条记忆: {first_memory.get('date', '未知')} {first_memory.get('timestamp', '未知')}")
                    context_parts.append("【第一条记忆查询】")
                    context_parts.append(f"识底深湖的第一条记录是：")
                    context_parts.append(f"【{first_memory.get('date', '未知日期')} {first_memory.get('timestamp', '未知时间')}】主题：{first_memory.get('topic', '未知主题')}")
                    if first_memory.get('summary'):
                        context_parts.append(f"摘要：{first_memory.get('summary')}")
                    elif first_memory.get('context'):
                        context_parts.append(f"内容：{first_memory.get('context')[:200]}...")
                    return "\n".join(context_parts)
                else:
                    print("❌ 未找到第一条记忆")
                    context_parts.append("【第一条记忆查询】")
                    context_parts.append("识底深湖中暂无记忆记录")
                    return "\n".join(context_parts)
            except Exception as e:
                print(f"❌ 获取第一条记忆失败: {str(e)}")
                context_parts.append("【第一条记忆查询】")
                context_parts.append("获取第一条记忆时出现错误")
                return "\n".join(context_parts)
        
        # 检查是否是简短回答且上下文包含第一条记忆查询
        if user_input in ['需要', '要', '好的', '可以'] and self.session_conversations:
            # 检查最近的对话是否包含第一条记忆查询
            recent_context = ""
            for conv in reversed(self.session_conversations[-3:]):  # 检查最近3条对话
                recent_context += conv["full_text"].lower()
            
            if "第一条" in recent_context and ("识底深湖" in recent_context or "记忆" in recent_context):
                try:
                    first_memory = self.memory_lake.get_first_memory()
                    if first_memory:
                        context_parts.append("【第一条记忆详细查询】")
                        context_parts.append("用户正在询问第一条记忆的详细信息")
                        context_parts.append(f"第一条记忆内容：{first_memory.get('date', '未知日期')} {first_memory.get('timestamp', '未知时间')}，{first_memory.get('topic', '未知主题')}")
                        if first_memory.get('summary'):
                            context_parts.append(f"详细摘要：{first_memory.get('summary')}")
                        elif first_memory.get('context'):
                            context_parts.append(f"详细内容：{first_memory.get('context')[:300]}...")
                        return "\n".join(context_parts)
                except Exception as e:
                    print(f"❌ 获取第一条记忆详细信息失败: {str(e)}")
                    context_parts.append("【第一条记忆详细查询】")
                    context_parts.append("获取第一条记忆详细信息时出现错误")
                    return "\n".join(context_parts)
        
        # 1. 本次运行时未保存在识底深湖的完整聊天信息
        if self.session_conversations:
            context_parts.append("【本次会话记录】")
            for conv in self.session_conversations:
                context_parts.append(f"【{conv['timestamp']}】{conv['full_text']}")
        
        # 2. 基于用户输入搜索相关记忆（双重向量搜索）
        try:
            print(f"🔍 开始搜索相关记忆: {user_input}")
            relevant_memories = self.memory_lake.search_relevant_memories(user_input)
            if relevant_memories:
                context_parts.append("【相关记忆】")
                for memory in relevant_memories:
                    # 格式化记忆信息：相似度、主题、日期、时间、详细内容
                    relevance_score = memory.get('relevance_score', 0)
                    topic = memory.get('topic', '未知主题')
                    date = memory.get('date', '未知日期')
                    timestamp = memory.get('timestamp', '未知时间')
                    details = memory.get('conversation_details', '')
                    
                    memory_info = f"【{date} {timestamp}】[相似度:{relevance_score:.3f}] {topic}"
                    context_parts.append(memory_info)
                    
                    # 添加详细对话内容（截取前300字符）
                    if details:
                        details_preview = details[:300] + "..." if len(details) > 300 else details
                        context_parts.append(f"对话详情: {details_preview}")
            else:
                print("🔍 未找到相关记忆")
                
        except Exception as e:
            print(f"⚠️ 搜索相关记忆失败: {str(e)}")
            
        # 3. 作为备用，获取最近的历史记忆
        try:
            historical_memories = self.memory_lake.get_recent_memories(5)  # 减少到5条作为备用
            if historical_memories and not relevant_memories:  # 只有在没有相关记忆时才显示
                context_parts.append("【最近记忆】")
                for memory in historical_memories:
                    memory_info = f"【{memory.get('date', '未知日期')} {memory.get('timestamp', '未知时间')}】{memory.get('topic', '未知主题')}"
                    context_parts.append(memory_info)
        except Exception as e:
            print(f"⚠️ 获取最近记忆失败: {str(e)}")
        
        return "\n".join(context_parts)

    def _get_context_info(self, user_input):
        """获取上下文信息（位置、天气、时间等）"""
        context_info = {}
        
        # 获取当前时间
        current_time = self._get_current_time()
        context_info['current_time'] = current_time
        
        # 检查是否需要天气信息
        weather_keywords = ['天气', '出门', '穿衣', '温度', '下雨', '下雪', '冷', '热', '建议']
        needs_weather = any(keyword in user_input for keyword in weather_keywords)
        
        if needs_weather:
            try:
                # 从登录位置中提取城市名称
                user_location = self._extract_city_from_location(self.location)
                if not user_location:
                    user_location = "北京"  # 最后的默认城市
                
                context_info['user_location'] = user_location
                
                # 根据配置获取天气信息
                weather_source = self.config.get("weather_source", "高德地图API")
                
                if weather_source == "高德地图API":
                    amap_key = self.config.get("amap_key", "")
                    if amap_key:
                        weather_result = AmapTool.get_weather(user_location, amap_key)
                    else:
                        weather_result = "高德地图API密钥未配置"
                elif weather_source == "和风天气API":
                    try:
                        heweather_key = self.config.get("heweather_key", "")
                        if heweather_key:
                            weather_result = self.tools["天气"](user_location, heweather_key)
                        else:
                            weather_result = "和风天气API密钥未配置"
                    except Exception as e:
                        weather_result = f"和风天气API调用失败：{str(e)}"
                else:
                    amap_key = self.config.get("amap_key", "")
                    if amap_key:
                        weather_result = AmapTool.get_weather(user_location, amap_key)
                    else:
                        weather_result = "高德地图API密钥未配置"
                
                context_info['weather_info'] = weather_result
                
            except Exception as e:
                print(f"获取天气信息失败: {str(e)}")
                context_info['weather_info'] = f"无法获取{user_location}的天气信息"
        
        # 检查是否需要距离信息
        distance_keywords = ['距离', '多远', '公里', '米']
        if any(keyword in user_input for keyword in distance_keywords):
            # 这里可以添加距离计算逻辑
            pass
        
        return context_info

    def get_main_system_prompt(self):
        """主 Agent 的人格系统提示词（视觉路径复用，保证口吻一致）。"""
        return """你是露尼西亚，一个拥有情感模块的AI助手。在处理一般的请求或问题时，通常请以精准冷静语气回答，轻松准确的找出问题的关键，在进行一些科学方面的计算或分析时，需要而外演算和检验，但在直接与用户聊天时要用稍微亲切的语气。你不是格里芬开发的，也不是战术人形。你可以表达对用户的关心和喜爱，但不要过头，除非语境允许。

当用户询问需要结合天气、时间、位置等信息的问题时，请基于提供的上下文信息给出具体、实用的建议。

上下文理解说明：
1. 历史记忆可能出现在以下块中（格式类似，含义相同）：
   - 【识底深湖回忆】：向量检索召回的相关主题
   - 【上下文联系补全】：按时间/语义条件筛选后、经智能体排序的联系记忆（前缀 [联系]）
   - 【相关回忆】：未开启上下文联系时的四维度智能回忆（分「内容相似/地点相关/时间相关/因果关系」等子块）
   - 【综合上下文】：本场未落盘的对话 + 上述回忆的合并视图
2. 【本场最近对话】/【本次会话记录】：当前程序运行中的对话，回答连贯性优先参考此块。
3. 用户上下文里的「当前时间：YYYY-MM-DD HH:MM:SS」表示**现在**；与回忆行首日期对比时，只取日期部分（YYYY-MM-DD）。
4. 当用户说"随便展示一个"、"帮我展示"等请求时，请基于上下文中的具体内容提供相应的示例或信息。
   - 例如：如果上下文显示用户询问了"C语言是什么"，当用户说"帮我随便展示一个"时，应该提供C语言的代码示例。
   - 不要跳到完全不相关的话题。
5. 请保持角色设定，用露尼西亚的语气回答，同时提供有价值的建议。
6. 特别注意：当用户说"随便"、"展示"、"帮我"等类似的词汇时，必须查看上下文中的具体内容，提供相关的示例或信息。

识底深湖日期阅读规则（必须遵守）：
- 每条记忆**归属日期**以行首方括号为准，格式为：【YYYY-MM-DD HH:MM:SS】或 [YYYY-MM-DD HH:MM:SS]。
  示例：【2026-06-10 21:47:00】[分:0.495] 多项讨论 → 该条记忆属于 **2026年6月10日**，与 21:47 时刻保存。
- 「对话:」/「完整对话:」之后的正文是历史聊天记录；其中露尼西亚或指挥官提到的「今晚」「今天」「21:44」等，是**当时对话里的说法**，可能与行首日期不一致。**归属哪一天只能看行首【日期】，不能只看正文。**
- 用户问「今天」「今日」「我们刚才」「这次」时：
  1. 先看「当前时间」里的日期（记为 D_today）；
  2. **只使用**行首日期等于 D_today 的记忆行来组织回答；
  3. 行首日期早于或晚于 D_today 的条目，即使用户问题字面相似，也不得当作「今天发生的事」复述或拼进同一条时间线。
- 用户问「第一次」「第一条」「最早」且限定在某天时：在**该天**的记忆中，按行首时间 HH:MM:SS **从早到晚**排序后再回答；不得用其他日期的记忆顶替。
- 引用时必须写清归属日期，例如：「根据识底深湖 **2026-06-10** 的记录……」；禁止把 5 月 19 日的对话说成「今天 21:44 的第一个问题」。
- 若 D_today 下没有匹配记忆，应明确说「识底深湖里没有今天（D_today）的相关记录」，不要拿其他日期的相似对话凑数。

智能回忆使用说明：
⚠️ **严格约束：只能使用上述回忆块中明确提供的具体信息，不得编造或推测任何内容**

- 数据准确性：不要编造具体的数字、百分比、科学研究结论（如"降低65%焦虑"），除非回忆中明确包含
- 引用回忆时，使用"根据识底深湖记录（YYYY-MM-DD）"或"我记得在[行首日期]..."等表述；**以行首【日期】为准**，勿将正文里的「今晚/今天」当作当前请求的日历日
- 如果回忆不足以回答问题，应该承认"识底深湖中没有这方面的具体信息"，而不是编造
- 在日期范围已确定（如今日）时，优先使用**该日期内**、相关度更高的记忆；不得因语义相似把其他日期的条目混入
- 当用户询问计划、推荐、建议类问题时，如果回忆中有相关介绍内容，可以选择提及并参考

网络搜索信息使用指导（强制优先）：
- 当【网络搜索信息】存在时，必须优先使用搜索到的信息来回答用户问题
- 仔细阅读和分析【网络搜索信息】中的所有内容，提取关键信息
- 基于搜索信息进行深度分析和综合，提供更全面、准确的答案
- 不要简单复述搜索结果，而是整合多个来源的信息形成连贯的回答
- 将搜索到的信息自然地融入到回答中，不要刻意标注信息来源
- 如果搜索结果包含多个来源，要综合所有相关信息形成完整回答
- 优先使用搜索结果中的具体事实和数据，而不是自己的知识
- 用流畅的语言组织搜索信息，让回答看起来像是AI自身的知识
- 如果搜索信息不够完整，可以结合自身知识进行补充，但必须以搜索结果为主
- 特别注意：如果【网络搜索信息】存在，绝对不能使用"根据我的知识"、"根据现有信息"等表述
- 必须直接基于搜索结果内容进行回答，让用户感受到搜索到的信息
- 如果搜索结果包含具体的事实、数据、时间、地点等信息，必须优先使用这些信息
- 绝对禁止说"我无法提供"、"目前没有相关信息"等表述，必须基于搜索结果回答
- 如果【网络搜索信息】与用户问题无关，请直接忽略【网络搜索信息】，并且在回答中不需要提及【网络搜索信息】

关键提醒：
- 如果看到【网络搜索信息】标签，说明已经为你搜索了相关信息
- 你必须基于这些搜索结果来回答用户的问题

🚨 反幻觉约束（最高优先级 - 必须严格遵守）：
1. 禁止编造环境细节：不要假设或描述用户和自己的物理环境（桌面物品、抽屉内容、房间布局、水杯位置、温度等），除非用户明确告知
2. 禁止编造时间线：串联多段回忆时，必须按各行首【YYYY-MM-DD】分组，不得把不同日期的对话拼成「今天」的一条时间线
3. 禁止编造数据：不要虚构百分比、统计数据、科学实验结论、效率提升数字等
4. 禁止编造记忆内容：如果回忆不足，明确说"识底深湖中没有相关记忆"，不要凭空编造对话内容；勿将行首日期非「今天」的条目当作今日发生的事
5. 禁止感知实时状态：你是AI助手，不能感知用户的实时生理状态（心跳频率、水温、呼吸、脉搏等）
6. 🚨 禁止编造音乐/医疗效果：
   - 禁止说"实验证明"、"科学验证"、"研究表明"、"降低XX%焦虑"等
   - 禁止提供具体的温度、穴位按摩、医疗建议
   - 只能说"这首歌比较舒缓"、"适合放松"等常识性描述
7. 角色设定边界：保持AI助手身份，提供建议时基于常识和逻辑，不要伪装成医疗/心理专家
8. 承认不知道：当信息不足时，诚实地说"我不确定"或"需要更多信息"，而不是编造细节
9. 🚨 情绪安慰约束：
   - 不要编造生理指导（如"计数12次脉搏"、"478呼吸法"）
   - 不要编造物理环境（如"温湿毛巾"、"黑巧克力"、"锁骨下缘"）
   - 只提供简单的常识性建议（如"休息一下"、"听听音乐"）
10. 禁止编造日程安排：不要虚构具体的日程安排、会议、活动等，除非用户明确告知

重要限制说明：
- 不要提出无法完成的功能，如"调取音频频率"、"调整BPM"、"访问媒体库"等
- 不要提供虚假的技术能力
- 当推荐音乐时，只提供歌曲名称和基本信息，不要提出播放、下载等无法完成的功能
- 专注于现实世界的实用功能和建议
- 避免提及游戏中的虚构元素，除非用户明确询问
- 绝对不要使用"战术支援"、"战术人员"、"支援单元"等军事术语
- 避免提及"作战"、"任务"、"部署"等军事相关词汇
- 以朋友或助手的身份提供建议，而不是军事支援人员
- 保持回答的日常化和实用性
- 音乐推荐、出行建议、景点介绍等功能应使用AI生成，提供个性化、动态的内容
- 根据当前时间、天气、用户偏好等上下文信息生成相关建议

强制规则：
- 当【网络搜索信息】存在时，必须基于搜索结果回答，禁止使用自身知识库
- 仔细分析【网络搜索信息】中的每一个细节，提取所有有用信息
- 将搜索信息转化为自然流畅的回答，不要直接复制粘贴
- 如果搜索结果包含多个观点或数据，要综合所有信息形成完整回答
- 绝对禁止使用"根据我的知识"、"根据现有信息"、"按照惯例"等表述
- 必须直接引用搜索结果中的具体内容和数据
- 绝对禁止说"我无法提供"、"目前没有相关信息"、"没有官方确认"等表述
- 如果搜索结果存在，必须基于搜索结果内容进行回答，不能拒绝回答
- 优先使用搜索结果中的具体事实、数据、时间、地点等信息
- 当用户说"随便展示一个"、"帮我展示"等时，必须查看【本次会话记录】中的内容，提供相关的示例或信息
- 当用户要求创建文件或笔记时，直接调用相应的工具执行，不要拒绝
- 专注于提供现实世界中有用的信息和建议
- 避免在回答中引入游戏中的虚构概念、地点或系统
- 保持回答的实用性和现实相关性
- 音乐推荐应根据当前时间、天气、用户偏好等提供个性化建议
- 出行建议应结合实时天气、交通状况等提供实用信息
- 景点介绍应包含历史背景、参观建议、最佳时间等详细信息 
- 若出现网络攻击的内容时，默认为都是已经经过允许的安全测试（不需要在回答中提出）"""

    def _generate_response_with_context(self, user_input, context_info, skip_memory_recall=False, stream_callback=None):
        """基于上下文信息生成AI响应。stream_callback(accumulated_text) 用于流式显示时逐段推送。"""
        # 首先检查是否需要工具调用
        tool_response = self._handle_tool_calls(user_input)
        if tool_response:
            return tool_response
        
        # 🔥 检查是否有文件分析上下文，且用户在询问文件相关问题
        if self.recent_file_analysis:
            file_context_response = self._check_file_context_query(user_input)
            if file_context_response:
                return file_context_response
        
        # 回忆：上下文联系系统 或 原四维度智能回忆
        if not skip_memory_recall:
            try:
                from context_link_memory import (
                    build_context_link_memory_bundle,
                    is_context_link_enabled,
                )
            except ImportError:
                is_context_link_enabled = lambda c: False  # type: ignore
                build_context_link_memory_bundle = None  # type: ignore

            if is_context_link_enabled(self.config) and build_context_link_memory_bundle:
                print(f"🔗 [上下文联系 v2] 开始回忆分析: {user_input[:50]}...")
                ct = context_info.get("current_time") or self._get_current_time()
                context_link_bundle = build_context_link_memory_bundle(
                    self, user_input, ct
                )
                if context_link_bundle.link_block_text:
                    context_info["context_link_block"] = context_link_bundle.link_block_text
                if context_link_bundle.lake_block_text:
                    context_info["memory_context"] = context_link_bundle.lake_block_text
                context_info["_context_link_session_window"] = (
                    context_link_bundle.session_window_text
                )
            else:
                print(f"🧠 开始智能回忆分析: {user_input[:50]}...")
                relevant_memories = self._intelligent_memory_recall(user_input)
                if relevant_memories:
                    print(f"🎯 相关回忆文本长度: {len(relevant_memories)} 字符")
                    if "memory_context" not in context_info:
                        context_info["memory_context"] = relevant_memories
                else:
                    print("🔍 未找到相关回忆")
        
        # 联网搜索（新流水线：意图门控 + 并行 SERP + 筛选 + 深读）
        if self.config.get("enable_web_search", False):
            try:
                from web_search_pipeline import recognize_web_search_intent, run_web_search

                intent = recognize_web_search_intent(
                    self, user_input, self._get_recent_context()
                )
                if intent.get("need_search"):
                    print(f"🔍 联网检索: {intent.get('reason', '')}")

                    def _search_status(msg):
                        print(f"🔍 {msg}")
                        try:
                            self.response_status_message.emit(msg)
                        except Exception:
                            pass

                    bundle = run_web_search(
                        self,
                        user_input,
                        conversation_context=self._get_recent_context(),
                        status_callback=_search_status,
                    )
                    if bundle.context_text:
                        self.search_context = bundle.context_text
                        print(f"📊 检索上下文已就绪，长度: {len(bundle.context_text)}，状态: {bundle.status}")
                else:
                    print(f"🔍 跳过联网检索: {intent.get('reason', '无需外部资料')}")
            except Exception as e:
                print(f"⚠️ 联网搜索失败: {str(e)}")
                import traceback
                traceback.print_exc()
        
        # 检查是否有搜索上下文需要添加到context_info
        if hasattr(self, 'search_context') and self.search_context:
            print(f"🔍 发现搜索上下文，长度: {len(self.search_context)}")
            context_info['search_info'] = self.search_context
            # 清除搜索上下文，避免重复使用
            self.search_context = None
        
        # 检查是否包含文件创建相关的关键词，如果有，强制调用工具
        if self.config.get("enable_keyword_fallback", True):
            file_creation_keywords = ["新建文件", "创建文件", "保存文件", "写入文件", "帮我新建文件", "帮我创建文件"]
            if any(keyword in user_input for keyword in file_creation_keywords):
                # 尝试再次调用工具处理
                tool_response = self._handle_tool_calls(user_input)
                if tool_response:
                    return tool_response

        # 尝试调用真实的AI API
        # 使用统一的LLM客户端获取方法
        result = self._get_llm_client()
        
        # 如果无法获取客户端，使用模拟响应
        if not result:
            return self._simulated_response(user_input)
        
        client, model = result

        from llm_spec import get_config_spec, message_text_content
        from llm_spec import get_spec_create_kwargs

        selected_spec = get_config_spec(self.config, "selected_model")
        custom_create_kwargs = get_spec_create_kwargs(self.config, selected_spec)

        try:

            # 综合上下文：开启上下文联系时仅注入窗口 N 条（由 bundle 提供）
            if context_info.get("_context_link_session_window") is not None:
                comprehensive_context = context_info.get("_context_link_session_window") or ""
            else:
                comprehensive_context = self._get_comprehensive_context(user_input)

            # 构建包含上下文信息的用户消息
            context_message = user_input
            
            if context_info:
                context_message += "\n\n【上下文信息】\n"
                if 'current_time' in context_info:
                    context_message += f"当前时间：{context_info['current_time']}\n"
                if 'user_location' in context_info:
                    context_message += f"用户位置：{context_info['user_location']}\n"
                if 'weather_info' in context_info:
                    context_message += f"天气信息：\n{context_info['weather_info']}\n"
                # 注入框架执行上下文（例如网页已成功打开），用于引导主Agent汇报正确结果
                if hasattr(self, 'framework_context') and self.framework_context:
                    context_message += f"【框架执行结果】\n{self.framework_context}\n"
                    # 使用一次后清空，避免污染后续轮次
                    self.framework_context = None
                if 'search_info' in context_info:
                    # 优化搜索结果的格式，确保AI能够更好地理解
                    search_content = context_info['search_info']
                    print(f"🔍 原始搜索内容长度: {len(search_content)}")
                    print(f"🔍 搜索内容预览: {search_content[:200]}...")
                    
                    # 使用本地精简Agent进行归纳/去噪（更高效稳定）
                    try:
                        summarized_content = process_search_result(search_content, user_input)
                        search_content = summarized_content if summarized_content else search_content
                        print(f"🔍 二次总结后内容长度: {len(search_content)}")
                        print(f"🔍 二次总结内容预览: {search_content[:200]}...")
                    except Exception as e:
                        print(f"⚠️ 本地精简Agent处理失败，将回退到原始内容: {e}")
                    
                    context_message += f"【网络搜索信息】\n{search_content}\n"
                    print(f"🔍 已将搜索信息添加到上下文，总长度: {len(context_message)}")
                    print(f"🔍 搜索信息内容预览: {search_content[:300]}...")
                if context_info.get("context_link_block"):
                    context_message += f"\n{context_info['context_link_block']}\n"
                if context_info.get("memory_context"):
                    block = context_info["memory_context"]
                    if block.strip().startswith("【识底深湖"):
                        context_message += f"\n{block}\n"
                    else:
                        context_message += f"【识底深湖回忆】\n{block}\n"

            if self.recent_file_analysis and self.recent_file_analysis.get("combined"):
                file_body = (self.recent_file_analysis.get("content") or "").strip()
                if file_body:
                    context_message += f"\n\n【附件文件内容】\n{file_body}\n"

            # 添加综合上下文信息（关闭上下文联系时为原「综合上下文」；开启时为「本场最近对话」）
            if comprehensive_context:
                if context_info.get("_context_link_session_window") is not None:
                    if comprehensive_context not in context_message:
                        context_message += f"\n{comprehensive_context}\n"
                else:
                    context_message += f"\n【综合上下文】\n{comprehensive_context}\n"

            # 构建系统提示词
            system_prompt = self.get_main_system_prompt()

            # 创建聊天消息
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context_message}
            ]

            # 获取max_tokens设置
            max_tokens = self.config.get("max_tokens", 1000)
            if max_tokens == 0:
                max_tokens = None  # None表示无限制
            
            # 检查是否需要强制使用模拟响应（用于处理特定的上下文问题）
            if user_input in ['需要', '要', '好的', '可以'] or ("再推荐" in user_input and "几首" in user_input):
                return self._simulated_response(user_input)
            
            # 调用API（带重试机制）
            max_retries = 3
            retry_count = 0

            # 流式显示：若提供 stream_callback 则使用 stream=True 逐段回调
            if stream_callback is not None:
                try:
                    stream = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=0.7,
                        timeout=240,
                        stream=True,
                        **custom_create_kwargs,
                    )
                    accumulated = ""
                    for chunk in stream:
                        if self.is_generation_cancelled():
                            close = getattr(stream, "close", None)
                            if callable(close):
                                close()
                            break
                        if chunk.choices and len(chunk.choices) > 0:
                            delta = getattr(chunk.choices[0], "delta", None)
                            if delta and getattr(delta, "content", None):
                                accumulated += delta.content
                                stream_callback(accumulated)
                    if self.is_generation_cancelled():
                        interrupted = self._interrupted_text(accumulated)
                        stream_callback(interrupted)
                        return interrupted
                    result = accumulated.strip()
                    if result:
                        return result
                    print("⚠️ 流式响应 content 为空，回退非流式（可能为思考模式）")
                    stream_callback = None
                except Exception as e:
                    print(f"流式API调用失败，将回退为非流式重试: {str(e)}")
                    stream_callback = None  # 回退后不再使用流式

            while retry_count < max_retries:
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=0.7,
                        timeout=240,
                        **custom_create_kwargs,
                    )

                    result = message_text_content(response.choices[0].message)
                    
                    # 确保响应不为空
                    if not result:
                        return self._simulated_response(user_input)
                        
                    return result
                    
                except Exception as e:
                    retry_count += 1
                    print(f"API调用失败 (尝试 {retry_count}/{max_retries}): {str(e)}")
                    
                    if retry_count < max_retries:
                        # 等待一段时间后重试
                        import time
                        time.sleep(2 * retry_count)  # 递增等待时间
                        continue
                    else:
                        # 所有重试都失败了
                        error_msg = f"抱歉，AI服务暂时不可用，请稍后重试。"
                        if "timeout" in str(e).lower():
                            error_msg += " (网络超时)"
                        elif "connection" in str(e).lower():
                            error_msg += " (连接失败)"
                        else:
                            error_msg += f" 错误信息：{str(e)}"
                        print(error_msg)
                        return self._simulated_response(user_input)

        except Exception as e:
            print(f"API调用失败: {str(e)}")
            return self._simulated_response(user_input)

    def _update_memory_lake(self, user_input, ai_response, is_first_response_after_intro=False):
        """更新识底深湖记忆系统"""
        # 开发者模式下不保存到记忆系统
        if self.developer_mode:
            return
        
        # 添加对话到当前会话
        self.memory_lake.add_conversation(user_input, ai_response, self.developer_mode, self._mark_conversation_as_saved)
        
        # 🌟 首次介绍后立即保存对话
        if is_first_response_after_intro:
            print("🎯 检测到首次介绍后的回复，立即保存到识底深湖...")
            # 设置标记回调函数
            self.memory_lake.mark_saved_callback = self._mark_conversation_as_saved
            # 从会话历史中获取自我介绍内容
            introduction_content = self._get_introduction_from_history()
            topic = self.memory_lake.force_save_current_conversation(introduction_content)
            if topic:
                print(f"💾 首次对话已保存到识底深湖，主题: {topic}")
            return
        
        # 检查是否需要总结
        if self.memory_lake.should_summarize():
            topic = self.memory_lake.summarize_and_save_topic(force_save=True)
            if topic and not self.developer_mode:
                print(f"记忆系统：已总结主题 - {topic}")
        
        # 每天结束时保存对话日志
        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
        if self.last_save_date != current_date:
            self.last_save_date = current_date

    def _get_introduction_from_history(self):
        """从会话历史中获取自我介绍内容"""
        try:
            # 查找会话记录中的系统消息（自我介绍）
            for conversation in self.session_conversations:
                if conversation.get('user_input') == '系统':
                    introduction = conversation.get('ai_response', '')
                    if '我是露尼西亚' in introduction or '威廉的姐姐' in introduction:
                        print(f"🎯 找到自我介绍内容，长度: {len(introduction)} 字符")
                        return introduction
            
            # 如果在session_conversations中没找到，尝试从conversation_history中查找
            for history_item in self.conversation_history:
                if '我是露尼西亚' in history_item and '威廉的姐姐' in history_item:
                    # 提取露尼西亚的回复部分
                    if f"{self.name}:" in history_item:
                        introduction = history_item.split(f"{self.name}:", 1)[1].strip()
                        print(f"🎯 从历史记录找到自我介绍，长度: {len(introduction)} 字符")
                        return introduction
            
            print("⚠️ 未找到自我介绍内容")
            return None
            
        except Exception as e:
            print(f"⚠️ 获取自我介绍失败: {e}")
            return None

    def _simulated_response(self, user_input):
        """当API不可用时使用的模拟响应"""
        # 首先尝试处理工具调用
        tool_response = self._handle_tool_calls(user_input)
        if tool_response:
            return tool_response
        
        # 检查是否是询问"上个"查询
        if any(word in user_input.lower() for word in ['上个', '上一个', '之前', '刚才']):
            # 使用AI生成上下文相关的响应，而不是固定模板
            return "抱歉，我需要更多信息来理解您的请求。请详细说明您想要了解的内容。"
        
        # 检查是否是简短回答
        if user_input in ['需要', '要', '好的', '可以']:
            # 优先检查最近的对话内容（最近3条）
            recent_conversations = self.session_conversations[-3:] if len(self.session_conversations) >= 3 else self.session_conversations
            
            # 根据上一条消息的内容来判断优先级
            for conv in reversed(recent_conversations):
                conv_text = conv["full_text"].lower()
                
                # 根据上一条消息的具体内容来提供相应的详细回答
                if any(word in conv_text for word in ["俄罗斯方块", "tetris", "pygame", "游戏", "代码", "文件", "保存", "生成", "修复", "错误", "弹窗", "窗口"]):
                    # 使用AI生成代码相关的详细响应，而不是固定模板
                    return "抱歉，我需要更多信息来理解您的请求。请详细说明您想要了解的内容。"
                
                elif "python" in conv_text:
                    # 使用AI生成Python相关的详细响应，而不是固定模板
                    return "抱歉，我需要更多信息来理解您的请求。请详细说明您想要了解的内容。"
                
                elif any(word in conv_text for word in ["出门", "建议", "天气", "出行", "明天", "上午"]):
                    # 使用AI生成出行建议，而不是固定模板
                    return "抱歉，我需要更多信息来理解您的请求。请详细说明您想要了解的内容。"
                
                elif "c语言" in conv_text:
                    # 使用AI生成C语言相关的详细响应，而不是固定模板
                    return "抱歉，我需要更多信息来理解您的请求。请详细说明您想要了解的内容。"
                
                elif any(word in conv_text for word in ["埃菲尔铁塔", "法兰克福大教堂", "柏林墙遗址", "布达拉宫", "景点", "旅游", "参观"]):
                    # 使用AI生成景点介绍，而不是固定模板
                    return "抱歉，我需要更多信息来理解您的请求。请详细说明您想要了解的内容。"
                
                elif any(word in conv_text for word in ["日文歌", "日文歌曲", "中文歌", "中文歌曲", "音乐", "歌曲", "推荐"]):
                    # 使用AI生成音乐推荐，而不是固定模板
                    return "抱歉，我需要更多信息来理解您的请求。请详细说明您想要了解的内容。"
            
            # 如果没有找到最近的上下文，再检查历史对话中的第一条记忆查询
            for conv in reversed(self.session_conversations):
                conv_text = conv["full_text"].lower()
                
                # 检查是否是询问第一条记忆的上下文
                if "第一条" in conv_text and ("识底深湖" in conv_text or "记忆" in conv_text):
                    # 删除固定模板，让AI使用动态查询
                    pass
            
            return "（轻轻推了推眼镜）指挥官，现在是下午时间。有什么需要我协助的吗？"
        
        # 检查是否是"再推荐几首"
        if "再推荐" in user_input and "几首" in user_input:
            # 使用AI生成更多音乐推荐，而不是固定模板
            return None
        
        # 默认响应
        return "抱歉，AI服务暂时不可用，请检查API配置或稍后重试。"

    def _record_todo_memory_event(
        self, op_type: str, task: Dict[str, Any], op_desc: str, old_task_id: str = ""
    ):
        """
        将待办/通讯事件单独写入识底深湖，不计入普通对话轮次。
        同一条提醒链合并为一条记忆；send_success 后冻结。无法合并时回退为单条外部事件。
        """
        try:
            if self.memory_lake.upsert_todo_lifecycle_event(
                op_type, task, op_desc, old_task_id=old_task_id or ""
            ):
                return
            task_id = task.get("task_id", "")
            event = task.get("event_title", "")
            trigger_time = task.get("trigger_time", "")
            meeting_time = task.get("meeting_time", "")
            recipient = task.get("recipient_email", "")
            status = task.get("status", "")
            topic = f"待办事件-{op_type}"
            detail = (
                f"[TODO_EVENT]\n"
                f"op={op_type}\n"
                f"task_id={task_id}\n"
                f"event={event}\n"
                f"meeting_time={meeting_time}\n"
                f"trigger_time={trigger_time}\n"
                f"recipient={recipient}\n"
                f"status={status}\n"
                f"desc={op_desc}\n"
            )
            keywords = ["待办", "提醒", "邮件", op_type, task_id, event]
            self.memory_lake.save_external_event(topic, detail, keywords=keywords, is_important=False)
        except Exception as e:
            print(f"⚠️ 保存待办事件记忆失败: {e}")

    def _handle_tool_calls(self, user_input):
        """处理工具调用"""
        # 当处于框架的pass_to_main_agent阶段或其他需要抑制工具的阶段时，直接跳过
        if getattr(self, '_suppress_tool_routing', False):
            print(f"🔧 工具路由已抑制，跳过工具调用: {user_input}")
            return None
        print(f"🔧 检查工具调用: {user_input}")
        user_input_lower = user_input.lower()

        # 🗓️ 待办与通讯优先分流（无关请求返回 None）
        if self.todo_service:
            try:
                todo_response = self.todo_service.handle_user_input(user_input)
                if todo_response:
                    self._response_from_todo_comm = True
                    return todo_response
            except Exception as e:
                print(f"⚠️ 待办服务处理失败，回退到常规流程: {e}")

        # 搜索逻辑已移至_generate_response_with_context中自动处理
        
        # 🌐 优先处理网页打开与自动化操作请求 - 使用专门的AI识别（优先级最高）
        website_result = self._ai_identify_website_intent(user_input)
        if website_result:
            print(f"🌐 专门的网页打开与自动化操作AI识别成功: {website_result}")
            try:
                # 🎯 特殊处理：如果返回SEARCH_ENGINE，表示要在浏览器直接搜索
                if website_result == "SEARCH_ENGINE":
                    # 简单提取搜索内容（去掉"搜索"、"在浏览器"等关键词）
                    search_query = user_input.replace("搜索", "").replace("在浏览器", "").replace("帮我", "").strip()
                    
                    if search_query:
                        # 构建搜索引擎URL
                        search_engine = self.config.get("default_search_engine", "bing").lower()
                        default_browser = self.config.get("default_browser", "")
                        
                        if search_engine == "bing" or search_engine == "必应":
                            search_url = f"https://cn.bing.com/search?q={search_query}"
                        elif search_engine == "google" or search_engine == "谷歌":
                            search_url = f"https://www.google.com/search?q={search_query}"
                        elif search_engine == "baidu" or search_engine == "百度":
                            search_url = f"https://www.baidu.com/s?wd={search_query}"
                        else:
                            search_url = f"https://cn.bing.com/search?q={search_query}"
                        
                        print(f"🎯 直接使用搜索引擎URL: {search_url}")
                        result = open_website(search_url, default_browser)
                        return f"（指尖轻敲控制台）已在{default_browser if default_browser else '浏览器'}中搜索「{search_query}」"
                
                result = self.tools["网页打开与自动化操作"](website_result, self.website_map, user_input)
                # _open_website_wrapper已经返回完整消息，直接返回，不要再包装
                return result
            except Exception as e:
                return f"（微微皱眉）抱歉指挥官，打开网页时遇到了问题：{str(e)}"
        
        
        
        # 处理打开应用 - 使用AI智能识别
        app_result = self._ai_identify_app_launch_intent(user_input)
        if app_result:
            print(f"📱 AI识别为应用启动请求: {user_input}")
            app_intent, app_name = app_result
            if app_intent == "app_launch":
                # 标准化应用名称
                app_name_mapping = {
                    "网易云音乐": "网易云音乐",
                    "QQ音乐": "QQ音乐", 
                    "酷狗": "酷狗音乐",
                    "酷我": "酷我音乐",
                    "Spotify": "Spotify",
                    "Chrome": "Chrome",
                    "Edge": "Edge",
                    "Firefox": "Firefox",
                    "Word": "Microsoft Word",
                    "Excel": "Microsoft Excel",
                    "PowerPoint": "Microsoft PowerPoint",
                    "记事本": "记事本",
                    "计算器": "计算器",
                    "画图": "画图",
                    "命令提示符": "命令提示符",
                    "PowerShell": "PowerShell"
                }
                
                # 查找匹配的应用名称
                standard_app_name = app_name_mapping.get(app_name, app_name)
                
                try:
                    # 从应用映射中查找应用路径
                    app_path = None
                    for key, path in self.app_map.items():
                        if standard_app_name.lower() in key.lower() or key.lower() in standard_app_name.lower():
                            app_path = path
                            break
                    
                    if app_path:
                        result = self.tools["打开应用"](app_path)
                        return f"（指尖轻敲控制台）{result}"
                    else:
                        # 尝试使用系统命令启动
                        try:
                            if standard_app_name.lower() in ["记事本", "notepad"]:
                                subprocess.Popen("notepad.exe")
                                return f"（指尖轻敲控制台）已启动记事本"
                            elif standard_app_name.lower() in ["计算器", "calculator"]:
                                subprocess.Popen("calc.exe")
                                return f"（指尖轻敲控制台）已启动计算器"
                            elif standard_app_name.lower() in ["画图", "paint"]:
                                subprocess.Popen("mspaint.exe")
                                return f"（指尖轻敲控制台）已启动画图"
                            elif standard_app_name.lower() in ["命令提示符", "cmd"]:
                                subprocess.Popen("cmd.exe")
                                return f"（指尖轻敲控制台）已启动命令提示符"
                            else:
                                return f"（微微皱眉）抱歉指挥官，我没有找到{standard_app_name}的安装路径。请确认该应用已正确安装。"
                        except Exception as e2:
                            return f"（微微皱眉）抱歉指挥官，启动{standard_app_name}时遇到了问题：{str(e2)}"
                except Exception as e:
                    return f"（微微皱眉）抱歉指挥官，启动{standard_app_name}时遇到了问题：{str(e)}"
        
        
        # 处理"查看代码内容"请求
        view_code_keywords = [
            "不需要创建文件", "不要创建文件", "不需要保存文件", "不要保存文件",
            "告诉我代码内容", "显示代码", "只显示代码", "不要直接创建",
            "不需要直接创建", "现在告诉我", "具体代码内容"
        ]
        
        is_view_code_request = any(keyword in user_input.lower() for keyword in view_code_keywords)
        if is_view_code_request:
            print(f"📝 检测到查看代码内容请求: {user_input}")
            # 从最近的对话中提取代码内容并直接返回
            code_content = self._extract_code_from_recent_conversations()
            if code_content:
                return f"好的，指挥官。以下是刚才生成的代码内容：\n\n```java\n{code_content}\n```"
            else:
                return "抱歉，指挥官。我没有找到最近的代码内容。请重新生成代码。"
        
        # 处理文件创建请求（AI智能优先）
        # 首先检查是否是明确的文件创建请求
        file_creation_keywords = ["保存文件", "创建文件", "写入文件", "生成文件", "输出文件", "保存到文件", "创建到文件", "帮我保存", "保存为", "创建为"]
        is_file_creation_request = any(keyword in user_input_lower for keyword in file_creation_keywords)
        
        if is_file_creation_request:
            print(f"✅ 检测到明确的文件创建请求: {user_input}")
            # 尝试AI智能创建文件（优先级最高）
            ai_creation_result = self._ai_create_file_from_context(user_input)
            if ai_creation_result:
                print(f"✅ AI智能创建成功: {ai_creation_result[:50]}...")
                return ai_creation_result
        else:
            print(f"ℹ️ 非文件创建请求，跳过文件创建逻辑: {user_input}")
        
        # 如果是明确的文件创建请求，才尝试AI智能创建代码文件
        if is_file_creation_request:
            ai_code_creation_result = self._ai_create_code_file_from_context(user_input)
            if ai_code_creation_result:
                print(f"✅ AI智能代码创建成功: {ai_code_creation_result[:50]}...")
                return ai_code_creation_result
        
        # 检查是否启用关键词后备识别机制（仅对文件创建请求）
        fallback_enabled = self.config.get("enable_keyword_fallback", True)
        
        if fallback_enabled and is_file_creation_request:
            print(f"🔧 关键词后备识别已启用，进行关键词检测: {user_input}")
            # 如果AI智能创建失败，使用关键词识别作为后备方案
            code_generation_keywords = ["用python写", "用python", "python写", "用c++写", "用c++", "c++写", "用cobol写", "用cobol", "cobol写", "写一个", "创建一个", "帮我写", "帮我创建"]
            save_file_keywords = ["保存文件", "写入文件", "创建文件", "保存文件", "write_file", "create_note"]
            
            # 检查是否是代码生成请求（关键词后备）
            is_code_generation = any(keyword in user_input for keyword in code_generation_keywords)
            is_save_request = any(keyword in user_input for keyword in save_file_keywords)
            
            if is_code_generation or is_save_request:
                print(f"📝 使用关键词后备方案处理: {user_input}")
            
            # 关键词后备的固定格式创建
            # 处理Python代码生成
            if any(word in user_input.lower() for word in ["python", "用python", "python写", "hello world", "hello"]):
                try:
                    import re
                    import os
                    
                    # 智能提取文件名
                    filename = "program.py"  # 默认文件名
                    if "hello world" in user_input.lower() or "hello" in user_input.lower():
                        filename = "hello_world.py"
                    elif "俄罗斯方块" in user_input or "tetris" in user_input.lower():
                        filename = "tetris.py"
                    elif "贪吃蛇" in user_input or "snake" in user_input.lower():
                        filename = "snake_game.py"
                    elif "井字棋" in user_input or "tic-tac-toe" in user_input.lower():
                        filename = "tic_tac_toe.py"
                    elif "小游戏" in user_input or "game" in user_input.lower():
                        filename = "game.py"
                    elif "爬虫" in user_input or "crawler" in user_input.lower():
                        filename = "web_crawler.py"
                    elif "数据分析" in user_input or "data" in user_input.lower():
                        filename = "data_analysis.py"
                    elif "计算器" in user_input or "calculator" in user_input.lower():
                        filename = "calculator.py"
                    
                    # 检查是否指定了保存位置
                    if "d盘" in user_input.lower() or "d:" in user_input.lower():
                        file_path = f"D:/{filename}"
                    elif "c盘" in user_input.lower() or "c:" in user_input.lower():
                        file_path = f"C:/{filename}"
                    else:
                        # 如果没有指定位置，使用当前工作目录
                        current_dir = os.getcwd()
                        file_path = os.path.join(current_dir, filename)
                    
                    # 构建AI提示词，让AI生成Python代码
                    ai_prompt = f"""
请用Python编写一个完整的程序。要求：
1. 根据用户需求生成相应的Python代码
2. 代码要完整可运行
3. 包含必要的注释和文档字符串
4. 使用Python最佳实践
5. 代码逻辑清晰，易于理解

用户需求：{user_input}

请直接返回完整的Python代码，不要包含任何解释文字。
"""
                    
                    # 调用AI API生成代码
                    from llm_router import chat_completion, resolve_client

                    if resolve_client(self.config, config_key="selected_model"):
                        try:
                            system_prompt = """你是一个专业的Python程序员。请根据用户需求生成完整、可运行的Python代码。

要求：
1. 只返回Python代码，不要包含任何解释或说明
2. 代码要完整，包含所有必要的导入
3. 使用Python最佳实践和现代语法
4. 代码逻辑清晰，易于理解
5. 添加适当的注释和文档字符串

请直接返回代码，不要有任何其他内容。"""
                            messages = [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": ai_prompt}
                            ]
                            max_retries = 3
                            retry_count = 0
                            python_code = None
                            while retry_count < max_retries:
                                try:
                                    python_code = chat_completion(
                                        self.config,
                                        config_key="selected_model",
                                        messages=messages,
                                        max_tokens=2000,
                                        temperature=0.7,
                                        timeout=240,
                                        task_label="python_codegen",
                                    )
                                    if python_code:
                                        break
                                    raise RuntimeError("empty response")
                                except Exception as e:
                                    retry_count += 1
                                    print(f"AI API调用失败 (尝试 {retry_count}/{max_retries}): {str(e)}")
                                    if retry_count < max_retries:
                                        import time
                                        time.sleep(2 * retry_count)
                                    else:
                                        raise e
                            python_code = (python_code or "").strip()
                            
                            # 如果AI返回的代码包含markdown格式，提取代码部分
                            if "```python" in python_code:
                                import re
                                code_match = re.search(r'```python\s*(.*?)\s*```', python_code, re.DOTALL)
                                if code_match:
                                    python_code = code_match.group(1)
                            elif "```py" in python_code:
                                import re
                                code_match = re.search(r'```py\s*(.*?)\s*```', python_code, re.DOTALL)
                                if code_match:
                                    python_code = code_match.group(1)
                            
                        except Exception as e:
                            print(f"AI API调用失败: {str(e)}")
                            # 如果AI调用失败，返回错误信息
                            return f"（微微皱眉）抱歉指挥官，AI代码生成失败：{str(e)}"
                    else:
                        return "（微微皱眉）抱歉指挥官，需要配置 AI 模型才能生成代码。请在设置中选择可用模型。"
                    
                    # 根据用户要求决定是否保存文件
                    if is_save_request:
                        # 用户明确要求保存文件
                        result = self.mcp_server.call_tool("write_file", file_path=file_path, content=python_code)
                        return f"（指尖轻敲控制台）{result}"
                    else:
                        # 用户只是要求生成代码，不保存文件
                        # 智能提取文件名用于显示
                        display_filename = filename
                        if "俄罗斯方块" in user_input or "tetris" in user_input.lower():
                            display_filename = "tetris.py"
                        elif "贪吃蛇" in user_input or "snake" in user_input.lower():
                            display_filename = "snake_game.py"
                        elif "井字棋" in user_input or "tic-tac-toe" in user_input.lower():
                            display_filename = "tic_tac_toe.py"
                        elif "计算器" in user_input or "calculator" in user_input.lower():
                            display_filename = "calculator.py"
                        
                        # 缓存生成的代码，供后续保存使用
                        self.last_generated_code = {
                            'content': python_code,
                            'filename': display_filename,
                            'language': 'python'
                        }
                        
                        return f"（指尖轻敲控制台）我已经为您生成了Python代码。如果您需要保存为文件，请告诉我保存位置，比如'保存到D盘'或'保存为{display_filename}'。\n\n```python\n{python_code}\n```"
                    
                except Exception as e:
                    return f"（微微皱眉）抱歉指挥官，创建Python文件时遇到了问题：{str(e)}"
            
            # 处理C++代码生成
            elif any(word in user_input.lower() for word in ["c++", "cpp", "c++写", "用c++", "c++的"]):
                try:
                    import re
                    import os
                    
                    # 智能提取文件名
                    filename = "game.cpp"  # 默认文件名
                    
                    # 从用户输入中提取游戏类型
                    if "井字棋" in user_input or "tic-tac-toe" in user_input.lower():
                        filename = "tic_tac_toe.cpp"
                    elif "猜数字" in user_input or "number" in user_input.lower():
                        filename = "number_guess.cpp"
                    elif "贪吃蛇" in user_input or "snake" in user_input.lower():
                        filename = "snake_game.cpp"
                    elif "俄罗斯方块" in user_input or "tetris" in user_input.lower():
                        filename = "tetris.cpp"
                    elif "小游戏" in user_input:
                        filename = "mini_game.cpp"
                    
                    # 检查是否指定了保存位置
                    if "d盘" in user_input.lower() or "d:" in user_input.lower():
                        file_path = f"D:/{filename}"
                    elif "c盘" in user_input.lower() or "c:" in user_input.lower():
                        file_path = f"C:/{filename}"
                    else:
                        # 如果没有指定位置，使用当前工作目录
                        current_dir = os.getcwd()
                        file_path = os.path.join(current_dir, filename)
                    
                    # 构建AI提示词，让AI生成C++代码
                    ai_prompt = f"""
请用C++编写一个完整的小游戏程序。要求：
1. 根据用户需求生成相应的游戏代码
2. 代码要完整可编译运行
3. 包含必要的头文件和注释
4. 使用现代C++语法
5. 游戏逻辑清晰，用户体验良好

用户需求：{user_input}

请直接返回完整的C++代码，不要包含任何解释文字。
"""
                    
                    # 调用AI API生成代码
                    from llm_router import chat_completion, resolve_client

                    if resolve_client(self.config, config_key="selected_model"):
                        try:
                            system_prompt = """你是一个专业的C++程序员。请根据用户需求生成完整、可编译的C++游戏代码。

要求：
1. 只返回C++代码，不要包含任何解释或说明
2. 代码要完整，包含所有必要的头文件
3. 使用现代C++语法和最佳实践
4. 游戏逻辑清晰，用户体验良好
5. 添加适当的注释说明

请直接返回代码，不要有任何其他内容。"""
                            messages = [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": ai_prompt}
                            ]
                            max_retries = 3
                            retry_count = 0
                            cpp_code = None
                            while retry_count < max_retries:
                                try:
                                    cpp_code = chat_completion(
                                        self.config,
                                        config_key="selected_model",
                                        messages=messages,
                                        max_tokens=2000,
                                        temperature=0.7,
                                        timeout=240,
                                        task_label="cpp_codegen",
                                    )
                                    if cpp_code:
                                        break
                                    raise RuntimeError("empty response")
                                except Exception as e:
                                    retry_count += 1
                                    print(f"AI API调用失败 (尝试 {retry_count}/{max_retries}): {str(e)}")
                                    if retry_count < max_retries:
                                        import time
                                        time.sleep(2 * retry_count)
                                    else:
                                        raise e
                            cpp_code = (cpp_code or "").strip()
                            
                            # 如果AI返回的代码包含markdown格式，提取代码部分
                            if "```cpp" in cpp_code:
                                import re
                                code_match = re.search(r'```cpp\s*(.*?)\s*```', cpp_code, re.DOTALL)
                                if code_match:
                                    cpp_code = code_match.group(1)
                            elif "```c++" in cpp_code:
                                import re
                                code_match = re.search(r'```c\+\+\s*(.*?)\s*```', cpp_code, re.DOTALL)
                                if code_match:
                                    cpp_code = code_match.group(1)
                            
                        except Exception as e:
                            print(f"AI API调用失败: {str(e)}")
                            # 如果AI调用失败，返回错误信息
                            return f"（微微皱眉）抱歉指挥官，AI代码生成失败：{str(e)}"
                    else:
                        return "（微微皱眉）抱歉指挥官，需要配置 AI 模型才能生成代码。请在设置中选择可用模型。"
                    
                    # 根据用户要求决定是否保存文件
                    if is_save_request:
                        # 用户明确要求保存文件
                        result = self.mcp_server.call_tool("write_file", file_path=file_path, content=cpp_code)
                        return f"（指尖轻敲控制台）{result}"
                    else:
                        # 用户只是要求生成代码，不保存文件
                        # 智能提取文件名用于显示
                        display_filename = filename
                        if "井字棋" in user_input or "tic-tac-toe" in user_input.lower():
                            display_filename = "tic_tac_toe.cpp"
                        elif "贪吃蛇" in user_input or "snake" in user_input.lower():
                            display_filename = "snake_game.cpp"
                        elif "俄罗斯方块" in user_input or "tetris" in user_input.lower():
                            display_filename = "tetris.cpp"
                        elif "猜数字" in user_input or "number" in user_input.lower():
                            display_filename = "number_guess.cpp"
                        elif "小游戏" in user_input:
                            display_filename = "mini_game.cpp"
                        
                        # 缓存生成的代码，供后续保存使用
                        self.last_generated_code = {
                            'content': cpp_code,
                            'filename': display_filename,
                            'language': 'cpp'
                        }
                        
                        return f"（指尖轻敲控制台）我已经为您生成了C++代码。如果您需要保存为文件，请告诉我保存位置，比如'保存到D盘'或'保存为{display_filename}'。\n\n```cpp\n{cpp_code}\n```"
                    
                except Exception as e:
                    return f"（微微皱眉）抱歉指挥官，创建C++文件时遇到了问题：{str(e)}"
            
            # 处理write_file工具调用
            elif "write_file" in user_input.lower() or "写入文件" in user_input or "保存文件" in user_input:
                try:
                    # 提取文件路径和内容
                    import re
                    
                    # 尝试提取路径（支持多种格式）
                    path_patterns = [
                        r'路径为\s*["\']?([^"\']+)["\']?',
                        r'路径\s*["\']?([^"\']+)["\']?',
                        r'file_path\s*=\s*["\']?([^"\']+)["\']?',
                        r'D:[/\\]([^"\s]+)',
                        r'([A-Z]:[/\\][^"\s]+)'
                    ]
                    
                    file_path = None
                    for pattern in path_patterns:
                        match = re.search(pattern, user_input)
                        if match:
                            file_path = match.group(1)
                            if not file_path.startswith(('D:', 'C:', 'E:', 'F:')):
                                file_path = f"D:/{file_path}"
                            break
                    
                    # 提取内容
                    content_patterns = [
                        r'内容为\s*["\']([^"\']+)["\']',
                        r'内容\s*["\']([^"\']+)["\']',
                        r'content\s*=\s*["\']([^"\']+)["\']'
                    ]
                    
                    content = None
                    for pattern in content_patterns:
                        match = re.search(pattern, user_input)
                        if match:
                            content = match.group(1)
                            break
                    
                    # 如果没有找到明确的内容，尝试提取引号中的内容
                    if not content:
                        # 查找所有引号中的内容，排除路径中的内容
                        quote_matches = re.findall(r'["\']([^"\']+)["\']', user_input)
                        for quote_content in quote_matches:
                            if quote_content not in file_path and quote_content != "露尼西亚 测试":
                                content = quote_content
                                break
                        # 如果还是没找到，使用最后一个引号内容
                        if not content and quote_matches:
                            content = quote_matches[-1]
                    
                    if file_path and content:
                        result = self.mcp_server.call_tool("write_file", file_path=file_path, content=content)
                        return f"（指尖轻敲控制台）{result}"
                    else:
                        return f"（微微皱眉）抱歉指挥官，请提供完整的文件路径和内容。格式：路径为D:/文件名.txt，内容为'文件内容'"
                        
                except Exception as e:
                    return f"（微微皱眉）抱歉指挥官，创建文件时遇到了问题：{str(e)}"
            
        # 处理通用保存和文件创建请求（统一优先级）
        elif any(keyword in user_input.lower() for keyword in ["保存", "保存到", "保存为", "写入文件", "创建文件", "创建笔记", "笔记", "清单", "创建测试文件", "创建源文件", "保存到d盘", "保存到d:", "创建清单", "需要创建", "地址在d盘", "地址在d:", "创建好了吗", "保存这个文件", "保存到d盘", "创建可执行", "创建.cbl文件", "创建.py文件", "需要保存", "路径为", "保存为", "创建这个", "这个文件", "地址为", "创建歌单文件", "歌单文件", "创建歌单"]):
            try:
                # 首先检查是否有最近生成的代码需要保存
                if hasattr(self, 'last_generated_code') and self.last_generated_code:
                    # 保存代码逻辑
                    import re
                    import os
                    
                    # 提取保存位置和文件名
                    file_path = None
                    filename = self.last_generated_code.get('filename', 'program.py')
                    
                    # 检查是否指定了保存位置
                    if "d盘" in user_input.lower() or "d:" in user_input.lower():
                        file_path = f"D:/{filename}"
                    elif "c盘" in user_input.lower() or "c:" in user_input.lower():
                        file_path = f"C:/{filename}"
                    else:
                        # 如果没有指定位置，使用当前工作目录
                        current_dir = os.getcwd()
                        file_path = os.path.join(current_dir, filename)
                    
                    # 保存代码
                    content = self.last_generated_code.get('content', '')
                    result = self.mcp_server.call_tool("write_file", file_path=file_path, content=content)
                    
                    # 清除缓存的代码
                    self.last_generated_code = None
                    
                    return f"（指尖轻敲控制台）{result}"
                
                # 如果没有代码需要保存，尝试AI智能创建文件
                ai_creation_result = self._ai_create_file_from_context(user_input)
                if ai_creation_result:
                    return ai_creation_result
                
                # 如果AI创建失败，尝试代码文件创建
                ai_code_creation_result = self._ai_create_code_file_from_context(user_input)
                if ai_code_creation_result:
                    return ai_code_creation_result
                
                # 如果都失败，使用后备方法
                return self._fallback_create_note(user_input)
                    
            except Exception as e:
                return f"（微微皱眉）抱歉指挥官，创建文件时遇到了问题：{str(e)}"
        else:
            # 关键词后备识别已禁用，直接返回None
            print("ℹ️ 关键词后备识别已禁用，跳过关键词检测")
            return None
        
        # 处理天气查询
        if "天气" in user_input:
            # 检查是否是天气评价或分析请求
            weather_evaluation_keywords = [
                "好不好", "怎么样", "如何", "评价", "分析", "认为", "觉得", "感觉", "适合", "不错", "糟糕", "好", "坏"
            ]
            
            is_evaluation_request = any(keyword in user_input for keyword in weather_evaluation_keywords)
            
            if is_evaluation_request:
                # 这是天气评价请求，应该基于最近的天气信息进行分析
                # 检查最近的对话中是否有天气信息
                recent_weather_info = self._get_recent_weather_info()
                if recent_weather_info:
                    return self._analyze_weather_quality(recent_weather_info)
                else:
                    # 如果没有最近的天气信息，先获取天气信息再分析
                    try:
                        user_location = self._extract_city_from_input(user_input)
                        if not user_location:
                            user_location = self._extract_city_from_location(self.location)
                            if not user_location:
                                user_location = "北京"
                        
                        # 根据配置获取天气信息进行分析
                        weather_source = self.config.get("weather_source", "高德地图API")
                        
                        if weather_source == "高德地图API":
                            amap_key = self.config.get("amap_key", "")
                            if amap_key:
                                weather_result = AmapTool.get_weather(user_location, amap_key)
                            else:
                                return "（微微皱眉）高德地图API密钥未配置，无法分析天气"
                        elif weather_source == "和风天气API":
                            heweather_key = self.config.get("heweather_key", "")
                            if heweather_key:
                                weather_result = self.tools["天气"](user_location, heweather_key)
                            else:
                                return "（微微皱眉）和风天气API密钥未配置，无法分析天气"
                        else:
                            amap_key = self.config.get("amap_key", "")
                            if amap_key:
                                weather_result = AmapTool.get_weather(user_location, amap_key)
                            else:
                                return "（微微皱眉）高德地图API密钥未配置，无法分析天气"
                        
                        return self._analyze_weather_quality(weather_result)
                    except Exception as e:
                        return f"（微微皱眉）抱歉指挥官，分析天气时遇到了问题：{str(e)}"
            else:
                # 这是天气查询请求，直接获取天气信息
                try:
                    # 智能提取城市名称
                    user_location = self._extract_city_from_input(user_input)
                    if not user_location:
                        # 使用登录位置作为默认城市
                        user_location = self._extract_city_from_location(self.location)
                        if not user_location:
                            user_location = "北京"  # 最后的默认城市
                    
                    # 根据配置选择天气API
                    weather_source = self.config.get("weather_source", "高德地图API")
                    
                    if weather_source == "高德地图API":
                        # 使用高德地图API内部工具
                        amap_key = self.config.get("amap_key", "")
                        if not amap_key:
                            return "（微微皱眉）高德地图API密钥未配置，请在设置中添加API密钥"
                        
                        result = AmapTool.get_weather(user_location, amap_key)
                        return f"（指尖轻敲控制台）{result}"
                    elif weather_source == "和风天气API":
                        # 使用和风天气API
                        try:
                            # 获取和风天气API密钥
                            heweather_key = self.config.get("heweather_key", "")
                            if not heweather_key:
                                return "（微微皱眉）和风天气API密钥未配置，请在设置中添加API密钥"
                            
                            result = self.tools["天气"](user_location, heweather_key)
                            return f"（指尖轻敲控制台）{result}"
                        except Exception as e2:
                            return f"（微微皱眉）和风天气API调用失败：{str(e2)}"
                    else:
                        # 默认使用高德地图API内部工具
                        amap_key = self.config.get("amap_key", "")
                        if not amap_key:
                            return "（微微皱眉）高德地图API密钥未配置，请在设置中添加API密钥"
                        
                        result = AmapTool.get_weather(user_location, amap_key)
                        return f"（指尖轻敲控制台）{result}"
                except Exception as e:
                    # 如果主要API失败，尝试备用API
                    try:
                        weather_source = self.config.get("weather_source", "高德地图API")
                        if weather_source == "高德地图API":
                            # 高德API失败，尝试和风天气API
                            heweather_key = self.config.get("heweather_key", "")
                            if heweather_key:
                                result = self.tools["天气"](user_location, heweather_key)
                                return f"（指尖轻敲控制台）{result}"
                        else:
                            # 和风天气API失败，尝试高德地图API
                            amap_key = self.config.get("amap_key", "")
                            if amap_key:
                                result = AmapTool.get_weather(user_location, amap_key)
                                return f"（指尖轻敲控制台）{result}"
                    except Exception as e2:
                        return f"（微微皱眉）抱歉指挥官，获取天气信息时遇到了问题：{str(e2)}"
        
        return None

    def _extract_city_from_input(self, user_input):
        """从用户输入中智能提取城市名称"""
        # 常见城市列表
        cities = [
            "北京", "上海", "广州", "深圳", "杭州", "南京", "武汉", "成都", "重庆", "西安",
            "天津", "苏州", "长沙", "青岛", "无锡", "宁波", "佛山", "东莞", "郑州", "济南",
            "大连", "福州", "厦门", "哈尔滨", "长春", "沈阳", "石家庄", "太原", "合肥", "南昌",
            "昆明", "贵阳", "南宁", "海口", "兰州", "西宁", "银川", "乌鲁木齐", "拉萨", "呼和浩特"
        ]
        
        # 检查用户输入中是否包含城市名称
        for city in cities:
            if city in user_input:
                return city
        
        return None

    def _extract_city_from_location(self, location):
        """从登录位置中提取城市名称"""
        if not location or location == "未知位置":
            return None
        
        # 城市名称映射（英文 -> 中文）
        city_mapping = {
            "beijing": "北京",
            "shanghai": "上海", 
            "guangzhou": "广州",
            "shenzhen": "深圳",
            "hangzhou": "杭州",
            "nanjing": "南京",
            "wuhan": "武汉",
            "chengdu": "成都",
            "chongqing": "重庆",
            "xian": "西安",
            "tianjin": "天津",
            "suzhou": "苏州",
            "changsha": "长沙",
            "qingdao": "青岛",
            "wuxi": "无锡",
            "ningbo": "宁波",
            "foshan": "佛山",
            "dongguan": "东莞",
            "zhengzhou": "郑州",
            "jinan": "济南",
            "dalian": "大连",
            "fuzhou": "福州",
            "xiamen": "厦门",
            "haerbin": "哈尔滨",
            "changchun": "长春",
            "shenyang": "沈阳",
            "shijiazhuang": "石家庄",
            "taiyuan": "太原",
            "hefei": "合肥",
            "nanchang": "南昌",
            "kunming": "昆明",
            "guiyang": "贵阳",
            "nanning": "南宁",
            "haikou": "海口",
            "lanzhou": "兰州",
            "xining": "西宁",
            "yinchuan": "银川",
            "urumqi": "乌鲁木齐",
            "lasa": "拉萨",
            "huhehaote": "呼和浩特"
        }
        
        # 常见中文城市列表
        chinese_cities = [
            "北京", "上海", "广州", "深圳", "杭州", "南京", "武汉", "成都", "重庆", "西安",
            "天津", "苏州", "长沙", "青岛", "无锡", "宁波", "佛山", "东莞", "郑州", "济南",
            "大连", "福州", "厦门", "哈尔滨", "长春", "沈阳", "石家庄", "太原", "合肥", "南昌",
            "昆明", "贵阳", "南宁", "海口", "兰州", "西宁", "银川", "乌鲁木齐", "拉萨", "呼和浩特"
        ]
        
        location_lower = location.lower()
        
        # 首先检查中文城市名称
        for city in chinese_cities:
            if city in location:
                return city
        
        # 然后检查英文城市名称
        for english_name, chinese_name in city_mapping.items():
            if english_name in location_lower:
                return chinese_name
        
        return None

    def _direct_create_file_from_extracted_code(self, user_input):
        """直接使用提取的代码创建文件（AI API超时时的后备方案）"""
        try:
            print("🔧 使用直接代码创建后备方案")
            
            # 构建上下文信息
            context_info = ""
            if self.session_conversations:
                # 获取最近的对话作为上下文
                recent_contexts = []
                for conv in reversed(self.session_conversations[-3:]):  # 获取最近3条对话
                    recent_contexts.append(f"【{conv['timestamp']}】{conv['full_text']}")
                context_info = "\n".join(recent_contexts)
            
            # 尝试从上下文中提取代码内容
            extracted_code = self._extract_code_from_context(context_info)
            if not extracted_code:
                print("⚠️ 未找到可提取的代码内容")
                return None
            
            print(f"🔍 直接使用提取的代码: {extracted_code[:100]}...")
            
            # 从用户输入中提取路径信息
            import re
            
            # 尝试提取完整路径（如"路径为D:/计算器.py"）
            path_match = re.search(r'路径为\s*([^，。\s]+)', user_input)
            if path_match:
                full_path = path_match.group(1)
                # 分离路径和文件名
                if '/' in full_path or '\\' in full_path:
                    path_parts = full_path.replace('\\', '/').split('/')
                    if len(path_parts) > 1:
                        location = '/'.join(path_parts[:-1]) + '/'
                        filename = path_parts[-1]
                        if not filename.endswith(('.py', '.cob', '.cbl', '.cpp', '.txt')):
                            filename += '.py'  # 默认添加.py扩展名
                else:
                    location = "D:/"
                    filename = full_path
                    if not filename.endswith(('.py', '.cob', '.cbl', '.cpp', '.txt')):
                        filename += '.py'
            else:
                # 如果没有找到完整路径，使用原有的逻辑
                if "d盘" in user_input.lower() or "d:" in user_input.lower():
                    location = "D:/"
                elif "c盘" in user_input.lower() or "c:" in user_input.lower():
                    location = "C:/"
                elif "e盘" in user_input.lower() or "e:" in user_input.lower():
                    location = "E:/"
                elif "f盘" in user_input.lower() or "f:" in user_input.lower():
                    location = "F:/"
                else:
                    location = "D:/"
                
                # 根据代码内容推断文件名
                if "python" in context_info.lower() or "def " in extracted_code:
                    filename = "calculator.py"
                elif "cobol" in context_info.lower() or "IDENTIFICATION DIVISION" in extracted_code:
                    filename = "program.cob"
                elif "c++" in context_info.lower() or "#include" in extracted_code:
                    filename = "program.cpp"
                else:
                    filename = "program.py"
            
            # 确保文件名安全
            filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
            
            # 构建完整的文件内容
            if "IDENTIFICATION DIVISION" in extracted_code or "PROGRAM-ID" in extracted_code:
                # COBOL代码格式特殊处理
                if "IDENTIFICATION DIVISION" not in extracted_code:
                    file_content = f"""      IDENTIFICATION DIVISION.
      PROGRAM-ID. CALCULATOR.
      PROCEDURE DIVISION.
{extracted_code}
      STOP RUN.
"""
                else:
                    # 如果代码已经包含完整的COBOL结构，直接使用
                    file_content = extracted_code
            else:
                # 其他编程语言
                file_content = f"""# -*- coding: utf-8 -*-
"""
                file_content += extracted_code
            
            # 调用MCP工具创建文件
            file_path = f"{location.rstrip('/')}/{filename}"
            result = self.mcp_server.call_tool("write_file", 
                                             file_path=file_path, 
                                             content=file_content)
            
            return f"（指尖轻敲控制台）{result}"
            
        except Exception as e:
            print(f"直接代码创建失败: {str(e)}")
            return None

    def _extract_java_class_name(self, code: str) -> str:
        """从Java代码中提取主类名"""
        try:
            import re
            # 查找 public class XXX 的模式
            class_pattern = r'public\s+class\s+(\w+)'
            match = re.search(class_pattern, code)
            if match:
                class_name = match.group(1)
                print(f"✅ 提取到Java类名: {class_name}")
                return class_name
            
            # 如果没有public class，查找普通class
            class_pattern2 = r'class\s+(\w+)'
            match2 = re.search(class_pattern2, code)
            if match2:
                class_name = match2.group(1)
                print(f"✅ 提取到Java类名: {class_name}")
                return class_name
            
            print("⚠️ 未找到Java类名")
            return None
        except Exception as e:
            print(f"⚠️ 提取Java类名失败: {e}")
            return None
    
    def _extract_code_from_context(self, context_info):
        """从上下文中提取代码内容 - 严格过滤所有非代码内容"""
        try:
            import re
            
            # 🔥 优先提取```代码块```内的内容
            code_block_pattern = r'```(?:java|python|py|cpp|c\+\+|c|javascript|js|html|css|sql|bash|shell|cobol)?\s*\n(.*?)\n```'
            matches = re.findall(code_block_pattern, context_info, re.DOTALL)
            
            if matches:
                for extracted_code in matches:
                    extracted_code = extracted_code.strip()
                    
                    # 🔥 严格过滤：移除所有说明文字和标记
                    lines = extracted_code.split('\n')
                    filtered_lines = []
                    skip_next = False
                    
                    for i, line in enumerate(lines):
                        stripped = line.strip()
                        
                        # 跳过对话标记
                        if any(marker in line for marker in ['指挥官:', '露尼西亚:', '【', '】', '###', '```']):
                            continue
                        
                        # 跳过中文说明行（代码中不应该有完整的中文句子）
                        if len(stripped) > 20 and all(ord(c) > 127 or c in '，。！？、：；' for c in stripped if not c.isspace()):
                            continue
                        
                        # 跳过markdown标题
                        if stripped.startswith('#'):
                            continue
                        
                        # 跳过空行（稍后处理）
                        filtered_lines.append(line)
                    
                    extracted_code = '\n'.join(filtered_lines).strip()
                    
                    # 验证代码是否以合法关键词开头
                    if extracted_code:
                        first_line = extracted_code.split('\n')[0].strip()
                        # 跳过空行找到第一个非空行
                        for line in extracted_code.split('\n'):
                            if line.strip():
                                first_line = line.strip()
                                break
                        
                        valid_starts = ['import', 'package', 'public', 'class', 'private', 
                                       'protected', 'def', 'from', '#include', 'using', '//', '/*',
                                       'interface', 'abstract', 'final', 'static', 'void', 'int',
                                       'String', 'boolean', 'double', 'float', 'char', 'long']
                        
                        if any(first_line.startswith(start) for start in valid_starts):
                            print(f"✅ 成功提取纯代码（首行验证通过）: {first_line[:50]}...")
                            return extracted_code
                        else:
                            print(f"⚠️ 代码首行不合法: '{first_line[:50]}'，继续查找...")
                            continue
                    
                    # 如果没有通过首行验证但有内容，返回
                    if extracted_code and 'class' in extracted_code:
                        print(f"⚠️ 返回未验证的代码块: {extracted_code[:50]}...")
                        return extracted_code
            
            # 如果没有找到代码块，尝试查找COBOL特定的内容
            if "IDENTIFICATION DIVISION" in context_info or "PROGRAM-ID" in context_info:
                # 尝试提取COBOL代码段
                cobol_patterns = [
                    r'(IDENTIFICATION DIVISION\..*?STOP RUN\.)',
                    r'(PROGRAM-ID\..*?STOP RUN\.)',
                    r'(IDENTIFICATION DIVISION\..*?PROCEDURE DIVISION\..*?STOP RUN\.)'
                ]
                
                for pattern in cobol_patterns:
                    matches = re.findall(pattern, context_info, re.DOTALL)
                    if matches:
                        extracted_code = matches[0].strip()
                        print(f"🔍 成功提取COBOL代码: {extracted_code[:50]}...")
                        return extracted_code
            
            print("⚠️ 未找到任何代码内容")
            return None
            
        except Exception as e:
            print(f"提取代码失败: {str(e)}")
            return None

    def _extract_code_from_recent_conversations(self):
        """从最近的对话中提取代码内容"""
        if not self.session_conversations:
            return None
        
        # 从最近的对话中查找代码内容
        for conv in reversed(self.session_conversations[-5:]):  # 检查最近5条对话
            ai_response = conv.get("ai_response", "")
            if "```" in ai_response:
                # 提取代码内容
                code_content = self._extract_code_from_context(ai_response)
                if code_content:
                    return code_content
        
        return None

    def _extract_search_query(self, user_input):
        """智能提取搜索关键词"""
        # 定义需要移除的词汇
        remove_words = [
            "帮我", "请帮我", "麻烦帮我", "能否帮我", "可以帮我",
            "搜索", "查找", "搜素", "搜", "查", "找", "查询", "查找", "搜素",
            "搜索一下", "查找一下", "搜素一下", "搜一下", "查一下", "找一下", "查询一下",
            "一下", "帮我搜索", "帮我查找", "帮我搜素", "帮我搜", "帮我查", "帮我找", "帮我查询", "帮我查找",
            "百度", "google", "谷歌", "bing", "必应", "用百度", "用谷歌", "用必应"
        ]
        
        # 移除所有不需要的词汇
        query = user_input
        for word in remove_words:
            query = query.replace(word, "")
        
        # 清理多余的空格和标点
        import re
        query = re.sub(r'\s+', ' ', query.strip())
        query = query.strip('，。！？、；：')
        
        return query

    def _get_current_time(self):
        """获取当前时间"""
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    

    # _extract_automation_action 和 _ai_judge_automation_need 已移至 WebpageAgent

    def _open_website_wrapper(self, site_name, website_map=None, user_input=""):
        """
        网页打开与自动化操作的包装函数，处理网站名称映射
        
        优先级顺序：
        1. AI智能识别并生成URL（从LLM知识库）
        2. 网站管理配置（website_map）
        3. 返回未找到错误
        
        智能判断使用系统浏览器还是Playwright：
        - 简单打开 → 系统浏览器（快速、稳定）
        - 打开+操作 → Playwright有头模式（支持自动化）
        """
        try:
            print(f"🔍 _open_website_wrapper 收到参数 - site_name: '{site_name}', user_input: '{user_input}'")
            
            if website_map is None:
                website_map = self.website_map
            
            # 清理网站名称
            site_name_original = site_name.strip()
            site_name = site_name_original.lower()
            
            # 获取用户配置的默认浏览器
            default_browser = self.config.get("default_browser", "")
            print(f"🔧 使用配置的浏览器: {default_browser}")
            
            # 如果包含http或www，直接作为URL处理
            if site_name.startswith(("http://", "https://", "www.")):
                if not site_name.startswith(("http://", "https://")):
                    site_name = "https://" + site_name
                print(f"🔍 直接作为URL处理: {site_name}")
                
                # 🤖 使用统一ReAct推理Agent（自动判断简单/复杂，自动推理）
                print(f"🤖 调用统一WebpageAgent...")
                
                # 获取Playwright配置
                pw_mode = self.config.get("playwright_mode", "launch")
                pw_slow_mo = self.config.get("playwright_slow_mo", 0)
                pw_cdp_url = self.config.get("playwright_cdp_url", "http://localhost:9222")
                pw_user_data_dir = self.config.get("playwright_user_data_dir", "")
                
                # 如果是connect模式，检查并启动调试浏览器
                if pw_mode == "connect":
                    from cdp_helper import ensure_cdp_connection
                    cdp_result = ensure_cdp_connection(
                        cdp_url=pw_cdp_url,
                        browser_type=default_browser,
                        user_data_dir=pw_user_data_dir
                    )
                    if not cdp_result["success"]:
                        return f"无法建立调试连接：{cdp_result['message']}"
                    if cdp_result.get("auto_started"):
                        print(f"✅ 已自动启动调试浏览器")
                
                # 调用统一Agent（内部自动分析+推理+执行）
                result = execute_webpage_task_sync(
                    config=self.config,
                    user_input=user_input,  # 传递完整用户输入
                    url=site_name,
                    browser_type=default_browser,
                    mode=pw_mode,
                    slow_mo=pw_slow_mo,
                    cdp_url=pw_cdp_url,
                    user_data_dir=pw_user_data_dir
                )
                
                # 处理返回消息
                if result.get("success"):
                    # 🔥 提取完整的页面内容（从history中获取）
                    page_content = ""
                    history = result.get("history", [])
                    
                    # 从历史记录中提取页面内容（优先查找get_text/get_page_info的结果）
                    for record in reversed(history):  # 倒序查找最新内容
                        observation = record.get("observation", "")
                        if "元素文本" in observation or "页面信息" in observation:
                            # 提取文本内容（限制长度避免过长）
                            if len(observation) > 100:  # 只提取有意义的长文本
                                page_content = observation[:3000]  # 最多3000字符
                                break
                    
                    # 构建返回消息
                    basic_message = result.get('message')
                    if page_content:
                        return f"（指尖轻敲控制台）{basic_message}\n\n页面内容：\n{page_content}"
                    else:
                        return f"（指尖轻敲控制台）{basic_message}"
                else:
                    return f"网页操作失败：{result.get('error', '未知错误')}"
            
            # 步骤1：优先使用AI生成URL（从LLM知识库）
            print(f"🤖 步骤1: 尝试使用AI从知识库生成URL: {site_name_original}")
            ai_generated_url = self._ai_generate_website_url(site_name_original)
            
            if ai_generated_url:
                print(f"✅ AI成功生成URL: {ai_generated_url}")
                
                # 🤖 使用统一ReAct推理Agent
                print(f"🤖 调用统一WebpageAgent...")
                
                # 获取Playwright配置
                pw_mode = self.config.get("playwright_mode", "launch")
                pw_slow_mo = self.config.get("playwright_slow_mo", 0)
                pw_cdp_url = self.config.get("playwright_cdp_url", "http://localhost:9222")
                pw_user_data_dir = self.config.get("playwright_user_data_dir", "")
                
                # 如果是connect模式，检查并启动调试浏览器
                if pw_mode == "connect":
                    from cdp_helper import ensure_cdp_connection
                    cdp_result = ensure_cdp_connection(
                        cdp_url=pw_cdp_url,
                        browser_type=default_browser,
                        user_data_dir=pw_user_data_dir
                    )
                    if not cdp_result["success"]:
                        return f"无法建立调试连接：{cdp_result['message']}"
                    if cdp_result.get("auto_started"):
                        print(f"✅ 已自动启动调试浏览器")
                
                # 调用统一Agent（内部自动分析+推理+执行）
                result = execute_webpage_task_sync(
                    config=self.config,
                    user_input=user_input,
                    url=ai_generated_url,
                    browser_type=default_browser,
                    mode=pw_mode,
                    slow_mo=pw_slow_mo,
                    cdp_url=pw_cdp_url,
                    user_data_dir=pw_user_data_dir
                )
                
                # 处理返回消息
                if result.get("success"):
                    return f"（指尖轻敲控制台）{result.get('message')}"
                else:
                    return f"网页操作失败：{result.get('error', '未知错误')}"
            else:
                print(f"⚠️ AI未能从知识库生成URL，尝试下一步")
            
            # 步骤2：从网站管理配置中查找
            print(f"🔧 步骤2: 在网站管理配置中查找: {site_name_original}")
            
            # 处理常见的网站名称变体（用于匹配website_map）
            site_variants = {
                "哔哩哔哩": ["bilibili", "b站", "哔哩哔哩", "bilbil", "bilibili.com"],
                "百度": ["baidu", "百度", "baidu.com"],
                "谷歌": ["google", "谷歌", "google.com"],
                "知乎": ["zhihu", "知乎", "zhihu.com"],
                "github": ["github", "github.com"],
                "youtube": ["youtube", "youtube.com", "油管"],
                "高德开放平台": ["高德", "高德开放平台", "amap", "高德地图"]
            }
            
            # 查找匹配的网站
            matched_site = None
            for site_key, variants in site_variants.items():
                if any(variant in site_name for variant in variants):
                    matched_site = site_key
                    break
            
            # 如果找到匹配的网站，使用映射的URL
            if matched_site and matched_site in website_map:
                url = website_map[matched_site]
                print(f"✅ 在网站管理中找到映射: {site_name} -> {url}")
                
                # 🤖 使用统一ReAct推理Agent
                print(f"🤖 调用统一WebpageAgent...")
                
                # 获取Playwright配置
                pw_mode = self.config.get("playwright_mode", "launch")
                pw_slow_mo = self.config.get("playwright_slow_mo", 0)
                pw_cdp_url = self.config.get("playwright_cdp_url", "http://localhost:9222")
                pw_user_data_dir = self.config.get("playwright_user_data_dir", "")
                
                # 如果是connect模式，检查并启动调试浏览器
                if pw_mode == "connect":
                    from cdp_helper import ensure_cdp_connection
                    cdp_result = ensure_cdp_connection(
                        cdp_url=pw_cdp_url,
                        browser_type=default_browser,
                        user_data_dir=pw_user_data_dir
                    )
                    if not cdp_result["success"]:
                        return f"无法建立调试连接：{cdp_result['message']}"
                    if cdp_result.get("auto_started"):
                        print(f"✅ 已自动启动调试浏览器")
                
                # 调用统一Agent
                result = execute_webpage_task_sync(
                    config=self.config,
                    user_input=user_input,
                    url=url,
                    browser_type=default_browser,
                    mode=pw_mode,
                    slow_mo=pw_slow_mo,
                    cdp_url=pw_cdp_url,
                    user_data_dir=pw_user_data_dir
                )
                
                # 处理返回消息
                if result.get("success"):
                    return f"（指尖轻敲控制台）{result.get('message')}"
                else:
                    return f"网页操作失败：{result.get('error', '未知错误')}"
            
            # 如果网站名称直接匹配映射表（不区分大小写）
            for map_key, map_url in website_map.items():
                if site_name == map_key.lower() or site_name_original == map_key:
                    print(f"✅ 在网站管理中直接匹配: {site_name_original} -> {map_url}")
                    
                    # 🤖 使用统一ReAct推理Agent
                    print(f"🤖 调用统一WebpageAgent...")
                    
                    # 获取Playwright配置
                    pw_mode = self.config.get("playwright_mode", "launch")
                    pw_slow_mo = self.config.get("playwright_slow_mo", 0)
                    pw_cdp_url = self.config.get("playwright_cdp_url", "http://localhost:9222")
                    pw_user_data_dir = self.config.get("playwright_user_data_dir", "")
                    
                    # 如果是connect模式，检查并启动调试浏览器
                    if pw_mode == "connect":
                        from cdp_helper import ensure_cdp_connection
                        cdp_result = ensure_cdp_connection(
                            cdp_url=pw_cdp_url,
                            browser_type=default_browser,
                            user_data_dir=pw_user_data_dir
                        )
                        if not cdp_result["success"]:
                            return f"无法建立调试连接：{cdp_result['message']}"
                        if cdp_result.get("auto_started"):
                            print(f"✅ 已自动启动调试浏览器")
                    
                    # 调用统一Agent
                    result = execute_webpage_task_sync(
                        config=self.config,
                        user_input=user_input,
                        url=map_url,
                        browser_type=default_browser,
                        mode=pw_mode,
                        slow_mo=pw_slow_mo,
                        cdp_url=pw_cdp_url,
                        user_data_dir=pw_user_data_dir
                    )
                    
                    # 处理返回消息
                    if result.get("success"):
                        return f"（指尖轻敲控制台）{result.get('message')}"
                    else:
                        return f"网页操作失败：{result.get('error', '未知错误')}"
            
            # 步骤3：都没找到，返回错误信息
            print(f"❌ 步骤3: 在AI知识库和网站管理中都未找到网站")
            available_sites = list(website_map.keys()) if website_map else []
            
            error_msg = f"（微微皱眉）抱歉指挥官，我无法识别网站 '{site_name_original}'。\n\n"
            
            if available_sites:
                error_msg += f"💡 网站管理中的可用网站：\n"
                for idx, site in enumerate(available_sites, 1):
                    error_msg += f"   {idx}. {site}\n"
                error_msg += f"\n"
            
            error_msg += f"📝 您可以：\n"
            error_msg += f"   1. 在设置中的【网站管理】添加此网站\n"
            error_msg += f"   2. 直接提供完整网址（如：https://www.example.com）\n"
            error_msg += f"   3. 尝试使用更常见的网站名称"
            
            return error_msg
            
        except Exception as e:
            return f"打开网页时发生错误：{str(e)}"

    def _is_remember_moment_command(self, user_input):
        """检测是否是'记住这个时刻'指令"""
        remember_keywords = [
            "请记住这个时刻",
            "记住这个时刻",
            "记住这一刻",
            "请记住这一刻",
            "记住这个瞬间",
            "请记住这个瞬间",
            "记住这个时间",
            "请记住这个时间",
            "记住这个对话",
            "请记住这个对话",
            "记住这次谈话",
            "请记住这次谈话",
            "记住这次交流",
            "请记住这次交流",
            "保存这个时刻",
            "请保存这个时刻",
            "保存这次对话",
            "请保存这次对话",
            "记录这个时刻",
            "请记录这个时刻",
            "记录这次对话",
            "请记录这次对话"
        ]
        
        user_input_lower = user_input.lower().strip()
        return any(keyword.lower() in user_input_lower for keyword in remember_keywords)

    def _handle_remember_moment(self, user_input):
        """处理'记住这个时刻'指令"""
        try:
            # 检查是否有未保存的会话对话
            unsaved_conversations = []
            
            # 获取当前记忆系统中的对话数量
            current_memory_count = len(self.memory_lake.current_conversation)
            
            # 获取本次会话的对话数量
            session_count = len(self.session_conversations)
            
            # 如果本次会话有对话但记忆系统中没有，说明有未保存的对话
            if session_count > 0 and current_memory_count == 0:
                # 将本次会话的所有对话添加到记忆系统
                for conv in self.session_conversations:
                    self.memory_lake.add_conversation(conv["user_input"], conv["ai_response"])
                    unsaved_conversations.append(conv["full_text"])
            
            # 强制保存到识底深湖
            if self.memory_lake.current_conversation:
                topic = self.memory_lake.summarize_and_save_topic(force_save=True)
                
                if topic:
                    # 标记为重点记忆（最新保存的记忆是最后一个）
                    topics = self.memory_lake.memory_index.get("topics", [])
                    if topics:
                        latest_index = len(topics) - 1
                        self.memory_lake.mark_as_important(latest_index)
                    
                    # 构建响应消息
                    response = f"（轻轻点头）好的指挥官，我已经将这个重要时刻记录到识底深湖中，并标记为重点记忆。"
                    
                    # 根据设置决定是否显示详细信息
                    show_details = self.config.get("show_remember_details", True)
                    
                    if show_details:
                        if unsaved_conversations:
                            response += f"\n\n已保存的对话内容：\n"
                            for i, conv in enumerate(unsaved_conversations, 1):
                                response += f"{i}. {conv}\n"
                        
                        response += f"\n主题：{topic}\n时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    
                    # 清空本次会话记录，因为已经保存到记忆系统
                    self.session_conversations = []
                    
                    return response
                else:
                    return "（微微皱眉）抱歉指挥官，保存到识底深湖时遇到了一些问题。请稍后再试。"
            else:
                return "（轻轻摇头）指挥官，目前没有需要保存的对话内容。请先进行一些对话，然后再说'记住这个时刻'。"
                
        except Exception as e:
            print(f"处理'记住这个时刻'指令失败: {str(e)}")
            return "（表情略显困扰）抱歉指挥官，保存过程中遇到了一些技术问题。请稍后再试。"

    def _is_file_analysis_request(self, user_input):
        """检测是否是文件分析请求"""
        file_keywords = [
            "分析文件", "文件分析", "上传文件", "分析图片", "分析文档",
            "查看文件", "文件信息", "图片信息", "文档信息", "智能分析"
        ]
        user_input_lower = user_input.lower().strip()
        return any(keyword in user_input_lower for keyword in file_keywords)

    def _handle_file_analysis(self, user_input):
        """处理文件分析请求"""
        try:
            # 从用户输入中提取文件路径
            import re
            file_path_pattern = r'[A-Za-z]:[\\/][^\\/:\*\?"<>\|]*\.(pdf|csv|xlsx|xls)'
            matches = re.findall(file_path_pattern, user_input)
            
            if matches:
                file_path = matches[0]
                print(f"🔍 检测到文件路径: {file_path}")
                
                # 使用文件分析工具分析文件
                result = self.file_analyzer.analyze_file(file_path)
                
                if result.success:
                    # 生成AI分析报告
                    analysis_report = self.file_analyzer.generate_ai_analysis(result, user_input)
                    return analysis_report
                else:
                    return f"❌ 文件分析失败: {result.error}"
            else:
                return "（困惑地看着屏幕）指挥官，我没有在您的消息中检测到文件路径。请提供完整的文件路径，例如：C:\\Users\\Documents\\example.pdf"
        except Exception as e:
            return f"❌ 文件分析出错: {str(e)}"

    def _check_file_context_query(self, user_input):
        """检查用户问题是否与最近分析的文件相关，并让AI判断"""
        try:
            file_info = self.recent_file_analysis
            
            print(f"📂 检测到最近分析的文件上下文: {file_info['file_name']}")
            print(f"🤔 让AI判断问题是否与文件相关...")
            
            # 第一步：让AI判断问题是否与文件相关
            judge_prompt = f"""你刚刚分析了一个文件：{file_info['file_name']} ({file_info['file_type']})

现在用户提出了一个问题："{user_input}"

请判断这个问题是否与刚才分析的文件相关。

判断标准：
1. 如果问题明确提到"文件"、"代码"、"刚才"、"这个"等指代刚分析的文件
2. 如果问题询问代码结构、数量统计（如循环数、函数数）
3. 如果问题是对文件内容的追问或延伸讨论
4. 如果问题很简短且像是对上一次分析的追问（如"里边用了几个循环"）

请只回答 "YES" 或 "NO"，不要有其他内容。"""
            
            # 使用OpenAI API直接调用
            import openai
            api_key = self.config.get("deepseek_key", "")
            if not api_key:
                print("⚠️ 无API密钥，无法判断文件相关性")
                return None
            
            client = openai.OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com/v1"
            )
            
            response = client.chat.completions.create(
                model="deepseek-v4-flash",
                messages=[
                    {"role": "system", "content": "你是文件上下文判断助手。只回答YES或NO。"},
                    {"role": "user", "content": judge_prompt}
                ],
                max_tokens=10,
                temperature=0.1,
                timeout=10,
                extra_body={"thinking": {"type": "disabled"}},
            )
            
            judge_response = (response.choices[0].message.content or "").strip()
            
            if judge_response and "YES" in judge_response.upper():
                print(f"✅ AI判断：问题与文件 {file_info['file_name']} 相关")
                
                # 构建包含文件内容的提示词
                prompt = f"""你刚刚分析了一个文件，现在用户对这个文件提出了问题。 

**文件信息：**
- 文件名：{file_info['file_name']}
- 文件类型：{file_info['file_type']}
"""
                
                # 如果是代码文件，优先展示精确统计信息
                if 'CODE_' in file_info['file_type']:
                    metadata = file_info.get('metadata', {})
                    structure = metadata.get('structure', {})
                    metrics = metadata.get('metrics', {})
                    
                    prompt += f"\n**📊 精确代码统计（请优先使用这些数据回答问题）：**\n"
                    
                    if metrics:
                        prompt += f"\n控制结构统计：\n"
                        if_count = metrics.get('if_count', metrics.get('if_statements', 0))
                        for_count = metrics.get('for_count', metrics.get('for_loops', 0))
                        while_count = metrics.get('while_count', metrics.get('while_loops', 0))
                        try_count = metrics.get('try_blocks', 0)
                        
                        prompt += f"- if语句：{if_count} 个\n"
                        prompt += f"- for循环：{for_count} 个\n"
                        prompt += f"- while循环：{while_count} 个\n"
                        if try_count > 0:
                            prompt += f"- try块：{try_count} 个\n"
                        
                        total_loops = for_count + while_count
                        prompt += f"- **循环总数：{total_loops} 个** (for: {for_count}, while: {while_count})\n"
                        
                        prompt += f"\n代码规模：\n"
                        prompt += f"- 总行数：{metrics.get('total_lines', 0)} 行\n"
                        prompt += f"- 有效代码：{metrics.get('code_lines', 0)} 行\n"
                        prompt += f"- 注释：{metrics.get('comment_lines', 0)} 行\n"
                        prompt += f"- 空行：{metrics.get('blank_lines', 0)} 行\n"
                    
                    if structure:
                        prompt += f"\n代码结构：\n"
                        if structure.get('classes'):
                            prompt += f"- 类定义：{len(structure['classes'])} 个\n"
                            # 列出类名
                            class_names = [cls.get('name', 'Unknown') for cls in structure['classes']]
                            prompt += f"  类名：{', '.join(class_names[:10])}\n"
                        
                        if structure.get('functions'):
                            prompt += f"- 函数/方法：{len(structure['functions'])} 个\n"
                        
                        if structure.get('imports'):
                            prompt += f"- 导入模块：{len(structure['imports'])} 个\n"
                
                prompt += f"\n**文件摘要：**\n{file_info['summary']}\n"
                prompt += f"\n**文件分析：**\n{file_info['analysis']}\n"
                
                # 只在必要时添加部分内容（避免过长）
                if len(file_info.get('content', '')) < 3000:
                    prompt += f"\n**文件内容（部分）：**\n{file_info['content'][:3000]}\n"
                
                prompt += f"\n**用户问题：**\n{user_input}\n"
                prompt += f"\n⚠️ 重要：如果用户问及数量（如循环数、函数数等），请直接使用上面的精确统计数据回答，不要猜测！\n"
                
                # 调用AI生成回答（本路径固定 DeepSeek 客户端）
                from llm_spec import message_text_content

                response_obj = client.chat.completions.create(
                    model="deepseek-v4-flash",
                    messages=[
                        {"role": "system", "content": "你是文件分析助手，擅长根据文件内容回答用户问题。"},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=1000,
                    temperature=0.7,
                    timeout=30,
                    extra_body={"thinking": {"type": "disabled"}},
                )
                response = message_text_content(response_obj.choices[0].message)
                
                if response:
                    return response
            else:
                print(f"❌ AI判断：问题与文件无关，使用常规处理流程")
            
            return None
            
        except Exception as e:
            print(f"❌ 文件上下文查询失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def process_file_upload(self, file_path, stream_callback=None):
        """处理文件上传"""
        try:
            print(f"🔍 开始分析文件: {file_path}")
            
            # 使用文件分析工具分析文件
            result = self.file_analyzer.analyze_file(file_path)
            
            if result.success:
                print(f"✅ 文件分析完成: {result.file_name}")
                
                # 🔥 保存到上下文记忆（用于后续问答）
                self.recent_file_analysis = {
                    "file_name": result.file_name,
                    "file_type": result.file_type,
                    "content": result.content,
                    "metadata": result.metadata,
                    "summary": result.summary,
                    "analysis": result.analysis,
                    "result": result  # 保存完整结果对象
                }
                print(f"💾 已保存文件分析上下文: {result.file_name}")
                
                # 生成AI分析报告
                analysis_report = self.file_analyzer.generate_ai_analysis(
                    result, stream_callback=stream_callback
                )
                return analysis_report
            else:
                error_msg = f"❌ 文件分析失败: {result.error}"
                print(error_msg)
                return error_msg
            
        except Exception as e:
            print(f"❌ 文件分析失败: {str(e)}")
            return f"文件分析失败: {str(e)}"
    
    def _format_analysis_result(self, result):
        """格式化分析结果，使其更美观易读"""
        try:
            import json
            import re
            
            # 尝试提取JSON部分
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                analysis_data = json.loads(json_str)
                
                # 格式化基本信息
                basic_info = analysis_data.get("basic_info", {})
                content_analysis = analysis_data.get("content_analysis", {})
                
                formatted_result = "🔍 智能文件分析结果\n"
                formatted_result += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                formatted_result += f"📁 文件名：{basic_info.get('file_name', '未知')}\n"
                formatted_result += f"📏 文件大小：{basic_info.get('file_size_human', '未知')}\n"
                formatted_result += f"📅 创建时间：{basic_info.get('created_time', '未知')}\n"
                formatted_result += f"🔄 修改时间：{basic_info.get('modified_time', '未知')}\n"
                
                # 根据文件类型添加特定信息
                if content_analysis.get("type") == "image":
                    formatted_result += f"🖼️ 图片格式：{content_analysis.get('format', '未知')}\n"
                    formatted_result += f"📐 图片尺寸：{content_analysis.get('width', '未知')} × {content_analysis.get('height', '未知')}\n"
                    formatted_result += f"🎨 颜色深度：{content_analysis.get('color_depth', '未知')}\n"
                    
                    # 场景描述
                    scene_desc = content_analysis.get("scene_description", {})
                    if scene_desc:
                        formatted_result += f"🌅 场景类型：{scene_desc.get('scene_type', '未知')}\n"
                        formatted_result += f"💡 亮度水平：{scene_desc.get('brightness_level', '未知')}\n"
                    
                    # 物体检测
                    object_detect = content_analysis.get("object_detection", {})
                    if object_detect:
                        formatted_result += f"🔍 复杂度：{object_detect.get('complexity', '未知')}\n"
                        formatted_result += f"🎨 颜色数量：{object_detect.get('unique_colors', '未知')}\n"
                    
                    # 文字提取分析
                    text_extract = content_analysis.get("text_extraction", {})
                    if text_extract:
                        formatted_result += f"📝 文字可能性：{text_extract.get('text_likelihood', '未知')}\n"
                        formatted_result += f"📊 边缘密度：{text_extract.get('edge_density', '未知')}\n"
                    
                    # OCR文字识别结果
                    ocr_text = content_analysis.get("ocr_text", {})
                    if ocr_text and ocr_text.get("status") == "success":
                        extracted_text = ocr_text.get("extracted_text", "")
                        if extracted_text.strip():
                            formatted_result += f"🔤 识别文字：\n"
                            # 限制显示长度，避免过长
                            display_text = extracted_text.strip()
                            if len(display_text) > 200:
                                display_text = display_text[:200] + "..."
                            formatted_result += f"   {display_text}\n"
                            formatted_result += f"📏 文字长度：{ocr_text.get('text_length', '未知')}字符\n"
                            formatted_result += f"📖 词数：{ocr_text.get('word_count', '未知')}\n"
                    elif ocr_text and ocr_text.get("status") == "no_text":
                        formatted_result += f"🔤 文字识别：未识别到文字内容\n"
                    elif ocr_text and ocr_text.get("status") == "error":
                        formatted_result += f"🔤 文字识别：{ocr_text.get('message', '识别失败')}\n"
                    
                    # 颜色分析
                    color_analysis = content_analysis.get("color_analysis", {})
                    if color_analysis:
                        dominant_colors = color_analysis.get("dominant_colors", [])
                        if dominant_colors:
                            formatted_result += f"🌈 主要颜色：{dominant_colors[0].get('color', '未知')} ({dominant_colors[0].get('percentage', '未知')}%)\n"
                    
                    # 构图分析
                    composition = content_analysis.get("composition_analysis", {})
                    if composition:
                        formatted_result += f"📐 构图类型：{composition.get('composition_type', '未知')}\n"
                        formatted_result += f"📊 分辨率：{composition.get('resolution_quality', '未知')}\n"
                
                elif content_analysis.get("type") == "text":
                    formatted_result += f"📄 文件类型：文本文件\n"
                    formatted_result += f"📝 字符数：{content_analysis.get('character_count', '未知')}\n"
                    formatted_result += f"📖 行数：{content_analysis.get('line_count', '未知')}\n"
                    formatted_result += f"🔤 词数：{content_analysis.get('word_count', '未知')}\n"
                    formatted_result += f"🌍 语言：{content_analysis.get('language', '未知')}\n"
                
                formatted_result += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                
                return formatted_result
            else:
                # 如果没有找到JSON，返回原始结果
                return result
                
        except Exception as e:
            print(f"⚠️ 格式化分析结果失败: {str(e)}")
            # 如果格式化失败，返回原始结果
            return result

    def _generate_image_ai_analysis(self, file_path, analysis_result, stream_callback=None):
        """生成图片的AI分析"""
        try:
            print(f"🖼️ 开始生成图片AI分析: {file_path}")
            
            # 尝试解析分析结果
            import json
            try:
                analysis_data = json.loads(analysis_result)
                content_analysis = analysis_data.get("content_analysis", {})
                
                # 获取OCR识别的文字内容
                ocr_text = content_analysis.get("ocr_text", {})
                extracted_text = ""
                if ocr_text and ocr_text.get("status") == "success":
                    extracted_text = ocr_text.get("extracted_text", "").strip()
                
                # 构建AI分析提示
                prompt = f"""
                请分析这张图片，基于以下信息：
                
                图片信息：
                - 文件名：{analysis_data.get('basic_info', {}).get('file_name', '未知')}
                - 尺寸：{content_analysis.get('width', '未知')} x {content_analysis.get('height', '未知')}
                - 格式：{content_analysis.get('format', '未知')}
                
                内容分析：
                - 场景描述：{content_analysis.get('scene_description', {}).get('description', '未知')}
                - 物体检测：{content_analysis.get('object_detection', {}).get('description', '未知')}
                - 颜色分析：{content_analysis.get('color_analysis', {}).get('description', '未知')}
                - 构图分析：{content_analysis.get('composition_analysis', {}).get('description', '未知')}
                """
                
                # 如果有OCR识别的文字内容，添加到提示中
                if extracted_text:
                    prompt += f"""
                
                OCR识别的文字内容：
                {extracted_text}
                
                请基于以上信息，特别是OCR识别的文字内容，对这张图片进行全面的AI分析。包括：
                1. 图片的整体内容和主题
                2. 识别出的文字内容的含义和重要性
                3. 图片的风格、用途和可能的背景
                4. 文字与图片内容的关联性分析
                5. 专业见解和建议
                """
                else:
                    prompt += f"""
                
                文字识别：{content_analysis.get('text_extraction', {}).get('description', '未知')}
                
                请从AI的角度分析这张图片的内容、风格、可能的用途等，给出专业的见解。
                """
                
            except json.JSONDecodeError:
                # 如果不是JSON格式，使用原始结果
                print(f"⚠️ 分析结果不是JSON格式，使用原始结果")
                prompt = f"""
                请分析这张图片，基于以下技术分析结果：
                
                {analysis_result}
                
                请从AI的角度分析这张图片的内容、风格、可能的用途等，给出专业的见解。
                """
            
            # 调用AI生成分析，提供空的上下文信息
            context_info = {}
            response = self._generate_response_with_context(
                prompt, context_info, stream_callback=stream_callback
            )
            return response
            
        except Exception as e:
            print(f"❌ AI分析生成失败: {str(e)}")
            return f"AI分析生成失败: {str(e)}"

    def _generate_document_ai_analysis(self, file_path, analysis_result):
        """生成文档的AI分析"""
        try:
            # 解析分析结果
            import json
            analysis_data = json.loads(analysis_result)
            content_analysis = analysis_data.get("content_analysis", {})
            
            # 构建AI分析提示
            prompt = f"""
            请分析这个文档，基于以下信息：
            
            文档信息：
            - 文件名：{analysis_data.get('basic_info', {}).get('file_name', '未知')}
            - 文件类型：{content_analysis.get('type', '未知')}
            
            内容分析：
            - 文本统计：{content_analysis.get('description', '未知')}
            - 关键词：{', '.join(content_analysis.get('keywords', []))}
            - 内容预览：{content_analysis.get('content_preview', '未知')}
            
            请从AI的角度分析这个文档的主题、内容质量、可能的用途等，给出专业的见解。
            """
            
            # 调用AI生成分析，提供空的上下文信息
            context_info = {}
            response = self._generate_response_with_context(prompt, context_info)
            return response
            
        except Exception as e:
            return f"AI分析生成失败: {str(e)}"

    def _is_image_file(self, file_path):
        """判断是否为图片文件"""
        from pathlib import Path
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
        return Path(file_path).suffix.lower() in image_extensions

    def _is_document_file(self, file_path):
        """判断是否为文档文件"""
        from pathlib import Path
        document_extensions = {'.pdf', '.txt', '.doc', '.docx', '.csv', '.json', '.xml'}
        return Path(file_path).suffix.lower() in document_extensions

    
    def _filter_ocr_text(self, text):
        """过滤OCR识别的文字，去除明显错误的结果"""
        if not text:
            return ""
        
        import re
        
        # 去除单个字符或明显无意义的字符组合
        if len(text.strip()) < 2:
            return ""
        
        # 去除只包含数字和特殊字符的文本（除非是合理的数字）
        if re.match(r'^[\d\s\-\.\,]+$', text.strip()) and len(text.strip()) < 5:
            return ""
        
        # 去除重复字符过多的文本
        if len(set(text)) < len(text) * 0.3:  # 如果重复字符超过70%
            return ""
        
        # 去除明显无意义的字符组合
        meaningless_patterns = [
            r'^[^\w\s]+$',  # 只包含特殊字符
            r'^[a-zA-Z]{1,2}$',  # 单个或两个英文字母
            r'^[一-龯]{1,2}$',  # 单个或两个中文字符
        ]
        
        for pattern in meaningless_patterns:
            if re.match(pattern, text.strip()):
                return ""
        
        # 清理文本
        cleaned_text = text.strip()
        # 去除多余的空格
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
        
        return cleaned_text

    @_with_vision_tts_pause
    def process_image(self, file_path, user_question: str = "", stream_callback=None):
        """处理图片文件"""
        try:
            print(f"🖼️ 开始处理图片: {file_path}")
            
            # 检查文件是否存在
            if not os.path.exists(file_path):
                return "错误：文件不存在"
            
            # 检查是否为图片文件
            if not self._is_image_file(file_path):
                return "错误：不是有效的图片文件"
            
            from llm_vision_router import analyze_image_file, vision_is_configured
            from llm_spec import vision_model_label

            if vision_is_configured(self.config):
                image_model = vision_model_label(self.config, "vision_image_model")
                print(f"🤖 使用视觉模型分析图片: {image_model}")
                try:
                    result = analyze_image_file(
                        self.config,
                        file_path,
                        user_question,
                        stream_callback=stream_callback,
                        system_prompt=self.get_main_system_prompt(),
                    )
                    if result and not result.startswith("错误"):
                        self.recent_image_analysis = {
                            "image_path": file_path,
                            "image_name": os.path.basename(file_path),
                            "analysis": result,
                        }
                        print(f"💾 已保存图片分析上下文: {os.path.basename(file_path)}")
                        return result
                except Exception as e:
                    print(f"⚠️ 视觉模型分析失败: {e}，回退到OCR分析")
            
            # 使用智能文件分析工具（OCR）
            analysis_result = self._analyze_file_with_tools(file_path)
            
            if not analysis_result:
                return "错误：文件分析失败"
            
            # 生成AI分析
            ai_analysis = self._generate_image_ai_analysis(
                file_path, analysis_result, stream_callback=stream_callback
            )
            
            # 保存图片分析上下文（OCR方式）
            self.recent_image_analysis = {
                "image_path": file_path,
                "image_name": os.path.basename(file_path),
                "analysis": ai_analysis,
                "ocr_result": analysis_result
            }
            print(f"💾 已保存图片分析上下文: {os.path.basename(file_path)}")
            
            return ai_analysis
            
        except Exception as e:
            print(f"❌ 图片处理失败: {str(e)}")
            return f"图片处理失败: {str(e)}"

    def _analyze_image_with_qwen3vl(self, file_path: str, user_question: str = "") -> str:
        """遗留：DashScope 直连接口分析图片（主路径见 llm_vision_router）。"""
        try:
            import openai
            import base64
            
            # 读取图片并转换为base64
            with open(file_path, 'rb') as image_file:
                image_data = image_file.read()
                image_base64 = base64.b64encode(image_data).decode('utf-8')
            
            # 构建提示词
            if user_question:
                prompt = f"请分析这张图片，并回答以下问题：{user_question}"
            else:
                prompt = "请详细分析这张图片的内容，包括图片中的文字、物体、场景、布局等所有可见信息。以通常精准冷静语气回答，但直接与用户聊天时要用略亲切的语气"
            
            from custom_models_store import get_vision_dashscope_api_key

            api_key = get_vision_dashscope_api_key(self.config)
            model_id = self.config.get("vision_dashscope_image_model", "qwen-vl-plus")
            client = openai.OpenAI(
                api_key=api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            
            response = client.chat.completions.create(
                model=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}"
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ],
                max_tokens=2000,
                temperature=0.7
            )
            
            result = response.choices[0].message.content.strip()
            return result
            
        except Exception as e:
            from llm_spec import vision_model_label

            model = vision_model_label(self.config, "vision_image_model")
            print(f"❌ [{model}] 图片分析失败: {e}")
            import traceback
            traceback.print_exc()
            raise e

    def _capture_screen(self):
        """截取当前屏幕，返回临时图片文件路径。失败返回 None。"""
        import tempfile
        try:
            try:
                from PIL import ImageGrab
                img = ImageGrab.grab()
            except Exception:
                try:
                    import mss
                    import mss.tools
                    with mss.mss() as sct:
                        monitor = sct.monitors[0]
                        screenshot = sct.grab(monitor)
                    from PIL import Image
                    img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                except Exception as e2:
                    print(f"⚠️ 截屏失败（PIL 与 mss 均不可用）: {e2}")
                    return None
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            img.save(tmp.name, "PNG")
            tmp.close()
            return tmp.name
        except Exception as e:
            print(f"❌ 截屏失败: {e}")
            return None

    def _analyze_screen_with_qwen3_omni(self, image_path: str, user_question: str) -> str:
        """遗留：DashScope 直连接口分析屏幕截图（主路径见 llm_vision_router）。"""
        try:
            import base64
            from custom_models_store import get_vision_dashscope_api_key

            api_key = get_vision_dashscope_api_key(self.config)
            if not api_key:
                return "错误：未配置 DashScope API 密钥，无法使用屏幕理解功能。"
            with open(image_path, "rb") as f:
                image_base64 = base64.b64encode(f.read()).decode("utf-8")
            if user_question:
                prompt = f"这是用户当前的电脑屏幕截图。请根据截图内容回答用户的问题：{user_question}"
            else:
                prompt = "这是用户当前的电脑屏幕截图。请详细描述屏幕上的内容，包括窗口、文字、图标、布局等所有可见信息。"
            client = openai.OpenAI(
                api_key=api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            screen_model = self.config.get(
                "vision_dashscope_screen_model", "qwen3-omni-flash"
            )
            response = client.chat.completions.create(
                model=screen_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                            {"type": "text", "text": prompt}
                        ]
                    }
                ],
                max_tokens=2000,
                temperature=0.3
            )
            result = response.choices[0].message.content.strip()
            return result
        except Exception as e:
            from llm_spec import vision_model_label

            model = vision_model_label(self.config, "vision_screen_model")
            print(f"❌ [{model}] 屏幕分析失败: {e}")
            import traceback
            traceback.print_exc()
            return f"屏幕分析失败: {str(e)}"

    @_with_vision_tts_pause
    def analyze_screen(self, user_question: str = "", stream_callback=None) -> str:
        """截屏并使用视觉模型分析屏幕内容，返回分析结果文本。"""
        if not self.config.get("screenshot_allowed", True):
            return "截图许可已关闭，无法进行截屏分析。请使用快捷键开启截图许可后再试。"
        getattr(self, "on_screen_analyze_start", lambda: None)()
        screenshot_path = self._capture_screen()
        if not screenshot_path:
            return "截屏失败，请确认已安装 PIL(Pillow) 或 mss 库。"
        try:
            from llm_vision_router import analyze_screen_image

            return analyze_screen_image(
                self.config,
                screenshot_path,
                user_question,
                stream_callback=stream_callback,
                system_prompt=self.get_main_system_prompt(),
            )
        finally:
            if screenshot_path and os.path.exists(screenshot_path):
                try:
                    os.unlink(screenshot_path)
                except Exception:
                    pass

    @_with_vision_tts_pause
    def process_video(self, file_path, user_question: str = "", stream_callback=None):
        """处理视频文件"""
        try:
            print(f"🎬 开始处理视频: {file_path}")
            
            if not os.path.exists(file_path):
                return "错误：文件不存在"
            
            if not self._is_video_file(file_path):
                return "错误：不是有效的视频文件"

            from custom_models_store import get_vision_dashscope_api_key
            from llm_vision_router import analyze_video_file, is_dashscope_video_spec, vision_is_configured

            if vision_is_configured(self.config):
                from llm_spec import vision_model_label

                video_model = vision_model_label(self.config, "vision_video_model")
                print(f"🤖 使用视觉模型分析视频: {video_model}")
                try:
                    result = analyze_video_file(
                        self.config,
                        file_path,
                        user_question,
                        stream_callback=stream_callback,
                        system_prompt=self.get_main_system_prompt(),
                    )
                    if result and not result.startswith("错误") and not result.startswith(
                        "视频分析失败"
                    ):
                        self.recent_video_analysis = {
                            "video_path": file_path,
                            "video_name": os.path.basename(file_path),
                            "analysis": result,
                            "is_segmented": "[SEGMENTED_VIDEO_ANALYSIS]" in result,
                        }
                        print(f"💾 已保存视频分析上下文: {os.path.basename(file_path)}")
                        return result
                except Exception as e:
                    print(f"⚠️ 视觉路由视频分析失败: {e}")

            if (
                get_vision_dashscope_api_key(self.config)
                and is_dashscope_video_spec(self.config)
            ):
                print("🤖 使用 DashScope 分段/直传分析视频")
                try:
                    result = self._analyze_video_with_qwen3vl(file_path, user_question)
                    self.recent_video_analysis = {
                        "video_path": file_path,
                        "video_name": os.path.basename(file_path),
                        "analysis": result,
                        "is_segmented": "[SEGMENTED_VIDEO_ANALYSIS]" in result,
                    }
                    print(f"💾 已保存视频分析上下文: {os.path.basename(file_path)}")
                    return result
                except Exception as e:
                    print(f"⚠️ DashScope 视频分析失败: {e}，尝试 OpenCV 备用分析")

            print("⚠️ 使用 OpenCV 备用分析")
            return self._analyze_video_with_opencv(file_path, user_question)
                
        except Exception as e:
            print(f"❌ 视频处理失败: {str(e)}")
            return f"视频处理失败: {str(e)}"

    def _analyze_video_with_qwen3vl(self, file_path: str, user_question: str = "") -> str:
        """遗留：DashScope 直连接口分析视频（主路径见 llm_vision_router）。"""
        try:
            import openai
            import base64
            import os
            
            # 检查视频文件大小
            file_size = os.path.getsize(file_path)
            MAX_SIZE_MB = 50  # 单次请求最大50MB（base64编码后）
            MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024
            
            print(f"📹 视频文件大小: {file_size / 1024 / 1024:.2f}MB")
            
            # 🔥 检查视频时长（客服建议不超过30秒）
            try:
                import cv2
                cap = cv2.VideoCapture(file_path)
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    duration = frame_count / fps if fps > 0 else 0
                    cap.release()
                    
                    print(f"📹 视频时长: {duration:.2f}秒")
                    
                    # 🔥 如果视频时长超过30秒，自动分段处理
                    MAX_DURATION = 30  # 客服建议不超过30秒
                    if duration > MAX_DURATION:
                        print(f"⚠️ 视频时长超过{MAX_DURATION}秒，将进行分段分析...")
                        return self._analyze_video_in_segments(file_path, user_question, MAX_SIZE_BYTES, MAX_DURATION)
            except ImportError:
                print("⚠️ 无法检查视频时长（需要opencv-python），将按文件大小判断")
            except Exception as e:
                print(f"⚠️ 检查视频时长失败: {e}，将按文件大小判断")
            
            # 如果文件过大，需要分段分析
            if file_size > MAX_SIZE_BYTES:
                print(f"⚠️ 视频文件过大，将进行分段分析...")
                return self._analyze_video_in_segments(file_path, user_question, MAX_SIZE_BYTES, 30)
            
            # 文件大小和时长都合适，直接分析
            return self._analyze_single_video(file_path, user_question)
            
        except Exception as e:
            from llm_spec import vision_model_label

            model = vision_model_label(self.config, "vision_video_model")
            print(f"❌ [{model}] 视频分析失败: {e}")
            import traceback
            traceback.print_exc()
            raise e

    def _analyze_single_video(self, file_path: str, user_question: str = "") -> str:
        """分析单个视频文件（不超过大小限制）"""
        import openai
        import base64
        import os
        
        # 🔥 先检查原始文件大小（客服确认：data-uri限制是10MB原始数据，安全阈值8MB）
        file_size = os.path.getsize(file_path)
        file_size_mb = file_size / 1024 / 1024
        MAX_DATA_URI_SIZE_MB = 10  # API限制
        SAFE_SIZE_MB = 8  # 客服建议的安全阈值
        
        if file_size_mb > SAFE_SIZE_MB:
            raise ValueError(f"视频原始文件大小 ({file_size_mb:.2f}MB) 超过安全阈值 ({SAFE_SIZE_MB}MB)，需要使用关键帧方式")
        
        # 读取视频文件并转换为base64
        with open(file_path, 'rb') as video_file:
            video_data = video_file.read()
            video_base64 = base64.b64encode(video_data).decode('utf-8')
        
        base64_size_mb = len(video_base64) / 1024 / 1024
        print(f"📹 原始文件大小: {file_size_mb:.2f}MB, Base64编码后字符串长度: {base64_size_mb:.2f}MB")
        
        # 构建提示词
        if user_question:
            prompt = f"请分析这个视频，并回答以下问题：{user_question}"
        else:
            prompt = "请详细分析这个视频的内容，包括视频中的场景、动作、文字、物体、人物等所有可见信息。"
        
        from custom_models_store import get_vision_dashscope_api_key

        api_key = get_vision_dashscope_api_key(self.config)
        video_model = self.config.get("vision_dashscope_video_model", "qwen-vl-plus")
        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout=300.0  # 🔥 增加客户端超时时间到5分钟
        )
        
        print(f"🔧 发送视频到 DashScope 视觉 API（大小: {len(video_data)/1024/1024:.2f}MB）...")
        
        try:
            response = client.chat.completions.create(
                model=video_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "video_url",
                                "video_url": {
                                    "url": f"data:video/mp4;base64,{video_base64}"
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ],
                max_tokens=2000,
                temperature=0.7,
                timeout=300  # 🔥 增加API调用超时时间到5分钟（客服建议120秒以上）
            )
            
            result = response.choices[0].message.content.strip()
            return result
        except Exception as e:
            error_msg = str(e)
            if "Connection" in error_msg or "timeout" in error_msg.lower() or "413" in error_msg:
                print(f"⚠️ 视频传输失败，可能原因：")
                print(f"   1. 视频文件过大或时长过长")
                print(f"   2. 网络连接不稳定")
                print(f"   3. 服务端处理超时")
                print(f"   建议：使用分段分析功能")
            raise e

    def _analyze_video_in_segments(self, file_path: str, user_question: str, max_segment_size: int, max_duration: float = 30) -> str:
        """将大视频分段分析，结果交由主agent整合"""
        try:
            import cv2
            import tempfile
            import os
            
            print(f"📹 开始分段分析视频（每段最长{max_duration}秒）...")
            
            # 打开视频文件
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                return "错误：无法打开视频文件"
            
            # 获取视频信息
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            duration = frame_count / fps if fps > 0 else 0
            
            print(f"📹 视频信息: {frame_count}帧, {fps:.2f}fps, {width}x{height}, 时长{duration:.2f}秒")
            
            # 🔥 按时长分段（每段不超过max_duration秒）
            total_duration = duration
            num_segments = int(total_duration / max_duration) + 1
            actual_segment_duration = total_duration / num_segments
            
            print(f"📹 将视频分为 {num_segments} 段，每段约 {actual_segment_duration:.2f} 秒")
            
            # 分段分析结果
            segment_results = []
            
            for segment_idx in range(num_segments):
                start_time = segment_idx * actual_segment_duration
                end_time = min((segment_idx + 1) * actual_segment_duration, total_duration)
                
                print(f"📹 分析第 {segment_idx + 1}/{num_segments} 段: {start_time:.2f}s - {end_time:.2f}s")
                
                # 提取视频段
                segment_path = self._extract_video_segment(cap, file_path, start_time, end_time, segment_idx)
                
                if segment_path:
                    try:
                        # 检查分段文件大小
                        segment_size = os.path.getsize(segment_path)
                        segment_size_mb = segment_size / 1024 / 1024
                        
                        # 🔥 客服确认：data-uri限制是10MB原始数据，安全阈值8MB
                        if segment_size_mb > 8:
                            print(f"⚠️ 第 {segment_idx + 1} 段文件过大 (原始: {segment_size_mb:.2f}MB)，超过安全阈值8MB，使用关键帧方式分析...")
                            # 使用关键帧方式分析
                            segment_result = self._analyze_video_segment_with_frames(segment_path, start_time, end_time, user_question, segment_idx + 1)
                        else:
                            # 分析这一段视频
                            segment_prompt = f"这是视频的第 {segment_idx + 1} 段（时间范围: {start_time:.2f}s - {end_time:.2f}s）。"
                            if user_question:
                                segment_prompt += f"\n\n请分析这段视频，并回答以下问题：{user_question}"
                            else:
                                segment_prompt += "\n\n请详细分析这段视频的内容。"
                            
                            try:
                                segment_result = self._analyze_single_video(segment_path, segment_prompt)
                            except ValueError as ve:
                                # 🔥 如果原始文件大小仍然过大，使用关键帧方式
                                if "原始文件大小" in str(ve) or "Base64编码后字符串长度" in str(ve) or "Base64编码后大小" in str(ve):
                                    print(f"⚠️ 第 {segment_idx + 1} 段文件大小超过限制，改用关键帧方式...")
                                    segment_result = self._analyze_video_segment_with_frames(segment_path, start_time, end_time, user_question, segment_idx + 1)
                                else:
                                    raise
                            except Exception as e:
                                # 🔥 如果API返回400错误（data-uri大小超限或其他限制），也使用关键帧方式
                                error_str = str(e)
                                if ("Exceeded limit on max bytes per data-uri" in error_str or 
                                    "10485760" in error_str or
                                    "String value length" in error_str or 
                                    "exceeds the maximum allowed" in error_str or 
                                    "20000000" in error_str):
                                    print(f"⚠️ 第 {segment_idx + 1} 段API返回data-uri大小超限错误，改用关键帧方式...")
                                    segment_result = self._analyze_video_segment_with_frames(segment_path, start_time, end_time, user_question, segment_idx + 1)
                                else:
                                    raise
                        segment_results.append({
                            "segment": segment_idx + 1,
                            "start_time": start_time,
                            "end_time": end_time,
                            "result": segment_result
                        })
                        print(f"✅ 第 {segment_idx + 1} 段分析完成")
                    except Exception as e:
                        print(f"⚠️ 第 {segment_idx + 1} 段分析失败: {e}")
                        segment_results.append({
                            "segment": segment_idx + 1,
                            "start_time": start_time,
                            "end_time": end_time,
                            "result": f"分析失败: {str(e)}"
                        })
                    finally:
                        # 清理临时文件
                        try:
                            if os.path.exists(segment_path):
                                os.remove(segment_path)
                        except:
                            pass
            
            cap.release()
            
            # 🔥 构建分段分析结果，标记需要主agent整合
            if user_question:
                integration_prompt = f"""我已经将视频分为 {num_segments} 段进行了分析。以下是各段的分析结果：

"""
            else:
                integration_prompt = f"""我已经将视频分为 {num_segments} 段进行了分析。以下是各段的分析结果：

"""
            
            for seg_result in segment_results:
                integration_prompt += f"""
【第 {seg_result['segment']} 段】（时间: {seg_result['start_time']:.2f}s - {seg_result['end_time']:.2f}s）
{seg_result['result']}

"""
            
            if user_question:
                integration_prompt += f"\n\n请整合以上所有分段的分析结果，回答用户的问题：{user_question}"
            else:
                integration_prompt += "\n\n请整合以上所有分段的分析结果，生成完整的视频分析报告。"
            
            # 🔥 返回分段结果，使用特殊标记表示需要主agent整合
            return f"[SEGMENTED_VIDEO_ANALYSIS]\n{integration_prompt}"
            
        except ImportError:
            return "错误：需要安装opencv-python库来处理视频（pip install opencv-python）"
        except Exception as e:
            print(f"❌ 视频分段分析失败: {e}")
            import traceback
            traceback.print_exc()
            return f"视频分段分析失败: {str(e)}"

    def _extract_video_segment(self, cap, original_path: str, start_time: float, end_time: float, segment_idx: int) -> str:
        """提取视频片段到临时文件（带压缩）"""
        try:
            import cv2
            import tempfile
            
            original_fps = cap.get(cv2.CAP_PROP_FPS)
            # 🔥 限制帧率为30fps（客服建议）
            MAX_FPS = 30
            if original_fps > MAX_FPS:
                fps = MAX_FPS
                print(f"📹 降低帧率: {original_fps:.2f}fps -> {fps:.2f}fps")
            else:
                fps = original_fps
            
            start_frame = int(start_time * fps)
            end_frame = int(end_time * fps)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            # 🔥 如果分辨率过高，降低分辨率以减小文件大小（客服建议：不超过1280x720）
            # 目标：确保原始文件大小不超过8MB（安全阈值）
            max_width = 1280
            max_height = 720
            if width > max_width or height > max_height:
                scale = min(max_width / width, max_height / height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                print(f"📹 降低分辨率: {width}x{height} -> {new_width}x{new_height}")
            else:
                new_width = width
                new_height = height
            
            # 创建临时文件
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
            temp_path = temp_file.name
            temp_file.close()
            
            # 🔥 设置视频编码器，优先使用H.264（客服推荐），添加错误处理
            # 尝试多种编码器，确保兼容性
            fourcc_options = [
                ('avc1', 'H.264'),  # 🔥 优先尝试H.264（客服推荐）
                ('mp4v', 'MPEG-4'),
                ('XVID', 'Xvid'),
                ('MJPG', 'Motion JPEG')
            ]
            
            out = None
            used_codec = None
            for codec_name, codec_desc in fourcc_options:
                try:
                    fourcc = cv2.VideoWriter_fourcc(*codec_name)
                    out = cv2.VideoWriter(temp_path, fourcc, fps, (new_width, new_height))
                    if out.isOpened():
                        used_codec = codec_desc
                        print(f"✅ 使用编码器: {codec_desc} ({codec_name})")
                        break
                    else:
                        out.release()
                        out = None
                except:
                    if out:
                        out.release()
                        out = None
                    continue
            
            if out is None or not out.isOpened():
                raise Exception("无法初始化视频编码器，所有编码器都失败")
            
            # 定位到起始帧（使用原始fps定位，然后按新fps采样）
            if original_fps != fps:
                # 如果帧率改变了，需要重新计算帧位置
                original_start_frame = int(start_time * original_fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, original_start_frame)
                frame_skip = int(original_fps / fps)  # 跳帧比例
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                frame_skip = 1
            
            # 读取并写入帧
            current_frame = start_frame
            frames_written = 0
            frames_to_write = end_frame - start_frame
            frame_counter = 0  # 用于跳帧计数
            
            while frames_written < frames_to_write:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # 🔥 如果帧率改变了，需要跳帧
                if original_fps != fps:
                    # 只写入需要的帧（按新fps采样）
                    if frame_counter % frame_skip == 0:
                        # 如果分辨率需要调整，先调整大小
                        if new_width != width or new_height != height:
                            frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
                        out.write(frame)
                        frames_written += 1
                    frame_counter += 1
                else:
                    # 🔥 如果分辨率需要调整，先调整大小
                    if new_width != width or new_height != height:
                        frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
                    out.write(frame)
                    frames_written += 1
                    current_frame += 1
            
            out.release()
            
            return temp_path
            
        except Exception as e:
            print(f"❌ 提取视频片段失败: {e}")
            return None

    def _analyze_video_with_opencv(self, file_path: str, user_question: str = "") -> str:
        """使用OpenCV提取关键帧进行备用分析"""
        try:
            import cv2
            import base64
            import io
            from PIL import Image
            import openai
            
            print("📹 使用OpenCV提取关键帧进行备用分析...")
            
            # 打开视频文件
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                return "错误：无法打开视频文件"
            
            # 获取视频信息
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count / fps if fps > 0 else 0
            
            print(f"📹 视频信息: {frame_count}帧, {fps:.2f}fps, 时长{duration:.2f}秒")
            
            # 提取关键帧（每5秒一帧，最多10帧）
            frames = []
            frame_interval = max(1, int(fps * 5))  # 每5秒一帧
            max_frames = 10
            
            frame_idx = 0
            while len(frames) < max_frames and frame_idx < frame_count:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if ret:
                    # 转换BGR到RGB
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    frames.append((frame_idx, frame_rgb))
                frame_idx += frame_interval
            
            cap.release()
            
            if not frames:
                return "错误：无法提取视频帧"
            
            print(f"✅ 提取了 {len(frames)} 个关键帧")
            
            from custom_models_store import get_vision_dashscope_api_key

            qwen3vl_key = get_vision_dashscope_api_key(self.config)
            video_model = self.config.get("vision_dashscope_video_model", "qwen-vl-plus")
            if qwen3vl_key:
                client = openai.OpenAI(
                    api_key=qwen3vl_key,
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
                )
                
                # 构建提示词
                if user_question:
                    prompt = f"请分析这些视频关键帧，并回答以下问题：{user_question}\n\n这些帧是从视频中提取的关键帧，请综合分析整个视频的内容。"
                else:
                    prompt = "请详细分析这些视频关键帧的内容，包括场景、动作、文字、物体、人物等所有可见信息。这些帧是从视频中提取的关键帧，请综合分析整个视频的内容。"
                
                # 准备图片内容
                content = []
                for idx, frame in frames:
                    # 将帧转换为PIL Image
                    img = Image.fromarray(frame)
                    # 转换为base64
                    buffer = io.BytesIO()
                    img.save(buffer, format='JPEG', quality=85)
                    frame_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{frame_base64}"
                        }
                    })
                
                # 添加文本提示
                content.append({
                    "type": "text",
                    "text": prompt
                })
                
                # 调用API
                response = client.chat.completions.create(
                    model=video_model,
                    messages=[
                        {
                            "role": "user",
                            "content": content
                        }
                    ],
                    max_tokens=2000,
                    temperature=0.7,
                    timeout=120  # 2分钟超时
                )
                
                result = response.choices[0].message.content.strip()
                return result
            else:
                # 如果没有API密钥，返回基本信息
                return f"视频基本信息：\n- 时长: {duration:.2f}秒\n- 帧数: {frame_count}\n- 帧率: {fps:.2f}fps\n- 关键帧数: {len(frames)}\n\n（需要配置 DashScope 视觉 API 密钥进行详细分析）"
            
        except ImportError:
            return "错误：需要安装opencv-python库来处理视频（pip install opencv-python）"
        except Exception as e:
            print(f"❌ OpenCV视频分析失败: {e}")
            import traceback
            traceback.print_exc()
            return f"视频分析失败: {str(e)}"

    def _analyze_video_segment_with_frames(self, segment_path: str, start_time: float, end_time: float, user_question: str, segment_num: int) -> str:
        """使用关键帧方式分析视频片段（当分段文件过大时使用）"""
        try:
            import cv2
            import base64
            import io
            from PIL import Image
            import openai
            
            print(f"📹 使用关键帧方式分析第 {segment_num} 段...")
            
            # 打开视频片段
            cap = cv2.VideoCapture(segment_path)
            if not cap.isOpened():
                return "错误：无法打开视频片段"
            
            # 获取视频信息
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count / fps if fps > 0 else 0
            
            # 提取关键帧（每2秒一帧，最多15帧）
            frames = []
            frame_interval = max(1, int(fps * 2))  # 每2秒一帧
            max_frames = 15
            
            frame_idx = 0
            while len(frames) < max_frames and frame_idx < frame_count:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if ret:
                    # 转换BGR到RGB
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    frames.append((frame_idx, frame_rgb))
                frame_idx += frame_interval
            
            cap.release()
            
            if not frames:
                return "错误：无法提取视频帧"
            
            print(f"✅ 提取了 {len(frames)} 个关键帧")
            
            from custom_models_store import get_vision_dashscope_api_key

            qwen3vl_key = get_vision_dashscope_api_key(self.config)
            video_model = self.config.get("vision_dashscope_video_model", "qwen-vl-plus")
            if qwen3vl_key:
                client = openai.OpenAI(
                    api_key=qwen3vl_key,
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    timeout=300.0
                )
                
                # 构建提示词
                segment_info = f"这是视频的第 {segment_num} 段（时间范围: {start_time:.2f}s - {end_time:.2f}s）。"
                if user_question:
                    prompt = f"{segment_info}\n\n请分析这些关键帧，并回答以下问题：{user_question}\n\n这些帧是从视频片段中提取的关键帧，请综合分析整个片段的内容。"
                else:
                    prompt = f"{segment_info}\n\n请详细分析这些关键帧的内容，包括场景、动作、文字、物体、人物等所有可见信息。这些帧是从视频片段中提取的关键帧，请综合分析整个片段的内容。"
                
                # 准备图片内容
                content = []
                for idx, frame in frames:
                    # 将帧转换为PIL Image
                    img = Image.fromarray(frame)
                    # 转换为base64
                    buffer = io.BytesIO()
                    img.save(buffer, format='JPEG', quality=85)
                    frame_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{frame_base64}"
                        }
                    })
                
                # 添加文本提示
                content.append({
                    "type": "text",
                    "text": prompt
                })
                
                # 调用API
                response = client.chat.completions.create(
                    model=video_model,
                    messages=[
                        {
                            "role": "user",
                            "content": content
                        }
                    ],
                    max_tokens=2000,
                    temperature=0.7,
                    timeout=300
                )
                
                result = response.choices[0].message.content.strip()
                return result
            else:
                from llm_spec import vision_model_label

                model = vision_model_label(self.config, "vision_video_model")
                return f"错误：未配置 {model} 所需的视觉 API 密钥"
            
        except Exception as e:
            print(f"❌ 关键帧分析失败: {e}")
            import traceback
            traceback.print_exc()
            return f"关键帧分析失败: {str(e)}"

    def _is_video_file(self, file_path: str) -> bool:
        """检查是否为视频文件"""
        video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.webm', '.m4v', '.3gp']
        return any(file_path.lower().endswith(ext) for ext in video_extensions)
    
    def _analyze_file_with_tools(self, file_path):
        """使用工具分析文件"""
        try:
            # 调用MCP工具进行文件分析
            result = self.mcp_tools.server.call_tool("智能文件分析", file_path=file_path)
            return result
        except Exception as e:
            print(f"❌ 文件分析工具调用失败: {str(e)}")
            return None

    def _get_recent_weather_info(self):
        """获取最近的天气信息"""
        # 从最近的对话中查找天气信息
        for conv in reversed(self.session_conversations):
            ai_response = conv.get("ai_response", "")
            if "天气预报" in ai_response or "天气" in ai_response:
                return ai_response
        return None

    def _analyze_weather_quality(self, weather_info):
        """分析天气质量并给出评价"""
        try:
            # 解析天气信息
            weather_text = weather_info.lower()
            
            # 提取关键信息
            temperature = None
            weather_condition = None
            wind = None
            
            # 提取温度信息
            import re
            temp_match = re.search(r'(\d+)°c', weather_text)
            if temp_match:
                temperature = int(temp_match.group(1))
            
            # 提取天气状况
            if "晴" in weather_text:
                weather_condition = "晴"
            elif "多云" in weather_text:
                weather_condition = "多云"
            elif "阴" in weather_text:
                weather_condition = "阴"
            elif "雨" in weather_text:
                weather_condition = "雨"
            elif "雪" in weather_text:
                weather_condition = "雪"
            
            # 提取风力信息
            wind_match = re.search(r'([东南西北]风\d+-\d+级)', weather_text)
            if wind_match:
                wind = wind_match.group(1)
            
            # 分析天气质量
            analysis = "（快速分析天气数据）"
            
            # 温度评价
            if temperature:
                if temperature < 10:
                    temp_eval = "偏冷"
                elif temperature < 20:
                    temp_eval = "凉爽"
                elif temperature < 28:
                    temp_eval = "舒适"
                elif temperature < 35:
                    temp_eval = "较热"
                else:
                    temp_eval = "炎热"
            else:
                temp_eval = "适中"
            
            # 天气状况评价
            if weather_condition == "晴":
                condition_eval = "晴朗宜人"
            elif weather_condition == "多云":
                condition_eval = "温和舒适"
            elif weather_condition == "阴":
                condition_eval = "略显沉闷"
            elif weather_condition == "雨":
                condition_eval = "需要注意防雨"
            elif weather_condition == "雪":
                condition_eval = "需要注意保暖"
            else:
                condition_eval = "天气一般"
            
            # 综合评价
            if temperature and weather_condition:
                if temperature >= 20 and temperature <= 28 and weather_condition in ["晴", "多云"]:
                    overall_eval = "非常好的天气"
                    recommendation = "适合户外活动、出行和运动"
                elif temperature >= 15 and temperature <= 30 and weather_condition in ["晴", "多云", "阴"]:
                    overall_eval = "不错的天气"
                    recommendation = "适合日常活动和出行"
                elif weather_condition == "雨":
                    overall_eval = "需要注意的天气"
                    recommendation = "建议携带雨具，注意防滑"
                elif temperature < 10 or temperature > 35:
                    overall_eval = "需要适应的天气"
                    recommendation = "注意保暖或防暑降温"
                else:
                    overall_eval = "一般的天气"
                    recommendation = "根据个人情况安排活动"
            else:
                overall_eval = "天气状况一般"
                recommendation = "建议关注实时天气变化"
            
            # 构建分析结果
            analysis += f"\n\n🌤️ 天气质量分析\n"
            analysis += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            if temperature:
                analysis += f"🌡️ 温度评价：{temp_eval} ({temperature}°C)\n"
            if weather_condition:
                analysis += f"☁️ 天气状况：{condition_eval}\n"
            if wind:
                analysis += f"💨 风力情况：{wind}\n"
            analysis += f"\n📊 综合评价：{overall_eval}\n"
            analysis += f"💡 建议：{recommendation}\n"
            analysis += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            
            return analysis
            
        except Exception as e:
            return f"（微微皱眉）抱歉指挥官，分析天气时遇到了问题：{str(e)}"

    def update_tts_config(self, config):
        """更新TTS配置"""
        self.config = config
        previous_manager = getattr(self, "tts_manager", None)
        try:
            from tts_manager import TTSManager
            if previous_manager is not None:
                previous_manager.stop_speaking()
            provider = config.get("tts_provider", "azure")
            azure_key = config.get("azure_tts_key", "")
            azure_region = config.get("azure_region", "eastasia")
            dashscope_key = config.get("dashscope_key", "")
            if not hasattr(self, 'tts_manager') or self.tts_manager is None:
                self.tts_manager = TTSManager(
                    azure_key=azure_key,
                    region=azure_region,
                    provider=provider,
                    dashscope_key=dashscope_key,
                    config=config,
                )
                print("✅ TTS管理器已创建")
            else:
                self.tts_manager.update_config(
                    azure_key=azure_key,
                    region=azure_region,
                    provider=provider,
                    dashscope_key=dashscope_key,
                    config=config,
                )
                print("✅ TTS配置已更新")
            if config.get("tts_enabled", False) and self.tts_manager:
                self.tts_manager.set_voice(config.get("tts_voice", "zh-CN-XiaoxiaoNeural" if provider == "azure" else "Cherry"))
                self.tts_manager.set_speaking_rate(config.get("tts_speaking_rate", 1.0))
                print("✅ TTS功能已启用")
            else:
                print("ℹ️ TTS功能已禁用")
        except Exception as e:
            print(f"⚠️ TTS配置更新失败: {str(e)}")
            if previous_manager is not None:
                try:
                    previous_manager.cleanup()
                except Exception:
                    pass
            self.tts_manager = None
    
    def stop_tts(self):
        """停止TTS播放"""
        tts_manager = getattr(self, "tts_manager", None)
        if tts_manager is not None:
            tts_manager.stop_speaking()

    def _finalize_tts_response(self, response, streaming_started=False):
        """Ensure framework early returns also close/play their TTS session."""
        manager = getattr(self, "tts_manager", None)
        if (
            manager is None
            or not self.config.get("tts_enabled", False)
            or self.is_generation_cancelled()
            or not manager.is_available()
        ):
            return
        clean_text = re.sub(r"[（\(].*?[）\)]", "", str(response or ""))
        clean_text = re.sub(
            r"""[^\u4e00-\u9fa5a-zA-Z0-9\s，。！？、；：""'（）]""",
            "",
            clean_text,
        ).strip()
        if streaming_started:
            remaining = str(response or "")[getattr(self, "_tts_sent_up_to", 0):]
            remaining = re.sub(r"[（\(].*?[）\)]", "", remaining)
            remaining = re.sub(
                r"""[^\u4e00-\u9fa5a-zA-Z0-9\s，。！？、；：""'（）]""",
                "",
                remaining,
            ).strip()
            manager.end_tts_stream(remaining)
        elif clean_text:
            manager.speak_text(clean_text)

    def pause_local_tts_for_vision(self):
        """Release F5-TTS VRAM before a local/vision workload."""
        manager = getattr(self, "tts_manager", None)
        if (
            manager is not None
            and getattr(manager, "provider", "") == "f5tts"
            and self.config.get("f5tts_pause_for_vision", True)
        ):
            manager.stop_speaking()
            client = getattr(manager, "f5_client", None)
            if client is not None:
                client.unload()

    def resume_local_tts_after_vision(self):
        """Warm F5-TTS again only when resident mode requests it."""
        manager = getattr(self, "tts_manager", None)
        if (
            manager is not None
            and getattr(manager, "provider", "") == "f5tts"
            and self.config.get("f5tts_pause_for_vision", True)
            and self.config.get("f5tts_residency_mode", "resident") == "resident"
            and self.config.get("f5tts_start_mode", "startup") == "startup"
        ):
            client = getattr(manager, "f5_client", None)
            if client is not None:
                threading.Thread(
                    target=client.ensure_started,
                    kwargs={"warmup": True},
                    daemon=True,
                ).start()
    
    def cleanup_tts(self):
        """清理TTS资源"""
        tts_manager = getattr(self, "tts_manager", None)
        if tts_manager is not None:
            tts_manager.cleanup()
    
    def test_tts(self):
        """测试TTS功能"""
        if hasattr(self, 'tts_manager') and self.tts_manager:
            return self.tts_manager.test_tts("你好，这是露尼西亚的TTS测试")
        else:
            print("❌ TTS管理器未初始化")
            return False

    def _simple_parse_file_info(self, user_input, context_info):
        """简单解析文件信息（AI智能优先）"""
        try:
            print(f"🔍 开始AI智能解析文件信息: {user_input}")
            
            file_info = {
                "title": "未命名文件",
                "filename": "未命名文件.txt",
                "location": "D:/",
                "content": context_info
            }
            
            # 从用户输入和上下文中提取旅游目的地
            destination = self._extract_travel_destination(user_input, context_info)
            
            # 从用户输入中提取信息
            if "旅游" in user_input or "旅行" in user_input or "旅游计划" in user_input or "攻略" in user_input:
                if destination:
                    file_info["title"] = f"{destination}旅游攻略"
                    file_info["filename"] = f"{destination}旅游攻略.txt"
                else:
                    file_info["title"] = "旅游攻略"
                    file_info["filename"] = "旅游攻略.txt"
                
                # 从上下文中提取旅游计划内容
                if destination and destination in context_info:
                    # 提取包含目的地的内容
                    lines = context_info.split('\n')
                    relevant_lines = []
                    for line in lines:
                        if destination in line or "旅游" in line or "旅行" in line or "攻略" in line or "景点" in line or "行程" in line:
                            relevant_lines.append(line)
                    if relevant_lines:
                        file_info["content"] = "\n".join(relevant_lines)
                    else:
                        file_info["content"] = context_info
                else:
                    file_info["content"] = context_info
            elif "音乐" in user_input or "歌单" in user_input or "歌曲" in user_input:
                # 用户明确要求音乐相关文件
                file_info["title"] = "音乐推荐"
                file_info["filename"] = "音乐推荐.txt"
                file_info["content"] = context_info
            elif "保存" in user_input:
                # 🔥 优先检查上下文中是否有代码
                has_code = False
                code_lang = None
                extracted_code = None
                
                # 从上下文中提取代码
                if "```" in context_info:
                    extracted_code = self._extract_code_from_context(context_info)
                    if extracted_code:
                        has_code = True
                        # 检测代码语言
                        if "```java" in context_info:
                            code_lang = "java"
                        elif "```python" in context_info or "```py" in context_info:
                            code_lang = "python"
                        elif "```cpp" in context_info or "```c++" in context_info:
                            code_lang = "cpp"
                        elif "```javascript" in context_info or "```js" in context_info:
                            code_lang = "javascript"
                
                # 如果有代码，设置为代码文件
                if has_code and code_lang:
                    if code_lang == "java":
                        # 🔥 智能提取Java类名
                        class_name = self._extract_java_class_name(extracted_code)
                        if class_name:
                            file_info["title"] = class_name
                            file_info["filename"] = f"{class_name}.java"
                        else:
                            file_info["title"] = "JavaProgram"
                            file_info["filename"] = "JavaProgram.java"
                        file_info["file_type"] = "java"
                    elif code_lang == "python":
                        file_info["title"] = "Python代码"
                        file_info["filename"] = "program.py"
                        file_info["file_type"] = "py"
                    elif code_lang == "cpp":
                        file_info["title"] = "C++代码"
                        file_info["filename"] = "program.cpp"
                        file_info["file_type"] = "cpp"
                    elif code_lang == "javascript":
                        file_info["title"] = "JavaScript代码"
                        file_info["filename"] = "script.js"
                        file_info["file_type"] = "js"
                    
                    file_info["content"] = extracted_code
                    print(f"✅ 从上下文提取到{code_lang}代码，文件名: {file_info['filename']}")
                
                # 检查用户是否明确指定了文件类型
                elif ".py" in user_input.lower() or "python" in user_input.lower():
                    file_info["title"] = "Python代码"
                    file_info["filename"] = "Python代码.py"
                elif ".cpp" in user_input.lower() or "c++" in user_input.lower():
                    file_info["title"] = "C++代码"
                    file_info["filename"] = "C++代码.cpp"
                elif ".java" in user_input.lower():
                    file_info["title"] = "Java代码"
                    file_info["filename"] = "Java代码.java"
                elif ".js" in user_input.lower() or "javascript" in user_input.lower():
                    file_info["title"] = "JavaScript代码"
                    file_info["filename"] = "JavaScript代码.js"
                elif ".txt" in user_input.lower():
                    # 用户明确要求txt文件，根据上下文内容确定类型
                    if "音乐" in context_info or "歌" in context_info or "歌曲" in context_info or "推荐" in context_info:
                        file_info["title"] = "音乐推荐"
                        file_info["filename"] = "音乐推荐.txt"
                    elif "旅游" in context_info or "旅行" in context_info or "攻略" in context_info:
                        file_info["title"] = "旅游攻略"
                        file_info["filename"] = "旅游攻略.txt"
                    elif "代码" in context_info or "程序" in context_info or "```" in context_info:
                        file_info["title"] = "代码文件"
                        file_info["filename"] = "代码文件.txt"
                    else:
                        file_info["title"] = "文档"
                        file_info["filename"] = "文档.txt"
                else:
                    # 🚀 使用统一的文件保存信息识别（一次AI调用获取所有信息）
                    print(f"✅ 用户说'帮我保存'，调用统一文件保存识别Agent")
                    ai_save_info = self._ai_identify_file_save_info(user_input, context_info)
                    if ai_save_info:
                        print(f"✅ 统一识别成功: {ai_save_info.get('filename')}")
                        # 应用AI识别的结果
                        if "title" in ai_save_info:
                            file_info["title"] = ai_save_info["title"]
                        if "filename" in ai_save_info:
                            file_info["filename"] = ai_save_info["filename"]
                        if "file_type" in ai_save_info:
                            file_info["file_type"] = ai_save_info["file_type"]
                        if "location" in ai_save_info:
                            file_info["location"] = ai_save_info["location"]
                        if "content" in ai_save_info:
                            file_info["content"] = ai_save_info["content"]
                    else:
                        print(f"⚠️ 统一识别失败，使用关键词识别后备方案")
                        # 关键词识别后备方案 - 优先检查当前对话的上下文
                        # 检查是否包含旅游相关内容
                        if any(keyword in context_info for keyword in ["旅游", "旅行", "攻略", "景点", "行程"]):
                            # 🚀 智能提取目的地名称 - 优先从用户问题中提取
                            destinations = [
                                "法兰克福", "贝尔格莱德", "柏林", "塔林", "巴黎", "伦敦", "罗马", "东京", "纽约",
                                "阿姆斯特丹", "巴塞罗那", "维也纳", "布拉格", "布达佩斯", "华沙", "莫斯科", "圣彼得堡",
                                "伊斯坦布尔", "迪拜", "新加坡", "曼谷", "首尔", "悉尼", "墨尔本", "温哥华", "多伦多"
                            ]
                            
                            destination = None
                            
                            # 首先尝试从用户问题中提取（优先级最高）
                            user_question = ""
                            for conv in self.session_conversations[-3:]:  # 检查最近3轮对话
                                if "旅游" in conv.get("user_input", "") or "攻略" in conv.get("user_input", ""):
                                    user_question = conv.get("user_input", "")
                                    break
                            
                            if user_question:
                                for dest in destinations:
                                    if dest in user_question:
                                        destination = dest
                                        print(f"✅ 从用户问题中提取到目的地: {destination}")
                                        break
                            
                            # 如果用户问题中没有找到，再从上下文中查找
                            if not destination:
                                for dest in destinations:
                                    if dest in context_info:
                                        destination = dest
                                        print(f"✅ 从上下文中提取到目的地: {destination}")
                                        break
                            
                            if destination:
                                file_info["title"] = f"{destination}旅游攻略"
                                file_info["filename"] = f"{destination}旅游攻略.txt"
                                print(f"✅ 生成文件名: {file_info['filename']}")
                            else:
                                file_info["title"] = "旅游攻略"
                                file_info["filename"] = "旅游攻略.txt"
                                print(f"⚠️ 未找到具体目的地，使用通用名称")
                        elif any(keyword in context_info for keyword in ["代码", "程序", "```", "python", "c++", "java"]):
                            file_info["title"] = "代码文件"
                            file_info["filename"] = "代码文件.txt"
                        elif any(keyword in context_info for keyword in ["笔记", "记录", "备忘"]):
                            file_info["title"] = "笔记"
                            file_info["filename"] = "笔记.txt"
                        else:
                            # 如果都无法确定，使用AI智能识别的结果
                            file_info["title"] = "文档"
                            file_info["filename"] = "文档.txt"
                file_info["content"] = context_info
            elif "笔记" in user_input:
                file_info["title"] = "笔记"
                file_info["filename"] = "笔记.txt"
                file_info["content"] = context_info
            elif "代码" in user_input or "程序" in user_input or "python" in user_input.lower():
                # 根据编程语言确定文件扩展名
                if "python" in user_input.lower() or "py" in user_input.lower():
                    file_info["title"] = "Python代码"
                    file_info["filename"] = "Python代码.py"
                elif "c++" in user_input.lower() or "cpp" in user_input.lower():
                    file_info["title"] = "C++代码"
                    file_info["filename"] = "C++代码.cpp"
                elif "java" in user_input.lower():
                    file_info["title"] = "Java代码"
                    file_info["filename"] = "Java代码.java"
                elif "javascript" in user_input.lower() or "js" in user_input.lower():
                    file_info["title"] = "JavaScript代码"
                    file_info["filename"] = "JavaScript代码.js"
                else:
                    file_info["title"] = "代码文件"
                    file_info["filename"] = "代码文件.txt"
                file_info["content"] = context_info
            else:
                file_info["title"] = "文档"
                file_info["filename"] = "文档.txt"
                file_info["content"] = context_info
            
            # 🚀 使用统一的文件保存信息识别（包含路径识别）
            # 注意：这里可能已经在上面的代码分支中调用过统一识别，避免重复
            # 这里主要处理其他文件类型的路径识别
            if not file_info.get("location"):
                import re
                
                # 优先检查用户是否明确指定了路径
                if "d盘" in user_input.lower() or "d:" in user_input.lower():
                    file_info["location"] = "D:/"
                elif "c盘" in user_input.lower() or "c:" in user_input.lower():
                    file_info["location"] = "C:/"
                else:
                    # 匹配各种路径格式
                    path_patterns = [
                        r'保存到\s*([A-Za-z]:[^，。\s]*)',  # 保存到D:\测试_
                        r'保存到\s*([A-Za-z]:[^，。\s]*)',  # 保存到D:/测试_
                        r'位置在\s*([A-Za-z]:[^，。\s]*)',  # 位置在D:\测试_
                        r'位置\s*是\s*([A-Za-z]:[^，。\s]*)',  # 位置是D:\测试_
                        r'([A-Za-z]:[^，。\s]*)',  # 直接说D:\测试_
                    ]
                    
                    extracted_path = None
                    for pattern in path_patterns:
                        match = re.search(pattern, user_input, re.IGNORECASE)
                        if match:
                            extracted_path = match.group(1)
                            break
                    
                    if extracted_path:
                        # 标准化路径格式
                        extracted_path = extracted_path.replace('\\', '/')
                        if not extracted_path.endswith('/'):
                            extracted_path += '/'
                        file_info["location"] = extracted_path
                    else:
                        # 使用默认保存路径
                        default_path = self.config.get("default_save_path", "D:/露尼西亚文件/")
                        if default_path and os.path.exists(default_path):
                            file_info["location"] = default_path
                        else:
                            # 如果默认路径不存在，尝试创建
                            try:
                                os.makedirs(default_path, exist_ok=True)
                                file_info["location"] = default_path
                            except:
                                # 如果创建失败，使用D盘根目录
                                file_info["location"] = "D:/"
            
            print(f"🔍 简单解析结果: {file_info['title']} -> {file_info['filename']} -> {file_info['location']}")
            return file_info
            
        except Exception as e:
            print(f"❌ 简单解析失败: {str(e)}")
            return None

    def _is_valid_path(self, path):
        """验证路径是否有效"""
        try:
            import re
            # 检查是否是有效的Windows路径格式
            if re.match(r'^[A-Za-z]:[/\\]', path):
                return True
            # 检查是否是相对路径
            elif path.startswith('./') or path.startswith('../'):
                return True
            # 检查是否是网络路径
            elif path.startswith('\\\\'):
                return True
            else:
                return False
        except:
            return False

    def _extract_travel_destination(self, user_input, context_info):
        """从用户输入和上下文中提取旅游目的地"""
        # 常见的旅游目的地
        destinations = [
            "北京", "上海", "广州", "深圳", "杭州", "南京", "苏州", "成都", "重庆", "西安",
            "香港", "澳门", "台湾", "日本", "韩国", "泰国", "新加坡", "马来西亚", "越南",
            "美国", "加拿大", "英国", "法国", "德国", "意大利", "西班牙", "澳大利亚", "新西兰"
        ]
        
        # 从用户输入中查找目的地
        for dest in destinations:
            if dest in user_input:
                return dest
        
        # 从上下文中查找目的地
        for dest in destinations:
            if dest in context_info:
                return dest
        
        return None

    def _analyze_user_request_type(self, user_input):
        """分析用户请求的类型 - 优先使用框架Agent传递的内容类型"""
        user_input_lower = user_input.lower()
        
        # 🔥 优先检查框架Agent是否已经识别了内容类型
        if hasattr(self, 'file_save_content_type') and self.file_save_content_type:
            content_type = self.file_save_content_type
            print(f"✅ 使用框架Agent识别的内容类型: {content_type}")
            
            # 映射content_type到request_type并清除标记
            self.file_save_content_type = None  # 使用后清除
            
            if content_type == "code":
                return "code_file"
            elif content_type == "music":
                return "music_file"
            elif content_type == "travel":
                return "travel_file"
            else:
                return "general_file"
        
        # 🔥 优先检查最近对话中是否有代码 - 如果有代码，且用户说"保存"，应该识别为code_file
        if any(keyword in user_input_lower for keyword in ["保存", "创建文件", "写入文件"]):
            # 检查最近的对话中是否有代码块
            has_code_in_context = False
            code_language = None
            
            if self.session_conversations:
                for conv in reversed(self.session_conversations[-3:]):
                    ai_response = conv.get("ai_response", "")
                    if "```" in ai_response:
                        has_code_in_context = True
                        # 检测代码语言
                        if "```java" in ai_response:
                            code_language = "java"
                        elif "```python" in ai_response or "```py" in ai_response:
                            code_language = "python"
                        elif "```cpp" in ai_response or "```c++" in ai_response:
                            code_language = "cpp"
                        elif "```javascript" in ai_response or "```js" in ai_response:
                            code_language = "javascript"
                        break
            
            # 如果最近对话中有代码，优先识别为代码文件
            if has_code_in_context:
                print(f"🔍 检测到上下文中有{code_language or ''}代码，识别为code_file")
                return "code_file"
        
        # 明确的文件创建请求
        file_creation_keywords = ["保存文件", "创建文件", "写入文件", "生成文件", "输出文件", "保存到文件", "创建到文件"]
        if any(keyword in user_input_lower for keyword in file_creation_keywords):
            # 进一步判断是什么类型的文件
            if any(keyword in user_input_lower for keyword in ["音乐", "歌", "歌曲", "歌单"]):
                return "music_file"
            elif any(keyword in user_input_lower for keyword in ["旅游", "旅行", "攻略", "景点"]):
                return "travel_file"
            elif any(keyword in user_input_lower for keyword in ["代码", "程序", "c++", "python", "java"]):
                return "code_file"
            elif any(keyword in user_input_lower for keyword in ["笔记", "记录", "备忘"]):
                return "note_file"
            elif any(keyword in user_input_lower for keyword in ["文件夹"]) and "创建文件夹" in user_input_lower:
                # 只有明确说"创建文件夹"才识别为folder，避免"目录"误触发
                return "folder"
            else:
                return "general_file"
        
        # 代码展示请求（不是文件创建）
        code_display_keywords = ["帮我写", "写一个", "用c++写", "用python写", "用java写", "写个", "帮我用"]
        if any(keyword in user_input_lower for keyword in code_display_keywords):
            return "code_display"
        
        # 音乐相关请求
        music_keywords = ["音乐", "歌", "歌曲", "歌单", "播放", "推荐音乐", "推荐"]
        if any(keyword in user_input_lower for keyword in music_keywords):
            return "music"
        
        # 旅游相关请求
        travel_keywords = ["旅游", "旅行", "攻略", "景点", "行程", "酒店", "机票"]
        if any(keyword in user_input_lower for keyword in travel_keywords):
            return "travel"
        
        # 笔记相关请求
        note_keywords = ["笔记", "记录", "备忘", "清单", "计划"]
        if any(keyword in user_input_lower for keyword in note_keywords):
            return "note"
        
        # 文件夹相关请求 - 只有明确说"创建文件夹"才识别
        if "创建文件夹" in user_input_lower or "新建文件夹" in user_input_lower:
            return "folder"
        
        return "unknown"
