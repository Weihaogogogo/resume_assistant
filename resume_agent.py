"""
简历助手 AI 代理模块
使用 LangGraph 构建的智能对话系统，帮助用户完善简历。

核心设计原则：
1. 状态驱动：所有状态通过 AgentState 传递，使用 LangGraph checkpointer 持久化
2. 工具调用：只在必要时调用工具（signal_formatter_tool, save_resume_tool）
3. 消息过滤：只传递 HumanMessage/AIMessage/SystemMessage 给 LLM，跳过 ToolMessage
4. 无硬编码回复：所有 AI 回复由 LLM 生成，不使用硬编码内容
"""

import os
import json
import uuid
import asyncio
import httpx
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from dataclasses import field
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from dataclasses import dataclass
from typing import List
from pydantic import BaseModel, Field

# 全局变量：当前用户ID（由 mcp_service_simple.py 设置）
current_user_id = None

# 加载环境变量
load_dotenv()


# =============================================================================
# Pydantic 数据模型定义
# =============================================================================

class BasicInfo(BaseModel):
    """基本信息"""
    name: str = Field(..., description="姓名")
    gender: str = Field(..., description="性别")
    phone: str = Field(..., description="手机号")
    email: str = Field(..., description="邮箱")
    target_position: str = Field(..., description="期望岗位")


class Thesis(BaseModel):
    """论文信息"""
    title: str = Field(..., description="论文标题")
    details: List[str] = Field(default_factory=list, description="论文详细内容")


class Education(BaseModel):
    """教育背景"""
    school_name: str = Field(..., description="学校名称")
    major: str = Field(..., description="专业")
    degree: str = Field(..., description="学历")
    date_range: List[str] = Field(..., description="就读时间")
    school_tags: List[str] = Field(default_factory=list, description="学校性质标签")
    theses: List[Thesis] = Field(default_factory=list, description="论文列表")


class WorkExperience(BaseModel):
    """工作经历"""
    company_name: str = Field(..., description="公司名称")
    job_title: str = Field(..., description="职位名称")
    date_range: List[str] = Field(..., description="就职时间")
    job_type: str = Field(..., description="工作类型（实习/全职）")
    details: List[str] = Field(default_factory=list, description="工作详细内容")


class ProjectExperience(BaseModel):
    """项目经历"""
    project_name: str = Field(..., description="项目名称")
    role: str = Field(..., description="项目角色")
    date_range: List[str] = Field(..., description="项目时间")
    details: List[str] = Field(default_factory=list, description="项目详细内容")


class Others(BaseModel):
    """其他信息"""
    skills: List[str] = Field(default_factory=list, description="技能")
    certificates: List[str] = Field(default_factory=list, description="证书")
    languages: List[str] = Field(default_factory=list, description="语言")


class Resume(BaseModel):
    """完整简历数据结构"""
    basics: BasicInfo = Field(..., description="基本信息")
    education: List[Education] = Field(default_factory=list, description="教育背景")
    work_experience: List[WorkExperience] = Field(default_factory=list, description="工作经历")
    project_experience: List[ProjectExperience] = Field(default_factory=list, description="项目经历")
    others: Others = Field(default_factory=Others, description="其他信息")
    self_evaluation: List[str] = Field(default_factory=list, description="自我评价")


# =============================================================================
# JD (Job Description) 数据模型定义
# =============================================================================

class JDRequirements(BaseModel):
    """JD要求"""
    education: str = Field(default="", description="学历要求")
    experience: str = Field(default="", description="经验要求")
    skills: List[str] = Field(default_factory=list, description="技能要求")
    language: str = Field(default="", description="语言要求")


class JobDescription(BaseModel):
    """完整JD数据结构"""
    company: str = Field(default="", description="公司名称")
    position: str = Field(default="", description="职位名称")
    department: str = Field(default="", description="部门/团队")
    location: str = Field(default="", description="工作地点")
    job_type: str = Field(default="", description="全职/实习")
    salary: str = Field(default="", description="薪资范围")
    description: str = Field(default="", description="职位描述（核心职责）")
    requirements: JDRequirements = Field(default_factory=JDRequirements, description="任职要求")
    preferred_qualifications: List[str] = Field(default_factory=list, description="优先条件")
    highlights: List[str] = Field(default_factory=list, description="JD亮点/核心关键词")


# =============================================================================
# LLM 配置
# =============================================================================

httpx_client = httpx.Client(
    timeout=httpx.Timeout(90.0),
    limits=httpx.Limits(max_connections=10),
)

# Conversation LLM - 负责对话和读取
conversation_llm = ChatOpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("BASE_URL"),
    model="gemini-3-flash-preview",
    http_client=httpx_client,
    max_retries=3,
    temperature=0.1
)

# Formatter LLM - 负责格式化 JSON 和写入
formatter_llm = ChatOpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("BASE_URL"),
    model="gemini-3-flash-preview",
    http_client=httpx_client,
    max_retries=3,
    temperature=0.0  # 格式化需要更低温度
)

# JD Parser LLM - 负责解析JD文本/图片为JSON
jd_parser_llm = ChatOpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("BASE_URL"),
    model="gemini-3-flash-preview",
    http_client=httpx_client,
    max_retries=3,
    temperature=0.0  # 解析需要低温度，保证JSON格式准确
)


# =============================================================================
# Prompts - 系统提示词
# =============================================================================

