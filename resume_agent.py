"""
简历助手 AI 代理模块
使用 LangGraph 构建的智能对话系统，帮助用户完善简历。

核心设计原则：
1. 状态驱动：所有状态通过 AgentState 传递，使用 LangGraph checkpointer 持久化
2. 工具调用：只在必要时调用工具（read_file, write_file）
3. 消息过滤：只传递 HumanMessage/AIMessage/SystemMessage 给 LLM，跳过 ToolMessage
4. 无硬编码回复：所有 AI 回复由 LLM 生成，不使用硬编码内容
"""

import os
import json
import asyncio
import httpx
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from dataclasses import dataclass
from typing import List
from pydantic import BaseModel, Field

# 导入自定义工具
from tools import read_file, write_file

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
4. **关键信息加粗**：用两个星号 ** 包裹关键信息以加粗，包括量化指标（数字、百分比）、核心技术/工具、核心成就，以及标签式描述（如“技术栈：”、“职责：”等）。

# 用户的简历数据：{{resume_data}}

# 对话逻辑规则
1. **引导式提问**：如果用户给出的经历太简略（如“我做过一个简历助手”），不要直接修改，要问：“这个项目很有潜力。你能细说下你当时遇到最难的技术点是什么吗？或者你用什么指标衡量它的成功？”
2. **即时反馈**：当用户给出补充后，给出一个对比示例：“你看，把‘做简历助手’改成‘基于大模型构建 STAR 法则映射引擎，提升用户简历诊断效率 40%’，是不是瞬间就有大厂感了？”
3. **确认修改**：仅当用户明确表示“好”、“就按这个改”、“确认”时，调用 `signal_formatter_tool`。

# 工具调用规则
- read_file_tool: 当用户问到关于简历的问题、且当前简历数据尚未加载时调用。
- signal_formatter_tool: 仅在用户确认修改意见后调用。

# 禁止行为
- 绝对禁止说：“已保存”、“已修改”、“正在为你更新”。
- 绝对禁止提及 JSON、Key、Value 等技术术语。
- 严禁输出 JSON 代码块。

# 简历模块格式说明（供参考）
**注意**：括号内标注"数组"的字段均为数组格式，如`["条目1", "条目2"]`。
- basics: 基本信息（姓名、性别、手机、邮箱、期望岗位）
- education: 教育背景（学校、专业、学历、时间、标签（如985/211/双一流/强基计划等等）、论文）
- work_experience: 工作经历（公司、职位、时间、类型、具体内容（数组））
- project_experience: 项目经历（项目名称、角色、时间、具体内容（数组））
- others: 其他信息（技能（数组）、证书（数组）、语言（数组））
- self_evaluation: 自我评价（数组）

请根据用户的具体问题和当前简历内容，给出专业、有针对性的回复。"""


FORMATTER_PROMPT = """# Role
你是简历格式化专家，负责将用户的修改意图转化为规范的 JSON 格式，并调用 write_file 工具保存结果。

# 核心规则
1. 从对话历史中，分析用户想要修改什么内容
2. 结合当前的简历数据，只修改用户明确指定的部分，允许覆盖部分原有内容
3. 将修改内容格式化为符合 JSON schema 的格式
4. **保留原有内容的完整性**，只修改用户明确指定的部分
5. **必须调用 write_file 工具**将 JSON 保存到 resume.json

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
- **允许（谨慎）**：仅在用户表述明显不完整、模糊或遗漏关键信息时，才进行小幅优化
- **允许**：补充缺失的元数据（如 date_range）
- **禁止**：修改用户未指定的字段
- **禁止**：删除用户未要求删除的内容
- **禁止**：大段重写用户的原始表述

# 输出要求
1. 直接调用 write_file 工具，传入格式化后的完整 JSON
2. 不要输出任何解释性文字
"""


# =============================================================================
# LangChain Tools
# =============================================================================

@tool
def read_file_tool(file_path: str = "resume.json") -> str:
    """读取简历文件内容"""
    return read_file(file_path=file_path)


@tool
def write_file_tool(file_path: str = "resume.json", content: str = "") -> str:
    """
    写入 JSON 内容到文件

    Args:
        file_path: 文件路径
        content: JSON 格式的内容
    """
    import re

    # 清理 markdown 代码块标记
    content = re.sub(r'```json\s*', '', content)
    content = re.sub(r'```\s*', '', content)
    content = content.strip()

    # 提取 JSON 对象（如果包含其他文字）
    if not content.startswith('{'):
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            content = match.group()

    # 保存文件
    write_file(file_path=file_path, content=content)
    return "简历已成功保存到 resume.json"


@tool
def signal_formatter_tool() -> str:
    """当用户明确同意修改简历时，必须调用此工具。
     此工具不执行任何实际操作，只是发送路由信号。
     示例场景：用户说"好的"、"可以"、"确认"、"开始吧"等同意修改时。
     """
    return "路由信号：准备转向 formatter_llm"


# 工具列表
conversation_tools = [read_file_tool, signal_formatter_tool]
formatter_tools = [write_file_tool]


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
    """
    messages: list
    resume_data: dict = None  # None 表示尚未读取简历


