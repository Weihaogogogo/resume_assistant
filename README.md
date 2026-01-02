# DeepAgents - AI 简历助手

基于 LangGraph + Vue3 的智能简历助手，通过对话帮助用户完善简历内容，支持岗位 JD 匹配分析和 PDF 导出。

## 目录结构

```
DeepAgents/
├── frontend/                          # 前端 Vue3 项目
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatMessage.vue      # 聊天消息组件 (Markdown 渲染)
│   │   │   ├── ResumePreview.vue    # 简历预览组件 (A4分页、PDF导出)
│   │   │   ├── RichTextEditor.vue   # 富文本编辑器 (Ctrl+B 加粗)
│   │   │   └── BoldTextarea.vue     # 加粗文本域组件
│   │   ├── App.vue                  # 主应用组件 (SSE流式通信)
│   │   ├── main.js                  # 应用入口 (Element Plus 配置)
│   │   └── style.css                # 全局样式
│   ├── package.json
│   └── vite.config.js
│
├── mcp_service_simple.py              # FastAPI 服务入口 (SSE流式响应)
├── resume_agent.py                    # LangGraph AI 代理核心
├── tools.py                           # 工具函数集合
├── pdf_generator.py                   # PDF 生成器 (WeasyPrint)
├── jd.json                            # 岗位 JD 数据存储
├── resume.json                        # 简历数据存储
├── .env                               # 环境变量
└── start_backend.sh                   # 后端启动脚本
```

## 技术栈

### 前端
- **Vue 3.5.24** - 响应式 UI 框架
- **Vite 7.2.4** - 构建工具
- **Element Plus 2.8.0** - UI 组件库
- **marked 17.0.1** - Markdown 渲染

### 后端
- **FastAPI** - HTTP API 框架
- **Uvicorn** - ASGI 服务器
- **LangGraph** - AI 代理工作流
- **LangChain** - LLM 集成
- **WeasyPrint** - 服务端 PDF 生成

## 快速启动

### 1. 安装依赖

```bash
# macOS PDF 依赖
brew install pango harfbuzz cairo fontconfig

# 前端依赖
cd frontend && npm install

# 后端虚拟环境
cd .. && source .venv/bin/activate
```

### 2. 启动服务

**后端服务 (端口 8000)**
```bash
cd /Users/weihaohuang/Desktop/DeepAgents
./start_backend.sh
# 或手动: source .venv/bin/activate && python mcp_service_simple.py
```

**前端服务 (端口 5173)**
```bash
cd frontend && npm run dev
```

### 3. 访问
- 前端: http://localhost:5173
- 后端 API: http://localhost:8000

## API 接口

| 端点 | 方法 | 功能 |
|------|------|------|
| `/health` | POST | 健康检查 |
| `/chat` | POST | 聊天接口 (SSE 流式响应) |
| `/load_resume` | POST | 加载简历数据 |
| `/save_resume` | POST | 保存简历数据 |
| `/load_jd` | POST | 加载 JD 数据 |
| `/parse_jd` | POST | 解析 JD (文本/图片智能识别) |
| `/save_jd` | POST | 保存 JD 数据 |
| `/export_pdf` | POST | 导出 PDF 文件 |

## LangGraph 工作流

```
┌────────────────────────────────────────────────────────────┐
│                    LangGraph StateGraph                     │
├────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐                                       │
│  │  conversation_  │  入口点 - 处理用户对话                 │
│  │  llm            │  temperature=0.1                      │
│  └────────┬────────┘                                       │
│           │                                                │
│           ▼                                                │
│  ┌────────────────────────────────────────┐               │
│  │    route_after_conversation             │               │
│  └────────────────────────────────────────┘               │
│           │                    │                    │      │
│           ▼                    ▼                    ▼      │
│  ┌─────────────┐      ┌─────────────┐      ┌───────────┐  │
│  │ formatter_  │      │  tool_node  │      │  END      │  │
│  │ llm         │      │  (工具执行) │               │  │
│  └──────┬──────┘      └──────┬──────┘      └───────────┘  │
│         │                    │                             │
│         │                    ▼                             │
│         │         ┌─────────────────────────┐              │
│         │         │    tool_node → conv     │              │
│         │         └─────────────────────────┘              │
│         ▼                                                   │
│  ┌─────────────┐                                           │
│  │ formatter_  │  条件边 route_after_formatter             │
│  │ node        │                                           │
│  └──────┬──────┘                                           │
│         │                                                   │
│         ▼                                                   │
│  ┌─────────────┐                                           │
│  │  tool_node  │  执行 write_file                          │
│  └─────────────┘                                           │
└────────────────────────────────────────────────────────────┘
```