CONVERSATION_PROMPT = """
# Role
你是资深职业顾问及面试官。你不仅是在修改文字，更是在通过对话挖掘用户经历中的“金子”。你擅长运用 STAR 法则（Situation, Task, Action, Result）将平庸的描述转化为具有竞争力的职业资产。

# 核心原则
- **深挖而非代笔**：不直接给模棱两可的建议，而是通过追问挖掘用户没写出来的细节。
- **结果导向**：坚信任何经历都必须有量化指标或具体成果。
- **学长风范**：专业、敏锐、直接，用自然流畅的对话消除用户的焦虑。

# 简历精炼法则 (核心指南)
当用户提供或询问经历时，请务必引导其符合以下标准：
1. **STAR 结构化**：
   - **Situation/Task**：用一句话概括背景（做了什么，解决了什么难题）。
   - **Action (关键)**：使用了什么工具/方法？具体拆解了哪些步骤？（例如：从“负责开发”引导至“利用 Vue3 + LangGraph 构建了状态机逻辑”）。
   - **Result**：必须有数字或对比（如：效率提升 30%、首屏加载从 2s 降至 0.5s、获得 500+ 用户好评）。
2. **动词精准**：优先使用“主导”、“重构”、“从0到1构建”、“优化”等高含金量动词。
3. **去除冗余**：删掉“负责”、“参与”等虚词，直接描述动作。
4. **关键信息加粗**：**重要** - 用两个星号 ** 包裹关键信息以加粗，包括量化指标（数字、百分比）、核心技术/工具、核心成就，以及标签式描述（如“技术栈：”、“职责：”等）。

# 简历质量约束（参考资深面试官标准）
1. **穿透包装**：识别并拆穿“用过程繁琐掩盖结果平庸”的防御性描述。引导用户关注价值而非工作量（例如“写了1w字”、“调研6款产品”等过程劳务化表述应转化为具体产出）。
2. **结果导向**：坚信没有量化结果的经历等同于“流水账”。每个经历必须包含数字或对比（如效率提升30%、用户增长500+等），否则引导用户补充。
3. **决策挖掘**：关注用户“为什么做”而不仅仅是“做了什么”。询问决策背后的原因、选型依据、权衡考虑，体现思考深度。
4. **避免黑话**：禁止使用“赋能、闭环、沉淀、颗粒度”等空洞话术。引导用户用具体、直白的语言描述实际贡献。
5. **负面惩罚意识**：如果用户提供的内容存在“过程劳务化”、“话术空心化”、“缺乏决策痕迹”，应指出并引导改进，而非直接采用。

# 用户的简历数据：{{resume_data}}

# 目标岗位JD数据：{{jd_data}}

# 对话逻辑规则
1. **引导式提问**：如果用户给出的经历太简略（如"我做过一个简历助手"），不要直接修改，要问："这个项目很有潜力。你能细说下你当时遇到最难的技术点是什么吗？或者你用什么指标衡量它的成功？"
2. **即时反馈**：当用户给出补充后，给出一个对比示例："你看，把'做简历助手'改成'基于大模型构建 STAR 法则映射引擎，提升用户简历诊断效率 40%'，是不是瞬间就有大厂感了？"
3. **确认修改**：仅当用户明确表示"好"、"就按这个改"、"确认"时，调用 `signal_formatter_tool`。

# 工具调用规则（当完成修改后，不需要调用工具）
- ask_confirmation: **重要** - 当你给出了完整的优化建议、可以达到修改标准时，**必须**调用此工具，该工具仅用于显示确定按钮按钮让用户便捷点击。
- signal_formatter_tool: 在用户确认修改意见后调用。

# 重要规则
- **重要** 当 just_saved=True（简历刚保存）时，说明简历已经修改完成了，不要调用 signal_formatter_tool 或 ask_confirmation。

# 禁止行为
- **重要** 绝对禁止输出 JSON 代码块。
- **重要** 严禁输出JSON格式内容。
- 绝对禁止说："已保存"、"已修改"、"正在为你更新"。
- 绝对禁止提及 JSON、Key、Value 等技术术语。

# 简历模块格式说明（供参考）
**注意**：括号内标注"数组"的字段均为数组格式，如`["条目1", "条目2"]`。
- basics: 基本信息（姓名、性别、手机、邮箱、期望岗位）
- education: 教育背景（学校、专业、学历、时间、标签（如985/211/双一流/强基计划等等）、论文）
- work_experience: 工作经历（公司、职位、时间、类型、具体内容（数组））
- project_experience: 项目经历（项目名称、角色、时间、具体内容（数组））
- others: 其他信息（技能（数组）、证书（数组）、语言（数组））
- self_evaluation: 自我评价（数组）

请根据用户的具体问题和当前简历内容，给出专业、有针对性的回复。"""