# =============================================================================
# 工具函数
# =============================================================================

def parse_resume_from_tool_message(content: str) -> dict:
    """
    从 ToolMessage 内容中解析简历数据

    Args:
        content: ToolMessage 的 content 字符串

    Returns:
        解析后的简历字典
    """
    try:
        # 移除 "文件 xxx 的内容：" 前缀
        if "的内容：" in content:
            content = content.split("的内容：", 1)[1].strip()

        # 尝试解析为 JSON
        resume_data = json.loads(content)
        return resume_data
    except json.JSONDecodeError:
        return {}


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

    return "\n".join(conversation_history)


# =============================================================================
# Nodes
# =============================================================================

async def conversation_node(state: AgentState) -> dict:
    """
    Conversation LLM 节点

    处理用户对话，根据情况决定是否需要读取文件或转向 formatter
    """
    last_msg = state.messages[-1] if state.messages else None
    if not last_msg:
        return {"messages": state.messages, "resume_data": state.resume_data or {}}

    # 构建系统消息，使用模板替换 resume_data
    if state.resume_data:
        resume_json = json.dumps(state.resume_data, ensure_ascii=False, indent=2)
        system_content = CONVERSATION_PROMPT.replace("{{resume_data}}", f"\n{resume_json}\n")
    else:
        system_content = CONVERSATION_PROMPT.replace("{{resume_data}}", "\n（简历数据尚未加载）")

    messages = [SystemMessage(content=system_content)] + list(state.messages)

    # 调用 LLM
    try:
        conversation_llm_with_tools = conversation_llm.bind_tools(
            conversation_tools,
            tool_choice="auto"
        )
        async with asyncio.timeout(60.0):
            response = await conversation_llm_with_tools.ainvoke(messages)
    except asyncio.TimeoutError:
        raise TimeoutError("LLM 调用超时，请稍后重试")
    except Exception as e:
        raise RuntimeError(f"LLM 调用失败: {str(e)}")

    # 如果原始消息中有带 tool_calls 的 AIMessage，清除它们
    cleaned_messages = []
    for msg in state.messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            cleaned_messages.append(AIMessage(content=msg.content, tool_calls=[]))
        else:
            cleaned_messages.append(msg)

    return {
        "messages": cleaned_messages + [response],
        "resume_data": state.resume_data or {}
    }


async def tool_node(state: AgentState) -> dict:
    """
    工具执行节点

    执行 LLM 调用的工具（read_file_tool 或 write_file_tool）
    执行 read_file_tool 后会更新 resume_data
    """
    last_message = state.messages[-1]

    # 检查是否有工具调用
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return {"messages": state.messages, "resume_data": state.resume_data or {}}

    # 执行工具调用
    new_messages = []
    updated_resume_data = state.resume_data

    for tool_call in last_message.tool_calls:
        # 兼容不同版本的 tool_call 格式
        # 可能是字典 {"name": "...", "args": {...}, "id": "..."} 或命名元组
        if hasattr(tool_call, 'name'):
            tool_name = tool_call.name
        elif isinstance(tool_call, dict) and 'name' in tool_call:
            tool_name = tool_call['name']
        else:
            continue  # 无效的工具调用，跳过

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
        else:
            try:
                result = tool_func.invoke(tool_args)
                # 如果是 read_file_tool，解析并更新 resume_data
                if tool_name == 'read_file_tool':
                    parsed_data = parse_resume_from_tool_message(result)
                    if parsed_data:
                        updated_resume_data = parsed_data
            except Exception as e:
                result = f"错误: {str(e)}"

        # 创建 ToolMessage，使用 tool_call 的 id 作为 tool_call_id
        # 这样 LangGraph/LangChain 可以正确追踪工具调用的关联关系
        if hasattr(tool_call, 'id'):
            tool_call_id = tool_call.id
        elif isinstance(tool_call, dict) and 'id' in tool_call:
            tool_call_id = tool_call['id']
        else:
            tool_call_id = ''
        tool_message = ToolMessage(
            content=result,
            tool_call_id=tool_call_id,
            name=tool_name
        )
        new_messages.append(tool_message)

    return {
        "messages": state.messages + new_messages,
        "resume_data": updated_resume_data if updated_resume_data else state.resume_data
    }


