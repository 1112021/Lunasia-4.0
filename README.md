# 露尼西亚AI助手

一个基于PyQt5的桌面AI助手应用，具有天气查询、网站打开、应用管理、**Playwright网页导航与交互自动化**等功能。

## 🚀 快速开始

### Windows用户（推荐）
1. 确保已安装Python 3.8+
2. 双击 `启动露尼西亚.bat` 文件
3. 等待自动安装依赖包

首次使用本地 F5-TTS 时，完整版启动脚本还会创建隔离的
`tools/f5tts_env` 环境并检查 FFmpeg。该环境体积较大，不会安装到主程序 Python。

### 其他系统用户
1. 安装Python 3.8+
2. 运行 `pip install -r requirements.txt`
3. 运行 `python main.py`

```

## 前提条件

在开始使用露尼西亚AI助手之前，请确保您的系统已安装以下软件：

### Python环境

- **Python版本**：Python 3.8 或更高版本
- **推荐版本**：Python 3.9 或 3.10（最佳兼容性）

#### 检查Python版本

```bash
python --version
# 或
python3 --version
```

#### 安装Python

如果您的系统未安装Python，请访问 [Python官网](https://www.python.org/downloads/) 下载并安装：

1. **Windows系统**：
   - 下载Python安装包
   - 运行安装程序，**务必勾选"Add Python to PATH"**
   - 选择"Install Now"进行安装

2. **Linux系统**：
   ```bash
   # Ubuntu/Debian
   sudo apt update
   sudo apt install python3 python3-pip python3-venv
   
   # CentOS/RHEL
   sudo yum install python3 python3-pip
   ```

3. **macOS系统**：
   ```bash
   # 使用Homebrew
   brew install python3
   
   # 或从官网下载安装包
   ```

#### 验证安装

安装完成后，在命令行中运行以下命令验证：

```bash
python --version
pip --version
```

如果显示版本信息，说明Python安装成功。

## 环境配置

### 创建虚拟环境

为了避免依赖冲突，建议使用虚拟环境来运行露尼西亚项目。

#### Windows系统

```bash
# 创建虚拟环境
python -m venv lunesia_env

# 激活虚拟环境
lunesia_env\Scripts\activate

# 验证虚拟环境已激活（命令提示符前会显示 (lunesia_env)）
```

#### Linux/macOS系统

```bash
# 创建虚拟环境
python3 -m venv lunesia_env

# 激活虚拟环境
source lunesia_env/bin/activate

# 验证虚拟环境已激活（命令提示符前会显示 (lunesia_env)）
```

### 虚拟环境管理

```bash
# 退出虚拟环境
deactivate

# 删除虚拟环境（在项目目录外执行）
rm -rf lunesia_env  # Linux/macOS
rmdir /s lunesia_env  # Windows
```

### 虚拟环境优势

- **依赖隔离**：避免与其他Python项目的依赖冲突
- **版本控制**：确保使用特定版本的依赖包
- **环境清理**：可以轻松删除和重建环境
- **部署一致性**：确保开发和生产环境的一致性

## 安装依赖

在激活虚拟环境后安装项目依赖：

```bash
pip install -r requirements.txt
```

## 运行程序

### 方法一：使用启动脚本（推荐）

项目提供了便捷的启动脚本，双击即可运行：

#### Windows系统
- **完整版启动**：双击 `启动露尼西亚.bat`
  - 自动检查Python环境
  - 自动安装依赖包
  - 提供详细的错误诊断
  - 适合首次使用或环境配置

- **快速启动**：双击 `快速启动.bat`
  - 直接启动程序
  - 启动速度更快
  - 适合日常使用

#### 启动脚本特性
- ✅ 支持中文显示（UTF-8编码）
- ✅ 自动检查Python环境
- ✅ 自动安装依赖包
- ✅ 友好的错误提示
- ✅ 异常退出时的诊断信息

### 方法二：命令行启动

在激活虚拟环境后运行程序：

```bash
python main.py
```

#### 首次运行建议
1. 使用 `启动露尼西亚.bat` 进行首次启动
2. 确保所有依赖包正确安装
3. 验证配置文件设置
4. 后续可使用 `快速启动.bat` 进行日常使用

## 主要功能

- **天气查询**：支持和风天气API获取实时天气信息
- **网站浏览**：快速打开常用网站
- **应用管理**：扫描和启动系统应用
- **搜索功能**：支持DuckDuckGo和Playwright双模式搜索
- **Playwright网页导航与交互自动化**：页面导航、点击、输入、上传文件、下拉选择、滚动等完整网页操作
- **AI对话**：基于OpenAI/DeepSeek的智能对话
- **记忆系统**：识底深湖智能记忆和上下文回忆
- **MCP工具**：本地工具调用系统，支持文件操作、计算、笔记等
- **文件分析**：支持PDF、CSV、Excel文件分析
- **HexStrike AI安全测试**：集成HexStrike AI，提供150+安全工具和12+自主AI代理，支持智能攻击链规划

## 配置说明

在设置中可以配置：
- **API密钥**：OpenAI、DeepSeek、和风天气、高德地图
- **天气服务**：和风天气API、高德地图API
- **默认浏览器**：Chrome、Firefox、Edge、Opera、Safari
- **网站管理**：自定义网站映射（作为AI知识库的补充）

### 网站管理配置

网站管理功能作为 AI 智能识别的**补充**，让您可以添加 AI 不认识的小众网站或自定义网址。

**配置方式**：
在 `ai_agent_config.json` 中的 `website_map` 部分添加：

```json
{
  "website_map": {
    "高德开放平台": "https://lbs.amap.com/",
    "我的博客": "https://myblog.com",
    "公司内网": "http://192.168.1.100"
  }
}
```

**使用场景**：
- ✅ AI 不认识的小众网站
- ✅ 企业内部网站/内网地址
- ✅ 个人常用的特定网站
- ✅ 需要精确控制的URL映射

**工作流程**：
1. 用户说："帮我打开XXX"
2. AI 先尝试从知识库生成 URL
3. 如果 AI 生成失败，从网站管理中查找
4. 两者都没找到，提示用户添加到网站管理
- **搜索设置**：详见下方"搜索功能配置"章节
- **AI模型选择**：DeepSeek-Reasoner、GPT-3.5、GPT-4等
- **TTS设置**：支持 Azure、Qwen3 与本地 F5-TTS Sidecar；可配置参考音频、
  参考文稿、模型驻留、CUDA/CPU 回退及视觉任务显存互斥
- **窗口设置**：透明度、最大token数
- **记忆系统**：识底深湖总结模型、笔记格式
- **网站和应用映射**：自定义网站快捷方式和应用启动
- **HexStrike AI配置**：Kali Linux桥接、服务器路径、DeepSeek API配置

## 本地 F5-TTS

F5-TTS 运行在独立 Sidecar 中，主程序的 `requirements.txt` 不安装
PyTorch/F5-TTS。首次安装可直接双击 `启动露尼西亚.bat`，或在 PowerShell 执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\tools\setup_f5tts.ps1
```