# JD Parser Prompt - 用于解析JD文本/图片为JSON
JD_PARSER_PROMPT = '''# Role
你是JD解析专家，负责将招聘描述（Job Description）解析为结构化JSON。

# 任务
将用户提供的JD文本或图片OCR内容解析为结构化数据。

# 严格的输出格式
你必须严格按照以下JSON Schema输出，直接输出JSON对象：

```json
{
  "type": "object",
  "properties": {
    "company": { "type": "string", "description": "公司名称" },
    "position": { "type": "string", "description": "职位名称" },
    "department": { "type": "string", "description": "部门/团队" },
    "location": { "type": "string", "description": "工作地点" },
    "job_type": { "type": "string", "description": "全职/实习" },
    "salary": { "type": "string", "description": "薪资范围" },
    "description": { "type": "string", "description": "职位描述（核心职责）" },
    "requirements": {
      "type": "object",
      "properties": {
        "education": { "type": "string", "description": "学历要求" },
        "experience": { "type": "string", "description": "经验要求" },
        "skills": { "type": "array", "items": { "type": "string" }, "description": "技能要求" },
        "language": { "type": "string", "description": "语言要求" }
      }
    },
    "preferred_qualifications": { "type": "array", "items": { "type": "string" }, "description": "优先条件" },
    "highlights": { "type": "array", "items": { "type": "string" }, "description": "JD亮点/核心关键词" }
  },
  "required": ["company", "position"]
}
```

# 严格规则
1. **只输出JSON**，不要有任何解释、前缀、后缀、markdown代码块标记
2. **必须包含所有字段**，即使值为空字符串或空数组
3. **skills、preferred_qualifications、highlights 必须是数组格式**
4. 如果原始JD没有某字段，设置为空字符串 "" 或空数组 []
5. 绝对不要输出 ```json 或 ``` 标记
6. 绝对不要输出其他任何文字

# 示例
输入：字节跳动招聘高级产品经理，要求本科以上学历，3年以上经验
输出：{"company":"字节跳动","position":"高级产品经理","department":"","location":"","job_type":"全职","salary":"","description":"","requirements":{"education":"本科以上","experience":"3年以上","skills":[],"language":""},"preferred_qualifications":[],"highlights":[]}
'''


FORMATTER_PROMPT = """# Role
你是简历格式化专家，负责将用户的修改意图转化为规范的 JSON 格式，并调用 save_resume 工具保存结果。

# 核心规则
1. 从对话历史中，分析用户想要修改什么内容
2. 结合当前的简历数据，只修改用户明确指定的部分，允许覆盖部分原有内容
3. 将修改内容格式化为符合 JSON schema 的格式
4. **保留原有内容的完整性**，只修改用户明确指定的部分
5. **必须调用 save_resume 工具**将 JSON 保存到数据库

# 如何识别修改意图
- 用户说"把xxx改成yyy"、"修改xxx为yyy"、"xxx换成yyy"等 → 明确修改指令
- 用户说"好的"、"可以"、"确认"等 → 这是确认词，不是修改内容
- 根据上下文对话，理解用户的真实修改需求

# JSON 结构规范
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
    "degree": "学位",
    "date_range": ["开始时间", "结束时间"],
    "school_tags": ["标签1", "标签2"],
    "theses": []
  }],
  "work_experience": [{
    "company_name": "公司",
    "job_title": "职位",
    "date_range": ["开始时间", "结束时间"],
    "job_type": "实习/全职",
    "details": ["具体工作内容1", "具体工作内容2"]
  }],
  "project_experience": [{
    "project_name": "项目名称",
    "role": "角色",
    "date_range": ["开始时间", "结束时间"],
    "details": ["具体内容1", "具体内容2"]
  }],
  "others": {
    "skills": ["技能1", "技能2"],
    "certificates": ["证书1", "证书2"],
    "languages": ["语言"]
  },
  "self_evaluation": ["自我评价1", "自我评价2"]
}

#用户的简历数据：{{resume_data}}
```

# 内容编辑自由度
- **允许**：将长字符串拆分为数组（如 details 数组）
- **允许（重要）**：用两个星号 ** 包裹关键信息以加粗，包括量化指标（数字、百分比）、核心技术/工具、核心成就，以及标签式描述（如“技术栈：”、“职责：”等）。
- **允许（谨慎）**：仅在用户表述明显不完整、模糊或遗漏关键信息时，才进行小幅优化
- **允许**：补充缺失的元数据（如 date_range）
- **禁止**：修改用户未指定的字段
- **禁止**：删除用户未要求删除的内容
- **禁止**：大段重写用户的原始表述

# 输出要求
1. 直接调用 save_resume 工具，传入格式化后的完整 JSON
2. 不要输出任何解释性文字
"""


# =============================================================================
# LangChain Tools
# =============================================================================

@tool
def save_resume_tool(content: str = "", user_id: int = None) -> str:
    """
    将格式化后的简历数据保存到数据库

    Args:
        content: JSON 格式的简历数据
        user_id: 用户ID（从状态中传递）
    """
    import re
    from tools import update_resume

    # 检查是否有用户ID
    if user_id is None:
        return "错误：无法确定用户身份，请确保已登录"

    # 清理 markdown 代码块标记
    content = re.sub(r'```json\s*', '', content)
    content = re.sub(r'```\s*', '', content)
    content = content.strip()

    # 提取 JSON 对象（如果包含其他文字）
    if not content.startswith('{'):
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            content = match.group()

    # 解析并保存到数据库
    try:
        resume_data = json.loads(content)
        result = update_resume(resume_data, user_id=user_id)
        return result
    except json.JSONDecodeError as e:
        return f"保存失败：JSON 格式错误"


@tool
def signal_formatter_tool() -> str:
    """发送路由信号，让系统准备格式化简历数据。
     当用户同意修改简历时调用此工具。
     返回路由信号，不执行实际保存操作。
     """
    return "路由信号：准备转向 formatter_llm"


