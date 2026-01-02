# DeepAgents - AI 简历助手

基于 LangGraph + Vue3 的智能简历助手，通过对话帮助用户完善简历内容。

## 目录结构

```
DeepAgents/
├── frontend/                      # 前端 Vue3 项目
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatMessage.vue    # 聊天消息组件
│   │   │   └── ResumePreview.vue  # 简历预览组件 (A4分页、PDF导出)
│   │   ├── App.vue                # 主应用组件 (SSE流式通信)
│   │   ├── main.js                # 应用入口
│   │   └── style.css              # 全局样式
│   ├── package.json
│   ├── vite.config.js
│   └── dist/                      # 构建输出
│
├── mcp_service_simple.py          # FastAPI 服务入口 (SSE流式响应)
├── resume_agent.py                # LangGraph AI 代理核心
├── tools.py                       # 工具函数集合
├── pdf_generator.py               # PDF 生成器 (WeasyPrint)
├── start_backend.sh               # 后端启动脚本
│
├── resume.json                    # 简历数据存储
├── .env                           # 环境变量
└── .venv/                         # Python 虚拟环境
```

## 技术栈

### 前端
- **Vue 3.5.24** - 响应式 UI 框架
- **Vite 7.2.4** - 构建工具
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
    "gender": "性别",
    "phone": "手机号",
    "email": "邮箱",
    "target_position": "期望岗位"
  },
  "education": [{
    "school_name": "学校",
    "major": "专业",
    "degree": "学历",
    "date_range": ["开始时间", "结束时间"],
    "school_tags": ["标签"],
    "theses": []
  }],
  "work_experience": [{
    "company_name": "公司",
    "job_title": "职位",
    "date_range": ["开始时间", "结束时间"],
    "job_type": "实习/全职",
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

## 核心文件说明

| 文件 | 功能 |
|------|------|
| `resume_agent.py` | LangGraph 工作流定义、LLM 节点、路由函数 |
| `mcp_service_simple.py` | FastAPI 服务、SSE 流式输出、状态同步 |
| `tools.py` | read_file / write_file 工具函数 |
| `pdf_generator.py` | WeasyPrint PDF 生成器 |
| `ResumePreview.vue` | A4 分页预览、样式控制、PDF 导出 |
| `App.vue` | SSE 通信、消息管理、文件上传 |

## 环境变量 (.env)

```env
LLM_API_KEY="sk-xxx"
BASE_URL="https://api.bltcy.ai/v1"
TAVILY_API_KEY="tvly-xxx"
```

## 功能特性

- **对话式简历优化** - 通过自然对话完善简历内容
- **实时预览** - A4 分页预览，所见即所得
- **样式调节** - 页边距、模块边距、行间距、字体大小
- **模块高亮** - AI 风格蓝紫色炫光动画
- **PDF 导出** - 服务端 WeasyPrint 生成矢量 PDF
- **状态持久化** - LangGraph MemorySaver 支持断点续传
- **上下文压缩** - 对话历史过长时自动压缩
