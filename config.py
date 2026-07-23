# -*- coding: utf-8 -*-
"""
配置管理模块
处理应用程序的配置加载、保存和默认配置
"""

import json
import os

# 配置文件路径
CONFIG_FILE = "ai_agent_config.json"

def load_config():
    """加载配置"""
    default_config = {
        "openai_key": "",
        "deepseek_key": "",
        "qwen3vl_plus_key": "",  # 兼容旧配置；视觉密钥见 vision_dashscope_api_key
        "vision_dashscope_api_key": "",
        "vision_dashscope_screen_model": "qwen3-omni-flash",
        "vision_dashscope_image_model": "qwen-vl-plus",
        "vision_dashscope_video_model": "qwen-vl-plus",
        "vision_screen_model": {"backend": "dashscope", "provider": "dashscope", "model_id": "qwen3-omni-flash"},
        "vision_image_model": {"backend": "dashscope", "provider": "dashscope", "model_id": "qwen-vl-plus"},
        "vision_video_model": {"backend": "dashscope", "provider": "dashscope", "model_id": "qwen-vl-plus"},
        "vision_custom_fallback_to_dashscope": True,
        "vision_multi_image_batch_max_mb": 4,
        "combined_send_file_extract_max_chars": 18000,
        "custom_fail_fallback_to_cloud": False,
        "custom_model_on_delete": "block_until_reselect",
        "custom_models": [],
        "dashscope_key": "",  # 阿里 DashScope API 密钥（用于语音识别 Paraformer 8k-v2）
        "voice_auto_send": False,  # 语音识别结束后是否自动发送消息
        "weather_key": "",
        "heweather_key": "",
        "amap_key": "",  # 用户需要在设置中配置自己的API密钥
        "weather_source": "高德地图API",
        "default_browser": "",  # 默认浏览器
        "default_search_engine": "baidu",  # 默认搜索引擎
        "selected_model": "deepseek-v4-flash",
        "memory_summary_model": "deepseek-v4-flash",  # 识底深湖总结使用的模型
        "max_tokens": 1000,  # AI最大token数，0表示无限制
        "enable_stream_display": False,  # 启用回复流式显示，体感更快
        "workflow_auto_collapse": True,  # 回复完成后自动折叠工作流程
        "window_transparency": 100,  # 窗口透明度，100表示完全不透明
        # 关闭主窗口：exit=直接退出；tray=隐藏到系统托盘（点 _ 最小化仍到任务栏，行为不变）
        "close_main_window_action": "exit",
        # 托盘驻留时是否保留全局快捷键（默认 False：进托盘后卸掉 hook，恢复窗口时再挂载）
        "tray_keep_global_shortcuts": False,
        # 开机自启动（Windows 启动文件夹 Lunasia.lnk）：off | normal | tray
        "startup_mode": "off",
        # 自启动时是否用 pythonw 隐藏控制台（无 pythonw 时自动退回 python）
        "startup_hide_console": False,
        # 运行日志（logs/YYYY-MM-DD.txt）
        "file_log_enabled": True,
        "file_log_dir": "",  # 留空=项目根/logs
        "file_log_retention_days": 0,  # 0=不自动删除
        "show_remember_details": True,  # 是否显示"记住这个时刻"的详细信息
        "note_filename_format": "timestamp",  # 笔记文件名格式：timestamp(时间戳格式) 或 simple(简单格式)
        "max_memory_recall": 12,  # 智能回忆最大加载轮数（必须是3的倍数）
        # 上下文联系及短期记忆轻量化增强
        "context_link_short_term_enabled": False,
        "session_context_rounds": 15,
        "memory_score_agent_model": "deepseek-v4-flash",
        "context_link_agent_slots": 15,
        "memory_recall_ai_pool_cap": 60,
        "memory_recall_candidate_pool": 25,
        "context_link_snippet_max_chars": 400,
        "context_link_agent_preview_chars": 100,
        # 识底深湖：普通聊天「未压缩原文」条数上限（外部事件/待办链不计入、不参与压缩）
        "memory_max_full_topics": 80,
        # 每次启动超出上限时，最多自动压缩多少条（避免启动过久）
        "memory_compress_batch_per_startup": 40,
        # 智能回忆各维最低相关度（放宽回忆）
        "memory_recall_content_score_min": 0.12,
        "memory_recall_location_score_min": 0.22,
        "memory_recall_time_score_min": 0.12,
        "memory_recall_causal_score_min": 0.22,
        # 向量回忆 / 四维度回忆 / 上下文联系是否包含待办事件与待办链（默认关闭）
        "memory_include_todo_events": False,
        # TTS设置
        "tts_enabled": False,  # 是否启用TTS
        "tts_provider": "azure",  # 引擎: azure | qwen3 | f5tts
        "azure_tts_key": "",  # Azure TTS API密钥
        "azure_region": "eastasia",  # Azure区域
        "tts_voice": "zh-CN-XiaoxiaoNeural",  # 语音（Azure 为 Neural 名，Qwen3 为 Cherry 等）
        "tts_speaking_rate": 1.0,  # TTS语速
        "tts_stop_key_sequence": "escape",  # 打断TTS播放的快捷键（留空则禁用）
        # 本地 F5-TTS sidecar
        "f5tts_base_url": "http://127.0.0.1:18765",
        "f5tts_python_path": "tools/f5tts_env/Scripts/python.exe",
        "f5tts_start_mode": "startup",  # startup | on_demand
        "f5tts_residency_mode": "resident",  # resident | idle_unload
        "f5tts_idle_unload_minutes": 10,
        "f5tts_model": "F5TTS_v1_Base",
        "f5tts_device": "cuda",
        "f5tts_cpu_fallback_enabled": True,
        "f5tts_nfe_step": 32,
        "f5tts_cfg_strength": 2.0,
        "f5tts_ref_audio_source": "",
        "f5tts_ref_audio": "assets/tts/lunasia_ref.wav",
        "f5tts_ref_text": "",
        "f5tts_default_ref_audio_source": "",
        "f5tts_default_ref_audio": "assets/tts/lunasia_ref.wav",
        "f5tts_default_ref_text": "",
        "f5tts_cloud_fallback_enabled": False,
        "f5tts_fallback_provider": "azure",
        "f5tts_pause_for_vision": True,
        "f5tts_result_inline_max_bytes": 1048576,
        "f5tts_temp_ttl_minutes": 30,
        "f5tts_temp_scan_minutes": 5,
        "f5tts_cache_max_items": 24,
        "ai_fallback_enabled": True,  # 是否启用AI智能创建的后备机制（关键词识别）
        # 快捷键设置
        "send_key_sequence": "ctrl+enter",  # 发送消息快捷键（keyboard库格式，如 "ctrl+enter", "enter"）
        "show_window_key_sequence": "ctrl+shift+l",  # 窗口呼出快捷键（keyboard库格式）
        "voice_input_key_sequence": "",  # 语音输入快捷键（按住说话，松开结束；留空则禁用）
        "screenshot_allowed": True,  # 是否允许截屏/读屏（隐私页面可关闭）
        "screenshot_toggle_key_sequence": "ctrl+shift+s",  # 开关截图许可的快捷键（留空则禁用）
        # 待办与通讯
        "todo_default_email": "",
        "todo_timezone": "",  # 留空表示跟随系统时区
        "todo_default_lead_minutes": 10,
        "todo_min_trigger_seconds": 30,
        "todo_retention_days": 7,
        "todo_retry_max": 3,
        "todo_db_path": "todo_tasks.db",
        "todo_poll_interval_seconds": 2,
        "todo_email_model": "deepseek-v4-flash",
        "todo_email_style": "concise",
        "todo_time_parse_model": "",
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "smtp_username": "",
        "smtp_password": "",  # QQ邮箱授权码
        "website_map": {
            "哔哩哔哩": "https://www.bilibili.com",
            "b站": "https://www.bilibili.com",
            "百度": "https://www.baidu.com",
            "谷歌": "https://www.google.com",
            "知乎": "https://www.zhihu.com",
            "github": "https://github.com",
            "youtube": "https://www.youtube.com"
        },
        "app_map": {},
        # 联网检索（新流水线）
        "enable_web_search": False,
        "search_method": "Playwright",
        "search_engine": "Bing",
        "max_search_questions": 3,
        "serp_results_per_query": 5,
        "max_pages_to_browse": 2,
        "max_search_context_chars": 8000,
        "search_intent_model": "deepseek-v4-flash",
        "security_intent_model": "deepseek-v4-flash",
        "search_rerank_model": "deepseek-v4-flash",
        "max_search_results": 12,
        "browse_result_count": 3,
        # 混合 LLM（见 docs/llm_hybrid_spec.md）
        "llm_mode": "hybrid",
        "cloud_provider": "DeepSeek",
        "llm_provider": "DeepSeek",
        "local_fail_fallback_to_cloud": False,
        "local_preload_on_startup": False,
        "custom_fail_fallback_to_cloud": False,
        "ollama_url": "http://localhost:11434",
        "ollama_model": "qwen2.5:latest",
        "ollama": {
            "enabled": False,
            "base_url": "http://localhost:11434",
            "api_key": "",
        },
        "lmstudio": {
            "enabled": False,
            "base_url": "http://localhost:1234",
            "api_key": "",
        },
        "framework_plan_model": "deepseek-v4-flash",
        "webpage_agent_model": "deepseek-v4-flash",
        "cloud_fallback_model": "deepseek-v4-flash",
    }

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 向后兼容：如果配置中没有 send_key_sequence，从 send_key_mode 推断
                if "send_key_sequence" not in config and "send_key_mode" in config:
                    send_key_mode = config.get("send_key_mode", "Ctrl+Enter")
                    if send_key_mode == "Enter":
                        config["send_key_sequence"] = "enter"
                    else:
                        config["send_key_sequence"] = "ctrl+enter"
                # 向后兼容：如果配置中没有 show_window_key_sequence，使用默认值
                if "show_window_key_sequence" not in config:
                    config["show_window_key_sequence"] = "ctrl+shift+l"
                if "tts_stop_key_sequence" not in config:
                    config["tts_stop_key_sequence"] = "escape"
                for key in (
                    "f5tts_base_url", "f5tts_python_path", "f5tts_start_mode",
                    "f5tts_residency_mode", "f5tts_idle_unload_minutes",
                    "f5tts_model", "f5tts_device", "f5tts_nfe_step",
                    "f5tts_cpu_fallback_enabled",
                    "f5tts_cfg_strength", "f5tts_ref_audio_source",
                    "f5tts_default_ref_audio_source",
                    "f5tts_ref_audio", "f5tts_default_ref_audio",
                    "f5tts_cloud_fallback_enabled", "f5tts_fallback_provider",
                    "f5tts_pause_for_vision", "f5tts_result_inline_max_bytes",
                    "f5tts_temp_ttl_minutes", "f5tts_temp_scan_minutes",
                    "f5tts_cache_max_items",
                ):
                    if key not in config:
                        config[key] = default_config[key]
                config.setdefault("f5tts_ref_text", "")
                config.setdefault("f5tts_default_ref_text", "")
                if config.get("tts_provider") in {"f5", "f5-tts", "F5-TTS"}:
                    config["tts_provider"] = "f5tts"
                if config.get("f5tts_start_mode") not in {
                    "startup", "on_demand"
                }:
                    config["f5tts_start_mode"] = "startup"
                if config.get("f5tts_residency_mode") not in {
                    "resident", "idle_unload"
                }:
                    config["f5tts_residency_mode"] = "resident"
                if config.get("f5tts_device") not in {"cuda", "cpu"}:
                    config["f5tts_device"] = "cuda"
                try:
                    config["f5tts_idle_unload_minutes"] = max(
                        1,
                        min(
                            60,
                            int(config["f5tts_idle_unload_minutes"]),
                        ),
                    )
                    config["f5tts_nfe_step"] = max(
                        8, min(64, int(config["f5tts_nfe_step"]))
                    )
                except (TypeError, ValueError):
                    config["f5tts_idle_unload_minutes"] = 10
                    config["f5tts_nfe_step"] = 32
                if "screenshot_allowed" not in config:
                    config["screenshot_allowed"] = True
                if "screenshot_toggle_key_sequence" not in config:
                    config["screenshot_toggle_key_sequence"] = "ctrl+shift+s"
                if "memory_max_full_topics" not in config:
                    config["memory_max_full_topics"] = 80
                if "memory_compress_batch_per_startup" not in config:
                    config["memory_compress_batch_per_startup"] = 40
                if "memory_recall_content_score_min" not in config:
                    config["memory_recall_content_score_min"] = 0.12
                if "memory_recall_location_score_min" not in config:
                    config["memory_recall_location_score_min"] = 0.22
                if "memory_recall_time_score_min" not in config:
                    config["memory_recall_time_score_min"] = 0.12
                if "memory_recall_causal_score_min" not in config:
                    config["memory_recall_causal_score_min"] = 0.22
                if "close_main_window_action" not in config:
                    config["close_main_window_action"] = "exit"
                if "tray_keep_global_shortcuts" not in config:
                    config["tray_keep_global_shortcuts"] = False
                if "startup_mode" not in config:
                    config["startup_mode"] = "off"
                if "startup_hide_console" not in config:
                    config["startup_hide_console"] = False
                if "file_log_enabled" not in config:
                    config["file_log_enabled"] = True
                if "file_log_dir" not in config:
                    config["file_log_dir"] = ""
                if "file_log_retention_days" not in config:
                    config["file_log_retention_days"] = 0
                if "context_link_short_term_enabled" not in config:
                    config["context_link_short_term_enabled"] = False
                if "session_context_rounds" not in config:
                    config["session_context_rounds"] = 15
                if "memory_score_agent_model" not in config:
                    config["memory_score_agent_model"] = "deepseek-v4-flash"
                if "context_link_agent_slots" not in config:
                    config["context_link_agent_slots"] = config.get(
                        "memory_recall_final_k", config.get("max_memory_recall", 15)
                    )
                if "memory_recall_ai_pool_cap" not in config:
                    config["memory_recall_ai_pool_cap"] = 60
                if "memory_recall_candidate_pool" not in config:
                    config["memory_recall_candidate_pool"] = 25
                if "memory_include_todo_events" not in config:
                    config["memory_include_todo_events"] = False
                if "context_link_snippet_max_chars" not in config:
                    config["context_link_snippet_max_chars"] = 400
                if "context_link_agent_preview_chars" not in config:
                    config["context_link_agent_preview_chars"] = 100
                if "workflow_auto_collapse" not in config:
                    config["workflow_auto_collapse"] = True
                _migrate_search_config(config)
                from llm_spec import migrate_config_llm
                migrate_config_llm(config)
                return config
        except:
            from llm_spec import migrate_config_llm
            migrate_config_llm(default_config)
            return default_config
    from llm_spec import migrate_config_llm
    migrate_config_llm(default_config)
    return default_config


def _migrate_search_config(config: dict) -> None:
    """旧搜索配置键迁移到新语义。"""
    if "max_pages_to_browse" not in config and "browse_result_count" in config:
        try:
            config["max_pages_to_browse"] = int(config["browse_result_count"])
        except (TypeError, ValueError):
            config["max_pages_to_browse"] = 2
    if "serp_results_per_query" not in config and "max_search_results" in config:
        try:
            mq = max(1, int(config.get("max_search_questions", 3)))
            total = int(config["max_search_results"])
            config["serp_results_per_query"] = max(3, min(10, total // mq))
        except (TypeError, ValueError):
            config["serp_results_per_query"] = 5
    if "search_rerank_model" not in config:
        config["search_rerank_model"] = config.get(
            "search_intent_model", "deepseek-v4-flash"
        )
    if "max_search_context_chars" not in config:
        config["max_search_context_chars"] = 8000

def save_config(config):
    """保存配置"""
    temp_path = CONFIG_FILE + ".tmp"
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, CONFIG_FILE)