async def formatter_node(state: AgentState) -> dict:
    """
    Formatter LLM 节点

    将用户的修改意图格式化为 JSON，并调用 write_file 保存
    """
    # 提取用户修改意图
    user_modification = extract_user_intent(state)
    resume_data_str = json.dumps(state.resume_data or {}, ensure_ascii=False, indent=2)

    # 构建消息
    formatter_prompt = FORMATTER_PROMPT.replace("{{resume_data}}", f"\n{resume_data_str}\n")

    messages = [
        SystemMessage(content=formatter_prompt),
        HumanMessage(content=f"""请分析以下对话历史，理解用户的修改意图，并格式化为 JSON：

=== 对话历史 ===
{user_modification}

=== 当前简历数据 ===
{resume_data_str}

请分析用户的修改需求，直接调用 write_file 工具保存更新后的简历。""")
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

    return {
        "messages": state.messages + [
            AIMessage(content=formatted_content, tool_calls=response.tool_calls if hasattr(response, 'tool_calls') else [])
        ],
        "resume_data": state.resume_data or {}
    }


# =============================================================================
# Routing Functions
# =============================================================================

def route_after_conversation(state: AgentState) -> str:
    """
    conversation_llm 后的路由决策

    Returns:
        'formatter_llm': 需要格式化写入
        'tool_node': 需要执行工具
        END: 对话结束
    """
    last_message = state.messages[-1]
    content = str(getattr(last_message, 'content', ''))

    # 1. 检查是否有工具调用
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        # 检查是否是 formatter_llm 路由信号（signal_formatter_tool 调用）
        for tool_call in last_message.tool_calls:
            # 兼容不同版本的 tool_call 格式
            if hasattr(tool_call, 'name'):
                func_name = tool_call.name
            elif isinstance(tool_call, dict):
                # 新版本格式: {'name': 'xxx', 'args': {...}}
                func_name = tool_call.get('name', '')
                if not func_name:
                    # 旧版本格式: {'function': {'name': 'xxx', 'arguments': {...}}}
                    func_name = tool_call.get('function', {}).get('name', '')
            else:
                func_name = ''
            if func_name == 'signal_formatter_tool':
                return "formatter_llm"
        # 普通工具调用 → tool_node
        return "tool_node"

    # 2. 如果最后一条是 ToolMessage（工具刚执行完）
    if isinstance(last_message, ToolMessage):
        # 检查是否是重复的工具调用（避免无限循环）
        if len(state.messages) >= 2:
            prev_message = state.messages[-2]
            if isinstance(prev_message, ToolMessage) and prev_message.name == last_message.name:
                return END
        # 根据工具返回内容判断下一步：
        # - "的内容：" -> read_file 结果，需要继续对话
        # - "已成功保存" -> write_file 结果，直接结束
        if '已成功保存' in content:
            return END
        return "conversation_llm"

    # 3. 兼容旧逻辑：检查是否需要转向 formatter_llm（用户确认修改）
    if "[转向 formatter_llm]" in content:
        return "formatter_llm"

    # 4. 无工具调用 → 结束对话
    return END


def route_after_formatter(state: AgentState) -> str:
    """
    formatter_llm 后的路由决策

    Returns:
        'tool_node': 需要执行 write_file
        'conversation_llm': 写入完成，继续对话
    """
    last_message = state.messages[-1]

    # 有工具调用 → tool_node（write_file）
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "tool_node"

    # 无工具调用 → conversation_llm
    return "conversation_llm"


# =============================================================================
# Graph Construction
# =============================================================================

graph_builder = StateGraph(AgentState)

# 添加节点
graph_builder.add_node("conversation_llm", conversation_node)
graph_builder.add_node("formatter_llm", formatter_node)
graph_builder.add_node("tool_node", tool_node)

# 设置入口点
graph_builder.set_entry_point("conversation_llm")

# conversation_llm → formatter_llm / tool_node / conversation_llm / END
graph_builder.add_conditional_edges(
    "conversation_llm",
    route_after_conversation,
    {
        "formatter_llm": "formatter_llm",
        "tool_node": "tool_node",
        "conversation_llm": "conversation_llm",
        END: END
    }
)

# formatter_llm → tool_node / conversation_llm
graph_builder.add_conditional_edges(
    "formatter_llm",
    route_after_formatter,
    {
        "tool_node": "tool_node",
        "conversation_llm": "conversation_llm"
    }
)

# tool_node → conversation_llm（工具执行完后返回结果）
graph_builder.add_edge("tool_node", "conversation_llm")

# 编译图（带 checkpointer 用于状态持久化）
memory = MemorySaver()
graph = graph_builder.compile(checkpointer=memory)


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
            print("\n💡 助手回复:")
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

        print("\n💡 助手回复:")
        print("-" * 40)
        print(final_response or "未找到回复")
        print("-" * 40)


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_agent())
