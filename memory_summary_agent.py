# -*- coding: utf-8 -*-
"""
记忆总结AI代理 - 纯AI版本
专门用于生成高质量的识底深湖总结，不使用关键词检测
"""

import openai
import json
import re
from typing import List, Dict, Optional
import concurrent.futures

from llm_router import chat_completion_create
from llm_spec import get_config_spec

class MemorySummaryAgent:
    """记忆总结AI代理 - 纯AI版本"""
    
    def __init__(self, config: Dict):
        self.config = config
        self._apply_config(config)

    def refresh_from_config(self, config: Dict) -> None:
        """设置保存后与主 Agent 配置同步。"""
        self._apply_config(config)

    def _apply_config(self, config: Dict) -> None:
        self.config = config
        self.model_spec = get_config_spec(config, "memory_summary_model")
        self.model = self.model_spec.model_id

    def _chat(self, messages: list, max_tokens: int = 200, temperature: float = 0.3, timeout: float = 240):
        return chat_completion_create(
            self.config,
            config_key="memory_summary_model",
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            task_label="memory_summary",
        )
        
    def summarize_topic(self, conversation_text: str) -> str:
        """🚀 总结对话主题 - 纯AI方式"""
        max_retries = 5  # 增加重试次数，确保AI能够成功
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                print(f"🔧 开始AI主题总结，模型: {self.model_spec.display_name()} (第{attempt + 1}次尝试)")
                
                # 🚀 修复：提取指挥官的言论，用于主题分析
                commander_quotes = self._extract_commander_quotes(conversation_text)
                print(f"🔧 提取到指挥官言论: {commander_quotes}")
                
                # 🔥 修复：改进prompt，不要列出所有主题类型，让AI根据实际内容总结
                prompt = f"""请分析以下对话内容，总结出准确的主题，要求：
1. 仔细阅读对话内容，识别实际讨论的主要话题
2. 主题要具体准确，反映实际对话内容
3. 如果是图片分析，主题应该是"图片分析"或"图像识别"
4. 如果是文件上传，主题应该是"文件分析"或相关文件类型
5. 如果是编程相关，主题应该包含编程语言或技术名称
6. 如果是其他类型，根据实际内容总结
7. 主题控制在50字以内，简洁明了
8. 只总结实际讨论的内容，不要添加未涉及的话题
9. 如果对话涉及多个主题，用顿号分隔，但不要超过3个主要主题

对话内容：
{commander_quotes}

请直接输出主题，不要添加其他说明："""
                
                print(f"🔧 发送API请求，超时时间: 240秒")
                # 🔥 修复：每次重试时增加temperature，避免缓存导致相同结果
                temperature = 0.3 + (attempt * 0.1)  # 每次重试增加随机性
                response = self._chat(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=200,
                    temperature=temperature,
                    timeout=240,
                )
                
                print(f"🔧 API响应对象: {response}")
                print(f"🔧 响应选择: {response.choices}")
                if response.choices:
                    print(f"🔧 第一个选择: {response.choices[0]}")
                    print(f"🔧 消息内容: {response.choices[0].message}")
                    
                    # 检查是否有主要内容
                    result = response.choices[0].message.content.strip()
                    print(f"🔧 API响应主要内容: '{result}' (长度: {len(result)})")
                    
                    # 🚀 修复：如果没有主要内容，尝试从推理内容中提取
                    if not result and hasattr(response.choices[0].message, 'reasoning_content'):
                        reasoning = response.choices[0].message.reasoning_content
                        print(f"🔧 推理内容: {reasoning[:200]}...")
                        
                        # 🚀 修复：如果推理内容也不完整，重新调用AI
                        if len(reasoning) < 100:  # 推理内容太短，可能不完整
                            print(f"🔧 推理内容不完整，重新调用AI...")
                            continue  # 继续下一次重试
                        
                        # 🚀 修复：智能分析推理内容，提取主题
                        extracted_topic = self._extract_topic_from_reasoning(reasoning)
                        if extracted_topic:
                            print(f"🔧 从推理内容提取主题: {extracted_topic}")
                            return extracted_topic
                        else:
                            print(f"🔧 从推理内容无法提取主题，重新调用AI...")
                            continue  # 继续下一次重试
                    
                    # 🚀 修复：如果推理内容也没有，尝试从完整响应中提取
                    if not result:
                        print(f"🔧 尝试从完整响应中提取主题...")
                        full_response = str(response.choices[0].message)
                        extracted_topic = self._extract_topic_from_full_response(full_response)
                        if extracted_topic:
                            print(f"🔧 从完整响应提取主题: {extracted_topic}")
                            return extracted_topic
                        else:
                            print(f"🔧 从完整响应无法提取主题，重新调用AI...")
                            continue  # 继续下一次重试
                    
                    # 🔥 修复：放宽验证逻辑，允许更长的主题（最多60字）
                    # 同时检查是否是AI直接返回了主题列表
                    if result:
                        # 检查是否是直接返回了所有主题类型的列表
                        common_topics = ["音乐推荐", "国家介绍", "文章写作", "天气查询", "编程代码", 
                                       "自我介绍", "城市介绍", "出行建议", "文件保存", "技术解释", "历史介绍"]
                        topic_count = sum(1 for topic in common_topics if topic in result)
                        
                        # 如果包含了超过5个常见主题，说明AI直接返回了列表，需要重新生成
                        if topic_count > 5:
                            print(f"⚠️ AI返回了主题列表而非实际主题（包含{topic_count}个常见主题），重新调用AI...")
                            continue
                        
                        # 🔥 修复：放宽长度限制到60字符
                        if len(result) >= 2 and len(result) <= 60:
                            print(f"✅ AI成功生成主题: {result}")
                            return result
                        else:
                            print(f"⚠️ AI生成的主题长度不合理: '{result}' (长度: {len(result)})，重新调用AI...")
                            continue
                    else:
                        print(f"⚠️ AI返回空结果，重新调用AI...")
                        continue
                else:
                    print(f"⚠️ API响应没有选择")
                    continue  # 继续下一次重试
                    
            except Exception as e:
                print(f"⚠️ AI主题总结失败 (第{attempt + 1}次): {str(e)}")
                if attempt < max_retries - 1:
                    print(f"🔄 等待{retry_delay}秒后重试...")
                    import time
                    time.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
                else:
                    print(f"❌ AI主题总结最终失败，返回默认值")
                    # 🔥 修复：根据实际对话内容生成默认主题
                    if "图片" in conversation_text or "图像" in conversation_text:
                        return "图片分析"
                    elif "文件" in conversation_text:
                        return "文件分析"
                    else:
                        return "多项讨论"
        
        # 🔥 修复：最终fallback也根据内容判断
        if "图片" in conversation_text or "图像" in conversation_text:
            return "图片分析"
        elif "文件" in conversation_text:
            return "文件分析"
        else:
            return "多项讨论"
    
    def _extract_commander_quotes(self, conversation_text: str) -> str:
        """🚀 提取指挥官的言论，用于主题分析"""
        try:
            lines = conversation_text.strip().split('\n')
            commander_quotes = []
            
            for line in lines:
                line = line.strip()
                if line.startswith('指挥官:'):
                    # 提取指挥官的问题/请求
                    quote = line.replace('指挥官:', '').strip()
                    if quote:
                        commander_quotes.append(quote)
            
            if commander_quotes:
                return '\n'.join(commander_quotes)
            else:
                # 如果没有找到指挥官言论，返回原始对话内容
                return conversation_text
                
        except Exception as e:
            print(f"⚠️ 提取指挥官言论失败: {str(e)}")
            return conversation_text
    
    def _extract_topic_from_reasoning(self, reasoning: str) -> str:
        """🚀 从推理内容中智能提取主题 - 纯AI方式"""
        try:
            # 🚀 修复：不再使用关键词检测，而是分析推理内容的语义
            # 让AI重新尝试，而不是fallback到关键词
            print(f"🔧 推理内容不完整，需要重新调用AI")
            return None  # 返回None，触发重新调用AI
            
        except Exception as e:
            print(f"⚠️ 从推理内容提取主题失败: {str(e)}")
            return None  # 返回None，触发重新调用AI
    
    def _extract_topic_from_full_response(self, full_response: str) -> str:
        """🚀 从完整响应中提取主题 - 纯AI方式"""
        try:
            # 🚀 修复：不再使用关键词检测，而是分析完整响应的语义
            # 让AI重新尝试，而不是fallback到关键词
            print(f"🔧 完整响应不完整，需要重新调用AI")
            return None  # 返回None，触发重新调用AI
            
        except Exception as e:
            print(f"⚠️ 从完整响应提取主题失败: {str(e)}")
            return None  # 返回None，触发重新调用AI
    
    def summarize_context(self, conversation_text: str) -> str:
        """🚀 总结上下文摘要 - 纯AI方式"""
        max_retries = 5  # 增加重试次数，确保AI能够成功
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                print(f"🔧 开始AI上下文总结 (第{attempt + 1}次)")
                
                prompt = f"""请分析以下对话内容，生成简洁的上下文摘要，要求：
1. 按时间顺序总结每轮对话的主要内容
2. 保留关键信息（如音乐名称、国家名称、具体内容等）
3. 使用简洁的语言，控制在80-150字以内
4. 要准确反映实际对话内容，不要添加不存在的信息
5. 如果是音乐推荐，要包含具体的歌曲名和艺术家
6. 如果是国家介绍，要包含国家名称、地理位置、首都等关键信息
7. 如果是游记写作，要包含地点和内容概要
8. 如果是天气查询，要包含具体天气数据
9. 如果是编程代码，要包含编程语言和项目类型
10. 如果是城市介绍，要包含城市名称、国家、地理位置、主要景点等关键信息
11. 如果是技术解释，要包含技术名称、核心概念、应用场景等关键信息
12. 总结要连贯流畅，体现对话的逻辑关系
13. 要具体准确，避免泛泛而谈

对话内容：
{conversation_text}

上下文摘要："""
                
                response = self._chat(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=800,
                    temperature=0.3,
                    timeout=240,
                )
                
                if response.choices:
                    result = response.choices[0].message.content.strip()
                    print(f"🔧 上下文总结API响应: '{result}' (长度: {len(result)})")
                    
                    # 🚀 修复：如果没有主要内容，尝试从推理内容中提取
                    if not result and hasattr(response.choices[0].message, 'reasoning_content'):
                        reasoning = response.choices[0].message.reasoning_content
                        print(f"🔧 上下文总结推理内容: {reasoning[:200]}...")
                        
                        # 🚀 修复：如果推理内容也不完整，重新调用AI
                        if len(reasoning) < 100:  # 推理内容太短，可能不完整
                            print(f"🔧 推理内容不完整，重新调用AI...")
                            continue  # 继续下一次重试
                        
                        # 从推理内容中提取关键信息
                        extracted_summary = self._extract_context_from_reasoning(reasoning)
                        if extracted_summary:
                            print(f"🔧 从推理内容提取上下文: {extracted_summary}")
                            return extracted_summary
                        else:
                            print(f"🔧 从推理内容无法提取上下文，重新调用AI...")
                            continue  # 继续下一次重试
                    
                    # 🚀 修复：验证AI生成的内容是否合理
                    if result and len(result) > 20 and len(result) < 200:
                        print(f"✅ AI成功生成上下文摘要: {result}")
                        return result
                    else:
                        print(f"⚠️ AI生成的内容不合理: '{result}'，重新调用AI...")
                        continue  # 继续下一次重试
                else:
                    print(f"⚠️ 上下文总结API响应没有选择")
                    continue  # 继续下一次重试
                
            except Exception as e:
                print(f"⚠️ AI上下文总结失败 (第{attempt + 1}次): {str(e)}")
                if attempt < max_retries - 1:
                    print(f"🔄 等待{retry_delay}秒后重试...")
                    import time
                    time.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
                else:
                    print(f"❌ AI上下文总结最终失败，返回默认值")
                    return "对话内容丰富，涉及多个方面的讨论。"  # 只有在所有重试都失败后才返回默认值
        
        return "对话内容丰富，涉及多个方面的讨论。"  # 最终fallback
    
    def _extract_context_from_reasoning(self, reasoning: str) -> str:
        """🚀 从推理内容中智能提取上下文 - 纯AI方式"""
        try:
            # 🚀 修复：不再使用关键词检测，而是分析推理内容的语义
            # 让AI重新尝试，而不是fallback到关键词
            print(f"🔧 推理内容不完整，需要重新调用AI")
            return None  # 返回None，触发重新调用AI
            
        except Exception as e:
            print(f"⚠️ 从推理内容提取上下文失败: {str(e)}")
            return None  # 返回None，触发重新调用AI
    
    def summarize_conversation_details(self, conversation_text: str) -> str:
        """🚀 总结具体聊天记录 - 真正的并行处理，纯AI方式"""
        try:
            # 🚀 智能分割对话内容，识别完整的问答对
            conversations = self._smart_split_conversations(conversation_text)
            print(f"🔧 智能检测到 {len(conversations)} 轮完整对话，开始并行处理...")
            
            # 🚀 真正的并行处理：每轮对话使用独立的AI调用
            def summarize_single_round(conv, round_num):
                """单轮对话总结的函数"""
                try:
                    return self._summarize_single_conversation(conv, round_num)
                except Exception as e:
                    print(f"⚠️ 第{round_num}轮总结失败: {str(e)}")
                    return None
            
            # 🚀 修复：使用线程池并行处理，每轮对话发给独立的AI
            summarized_conversations = [""] * len(conversations)  # 预分配数组
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                # 提交所有任务，确保每轮对话发给独立的AI
                future_to_round = {}
                for i, conv in enumerate(conversations):
                    if conv.strip():
                        future = executor.submit(summarize_single_round, conv, i + 1)
                        future_to_round[future] = i + 1
                        print(f"🔧 提交第{i + 1}轮对话给AI处理")
                
                # 收集结果，按轮次顺序排列
                for future in concurrent.futures.as_completed(future_to_round):
                    round_num = future_to_round[future]
                    try:
                        result = future.result()
                        if result:
                            # 按轮次顺序插入结果
                            summarized_conversations[round_num - 1] = result
                            print(f"✅ 第{round_num}轮总结完成: {len(result)}字")
                        else:
                            print(f"⚠️ 第{round_num}轮总结返回空结果")
                    except Exception as e:
                        print(f"❌ 第{round_num}轮总结异常: {str(e)}")
            
            # 🚀 拼接所有对话总结，按顺序排列
            valid_summaries = [s for s in summarized_conversations if s and s.strip()]
            if valid_summaries:
                final_summary = '\n\n'.join(valid_summaries)
                print(f"✅ 并行处理完成，生成 {len(valid_summaries)} 轮对话总结")
                return final_summary
            else:
                print(f"⚠️ 并行处理失败，使用备用方案")
                return self._fallback_conversation_summary(conversation_text)
                
        except Exception as e:
            print(f"⚠️ AI对话记录总结失败: {str(e)}")
            return self._fallback_conversation_summary(conversation_text)
    
    def _smart_split_conversations(self, conversation_text: str) -> List[str]:
        """🚀 智能分割对话内容，识别完整的问答对"""
        try:
            lines = conversation_text.strip().split('\n')
            conversations = []
            current_qa_pair = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # 检查是否是新的对话开始
                if line.startswith('指挥官:'):
                    # 如果已有问答对，保存它
                    if current_qa_pair:
                        conversations.append('\n'.join(current_qa_pair))
                        current_qa_pair = []
                    current_qa_pair.append(line)
                elif line.startswith('露尼西亚:'):
                    # 这是回答，添加到当前问答对
                    current_qa_pair.append(line)
                elif current_qa_pair:
                    # 这是回答的继续内容，添加到当前问答对
                    current_qa_pair.append(line)
            
            # 保存最后一个问答对
            if current_qa_pair:
                conversations.append('\n'.join(current_qa_pair))
            
            # 过滤掉无效的对话（如只有问题没有回答）
            valid_conversations = []
            seen_conv_keys = set()  # 🚀 修复：去重，避免重复的对话被多次总结
            
            for conv in conversations:
                if '指挥官:' in conv and '露尼西亚:' in conv:
                    # 🚀 修复：使用对话的前200字符作为唯一标识符去重
                    conv_key = conv[:200]
                    if conv_key not in seen_conv_keys:
                        seen_conv_keys.add(conv_key)
                        valid_conversations.append(conv)
                    else:
                        print(f"⚠️ 检测到重复对话轮次，跳过: {conv[:50]}...")
            
            print(f"🔧 有效对话轮次: {len(valid_conversations)} (已去重)")
            return valid_conversations
            
        except Exception as e:
            print(f"⚠️ 智能分割对话失败: {str(e)}")
            return [conversation_text]
    
    def _summarize_single_conversation(self, conversation_text: str, round_num: int) -> str:
        """🚀 总结单轮对话 - 纯AI方式"""
        max_retries = 3  # 单轮对话增加重试次数
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                print(f"🔧 开始第{round_num}轮对话总结 (第{attempt + 1}次)")
                
                prompt = f"""请将以下第{round_num}轮对话内容总结为精简的对话记录，要求：
1. 保持问答格式不变（指挥官: xxx 露尼西亚: xxx）
2. 保留关键信息，如音乐名称、国家名称、具体内容等
3. 使用缩写句子，简洁但信息完整
4. 严格控制每轮对话300字以内
5. 如果是音乐推荐，要包含具体的歌曲名和艺术家，以及少量推荐原因
6. 如果是国家介绍，要包含国家名称、地理位置、首都、人口等关键信息
7. 如果是游记写作，要包含地点、行程天数、主要景点等概要
8. 如果是天气查询，要包含具体天气数据，以及少量建议和分析
9. 如果是编程代码，要包含编程语言和项目类型
10. 每个回答都要包含具体内容，不要过于简化
11. 要准确反映实际对话内容，不要添加不存在的信息
12. 如果是自我介绍，要包含身份、背景、能力范围等关键信息
13. 如果是城市介绍，要包含城市名称、国家、地理位置、主要景点等关键信息
14. 如果是出行建议，要包含具体的时间安排、地点推荐、注意事项等
15. 如果是文件保存，要包含文件名、保存路径、文件类型等具体信息
16. 如果是技术解释，要包含技术名称、核心概念、工作原理、应用场景等关键信息
17. 所有回答都要包含具体的数据、名称、地点等，避免泛泛而谈
18. 使用简洁的表达方式，类似"缩写句子"，但信息要完整
19. 如果是多主题回答，要包含所有主要主题的关键信息
20. 确保每轮对话不超过300字，但信息要完整
21. 重点突出具体数据、名称、地点等关键信息

对话内容：
{conversation_text}

精简的对话记录（300字以内）："""
                
                response = self._chat(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=3000,
                    temperature=0.3,
                    timeout=180,
                )
                
                if response.choices:
                    result = response.choices[0].message.content.strip()
                    print(f"🔧 第{round_num}轮对话总结API响应: '{result}' (长度: {len(result)})")
                    
                    # 🚀 修复：如果没有主要内容，尝试从推理内容中提取
                    if not result and hasattr(response.choices[0].message, 'reasoning_content'):
                        reasoning = response.choices[0].message.reasoning_content
                        print(f"🔧 第{round_num}轮对话总结推理内容: {reasoning[:200]}...")
                        
                        # 🚀 修复：如果推理内容也不完整，重新调用AI
                        if len(reasoning) < 100:  # 推理内容太短，可能不完整
                            print(f"🔧 推理内容不完整，重新调用AI...")
                            continue  # 继续下一次重试
                        
                        # 从推理内容中提取关键信息
                        extracted_summary = self._extract_single_conversation_from_reasoning(reasoning, round_num)
                        if extracted_summary:
                            print(f"🔧 从推理内容提取第{round_num}轮对话记录: {extracted_summary}")
                            return extracted_summary
                        else:
                            print(f"🔧 从推理内容无法提取第{round_num}轮对话记录，重新调用AI...")
                            continue  # 继续下一次重试
                    
                    # 🚀 修复：进一步放宽验证逻辑，确保AI内容能够通过
                    if result and len(result) > 5:  # 只要有少量内容就接受
                        print(f"✅ AI成功生成第{round_num}轮对话记录: {result}")
                        return result
                    else:
                        print(f"⚠️ AI生成的内容不合理: '{result}'，重新调用AI...")
                        continue  # 继续下一次重试
                else:
                    print(f"⚠️ 第{round_num}轮对话总结API响应没有选择")
                    continue  # 继续下一次重试
                    
            except Exception as e:
                print(f"⚠️ 第{round_num}轮对话总结失败 (第{attempt + 1}次): {str(e)}")
                if attempt < max_retries - 1:
                    print(f"🔄 等待{retry_delay}秒后重试...")
                    import time
                    time.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
                else:
                    print(f"❌ 第{round_num}轮对话总结最终失败")
                    # 🚀 修复：使用智能备用方案
                    return self._fallback_single_conversation_summary(conversation_text, round_num)
        
        # 🚀 修复：确保永远不返回None
        return self._fallback_single_conversation_summary(conversation_text, round_num)
    
    def _extract_single_conversation_from_reasoning(self, reasoning: str, round_num: int) -> str:
        """🚀 从推理内容中提取单轮对话记录 - 纯AI方式"""
        try:
            # 🚀 修复：不再使用关键词检测，而是分析推理内容的语义
            # 让AI重新尝试，而不是fallback到关键词
            print(f"🔧 第{round_num}轮对话推理内容不完整，需要重新调用AI")
            return None  # 返回None，触发重新调用AI
            
        except Exception as e:
            print(f"⚠️ 从推理内容提取第{round_num}轮对话记录失败: {str(e)}")
            return None  # 返回None，触发重新调用AI
    
    def _fallback_single_conversation_summary(self, conversation_text: str, round_num: int) -> str:
        """🚀 智能备用单轮对话记录总结方案"""
        try:
            print(f"🔧 使用智能备用方案提取第{round_num}轮对话记录...")
            
            # 🚀 修复：当AI完全失败时，生成基于原始对话的简化版本
            lines = conversation_text.strip().split('\n')
            commander_line = ""
            lunisia_content = ""
            
            for line in lines:
                line = line.strip()
                if line.startswith('指挥官:'):
                    commander_line = line
                elif line.startswith('露尼西亚:'):
                    lunisia_content = line  # 不截取，保持完整内容
                elif lunisia_content and line:
                    # 继续添加露尼西亚的回答，保持完整内容
                    lunisia_content += " " + line
            
            if commander_line and lunisia_content:
                return f"{commander_line}\n{lunisia_content}"
            else:
                return f"指挥官: 第{round_num}轮对话内容\n露尼西亚: 提供了详细的回答和专业建议"
                
        except Exception as e:
            print(f"⚠️ 智能备用单轮对话记录总结失败: {str(e)}")
            return f"指挥官: 第{round_num}轮对话内容\n露尼西亚: 提供了详细的回答和专业建议"
    
    def _fallback_conversation_summary(self, conversation_text: str) -> str:
        """🚀 智能备用对话记录总结方案"""
        try:
            print(f"🔧 使用智能备用对话记录总结方案...")
            
            # 🚀 修复：当AI完全失败时，生成基于原始对话的简化版本
            lines = conversation_text.strip().split('\n')
            summary_parts = []
            current_round = 1
            
            commander_line = ""
            lunisia_content = ""
            
            for line in lines:
                line = line.strip()
                if line.startswith('指挥官:'):
                    # 如果之前有完整的对话，先保存
                    if commander_line and lunisia_content:
                        summary_parts.append(f"{commander_line}\n{lunisia_content}")
                        current_round += 1
                    
                    commander_line = line
                    lunisia_content = ""
                elif line.startswith('露尼西亚:'):
                    lunisia_content = line  # 不截取，保持完整内容
                elif lunisia_content and line:
                    # 继续添加露尼西亚的回答，保持完整内容
                    lunisia_content += " " + line
            
            # 添加最后一轮对话
            if commander_line and lunisia_content:
                summary_parts.append(f"{commander_line}\n{lunisia_content}")
            
            if summary_parts:
                return '\n\n'.join(summary_parts)
            else:
                return "指挥官: 进行了多轮对话\n露尼西亚: 提供了详细的回答和专业建议"
                
        except Exception as e:
            print(f"⚠️ 智能备用对话记录总结失败: {str(e)}")
            return "指挥官: 进行了多轮对话\n露尼西亚: 提供了详细的回答和专业建议"