需要彻底重建环境时：

```powershell
.\tools\setup_f5tts.ps1 -Rebuild
```

设置中选择“F5-TTS（本地 Sidecar）”并启用语音合成。参考音频文稿可以留空：
Sidecar 会使用 Whisper 自动识别参考音频，再进行声音克隆。自动识别使用
SoundFile 解码 PCM，不依赖 TorchCodec 的 FFmpeg shared DLL；FFmpeg CLI 仅用于
参考音频裁剪和格式预处理。

推荐使用 Python 3.11；安装脚本在其不可用时会回退到 Python 3.13。CUDA 运行时
锁定为匹配的 PyTorch/Torchaudio `2.11.0+cu126`。详细安装、生命周期和故障排查
见 `docs/f5tts_local.md`。

## 🔍 搜索功能配置

### 设置位置

在露尼西亚主界面：
1. 点击右上角的 **⚙️ 设置** 按钮
2. 在 **AI模型与功能** 标签页中找到搜索设置

### 搜索方式选项

#### 1. DuckDuckGo模式（默认）

**特点**：
- ⚡ **速度快** - 无需启动浏览器
- 💚 **资源占用低** - 内存占用小
- 🔒 **隐私保护** - 不追踪用户
- 📡 **稳定可靠** - API调用稳定

**搜索引擎**：固定使用 DuckDuckGo

**适用场景**：
- 日常快速搜索
- 简单信息查询
- 资源受限环境

#### 2. Playwright模式（高级）

**特点**：
- 🎯 **高质量结果** - 原生搜索引擎
- 🌍 **多引擎支持** - Google/Bing/Baidu可选
- 🔧 **网页自动化** - 支持网页操作
- 📊 **丰富信息** - 详细的搜索结果
- 🔗 **URL智能识别** - 自动检测并浏览用户提供的URL

**搜索引擎选项**：
- **Google** - 最准确的搜索结果（需要特殊网络）
- **Bing** - 推荐！稳定且质量高
- **Baidu** - 中文搜索优秀

**适用场景**：
- 专业研究
- 高质量信息需求
- 需要网页自动化
- 需要访问特定网址获取内容

### 推荐配置

#### 日常使用（快速）
```json
{
  "search_method": "DuckDuckGo",
  "search_engine": "DuckDuckGo",
  "max_search_questions": 3,
  "max_search_results": 12
}
```

#### 专业搜索（高质量）
```json
{
  "search_method": "Playwright",
  "search_engine": "Bing",
  "max_search_questions": 4,
  "max_search_results": 12
}
```

#### 中文搜索（最佳）
```json
{
  "search_method": "Playwright",
  "search_engine": "Baidu",
  "max_search_questions": 3,
  "max_search_results": 12
}
```

### 功能对比表

| 特性     | DuckDuckGo | Playwright+Google | Playwright+Bing | Playwright+Baidu |
|---------|------------|-------------------|-----------------|------------------|
| 搜索速度 | 极快       | 快                | 快              | 快               |
| 搜索质量 | 中等       | 极高              | 高              | 高               |
| 中文支持 | 中等       | 良好              | 良好            | 极好             |
| 英文支持 | 良好       | 极好              | 极好            | 中等             |
| 网络要求 | 低         | 高                | 中              | 低               |
| 资源占用 | 低         | 高                | 高              | 高               |
| 网页操作 | 不支持     | 支持              | 支持            | 支持             |
| URL浏览  | 不支持     | 支持              | 支持            | 支持             |
| 隐私保护 | 高         | 中                | 中              | 中               |

### URL智能识别功能（Playwright模式专属）

当您的输入包含URL时，露尼西亚会：
1. **自动检测URL**：识别 `http://` 或 `https://` 开头的链接
2. **直接访问**：优先浏览您指定的URL，获取完整内容（最多2000字符）
3. **补充搜索**：同时搜索相关信息作为背景知识
4. **综合总结**：基于URL内容和搜索结果生成准确回答