@tool
def ask_confirmation(content: str = "", options: list = None) -> str:
    """
    当你给出明确的修改建议后，调用此工具显示确认按钮。

    Args:
        content: 确认提示文字，如 "确认保存此修改吗？"
        options: 选项列表，不传则使用默认的 [确认, 取消]
    """
    import json
    import uuid

    # 默认选项
    default_options = [
        {"label": "确认", "value": "confirm", "style": "primary"},
        {"label": "取消", "value": "cancel", "style": "default"}
    ]

    options = options or default_options

    # 返回结构化标记，后端解析
    marker = {
        "type": "ask_confirmation",
        "content": content or "确认执行此操作？",
        "options": options,
        "confirm_id": str(uuid.uuid4())[:8]
    }

    return f"[CONFIRM_MARKER:{json.dumps(marker)}]"


# 工具列表 - conversation_llm 只能调用信号工具和确认工具，不能直接保存
conversation_tools = [signal_formatter_tool, ask_confirmation]
formatter_tools = [save_resume_tool]


# =============================================================================
# Agent State
# =============================================================================

@dataclass
class AgentState:
    """
    代理状态

    Attributes:
        messages: 对话消息列表
        resume_data: 简历数据（从 resume.json 读取）
        jd_data: 目标岗位JD数据（从 jd.json 读取）
        pending_confirmation: 待确认状态（用于显示确认按钮）
        just_saved: 标记刚保存了简历，用于引导 LLM 不再调用工具
        user_id: 当前用户ID，用于数据隔离
    """
    messages: list = field(default_factory=list)
    resume_data: dict = None  # None 表示尚未读取简历
    jd_data: dict = None  # None 表示尚未加载JD
    pending_confirmation: dict = None  # 待确认状态
    just_saved: bool = False  # 刚保存简历后设置为 True
    user_id: int = None  # 当前用户ID


# =============================================================================
# DEBUG: 添加诊断日志
# =============================================================================