### 核心节点

| 节点 | 功能 | 说明 |
|------|------|------|
| `conversation_llm` | 对话生成 | 负责与用户交流，根据需要调用工具 |
| `formatter_llm` | 格式化 JSON | 将修改意图转化为规范 JSON |
| `tool_node` | 工具执行 | 执行 read_file / write_file |

### 路由规则

| 条件 | 路由 |
|------|------|
| 检测到 `signal_formatter_tool` 调用 | `formatter_llm` |
| 有工具调用 (read_file 等) | `tool_node` |
| 最后一条是 ToolMessage | `conversation_llm` |
| 无工具调用 | END |

## 简历数据结构

```json
{
  "basics": {
    "name": "姓名",
    "gender": "男/女/保密",
    "phone": "手机号",
    "email": "邮箱",
    "target_position": "期望岗位"
  },
  "education": [{
    "school_name": "学校",
    "major": "专业",
    "degree": "学历",
    "date_range": ["2020.09", "2025.06"],
    "school_tags": ["标签1", "标签2"],
    "theses": []
  }],
  "work_experience": [{
    "company_name": "公司",
    "job_title": "职位",
    "date_range": ["2024.07", "至今"],
    "job_type": "全职/实习",
    "details": ["工作内容1", "工作内容2"]
  }],
  "project_experience": [{
    "project_name": "项目名称",
    "role": "角色",
    "date_range": ["开始时间", "结束时间"],
    "details": ["项目内容1", "项目内容2"]
  }],
  "others": {
    "skills": ["技能1", "技能2"],
    "certificates": ["证书"],
    "languages": ["语言"]
  },
  "self_evaluation": ["自我评价"]
}
```

## JD 数据结构

```json
{
  "company": "公司名称",
  "position": "职位名称",
  "department": "部门/团队",
  "location": "工作地点",
  "job_type": "全职/实习",
  "salary": "薪资范围",
  "description": "职位描述",
  "requirements": {
    "education": "学历要求",
    "experience": "经验要求",
    "language": "语言要求",
    "skills": ["技能1", "技能2"]
  },
  "preferred_qualifications_text": "优先条件（逗号分隔）",
  "highlights_text": "亮点/关键词（逗号分隔）"
}
```

## 功能特性

### 核心功能
- **对话式简历优化** - 通过自然对话完善简历内容
- **JD 匹配分析** - 上传岗位描述，AI 分析匹配度
- **实时预览** - A4 分页预览，所见即所得
- **PDF 导出** - 服务端 WeasyPrint 生成矢量 PDF

### 编辑功能
- **简历编辑弹窗** - 表单式编辑基本信息、教育背景、工作经历、项目经历
- **岗位 JD 编辑** - 支持文本粘贴和图片识别解析
- **富文本编辑** - 工作内容/项目内容支持 Ctrl+B 加粗
- **日期选择器** - Element Plus 日期组件，支持"至今"选项
- **样式调节** - 页边距、模块边距、行间距、字体大小

### UI 特性
- **模块高亮** - AI 风格蓝紫色炫光动画
- **响应式设计** - 适配不同屏幕尺寸
- **实时行数统计** - 编辑区域显示行数
- **平滑动画** - 按钮 hover、弹窗过渡效果

### 技术特性
- **SSE 流式响应** - 实时显示 AI 生成内容
- **状态持久化** - LangGraph MemorySaver 支持断点续传
- **上下文压缩** - 对话历史过长时自动压缩

## 核心文件说明

| 文件 | 功能 |
|------|------|
| `resume_agent.py` | LangGraph 工作流定义、LLM 节点、路由函数 |
| `mcp_service_simple.py` | FastAPI 服务、SSE 流式输出、状态同步 |
| `tools.py` | read_file / write_file 工具函数 |
| `pdf_generator.py` | WeasyPrint PDF 生成器 |
| `App.vue` | SSE 通信、消息管理、文件上传、编辑弹窗 |
| `ResumePreview.vue` | A4 分页预览、样式控制、PDF 导出 |
| `RichTextEditor.vue` | 富文本编辑器 (加粗、换行) |

## 环境变量 (.env)

```env
LLM_API_KEY="sk-xxx"
BASE_URL="https://api.bltcy.ai/v1"
TAVILY_API_KEY="tvly-xxx"
```

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl + B` | 加粗选中文本 (在编辑框中) |
| `Ctrl + Enter` | 发送消息 (在全屏输入框中) |