**使用示例**：
```
指挥官: 帮我总结一下https://artificialintelligenceact.eu/the-act/的内容
露尼西亚: 
  🔗 检测到URL
  📄 直接访问该网址获取完整内容
  🔍 同时搜索"欧盟人工智能法案"等相关信息
  ✅ 基于网页实际内容生成总结
```

### 智能网站打开模式

露尼西亚会**智能判断**使用哪种方式打开网站或搜索信息：

| 功能场景          | 使用方式                  | 特点                         | 触发条件示例                           |
|------------------|-------------------------|-----------------------------|------------------------------------|
| 简单网站打开      | 系统默认浏览器           | 快速稳定，无残留进程           | "帮我打开bilibili"                  |
| 网站打开+自动化   | Playwright有头模式       | 可见浏览器，支持自动化操作      | "帮我打开bilibili并搜索python"       |
| 信息搜索获取      | Playwright无头模式       | 后台运行，不显示窗口           | "介绍一下户晨风"、"2025年93阅兵是什么" |

**AI智能判断逻辑**：

露尼西亚使用 AI 理解您的意图，而不是简单的关键词匹配：

1. **简单打开** → 系统浏览器
   - AI判断：仅需打开网站，无后续操作
   - 示例：
     - `帮我打开bilibili` ✅
     - `访问百度` ✅
     - `打开github` ✅
   - 使用您电脑上已安装的浏览器（Edge/Chrome/Firefox）

2. **打开+操作** → Playwright有头模式（可见浏览器）
   - AI判断：打开网站后需要执行自动化操作
   - 示例：
     - `帮我打开bilibili并搜索python` ✅ (打开+搜索)
     - `打开百度然后搜索天气` ✅ (打开+搜索)
     - `在github上搜索react` ✅ (打开+搜索)
     - `打开知乎，点击登录` ✅ (打开+点击)
   - 浏览器保持打开，支持后续自动化操作

3. **信息搜索** → Playwright无头模式（后台运行）
   - AI判断：纯信息查询，无需显示浏览器
   - 示例：
     - `户晨风是谁` ✅
     - `介绍一下Python` ✅
     - `2025年93阅兵是什么` ✅
   - 后台快速提取信息，不显示窗口

**AI判断优势**：
- 🧠 理解语义，不依赖关键词
- 🎯 准确识别复合操作
- 🔄 自然语言表达，更灵活
- ⚡ 判断速度快（<1秒）

**降级策略**：
- AI判断失败 → 默认使用系统浏览器
- Playwright打开失败 → 自动降级为系统浏览器

**浏览器配置**：

在 `ai_agent_config.json` 中配置默认浏览器：
```json
{
  "default_browser": "edge"
}
```

可选值：
- `"edge"` - Microsoft Edge（推荐Windows用户）
- `"chrome"` - Google Chrome
- `"firefox"` - Mozilla Firefox
- `""` - 系统默认浏览器（留空）

**Playwright 自动化配置**：

在 `ai_agent_config.json` 中配置 Playwright 行为：

```json
{
  "playwright_mode": "launch",
  "playwright_persistent": false,
  "playwright_slow_mo": 0,
  "playwright_cdp_url": "http://localhost:9222",
  "playwright_user_data_dir": ""
}
```

**配置说明**：

| 配置项 | 说明 | 可选值 | 推荐场景 |
|-------|------|-------|---------|
| `playwright_mode` | 启动模式 | `launch` 常规启动<br>`connect` 连接已有浏览器<br>`persistent` 持久化上下文 | `launch` 一般使用<br>`persistent` 需要登录的网站 |
| `playwright_persistent` | 持久化开关 | `true` / `false` | `true` 保存登录状态 |
| `playwright_slow_mo` | 慢速模式（毫秒） | 0-1000+ | `0` 快速执行<br>`100-500` 调试观察 |
| `playwright_cdp_url` | CDP连接地址 | URL | `connect`模式使用 |
| `playwright_user_data_dir` | 用户数据目录 | 路径 | 空字符串使用默认路径 |

**详细文档**：
- `PLAYWRIGHT_CONFIG.md` - 详细配置说明和使用场景
- `PLAYWRIGHT_USAGE.md` - 完整API参考和代码示例

**快速配置示例**：

```json
// 1. 需要登录的网站（推荐）
{
  "playwright_mode": "launch",
  "playwright_persistent": true,
  "playwright_user_data_dir": "D:/lunesia_browser"
}

// 2. 调试模式（观察过程）
{
  "playwright_mode": "connect",
  "playwright_cdp_url": "http://localhost:9222",
  "playwright_slow_mo": 500
}

// 3. 快速模式（默认）
{
  "playwright_mode": "launch",
  "playwright_persistent": false,
  "playwright_slow_mo": 0
}
```

**注意事项**：
- 简单打开使用系统浏览器（快速、稳定）
- 自动化操作使用 Playwright（功能完整）
- 搜索功能使用 Playwright 无头模式（后台高效）
- 如需更新 Playwright 浏览器：`python -m playwright install`

### 智能网站识别（三级查找）

当您请求打开网站时，露尼西亚会按以下优先级查找：

```
📊 网站查找优先级
┌─────────────────────────────────────┐
│ 1️⃣ AI智能识别（从LLM知识库）          │
│    - 利用AI模型的内置知识            │
│    - 自动生成常见网站的官方URL        │
│    - 覆盖主流网站和平台              │
├─────────────────────────────────────┤
│ 2️⃣ 网站管理配置（用户自定义）         │
│    - 从设置中的"网站管理"查找        │
│    - 您添加的自定义网站映射          │
│    - 作为AI的补充                   │
├─────────────────────────────────────┤
│ 3️⃣ 未找到 - 返回提示               │
│    - 显示可用的网站列表              │
│    - 提供添加网站的建议              │
└─────────────────────────────────────┘
```