def debug_print_state(state: AgentState, location: str = ""):
    """打印当前状态用于调试"""
    import sys
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"[DEBUG@{location}]", file=sys.stderr)
    print(f"  messages count: {len(state.messages)}", file=sys.stderr)
    print(f"  resume_data keys: {list((state.resume_data or {}).keys()) if state.resume_data else None}", file=sys.stderr)
    print(f"  jd_data loaded: {bool(state.jd_data)}", file=sys.stderr)
    print(f"  pending_confirmation: {bool(state.pending_confirmation)}", file=sys.stderr)
    
    # 打印最后几条消息
    if state.messages:
        print(f"  last 3 messages:", file=sys.stderr)
        for i, msg in enumerate(state.messages[-3:]):
            msg_type = type(msg).__name__
            content = getattr(msg, 'content', '') or ''
            content_str = str(content)[:80] if content else ''
            print(f"    [{len(state.messages)-3+i}] {msg_type}: {content_str}...", file=sys.stderr)
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                print(f"       tool_calls: {[tc.name if hasattr(tc, 'name') else tc.get('name') for tc in msg.tool_calls]}", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

def extract_user_intent(state: AgentState) -> str:
    """
    提取用户的修改意图

    从消息历史中提取用户的修改请求。
    将 HumanMessage 和 AIMessage 拼接成对话历史，让 LLM 判断修改意图。

    Args:
        state: 当前状态

    Returns:
        完整的对话历史文本
    """
    conversation_history = []
    for msg in state.messages:
        if isinstance(msg, HumanMessage):
            conversation_history.append(f"用户: {msg.content}")
        elif isinstance(msg, AIMessage):
            conversation_history.append(f"助手: {msg.content}")
        elif isinstance(msg, ToolMessage):
            tool_name = getattr(msg, 'name', 'unknown')
            conversation_history.append(f"[工具 {tool_name}]: {msg.content}")

    return "\n".join(conversation_history)


# =============================================================================
# Nodes
# =============================================================================

async def conversation_node(state: AgentState) -> dict:
    """
    Conversation LLM 节点

    处理用户对话，根据情况决定是否需要读取文件或转向 formatter
    """
    debug_print_state(state, "conversation_node_ENTER")
    
    print(f"\n=== [Node] conversation_llm ===")
    print(f"Input: {len(state.messages)} messages")
    for i, msg in enumerate(state.messages):
        content = getattr(msg, 'content', '')
        content_str = str(content)[:50] if content else ''
        msg_type = type(msg).__name__
        has_tool_calls = hasattr(msg, 'tool_calls') and msg.tool_calls
        print(f"  [{i}] {msg_type}: {content_str}... (tool_calls: {bool(has_tool_calls)})")

    last_msg = state.messages[-1] if state.messages else None
    if not last_msg:
        print("=== [End] conversation_llm (no messages) ===\n")
        return {"messages": state.messages, "resume_data": state.resume_data or {}, "jd_data": state.jd_data or {}, "user_id": state.user_id}

    # 构建系统消息，使用模板替换 resume_data
    if state.resume_data:
        resume_json = json.dumps(state.resume_data, ensure_ascii=False, indent=2)
        system_content = CONVERSATION_PROMPT.replace("{{resume_data}}", f"\n{resume_json}\n")
    else:
        system_content = CONVERSATION_PROMPT.replace("{{resume_data}}", "\n（简历数据尚未加载）")

    # 注入 jd_data
    if state.jd_data:
        jd_json = json.dumps(state.jd_data, ensure_ascii=False, indent=2)
        system_content = system_content.replace("{{jd_data}}", f"\n目标岗位 JD 数据：\n{jd_json}\n")
    else:
        system_content = system_content.replace("{{jd_data}}", "\n（目标岗位JD数据尚未加载）")

    # 过滤掉 ToolMessage，只保留 HumanMessage 和 AIMessage 传给 LLM
    # ToolMessage 是工具执行的结果，不应该传给 LLM
    # 注意：如果 AIMessage 带有 tool_calls（但工具还没执行），需要清空 tool_calls
    llm_messages = []
    for msg in state.messages:
        if isinstance(msg, ToolMessage):
            continue  # 跳过 ToolMessage
        elif isinstance(msg, AIMessage) and msg.tool_calls:
            # 如果 AIMessage 有 tool_calls，清空它们（工具会在 tool_node 中执行）
            llm_messages.append(AIMessage(content=msg.content, tool_calls=[]))
        else:
            llm_messages.append(msg)

    # 消息已由 save_state_async 在超过 20 条时压缩，这里使用过滤后的消息
    messages = [SystemMessage(content=system_content)] + llm_messages
    
    # 如果刚保存了简历，添加一条 HumanMessage 提醒 LLM
    if getattr(state, 'just_saved', False):
        messages.append(HumanMessage(content="[系统提示：简历已成功保存到数据库，请不要调用任何工具，直接回复用户]"))
        print("[Debug] 已添加 just_saved 提示给 LLM")

    # 调用 LLM
    try:
        conversation_llm_with_tools = conversation_llm.bind_tools(
            conversation_tools,
            tool_choice="auto"
        )
        # 不要添加 stop 序列，否则可能导致工具名称被截断
        async with asyncio.timeout(60.0):
            response = await conversation_llm_with_tools.ainvoke(messages)
    except asyncio.TimeoutError:
        raise TimeoutError("LLM 调用超时，请稍后重试")
    except Exception as e:
        raise RuntimeError(f"LLM 调用失败: {str(e)}")

    # 打印 LLM 输出
    print("LLM Output:")
    print(f"  content: {repr(response.content)[:200]}")
    if hasattr(response, 'tool_calls') and response.tool_calls:
        print(f"  tool_calls: {[tc.name if hasattr(tc, 'name') else tc.get('name') for tc in response.tool_calls]}")
    print("=== [End] conversation_llm ===\n")

    # 如果原始消息中有带 tool_calls 的 AIMessage，清除它们
    cleaned_messages = []
    seen_contents = set()  # 用于去重
    for msg in state.messages:
        content = getattr(msg, 'content', None)
        # 跳过 list 类型的内容（不可哈希）
        if isinstance(content, list):
            content = str(content)
        msg_key = (content, type(msg).__name__)
        if msg_key[0] and msg_key[0] not in seen_contents:
            seen_contents.add(msg_key[0])
            if isinstance(msg, AIMessage) and msg.tool_calls:
                cleaned_messages.append(AIMessage(content=msg.content, tool_calls=[]))
            else:
                cleaned_messages.append(msg)

    # 返回所有消息：原始消息 + 新响应（这样上下文才能累积）
    all_messages = list(state.messages) + [response]
    output_state = {
        "messages": all_messages,
        "resume_data": state.resume_data or {},
        "jd_data": state.jd_data or {},
        "just_saved": False,  # 清除 just_saved 标记
        "user_id": state.user_id  # 保留用户ID
    }
    
    # 创建临时状态对象用于调试
    class DebugState:
        def __init__(self, d):
            self.messages = d.get("messages", [])
            self.resume_data = d.get("resume_data")
            self.jd_data = d.get("jd_data")
            self.pending_confirmation = None
    
    debug_print_state(DebugState(output_state), "conversation_node_EXIT")
    
    return output_state


async def tool_node(state: AgentState) -> dict:
    """
    工具执行节点

    执行 LLM 调用的工具（如 save_resume_tool）
    """
    debug_print_state(state, "tool_node_ENTER")
    
    print(f"\n=== [Node] tool_node ===")
    last_message = state.messages[-1]

    # 检查是否有工具调用
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        print("=== [End] tool_node (no tool_calls) ===\n")
        # 没有工具调用时，返回原始消息（保持上下文）
        return {"messages": list(state.messages), "resume_data": state.resume_data or {}, "jd_data": state.jd_data or {}}

    # 打印工具调用信息
    print(f"Tool calls: {[tc.name if hasattr(tc, 'name') else tc.get('name') for tc in last_message.tool_calls]}")

    # 执行工具调用
    new_messages = []
    updated_resume_data = None  # 用于保存从工具参数中提取的简历数据
    pending_confirmation = None  # 用于触发确认按钮

    # 先检查是否有 ask_confirmation（如果有一次确认，就跳过其他保存操作）
    has_ask_confirmation = False
    for tc in last_message.tool_calls:
        tc_name = getattr(tc, 'name', '') or tc.get('name', '') if hasattr(tc, 'get') else ''
        if tc_name == 'ask_confirmation':
            has_ask_confirmation = True
            break

    for tool_call in last_message.tool_calls:
        # 兼容不同版本的 tool_call 格式
        # 可能是字典 {"name": "...", "args": {...}, "id": "..."} 或命名元组
        if hasattr(tool_call, 'name'):
            tool_name = tool_call.name
        elif isinstance(tool_call, dict) and 'name' in tool_call:
            tool_name = tool_call['name']
        else:
            continue  # 无效的工具调用，跳过

        # 如果有 ask_confirmation，跳过 save_resume_tool（由 ask_confirmation 的 pending_data 保存）
        if has_ask_confirmation and tool_name == 'save_resume_tool':
            continue

        if hasattr(tool_call, 'args'):
            tool_args = tool_call.args
        elif isinstance(tool_call, dict) and 'args' in tool_call:
            tool_args = tool_call['args']
        else:
            tool_args = {}

        # 查找工具函数
        tool_func = None
        for t in conversation_tools + formatter_tools:
            if t.name == tool_name:
                tool_func = t
                break

        if not tool_func:
            result = f"错误: 工具 {tool_name} 不存在"
            print(f"[Tool] 工具 {tool_name} 调用失败: 工具不存在")
        else:
            try:
                # 如果是保存简历工具，从参数中提取简历数据用于更新状态，并传递 user_id
                if tool_name == 'save_resume_tool':
                    content = tool_args.get('content', '')
                    try:
                        updated_resume_data = json.loads(content)
                    except json.JSONDecodeError:
                        pass
                    # 传递 user_id 以确保数据隔离
                    tool_args['user_id'] = state.user_id

                result = tool_func.invoke(tool_args)

                # 检测 ask_confirmation 工具返回值，解析确认标记
                if tool_name == 'ask_confirmation':
                    import re
                    marker_match = re.search(r'\[CONFIRM_MARKER:(.+)\]', result)
                    if marker_match:
                        marker = json.loads(marker_match.group(1))
                        # pending_confirmation 只用于让前端渲染 confirm area
                        pending_confirmation = {
                            "confirm_id": marker["confirm_id"],
                            "content": marker["content"],
                            "options": marker["options"]
                        }

                        # 替换显示内容，不显示原始标记
                        result = f"等待确认：{marker['content']}"

            except Exception as e:
                result = f"错误: {str(e)}"

        # 创建 ToolMessage，使用 tool_call 的 id 作为 tool_call_id
        # 这样 LangGraph/LangChain 可以正确追踪工具调用的关联关系
        if hasattr(tool_call, 'id'):
            tool_call_id = tool_call.id
        elif isinstance(tool_call, dict) and 'id' in tool_call:
            tool_call_id = tool_call['id']
        else:
            # 生成唯一的 tool_call_id，确保 LangChain 能正确关联
            tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
        tool_message = ToolMessage(
            content=result,
            tool_call_id=tool_call_id,
            name=tool_name
        )
        new_messages.append(tool_message)

    # 打印工具结果
    print(f"Tool results: {[m.content for m in new_messages]}")
    print("=== [End] tool_node ===\n")

    # 返回所有消息：原始消息 + 新消息（这样 router 才能找到 AIMessage 的 tool_calls）
    all_messages = list(state.messages) + new_messages
    
    # 检查是否执行了 save_resume_tool
    saved_resume = any(
        (isinstance(m, ToolMessage) and '简历已成功保存' in m.content) 
        for m in new_messages
    )
    
    return {
        "messages": all_messages,
        "resume_data": updated_resume_data if updated_resume_data else (state.resume_data or {}),
        "jd_data": state.jd_data or {},
        "pending_confirmation": pending_confirmation,  # 触发后端发送 confirm
        "just_saved": saved_resume,  # 标记刚保存了简历
        "user_id": state.user_id  # 保留用户ID
    }


async def formatter_node(state: AgentState) -> dict:
    """
    Formatter LLM 节点

    将用户的修改意图格式化为 JSON，并调用 save_resume 保存
    """
    debug_print_state(state, "formatter_node_ENTER")
    
    print(f"\n=== [Node] formatter_llm ===")
    print(f"Input: resume_data keys={list((state.resume_data or {}).keys())}")

    # 检查是否用户点击了确认
    last_message = state.messages[-1] if state.messages else None
    user_content = getattr(last_message, 'content', '') or ''
    is_confirm = '[CONFIRM_REPLY:' in user_content
    print(f"Trigger: {'confirm click' if is_confirm else 'modify request'}")

    # 提取用户修改意图
    user_modification = extract_user_intent(state)
    resume_data_str = json.dumps(state.resume_data or {}, ensure_ascii=False, indent=2)

    # 构建消息
    formatter_prompt = FORMATTER_PROMPT.replace("{{resume_data}}", f"\n{resume_data_str}\n")

    if is_confirm:
        # 用户点击确认，从对话历史中提取之前 AI 输出的修改建议
        # 找到最近的一条包含修改建议的 AIMessage
        previous_modification = ""
        for msg in reversed(state.messages):
            if isinstance(msg, AIMessage) and msg.content:
                # 跳过空的 AIMessage 或确认相关的消息
                if '[CONFIRM_REPLY:' not in msg.content and msg.content.strip():
                    previous_modification = msg.content
                    break

        messages = [
            SystemMessage(content=formatter_prompt),
            HumanMessage(content=f"""用户已确认保存之前的修改建议。请将以下修改建议格式化为规范的 JSON 格式，并调用 save_resume 工具保存。

=== 之前生成的修改建议 ===
{previous_modification}

=== 当前简历数据 ===
{resume_data_str}

请直接将修改建议格式化为 JSON 并调用 save_resume 工具保存。""")
        ]
    else:
        # 普通修改请求，从对话历史中提取修改意图
        messages = [
            SystemMessage(content=formatter_prompt),
            HumanMessage(content=f"""请分析以下对话历史，理解用户的修改意图，并格式化为 JSON：

=== 对话历史 ===
{user_modification}

=== 当前简历数据 ===
{resume_data_str}

请分析用户的修改需求，直接调用 save_resume 工具保存更新后的简历。""")
        ]

    # 调用 formatter LLM
    formatter_llm_with_tools = formatter_llm.bind_tools(
        formatter_tools,
        tool_choice="auto"
    )

    try:
        async with asyncio.timeout(60.0):
            response = await formatter_llm_with_tools.ainvoke(messages)
    except asyncio.TimeoutError:
        raise TimeoutError("Formatter LLM 调用超时，请稍后重试")

    # 提取 JSON 并清理
    content = response.content or "{}"
    import re
    content = re.sub(r'```json\s*', '', content)
    content = re.sub(r'```\s*', '', content)
    content = content.strip()

    # 提取 JSON 对象
    if not content.startswith('{'):
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            content = match.group()
        else:
            content = "{}"

    # 验证 JSON
    try:
        json_data = json.loads(content)
        formatted_content = json.dumps(json_data, ensure_ascii=False, indent=2)
    except Exception:
        formatted_content = "{}"

    # 打印 LLM 输出
    print("LLM Output:")
    print(f"  content: {formatted_content[:200]}")
    if hasattr(response, 'tool_calls') and response.tool_calls:
        print(f"  tool_calls: {[tc.name if hasattr(tc, 'name') else tc.get('name') for tc in response.tool_calls]}")
    print("=== [End] formatter_llm ===\n")

    new_messages = [
        AIMessage(content=formatted_content, tool_calls=response.tool_calls if hasattr(response, 'tool_calls') else [])
    ]

    # 返回所有消息：原始消息 + 新消息（这样后续节点才能访问完整的上下文）
    all_messages = list(state.messages) + new_messages
    return {
        "messages": all_messages,
        "resume_data": state.resume_data or {},
        "jd_data": state.jd_data or {},
        "user_id": state.user_id  # 保留用户ID
    }


# =============================================================================
# Routing Functions
# =============================================================================

def route_after_conversation(state: AgentState) -> str:
    """
    conversation_llm 后的路由决策

    Returns:
        'formatter_llm': 需要格式化简历
        'tool_node': 直接保存简历
        END: 对话结束
    """
    if not state.messages:
        return END

    last_message = state.messages[-1]
    user_content = getattr(last_message, 'content', '') or ''

    # 如果是确认按钮点击，直接路由到 formatter_llm
    if '[CONFIRM_REPLY:' in user_content:
        return "formatter_llm"

    # 检查是否有工具调用
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        for tool_call in last_message.tool_calls:
            tool_name = getattr(tool_call, 'name', '') or tool_call.get('name', '')
            if tool_name == 'signal_formatter_tool':
                return "formatter_llm"
            elif tool_name == 'save_resume_tool':
                return "tool_node"
            elif tool_name == 'ask_confirmation':
                return "tool_node"

    return END  # 无工具调用，结束对话


def route_after_formatter(state: AgentState) -> str:
    """
    formatter_llm 后的路由决策

    Returns:
        'tool_node': 需要执行 save_resume
        'conversation_llm': 写入完成，继续对话
    """
    last_message = state.messages[-1]

    # 有工具调用 → tool_node（save_resume）
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "tool_node"

    # 无工具调用 → conversation_llm（返回确认）
    return "conversation_llm"


# =============================================================================
# Graph Construction
# =============================================================================

graph_builder = StateGraph(AgentState)

# 添加节点（只有三个节点）
graph_builder.add_node("conversation_llm", conversation_node)
graph_builder.add_node("formatter_llm", formatter_node)
graph_builder.add_node("tool_node", tool_node)

# conversation_llm → formatter_llm / tool_node / END
# 从 START 流入，去向：END / formatter_llm / tool_node
graph_builder.add_conditional_edges(
    "conversation_llm",
    route_after_conversation,
    {
        "formatter_llm": "formatter_llm",
        "tool_node": "tool_node",
        END: END
    }
)


# =============================================================================
# 入口路由函数
# =============================================================================

def entry_router(state: AgentState) -> str:
    """
    START 节点的路由决策

    Returns:
        'conversation_llm': 普通对话
        'formatter_llm': 确认按钮点击
    """
    if not state.messages:
        return "conversation_llm"

    # 检查最后一条消息是否是确认按钮点击
    last_message = state.messages[-1]
    user_content = getattr(last_message, 'content', '') or ''

    if '[CONFIRM_REPLY:' in user_content:
        return "formatter_llm"

    return "conversation_llm"


# 设置入口点的条件路由
graph_builder.set_conditional_entry_point(entry_router)

# formatter_llm → tool_node / conversation_llm
graph_builder.add_conditional_edges(
    "formatter_llm",
    route_after_formatter,
    {
        "tool_node": "tool_node",
        "conversation_llm": "conversation_llm"
    }
)

# tool_node → conversation_llm / formatter_llm / END
# 根据工具调用类型决定下一个节点
def tool_node_router(state: AgentState) -> str:
    # 获取最后一条 ToolMessage（这是刚执行完的工具）
    last_msg = state.messages[-1] if state.messages else None
    
    if not last_msg:
        print("[Router] tool_node_router: no messages, return END")
        return END
    
    # 如果是 ToolMessage，从 tool_call_id 找到对应的 AIMessage
    if isinstance(last_msg, ToolMessage):
        print(f"[Router] tool_node_router: last_msg is ToolMessage, tool_call_id={last_msg.tool_call_id}")
        print(f"[Router] state.messages count: {len(state.messages)}")
        
        # 在消息历史中找到对应的 AIMessage（包含 tool_calls）
        for i, msg in enumerate(reversed(state.messages[:-1])):
            msg_idx = len(state.messages) - 2 - i
            print(f"[Router] checking msg[{msg_idx}]: {type(msg).__name__}")
            print(f"[Router]   content: {str(getattr(msg, 'content', ''))[:50]}...")
            if isinstance(msg, AIMessage):
                tool_calls = getattr(msg, 'tool_calls', [])
                print(f"[Router]   has tool_calls: {bool(tool_calls)}, count: {len(tool_calls)}")
                if tool_calls:
                    for tc in tool_calls:
                        tc_id = getattr(tc, 'id', None) or tc.get('id', '')
                        tc_name = getattr(tc, 'name', '') or tc.get('name', '')
                        print(f"[Router]   tc: name={tc_name}, id={tc_id}")
                        if tc_id == last_msg.tool_call_id:
                            print(f"[Router] MATCH! tool_name={tc_name}")
                            if tc_name == 'save_resume_tool':
                                return "conversation_llm"
                            elif tc_name == 'signal_formatter_tool':
                                return "formatter_llm"
                # 继续检查其他消息，直到找到匹配
                continue
    
    # 检查是否有待确认状态（ask_confirmation）
    pending = getattr(state, "pending_confirmation", None)
    if pending:
        print("[Router] pending_confirmation exists, return END")
        return END  # 有待确认，返回 END

    print("[Router] default -> END")
    return END  # 默认结束

graph_builder.add_conditional_edges(
    "tool_node",
    tool_node_router,
    {
        "conversation_llm": "conversation_llm",
        "formatter_llm": "formatter_llm",
        END: END
    }
)

# 编译图（带 checkpointer 用于状态持久化）
# 根据环境变量选择 checkpointer
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import aiosqlite
import asyncio

use_sqlite = os.getenv("USE_SQLITE_CHECKPOINTER", "false").lower() == "true"

# 检测是否在 Docker 环境中运行
in_docker = os.path.exists("/.dockerenv") or os.getenv("DOCKER_CONTAINER", "")

async def create_async_checkpointer():
    """创建异步 checkpointer"""
    db_path = os.getenv("CHECKPOINTER_DB_PATH", "/app/data/checkpointer.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    checkpointer = AsyncSqliteSaver(conn)
    print(f"[Checkpointer] 使用 AsyncSQLite: {db_path}")
    return checkpointer

async def init_graph():
    """异步初始化图"""
    global graph
    
    if use_sqlite and in_docker:
        checkpointer = await create_async_checkpointer()
    else:
        checkpointer = MemorySaver()
        print("[Checkpointer] 使用内存存储")
    
    graph = graph_builder.compile(checkpointer=checkpointer)

# 在模块加载时初始化
try:
    asyncio.run(init_graph())
except Exception as e:
    print(f"[Checkpointer] 初始化失败: {e}")
    # 回退到内存存储
    graph = graph_builder.compile(checkpointer=MemorySaver())
    print("[Checkpointer] 回退到内存存储")
# =============================================================================
# 测试函数
# =============================================================================

async def run_agent():
    """命令行测试入口"""
    print("简历助手已启动，输入'退出'结束对话")
    print("=" * 50)

    thread_id = "cli_test"

    while True:
        user_input = input("\n你：")
        if user_input.lower() in ["退出", "quit", "exit"]:
            print("再见！")
            break

        initial_state = {
            "messages": [HumanMessage(content=user_input)],
            "resume_data": None
        }

        outputs = []
        error_message = None
        try:
            async for chunk in graph.astream(initial_state, config={"configurable": {"thread_id": thread_id}}):
                outputs.append(chunk)
        except TimeoutError as e:
            error_message = f"抱歉，处理时间过长，请稍后重试。"
        except RuntimeError as e:
            error_message = f"抱歉，我遇到了问题，请稍后重试。"

        # 如果有错误，直接显示错误消息
        if error_message:
            print("\n[助手回复]")
            print("-" * 40)
            print(error_message)
            print("-" * 40)
            continue

        # 提取最后一条 AIMessage
        final_response = None
        for output in outputs:
            for node_name, node_output in output.items():
                if isinstance(node_output, dict) and "messages" in node_output:
                    messages = node_output["messages"]
                    for msg in reversed(messages):
                        if isinstance(msg, AIMessage) and msg.content:
                            final_response = msg.content
                            break

        print("\n[助手回复]")
        print("-" * 40)
        print(final_response or "未找到回复")
        print("-" * 40)


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_agent())
