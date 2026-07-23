#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
文件分析AI Agent
专门负责文件内容的AI智能分析，包括PDF、表格等文件的深度理解
"""

import json
import openai
from typing import Dict, Any, Optional
from file_analysis_tool import FileAnalysisResult

class FileAnalysisAgent:
    """文件分析AI Agent - 专门负责文件内容的AI智能分析"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.name = "文件分析AI Agent"
        print(f"✅ {self.name}已初始化")
    
    def analyze_file_with_ai(
        self, result: FileAnalysisResult, user_question: str = "", stream_callback=None
    ) -> str:
        """使用AI深度分析文件内容"""
        try:
            print(f"✅ {self.name}开始深度分析文件: {result.file_name}")
            
            # 根据文件类型选择不同的分析策略
            if result.file_type == "PDF":
                return self._analyze_pdf_with_ai(result, user_question, stream_callback)
            elif result.file_type == "TABLE":
                return self._analyze_table_with_ai(result, user_question, stream_callback)
            else:
                return self._analyze_general_with_ai(result, user_question, stream_callback)
                
        except Exception as e:
            print(f"❌ {self.name}分析失败: {e}")
            return f"❌ AI文件分析失败: {str(e)}"
    
    def _analyze_pdf_with_ai(
        self, result: FileAnalysisResult, user_question: str = "", stream_callback=None
    ) -> str:
        """使用AI深度分析PDF内容"""
        try:
            # 构建分析提示词
            if user_question:
                prompt = f"""
你是一个专业的文档分析专家。请根据用户的问题"{user_question}"，对以下PDF文档进行深度分析。

文档信息：
- 文件名: {result.file_name}
- 页数: {result.metadata.get('page_count', '未知')}
- 内容长度: {len(result.content)} 字符

文档内容：
{result.content[:2000]}

请提供以下分析：
1. **核心主题总结**：用2-3句话概括文档的核心主题
2. **关键观点提取**：列出文档中的3-5个关键观点
3. **重要数据/事实**：提取文档中的重要数字、时间、统计数据
4. **结构分析**：分析文档的逻辑结构和章节安排
5. **针对用户问题的回答**：基于文档内容回答用户的具体问题

请用专业、简洁的语言进行分析，突出重点信息。以通常精准冷静语气回答，但直接与用户聊天时要用略亲切的语气。
"""
            else:
                prompt = f"""
你是一个专业的文档分析专家。请对以下PDF文档进行全面的智能分析。

文档信息：
- 文件名: {result.file_name}
- 页数: {result.metadata.get('page_count', '未知')}
- 内容长度: {len(result.content)} 字符

文档内容：
{result.content[:2000]}

请提供以下分析：
1. **文档主题**：用一句话概括文档的核心主题
2. **主要内容**：总结文档的主要章节和内容要点
3. **关键信息**：提取文档中的重要数据、时间、人物、概念
4. **逻辑结构**：分析文档的组织结构和论证逻辑
5. **价值评估**：评估文档的信息价值和实用性
6. **建议**：基于文档内容给出阅读建议或应用建议

请用专业、结构化的语言进行分析，突出重点信息。请以通常精准冷静语气回答，但直接与用户聊天时要用略亲切的语气。
"""
            
            # 调用AI API进行分析
            ai_response = self._call_ai_api(prompt, stream_callback=stream_callback)
            
            if ai_response:
                return f"✅ **AI深度分析报告**\n\n{ai_response}"
            else:
                return "❌ AI分析服务暂时不可用"
                
        except Exception as e:
            print(f"❌ PDF AI分析失败: {e}")
            return f"❌ PDF AI分析失败: {str(e)}"
    
    def _analyze_table_with_ai(
        self, result: FileAnalysisResult, user_question: str = "", stream_callback=None
    ) -> str:
        """使用AI深度分析表格内容"""
        try:
            metadata = result.metadata
            
            # 构建表格分析提示词
            if user_question:
                prompt = f"""
你是一个专业的数据分析专家（不需要在回答中提到）。请根据用户的问题"{user_question}"，对以下表格数据进行深度分析。

表格信息：
- 文件名: {result.file_name}
- 数据规模: {metadata.get('rows', 0)} 行 × {metadata.get('columns', 0)} 列
- 列名: {', '.join(metadata.get('column_names', []))}
- 数据类型: {metadata.get('data_types', {})}

表格内容：
{result.content[:1500]}

请提供以下分析：
1. **数据概览**：用2-3句话概括这个表格的主要内容和用途
2. **关键指标**：识别表格中的关键数据指标和重要数值
3. **数据特征**：分析数据的分布特征、趋势和异常值
4. **业务洞察**：基于数据提供业务洞察和建议
5. **针对用户问题的回答**：基于表格数据回答用户的具体问题

请用专业、数据驱动的语言进行分析，突出数据价值。以通常精准冷静语气回答，但直接与用户聊天时要用略亲切的语气。
"""
            else:
                prompt = f"""
你是一个专业的数据分析专家（不需要在回答中提到）。请对以下表格数据进行全面的智能分析。

表格信息：
- 文件名: {result.file_name}
- 数据规模: {metadata.get('rows', 0)} 行 × {metadata.get('columns', 0)} 列
- 列名: {', '.join(metadata.get('column_names', []))}
- 数据类型: {metadata.get('data_types', {})}

表格内容：
{result.content[:1500]}

请提供以下分析：
1. **数据概览**：用一句话概括这个表格的主要内容和用途
2. **数据结构**：分析表格的列结构、数据类型和数据质量
3. **关键指标**：识别并分析表格中的关键数据指标
4. **数据洞察**：基于数据提供业务洞察和趋势分析
5. **应用建议**：基于数据特征给出使用建议
6. **注意事项**：指出数据使用中需要注意的问题

请用专业、数据驱动的语言进行分析，突出数据价值。以通常精准冷静语气回答，但直接与用户聊天时要用略亲切的语气。
"""
            
            # 调用AI API进行分析
            ai_response = self._call_ai_api(prompt, stream_callback=stream_callback)
            
            if ai_response:
                return f"✅ **AI数据分析报告**\n\n{ai_response}"
            else:
                return "❌ AI分析服务暂时不可用"
                
        except Exception as e:
            print(f"❌ 表格AI分析失败: {e}")
            return f"❌ 表格AI分析失败: {str(e)}"
    
    def _analyze_general_with_ai(
        self, result: FileAnalysisResult, user_question: str = "", stream_callback=None
    ) -> str:
        """使用AI分析一般文件内容（Word文档等）"""
        try:
            # 智能截取：优先取全文，如果太长则取开头+中间+结尾
            content = result.content
            content_length = len(content)
            
            if content_length <= 8000:
                # 文档较短，使用全文
                content_sample = content
            else:
                # 文档较长，取开头、中间、结尾各部分
                part_size = 2500
                start = content[:part_size]
                middle_pos = content_length // 2 - part_size // 2
                middle = content[middle_pos:middle_pos + part_size]
                end = content[-part_size:]
                content_sample = f"{start}\n\n...[中间内容省略]...\n\n{middle}\n\n...[中间内容省略]...\n\n{end}"
            
            # 预先计算标题数（避免在f-string中使用复杂表达式）
            lines = content.split('\n')
            heading_count = len([line for line in lines if line.strip() and (line.startswith('#') or (len(line) < 50 and line.isupper()))])
            
            prompt = f"""
你是一个专业的文档分析专家（不需要在回答中提到）。请对以下{result.file_type}文档进行深度智能分析。

⚠️ **重要提示**：
- 你需要阅读并理解整篇文档的内容
- 不要只是复制文档的开头部分
- 要提炼出文档的核心观点、关键数据和主要结论
- 分析要基于对全文的理解，而不是表面的文字摘抄

文档信息：
- 文件名: {result.file_name}
- 文件类型: {result.file_type}
- 总长度: {content_length} 字符
- 段落数: {result.metadata.get('paragraph_count', '未知')}
- 表格数: {result.metadata.get('table_count', 0)}
- 标题数: {heading_count}

文档完整内容：
{content_sample}

请提供以下深度分析（**每一条都要基于对全文的理解**）：

**1. 文件概览**  
用1-2句话概括这篇文档的核心主题和目的（不是简单复制开头）

---

**2. 关键信息**  
从整篇文档中提取最重要的信息点：
- **核心论点/主题**：文档的中心思想是什么？
- **关键数据**：文档中出现的重要数字、百分比、统计数据（具体列举）
- **重要结论**：作者得出的主要结论或观点
- **核心挑战/问题**：文档指出的主要问题或挑战

---

**3. 内容结构**  
分析文档的组织逻辑：
- **逻辑框架**：文档按什么逻辑展开（时间线？问题-解决方案？总分总？）
- **章节层次**：主要包含哪些部分（不要简单列举标题，要说明各部分的作用）
- **完整性评估**：内容是否完整，是否有缺失或截断

---

**4. 价值评估**  
评估文档的实用性和价值：
- **信息密度**：内容是否充实、数据是否丰富
- **实用性**：对读者有什么实际帮助
- **局限性**：存在什么不足或需要补充的地方

---

**5. 使用建议**  
针对不同读者群体，给出具体的使用建议：
- **决策者**：如何用这份文档做决策
- **技术人员**：重点关注哪些技术细节
- **研究人员**：可以从中获取什么研究线索
- **补充建议**：需要配合哪些其他资料使用

请用专业、结构化的语言进行分析，突出核心价值，避免流水账式描述。以通常精准冷静语气回答，但直接与用户聊天时要用略亲切的语气。
"""
            
            # 调用AI API进行分析
            ai_response = self._call_ai_api(prompt, stream_callback=stream_callback)
            
            if ai_response:
                return f"✅ **AI文件分析报告**\n\n{ai_response}"
            else:
                return "❌ AI分析服务暂时不可用"
                
        except Exception as e:
            print(f"❌ 通用文件AI分析失败: {e}")
            return f"❌ 通用文件AI分析失败: {str(e)}"
    
    def _call_ai_api(self, prompt: str, stream_callback=None) -> Optional[str]:
        """调用AI API进行分析"""
        try:
            from llm_router import chat_completion

            return chat_completion(
                self.config,
                config_key="selected_model",
                messages=[
                    {"role": "system", "content": "你是一个专业的文档分析专家，擅长深度理解各种文件内容并提供有价值的分析。你能够通读全文，提炼核心要点，而不是简单地复制粘贴文档开头。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=3000,
                temperature=0.7,
                task_label="file_analysis",
                stream_callback=stream_callback,
            )
                
        except Exception as e:
            print(f"❌ AI API调用失败: {e}")
            return None

# 测试函数
def test_file_analysis_agent():
    """测试文件分析AI Agent"""
    print("🧪 测试文件分析AI Agent...")
    
    # 模拟配置
    config = {
        "selected_model": "deepseek-v4-flash",
        "deepseek_key": "sk-test-key"
    }
    
    # 创建Agent
    agent = FileAnalysisAgent(config)
    
    # 模拟文件分析结果
    from file_analysis_tool import FileAnalysisResult
    result = FileAnalysisResult(
        file_type="PDF",
        file_name="test.pdf",
        content="这是一个测试文档，包含人工智能相关内容。",
        metadata={"page_count": 1},
        summary="测试摘要",
        analysis="测试分析",
        success=True
    )
    
    # 测试分析
    analysis = agent.analyze_file_with_ai(result, "请总结这个文档")
    print(f"分析结果: {analysis}")

if __name__ == "__main__":
    test_file_analysis_agent()