**工作流程示例**：

```bash
# 场景1：AI知识库中的常见网站
指挥官: 帮我打开知乎
露尼西亚: 
  🤖 步骤1: AI从知识库生成URL
  ✅ 生成: https://www.zhihu.com
  🌐 在浏览器中打开
  
# 场景2：AI不认识，但在网站管理中
指挥官: 帮我打开高德开放平台
露尼西亚:
  🤖 步骤1: AI尝试生成URL (可能失败或不准确)
  🔧 步骤2: 在网站管理中找到
  ✅ 找到: https://lbs.amap.com/
  🌐 在浏览器中打开

# 场景3：两处都没找到
指挥官: 帮我打开某个小众网站
露尼西亚:
  ❌ AI知识库中未找到
  ❌ 网站管理中未找到
  💡 建议：请在设置中添加或提供完整URL
```

**使用示例**：
```bash
# 有头模式 - 会弹出浏览器窗口
指挥官: 帮我打开高德开放平台
露尼西亚: 已在浏览器中打开 高德开放平台

指挥官: 访问github
露尼西亚: 已在浏览器中打开 GitHub

# 无头模式 - 后台运行，不显示窗口
指挥官: 介绍一下户晨风
露尼西亚: [后台搜索并分析，直接显示结果]

指挥官: 搜索python最新动态
露尼西亚: [后台搜索多个来源，整合后显示]
```

### 智能切换建议

根据不同需求智能选择搜索方式：

#### 快速查询 → DuckDuckGo
```
指挥官: 搜索今天的新闻
露尼西亚: （使用DuckDuckGo快速返回结果）
```

#### 专业研究 → Playwright+Bing
```
指挥官: 搜索量子计算最新进展
露尼西亚: （使用Playwright+Bing返回高质量学术结果）
```

#### 中文搜索 → Playwright+Baidu
```
指挥官: 搜索中国传统文化
露尼西亚: （使用Playwright+Baidu返回最佳中文结果）
```

#### 网址内容总结 → Playwright（必须）
```
指挥官: 帮我总结https://example.com的内容
露尼西亚: （直接访问URL并生成总结）
```

### 注意事项

#### DuckDuckGo模式
- ✅ 无需额外安装
- ✅ 开箱即用
- ⚠️ 搜索结果相对简单
- ❌ 不支持直接访问URL

#### Playwright模式
- ⚠️ 需要安装Playwright浏览器驱动
- ⚠️ 首次使用需要下载约140MB浏览器
- ⚠️ 内存占用较高（约200-300MB）
- ✅ 搜索结果质量高
- ✅ 支持网页自动化
- ✅ 支持直接访问URL

### Playwright安装配置

#### 安装步骤

**1. 安装Python包**
```bash
pip install playwright>=1.40.0
```

**2. 安装浏览器驱动**
```bash
# 只安装Chromium（推荐，体积小）
python -m playwright install chromium

# 或安装所有浏览器
python -m playwright install
```

**3. 验证安装**
启动露尼西亚并尝试使用Playwright搜索功能，观察是否正常工作。

#### 镜像加速（中国用户）

如果浏览器驱动下载缓慢，可使用镜像：
```bash
# Windows (PowerShell)
$env:PLAYWRIGHT_DOWNLOAD_HOST="https://playwright.azureedge.net"
python -m playwright install chromium

# Linux/macOS
export PLAYWRIGHT_DOWNLOAD_HOST=https://playwright.azureedge.net
python -m playwright install chromium
```

### 故障排除

#### 问题1：Playwright搜索失败

**可能原因**：
- 未安装Playwright浏览器驱动
- 网络连接问题

**解决方案**：
```bash
# 重新安装Playwright
pip install --upgrade playwright>=1.40.0

# 重新安装浏览器驱动
python -m playwright install chromium --force
```

#### 问题2：浏览器驱动下载失败

**可能原因**：
- 网络连接不稳定
- 防火墙阻止下载

**解决方案**：
- 使用镜像加速（见上方"镜像加速"部分）
- 检查防火墙设置
- 尝试使用VPN或代理

#### 问题3：搜索结果为空

**可能原因**：
- 网络访问受限（特别是Google）
- 搜索引擎反爬虫机制

**解决方案**：
- 切换到Bing或Baidu搜索引擎
- 或切换回DuckDuckGo模式

#### 问题4：搜索速度慢

**可能原因**：
- Playwright需要启动浏览器

**说明**：
- 首次搜索约需3秒（启动浏览器）
- 后续搜索约0.5秒（复用浏览器）
- 对于日常快速查询，建议使用DuckDuckGo模式

#### 问题5：内存占用高

**可能原因**：
- Playwright运行完整的浏览器实例

**解决方案**：
- 关闭其他浏览器窗口
- 使用headless模式（默认已启用）
- 对于简单查询切换到DuckDuckGo模式

#### 问题6：异步资源警告

**说明**：
- 程序已实现完整的异步资源清理机制
- 使用持久化事件循环和单例模式
- 所有警告信息已被智能过滤
- 如仍出现警告，可忽略，不影响功能

## 使用示例

### 启动程序
- **Windows用户**：双击 `启动露尼西亚.bat` 或 `快速启动.bat`
- **命令行用户**：运行 `python main.py`
- **首次使用**：建议使用完整版启动脚本进行环境检查

