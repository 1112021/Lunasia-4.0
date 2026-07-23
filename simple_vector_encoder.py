# -*- coding: utf-8 -*-
"""
简单向量编码器 - 将主题词转换为向量
用于识底深湖记忆系统的向量数据库功能
"""

import re
import json
import os
import math
from collections import Counter
from typing import List, Dict, Optional

class SimpleVectorEncoder:
    """简单的主题词向量编码器"""
    
    def __init__(self, vocab_file="topic_vocab.json", vector_dim=128):
        # 检查是否使用新的文件结构
        new_vocab_file = os.path.join("chat_logs", "vectors", "topic_vocab.json")
        if os.path.exists(new_vocab_file):
            self.vocab_file = new_vocab_file
        else:
            self.vocab_file = vocab_file
            
        self.vector_dim = vector_dim
        self.vocab = {}  # 词汇表 {word: index}
        self.word_freq = Counter()  # 词频统计
        self.idf_scores = {}  # IDF分数
        self.load_vocab()
    
    def load_vocab(self):
        """加载词汇表"""
        if os.path.exists(self.vocab_file):
            try:
                with open(self.vocab_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.vocab = data.get("vocab", {})
                    self.word_freq = Counter(data.get("word_freq", {}))
                    self.idf_scores = data.get("idf_scores", {})
                    print(f"📚 加载词汇表: {len(self.vocab)} 个词汇")
            except Exception as e:
                print(f"⚠️ 加载词汇表失败: {e}")
                self.vocab = {}
                self.word_freq = Counter()
                self.idf_scores = {}
    
    def save_vocab(self):
        """保存词汇表"""
        try:
            data = {
                "vocab": self.vocab,
                "word_freq": dict(self.word_freq),
                "idf_scores": self.idf_scores
            }
            with open(self.vocab_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存词汇表失败: {e}")
    
    def tokenize(self, text: str) -> List[str]:
        """分词 - 简单的中文分词"""
        if not text:
            return []
        
        # 移除标点符号和特殊字符
        text = re.sub(r'[^\w\s]', ' ', text)
        
        # 分离中文字符和英文单词
        tokens = []
        current_word = ""
        
        for char in text:
            if char.isalpha():
                if '\u4e00' <= char <= '\u9fff':  # 中文字符
                    if current_word:
                        tokens.append(current_word.lower())
                        current_word = ""
                    tokens.append(char)
                else:  # 英文字符
                    current_word += char
            elif char.isspace():
                if current_word:
                    tokens.append(current_word.lower())
                    current_word = ""
            else:
                if current_word:
                    tokens.append(current_word.lower())
                    current_word = ""
        
        if current_word:
            tokens.append(current_word.lower())
        
        # 过滤掉太短的词
        tokens = [token for token in tokens if len(token) >= 1]
        
        return tokens
    
    def update_vocab(self, texts: List[str]):
        """更新词汇表"""
        all_tokens = []
        doc_count = {}  # 每个词出现在多少个文档中
        
        for text in texts:
            tokens = self.tokenize(text)
            all_tokens.extend(tokens)
            
            # 统计文档频率
            unique_tokens = set(tokens)
            for token in unique_tokens:
                doc_count[token] = doc_count.get(token, 0) + 1
        
        # 更新词频
        self.word_freq.update(all_tokens)
        
        # 重建词汇表索引
        unique_words = list(self.word_freq.keys())
        self.vocab = {word: idx for idx, word in enumerate(unique_words)}
        
        # 计算IDF分数
        total_docs = len(texts) if texts else 1
        for word, df in doc_count.items():
            self.idf_scores[word] = math.log(total_docs / (df + 1))
        
        print(f"📚 更新词汇表: {len(self.vocab)} 个词汇")
        self.save_vocab()
    
    def encode_text(self, text: str) -> Optional[List[float]]:
        """将文本编码为向量"""
        if not text:
            return None
        
        tokens = self.tokenize(text)
        if not tokens:
            return None
        
        # 创建TF-IDF向量
        vector = [0.0] * self.vector_dim
        token_count = Counter(tokens)
        
        for token, tf in token_count.items():
            if token in self.vocab:
                idx = self.vocab[token] % self.vector_dim  # 映射到向量维度
                idf = self.idf_scores.get(token, 1.0)
                tfidf = tf * idf
                vector[idx] += tfidf
        
        # 归一化向量
        vector_norm = math.sqrt(sum(x * x for x in vector))
        if vector_norm > 0:
            vector = [x / vector_norm for x in vector]
        
        return vector
    
    def calculate_similarity(self, vector1: List[float], vector2: List[float]) -> float:
        """计算两个向量的余弦相似度"""
        if not vector1 or not vector2:
            return 0.0
        
        if len(vector1) != len(vector2):
            return 0.0
        
        # 余弦相似度
        dot_product = sum(a * b for a, b in zip(vector1, vector2))
        norm1 = math.sqrt(sum(a * a for a in vector1))
        norm2 = math.sqrt(sum(b * b for b in vector2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def get_stats(self) -> Dict:
        """获取编码器统计信息"""
        return {
            "vocab_size": len(self.vocab),
            "total_words": sum(self.word_freq.values()),
            "unique_words": len(self.word_freq),
            "vector_dim": self.vector_dim
        }

# 全局实例
_encoder_instance = None

def get_vector_encoder() -> SimpleVectorEncoder:
    """获取向量编码器实例"""
    global _encoder_instance
    if _encoder_instance is None:
        _encoder_instance = SimpleVectorEncoder()
    return _encoder_instance
