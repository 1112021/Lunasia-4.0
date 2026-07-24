# -*- coding: utf-8 -*-
"""
TTS 管理器：支持 Azure TTS 与 Qwen3 TTS（通义）
"""

import threading
import queue
import time
from typing import Optional
import pygame
import tempfile
import os

from f5tts_client import F5TTSSidecarClient, ensure_managed_reference

try:
    import azure.cognitiveservices.speech as speechsdk
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False
    print("⚠️ Azure Speech SDK未安装，Azure TTS 将不可用")

try:
    import dashscope
    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False
    print("⚠️ dashscope 未安装，Qwen3 TTS 将不可用")

class TTSManager:
    """TTS 管理器，支持 Azure、Qwen3 与本地 F5-TTS sidecar。"""
    
    def __init__(
        self,
        azure_key: str = "",
        region: str = "eastasia",
        provider: str = "azure",
        dashscope_key: str = "",
        config: dict = None,
    ):
        self.config = dict(config or {})
        self.provider = provider or "azure"
        self.azure_key = azure_key
        self.region = region
        self.dashscope_key = (dashscope_key or "").strip()
        self.enabled = False
        self.voice_name = "zh-CN-XiaoxiaoNeural" if self.provider == "azure" else "Cherry"
        self.speech_config = None
        self.audio_queue = queue.Queue(maxsize=2)
        self.text_queue = queue.Queue(maxsize=2)
        self._producer_thread = None
        self._consumer_thread = None
        self._session_id = 0
        self._session_lock = threading.Lock()
        self._synthesis_lock = threading.Lock()
        self.is_playing = False
        self.stop_playback = False
        self.speaking_rate = float(
            self.config.get("tts_speaking_rate", 1.0)
        )
        self.f5_client = None
        self._fallback_manager = None
        
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
            self.audio_available = True
        except Exception as e:
            print(f"⚠️ 音频初始化失败: {e}")
            self.audio_available = False
        
        if self.provider == "f5tts":
            self._init_f5tts()
        elif self.provider == "qwen3":
            if DASHSCOPE_AVAILABLE and self.dashscope_key:
                self.enabled = True
                print(f"✅ Qwen3 TTS 配置成功 (语音: {self.voice_name})")
            else:
                if not self.dashscope_key:
                    print("ℹ️ 未配置 DashScope API 密钥，Qwen3 TTS 已禁用")
                self.enabled = False
        else:
            if AZURE_AVAILABLE and azure_key:
                self._init_azure_config()
    
    def _init_azure_config(self):
        """初始化Azure配置"""
        try:
            # 🔥 验证API密钥和区域
            if not self.azure_key or len(self.azure_key.strip()) == 0:
                print(f"❌ Azure TTS API密钥为空")
                self.enabled = False
                return
            
            if not self.region or len(self.region.strip()) == 0:
                print(f"❌ Azure TTS区域为空")
                self.enabled = False
                return
            
            self.speech_config = speechsdk.SpeechConfig(
                subscription=self.azure_key,
                region=self.region
            )
            if self.voice_name:
                self.speech_config.speech_synthesis_voice_name = self.voice_name
            print(f"🔍 [TTS配置] 语音名称: {self.voice_name}")
            self.speech_config.speech_synthesis_speaking_rate = 1.0
            
            # 🔥 不设置输出格式，使用默认格式（由AudioOutputConfig决定）
            # AudioOutputConfig会自动设置合适的格式
            
            self.enabled = True
            print(f"✅ Azure TTS配置成功 (区域: {self.region}, 语音: {self.voice_name})")
        except Exception as e:
            print(f"❌ Azure TTS配置失败: {e}")
            import traceback
            traceback.print_exc()
            self.enabled = False
    
    def _init_f5tts(self):
        """Initialize the lightweight client; model loading remains in sidecar."""
        try:
            managed = ensure_managed_reference(
                self.config.get("f5tts_ref_audio_source", ""),
                self.config.get(
                    "f5tts_ref_audio",
                    "assets/tts/user/lunasia_ref.wav",
                ),
            )
            if managed:
                self.config["f5tts_ref_audio"] = managed
            self.f5_client = F5TTSSidecarClient(self.config)
            self.enabled = bool(managed and self.audio_available)
            if (
                self.enabled
                and self.config.get("tts_enabled", False)
                and self.config.get(
                "f5tts_start_mode", "startup"
                ) == "startup"
            ):
                warmup = (
                    self.config.get("f5tts_residency_mode", "resident")
                    == "resident"
                )
                threading.Thread(
                    target=self._start_f5_background,
                    args=(warmup,),
                    daemon=True,
                ).start()
            elif not managed:
                print("⚠️ F5-TTS 参考音频不存在，等待在设置中选择")
        except Exception as exc:
            self.enabled = False
            print(f"⚠️ F5-TTS 客户端初始化失败: {exc}")

    def _start_f5_background(self, warmup=False):
        try:
            result = self.f5_client.ensure_started(warmup=warmup)
            if result.get("ok"):
                print("✅ F5-TTS sidecar 已就绪")
            else:
                print(f"⚠️ F5-TTS sidecar 启动失败: {result.get('error')}")
        except Exception as exc:
            print(f"⚠️ F5-TTS sidecar 启动失败: {exc}")

    def update_config(
        self,
        azure_key: str = "",
        region: str = "eastasia",
        provider: str = "azure",
        dashscope_key: str = "",
        config: dict = None,
    ):
        """更新 TTS 配置（支持 Azure / Qwen3 / F5-TTS）。"""
        old_provider = self.provider
        if config is not None:
            self.config = dict(config)
        self.provider = provider or "azure"
        self.azure_key = azure_key or ""
        self.region = region
        self.dashscope_key = (dashscope_key or "").strip()
        if old_provider == "f5tts" and self.provider != "f5tts" and self.f5_client:
            self.f5_client.shutdown()
            self.f5_client = None
        if self.provider == "f5tts":
            if self.f5_client is None:
                self._init_f5tts()
            else:
                self.f5_client.update_config(self.config)
                managed = ensure_managed_reference(
                    self.config.get("f5tts_ref_audio_source", ""),
                    self.config.get("f5tts_ref_audio", ""),
                )
                if managed:
                    self.config["f5tts_ref_audio"] = managed
                    self.f5_client.update_config(self.config)
                self.enabled = bool(managed and self.audio_available)
            if self.f5_client and not self.config.get("tts_enabled", False):
                self.f5_client.shutdown()
            elif (
                self.enabled
                and self.f5_client
                and self.config.get("f5tts_start_mode", "startup") == "startup"
            ):
                warmup = (
                    self.config.get("f5tts_residency_mode", "resident")
                    == "resident"
                )
                threading.Thread(
                    target=self._start_f5_background,
                    args=(warmup,),
                    daemon=True,
                ).start()
        elif self.provider == "qwen3":
            self.enabled = bool(DASHSCOPE_AVAILABLE and self.dashscope_key)
            if self.enabled:
                print(f"✅ Qwen3 TTS 配置已更新 (语音: {self.voice_name})")
        else:
            if self.azure_key:
                self._init_azure_config()
            else:
                self.enabled = False
    
    def set_voice(self, voice_name: str):
        """设置语音"""
        self.voice_name = voice_name
        if self.speech_config:
            self.speech_config.speech_synthesis_voice_name = voice_name
    
    def set_speaking_rate(self, rate: float):
        """设置语速 (0.5-2.0)"""
        self.speaking_rate = float(rate)
        self.config["tts_speaking_rate"] = self.speaking_rate
        if self.f5_client:
            self.f5_client.update_config(self.config)
        if self.speech_config:
            self.speech_config.speech_synthesis_speaking_rate = rate

    def _synthesize_f5tts(self, text: str) -> Optional[str]:
        if not self.f5_client:
            return None
        try:
            return self.f5_client.synthesize(text)
        except Exception as exc:
            print(f"⚠️ F5-TTS 合成失败: {exc}")
            return self._synthesize_fallback(text)

    def _synthesize_fallback(self, text: str) -> Optional[str]:
        if not self.config.get("f5tts_cloud_fallback_enabled", False):
            return None
        provider = self.config.get("f5tts_fallback_provider", "azure")
        if provider == "f5tts":
            return None
        try:
            if (
                self._fallback_manager is None
                or self._fallback_manager.provider != provider
            ):
                self._fallback_manager = TTSManager(
                    azure_key=self.config.get("azure_tts_key", ""),
                    region=self.config.get("azure_region", "eastasia"),
                    provider=provider,
                    dashscope_key=self.config.get("dashscope_key", ""),
                    config=self.config,
                )
                fallback_voice = (
                    "Cherry"
                    if provider == "qwen3"
                    else "zh-CN-XiaoxiaoNeural"
                )
                self._fallback_manager.set_voice(fallback_voice)
            return self._fallback_manager.synthesize_text(text)
        except Exception as exc:
            print(f"⚠️ F5-TTS 云端回退失败: {exc}")
            return None
    
    def _synthesize_qwen3(self, text: str) -> Optional[str]:
        """使用 Qwen3 TTS 合成，返回临时 wav 文件路径"""
        if not DASHSCOPE_AVAILABLE or not self.dashscope_key:
            return None
        import re
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s，。！？、；：""''（）【】《》·-]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        max_length = 500
        if len(text) > max_length:
            text = text[:max_length]
        if not text:
            return None
        temp_path = None
        try:
            response = dashscope.MultiModalConversation.call(
                model="qwen3-tts-flash",
                api_key=self.dashscope_key,
                text=text,
                voice=self.voice_name,
                stream=False
            )
            if not response or getattr(response, "status_code", 0) != 200:
                msg = getattr(response, "message", None) or str(response)
                print(f"⚠️ Qwen3 TTS 请求失败: {msg}")
                return None
            output = getattr(response, "output", None)
            if output is not None and not isinstance(output, dict):
                output = {"audio": getattr(output, "audio", None)}
            output = output or {}
            audio = output.get("audio")
            if audio is not None and not isinstance(audio, dict):
                audio = {"url": getattr(audio, "url", None), "data": getattr(audio, "data", None)}
            audio = audio or {}
            url = audio.get("url") or (getattr(audio, "url", None) if hasattr(audio, "url") else None)
            data_b64 = audio.get("data") or (getattr(audio, "data", None) if hasattr(audio, "data") else None)
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            temp_path = temp_file.name
            temp_file.close()
            if data_b64:
                import base64
                with open(temp_path, "wb") as f:
                    f.write(base64.b64decode(data_b64))
                return temp_path
            if url:
                try:
                    import urllib.request
                    urllib.request.urlretrieve(url, temp_path)
                    return temp_path
                except Exception as e:
                    print(f"⚠️ Qwen3 TTS 下载音频失败: {e}")
                    if os.path.exists(temp_path):
                        try:
                            os.unlink(temp_path)
                        except Exception:
                            pass
                    return None
            print("⚠️ Qwen3 TTS 返回无音频 url/data")
            return None
        except Exception as e:
            print(f"⚠️ Qwen3 TTS 合成异常: {e}")
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
            return None

    def synthesize_text(self, text: str) -> Optional[str]:
        """合成文本为音频文件"""
        if self.provider == "f5tts":
            return self._synthesize_f5tts(text)
        if self.provider == "qwen3":
            return self._synthesize_qwen3(text)
        if not self.enabled or not AZURE_AVAILABLE:
            return None
        original_preview = text[:50] if len(text) > 0 else ""
        
        # 🔥 清理文本，移除可能导致API错误的特殊字符
        # 移除或替换可能导致问题的字符
        import re
        # 先移除emoji和特殊符号（保留基本标点）
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s，。！？、；：""''（）【】《》·-]', '', text)
        # 移除多余空白
        text = re.sub(r'\s+', ' ', text).strip()
        
        # 限制文本长度
        max_length = 500
        if len(text) > max_length:
            text = text[:max_length]
        
        # 如果文本为空，返回None
        if not text or len(text.strip()) == 0:
            return None
        
        temp_file_path = None
        synthesizer = None
        audio_config = None
        
        try:
            # 创建临时音频文件
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
            temp_file_path = temp_file.name
            temp_file.close()
            
            # 使用内存输出，从result.audio_data直接获取数据
            abs_temp_path = os.path.abspath(temp_file_path)
            
            try:
                synthesizer = speechsdk.SpeechSynthesizer(
                    speech_config=self.speech_config
                )
            except Exception as config_error:
                print(f"❌ TTS配置失败: {config_error}")
                import traceback
                traceback.print_exc()
                if os.path.exists(temp_file_path):
                    try:
                        os.unlink(temp_file_path)
                    except:
                        pass
                return None
            
            # 执行TTS合成
            result = None
            try:
                result = synthesizer.speak_text(text)
                
                # 如果成功，从result.audio_data写入文件
                if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                    try:
                        audio_data = result.audio_data
                        if audio_data:
                            with open(abs_temp_path, 'wb') as audio_file:
                                audio_file.write(audio_data)
                            return abs_temp_path
                        else:
                            print(f"⚠️ TTS合成成功但audio_data为空")
                            return None
                    except Exception as write_error:
                        print(f"⚠️ TTS写入文件失败: {write_error}")
                        return None
                
            except Exception as timeout_error:
                print(f"⚠️ TTS合成过程异常: {timeout_error}")
                if synthesizer:
                    synthesizer = None
                if audio_config:
                    audio_config = None
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.unlink(temp_file_path)
                    except:
                        pass
                return None
            
            # 如果没有获取到结果，直接返回
            if result is None:
                print(f"⚠️ TTS合成未返回结果")
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.unlink(temp_file_path)
                    except:
                        pass
                return None
            
            # 检查结果
            try:
                if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                    return abs_temp_path
                elif result.reason == speechsdk.ResultReason.Canceled:
                    print(f"⚠️ TTS合成被取消")
                    if temp_file_path and os.path.exists(temp_file_path):
                        try:
                            os.unlink(temp_file_path)
                        except Exception:
                            pass
                    return None
                else:
                    print(f"⚠️ TTS合成失败: {result.reason}")
                    if temp_file_path and os.path.exists(temp_file_path):
                        try:
                            os.unlink(temp_file_path)
                        except:
                            pass
                    return None
            except Exception as result_error:
                print(f"⚠️ TTS合成过程异常: {result_error}")
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.unlink(temp_file_path)
                    except:
                        pass
                return None
                
        except Exception as e:
            print(f"⚠️ TTS合成异常: {e}")
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
            return None
        finally:
            # 确保资源释放
            try:
                if synthesizer:
                    synthesizer = None
                if audio_config:
                    audio_config = None
            except:
                pass
    
    def play_audio(self, audio_file: str):
        """播放音频文件"""
        if not self.audio_available:
            return
        
        try:
            # 停止当前播放
            if self.is_playing:
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()  # 🔥 关键：卸载当前音频
            
            # 播放新音频
            pygame.mixer.music.load(audio_file)
            pygame.mixer.music.play()
            self.is_playing = True
            
            # 等待播放完成
            while pygame.mixer.music.get_busy() and not self.stop_playback:
                time.sleep(0.1)
            
            self.is_playing = False
            
           
            pygame.mixer.music.unload()
            time.sleep(0.1)  # 等待文件句柄释放
            
            # 清理临时文件（带重试机制）
            max_retries = 5
            for i in range(max_retries):
                try:
                    if os.path.exists(audio_file):
                        os.unlink(audio_file)
                    break
                except PermissionError:
                    if i < max_retries - 1:
                        time.sleep(0.2)  # 等待后重试
                    else:
                        print(f"⚠️ 无法删除临时文件: {audio_file}，稍后系统会自动清理")
                except Exception as e:
                    print(f"⚠️ 删除临时文件失败: {e}")
                    break
                
        except Exception as e:
            print(f"❌ 音频播放失败: {e}")
            self.is_playing = False
        finally:
            # Covers load/play failures and cancellation as well as normal playback.
            try:
                if audio_file and os.path.exists(audio_file):
                    os.unlink(audio_file)
            except Exception:
                pass
    
    def _split_into_sentences(self, text: str, max_per_chunk: int = 500) -> list:
        """按句号、问号、感叹号、换行、分号切分为句子列表，单句过长时按长度再切分。"""
        import re
        # 按句末标点与换行分割，保留分隔符
        parts = re.split(r'([。！？\n；])', text)
        sentences = []
        for i in range(0, len(parts), 2):
            s = (parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")).strip()
            if not s:
                continue
            if len(s) <= max_per_chunk:
                sentences.append(s)
            else:
                # 单句过长：按逗号/空格或固定长度再切
                for j in range(0, len(s), max_per_chunk):
                    chunk = s[j:j + max_per_chunk].strip()
                    if chunk:
                        sentences.append(chunk)
        return sentences

    def _drain_queues(self):
        """清空文本队列和音频队列，并删除未播放的临时音频文件"""
        while True:
            try:
                item = self.audio_queue.get_nowait()
                p = item[1] if isinstance(item, tuple) else item
                if p and os.path.exists(p):
                    try:
                        os.unlink(p)
                    except Exception:
                        pass
            except queue.Empty:
                break
        while True:
            try:
                self.text_queue.get_nowait()
            except queue.Empty:
                break

    def _synthesize_one(self, text: str) -> list:
        """合成单句/单块，返回音频文件路径列表（长句可能拆成多段返回多路径）。"""
        if not text or not text.strip():
            return []
        s = text.strip()
        if self.provider == "f5tts":
            path = self._synthesize_f5tts(s)
            return [path] if path else []
        if self.provider == "qwen3":
            path = self._synthesize_qwen3(s)
            return [path] if path else []
        # Azure：单段上限 400
        max_len = 400
        if len(s) <= max_len:
            path = self.synthesize_text(s)
            return [path] if path else []
        chunks = self._split_into_sentences(s, max_per_chunk=max_len)
        paths = []
        for ch in chunks:
            if self.stop_playback:
                break
            path = self.synthesize_text(ch)
            if path:
                paths.append(path)
        return paths

    def _producer_loop(self):
        """生产者：从 text_queue 取句子，合成后放入 audio_queue，遇到 None 结束。"""
        while True:
            try:
                item = self.text_queue.get()
            except Exception:
                break
            if isinstance(item, tuple):
                session_id, s = item
            else:
                session_id, s = self._session_id, item
            if session_id != self._session_id:
                continue
            if s is None:
                self.audio_queue.put((session_id, None))
                return
            if self.stop_playback:
                self.audio_queue.put((session_id, None))
                return
            with self._synthesis_lock:
                paths = self._synthesize_one(s)
            for p in paths:
                if self.stop_playback or session_id != self._session_id:
                    try:
                        if p and os.path.exists(p):
                            os.unlink(p)
                    except Exception:
                        pass
                    break
                if p:
                    self.audio_queue.put((session_id, p))
        self.audio_queue.put((self._session_id, None))

    def _consumer_loop(self):
        """消费者：从 audio_queue 取路径播放，遇到 None 结束。"""
        while True:
            try:
                item = self.audio_queue.get()
            except Exception:
                break
            if isinstance(item, tuple):
                session_id, path = item
            else:
                session_id, path = self._session_id, item
            if path is None:
                return
            if self.stop_playback or session_id != self._session_id:
                try:
                    if path and os.path.exists(path):
                        os.unlink(path)
                except Exception:
                    pass
                continue
            self.play_audio(path)

    def _ensure_worker_started(self):
        """确保生产者、消费者线程已启动（若已结束则重新启动）。"""
        if self._producer_thread is None or not self._producer_thread.is_alive():
            self._producer_thread = threading.Thread(
                target=self._producer_loop, daemon=True
            )
            self._producer_thread.start()
        if self._consumer_thread is None or not self._consumer_thread.is_alive():
            self._consumer_thread = threading.Thread(
                target=self._consumer_loop, daemon=True
            )
            self._consumer_thread.start()

    def _new_session(self):
        with self._session_lock:
            self._session_id += 1
            return self._session_id

    def speak_text(self, text: str):
        """文本转语音并播放（生产者-消费者：播当前句时预合成下一句，减少句间空隙）。"""
        if not self.enabled:
            return
        import re
        clean = re.sub(r'[（\(].*?[）\)]', '', text)
        clean = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s，。！？、；：""''（）【】《》·-]', '', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        if not clean:
            return
        max_chunk = 300 if self.provider == "f5tts" else (
            500 if self.provider == "qwen3" else 400
        )
        sentences = self._split_into_sentences(clean, max_per_chunk=max_chunk)
        if not sentences:
            return
        self.stop_playback = False
        self._drain_queues()
        session_id = self._new_session()
        self._ensure_worker_started()
        for s in sentences:
            self.text_queue.put((session_id, s))
        self.text_queue.put((session_id, None))

    def start_tts_stream(self):
        """开始流式 TTS：清空队列，准备接收逐句推送。"""
        self.stop_playback = False
        self._drain_queues()
        self._new_session()
        self._ensure_worker_started()

    def enqueue_sentence(self, sentence: str):
        """流式模式下推送一句完整句子（会立即进入合成队列，可与播放并行）。"""
        if not self.enabled:
            return
        s = (sentence or "").strip()
        if not s:
            return
        self.text_queue.put((self._session_id, s))
        self._ensure_worker_started()

    def end_tts_stream(self, remaining: str = ""):
        """结束流式 TTS：可传入剩余未成句的文本一并合成播放。"""
        if not self.enabled:
            return
        if (remaining or "").strip():
            self.text_queue.put((self._session_id, remaining.strip()))
        self.text_queue.put((self._session_id, None))
        self._ensure_worker_started()
    
    def stop_speaking(self):
        """停止当前播放（并通知生产者/消费者线程结束）"""
        self.stop_playback = True
        self._new_session()
        if self.f5_client:
            self.f5_client.cancel()
        self._drain_queues()
        try:
            self.text_queue.put_nowait(
                (self._session_id, None)
            )  # 让生产者从 get 返回并退出
        except queue.Full:
            pass
        if self.is_playing:
            pygame.mixer.music.stop()
            self.is_playing = False
    
    def get_available_voices(self) -> list:
        """获取当前引擎可用音色列表 (voice_id, 显示名)"""
        if self.provider == "qwen3":
            return [
                ("Cherry", "Cherry 女声"),
                ("Ethan", "Ethan 男声"),
                ("Chelsie", "Chelsie 女声"),
                ("Serena", "Serena 女声"),
                ("Dylan", "Dylan 北京话男声"),
                ("Jada", "Jada 上海话女声"),
                ("Sunny", "Sunny 四川话男声"),
            ]
        return [
            ("zh-CN-XiaoxiaoNeural", "晓晓 (推荐)"),
            ("zh-CN-XiaoyiNeural", "晓伊"),
            ("zh-CN-YunxiNeural", "云希"),
            ("zh-CN-YunyangNeural", "云扬"),
            ("zh-CN-XiaochenNeural", "晓辰"),
            ("zh-CN-XiaohanNeural", "晓涵"),
            ("zh-CN-XiaomoNeural", "晓墨"),
            ("zh-CN-XiaoxuanNeural", "晓萱"),
            ("zh-CN-XiaoyanNeural", "晓颜"),
            ("zh-CN-XiaoyouNeural", "晓悠"),
        ]

    def is_available(self) -> bool:
        """检查 TTS 是否可用"""
        if self.provider == "f5tts":
            return self.enabled and self.f5_client is not None and self.audio_available
        if self.provider == "qwen3":
            return self.enabled and DASHSCOPE_AVAILABLE and self.audio_available
        return self.enabled and AZURE_AVAILABLE and self.audio_available

    def test_tts(self, text: str = "你好，这是露尼西亚的TTS测试") -> str:
        """测试 TTS：合成并播放一段话，返回结果说明"""
        if not self.is_available():
            return "TTS 不可用，请检查密钥与引擎配置"
        audio_file = self.synthesize_text(text)
        if not audio_file:
            return "TTS 合成失败，请检查网络或密钥"
        self.play_audio(audio_file)
        return "TTS 测试播放完成"
    
    def cleanup(self):
        """清理资源"""
        self.stop_speaking()
        if self.f5_client:
            self.f5_client.shutdown()
        if self._fallback_manager:
            self._fallback_manager.cleanup()
        for worker in (self._producer_thread, self._consumer_thread):
            if (
                worker is not None
                and worker.is_alive()
                and worker is not threading.current_thread()
            ):
                worker.join(timeout=1.0)
        try:
            pygame.mixer.quit()
        except:
            pass