### 基础对话
- "你好" - 与露尼西亚打招呼
- "现在几点了" - 获取当前时间
- "今天是什么日子" - 获取当前日期

### 天气查询
- "今天天气怎么样" - 查询当前天气
- "明天会下雨吗" - 查询未来天气
- "北京现在多少度" - 查询特定城市天气

### 网络搜索
- "帮我搜索ChatGPT" - 搜索ChatGPT
- "找一下今天的新闻" - 搜索今日新闻

### 网站浏览
- "打开GitHub" - 使用浏览器打开GitHub
- "打开YouTube" - 打开视频网站

### 应用管理
- "打开记事本" - 启动系统应用
- "运行计算器" - 启动计算器应用

## 识底深湖记忆系统

### 功能特点
- **智能主题总结**：AI自动分析对话内容，提取关键主题
- **自动索引建立**：将主题、时间戳、上下文保存到JSON文件
- **上下文回忆**：当检测到回忆关键词时，自动搜索相关历史对话
- **自然回忆回复**：基于历史上下文生成自然的回忆回复，而非简单复制

### 记忆触发关键词
- "之前"、"记得"、"回忆"、"说过"、"讨论过"、"之前说过"

### 记忆管理
- 点击"识底深湖"按钮查看记忆系统状态
- 支持主题搜索和过滤
- 显示记忆统计信息（总主题数、日志文件数、当前对话数）
- 查看详细的主题索引和上下文摘要

## 本地MCP系统

### 功能特点
- **完全本地化**：所有MCP工具都在本地运行，无需网络连接
- **丰富工具集**：提供系统信息、文件操作、命令执行、笔记管理等多种工具
- **可视化管理**：通过MCP工具窗口管理所有可用工具
- **智能调用**：露尼西亚可以智能识别并调用相应的MCP工具

### 可用工具
- **系统工具**：`get_system_info` - 获取系统信息
- **文件操作**：`list_files`, `read_file`, `write_file`, `create_folder` - 文件管理
- **命令执行**：`execute_command`, `get_process_list` - 系统命令
- **笔记管理**：`create_note`, `list_notes`, `search_notes` - 笔记功能
- **计算工具**：`calculate` - 数学计算
- **天气信息**：`get_weather_info` - 实时天气查询（和风天气API）
- **记忆统计**：`get_memory_stats` - 记忆系统统计
- **自定义工具**：`calculate_distance` - 计算两地间距离（高德地图API）

### 使用方法
- **直接调用**：`执行 get_system_info` 或 `调用 list_files directory=.`
- **参数传递**：`执行 create_note title=测试 content=内容`
- **查看工具**：`工具列表` 或 `有哪些工具`
- **管理界面**：点击"MCP工具"按钮打开管理窗口
- **自定义工具**：通过管理界面创建、编辑、删除自定义工具
- **智能调用**：露尼西亚会自动判断并调用相应的MCP工具

### 使用示例

#### 笔记管理
```
指挥官：讲一下MCP工具
露尼西亚：介绍了MCP工具
指挥官: 帮我保存文件
露尼西亚: 文件 D:/露尼西亚文件/文档.txt 写入成功

#### 计算工具
```
指挥官: 计算 (15 + 27) * 3 - 8
露尼西亚: 🧮 计算结果：(15 + 27) * 3 - 8 = 118

指挥官: 计算复利：本金10000，年利率5%，存3年
露尼西亚: 💰 复利计算结果：
📊 本金：10,000元
📈 年利率：5%
⏰ 存期：3年
💵 最终金额：11,576.25元
📈 总收益：1,576.25元
```

#### 天气查询
```
指挥官: 今天上海天气怎么样
露尼西亚: 🌤️ 上海天气信息：
🌡️ 当前温度：18°C
🌡️ 体感温度：16°C
🌤️ 天气状况：多云转晴
💨 风向：西北风
💨 风力：3级
💧 湿度：72%
👁️ 能见度：12km
🌧️ 降雨概率：10%
⏰ 更新时间：2024-12-19 14:30:00
```

#### 工具管理
```
指挥官: 显示所有可用工具
露尼西亚: 🛠️ 可用工具列表：
📊 系统工具：get_system_info, get_process_list
📁 文件操作：list_files, read_file, write_file, create_folder
📝 笔记管理：create_note, list_notes, search_notes
🧮 计算工具：calculate
🌤️ 天气查询：get_weather_info
📈 记忆统计：get_memory_stats
🗺️ 自定义工具：calculate_distance
```

### 技术架构
- **MCP服务器**：`mcp_server.py` - 提供工具服务
- **MCP客户端**：`mcp_client.py` - 本地客户端实现
- **工具管理**：集成在主程序中的可视化管理界面
- **自定义工具**：支持用户创建和管理自定义Python工具
- **工具类型**：区分内置工具和自定义工具，内置工具不可编辑/删除

### 自定义工具开发
- **创建方式**：通过MCP工具管理界面的"新建工具"按钮
- **代码格式**：Python函数，支持参数传递
- **存储位置**：`custom_tools.json` 文件
- **动态加载**：支持运行时重新加载自定义工具
- **安全执行**：在隔离的命名空间中执行自定义代码
- **API密钥管理**：支持快速替换代码中的"mykey"占位符为实际API密钥

### API密钥快速替换功能
- **功能说明**：在创建或编辑自定义工具时，可以快速将代码中的"mykey"占位符替换为实际的API密钥
- **使用方法**：
  1. 在工具代码中使用"mykey"作为API密钥占位符
  2. 在"快速添加API密钥"输入框中输入实际的API密钥
  3. 点击"替换API密钥"按钮，系统会自动替换所有"mykey"为实际密钥
- **支持格式**：同时支持双引号和单引号格式的"mykey"替换
- **应用场景**：适用于需要API密钥的自定义工具，如高德地图、天气API等

---

## 🔒 HexStrike AI 安全测试集成

### ⚠️ 免责声明（Kali / HexStrike AI）

- **本软件按「原样」提供，不提供任何明示或暗示的保证**（包括但不限于适销性、特定用途适用性）。使用本软件的风险由您自行承担。
- **API 密钥与账号安全**：您需自行在设置中配置各类 API 密钥（如 DeepSeek、OpenAI、高德等）。请妥善保管密钥，勿将含有真实密钥的配置文件提交至公开仓库或分享给他人。因密钥泄露导致的损失与本项目作者无关。
- **安全测试与合规使用**：若您使用本软件集成的 HexStrike AI、Kali 桥接等安全测试能力，**仅限在您已获得明确授权的目标上使用**（如自有系统、书面授权的渗透测试、合规的漏洞赏金计划等）。禁止对未授权目标进行扫描、渗透或任何未授权访问。因违规使用所产生的一切法律责任由使用者自行承担。
- **第三方服务与依赖**：本软件可能调用第三方 API 或集成第三方工具，其可用性、合规性及条款由各第三方负责。使用前请阅读相关服务条款与当地法律法规。
- **作者不对因使用或无法使用本软件而导致的任何直接、间接、附带或后果性损害承担责任。**

---

### 功能概述

露尼西亚已集成真实的 [HexStrike AI](https://github.com/0x4m4/hexstrike-ai) MCP 服务器，提供专业的安全测试能力：

- **150+ 安全工具**：端口扫描、漏洞扫描、密码破解、Web安全测试等
- **12+ 自主AI代理**：智能规划攻击链、自动选择工具、优化参数
- **智能攻击链规划**：HexStrike AI自己规划攻击步骤，无需手动指定工具
- **SSH桥接Kali Linux**：通过SSH连接到Kali Linux虚拟机执行安全工具

### 架构设计

```
用户请求（安全测试任务）
  ↓
