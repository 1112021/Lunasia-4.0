# -*- coding: utf-8 -*-
"""
HexStrike AI MCP 客户端
连接真实的 HexStrike AI MCP 服务器
仅支持SSH桥接方式（通过Kali Linux）
"""

import json
import os
import time
from typing import Dict, List, Any, Optional

class HexStrikeMCPClient:
    """HexStrike AI MCP 客户端（仅SSH桥接模式）"""
    
    def __init__(self, server_path: str = None, kali_bridge: Any = None, 
                 deepseek_api_key: str = None, deepseek_model: str = "deepseek-chat"):
        """
        初始化 HexStrike MCP 客户端
        
        Args:
            server_path: HexStrike 服务器脚本路径（Kali中的路径，用于自动启动）
            kali_bridge: VMwareKaliBridge 实例（必需）
            deepseek_api_key: DeepSeek API密钥（可选，用于配置HexStrike AI使用DeepSeek模型）
            deepseek_model: DeepSeek模型名称（默认 deepseek-chat）
        """
        self.server_path = server_path
        self.kali_bridge = kali_bridge
        self.deepseek_api_key = deepseek_api_key
        self.deepseek_model = deepseek_model
        self.available_tools = []
        
        if not self.kali_bridge:
            print("⚠️ SSH桥接模式需要kali_bridge实例")
        else:
            print("🔌 使用SSH桥接模式连接HexStrike AI")
            # 如果提供了DeepSeek API密钥，配置HexStrike AI使用DeepSeek
            if self.deepseek_api_key:
                self._configure_deepseek_api()
        
        # 先尝试确保服务器运行（但不强制要求成功）
        server_running = self._ensure_server_running()
        # 无论服务器是否运行，都尝试加载工具列表
        # （可能服务器已手动启动，或者使用默认工具列表）
        self._load_available_tools()
    
    def _configure_deepseek_api(self):
        """配置HexStrike AI使用DeepSeek API"""
        if not self.kali_bridge:
            return
        
        try:
            # 在Kali中设置环境变量或配置文件
            # 假设HexStrike AI通过环境变量读取API配置
            config_cmd = f"export DEEPSEEK_API_KEY='{self.deepseek_api_key}' && export DEEPSEEK_MODEL='{self.deepseek_model}'"
            result = self.kali_bridge.execute_command(config_cmd, timeout=5)
            
            if result.get("success"):
                print(f"✅ 已配置HexStrike AI使用DeepSeek API（模型: {self.deepseek_model}）")
            else:
                print(f"⚠️ 配置DeepSeek API失败: {result.get('stderr', '')}")
        except Exception as e:
            print(f"⚠️ 配置DeepSeek API时出错: {str(e)}")
    
    def _ensure_server_running(self):
        """确保 HexStrike 服务器正在运行（SSH桥接模式）"""
        if not self.kali_bridge:
            print("⚠️ SSH桥接模式需要kali_bridge实例")
            return False
        
        # 检查服务器是否在Kali中运行
        check_cmd = "curl -s http://localhost:8888/health 2>/dev/null || echo 'not_running'"
        result = self.kali_bridge.execute_command(check_cmd, timeout=5)
        
        if result.get("success"):
            stdout = result.get("stdout", "").strip()
            # 检查是否真的在运行（不是"not_running"字符串，且不是错误信息）
            if stdout and "not_running" not in stdout and "Connection refused" not in stdout and "curl:" not in stdout:
                print("✅ HexStrike AI 服务器已在Kali中运行")
                return True
            # 如果返回"not_running"，说明服务器未运行
            elif "not_running" in stdout:
                print("ℹ️ HexStrike AI 服务器在Kali中未运行")
            else:
                print(f"ℹ️ 无法检查服务器状态: {stdout[:100]}")
        
        # 如果服务器未运行，尝试在Kali中启动
        if self.server_path:
            print("🔄 正在在Kali中启动 HexStrike AI 服务器...")
            # 检查服务器脚本是否存在
            check_script = f"test -f {self.server_path} && echo 'exists' || echo 'not_exists'"
            check_result = self.kali_bridge.execute_command(check_script, timeout=5)
            
            if "not_exists" in check_result.get("stdout", ""):
                print(f"⚠️ 服务器脚本不存在: {self.server_path}")
                print(f"💡 提示：请确保HexStrike AI已安装在Kali中，路径正确")
                return False
            
            # 在后台启动服务器（如果配置了DeepSeek API，传递环境变量）
            env_vars = ""
            if self.deepseek_api_key:
                env_vars = f"DEEPSEEK_API_KEY='{self.deepseek_api_key}' DEEPSEEK_MODEL='{self.deepseek_model}' "
            
            start_cmd = f"cd {os.path.dirname(self.server_path)} && {env_vars}nohup python3 {self.server_path} > /tmp/hexstrike.log 2>&1 &"
            start_result = self.kali_bridge.execute_command(start_cmd, timeout=10)
            
            if start_result.get("success"):
                # 等待服务器启动
                time.sleep(5)
                # 再次检查
                check_result = self.kali_bridge.execute_command(check_cmd, timeout=5)
                if "not_running" not in check_result.get("stdout", ""):
                    print("✅ HexStrike AI 服务器已在Kali中启动")
                    return True
                else:
                    print("⚠️ 服务器启动可能失败，请检查日志: /tmp/hexstrike.log")
                    # 尝试获取日志
                    log_cmd = "tail -20 /tmp/hexstrike.log 2>/dev/null || echo '无法读取日志'"
                    log_result = self.kali_bridge.execute_command(log_cmd, timeout=5)
                    if log_result.get("success"):
                        print(f"📋 服务器日志: {log_result.get('stdout', '')[:200]}")
                    return False
            else:
                print(f"⚠️ 无法在Kali中启动服务器: {start_result.get('stderr', '')}")
                return False
        else:
            print("⚠️ SSH桥接模式需要配置server_path（Kali中的服务器路径）")
            print("💡 提示：如果服务器已在Kali中运行，请配置server_path以便自动启动")
            print("💡 或者手动在Kali中启动服务器，然后配置server_path为空（仅用于检查）")
            return False
    
    def _load_available_tools(self):
        """加载可用的工具列表（SSH桥接模式）"""
        if not self.kali_bridge:
            print("⚠️ SSH桥接未初始化，使用默认工具列表")
            self._use_default_tools()
            return
        
        try:
            # 方法1：尝试从 /api/tools/list 获取（如果存在）
            cmd = "curl -s http://localhost:8888/api/tools/list"
            result = self.kali_bridge.execute_command(cmd, timeout=10)
            
            if result.get("success"):
                stdout = result.get("stdout", "")
                if not stdout or "not_running" in stdout or "Connection refused" in stdout:
                    print("⚠️ HexStrike AI 服务器在Kali中未运行")
                    print("💡 提示：请确保服务器已启动，或配置server_path以便自动启动")
                    self._use_default_tools()
                    return
                
                # 检查是否是404错误（HTML响应）
                if "<!doctype html>" in stdout.lower() or "404" in stdout or "Not Found" in stdout:
                    # API端点不存在，尝试从 /health 端点提取工具列表
                    print("ℹ️ /api/tools/list 端点不存在，尝试从 /health 端点提取工具列表")
                    return self._load_tools_from_health()
                
                try:
                    tools_data = json.loads(stdout)
                    self.available_tools = tools_data.get("tools", [])
                    if self.available_tools:
                        print(f"✅ 已加载 {len(self.available_tools)} 个 HexStrike AI 工具（SSH桥接）")
                    else:
                        # 如果工具列表为空，尝试从 /health 提取
                        return self._load_tools_from_health()
                except json.JSONDecodeError as e:
                    # JSON解析失败，可能是HTML错误页面，尝试从 /health 提取
                    print(f"ℹ️ 无法解析工具列表JSON，尝试从 /health 端点提取: {e}")
                    return self._load_tools_from_health()
            else:
                # 如果 /api/tools/list 失败，尝试从 /health 提取
                return self._load_tools_from_health()
        except Exception as e:
            print(f"⚠️ 加载工具列表失败: {e}")
            import traceback
            print(f"📋 错误详情: {traceback.format_exc()}")
            # 尝试从 /health 提取作为后备方案
            return self._load_tools_from_health()
    
    def _load_tools_from_health(self):
        """从 /health 端点提取工具列表"""
        try:
            cmd = "curl -s http://localhost:8888/health"
            result = self.kali_bridge.execute_command(cmd, timeout=10)
            
            if result.get("success"):
                stdout = result.get("stdout", "")
                try:
                    health_data = json.loads(stdout)
                    tools_status = health_data.get("tools_status", {})
                    
                    # 提取所有可用的工具名称（值为True的工具）
                    self.available_tools = [tool_name for tool_name, available in tools_status.items() if available]
                    
                    if self.available_tools:
                        print(f"✅ 已从 /health 端点加载 {len(self.available_tools)} 个可用工具（SSH桥接）")
                    else:
                        print("⚠️ 从 /health 端点未找到可用工具，使用默认工具列表")
                        self._use_default_tools()
                except json.JSONDecodeError as e:
                    print(f"⚠️ 无法解析 /health 响应JSON: {e}")
                    print(f"📋 原始响应: {stdout[:200]}")
                    self._use_default_tools()
            else:
                print("⚠️ 无法从 /health 端点获取工具列表")
                self._use_default_tools()
        except Exception as e:
            print(f"⚠️ 从 /health 提取工具列表失败: {e}")
            self._use_default_tools()
    
    def _use_default_tools(self):
        """使用默认工具列表"""
        self.available_tools = [
            "port_scan", "directory_scan", "subdomain_enum", "web_vuln_scan",
            "sql_injection", "nuclei_scan", "masscan", "wpscan", "hydra",
            "john", "hashcat", "wfuzz", "whatweb", "dnsrecon", "fierce",
            "enum4linux", "smbclient", "crackmapexec", "responder", "tcpdump",
            "netcat", "curl", "wget", "dig", "nslookup", "whois", "searchsploit"
        ]
    
    def call_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        调用 HexStrike AI 工具
        
        Args:
            tool_name: 工具名称
            **kwargs: 工具参数
        
        Returns:
            工具执行结果
        """
        return self._call_tool_ssh(tool_name, **kwargs)
    
    def _call_tool_ssh(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """SSH桥接模式下调用工具"""
        if not self.kali_bridge:
            return {
                "success": False,
                "error": "SSH桥接未初始化",
                "tool": tool_name
            }
        
        # 先检查服务器是否运行
        if not self._is_available_ssh():
            return {
                "success": False,
                "error": "HexStrike AI 服务器在Kali中未运行，请先启动服务器或配置server_path",
                "tool": tool_name
            }
        
        try:
            # 工具名称映射（将通用名称映射到HexStrike AI的实际工具名）
            tool_name_mapping = {
                "port_scan": "nmap",
                "directory_scan": "gobuster",
                "subdomain_enum": "amass",
                "web_vuln_scan": "nuclei",
                "sql_injection": "sqlmap",
                "nuclei_scan": "nuclei",
                "masscan": "masscan",
                "wpscan": "wpscan",
                "hydra": "hydra",
                "john": "john",
                "hashcat": "hashcat",
                "wfuzz": "wfuzz",
                "whatweb": "httpx",  # httpx可以用于Web技术识别
                "dnsrecon": "dnsenum",
                "fierce": "fierce",
                "enum4linux": "enum4linux",
                "smbclient": "netexec",  # netexec包含SMB功能
                "crackmapexec": "netexec",
                "responder": "responder",
                "tcpdump": "tcpdump",
                "netcat": "netcat",
                "curl": "curl",
                "wget": "wget",
                "dig": "dig",
                "nslookup": "nslookup",
                "whois": "whois",
                "searchsploit": "searchsploit",
            }
            
            # 获取实际的工具名称（如果工具名以hexstrike_开头，去掉前缀）
            if tool_name.startswith("hexstrike_"):
                tool_name = tool_name[10:]  # 去掉 "hexstrike_" 前缀
            
            # 映射到实际工具名
            actual_tool_name = tool_name_mapping.get(tool_name, tool_name)
            
            # HexStrike AI 使用 /api/tools/{tool_name} 端点
            endpoint = f"http://localhost:8888/api/tools/{actual_tool_name}"
            
            # 构建JSON payload - 直接传递参数（不包装）
            payload = kwargs
            
            # 尝试不同的payload格式（有些工具可能需要不同的格式）
            payloads = [
                kwargs,  # 直接传递参数
                {"params": kwargs},  # 包装在params中
                {"arguments": kwargs},  # 包装在arguments中
            ]
            
            last_error = None
            for payload in payloads:
                try:
                    payload_json = json.dumps(payload)
                    # 转义单引号以便在shell中使用
                    payload_json_escaped = payload_json.replace("'", "'\\''")
                    
                    # 通过SSH执行curl命令调用API
                    cmd = f"curl -s -X POST {endpoint} -H 'Content-Type: application/json' -d '{payload_json_escaped}'"
                    result = self.kali_bridge.execute_command(cmd, timeout=600)
                    
                    if result.get("success"):
                        stdout = result.get("stdout", "")
                        # 检查是否是连接被拒绝
                        if "Connection refused" in stdout:
                            last_error = "HexStrike AI 服务器在Kali中未运行，请先启动服务器"
                            continue
                        
                        # 检查是否是404错误
                        if "<!doctype html>" in stdout.lower() or "404" in stdout or "Not Found" in stdout:
                            last_error = f"工具 {actual_tool_name} 的端点不存在或工具未安装。请检查工具是否在HexStrike AI中可用"
                            continue
                        
                        # 尝试解析JSON响应
                        try:
                            response_data = json.loads(stdout)
                            # HexStrike AI 可能返回不同的字段名
                            return {
                                "success": response_data.get("success", True),
                                "result": response_data.get("result", response_data.get("output", response_data.get("stdout", response_data.get("data", "")))),
                                "stdout": response_data.get("stdout", response_data.get("output", response_data.get("data", ""))),
                                "stderr": response_data.get("stderr", response_data.get("error", "")),
                                "tool": tool_name
                            }
                        except json.JSONDecodeError:
                            # 如果不是JSON，可能是HTML错误页面或纯文本输出
                            if "<!doctype html>" not in stdout.lower() and "<html" not in stdout.lower():
                                # 可能是纯文本输出，当作成功处理
                                return {
                                    "success": True,
                                    "result": stdout,
                                    "stdout": stdout,
                                    "stderr": "",
                                    "tool": tool_name
                                }
                            else:
                                last_error = f"端点返回非JSON响应: {stdout[:200]}"
                                continue
                    else:
                        error = result.get("error", "")
                        stderr = result.get("stderr", "")
                        stdout = result.get("stdout", "")
                        
                        # 检查是否是连接被拒绝（服务器未运行）
                        if "Connection refused" in stdout or "Connection refused" in stderr or "Connection refused" in error:
                            last_error = "HexStrike AI 服务器在Kali中未运行，请先启动服务器"
                            continue
                        
                        last_error = error or stderr or stdout or "SSH执行失败"
                except Exception as e:
                    last_error = f"调用工具时出错: {str(e)}"
                    continue
            
            # 所有payload格式都失败，返回错误
            return {
                "success": False,
                "error": last_error or f"工具 {actual_tool_name} 执行失败，请检查工具是否已安装",
                "tool": tool_name
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"工具调用异常: {str(e)}",
                "tool": tool_name
            }
    
    def get_tool_status(self) -> str:
        """获取工具状态（SSH桥接模式）"""
        if not self.kali_bridge:
            return "❌ SSH桥接未初始化"
        
        try:
            # 尝试多个状态端点
            endpoints = [
                "http://localhost:8888/api/status",
                "http://localhost:8888/status",
                "http://localhost:8888/health"
            ]
            
            for endpoint in endpoints:
                cmd = f"curl -s {endpoint}"
                result = self.kali_bridge.execute_command(cmd, timeout=10)
                
                if result.get("success"):
                    stdout = result.get("stdout", "")
                    # 检查是否是404错误
                    if "<!doctype html>" in stdout.lower() or "404" in stdout or "Not Found" in stdout:
                        continue  # 尝试下一个端点
                    
                    try:
                        status = json.loads(stdout)
                        return json.dumps(status, ensure_ascii=False, indent=2)
                    except json.JSONDecodeError:
                        if endpoint == endpoints[-1]:  # 最后一个端点
                            return f"❌ 无法解析状态JSON: {stdout[:200]}"
                        continue  # 尝试下一个端点
            
            return f"❌ 所有状态端点都失败: {result.get('stderr', '')}"
        except Exception as e:
            return f"❌ 获取状态失败: {str(e)}"
    
    def list_tools(self) -> List[str]:
        """列出所有可用工具"""
        return self.available_tools
    
    def is_available(self) -> bool:
        """检查 HexStrike AI 是否可用（SSH桥接模式）"""
        return self._is_available_ssh()
    
    def _is_available_ssh(self) -> bool:
        """SSH桥接模式下检查可用性"""
        if not self.kali_bridge:
            return False
        
        try:
            cmd = "curl -s http://localhost:8888/health"
            result = self.kali_bridge.execute_command(cmd, timeout=5)
            return result.get("success", False) and "not_running" not in result.get("stdout", "")
        except:
            return False
    
    def call_intelligence_api(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """
        调用 HexStrike AI 智能端点（用于AI规划攻击链）
        
        Args:
            endpoint: 智能端点名称（如 "analyze-target", "smart-scan", "create-attack-chain"）
            **kwargs: 端点参数
            
        Returns:
            API响应结果
        """
        if not self.kali_bridge:
            return {
                "success": False,
                "error": "SSH桥接未初始化",
                "endpoint": endpoint
            }
        
        # 先检查服务器是否运行
        if not self._is_available_ssh():
            return {
                "success": False,
                "error": "HexStrike AI 服务器在Kali中未运行，请先启动服务器或配置server_path",
                "endpoint": endpoint
            }
        
        try:
            # HexStrike AI 智能端点格式：/api/intelligence/{endpoint}
            api_endpoint = f"http://localhost:8888/api/intelligence/{endpoint}"
            
            # 构建JSON payload
            payload = kwargs
            
            payload_json = json.dumps(payload)
            # 转义单引号以便在shell中使用
            payload_json_escaped = payload_json.replace("'", "'\\''")
            
            # 通过SSH执行curl命令调用API
            cmd = f"curl -s -X POST {api_endpoint} -H 'Content-Type: application/json' -d '{payload_json_escaped}'"
            result = self.kali_bridge.execute_command(cmd, timeout=600)
            
            if result.get("success"):
                stdout = result.get("stdout", "")
                # 检查是否是连接被拒绝
                if "Connection refused" in stdout:
                    return {
                        "success": False,
                        "error": "HexStrike AI 服务器在Kali中未运行，请先启动服务器",
                        "endpoint": endpoint
                    }
                
                # 检查是否是404错误
                if "<!doctype html>" in stdout.lower() or "404" in stdout or "Not Found" in stdout:
                    return {
                        "success": False,
                        "error": f"智能端点 {endpoint} 不存在或不可用",
                        "endpoint": endpoint
                    }
                
                # 尝试解析JSON响应
                try:
                    response_data = json.loads(stdout)
                    
                    # 特殊处理smart-scan端点：它返回scan_results字段，包含combined_output（实际工具执行输出）
                    if endpoint == "smart-scan" and "scan_results" in response_data:
                        scan_results = response_data.get("scan_results", {})
                        # 优先使用combined_output（实际工具执行输出），如果没有则使用整个scan_results
                        combined_output = scan_results.get("combined_output", "")
                        if combined_output:
                            result_text = combined_output
                        else:
                            # 如果没有combined_output，尝试从tools_executed中提取stdout
                            tools_executed = scan_results.get("tools_executed", [])
                            if tools_executed:
                                outputs = []
                                for tool_result in tools_executed:
                                    if tool_result.get("stdout"):
                                        outputs.append(f"=== {tool_result.get('tool', 'unknown').upper()} ===\n{tool_result.get('stdout', '')}")
                                result_text = "\n\n".join(outputs) if outputs else json.dumps(scan_results, ensure_ascii=False, indent=2)
                            else:
                                result_text = json.dumps(scan_results, ensure_ascii=False, indent=2)
                        
                        return {
                            "success": response_data.get("success", True),
                            "result": result_text,
                            "scan_results": scan_results,
                            "combined_output": combined_output,
                            "tools_executed": scan_results.get("tools_executed", []),
                            "execution_summary": scan_results.get("execution_summary", {}),
                            "data": response_data,
                            "endpoint": endpoint
                        }
                    
                    # 默认处理：提取result字段
                    return {
                        "success": response_data.get("success", True),
                        "result": response_data.get("result", response_data.get("output", response_data.get("data", response_data.get("attack_chain", response_data.get("analysis", ""))))),
                        "attack_chain": response_data.get("attack_chain", []),
                        "analysis": response_data.get("analysis", ""),
                        "recommendations": response_data.get("recommendations", []),
                        "data": response_data,
                        "endpoint": endpoint
                    }
                except json.JSONDecodeError:
                    # 如果不是JSON，可能是HTML错误页面或纯文本输出
                    if "<!doctype html>" not in stdout.lower() and "<html" not in stdout.lower():
                        # 可能是纯文本输出，当作成功处理
                        return {
                            "success": True,
                            "result": stdout,
                            "data": {"output": stdout},
                            "endpoint": endpoint
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"无法解析响应JSON: {stdout[:200]}",
                            "endpoint": endpoint
                        }
            else:
                error = result.get("error", "")
                stderr = result.get("stderr", "")
                stdout = result.get("stdout", "")
                
                # 检查是否是连接被拒绝（服务器未运行）
                if "Connection refused" in stdout or "Connection refused" in stderr or "Connection refused" in error:
                    error_msg = "HexStrike AI 服务器在Kali中未运行，请先启动服务器"
                elif not stderr and not stdout and not error:
                    error_msg = "SSH执行失败，但无错误信息"
                else:
                    error_msg = error or stderr or stdout or "SSH执行失败"
                
                return {
                    "success": False,
                    "error": error_msg,
                    "endpoint": endpoint
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"调用智能端点异常: {str(e)}",
                "endpoint": endpoint
            }
    
    def analyze_target(self, target: str, analysis_type: str = "comprehensive") -> Dict[str, Any]:
        """
        分析目标（使用HexStrike AI的智能分析）
        
        Args:
            target: 目标（IP、域名或URL）
            analysis_type: 分析类型（comprehensive, quick, deep）
            
        Returns:
            分析结果
        """
        return self.call_intelligence_api("analyze-target", target=target, analysis_type=analysis_type)
    
    def smart_scan(self, target: str, scan_type: str = "comprehensive") -> Dict[str, Any]:
        """
        智能扫描（使用HexStrike AI的智能扫描）
        
        Args:
            target: 目标（IP、域名或URL）
            scan_type: 扫描类型（实际会映射为objective参数）
            
        Returns:
            扫描结果
        """
        # 注意：smart-scan端点使用objective参数，不是scan_type
        return self.call_intelligence_api("smart-scan", target=target, objective=scan_type)
    
    def create_attack_chain(self, target: str, objective: str = None) -> Dict[str, Any]:
        """
        创建攻击链（使用HexStrike AI的智能规划）
        
        Args:
            target: 目标（IP、域名或URL）
            objective: 攻击目标（可选，如"获取敏感信息"、"提权"等）
            
        Returns:
            攻击链结果
        """
        params = {"target": target}
        if objective:
            params["objective"] = objective
        return self.call_intelligence_api("create-attack-chain", **params)
    
    def comprehensive_assessment(self, target: str) -> Dict[str, Any]:
        """
        综合评估（Bug Bounty综合评估）
        
        Args:
            target: 目标（IP、域名或URL）
            
        Returns:
            评估结果
        """
        # 注意：comprehensive-assessment端点在 /api/bugbounty/ 路径下，且需要domain参数
        if not self.kali_bridge:
            return {
                "success": False,
                "error": "SSH桥接未初始化",
                "endpoint": "comprehensive-assessment"
            }
        
        # 先检查服务器是否运行
        if not self._is_available_ssh():
            return {
                "success": False,
                "error": "HexStrike AI 服务器在Kali中未运行，请先启动服务器或配置server_path",
                "endpoint": "comprehensive-assessment"
            }
        
        try:
            # Bug Bounty端点格式：/api/bugbounty/comprehensive-assessment
            api_endpoint = f"http://localhost:8888/api/bugbounty/comprehensive-assessment"
            
            # 构建JSON payload - 使用domain参数而不是target
            payload = {"domain": target}
            
            payload_json = json.dumps(payload)
            # 转义单引号以便在shell中使用
            payload_json_escaped = payload_json.replace("'", "'\\''")
            
            # 通过SSH执行curl命令调用API
            cmd = f"curl -s -X POST {api_endpoint} -H 'Content-Type: application/json' -d '{payload_json_escaped}'"
            result = self.kali_bridge.execute_command(cmd, timeout=600)
            
            if result.get("success"):
                stdout = result.get("stdout", "")
                # 检查是否是连接被拒绝
                if "Connection refused" in stdout:
                    return {
                        "success": False,
                        "error": "HexStrike AI 服务器在Kali中未运行，请先启动服务器",
                        "endpoint": "comprehensive-assessment"
                    }
                
                # 检查是否是404错误
                if "<!doctype html>" in stdout.lower() or "404" in stdout or "Not Found" in stdout:
                    return {
                        "success": False,
                        "error": f"智能端点 comprehensive-assessment 不存在或不可用",
                        "endpoint": "comprehensive-assessment"
                    }
                
                # 尝试解析JSON响应
                try:
                    response_data = json.loads(stdout)
                    return {
                        "success": response_data.get("success", True),
                        "result": response_data.get("result", response_data.get("assessment", response_data.get("data", ""))),
                        "assessment": response_data.get("assessment", {}),
                        "data": response_data,
                        "endpoint": "comprehensive-assessment"
                    }
                except json.JSONDecodeError:
                    # 如果不是JSON，可能是HTML错误页面或纯文本输出
                    if "<!doctype html>" not in stdout.lower() and "<html" not in stdout.lower():
                        # 可能是纯文本输出，当作成功处理
                        return {
                            "success": True,
                            "result": stdout,
                            "data": {"output": stdout},
                            "endpoint": "comprehensive-assessment"
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"无法解析响应JSON: {stdout[:200]}",
                            "endpoint": "comprehensive-assessment"
                        }
            else:
                error = result.get("error", "")
                stderr = result.get("stderr", "")
                stdout = result.get("stdout", "")
                
                # 检查是否是连接被拒绝（服务器未运行）
                if "Connection refused" in stdout or "Connection refused" in stderr or "Connection refused" in error:
                    error_msg = "HexStrike AI 服务器在Kali中未运行，请先启动服务器"
                elif not stderr and not stdout and not error:
                    error_msg = "SSH执行失败，但无错误信息"
                else:
                    error_msg = error or stderr or stdout or "SSH执行失败"
                
                return {
                    "success": False,
                    "error": error_msg,
                    "endpoint": "comprehensive-assessment"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"调用智能端点异常: {str(e)}",
                "endpoint": "comprehensive-assessment"
            }
    
    def execute_attack_chain(self, target: str, objective: str = None, attack_chain: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        执行攻击链（规划并执行，返回执行报告）
        
        Args:
            target: 目标（IP、域名或URL）
            objective: 攻击目标/任务描述
            attack_chain: 已规划的攻击链（如果提供，直接执行；否则先规划）
            
        Returns:
            执行报告
        """
        print("=" * 60)
        print("🎯 [HexStrike Client] execute_attack_chain 开始")
        print(f"   📍 目标: {target}")
        print(f"   📝 任务描述: {objective[:100] if objective else 'N/A'}...")
        print(f"   🔗 攻击链: {'已提供' if attack_chain else '未提供（将先规划）'}")
        print("=" * 60)
        
        # 如果没有提供攻击链，先规划
        plan_result = None
        if not attack_chain:
            if not target:
                print("❌ [HexStrike Client] 未提供攻击链或目标")
                return {
                    "success": False,
                    "error": "未提供攻击链或目标"
                }
            # 先规划攻击链
            print("📋 [步骤1] 调用 create_attack_chain 进行规划...")
            plan_result = self.create_attack_chain(target, objective)
            print(f"📋 [步骤1] 规划结果: 成功={plan_result.get('success', False)}")
            if not plan_result.get("success"):
                print(f"❌ [步骤1] 规划失败: {plan_result.get('error', '未知错误')}")
                print("🔄 [降级] 规划失败，将跳过规划步骤，直接尝试执行端点或降级到智能端点...")
                # 不直接返回，继续执行降级逻辑
                plan_result = None
                attack_chain = None
            else:
                attack_chain = plan_result.get("attack_chain") or plan_result.get("data", {})
                print(f"📋 [步骤1] 已获取攻击链规划，包含 {len(attack_chain) if isinstance(attack_chain, (list, dict)) else 'N/A'} 个步骤/工具")
        
        # 检查规划结果是否已经包含执行信息
        # 注意：create-attack-chain通常只返回规划信息，不包含实际执行结果
        # 只有真正包含工具执行输出时才跳过执行步骤
        if plan_result and plan_result.get("success"):
            plan_data = plan_result.get("data", {})
            result_text = str(plan_result.get("result", ""))
            
            # 检查是否已经包含执行结果（多种可能的字段名）
            has_execution_results = (
                "execution_results" in plan_data or 
                "results" in plan_data or 
                "report" in plan_data or
                "output" in plan_data or
                "execution_report" in plan_data or
                "attack_results" in plan_data
            )
            
            # 严格检查：规划结果通常包含estimated_time、required_tools等字段
            # 如果包含这些规划字段但没有执行结果字段，说明只是规划，不是执行结果
            has_planning_fields = (
                "estimated_time" in plan_data or
                "required_tools" in plan_data or
                "attack_chain" in plan_data
            )
            
            # 如果只有规划字段，没有执行结果字段，明确判断为规划结果
            # 关键：如果包含estimated_time或required_tools，说明是规划结果，不是执行结果
            is_planning_only = has_planning_fields and not has_execution_results
            
            # 检查result字段是否包含实际的工具执行输出（不只是规划描述）
            # 实际执行结果通常包含：端口号、服务信息、HTML内容、扫描结果等
            # 注意：如果is_planning_only为True，说明是规划结果，不应该再检查执行输出
            has_actual_execution_output = False
            if result_text and not is_planning_only:
                # 检查是否包含实际的执行输出特征（必须是工具的实际输出，不是工具名称列表）
                execution_indicators = [
                    r'\d+/\w+\s+open\s+\w+',  # 端口扫描结果：80/tcp open http
                    r'PORT\s+STATE\s+SERVICE',  # nmap扫描报告头
                    r'Nmap scan report',  # nmap扫描报告
                    r'<html[^>]*>',  # HTML内容（完整的HTML标签）
                    r'HTTP/\d\.\d\s+\d+\s+\w+',  # HTTP响应：HTTP/1.1 200 OK
                    r'status:\s*\d{3}',  # HTTP状态码：status: 200
                    r'vulnerability.*found',  # 漏洞发现
                    r'CVE-\d{4}-\d+',  # CVE编号格式
                    r'Starting Nmap',  # nmap开始扫描
                    r'Host is up',  # 主机在线
                    r'Not shown: \d+ closed ports',  # nmap端口统计
                ]
                import re
                for pattern in execution_indicators:
                    if re.search(pattern, result_text, re.IGNORECASE):
                        has_actual_execution_output = True
                        print(f"   ✅ 找到执行输出特征: {pattern}")
                        break
            
            print(f"   - 包含执行结果字段: {has_execution_results}")
            print(f"   - 包含规划字段: {has_planning_fields}")
            print(f"   - 仅包含规划信息（无执行结果）: {is_planning_only}")
            print(f"   - 包含实际执行输出: {has_actual_execution_output}")
            
            # 只有真正包含执行结果时才跳过执行步骤
            # 如果只有规划字段，必须执行攻击链
            if is_planning_only:
                print("ℹ️ [步骤2] 这是规划结果（包含estimated_time/required_tools），不包含执行结果，需要执行攻击链")
            elif has_execution_results or has_actual_execution_output:
                # 规划结果已经包含执行信息，直接返回
                print("✅ [步骤2] 规划结果已包含执行信息，直接返回")
                print("=" * 60)
                return {
                    "success": True,
                    "result": plan_result.get("result", json.dumps(plan_data, ensure_ascii=False, indent=2)),
                    "attack_chain": plan_result.get("attack_chain", []),
                    "data": plan_data
                }
            else:
                # 规划结果不包含执行信息，必须执行攻击链
                print("ℹ️ [步骤2] 规划结果不包含执行信息，需要执行攻击链")
        
        # 执行攻击链
        # 尝试不同的执行端点
        print("🚀 [步骤3] 开始执行攻击链...")
        endpoints = [
            "execute-attack-chain",
            "run-attack-chain",
            "execute-chain"
        ]
        
        last_error = None
        for i, endpoint in enumerate(endpoints, 1):
            print(f"   🔄 [尝试 {i}/{len(endpoints)}] 调用端点: {endpoint}")
            try:
                result = self.call_intelligence_api(endpoint, attack_chain=attack_chain, target=target, objective=objective)
                if result.get("success"):
                    print(f"   ✅ [尝试 {i}] 端点 {endpoint} 执行成功")
                    print("=" * 60)
                    return result
                else:
                    last_error = result.get("error", "未知错误")
                    print(f"   ❌ [尝试 {i}] 端点 {endpoint} 执行失败: {last_error}")
            except Exception as e:
                last_error = str(e)
                print(f"   ❌ [尝试 {i}] 端点 {endpoint} 异常: {last_error}")
                continue
        
        # 如果所有执行端点都失败，直接调用HexStrike AI的智能端点，让它自己处理
        # 框架Agent只负责传递请求，不参与工具选择和执行
        if target:
            print("=" * 60)
            print("🔧 [步骤4] 所有执行端点都失败，调用HexStrike AI智能端点处理")
            print("   💡 让HexStrike AI自己决定如何规划和执行，框架Agent只负责传递请求")
            print("=" * 60)
            
            # 根据任务类型选择更合适的降级端点
            # 分析objective和target，判断任务类型
            task_type = self._analyze_task_type(target, objective)
            print(f"   🎯 任务类型分析: {task_type}")
            
            # 根据任务类型选择优先端点
            if task_type in ["html_source", "web_request", "port_scan", "web_scan"]:
                # HTML源码、Web请求、端口扫描、Web扫描 → 优先使用smart-scan（会实际执行工具）
                print("   💡 任务类型适合使用smart-scan（会实际执行工具）")
                try:
                    print("   🔄 尝试 smart-scan...")
                    scan_result = self.smart_scan(target, scan_type=objective or "comprehensive")
                    if scan_result.get("success"):
                        print("   ✅ smart-scan 执行成功")
                        print("=" * 60)
                        return scan_result
                    else:
                        last_error = scan_result.get("error", "smart-scan失败")
                        print(f"   ❌ smart-scan 失败: {last_error}")
                except Exception as e:
                    last_error = f"smart-scan异常: {str(e)}"
                    print(f"   ❌ smart-scan 异常: {last_error}")
                
                # 如果smart-scan失败，尝试comprehensive-assessment
                try:
                    print("   🔄 尝试 comprehensive-assessment（降级）...")
                    assessment_result = self.comprehensive_assessment(target)
                    if assessment_result.get("success"):
                        print("   ✅ comprehensive-assessment 执行成功")
                        print("=" * 60)
                        return assessment_result
                    else:
                        last_error = assessment_result.get("error", "comprehensive-assessment失败")
                        print(f"   ❌ comprehensive-assessment 失败: {last_error}")
                except Exception as e:
                    last_error = f"comprehensive-assessment异常: {str(e)}"
                    print(f"   ❌ comprehensive-assessment 异常: {last_error}")
            else:
                # 综合评估、Bug Bounty等 → 优先使用comprehensive-assessment
                print("   💡 任务类型适合使用comprehensive-assessment（综合评估）")
                try:
                    print("   🔄 尝试 comprehensive-assessment...")
                    assessment_result = self.comprehensive_assessment(target)
                    if assessment_result.get("success"):
                        print("   ✅ comprehensive-assessment 执行成功")
                        print("=" * 60)
                        return assessment_result
                    else:
                        last_error = assessment_result.get("error", "comprehensive-assessment失败")
                        print(f"   ❌ comprehensive-assessment 失败: {last_error}")
                except Exception as e:
                    last_error = f"comprehensive-assessment异常: {str(e)}"
                    print(f"   ❌ comprehensive-assessment 异常: {last_error}")
                
                # 如果comprehensive-assessment失败，尝试smart-scan
                try:
                    print("   🔄 尝试 smart-scan（降级）...")
                    scan_result = self.smart_scan(target, scan_type=objective or "comprehensive")
                    if scan_result.get("success"):
                        print("   ✅ smart-scan 执行成功")
                        print("=" * 60)
                        return scan_result
                    else:
                        last_error = scan_result.get("error", "smart-scan失败")
                        print(f"   ❌ smart-scan 失败: {last_error}")
                except Exception as e:
                    last_error = f"smart-scan异常: {str(e)}"
                    print(f"   ❌ smart-scan 异常: {last_error}")

        # 如果所有方法都失败，返回错误
        print("=" * 60)
        print("❌ [最终] 所有执行方法都失败")
        print(f"   错误信息: {last_error or '所有执行端点都不可用'}")
        print("=" * 60)
        return {
            "success": False,
            "error": f"无法执行攻击链：{last_error or '所有执行端点都不可用'}"
        }
    
    def _analyze_task_type(self, target: str, objective: str = None) -> str:
        """
        分析任务类型，用于选择更合适的降级端点
        
        Args:
            target: 目标
            objective: 任务描述
            
        Returns:
            任务类型：html_source, web_request, port_scan, web_scan, comprehensive, unknown
        """
        if not objective:
            objective = ""
        
        # 转换为小写以便匹配
        target_lower = str(target).lower()
        objective_lower = str(objective).lower()
        combined = f"{target_lower} {objective_lower}"
        
        # HTML源码相关
        if any(keyword in combined for keyword in ["html", "源码", "source", "view-source"]):
            return "html_source"
        
        # 端口扫描相关
        if any(keyword in combined for keyword in ["端口", "port", "开放端口", "端口扫描"]):
            return "port_scan"
        
        # Web漏洞扫描相关
        if any(keyword in combined for keyword in ["漏洞", "vulnerability", "vuln", "web漏洞", "web扫描"]):
            return "web_scan"
        
        # Web请求相关（但不包含HTML源码）
        if any(keyword in combined for keyword in ["http", "https", "web", "api", "请求"]):
            return "web_request"
        
        # 综合评估相关
        if any(keyword in combined for keyword in ["综合", "comprehensive", "评估", "assessment", "安全状况", "安全分析"]):
            return "comprehensive"
        
        # 默认返回unknown，将使用comprehensive-assessment
        return "unknown"
    
    def close(self):
        """关闭客户端"""
        # SSH桥接模式下不需要关闭本地进程
        pass
