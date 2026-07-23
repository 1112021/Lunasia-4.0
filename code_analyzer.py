#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
代码分析器 - 露尼西亚的代码理解能力
支持Python、Java、JavaScript、C++等多种编程语言的智能分析
"""

import os
import ast
import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from pathlib import Path

@dataclass
class CodeAnalysisResult:
    """代码分析结果"""
    language: str
    file_name: str
    content: str
    structure: Dict[str, Any]
    metrics: Dict[str, Any]
    summary: str
    analysis: str
    success: bool
    error: Optional[str] = None

class PythonCodeAnalyzer:
    """Python代码分析器（使用AST）"""
    
    def __init__(self):
        self.name = "Python代码分析器"
    
    def analyze(self, file_path: str) -> CodeAnalysisResult:
        """分析Python代码"""
        try:
            print(f"🐍 开始分析Python代码: {file_path}")
            
            # 读取代码内容
            with open(file_path, 'r', encoding='utf-8') as f:
                code_content = f.read()
            
            # 解析AST
            try:
                tree = ast.parse(code_content)
            except SyntaxError as e:
                return CodeAnalysisResult(
                    language="Python",
                    file_name=os.path.basename(file_path),
                    content=code_content,
                    structure={},
                    metrics={},
                    summary=f"语法错误: {str(e)}",
                    analysis="",
                    success=False,
                    error=f"Python语法错误: {str(e)}"
                )
            
            # 提取代码结构
            structure = self._extract_structure(tree, code_content)
            
            # 计算代码度量
            metrics = self._calculate_metrics(tree, code_content)
            
            # 生成摘要和分析
            summary = self._generate_summary(structure, metrics)
            analysis = self._generate_analysis(structure, metrics)
            
            return CodeAnalysisResult(
                language="Python",
                file_name=os.path.basename(file_path),
                content=code_content,
                structure=structure,
                metrics=metrics,
                summary=summary,
                analysis=analysis,
                success=True
            )
            
        except Exception as e:
            print(f"❌ Python代码分析失败: {e}")
            import traceback
            traceback.print_exc()
            return CodeAnalysisResult(
                language="Python",
                file_name=os.path.basename(file_path),
                content="",
                structure={},
                metrics={},
                summary="",
                analysis="",
                success=False,
                error=str(e)
            )
    
    def _extract_structure(self, tree: ast.AST, code: str) -> Dict[str, Any]:
        """提取代码结构"""
        structure = {
            "imports": [],
            "classes": [],
            "functions": [],
            "variables": [],
            "decorators": []
        }
        
        for node in ast.walk(tree):
            # 导入语句
            if isinstance(node, ast.Import):
                for alias in node.names:
                    structure["imports"].append({
                        "type": "import",
                        "name": alias.name,
                        "alias": alias.asname
                    })
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    structure["imports"].append({
                        "type": "from",
                        "module": module,
                        "name": alias.name,
                        "alias": alias.asname
                    })
            
            # 类定义
            elif isinstance(node, ast.ClassDef):
                bases = [self._get_name(base) for base in node.bases]
                methods = []
                class_vars = []
                
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        methods.append({
                            "name": item.name,
                            "args": [arg.arg for arg in item.args.args],
                            "decorators": [self._get_name(d) for d in item.decorator_list],
                            "is_async": isinstance(item, ast.AsyncFunctionDef),
                            "docstring": ast.get_docstring(item)
                        })
                    elif isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                class_vars.append(target.id)
                
                structure["classes"].append({
                    "name": node.name,
                    "bases": bases,
                    "methods": methods,
                    "class_variables": class_vars,
                    "decorators": [self._get_name(d) for d in node.decorator_list],
                    "docstring": ast.get_docstring(node)
                })
            
            # 函数定义（顶层）
            elif isinstance(node, ast.FunctionDef) and isinstance(node, ast.Module):
                # 只统计模块级别的函数
                continue
        
        # 统计顶层函数（不在类中的）
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                structure["functions"].append({
                    "name": node.name,
                    "args": [arg.arg for arg in node.args.args],
                    "decorators": [self._get_name(d) for d in node.decorator_list],
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                    "docstring": ast.get_docstring(node)
                })
            # 全局变量
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        structure["variables"].append(target.id)
        
        return structure
    
    def _get_name(self, node):
        """获取节点名称"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Call):
            return self._get_name(node.func)
        else:
            return str(node)
    
    def _calculate_metrics(self, tree: ast.AST, code: str) -> Dict[str, Any]:
        """计算代码度量"""
        lines = code.split('\n')
        
        # 统计各种节点
        node_counts = {
            "total_lines": len(lines),
            "code_lines": len([line for line in lines if line.strip() and not line.strip().startswith('#')]),
            "comment_lines": len([line for line in lines if line.strip().startswith('#')]),
            "blank_lines": len([line for line in lines if not line.strip()]),
            "classes": 0,
            "functions": 0,
            "methods": 0,
            "imports": 0,
            "if_statements": 0,
            "for_loops": 0,
            "while_loops": 0,
            "try_blocks": 0,
            "with_statements": 0
        }
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                node_counts["classes"] += 1
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                node_counts["functions"] += 1
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                node_counts["imports"] += 1
            elif isinstance(node, ast.If):
                node_counts["if_statements"] += 1
            elif isinstance(node, ast.For):
                node_counts["for_loops"] += 1
            elif isinstance(node, ast.While):
                node_counts["while_loops"] += 1
            elif isinstance(node, ast.Try):
                node_counts["try_blocks"] += 1
            elif isinstance(node, ast.With):
                node_counts["with_statements"] += 1
        
        # 计算复杂度
        node_counts["complexity_score"] = (
            node_counts["if_statements"] + 
            node_counts["for_loops"] + 
            node_counts["while_loops"] + 
            node_counts["try_blocks"]
        )
        
        return node_counts
    
    def _generate_summary(self, structure: Dict, metrics: Dict) -> str:
        """生成代码摘要"""
        summary_parts = []
        
        summary_parts.append(f"📊 代码行数: {metrics['total_lines']} 行")
        summary_parts.append(f"  - 有效代码: {metrics['code_lines']} 行")
        summary_parts.append(f"  - 注释: {metrics['comment_lines']} 行")
        summary_parts.append(f"  - 空行: {metrics['blank_lines']} 行")
        
        if structure["imports"]:
            summary_parts.append(f"📦 导入模块: {len(structure['imports'])} 个")
        
        if structure["classes"]:
            total_methods = sum(len(cls["methods"]) for cls in structure["classes"])
            summary_parts.append(f"🏗️ 类定义: {len(structure['classes'])} 个 (共 {total_methods} 个方法)")
        
        if structure["functions"]:
            summary_parts.append(f"⚙️ 函数定义: {len(structure['functions'])} 个")
        
        if metrics.get("complexity_score", 0) > 0:
            complexity_level = "低"
            if metrics["complexity_score"] > 50:
                complexity_level = "高"
            elif metrics["complexity_score"] > 20:
                complexity_level = "中"
            summary_parts.append(f"📈 代码复杂度: {complexity_level} ({metrics['complexity_score']})")
        
        return "\n".join(summary_parts)
    
    def _generate_analysis(self, structure: Dict, metrics: Dict) -> str:
        """生成代码分析"""
        analysis_parts = []
        
        # 代码组织分析
        if structure["classes"]:
            analysis_parts.append("🏗️ 面向对象设计：使用了类结构")
            
            # 分析类的特点
            class_features = []
            for cls in structure["classes"]:
                if cls["bases"]:
                    class_features.append(f"继承关系")
                    break
            
            for cls in structure["classes"]:
                for method in cls["methods"]:
                    if method["decorators"]:
                        class_features.append("使用装饰器")
                        break
                if class_features:
                    break
            
            if class_features:
                analysis_parts.append(f"  特点: {', '.join(class_features)}")
        
        # 导入分析
        if structure["imports"]:
            import_modules = set()
            for imp in structure["imports"]:
                if imp["type"] == "import":
                    import_modules.add(imp["name"].split('.')[0])
                else:
                    import_modules.add(imp["module"].split('.')[0] if imp["module"] else "")
            
            common_libs = {"os", "sys", "json", "re", "typing", "pathlib"}
            web_libs = {"flask", "django", "fastapi", "requests", "aiohttp"}
            data_libs = {"pandas", "numpy", "matplotlib", "sklearn", "tensorflow", "torch"}
            
            detected_libs = []
            if import_modules & web_libs:
                detected_libs.append("Web框架")
            if import_modules & data_libs:
                detected_libs.append("数据分析/机器学习")
            if import_modules & common_libs:
                detected_libs.append("标准库")
            
            if detected_libs:
                analysis_parts.append(f"📦 依赖类型: {', '.join(detected_libs)}")
        
        # 代码风格分析
        if structure["functions"] or structure["classes"]:
            has_docstrings = False
            
            for func in structure["functions"]:
                if func.get("docstring"):
                    has_docstrings = True
                    break
            
            if not has_docstrings:
                for cls in structure["classes"]:
                    if cls.get("docstring"):
                        has_docstrings = True
                        break
            
            if has_docstrings:
                analysis_parts.append("📝 包含文档字符串，代码规范性良好")
        
        # 异步编程
        async_count = len([f for f in structure["functions"] if f.get("is_async")])
        for cls in structure["classes"]:
            async_count += len([m for m in cls["methods"] if m.get("is_async")])
        
        if async_count > 0:
            analysis_parts.append(f"⚡ 使用异步编程 ({async_count} 个async函数/方法)")
        
        # 错误处理
        if metrics.get("try_blocks", 0) > 0:
            analysis_parts.append(f"🛡️ 包含异常处理 ({metrics['try_blocks']} 个try块)")
        
        return "\n".join(analysis_parts) if analysis_parts else "📄 标准Python代码"