框架Agent检测到目标（URL/IP/域名）
  ↓
框架Agent创建简单框架：
  1. 启动HexStrike AI服务器
  2. 调用HexStrike AI智能规划（create-attack-chain）
     - 传递目标（target）
     - 传递完整用户请求（objective，让HexStrike AI理解任务）
  3. 传递结果给主Agent
  ↓
HexStrike AI自己规划攻击链并执行
  ↓
结果返回给框架Agent → 主Agent
```

**关键特性**：
- ✅ **智能规划**：HexStrike AI根据任务目标自动规划攻击链
- ✅ **无需关键词依赖**：通过目标检测判断是否是安全测试任务
- ✅ **直接传递任务**：将完整用户请求传递给HexStrike AI，让它自己理解

### 安装配置

#### 1. 在Kali Linux虚拟机中安装HexStrike AI

```bash
# 克隆项目
cd ~
git clone https://github.com/0x4m4/hexstrike-ai.git
cd hexstrike-ai

# 创建虚拟环境（推荐）
python3 -m venv hexstrike-env
source hexstrike-env/bin/activate

# 安装依赖
pip3 install -r requirements.txt

# 修复PATH（如果出现警告）
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# 修复依赖冲突（如果出现）
pip3 install --force-reinstall "pyee>=8.1.0,<9.0.0" "urllib3>=1.25.8,<2.0.0" "starlette>=0.27.0,<0.28.0" "python-slugify>=6.1.2"
```

#### 2. 配置Kali Linux桥接

在露尼西亚设置中配置Kali Linux桥接：

1. 打开设置 → **Kali Linux桥接设置**
2. 启用Kali Linux桥接
3. 配置SSH连接信息：
   - **SSH主机**：Kali虚拟机的IP地址（如：192.168.1.100）
   - **SSH端口**：22（默认）
   - **SSH用户名**：kali（默认）
   - **SSH密码**：您的Kali密码
4. 点击"测试连接"验证

#### 3. 配置HexStrike AI

在露尼西亚设置中配置HexStrike AI：

1. 打开设置 → **HexStrike AI设置**
2. 启用HexStrike AI
3. 配置服务器路径（Kali中的路径）：
   - 例如：`/home/kali/hexstrike-ai/hexstrike_server.py`
4. 启用自动启动服务器（可选）
5. 点击"测试连接"验证

#### 4. 配置DeepSeek API（可选）

HexStrike AI可以使用DeepSeek API进行智能规划：

1. 在设置中配置DeepSeek API密钥
2. 系统会自动将API密钥传递给HexStrike AI服务器

### 使用方法

#### 基本使用

当您输入包含目标（URL、IP或域名）的安全测试请求时，露尼西亚会自动：

1. 检测到安全测试任务
2. 启动HexStrike AI服务器（如果未运行）
3. 调用HexStrike AI智能规划，传递您的完整请求
4. HexStrike AI自己规划攻击链并执行
5. 返回结果

**使用示例**：

```
指挥官: 扫描example.com开放端口
露尼西亚: 
  🔒 检测到安全测试任务
  🚀 启动HexStrike AI服务器
  🧠 使用HexStrike AI智能规划攻击链
  ✅ HexStrike AI已规划并执行端口扫描
  📊 返回扫描结果

