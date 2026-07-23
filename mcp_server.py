# -*- coding: utf-8 -*-
"""
本地MCP服务器
提供各种工具功能供露尼西亚调用
"""

import json
import os
import sys
import subprocess
import platform
import datetime
from typing import Dict, List, Any, Optional

class LocalMCPServer:
    """本地MCP服务器 - 简化版本"""
    
    def __init__(self):
        self.tools = {
            "get_system_info": self.get_system_info,
            "list_files": self.list_files,
            "read_file": self.read_file,
            "write_file": self.write_file,
            "create_folder": self.create_folder,
            "execute_command": self.execute_command,
            "get_process_list": self.get_process_list,
            "create_note": self.create_note,
            "list_notes": self.list_notes,
            "search_notes": self.search_notes,
            "get_weather_info": self.get_weather_info,
            "calculate": self.calculate,
            "get_memory_stats": self.get_memory_stats
        }
        
        # 初始化 Kali Linux 桥接（如果已启用）
        self.kali_bridge = None
        self._init_kali_bridge()
        
        # 初始化真实的 HexStrike AI MCP 客户端（唯一工具集）
        self.hexstrike_mcp_client = None
        self._init_hexstrike_ai()
        
        # 加载自定义工具
        self.load_custom_tools()
    
    def get_system_info(self) -> str:
        """获取系统信息"""
        info = {
            "platform": platform.system(),
            "platform_version": platform.version(),
            "architecture": platform.architecture()[0],
            "processor": platform.processor(),
            "python_version": sys.version,
            "current_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        return json.dumps(info, ensure_ascii=False, indent=2)
    
    def list_files(self, directory: str = ".") -> str:
        """列出指定目录的文件"""
        try:
            if not os.path.exists(directory):
                return f"目录不存在: {directory}"
            
            files = []
            for item in os.listdir(directory):
                item_path = os.path.join(directory, item)
                if os.path.isfile(item_path):
                    size = os.path.getsize(item_path)
                    files.append(f"文件: {item} ({size} bytes)")
                elif os.path.isdir(item_path):
                    files.append(f"目录: {item}/")
            
            return f"目录 {directory} 的内容:\n" + "\n".join(files)
        except Exception as e:
            return f"列出文件失败: {str(e)}"
    
    def read_file(self, file_path: str) -> str:
        """读取文件内容"""
        try:
            if not os.path.exists(file_path):
                return f"文件不存在: {file_path}"
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return f"文件 {file_path} 的内容:\n{content}"
        except Exception as e:
            return f"读取文件失败: {str(e)}"
    
    def write_file(self, file_path: str, content: str) -> str:
        """写入文件内容"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return f"文件 {file_path} 写入成功"
        except Exception as e:
            return f"写入文件失败: {str(e)}"
    
    def create_folder(self, folder_path: str) -> str:
        """创建文件夹"""
        try:
            # 检查文件夹是否已存在
            if os.path.exists(folder_path):
                if os.path.isdir(folder_path):
                    return f"文件夹 {folder_path} 已存在"
                else:
                    return f"路径 {folder_path} 已存在，但不是文件夹"
            
            # 创建文件夹（包括父目录）
            os.makedirs(folder_path, exist_ok=True)
            
            return f"文件夹 {folder_path} 创建成功"
        except Exception as e:
            return f"创建文件夹失败: {str(e)}"
    
    def execute_command(self, command: str) -> str:
        """执行系统命令"""
        try:
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True, 
                timeout=30
            )
            
            output = {
                "command": command,
                "return_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
            
            return json.dumps(output, ensure_ascii=False, indent=2)
        except subprocess.TimeoutExpired:
            return f"命令执行超时: {command}"
        except Exception as e:
            return f"执行命令失败: {str(e)}"
    
    def get_process_list(self) -> str:
        """获取进程列表"""
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    "tasklist", 
                    capture_output=True, 
                    text=True
                )
            else:
                result = subprocess.run(
                    "ps aux", 
                    capture_output=True, 
                    text=True
                )
            
            return f"进程列表:\n{result.stdout}"
        except Exception as e:
            return f"获取进程列表失败: {str(e)}"
    
    def create_note(self, title: str, content: str, filename_format: str = "timestamp", location: str = None) -> str:
        """创建笔记"""
        try:
            # 确定保存位置
            if location:
                # 用户指定了位置
                if location.lower() in ["d盘", "d:", "d:/", "d:\\"]:
                    save_dir = "D:/"
                elif location.lower() in ["c盘", "c:", "c:/", "c:\\"]:
                    save_dir = "C:/"
                elif location.lower() in ["e盘", "e:", "e:/", "e:\\"]:
                    save_dir = "E:/"
                elif location.lower() in ["f盘", "f:", "f:/", "f:\\"]:
                    save_dir = "F:/"
                else:
                    # 尝试解析其他路径
                    save_dir = location
            else:
                # 默认保存到notes目录
                save_dir = "notes"
            
            # 确保目录存在
            os.makedirs(save_dir, exist_ok=True)
            
            # 根据文件名格式设置生成文件名
            if filename_format == "simple":
                # 简单格式：直接使用标题作为文件名
                filename = os.path.join(save_dir, f"{title}.txt")
                
                # 检查文件是否已存在，如果存在则添加数字后缀
                counter = 1
                original_filename = filename
                while os.path.exists(filename):
                    name_without_ext = original_filename[:-4]  # 移除.txt
                    filename = f"{name_without_ext}_{counter}.txt"
                    counter += 1
            else:
                # 时间戳格式：使用时间戳+标题
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(save_dir, f"{timestamp}_{title}.txt")
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"标题: {title}\n")
                f.write(f"创建时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"内容:\n{content}\n")
            
            return f"笔记已创建: {filename}"
        except Exception as e:
            return f"创建笔记失败: {str(e)}"
    
    def list_notes(self) -> str:
        """列出所有笔记"""
        try:
            notes_dir = "notes"
            if not os.path.exists(notes_dir):
                return "没有找到笔记目录"
            
            notes = []
            for file in os.listdir(notes_dir):
                if file.endswith('.txt'):
                    file_path = os.path.join(notes_dir, file)
                    stat = os.stat(file_path)
                    notes.append(f"{file} (大小: {stat.st_size} bytes, 修改时间: {datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')})")
            
            if notes:
                return "笔记列表:\n" + "\n".join(notes)
            else:
                return "没有找到笔记"
        except Exception as e:
            return f"列出笔记失败: {str(e)}"
    
    def search_notes(self, keyword: str) -> str:
        """搜索笔记内容"""
        try:
            notes_dir = "notes"
            if not os.path.exists(notes_dir):
                return "没有找到笔记目录"
            
            results = []
            for file in os.listdir(notes_dir):
                if file.endswith('.txt'):
                    file_path = os.path.join(notes_dir, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            if keyword.lower() in content.lower():
                                results.append(f"找到关键词 '{keyword}' 在文件: {file}")
                    except:
                        continue
            
            if results:
                return "搜索结果:\n" + "\n".join(results)
            else:
                return f"没有找到包含关键词 '{keyword}' 的笔记"
        except Exception as e:
            return f"搜索笔记失败: {str(e)}"
    
    def get_weather_info(self, city: str = "北京") -> str:
        """获取天气信息（使用和风天气API）"""
        try:
            import requests
            
            # 获取和风天气API密钥
            api_key = self.get_heweather_key()
            if not api_key:
                return "和风天气API密钥未配置，无法获取天气信息"
            
            # 调用和风天气API
            url = f"https://api.heweather.com/v3/weather/now"
            params = {
                "location": city,
                "key": api_key,
                "lang": "zh"
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get("status") == "ok" and data.get("HeWeather3"):
                weather_data = data["HeWeather3"][0]
                now = weather_data.get("now", {})
                basic = weather_data.get("basic", {})
                update = weather_data.get("update", {})
                
                result = {
                    "city": basic.get("location", city),
                    "region": basic.get("admin_area", ""),
                    "country": basic.get("cnty", ""),
                    "weather": now.get("cond_txt", "未知"),
                    "temperature": f"{now.get('tmp', 'N/A')}°C",
                    "feels_like": f"{now.get('fl', 'N/A')}°C",
                    "wind_direction": now.get("wind_dir", "未知"),
                    "wind_scale": f"{now.get('wind_sc', 'N/A')}级",
                    "wind_speed": f"{now.get('wind_spd', 'N/A')}km/h",
                    "humidity": f"{now.get('hum', 'N/A')}%",
                    "precipitation": f"{now.get('pcpn', 'N/A')}mm",
                    "visibility": f"{now.get('vis', 'N/A')}km",
                    "cloud_cover": f"{now.get('cloud', 'N/A')}%",
                    "update_time": update.get("loc", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                }
                
                return json.dumps(result, ensure_ascii=False, indent=2)
            else:
                return f"获取{city}天气信息失败: {data.get('status', '未知错误')}"
                
        except Exception as e:
            return f"获取天气信息失败: {str(e)}"
    
    def get_heweather_key(self):
        """获取和风天气API密钥"""
        try:
            # 从配置文件读取API密钥
            if os.path.exists("ai_agent_config.json"):
                with open("ai_agent_config.json", "r", encoding="utf-8") as f:
                    config = json.load(f)
                    return config.get("heweather_key", "")
        except:
            pass
        return ""
    
    def calculate_distance(self, location1: str, location2: str) -> str:
        """计算两个地点之间的距离（使用高德地图API）"""
        try:
            import requests
            
            # 高德地图API密钥（需要用户配置）
            api_key = self.get_amap_key()
            if not api_key:
                return "高德地图API密钥未配置，无法计算距离"
            
            # 地理编码API获取坐标
            def get_coordinates(address):
                url = f"https://restapi.amap.com/v3/geocode/geo"
                params = {
                    "address": address,
                    "key": api_key,
                    "output": "json"
                }
                response = requests.get(url, params=params, timeout=10)
                data = response.json()
                
                if data["status"] == "1" and data["geocodes"]:
                    location = data["geocodes"][0]["location"]
                    return location.split(",")
                return None
            
            # 获取两个地点的坐标
            coords1 = get_coordinates(location1)
            coords2 = get_coordinates(location2)
            
            if not coords1 or not coords2:
                return f"无法获取地点坐标：{location1} 或 {location2}"
            
            # 计算直线距离
            from math import radians, cos, sin, asin, sqrt
            
            def haversine_distance(lat1, lon1, lat2, lon2):
                """使用Haversine公式计算两点间的直线距离"""
                # 将经纬度转换为弧度
                lat1, lon1, lat2, lon2 = map(radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
                
                # Haversine公式
                dlat = lat2 - lat1
                dlon = lon2 - lon1
                a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                c = 2 * asin(sqrt(a))
                r = 6371  # 地球半径（公里）
                return c * r
            
            distance = haversine_distance(coords1[1], coords1[0], coords2[1], coords2[0])
            
            result = {
                "location1": location1,
                "location2": location2,
                "coordinates1": coords1,
                "coordinates2": coords2,
                "distance_km": round(distance, 2),
                "distance_m": round(distance * 1000, 0),
                "calculation_type": "直线距离（Haversine公式）",
                "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            return f"计算距离失败: {str(e)}"
    
    def get_amap_key(self):
        """获取高德地图API密钥"""
        try:
            # 从配置文件读取API密钥
            if os.path.exists("ai_agent_config.json"):
                with open("ai_agent_config.json", "r", encoding="utf-8") as f:
                    config = json.load(f)
                    api_key = config.get("amap_key", "")
                    # 如果API密钥为空或为占位符，返回空字符串
                    if not api_key or api_key == "MYKEY" or api_key == "mykey":
                        return ""
                    return api_key
        except Exception as e:
            print(f"读取高德地图API密钥失败: {str(e)}")
        return ""
    
    def calculate(self, expression: str) -> str:
        """计算数学表达式"""
        try:
            # 安全计算，只允许基本数学运算
            allowed_chars = set('0123456789+-*/(). ')
            if not all(c in allowed_chars for c in expression):
                return "表达式包含不允许的字符"
            
            result = eval(expression)
            return f"计算结果: {expression} = {result}"
        except Exception as e:
            return f"计算失败: {str(e)}"
    
    def get_memory_stats(self) -> str:
        """获取记忆系统统计信息"""
        try:
            memory_file = "memory_lake.json"
            if os.path.exists(memory_file):
                with open(memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        total_topics = len(data)
                    elif isinstance(data, dict):
                        total_topics = len(data.get("topics", []))
                    else:
                        total_topics = 0
            else:
                total_topics = 0
            
            chat_logs_dir = "chat_logs"
            total_log_files = len([f for f in os.listdir(chat_logs_dir) if f.endswith('.json')]) if os.path.exists(chat_logs_dir) else 0
            
            stats = {
                "total_topics": total_topics,
                "total_log_files": total_log_files,
                "memory_file_size": os.path.getsize(memory_file) if os.path.exists(memory_file) else 0
            }
            
            return json.dumps(stats, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"获取记忆统计失败: {str(e)}"
    
    def call_tool(self, tool_name: str, **kwargs) -> str:
        """调用工具"""
        if tool_name in self.tools:
            try:
                # 添加调试信息
                if tool_name.startswith("hexstrike_"):
                    print(f"🔧 [工具调用] {tool_name} 参数: {kwargs}")
                return self.tools[tool_name](**kwargs)
            except Exception as e:
                import traceback
                error_msg = f"调用工具失败: {str(e)}\n{traceback.format_exc()[:300]}"
                print(f"❌ [工具调用错误] {tool_name}: {error_msg}")
                return error_msg
        else:
            # 列出相似的工具名称以便调试
            similar_tools = [k for k in self.tools.keys() if tool_name.lower() in k.lower() or k.lower() in tool_name.lower()][:5]
            error_msg = f"工具不存在: {tool_name}"
            if similar_tools:
                error_msg += f"\n相似的工具: {', '.join(similar_tools)}"
            print(f"❌ [工具不存在] {tool_name}")
            return error_msg
    
    def list_tools(self) -> List[str]:
        """列出可用工具"""
        return list(self.tools.keys())
    
    def get_tool_info(self, tool_name: str) -> Dict[str, Any]:
        """获取工具信息"""
        if tool_name in self.tools:
            return {
                "name": tool_name,
                "description": self.tools[tool_name].__doc__ or "无描述"
            }
        return {}
    
    def load_custom_tools(self):
        """加载自定义工具"""
        try:
            if os.path.exists("custom_tools.json"):
                with open("custom_tools.json", "r", encoding="utf-8") as f:
                    custom_tools = json.load(f)
                    for tool_name, tool_info in custom_tools.items():
                        if tool_info.get("type") == "custom":
                            # 动态创建工具函数
                            self.create_custom_tool(tool_name, tool_info)
        except Exception as e:
            print(f"加载自定义工具失败: {str(e)}")
    
    def create_custom_tool(self, tool_name, tool_info):
        """创建自定义工具"""
        try:
            # 创建工具函数的命名空间
            namespace = {}
            
            # 执行工具代码
            exec(tool_info["code"], namespace)
            
            # 创建包装函数
            def tool_wrapper(**kwargs):
                # 根据工具名称和参数判断调用哪个函数
                if tool_name == "智能文件分析":
                    # 文件分析工具
                    if 'file_path' in kwargs:
                        if 'analyze_file_content' in namespace:
                            # 直接调用analyze_file_content返回JSON格式
                            return namespace['analyze_file_content'](kwargs['file_path'])
                        elif 'upload_and_analyze_file' in namespace:
                            return namespace['upload_and_analyze_file'](kwargs['file_path'])
                        else:
                            return "文件分析功能未找到"
                    else:
                        return "请提供file_path参数"
                elif 'location1' in kwargs and 'location2' in kwargs:
                    # 调用距离计算函数
                    if 'calculate_distance' in namespace:
                        return namespace['calculate_distance'](kwargs['location1'], kwargs['location2'])
                elif 'keyword' in kwargs:
                    # 调用兴趣点搜索函数
                    if 'search_poi' in namespace:
                        city = kwargs.get('city', '北京')
                        return namespace['search_poi'](kwargs['keyword'], city)
                elif 'city' in kwargs and 'keyword' not in kwargs:
                    # 调用天气预报函数
                    if 'get_weather_forecast' in namespace:
                        return namespace['get_weather_forecast'](kwargs['city'])
                else:
                    return f"参数错误，请提供正确的参数。可用功能：距离计算(location1, location2)、兴趣点搜索(keyword, city)、天气预报(city)、文件分析(file_path)"
            
            # 将包装函数添加到工具列表
            self.tools[tool_name] = tool_wrapper
            
        except Exception as e:
            print(f"创建自定义工具 {tool_name} 失败: {str(e)}")
    
    def reload_custom_tools(self):
        """重新加载自定义工具"""
        # 移除现有的自定义工具
        custom_tools = self.get_custom_tools_config()
        for tool_name in custom_tools.keys():
            if tool_name in self.tools:
                del self.tools[tool_name]
        
        # 重新加载
        self.load_custom_tools()
    
    def get_custom_tools_config(self):
        """获取自定义工具配置"""
        try:
            if os.path.exists("custom_tools.json"):
                with open("custom_tools.json", "r", encoding="utf-8") as f:
                    return json.load(f)
        except:
            pass
        return {}
    
    # 已移除轻量级适配器，只使用 HexStrike AI
    
    def _init_hexstrike_ai(self):
        """初始化 HexStrike AI MCP 客户端（仅SSH桥接模式）"""
        try:
            from hexstrike_mcp_client import HexStrikeMCPClient
            
            # 从配置文件读取 HexStrike AI 配置
            hexstrike_config = self._load_hexstrike_config()
            
            if hexstrike_config and hexstrike_config.get("enabled", False):
                server_path = hexstrike_config.get("server_path", None)
                
                # 复用已存在的kali_bridge（必需）
                kali_bridge = None
                if self.kali_bridge:
                    # 复用已存在的 Kali 桥接实例（使用设置中的连接）
                    kali_bridge = self.kali_bridge
                    print("🔌 使用SSH桥接模式连接HexStrike AI（复用Kali Linux桥接）")
                else:
                    # 如果没有已存在的实例，尝试创建新的
                    kali_config = self._load_kali_config()
                    if kali_config and kali_config.get("enabled", False):
                        from vmware_kali_bridge import VMwareKaliBridge
                        kali_bridge = VMwareKaliBridge(kali_config)
                        self.kali_bridge = kali_bridge  # 保存以供后续使用
                        print("🔌 使用SSH桥接模式连接HexStrike AI（通过Kali Linux）")
                    else:
                        print("⚠️ SSH桥接模式需要启用Kali桥接")
                        print("💡 提示：请在ai_agent_config.json中配置kali_bridge.enabled=true")
                        return
                
                # 读取DeepSeek API配置
                deepseek_api_key = None
                deepseek_model = "deepseek-chat"
                try:
                    if os.path.exists("ai_agent_config.json"):
                        with open("ai_agent_config.json", "r", encoding="utf-8") as f:
                            config = json.load(f)
                            deepseek_api_key = config.get("deepseek_key", "")
                            if deepseek_api_key:
                                deepseek_model = config.get("selected_model", "deepseek-chat")
                                print(f"✅ 已配置DeepSeek API（模型: {deepseek_model}）")
                except Exception as e:
                    print(f"⚠️ 读取DeepSeek配置失败: {str(e)}")
                
                self.hexstrike_mcp_client = HexStrikeMCPClient(
                    server_path=server_path,
                    kali_bridge=kali_bridge,
                    deepseek_api_key=deepseek_api_key if deepseek_api_key else None,
                    deepseek_model=deepseek_model
                )
                
                # 即使服务器不可用，也尝试注册工具（可能使用默认工具列表）
                if self.hexstrike_mcp_client.is_available():
                    print("🔌 HexStrike AI MCP 客户端已连接")
                    # 注册 HexStrike AI 工具（使用 hexstrike_* 前缀，移除 _ai 后缀）
                    self._register_hexstrike_ai_tools()
                else:
                    # 检查是否有可用工具（可能使用默认工具列表）
                    tools = self.hexstrike_mcp_client.list_tools()
                    if tools:
                        print(f"⚠️ HexStrike AI 服务器不可用，但已加载 {len(tools)} 个默认工具")
                        # 即使服务器不可用，也注册默认工具
                        self._register_hexstrike_ai_tools()
                    else:
                        print("⚠️ HexStrike AI 服务器不可用，且无可用工具")
                        print("💡 提示：请确保服务器已启动，或配置server_path以便自动启动")
                        self.hexstrike_mcp_client = None
            else:
                print("ℹ️ HexStrike AI 未启用（在ai_agent_config.json中配置hexstrike_ai.enabled=true）")
        except ImportError as e:
            print(f"⚠️ 无法导入 HexStrike MCP 客户端: {e}")
        except Exception as e:
            print(f"⚠️ 初始化 HexStrike AI 失败: {str(e)}")
    
    def _load_hexstrike_config(self) -> Optional[Dict]:
        """从配置文件加载 HexStrike AI 配置"""
        try:
            if os.path.exists("ai_agent_config.json"):
                with open("ai_agent_config.json", "r", encoding="utf-8") as f:
                    config = json.load(f)
                    return config.get("hexstrike_ai", {})
        except Exception as e:
            print(f"读取 HexStrike AI 配置失败: {str(e)}")
        return None
    
    def _register_hexstrike_ai_tools(self):
        """动态注册 HexStrike AI 工具（使用 hexstrike_* 前缀）"""
        if not self.hexstrike_mcp_client:
            return
        
        try:
            # 获取可用工具列表
            tools = self.hexstrike_mcp_client.list_tools()
            
            # 通用名称到实际工具名的映射（反向映射）
            generic_to_actual = {
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
                "whatweb": "httpx",
                "dnsrecon": "dnsenum",
                "fierce": "fierce",
                "enum4linux": "enum4linux",
                "smbclient": "netexec",
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
            
            registered_count = 0
            
            # 为每个实际工具创建 wrapper 方法
            for actual_tool_name in tools:
                # 使用 hexstrike_* 前缀注册实际工具名
                wrapper_name = f"hexstrike_{actual_tool_name}"
                
                # 创建动态方法（修复闭包变量捕获问题）
                def make_wrapper(tool=actual_tool_name):
                    def wrapper(**kwargs):
                        if not self.hexstrike_mcp_client:
                            return "❌ HexStrike AI 客户端未初始化，请先启动服务器"
                        try:
                            result = self.hexstrike_mcp_client.call_tool(tool, **kwargs)
                            if result.get("success"):
                                output = result.get('result', '') or result.get('stdout', '') or '执行成功'
                                return f"✅ {tool} 执行成功:\n{output}"
                            else:
                                error_msg = result.get('error', '') or result.get('stderr', '') or '未知错误'
                                return f"❌ {tool} 执行失败: {error_msg}"
                        except Exception as e:
                            import traceback
                            return f"❌ {tool} 执行异常: {str(e)}\n{traceback.format_exc()[:200]}"
                    return wrapper
                
                self.tools[wrapper_name] = make_wrapper()
                registered_count += 1
            
            # 为通用名称创建映射（如果对应的实际工具存在）
            for generic_name, actual_tool_name in generic_to_actual.items():
                # 检查实际工具是否在可用工具列表中
                if actual_tool_name in tools:
                    generic_wrapper_name = f"hexstrike_{generic_name}"
                    # 如果还没有注册，则注册通用名称
                    if generic_wrapper_name not in self.tools:
                        # 修复闭包变量捕获问题：使用默认参数捕获变量
                        def make_generic_wrapper(actual_tool=actual_tool_name, generic_name_fixed=generic_name):
                            def wrapper(**kwargs):
                                if not self.hexstrike_mcp_client:
                                    return "❌ HexStrike AI 客户端未初始化，请先启动服务器"
                                try:
                                    result = self.hexstrike_mcp_client.call_tool(actual_tool, **kwargs)
                                    if result.get("success"):
                                        output = result.get('result', '') or result.get('stdout', '') or '执行成功'
                                        return f"✅ {generic_name_fixed} 执行成功:\n{output}"
                                    else:
                                        error_msg = result.get('error', '') or result.get('stderr', '') or '未知错误'
                                        return f"❌ {generic_name_fixed} 执行失败: {error_msg}"
                                except Exception as e:
                                    import traceback
                                    return f"❌ {generic_name_fixed} 执行异常: {str(e)}\n{traceback.format_exc()[:200]}"
                            return wrapper
                        
                        self.tools[generic_wrapper_name] = make_generic_wrapper()
                        registered_count += 1
            
            # 添加 kali_execute 工具（直接通过Kali桥接执行）
            self.tools["kali_execute"] = self.kali_execute
            self.tools["hexstrike_tool_status"] = self.hexstrike_tool_status
            registered_count += 2
            
            # 注册 HexStrike AI 智能规划工具
            self.tools["hexstrike_analyze_target"] = self.hexstrike_analyze_target
            self.tools["hexstrike_smart_scan"] = self.hexstrike_smart_scan
            self.tools["hexstrike_create_attack_chain"] = self.hexstrike_create_attack_chain
            self.tools["hexstrike_comprehensive_assessment"] = self.hexstrike_comprehensive_assessment
            registered_count += 4
            
            print(f"✅ 已注册 {registered_count} 个 HexStrike AI 工具（包括通用名称映射和智能规划）")
        except Exception as e:
            print(f"⚠️ 注册 HexStrike AI 工具失败: {str(e)}")
            import traceback
            print(traceback.format_exc())
    
    def _init_kali_bridge(self):
        """初始化 Kali Linux 桥接（如果已启用）"""
        try:
            kali_config = self._load_kali_config()
            if kali_config and kali_config.get("enabled", False):
                from vmware_kali_bridge import VMwareKaliBridge
                self.kali_bridge = VMwareKaliBridge(kali_config)
                print("🔌 Kali Linux 桥接已初始化")
        except Exception as e:
            print(f"⚠️ 初始化 Kali 桥接失败: {str(e)}")
            self.kali_bridge = None
    
    def _load_kali_config(self) -> Optional[Dict]:
        """从配置文件加载Kali桥接配置"""
        try:
            if os.path.exists("ai_agent_config.json"):
                with open("ai_agent_config.json", "r", encoding="utf-8") as f:
                    config = json.load(f)
                    return config.get("kali_bridge", {})
        except Exception as e:
            print(f"读取Kali配置失败: {str(e)}")
        return None
    
    def kali_execute(self, command: str) -> str:
        """在Kali Linux中执行命令（直接通过Kali桥接）"""
        if not self.kali_bridge:
            return "❌ Kali Linux 桥接未初始化，请先在设置中配置Kali桥接"
        
        try:
            result = self.kali_bridge.execute_command(command, timeout=300)
            if result.get("success"):
                stdout = result.get("stdout", "")
                stderr = result.get("stderr", "")
                if stdout:
                    return f"✅ 命令执行成功:\n{stdout}"
                elif stderr:
                    return f"⚠️ 命令执行完成（有警告）:\n{stderr}"
                else:
                    return "✅ 命令执行成功（无输出）"
            else:
                error = result.get("error", "")
                stderr = result.get("stderr", "")
                stdout = result.get("stdout", "")
                error_msg = error or stderr or stdout or "未知错误"
                return f"❌ 命令执行失败: {error_msg}"
        except Exception as e:
            return f"❌ 命令执行异常: {str(e)}"
    
    def hexstrike_tool_status(self) -> str:
        """获取HexStrike AI工具状态"""
        if not self.hexstrike_mcp_client:
            return "❌ HexStrike AI 客户端未初始化，请先启动服务器"
        
        try:
            status = self.hexstrike_mcp_client.get_tool_status()
            return f"✅ HexStrike AI 工具状态:\n{status}"
        except Exception as e:
            return f"❌ 获取工具状态失败: {str(e)}"
    
    def hexstrike_analyze_target(self, target: str, analysis_type: str = "comprehensive") -> str:
        """使用HexStrike AI分析目标"""
        if not self.hexstrike_mcp_client:
            return "❌ HexStrike AI 客户端未初始化，请先启动服务器"
        
        try:
            result = self.hexstrike_mcp_client.analyze_target(target, analysis_type)
            if result.get("success"):
                analysis = result.get("analysis", result.get("result", ""))
                return f"✅ HexStrike AI 目标分析完成:\n{analysis}"
            else:
                return f"❌ 分析失败: {result.get('error', '未知错误')}"
        except Exception as e:
            return f"❌ 分析异常: {str(e)}"
    
    def hexstrike_smart_scan(self, target: str, scan_type: str = "comprehensive") -> str:
        """使用HexStrike AI智能扫描"""
        if not self.hexstrike_mcp_client:
            return "❌ HexStrike AI 客户端未初始化，请先启动服务器"
        
        try:
            result = self.hexstrike_mcp_client.smart_scan(target, scan_type)
            if result.get("success"):
                scan_result = result.get("result", "")
                return f"✅ HexStrike AI 智能扫描完成:\n{scan_result}"
            else:
                return f"❌ 扫描失败: {result.get('error', '未知错误')}"
        except Exception as e:
            return f"❌ 扫描异常: {str(e)}"
    
    def hexstrike_create_attack_chain(self, target: str, objective: str = None) -> str:
        """使用HexStrike AI创建攻击链（让HexStrike AI自己规划攻击步骤）"""
        if not self.hexstrike_mcp_client:
            return "❌ HexStrike AI 客户端未初始化，请先启动服务器"
        
        try:
            result = self.hexstrike_mcp_client.create_attack_chain(target, objective)
            if result.get("success"):
                attack_chain = result.get("attack_chain", result.get("result", ""))
                if isinstance(attack_chain, list):
                    chain_text = "\n".join([f"步骤 {i+1}: {step}" for i, step in enumerate(attack_chain)])
                else:
                    chain_text = str(attack_chain)
                return f"✅ HexStrike AI 已创建攻击链:\n{chain_text}"
            else:
                return f"❌ 创建攻击链失败: {result.get('error', '未知错误')}"
        except Exception as e:
            return f"❌ 创建攻击链异常: {str(e)}"
    
    def hexstrike_execute_attack_chain(self, target: str, objective: str = None, attack_chain: Dict = None) -> str:
        """使用HexStrike AI执行攻击链（规划并执行，返回执行报告）"""
        print("=" * 60)
        print("🔧 [MCP Server] hexstrike_execute_attack_chain 被调用")
        print(f"   📍 目标: {target}")
        print(f"   📝 任务描述: {objective[:100] if objective else 'N/A'}...")
        print(f"   🔗 攻击链: {'已提供' if attack_chain else '未提供（将先规划）'}")
        print("=" * 60)
        
        if not self.hexstrike_mcp_client:
            print("❌ [MCP Server] HexStrike AI 客户端未初始化")
            return "❌ HexStrike AI 客户端未初始化，请先启动服务器"
        
        try:
            print("🔧 [MCP Server] 调用 hexstrike_mcp_client.execute_attack_chain...")
            result = self.hexstrike_mcp_client.execute_attack_chain(attack_chain=attack_chain, target=target, objective=objective)
            print(f"🔧 [MCP Server] execute_attack_chain 返回结果")
            print(f"   成功: {result.get('success', False)}")
            if result.get("success"):
                # 优先提取实际执行结果
                # smart-scan返回combined_output或scan_results
                if result.get("combined_output"):
                    report = result.get("combined_output")
                elif result.get("scan_results"):
                    scan_results = result.get("scan_results", {})
                    # 优先使用combined_output
                    if scan_results.get("combined_output"):
                        report = scan_results.get("combined_output")
                    else:
                        # 如果没有combined_output，从tools_executed中提取
                        tools_executed = scan_results.get("tools_executed", [])
                        if tools_executed:
                            outputs = []
                            for tool_result in tools_executed:
                                if tool_result.get("stdout"):
                                    tool_name = tool_result.get("tool", "unknown")
                                    outputs.append(f"=== {tool_name.upper()} OUTPUT ===\n{tool_result.get('stdout', '')}")
                            report = "\n\n".join(outputs) if outputs else json.dumps(scan_results, ensure_ascii=False, indent=2)
                        else:
                            report = json.dumps(scan_results, ensure_ascii=False, indent=2)
                # comprehensive-assessment返回assessment
                elif result.get("assessment"):
                    assessment = result.get("assessment", {})
                    # 尝试提取实际执行结果，如果没有则使用整个assessment
                    if isinstance(assessment, dict):
                        # 检查是否有实际执行输出
                        if assessment.get("combined_output"):
                            report = assessment.get("combined_output")
                        else:
                            report = json.dumps(assessment, ensure_ascii=False, indent=2)
                    else:
                        report = str(assessment)
                # 默认提取result字段
                else:
                    report = result.get("result", result.get("report", result.get("data", "")))
                
                if isinstance(report, dict):
                    report = json.dumps(report, ensure_ascii=False, indent=2)
                elif report is None:
                    report = ""
                
                print(f"   报告长度: {len(str(report))} 字符")
                print("=" * 60)
                return f"✅ HexStrike AI 攻击链执行完成，执行报告:\n{report}"
            else:
                error_msg = result.get('error', '未知错误')
                print(f"   错误: {error_msg}")
                print("=" * 60)
                return f"❌ 执行攻击链失败: {error_msg}"
        except Exception as e:
            import traceback
            error_msg = f"❌ 执行攻击链异常: {str(e)}\n{traceback.format_exc()[:200]}"
            print(f"   异常: {error_msg}")
            print("=" * 60)
            return error_msg
    
    def hexstrike_comprehensive_assessment(self, target: str) -> str:
        """使用HexStrike AI进行综合评估"""
        if not self.hexstrike_mcp_client:
            return "❌ HexStrike AI 客户端未初始化，请先启动服务器"
        
        try:
            result = self.hexstrike_mcp_client.comprehensive_assessment(target)
            if result.get("success"):
                assessment = result.get("result", "")
                return f"✅ HexStrike AI 综合评估完成:\n{assessment}"
            else:
                return f"❌ 评估失败: {result.get('error', '未知错误')}"
        except Exception as e:
            return f"❌ 评估异常: {str(e)}"
    
    # 所有轻量级工具方法已删除，现在只使用 HexStrike AI
    # 工具通过 _register_hexstrike_ai_tools() 动态注册
    # 以下方法已废弃，保留仅为兼容性（实际不会调用）
    def _deprecated_hexstrike_port_scan(self, target: str, ports: str = "1-1000", scan_type: str = "connect") -> str:
        """HexStrike端口扫描（智能路由：简单任务用轻量级，复杂任务用真实项目）"""
        # 智能路由：判断任务复杂度
        if self._should_use_hexstrike_ai("port_scan", target=target, ports=ports):
            if self.hexstrike_mcp_client:
                result = self.hexstrike_mcp_client.call_tool("port_scan", target=target, ports=ports, scan_type=scan_type)
                if result["success"]:
                    return f"✅ [HexStrike AI] 端口扫描完成:\n{result.get('result', result.get('stdout', ''))}"
        
        # 使用轻量级适配器
        if not self.hexstrike_adapter:
            return "❌ HexStrike适配器未初始化"
        return self.hexstrike_adapter.port_scan(target, ports, scan_type)
    
    def hexstrike_directory_scan(self, url: str, wordlist: str = None) -> str:
        """HexStrike目录扫描"""
        if not self.hexstrike_adapter:
            return "❌ HexStrike适配器未初始化"
        return self.hexstrike_adapter.directory_scan(url, wordlist)
    
    # 所有轻量级工具方法已删除，现在只使用 HexStrike AI
    # 工具通过 _register_hexstrike_ai_tools() 动态注册

if __name__ == "__main__":
    server = LocalMCPServer()
    print("本地MCP服务器已启动")
    print("可用工具:", server.list_tools())
    print("\n测试工具调用:")
    print("系统信息:", server.call_tool("get_system_info"))
