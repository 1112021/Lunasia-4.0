# -*- coding: utf-8 -*-
"""
语音输入模块：录音 + 阿里 DashScope Paraformer 8k-v2 识别
长按麦克风录音，松开后识别并返回文本。
"""

import os
import tempfile
import threading
import wave

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
    FORMAT_PA = pyaudio.paInt16
except ImportError:
    PYAUDIO_AVAILABLE = False
    FORMAT_PA = None

try:
    from http import HTTPStatus
    from dashscope.audio.asr import Recognition
    import dashscope
    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False

# 8k-v2 仅支持 8kHz
SAMPLE_RATE = 8000
CHANNELS = 1
# 较小块便于松开后尽快退出录音循环（约 0.1 秒内响应）
CHUNK = 800


def record_to_wav(stop_event):
    """
    从麦克风录音，保存为 8kHz 单声道 wav 临时文件。
    调用方在「松开」时 set(stop_event)，本函数在检测到后停止录音并返回。
    :param stop_event: threading.Event，set() 时停止录音
    :return: (temp_wav_path, error_message). 成功时 error_message 为 None。
    """
    if not PYAUDIO_AVAILABLE:
        return None, "未安装 pyaudio，无法录音"
    if FORMAT_PA is None:
        return None, "pyaudio 格式不可用"

    pa = pyaudio.PyAudio()
    stream = None
    try:
        stream = pa.open(
            format=FORMAT_PA,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )
    except Exception as e:
        pa.terminate()
        return None, "打开麦克风失败: " + str(e)

    frames = []
    while not stop_event.is_set():
        try:
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
        except Exception:
            break
    try:
        stream.stop_stream()
        stream.close()
    except Exception:
        pass
    pa.terminate()

    if not frames:
        return None, "未录到音频"

    # 写入临时 wav（8kHz, 16bit, mono）
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wav_path = f.name
    f.close()
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # 16bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b"".join(frames))
    return wav_path, None


def recognize_wav(wav_path, api_key=None):
    """
    使用 DashScope Paraformer 8k-v2 识别 wav 文件。
    :param wav_path: 本地 wav 路径，8kHz 单声道
    :param api_key: DashScope API Key，None 时使用环境变量 DASHSCOPE_API_KEY
    :return: (text, error_message). 成功时 error_message 为 None。
    """
    if not DASHSCOPE_AVAILABLE:
        return "", "未安装 dashscope，无法进行语音识别"
    if api_key:
        dashscope.api_key = api_key
    elif not os.environ.get("DASHSCOPE_API_KEY") and not getattr(dashscope, "api_key", None):
        return "", "请先在设置中配置语音识别 API 密钥 (DashScope)。在「设置」→「API 设置」中填写「语音识别 API 密钥 (DashScope)」。"

    try:
        recognition = Recognition(
            model="paraformer-realtime-8k-v2",
            format="wav",
            sample_rate=SAMPLE_RATE,
            callback=None,
        )
        result = recognition.call(wav_path)
    except Exception as e:
        return "", "识别异常: " + str(e)

    if result.status_code != HTTPStatus.OK:
        msg = getattr(result, "message", None) or str(result)
        return "", "识别失败: " + msg

    sentence = result.get_sentence()
    text = ""
    if isinstance(sentence, list):
        texts = [s.get("text", "") for s in sentence if isinstance(s, dict) and s.get("text")]
        text = "".join(texts).strip()
    elif isinstance(sentence, dict) and sentence.get("text"):
        text = sentence["text"].strip()
    elif isinstance(sentence, str):
        text = sentence.strip()
    else:
        # 兼容：部分版本可能通过 result.output 等返回
        output = getattr(result, "output", None)
        if isinstance(output, dict) and output.get("text"):
            text = output["text"].strip()
        elif isinstance(output, str):
            text = output.strip()
    return text, None


def is_voice_input_available():
    """语音输入是否可用（依赖已安装且可录音）。"""
    return PYAUDIO_AVAILABLE and DASHSCOPE_AVAILABLE