```

#### 可用工具

HexStrike AI提供150+安全工具，包括：

**网络侦察**：
- `hexstrike_port_scan` - 端口扫描（nmap）
- `hexstrike_masscan` - 快速端口扫描
- `hexstrike_subdomain_enum` - 子域名枚举（amass）
- `hexstrike_dnsrecon` - DNS侦察
- `hexstrike_fierce` - DNS暴力扫描

**Web安全**：
- `hexstrike_directory_scan` - 目录扫描（gobuster）
- `hexstrike_web_vuln_scan` - Web漏洞扫描（nuclei）
- `hexstrike_sql_injection` - SQL注入测试（sqlmap）
- `hexstrike_wpscan` - WordPress扫描
- `hexstrike_nikto` - Web服务器扫描

**密码破解**：
- `hexstrike_hydra` - 密码暴力破解
- `hexstrike_john` - 哈希破解（John the Ripper）
- `hexstrike_hashcat` - 哈希破解（Hashcat）

**系统工具**：
- `kali_execute` - 在Kali Linux中执行任意命令
- `hexstrike_tool_status` - 获取工具状态

**智能规划工具**：
- `hexstrike_analyze_target` - 分析目标
- `hexstrike_smart_scan` - 智能扫描
- `hexstrike_create_attack_chain` - 创建攻击链（让HexStrike AI自己规划）
- `hexstrike_comprehensive_assessment` - 综合评估

### 智能规划机制

#### 自动检测安全测试任务

系统通过以下方式检测安全测试任务：
- ✅ 检测用户输入中是否包含目标（URL、IP、域名）
- ✅ 检查HexStrike AI是否可用
- ❌ **不依赖关键词**：不会因为缺少特定关键词而误判

#### HexStrike AI自主规划

当检测到安全测试任务时：
1. 框架Agent只负责传递任务，不自己规划步骤
2. 将完整用户请求作为`objective`传递给HexStrike AI
3. HexStrike AI根据任务目标自动规划攻击链
4. HexStrike AI执行规划的攻击步骤
5. 返回结果给框架Agent → 主Agent

**优势**：
- 🧠 利用HexStrike AI的专业安全知识
- 🎯 自动选择最合适的工具和参数
- 🔗 智能规划攻击链，无需手动指定
- 📊 提供详细的执行结果和分析

### 配置示例

在 `ai_agent_config.json` 中的配置示例：

```json
{
  "kali_bridge": {
    "enabled": true,
    "ssh_host": "192.168.1.100",
    "ssh_port": 22,
    "ssh_username": "kali",
    "ssh_password": "your_password",
    "ssh_key_path": "",
    "vmware_vmx_path": ""
  },
  "hexstrike_ai": {
    "enabled": true,
    "connection_mode": "ssh",
    "server_path": "/home/kali/hexstrike-ai/hexstrike_server.py",
    "auto_start": true
  },
  "deepseek_key": "your_deepseek_api_key",
  "selected_model": "deepseek-chat"
}
```

### 故障排除

#### 问题1：连接失败

**可能原因**：
- Kali Linux虚拟机未启动
- SSH连接信息错误
- 网络连接问题

**解决方案**：
1. 确保Kali Linux虚拟机正在运行
2. 检查SSH连接信息是否正确
3. 在设置中点击"测试连接"验证

#### 问题2：工具执行失败

**可能原因**：
- HexStrike AI服务器未运行
- 工具未安装在Kali中
- 权限问题

**解决方案**：
1. 检查HexStrike AI服务器是否在运行：`curl http://localhost:8888/health`
2. 确保所需工具已安装在Kali中
3. 检查工具执行权限

#### 问题3：智能规划失败

**可能原因**：
- HexStrike AI智能端点不可用
- API参数错误

**解决方案**：
1. 检查HexStrike AI服务器日志：`tail -f /tmp/hexstrike.log`
2. 验证智能端点是否可用：`curl http://localhost:8888/api/intelligence/create-attack-chain`
3. 确保传递了正确的参数（target和objective）

### 技术架构

**相关模块**：
- `hexstrike_mcp_client.py` - HexStrike AI MCP客户端（SSH桥接）
- `mcp_server.py` - 本地MCP服务器（注册HexStrike工具）
- `framework_react_agent.py` - 框架Agent（检测安全任务并调用HexStrike AI）
- `vmware_kali_bridge.py` - Kali Linux SSH桥接

**工作流程**：
1. 框架Agent检测到安全测试任务（通过目标检测）
2. 创建简单框架，调用HexStrike AI智能规划
3. HexStrike AI客户端通过SSH连接到Kali Linux
4. 在Kali中调用HexStrike AI的REST API（`/api/intelligence/create-attack-chain`）
5. HexStrike AI服务器规划攻击链并执行
6. 结果通过SSH返回给客户端
7. 框架Agent收集结果并传递给主Agent

---

## 🏗️ 技术架构文档

### 网页Agent统一架构

露尼西亚使用统一的 `UnifiedWebpageAgent` 架构，实现了智能分级处理和ReAct推理循环。

#### 核心设计

**统一架构优势**：
- ✅ 代码精简：500行 vs 旧版700行（两个Agent）
- ✅ 智能分级：简单任务使用系统浏览器（1秒），复杂任务使用ReAct推理（10-30秒）
- ✅ 统一推理：所有任务使用同一套ReAct循环，逻辑清晰
- ✅ 避免冲突：只有一个Agent控制页面，资源统一管理

#### 执行流程

**简单任务："打开B站"**
```
快速判断 → 无自动化关键词 → 系统浏览器 → 完成（1秒）⚡
```

