#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搜索结果精简Agent - 处理长文本搜索结果
"""

import json
import re
from typing import Optional, List, Dict

class SearchSummaryAgent:
    """搜索结果精简Agent"""
    
    def __init__(self):
        self.max_length = 1000  # 最大长度阈值（调整为约千字）
        
    def should_summarize(self, text: str) -> bool:
        """
        判断是否需要精简
        
        Args:
            text: 输入文本
            
        Returns:
            是否需要精简
        """
        return len(text) > self.max_length
    
    def summarize_search_result(self, search_result: str, query: str) -> str:
        """
        精简搜索结果
        
        Args:
            search_result: 原始搜索结果
            query: 搜索查询
            
        Returns:
            精简后的结果
        """
        if not self.should_summarize(search_result):
            return search_result
        
        try:
            # 提取关键信息
            key_info = self._extract_key_info(search_result, query)
            
            # 如果提取的信息仍然太长，进行进一步精简
            if len(key_info) > self.max_length:
                key_info = self._further_summarize(key_info)
            
            return f"搜索查询: {query}\n\n精简结果:\n{key_info}"
            
        except Exception as e:
            print(f"搜索结果精简失败: {e}")
            # 如果精简失败，返回截断的原始结果
            return search_result[:self.max_length] + "..."
    
    def _extract_key_info(self, text: str, query: str) -> str:
        """
        提取关键信息
        
        Args:
            text: 原始文本
            query: 搜索查询
            
        Returns:
            提取的关键信息
        """
        # 按段落分割
        paragraphs = text.split('\n\n')
        key_paragraphs = []
        
        # 提取包含查询关键词的段落
        query_words = query.lower().split()
        
        for paragraph in paragraphs:
            if not paragraph.strip():
                continue
                
            # 检查段落是否包含查询关键词
            paragraph_lower = paragraph.lower()
            relevance_score = sum(1 for word in query_words if word in paragraph_lower)
            
            if relevance_score > 0:
                key_paragraphs.append((paragraph, relevance_score))
        
        # 按相关性排序
        key_paragraphs.sort(key=lambda x: x[1], reverse=True)
        
        # 选择最相关的段落
        selected_paragraphs = []
        current_length = 0
        
        for paragraph, score in key_paragraphs:
            if current_length + len(paragraph) <= self.max_length:
                selected_paragraphs.append(paragraph)
                current_length += len(paragraph)
            else:
                break
        
        # 如果没有找到相关段落，使用前几个段落
        if not selected_paragraphs:
            for paragraph in paragraphs[:3]:
                if current_length + len(paragraph) <= self.max_length:
                    selected_paragraphs.append(paragraph)
                    current_length += len(paragraph)
                else:
                    break
        
        return '\n\n'.join(selected_paragraphs)
    
    def _further_summarize(self, text: str) -> str:
        """
        进一步精简文本
        
        Args:
            text: 需要精简的文本
            
        Returns:
            精简后的文本
        """
        # 按句子分割
        sentences = re.split(r'[.!?。！？]', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        # 选择前几个句子
        selected_sentences = []
        current_length = 0
        
        for sentence in sentences:
            if current_length + len(sentence) <= self.max_length:
                selected_sentences.append(sentence)
                current_length += len(sentence)
            else:
                break
        
        return '。'.join(selected_sentences) + '。'
    
    def extract_search_intent(self, user_input: str) -> Optional[str]:
        """
        从用户输入中提取搜索意图
        
        Args:
            user_input: 用户输入
            
        Returns:
            搜索查询，如果不是搜索意图则返回None
        """
        # 搜索相关的关键词
        search_keywords = [
            '搜索', '查找', '找', '搜', '查询', '了解', '知道', '是什么', '怎么样',
            '如何', '怎么', '为什么', '什么是', '最新', '新闻', '资讯', '信息',
            '介绍', '说明', '详细', '具体', '情况', '内容', '资料', '详情'
        ]
        
        # 检查是否包含搜索关键词
        user_lower = user_input.lower()
        has_search_keyword = any(keyword in user_lower for keyword in search_keywords)
        
        # 检查是否是疑问句
        is_question = any(char in user_input for char in '？?')
        
        # 检查是否包含具体的信息需求
        info_indicators = [
            '价格', '时间', '地点', '方法', '步骤', '原因', '结果', '影响',
            '历史', '现状', '未来', '趋势', '数据', '统计', '报告'
        ]
        
        has_info_need = any(indicator in user_input for indicator in info_indicators)
        
        # 判断是否需要搜索
        if has_search_keyword or (is_question and has_info_need):
            # 清理查询，移除搜索关键词
            query = user_input
            for keyword in search_keywords:
                query = query.replace(keyword, '').strip()
            
            # 移除常见的语气词
            query = re.sub(r'[，。！？,\.!?]', '', query).strip()
            
            if len(query) > 2:  # 确保查询有意义
                return query
        
        return None

# 创建全局精简agent实例
search_summary_agent = SearchSummaryAgent()

def process_search_result(search_result: str, query: str) -> str:
    """
    处理搜索结果 - 供外部调用
    
    Args:
        search_result: 原始搜索结果
        query: 搜索查询
        
    Returns:
        处理后的结果
    """
    return search_summary_agent.summarize_search_result(search_result, query)

def should_search(user_input: str) -> Optional[str]:
    """
    判断是否需要搜索 - 供外部调用
    
    Args:
        user_input: 用户输入
        
    Returns:
        搜索查询，如果不需要搜索则返回None
    """
    return search_summary_agent.extract_search_intent(user_input)

if __name__ == "__main__":
    # 测试精简功能
    test_result = "这是一个很长的搜索结果..." * 100
    test_query = "Python编程"
    
    print("原始长度:", len(test_result))
    summarized = process_search_result(test_result, test_query)
    print("精简后长度:", len(summarized))
    print("精简结果:", summarized[:200] + "...")