class GeneralCodeAnalyzer:
    """通用代码分析器（支持Java、JavaScript、C++等）"""
    
    def __init__(self):
        self.name = "通用代码分析器"
        
        # 语言特征模式
        self.language_patterns = {
            "java": {
                "extensions": [".java"],
                "class_pattern": r'class\s+(\w+)',
                "method_pattern": r'(public|private|protected)?\s*\w+\s+(\w+)\s*\(',
                "import_pattern": r'import\s+([\w.]+);'
            },
            "javascript": {
                "extensions": [".js", ".jsx", ".ts", ".tsx"],
                "class_pattern": r'class\s+(\w+)',
                "function_pattern": r'function\s+(\w+)\s*\(|const\s+(\w+)\s*=\s*\(',
                "import_pattern": r'import\s+.*from\s+[\'"](.+)[\'"]'
            },
            "cpp": {
                "extensions": [".cpp", ".cc", ".cxx", ".h", ".hpp"],
                "class_pattern": r'class\s+(\w+)',
                "function_pattern": r'\w+\s+(\w+)\s*\(',
                "include_pattern": r'#include\s*[<"](.+)[>"]'
            },
            "c": {
                "extensions": [".c", ".h"],
                "function_pattern": r'\w+\s+(\w+)\s*\(',
                "include_pattern": r'#include\s*[<"](.+)[>"]'
            },
            "go": {
                "extensions": [".go"],
                "function_pattern": r'func\s+(\w+)\s*\(',
                "import_pattern": r'import\s+"(.+)"'
            },
            "rust": {
                "extensions": [".rs"],
                "function_pattern": r'fn\s+(\w+)\s*\(',
                "struct_pattern": r'struct\s+(\w+)'
            }
        }
    
    def detect_language(self, file_path: str) -> str:
        """检测编程语言"""
        ext = os.path.splitext(file_path)[1].lower()
        
        for lang, config in self.language_patterns.items():
            if ext in config.get("extensions", []):
                return lang
        
        return "unknown"
    
    def analyze(self, file_path: str) -> CodeAnalysisResult:
        """分析代码文件"""
        try:
            language = self.detect_language(file_path)
            
            if language == "unknown":
                return CodeAnalysisResult(
                    language="Unknown",
                    file_name=os.path.basename(file_path),
                    content="",
                    structure={},
                    metrics={},
                    summary="不支持的文件类型",
                    analysis="",
                    success=False,
                    error=f"无法识别文件类型: {os.path.splitext(file_path)[1]}"
                )
            
            print(f"💻 开始分析{language.upper()}代码: {file_path}")
            
            # 读取代码内容
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                code_content = f.read()
            
            # 提取代码结构
            structure = self._extract_structure(code_content, language)
            
            # 计算代码度量
            metrics = self._calculate_metrics(code_content, language)
            
            # 生成摘要和分析
            summary = self._generate_summary(structure, metrics, language)
            analysis = self._generate_analysis(structure, metrics, language)
            
            return CodeAnalysisResult(
                language=language.title(),
                file_name=os.path.basename(file_path),
                content=code_content,
                structure=structure,
                metrics=metrics,
                summary=summary,
                analysis=analysis,
                success=True
            )
            
        except Exception as e:
            print(f"❌ 代码分析失败: {e}")
            import traceback
            traceback.print_exc()
            return CodeAnalysisResult(
                language="Unknown",
                file_name=os.path.basename(file_path),
                content="",
                structure={},
                metrics={},
                summary="",
                analysis="",
                success=False,
                error=str(e)
            )
    
    def _extract_structure(self, code: str, language: str) -> Dict[str, Any]:
        """提取代码结构"""
        structure = {
            "classes": [],
            "functions": [],
            "imports": []
        }
        
        patterns = self.language_patterns.get(language, {})
        
        # 提取类
        if "class_pattern" in patterns:
            classes = re.findall(patterns["class_pattern"], code)
            structure["classes"] = [{"name": cls} for cls in classes if cls]
        
        # 提取函数/方法
        if "function_pattern" in patterns:
            functions = re.findall(patterns["function_pattern"], code)
            # 处理元组结果
            if functions and isinstance(functions[0], tuple):
                functions = [f for group in functions for f in group if f]
            structure["functions"] = [{"name": func} for func in functions if func]
        elif "method_pattern" in patterns:
            methods = re.findall(patterns["method_pattern"], code)
            structure["functions"] = [{"name": m[1] if isinstance(m, tuple) else m} for m in methods]
        
        # 提取导入/包含
        if "import_pattern" in patterns:
            imports = re.findall(patterns["import_pattern"], code)
            structure["imports"] = [{"name": imp} for imp in imports]
        elif "include_pattern" in patterns:
            includes = re.findall(patterns["include_pattern"], code)
            structure["imports"] = [{"name": inc} for inc in includes]
        
        return structure
    
    def _calculate_metrics(self, code: str, language: str) -> Dict[str, Any]:
        """计算代码度量"""
        lines = code.split('\n')
        
        # 根据语言确定注释符号
        comment_patterns = {
            "java": r'^\s*//',
            "javascript": r'^\s*//',
            "cpp": r'^\s*//',
            "c": r'^\s*//',
            "go": r'^\s*//',
            "rust": r'^\s*//'
        }
        
        comment_pattern = comment_patterns.get(language, r'^\s*//')
        
        metrics = {
            "total_lines": len(lines),
            "code_lines": len([line for line in lines if line.strip() and not re.match(comment_pattern, line)]),
            "comment_lines": len([line for line in lines if re.match(comment_pattern, line)]),
            "blank_lines": len([line for line in lines if not line.strip()])
        }
        
        # 统计控制结构
        metrics["if_count"] = len(re.findall(r'\bif\s*\(', code))
        metrics["for_count"] = len(re.findall(r'\bfor\s*\(', code))
        metrics["while_count"] = len(re.findall(r'\bwhile\s*\(', code))
        
        metrics["complexity_score"] = metrics["if_count"] + metrics["for_count"] + metrics["while_count"]
        
        return metrics
    
    def _generate_summary(self, structure: Dict, metrics: Dict, language: str) -> str:
        """生成代码摘要"""
        summary_parts = []
        
        summary_parts.append(f"📊 代码行数: {metrics['total_lines']} 行")
        summary_parts.append(f"  - 有效代码: {metrics['code_lines']} 行")
        summary_parts.append(f"  - 注释: {metrics['comment_lines']} 行")
        
        if structure["imports"]:
            summary_parts.append(f"📦 导入/包含: {len(structure['imports'])} 个")
        
        if structure["classes"]:
            summary_parts.append(f"🏗️ 类定义: {len(structure['classes'])} 个")
        
        if structure["functions"]:
            summary_parts.append(f"⚙️ 函数/方法: {len(structure['functions'])} 个")
        
        if metrics.get("complexity_score", 0) > 0:
            summary_parts.append(f"📈 控制结构: if({metrics.get('if_count', 0)}) for({metrics.get('for_count', 0)}) while({metrics.get('while_count', 0)})")
        
        return "\n".join(summary_parts)
    
    def _generate_analysis(self, structure: Dict, metrics: Dict, language: str) -> str:
        """生成代码分析"""
        analysis_parts = []
        
        if structure["classes"]:
            analysis_parts.append(f"🏗️ 使用{language.upper()}面向对象编程")
        
        if structure["functions"]:
            func_count = len(structure["functions"])
            if func_count > 20:
                analysis_parts.append(f"⚙️ 函数较多 ({func_count}个)，建议考虑模块化")
            else:
                analysis_parts.append(f"⚙️ 函数结构清晰 ({func_count}个)")
        
        # 注释率分析
        if metrics["code_lines"] > 0:
            comment_ratio = metrics["comment_lines"] / metrics["code_lines"] * 100
            if comment_ratio > 20:
                analysis_parts.append(f"📝 注释充分 ({comment_ratio:.1f}%)")
            elif comment_ratio > 10:
                analysis_parts.append(f"📝 注释适中 ({comment_ratio:.1f}%)")
            else:
                analysis_parts.append(f"📝 注释较少 ({comment_ratio:.1f}%)，建议增加文档")
        
        return "\n".join(analysis_parts) if analysis_parts else f"📄 标准{language.upper()}代码"

# 测试函数
def test_code_analyzer():
    """测试代码分析器"""
    print("[TEST] 测试代码分析器...")
    
    # 测试Python分析器
    py_analyzer = PythonCodeAnalyzer()
    print(f"\n{py_analyzer.name} 已创建")
    
    # 测试通用分析器
    general_analyzer = GeneralCodeAnalyzer()
    print(f"{general_analyzer.name} 已创建")
    
    print("\n[OK] 代码分析器初始化成功！")

if __name__ == "__main__":
    test_code_analyzer()