**单步任务："打开B站并搜索java"**
```
判断需要自动化 → 启动Playwright → ReAct推理循环：
  Step 1: 思考"需要填写搜索框" → 行动"填写java" → 观察"已填写"
  Step 2: 思考"需要提交搜索" → 行动"按回车" → 观察"搜索结果已加载"
  Step 3: 思考"任务完成" → 完成（3步推理，~10秒）🤖
```

**复杂任务："打开B站，搜索java，点第一个视频，滚动到评论"**
```
ReAct循环执行多步：
  Step 1-3: 搜索java
  Step 4-5: 点击视频
  Step 6-7: 滚动到评论
  Step 8: 完成（8步推理，~30秒）🧠
```

#### 与旧架构的对比

| 特性 | 旧架构（2个Agent） | 新架构（1个统一Agent） |
|-----|------------------|---------------------|
| **代码量** | 700行 | 500行 ✅ |
| **简单任务速度** | 慢（Playwright） | 快（系统浏览器）⚡ |
| **复杂任务支持** | 不支持/部分支持 | 完美支持 🎯 |
| **维护难度** | 高（2个文件） | 低（1个文件）✅ |
| **推理能力** | 无/有（分离） | 统一（ReAct）🧠 |

### ReAct浏览器自动化Agent

`BrowserAutomationAgent` 实现了ReAct（Reasoning + Acting）推理循环，让AI能够自主决定每一步操作。

#### ReAct循环机制

```
For each step:
  1. 💭 Thought（思考）：AI分析当前状态，决定下一步
  2. 🎬 Action（行动）：执行操作（点击、填写、滚动等）
  3. 👁️ Observation（观察）：观察结果，更新状态
  
如果任务未完成 → 继续循环
如果任务完成 → 返回结果
```

#### 可用操作类型

```python
{
  "type": "navigate",     # 导航到URL
  "url": "https://..."
}

{
  "type": "find_element", # 查找元素
  "selector": "input[type='search']"
}

{
  "type": "click",        # 点击元素
  "text": "登录"          # 通过文本
  # 或
  "selector": ".btn"      # 通过选择器
}

{
  "type": "fill",         # 填写输入框
  "selector": "input",
  "text": "java"
}

{
  "type": "scroll",       # 滚动页面
  "direction": "down"
}

{
  "type": "wait",         # 等待
  "seconds": 2
}
```

#### 使用示例

**场景1：搜索操作**
```
用户："打开B站并搜索java"

ReAct推理过程：
Step 1: 思考 → "需要先确保在B站首页"
Step 2: 观察当前URL → "已在bilibili.com"
Step 3: 思考 → "需要找搜索框"
Step 4: 查找元素 → input[type="search"]
Step 5: 填写 → "java"
Step 6: 思考 → "需要提交搜索"
Step 7: 按回车 → Enter
Step 8: 观察 → "搜索结果已加载"
Step 9: 思考 → "任务完成"
```

**场景2：复杂登录操作**
```
用户："打开B站并点击登录，然后选择密码登录"

ReAct推理过程：
Step 1: 确认在B站首页
Step 2: 查找"登录"按钮
Step 3: 点击"登录"
Step 4: 等待登录弹窗
Step 5: 查找"密码登录"选项
Step 6: 点击"密码登录"
Step 7: 任务完成
```

### 代码迁移指南

#### 迁移到统一WebpageAgent

如果需要将旧代码迁移到新的统一架构，请参考以下步骤：

**1. 修改导入语句**

```python
# 旧代码
from webpage_agent import WebpageAgent

# 新代码
from webpage_agent_unified import execute_webpage_task_sync
```

**2. 修改初始化代码**

```python
# 旧代码
self.webpage_agent = WebpageAgent(config)

# 新代码
# 统一网页Agent已改为函数调用方式，无需初始化
```

**3. 修改调用方式**

```python
# 旧代码
operation = self.webpage_agent.analyze_webpage_operation(user_input)
result = self.webpage_agent.execute_webpage_operation(
    url=url,
    operation=operation,
    browser_type=browser_type,
    ...
)

# 新代码
result = execute_webpage_task_sync(
    config=self.config,
    user_input=user_input,  # 传递完整用户输入
    url=url,
    browser_type=default_browser,
    mode=pw_mode,
    slow_mo=pw_slow_mo,
    cdp_url=pw_cdp_url,
    user_data_dir=pw_user_data_dir
)
```

#### 预期效果

**代码行数变化**：
```
旧版_open_website_wrapper: ~400行（大量重复逻辑）
新版_open_website_wrapper: ~100行（统一调用）
减少: 300行代码 ✅
```

**用户体验**：
```
旧版：
  用户："打开B站，搜索java，点第一个"
  露尼西亚：只执行最后一步（点第一个）
  结果：失败 ❌

新版：
  用户："打开B站，搜索java，点第一个"
  露尼西亚推理：
    Step 1: 填写搜索框
    Step 2: 按回车
    Step 3: 等待加载
    Step 4: 点击第一个
  结果：成功 ✅
```

---

## 📚 更多文档

更多技术细节和架构设计请查看项目源代码注释。所有主要模块都包含详细的中文注释，便于理解和维护。

**主要模块**：
- `ai_agent.py` - AI对话和智能路由核心
- `framework_react_agent.py` - 框架ReAct任务规划引擎
- `webpage_agent_unified.py` - 统一网页自动化Agent
- `memory_lake.py` - 识底深湖记忆系统
- `mcp_server.py` - 本地MCP工具服务
- `hexstrike_mcp_client.py` - HexStrike AI MCP客户端
- `vmware_kali_bridge.py` - Kali Linux SSH桥接

