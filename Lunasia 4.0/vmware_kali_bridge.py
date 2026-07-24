# -*- coding: utf-8 -*-
"""
VMware Kali Linux 桥接模块
为露尼西亚提供远程操控Kali Linux的能力
通过SSH桥接执行电子战工具
"""

import subprocess
import paramiko
import json
import os
from typing import Dict, Optional, List
from pathlib import Path

class VMwareKaliBridge:
    """VMware Kali Linux 桥接器"""
    
    def __init__(self, config: Dict = None):
        """
        初始化桥接器
        
        Args:
            config: 配置字典，包含：
                - ssh_host: Kali Linux IP地址
                - ssh_port: SSH端口（默认22）
                - ssh_username: SSH用户名（默认kali）
                - ssh_password: SSH密码（可选，建议使用密钥）
                - ssh_key_path: SSH私钥路径（推荐）
                - vmware_vmx_path: VMware虚拟机.vmx文件路径（可选）
        """
        self.config = config or {}
        self.ssh_host = self.config.get("ssh_host", "192.168.1.100")
        self.ssh_port = self.config.get("ssh_port", 22)
        self.ssh_username = self.config.get("ssh_username", "kali")
        self.ssh_password = self.config.get("ssh_password", None)
        self.ssh_key_path = self.config.get("ssh_key_path", None)
        self.vmware_vmx_path = self.config.get("vmware_vmx_path", None)
        
        self.ssh_client = None
        self._connect_ssh()
    
    def _connect_ssh(self) -> bool:
        """建立SSH连接"""
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # 优先使用密钥认证
            if self.ssh_key_path and os.path.exists(self.ssh_key_path):
                self.ssh_client.connect(
                    hostname=self.ssh_host,
                    port=self.ssh_port,
                    username=self.ssh_username,
                    key_filename=self.ssh_key_path,
                    timeout=10
                )
            elif self.ssh_password:
                self.ssh_client.connect(
                    hostname=self.ssh_host,
                    port=self.ssh_port,
                    username=self.ssh_username,
                    password=self.ssh_password,
                    timeout=10
                )
            else:
                print("⚠️ 未配置SSH认证方式（密钥或密码）")
                return False
            
            print(f"✅ SSH连接成功: {self.ssh_username}@{self.ssh_host}:{self.ssh_port}")
            return True
            
        except Exception as e:
            print(f"❌ SSH连接失败: {str(e)}")
            return False
    
    def execute_command(self, command: str, timeout: int = 300) -> Dict:
        """
        在Kali Linux中执行命令
        
        Args:
            command: 要执行的命令
            timeout: 超时时间（秒）
        
        Returns:
            dict: {
                "success": bool,
                "stdout": str,
                "stderr": str,
                "return_code": int,
                "command": str
            }
        """
        if not self.ssh_client:
            if not self._connect_ssh():
                return {
                    "success": False,
                    "error": "SSH连接未建立",
                    "stdout": "",
                    "stderr": "",
                    "return_code": -1,
                    "command": command
                }
        
        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(
                command,
                timeout=timeout
            )
            
            # 读取输出
            stdout_text = stdout.read().decode('utf-8', errors='ignore')
            stderr_text = stderr.read().decode('utf-8', errors='ignore')
            return_code = stdout.channel.recv_exit_status()
            
            return {
                "success": return_code == 0,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "return_code": return_code,
                "command": command
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": str(e),
                "return_code": -1,
                "command": command
            }
    
    def check_tools(self) -> Dict[str, bool]:
        """检查Kali Linux中可用的安全工具"""
        tools = {
            "nmap": False,
            "gobuster": False,
            "nikto": False,
            "sqlmap": False,
            "subfinder": False,
            "amass": False,
            "nuclei": False,
            "metasploit": False,
            "dirb": False,
            "ffuf": False,
            "masscan": False,
            "rustscan": False,
            # 新增20个工具
            "wpscan": False,
            "hydra": False,
            "john": False,
            "hashcat": False,
            "wfuzz": False,
            "whatweb": False,
            "dnsrecon": False,
            "fierce": False,
            "enum4linux": False,
            "smbclient": False,
            "crackmapexec": False,
            "responder": False,
            "tcpdump": False,
            "nc": False,  # netcat
            "curl": False,
            "wget": False,
            "dig": False,
            "nslookup": False,
            "whois": False,
            "searchsploit": False,
        }
        
        for tool in tools.keys():
            result = self.execute_command(f"which {tool}", timeout=5)
            tools[tool] = result["success"] and result["return_code"] == 0
        
        return tools
    
    def upload_file(self, local_path: str, remote_path: str) -> bool:
        """上传文件到Kali Linux（使用SCP）"""
        try:
            if not self.ssh_client:
                if not self._connect_ssh():
                    return False
            
            sftp = self.ssh_client.open_sftp()
            sftp.put(local_path, remote_path)
            sftp.close()
            return True
            
        except Exception as e:
            print(f"❌ 文件上传失败: {str(e)}")
            return False
    
    def download_file(self, remote_path: str, local_path: str) -> bool:
        """从Kali Linux下载文件（使用SCP）"""
        try:
            if not self.ssh_client:
                if not self._connect_ssh():
                    return False
            
            sftp = self.ssh_client.open_sftp()
            sftp.get(remote_path, local_path)
            sftp.close()
            return True
            
        except Exception as e:
            print(f"❌ 文件下载失败: {str(e)}")
            return False
    
    def get_vm_status(self) -> str:
        """获取虚拟机状态（如果配置了VMware路径）"""
        if not self.vmware_vmx_path:
            return "未配置VMware虚拟机路径"
        
        try:
            # 使用VMRun检查虚拟机状态
            result = subprocess.run(
                ["vmrun", "list"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if self.vmware_vmx_path in result.stdout:
                return "虚拟机正在运行"
            else:
                return "虚拟机未运行"
                
        except FileNotFoundError:
            return "未找到vmrun工具（需要安装VMware Workstation/Player）"
        except Exception as e:
            return f"检查虚拟机状态失败: {str(e)}"
    
    def start_vm(self) -> bool:
        """启动VMware虚拟机"""
        if not self.vmware_vmx_path:
            return False
        
        try:
            result = subprocess.run(
                ["vmrun", "start", self.vmware_vmx_path],
                capture_output=True,
                text=True,
                timeout=60
            )
            return result.returncode == 0
        except Exception as e:
            print(f"❌ 启动虚拟机失败: {str(e)}")
            return False
    
    def stop_vm(self) -> bool:
        """停止VMware虚拟机"""
        if not self.vmware_vmx_path:
            return False
        
        try:
            result = subprocess.run(
                ["vmrun", "stop", self.vmware_vmx_path],
                capture_output=True,
                text=True,
                timeout=60
            )
            return result.returncode == 0
        except Exception as e:
            print(f"❌ 停止虚拟机失败: {str(e)}")
            return False
    
    def close(self):
        """关闭SSH连接"""
        if self.ssh_client:
            self.ssh_client.close()
            self.ssh_client = None

