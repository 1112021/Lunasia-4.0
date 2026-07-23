# -*- coding: utf-8 -*-
"""
HexStrike AI 电子战工具适配器（轻量级）
通过SSH桥接在Kali Linux中执行安全工具
"""

import json
from typing import Dict, Optional, List
from vmware_kali_bridge import VMwareKaliBridge

class HexStrikeAdapter:
    """HexStrike工具适配器 - 轻量级集成"""
    
    def __init__(self, kali_bridge: VMwareKaliBridge):
        """
        初始化HexStrike适配器
        
        Args:
            kali_bridge: VMwareKaliBridge实例，用于执行命令
        """
        self.kali_bridge = kali_bridge
        self.available_tools = {}
        self._check_available_tools()
    
    def _check_available_tools(self):
        """检查Kali Linux中可用的安全工具"""
        if self.kali_bridge:
            self.available_tools = self.kali_bridge.check_tools()
        else:
            self.available_tools = {}
    
    def port_scan(self, target: str, ports: str = "1-1000", scan_type: str = "connect") -> str:
        """
        端口扫描（使用nmap）
        
        Args:
            target: 目标IP或域名
            ports: 端口范围，如"1-1000"或"80,443,8080"
            scan_type: 扫描类型，"syn"（SYN扫描，需要sudo）或"connect"（TCP连接扫描）
        
        Returns:
            扫描结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("nmap"):
            return "❌ nmap未安装，无法进行端口扫描"
        
        try:
            if scan_type == "syn":
                # SYN扫描需要sudo权限，先尝试
                cmd = f"sudo nmap -sS -p {ports} {target} --max-retries 1 --host-timeout 5m"
                result = self.kali_bridge.execute_command(cmd, timeout=600)
                
                # 如果sudo失败（需要密码），自动降级为TCP连接扫描
                if not result["success"]:
                    error_msg = result.get('stderr', result.get('error', '')).lower()
                    if "sudo" in error_msg and ("密码" in error_msg or "password" in error_msg):
                        print("⚠️ SYN扫描需要sudo密码，自动降级为TCP连接扫描（无需sudo）")
                        # 降级为TCP连接扫描
                        cmd = f"nmap -sT -p {ports} {target} --max-retries 1 --host-timeout 5m"
                        result = self.kali_bridge.execute_command(cmd, timeout=600)
            else:
                # TCP连接扫描，不需要sudo
                cmd = f"nmap -sT -p {ports} {target} --max-retries 1 --host-timeout 5m"
                result = self.kali_bridge.execute_command(cmd, timeout=600)
            
            if result["success"]:
                return f"✅ 端口扫描完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ 端口扫描失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ 端口扫描异常: {str(e)}"
    
    def directory_scan(self, url: str, wordlist: str = None, threads: int = 50) -> str:
        """
        目录扫描（使用gobuster或dirb）
        
        Args:
            url: 目标URL
            wordlist: 字典文件路径（可选，默认使用常见字典）
            threads: 线程数
        
        Returns:
            扫描结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        # 优先使用gobuster，如果没有则使用dirb
        if self.available_tools.get("gobuster"):
            if wordlist:
                cmd = f"gobuster dir -u {url} -w {wordlist} -t {threads} -q"
            else:
                # 使用Kali默认字典
                cmd = f"gobuster dir -u {url} -w /usr/share/wordlists/dirb/common.txt -t {threads} -q"
        elif self.available_tools.get("dirb"):
            if wordlist:
                cmd = f"dirb {url} {wordlist} -S -w"
            else:
                cmd = f"dirb {url} /usr/share/wordlists/dirb/common.txt -S -w"
        elif self.available_tools.get("ffuf"):
            if wordlist:
                cmd = f"ffuf -u {url}/FUZZ -w {wordlist} -t {threads} -s"
            else:
                cmd = f"ffuf -u {url}/FUZZ -w /usr/share/wordlists/dirb/common.txt -t {threads} -s"
        else:
            return "❌ 未找到可用的目录扫描工具（gobuster/dirb/ffuf）"
        
        try:
            result = self.kali_bridge.execute_command(cmd, timeout=600)
            
            if result["success"]:
                return f"✅ 目录扫描完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ 目录扫描失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ 目录扫描异常: {str(e)}"
    
    def subdomain_enum(self, domain: str) -> str:
        """
        子域名枚举（使用subfinder或amass）
        
        Args:
            domain: 目标域名
        
        Returns:
            枚举结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        # 优先使用subfinder
        if self.available_tools.get("subfinder"):
            cmd = f"subfinder -d {domain} -silent"
        elif self.available_tools.get("amass"):
            cmd = f"amass enum -d {domain} -silent"
        else:
            return "❌ 未找到可用的子域名枚举工具（subfinder/amass）"
        
        try:
            result = self.kali_bridge.execute_command(cmd, timeout=300)
            
            if result["success"]:
                subdomains = [line.strip() for line in result['stdout'].split('\n') if line.strip()]
                return f"✅ 子域名枚举完成，发现 {len(subdomains)} 个子域名:\n" + "\n".join(subdomains[:50])  # 最多显示50个
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ 子域名枚举失败: {error_msg}"
        except Exception as e:
            return f"❌ 子域名枚举异常: {str(e)}"
    
    def web_vulnerability_scan(self, url: str) -> str:
        """
        Web漏洞扫描（使用nikto）
        
        Args:
            url: 目标URL
        
        Returns:
            扫描结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("nikto"):
            return "❌ nikto未安装，无法进行Web漏洞扫描"
        
        try:
            cmd = f"nikto -h {url} -Format txt"
            result = self.kali_bridge.execute_command(cmd, timeout=600)
            
            if result["success"]:
                return f"✅ Web漏洞扫描完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ Web漏洞扫描失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ Web漏洞扫描异常: {str(e)}"
    
    def sql_injection_test(self, url: str, data: str = None) -> str:
        """
        SQL注入测试（使用sqlmap）
        
        Args:
            url: 目标URL
            data: POST数据（可选）
        
        Returns:
            测试结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("sqlmap"):
            return "❌ sqlmap未安装，无法进行SQL注入测试"
        
        try:
            if data:
                cmd = f"sqlmap -u {url} --data='{data}' --batch --crawl=2 --level=2 --risk=2"
            else:
                cmd = f"sqlmap -u {url} --batch --crawl=2 --level=2 --risk=2"
            
            result = self.kali_bridge.execute_command(cmd, timeout=1800)  # 30分钟超时
            
            if result["success"]:
                return f"✅ SQL注入测试完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ SQL注入测试失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ SQL注入测试异常: {str(e)}"
    
    def nuclei_scan(self, target: str, templates: str = None) -> str:
        """
        使用Nuclei进行漏洞扫描
        
        Args:
            target: 目标URL或IP
            templates: 模板类型（可选，如"cves", "exposures", "vulnerabilities"）
        
        Returns:
            扫描结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("nuclei"):
            return "❌ nuclei未安装，无法进行漏洞扫描"
        
        try:
            if templates:
                cmd = f"nuclei -u {target} -t {templates} -silent"
            else:
                cmd = f"nuclei -u {target} -silent"
            
            result = self.kali_bridge.execute_command(cmd, timeout=600)
            
            if result["success"]:
                return f"✅ Nuclei扫描完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ Nuclei扫描失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ Nuclei扫描异常: {str(e)}"
    
    def masscan_scan(self, target: str, ports: str = "1-65535", rate: int = 1000) -> str:
        """
        快速端口扫描（使用masscan）
        
        Args:
            target: 目标IP或IP段
            ports: 端口范围
            rate: 扫描速率（包/秒）
        
        Returns:
            扫描结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("masscan"):
            return "❌ masscan未安装，无法进行快速端口扫描"
        
        try:
            # masscan需要sudo权限，先尝试
            cmd = f"sudo masscan -p{ports} {target} --rate={rate}"
            result = self.kali_bridge.execute_command(cmd, timeout=300)
            
            # 如果sudo失败，提示用户配置sudo免密或使用nmap
            if not result["success"]:
                error_msg = result.get('stderr', result.get('error', '')).lower()
                if "sudo" in error_msg and ("密码" in error_msg or "password" in error_msg):
                    return f"❌ Masscan扫描失败: 需要sudo权限但无法输入密码\n建议：\n1. 在Kali Linux中配置sudo免密：echo 'kali ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/kali\n2. 或使用hexstrike_port_scan（会自动降级为TCP扫描）"
            
            if result["success"]:
                return f"✅ Masscan扫描完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ Masscan扫描失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ Masscan扫描异常: {str(e)}"
    
    def wpscan(self, url: str, username: str = None, wordlist: str = None) -> str:
        """
        WordPress扫描（使用wpscan）
        
        Args:
            url: WordPress网站URL
            username: 用户名（可选，用于暴力破解）
            wordlist: 密码字典路径（可选）
        
        Returns:
            扫描结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("wpscan"):
            return "❌ wpscan未安装，无法进行WordPress扫描"
        
        try:
            cmd = f"wpscan --url {url} --no-banner"
            if username and wordlist:
                cmd += f" --usernames {username} --passwords {wordlist}"
            elif username:
                cmd += f" --usernames {username}"
            
            result = self.kali_bridge.execute_command(cmd, timeout=600)
            
            if result["success"]:
                return f"✅ WordPress扫描完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ WordPress扫描失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ WordPress扫描异常: {str(e)}"
    
    def hydra_bruteforce(self, target: str, service: str, username: str = None, wordlist: str = None) -> str:
        """
        密码暴力破解（使用hydra）
        
        Args:
            target: 目标IP或域名
            service: 服务类型（ssh, ftp, http, mysql等）
            username: 用户名（可选）
            wordlist: 密码字典路径（可选，默认使用常见密码）
        
        Returns:
            破解结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("hydra"):
            return "❌ hydra未安装，无法进行密码破解"
        
        try:
            if wordlist:
                if username:
                    cmd = f"hydra -l {username} -P {wordlist} {target} {service}"
                else:
                    cmd = f"hydra -L {wordlist} -P {wordlist} {target} {service}"
            else:
                if username:
                    cmd = f"hydra -l {username} -P /usr/share/wordlists/rockyou.txt {target} {service}"
                else:
                    return "❌ 需要指定用户名或密码字典"
            
            result = self.kali_bridge.execute_command(cmd, timeout=1800)
            
            if result["success"]:
                return f"✅ 密码破解完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ 密码破解失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ 密码破解异常: {str(e)}"
    
    def john_crack(self, hash_file: str, wordlist: str = None) -> str:
        """
        哈希破解（使用John the Ripper）
        
        Args:
            hash_file: 哈希文件路径
            wordlist: 密码字典路径（可选）
        
        Returns:
            破解结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("john"):
            return "❌ john未安装，无法进行哈希破解"
        
        try:
            if wordlist:
                cmd = f"john --wordlist={wordlist} {hash_file}"
            else:
                cmd = f"john --wordlist=/usr/share/wordlists/rockyou.txt {hash_file}"
            
            result = self.kali_bridge.execute_command(cmd, timeout=3600)
            
            if result["success"]:
                return f"✅ 哈希破解完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ 哈希破解失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ 哈希破解异常: {str(e)}"
    
    def hashcat_crack(self, hash_file: str, hash_type: str, wordlist: str = None) -> str:
        """
        哈希破解（使用hashcat）
        
        Args:
            hash_file: 哈希文件路径
            hash_type: 哈希类型（如0=MD5, 1000=NTLM, 1800=SHA512等）
            wordlist: 密码字典路径（可选）
        
        Returns:
            破解结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("hashcat"):
            return "❌ hashcat未安装，无法进行哈希破解"
        
        try:
            if wordlist:
                cmd = f"hashcat -m {hash_type} {hash_file} {wordlist}"
            else:
                cmd = f"hashcat -m {hash_type} {hash_file} /usr/share/wordlists/rockyou.txt"
            
            result = self.kali_bridge.execute_command(cmd, timeout=3600)
            
            if result["success"]:
                return f"✅ Hashcat破解完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ Hashcat破解失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ Hashcat破解异常: {str(e)}"
    
    def wfuzz_scan(self, url: str, wordlist: str = None, parameter: str = "FUZZ") -> str:
        """
        Web模糊测试（使用wfuzz）
        
        Args:
            url: 目标URL
            wordlist: 字典文件路径（可选）
            parameter: 模糊测试参数（默认FUZZ）
        
        Returns:
            扫描结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("wfuzz"):
            return "❌ wfuzz未安装，无法进行Web模糊测试"
        
        try:
            if wordlist:
                cmd = f"wfuzz -w {wordlist} -c {url.replace('FUZZ', '{FUZZ}')}"
            else:
                cmd = f"wfuzz -w /usr/share/wordlists/dirb/common.txt -c {url.replace('FUZZ', '{FUZZ}')}"
            
            result = self.kali_bridge.execute_command(cmd, timeout=600)
            
            if result["success"]:
                return f"✅ Web模糊测试完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ Web模糊测试失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ Web模糊测试异常: {str(e)}"
    
    def whatweb_scan(self, url: str) -> str:
        """
        Web技术识别（使用whatweb）
        
        Args:
            url: 目标URL
        
        Returns:
            识别结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("whatweb"):
            return "❌ whatweb未安装，无法进行Web技术识别"
        
        try:
            cmd = f"whatweb {url} --no-errors"
            result = self.kali_bridge.execute_command(cmd, timeout=300)
            
            if result["success"]:
                return f"✅ Web技术识别完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ Web技术识别失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ Web技术识别异常: {str(e)}"
    
    def dnsrecon_scan(self, domain: str) -> str:
        """
        DNS侦察（使用dnsrecon）
        
        Args:
            domain: 目标域名
        
        Returns:
            侦察结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("dnsrecon"):
            return "❌ dnsrecon未安装，无法进行DNS侦察"
        
        try:
            cmd = f"dnsrecon -d {domain}"
            result = self.kali_bridge.execute_command(cmd, timeout=300)
            
            if result["success"]:
                return f"✅ DNS侦察完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ DNS侦察失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ DNS侦察异常: {str(e)}"
    
    def fierce_scan(self, domain: str) -> str:
        """
        DNS暴力扫描（使用fierce）
        
        Args:
            domain: 目标域名
        
        Returns:
            扫描结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("fierce"):
            return "❌ fierce未安装，无法进行DNS暴力扫描"
        
        try:
            cmd = f"fierce -dns {domain}"
            result = self.kali_bridge.execute_command(cmd, timeout=600)
            
            if result["success"]:
                return f"✅ DNS暴力扫描完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ DNS暴力扫描失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ DNS暴力扫描异常: {str(e)}"
    
    def enum4linux_scan(self, target: str) -> str:
        """
        SMB枚举（使用enum4linux）
        
        Args:
            target: 目标IP地址
        
        Returns:
            枚举结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("enum4linux"):
            return "❌ enum4linux未安装，无法进行SMB枚举"
        
        try:
            cmd = f"enum4linux -a {target}"
            result = self.kali_bridge.execute_command(cmd, timeout=600)
            
            if result["success"]:
                return f"✅ SMB枚举完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ SMB枚举失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ SMB枚举异常: {str(e)}"
    
    def smbclient_connect(self, target: str, share: str = "IPC$", username: str = None, password: str = None) -> str:
        """
        SMB客户端连接（使用smbclient）
        
        Args:
            target: 目标IP地址
            share: 共享名称（默认IPC$）
            username: 用户名（可选）
            password: 密码（可选）
        
        Returns:
            连接结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("smbclient"):
            return "❌ smbclient未安装，无法连接SMB"
        
        try:
            if username and password:
                cmd = f"smbclient //{target}/{share} -U {username}%{password} -c 'ls'"
            elif username:
                cmd = f"smbclient //{target}/{share} -U {username} -c 'ls'"
            else:
                cmd = f"smbclient //{target}/{share} -N -c 'ls'"
            
            result = self.kali_bridge.execute_command(cmd, timeout=60)
            
            if result["success"]:
                return f"✅ SMB连接成功:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ SMB连接失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ SMB连接异常: {str(e)}"
    
    def crackmapexec_scan(self, target: str, username: str = None, password: str = None) -> str:
        """
        网络渗透测试（使用crackmapexec）
        
        Args:
            target: 目标IP或IP段
            username: 用户名（可选）
            password: 密码（可选）
        
        Returns:
            扫描结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("crackmapexec"):
            return "❌ crackmapexec未安装，无法进行网络渗透测试"
        
        try:
            if username and password:
                cmd = f"crackmapexec smb {target} -u {username} -p {password} --shares"
            elif username:
                cmd = f"crackmapexec smb {target} -u {username} --shares"
            else:
                cmd = f"crackmapexec smb {target} --shares"
            
            result = self.kali_bridge.execute_command(cmd, timeout=600)
            
            if result["success"]:
                return f"✅ 网络渗透测试完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ 网络渗透测试失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ 网络渗透测试异常: {str(e)}"
    
    def responder_poison(self, interface: str = "eth0") -> str:
        """
        LLMNR/NBT-NS毒化（使用responder）
        
        Args:
            interface: 网络接口（默认eth0）
        
        Returns:
            毒化结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("responder"):
            return "❌ responder未安装，无法进行LLMNR/NBT-NS毒化"
        
        try:
            # responder需要后台运行，这里只检查是否可用
            cmd = f"responder -I {interface} -wrf"
            result = self.kali_bridge.execute_command(cmd, timeout=10)
            
            return f"✅ Responder已启动（后台运行）:\n{result.get('stdout', '')}"
        except Exception as e:
            return f"❌ Responder启动异常: {str(e)}"
    
    def tcpdump_capture(self, interface: str = "eth0", count: int = 100, output_file: str = None) -> str:
        """
        网络抓包（使用tcpdump）
        
        Args:
            interface: 网络接口（默认eth0）
            count: 抓包数量（默认100）
            output_file: 输出文件路径（可选）
        
        Returns:
            抓包结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("tcpdump"):
            return "❌ tcpdump未安装，无法进行网络抓包"
        
        try:
            if output_file:
                cmd = f"tcpdump -i {interface} -c {count} -w {output_file}"
            else:
                cmd = f"tcpdump -i {interface} -c {count}"
            
            result = self.kali_bridge.execute_command(cmd, timeout=300)
            
            if result["success"]:
                return f"✅ 网络抓包完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ 网络抓包失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ 网络抓包异常: {str(e)}"
    
    def netcat_connect(self, target: str, port: int) -> str:
        """
        网络连接测试（使用netcat）
        
        Args:
            target: 目标IP或域名
            port: 目标端口
        
        Returns:
            连接结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("nc"):
            return "❌ netcat未安装，无法进行网络连接测试"
        
        try:
            cmd = f"nc -zv {target} {port}"
            result = self.kali_bridge.execute_command(cmd, timeout=30)
            
            if result["success"]:
                return f"✅ 网络连接测试完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ 网络连接测试失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ 网络连接测试异常: {str(e)}"
    
    def curl_request(self, url: str, method: str = "GET", data: str = None, headers: str = None) -> str:
        """
        HTTP请求（使用curl）
        
        Args:
            url: 目标URL
            method: HTTP方法（GET, POST等）
            data: POST数据（可选）
            headers: 自定义请求头（可选）
        
        Returns:
            请求结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("curl"):
            return "❌ curl未安装，无法发送HTTP请求"
        
        try:
            cmd = f"curl -X {method}"
            if data:
                cmd += f" -d '{data}'"
            if headers:
                cmd += f" -H '{headers}'"
            cmd += f" {url}"
            
            result = self.kali_bridge.execute_command(cmd, timeout=60)
            
            if result["success"]:
                return f"✅ HTTP请求完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ HTTP请求失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ HTTP请求异常: {str(e)}"
    
    def wget_download(self, url: str, output_file: str = None) -> str:
        """
        文件下载（使用wget）
        
        Args:
            url: 文件URL
            output_file: 输出文件名（可选）
        
        Returns:
            下载结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("wget"):
            return "❌ wget未安装，无法下载文件"
        
        try:
            if output_file:
                cmd = f"wget -O {output_file} {url}"
            else:
                cmd = f"wget {url}"
            
            result = self.kali_bridge.execute_command(cmd, timeout=300)
            
            if result["success"]:
                return f"✅ 文件下载完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ 文件下载失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ 文件下载异常: {str(e)}"
    
    def dig_query(self, domain: str, record_type: str = "A") -> str:
        """
        DNS查询（使用dig）
        
        Args:
            domain: 目标域名
            record_type: DNS记录类型（A, MX, NS等，默认A）
        
        Returns:
            查询结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("dig"):
            return "❌ dig未安装，无法进行DNS查询"
        
        try:
            cmd = f"dig {domain} {record_type} +short"
            result = self.kali_bridge.execute_command(cmd, timeout=30)
            
            if result["success"]:
                return f"✅ DNS查询完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ DNS查询失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ DNS查询异常: {str(e)}"
    
    def nslookup_query(self, domain: str, record_type: str = "A") -> str:
        """
        DNS查询（使用nslookup）
        
        Args:
            domain: 目标域名
            record_type: DNS记录类型（A, MX, NS等，默认A）
        
        Returns:
            查询结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("nslookup"):
            return "❌ nslookup未安装，无法进行DNS查询"
        
        try:
            cmd = f"nslookup -type={record_type} {domain}"
            result = self.kali_bridge.execute_command(cmd, timeout=30)
            
            if result["success"]:
                return f"✅ DNS查询完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ DNS查询失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ DNS查询异常: {str(e)}"
    
    def whois_query(self, domain: str) -> str:
        """
        域名信息查询（使用whois）
        
        Args:
            domain: 目标域名
        
        Returns:
            查询结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("whois"):
            return "❌ whois未安装，无法进行域名信息查询"
        
        try:
            cmd = f"whois {domain}"
            result = self.kali_bridge.execute_command(cmd, timeout=60)
            
            if result["success"]:
                return f"✅ 域名信息查询完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ 域名信息查询失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ 域名信息查询异常: {str(e)}"
    
    def searchsploit_search(self, keyword: str) -> str:
        """
        Exploit-DB搜索（使用searchsploit）
        
        Args:
            keyword: 搜索关键词（软件名、CVE编号等）
        
        Returns:
            搜索结果字符串
        """
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        if not self.available_tools.get("searchsploit"):
            return "❌ searchsploit未安装，无法搜索Exploit-DB"
        
        try:
            cmd = f"searchsploit {keyword}"
            result = self.kali_bridge.execute_command(cmd, timeout=60)
            
            if result["success"]:
                return f"✅ Exploit-DB搜索完成:\n{result['stdout']}"
            else:
                error_msg = result.get('stderr', result.get('error', '未知错误'))
                return f"❌ Exploit-DB搜索失败: {error_msg}\n输出: {result.get('stdout', '')}"
        except Exception as e:
            return f"❌ Exploit-DB搜索异常: {str(e)}"
    
    def get_tool_status(self) -> str:
        """获取工具状态信息"""
        if not self.kali_bridge:
            return "❌ Kali Linux桥接未配置"
        
        status = {
            "桥接状态": "已连接" if self.kali_bridge.ssh_client else "未连接",
            "可用工具": []
        }
        
        for tool, available in self.available_tools.items():
            if available:
                status["可用工具"].append(tool)
        
        return json.dumps(status, ensure_ascii=False, indent=2)

