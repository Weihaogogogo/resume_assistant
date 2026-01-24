"""
简历助手 MCP 服务

提供 HTTP API 接口，连接前端和 AI 代理。

核心职责：
1. HTTP 请求处理和响应
2. SSE 流式输出
3. 用户认证（JWT）
4. 数据持久化（SQLite）
"""

import json
import asyncio
import base64
import platform
import subprocess
import os
import sys
import uuid
from datetime import datetime
from fastapi import FastAPI, Request, UploadFile, File, Form, Depends, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入 resume_agent 中的 graph 和 conversation_llm
from resume_agent import graph, conversation_llm, current_user_id
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

# 导入自定义模块
from database import (
    init_db, get_db, create_user, get_user_by_email,
    save_user_resume, get_user_resume, save_user_jd, get_user_jd,
    check_invite_code, use_invite_code, create_invite_code
)
from auth import (
    verify_password, get_password_hash, create_access_token,
    get_current_user, oauth2_scheme
)

# PDF 生成器 - 懒加载（在 API 调用时才导入）
_pdf_generator = None

# =============================================================================
# 上下文压缩状态管理
# =============================================================================

class CompressionState:
    """全局压缩状态管理"""
    compressing = False  # 是否正在压缩
    pending_futures = []  # 等待压缩完成的 Future 列表

compression_state = CompressionState()

# 上下文压缩配置
MAX_HUMAN_MESSAGES = 15  # 最多保留多少条 HumanMessage
KEEP_RECENT = 5  # 保留最近多少条不压缩


def wait_for_compression():
    """等待当前压缩完成（如果正在压缩）"""
    if compression_state.compressing:
        future = asyncio.get_event_loop().create_future()
        compression_state.pending_futures.append(future)
        return future
    return None


def notify_compression_complete():
    """通知压缩完成，处理等待中的请求"""
    compression_state.compressing = False
    for future in compression_state.pending_futures:
        if not future.done():
            future.set_result(True)
    compression_state.pending_futures.clear()


def _setup_weasyprint_env():
    """设置 WeasyPrint 所需的 macOS 环境变量"""
    if platform.system() == "Darwin":
        libs = ['pango', 'harfbuzz', 'cairo', 'fontconfig']
        lib_paths = []

        for lib in libs:
            result = subprocess.run(['brew', '--prefix', lib], capture_output=True, text=True)
            if result.returncode == 0:
                lib_path = os.path.join(result.stdout.strip(), 'lib')
                lib_paths.append(lib_path)

        if lib_paths:
            os.environ['DYLD_LIBRARY_PATH'] = ':'.join(lib_paths)
            print(f"已设置 DYLD_LIBRARY_PATH={' '.join(lib_paths)}")


def get_pdf_generator():
    """懒加载 PDF 生成器"""
    global _pdf_generator
    if _pdf_generator is None:
        _setup_weasyprint_env()
        from pdf_generator import generate_pdf
        _pdf_generator = generate_pdf
    return _pdf_generator


def generate_session_id() -> str:
    """生成唯一会话 ID"""
    return str(uuid.uuid4())


# =============================================================================
# Pydantic Models
# =============================================================================

class RegisterRequest(BaseModel):
    """注册请求"""
    email: str
    password: str
    invite_code: str


class TokenResponse(BaseModel):
    """Token 响应"""
    access_token: str
    token_type: str
    user: dict


class UserResponse(BaseModel):
    """用户信息响应"""
    id: int
    email: str
    created_at: datetime


class SaveResumeRequest(BaseModel):
    """保存简历请求"""
    resume_data: dict


# =============================================================================
# LLM 上下文压缩
# =============================================================================

async def compress_context_with_llm(messages, max_summary_length=150):
    """
    使用 LLM 对早期对话进行语义压缩
    """
    if len(messages) <= 5:
        return messages

    early_messages = messages[:-5]
    recent_messages = messages[-5:]

    conversation_text = ""
    for msg in early_messages:
        role = getattr(msg, 'role', 'unknown') if hasattr(msg, 'role') else type(msg).__name__
        content = getattr(msg, 'content', str(msg))
        if isinstance(content, list):
            text_content = []
            for c in content:
                if isinstance(c, dict):
                    type_key = 'type'
                    if type_key in c and c[type_key] == 'text':
                        text_content.append(c)
            content = str(text_content)
        conversation_text += f"【{role}】{str(content)[:300]}\n"

    summary_prompt = ChatPromptTemplate.from_messages([
        ("system", f"""你是对话摘要专家。将以下对话压缩成简洁摘要：

要求：
1. 摘要长度：不超过{max_summary_length}个汉字
2. 保留关键信息：用户基本信息、工作经历、教育背景、已完成的修改、当前上下文
3. 格式：
   [早期对话摘要]
   - 用户信息：xxx
   - 已完成：xxx
   - 待完善：xxx
   - 当前上下文：xxx
"""),
        ("human", f"待压缩的对话：\n\n{conversation_text}")
    ])

    try:
        summary_chain = summary_prompt | conversation_llm
        summary_result = await summary_chain.ainvoke({})
        summary_content = summary_result.content.strip()
        print(f"[Context] LLM 摘要生成成功: {len(summary_content)}字")

        summary_message = SystemMessage(content=summary_content)
        return [summary_message] + recent_messages

    except Exception as e:
        print(f"[Context] LLM 摘要生成失败: {e}")
        return list(messages[-10:])


# =============================================================================
# FastAPI 应用
# =============================================================================

app = FastAPI(title="Resume Assistant MCP Service", version="2.0.0")

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化数据库
init_db()


# =============================================================================
# 认证端点
# =============================================================================

@app.post("/auth/register", response_model=TokenResponse)
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """
    用户注册

    - 邮箱+密码+邀请码
    - 返回 JWT Token
    """
    # 检查邀请码
    if not check_invite_code(db, request.invite_code):
        raise HTTPException(status_code=400, detail="邀请码无效或已使用")

    # 检查邮箱是否已存在
    if get_user_by_email(db, request.email):
        raise HTTPException(status_code=400, detail="邮箱已注册")

    # 创建用户
    hashed_password = get_password_hash(request.password)
    user = create_user(db, request.email, hashed_password, request.invite_code)

    # 使用邀请码
    use_invite_code(db, request.invite_code)

    # 生成 Token
    token = create_access_token({"sub": user.email})

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user={"id": user.id, "email": user.email, "created_at": user.created_at.isoformat()}
    )


@app.post("/auth/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """
    用户登录

    - 邮箱+密码
    - 返回 JWT Token
    """
    user = get_user_by_email(db, form_data.username)
    if not user:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账户已被禁用")

    token = create_access_token({"sub": user.email})

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user={"id": user.id, "email": user.email, "created_at": user.created_at.isoformat()}
    )


@app.get("/auth/me", response_model=UserResponse)
async def get_me(current_user = Depends(get_current_user)):
    """
    获取当前用户信息
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        created_at=current_user.created_at
    )


@app.get("/auth/invite-codes")
async def list_invites(current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    获取邀请码列表（需要登录）
    """
    from database import InviteCode
    codes = db.query(InviteCode).order_by(InviteCode.created_at.desc()).all()
    return [
        {"code": c.code, "is_used": c.is_used, "created_at": c.created_at.isoformat()}
        for c in codes
    ]


@app.post("/auth/invite-codes")
async def create_invite(request: Request, current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    生成邀请码（需要登录）
    """
    import random
    import string

    # 解析请求体
    try:
        body = await request.json()
        count = min(int(body.get('count', 1)), 20)
    except:
        count = 1

    codes = []
    for _ in range(count):
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        create_invite_code(db, code)
        codes.append({"code": code, "is_used": False, "created_at": None})

    return codes if count > 1 else {"code": codes[0]["code"]}


# =============================================================================
# 业务端点
# =============================================================================

@app.post("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "2.0.0"}


@app.post("/load_resume")
async def load_resume_endpoint(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    """
    加载当前用户的简历数据
    """
    try:
        print(f"[DEBUG] load_resume: current_user.id={current_user.id}, current_user.email={current_user.email}")
        resume_data = get_user_resume(db, current_user.id)
        print(f"[DEBUG] load_resume: resume_data={resume_data}")
        if isinstance(resume_data, dict) and "error" in resume_data:
            return JSONResponse(content={}, status_code=500)
        return JSONResponse(content=resume_data)
    except Exception as e:
        print(f"[ERROR] load_resume: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/save_resume")
async def save_resume_endpoint(request: SaveResumeRequest, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    """
    保存当前用户的简历数据
    """
    try:
        save_user_resume(db, current_user.id, request.resume_data)
        return JSONResponse(content={"success": True})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/load_jd")
async def load_jd_endpoint(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    """
    加载当前用户的JD数据
    """
    try:
        jd_data = get_user_jd(db, current_user.id)
        if isinstance(jd_data, dict) and "error" in jd_data:
            return JSONResponse(content={}, status_code=500)
        return JSONResponse(content=jd_data)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/save_jd")
async def save_jd_endpoint(request: Request, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    """
    保存当前用户的JD数据
    """
    try:
        request_data = await request.json()
        jd_data = request_data.get('jd_data', {})

        company = jd_data.get('company', '')
        position = jd_data.get('position', '')
        save_user_jd(db, current_user.id, jd_data, company, position)

        return JSONResponse(content={"success": True})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/save_conversation")
async def save_conversation_endpoint(request: Request, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    """
    保存对话历史
    """
    try:
        request_data = await request.json()
        session_id = request_data.get('session_id', 'default')
        messages = request_data.get('messages', [])

        from database import save_conversation
        save_conversation(db, current_user.id, session_id, messages)

        return JSONResponse(content={"success": True})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/load_conversation")
async def load_conversation_endpoint(request: Request, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    """
    加载对话历史
    """
    try:
        request_data = await request.json()
        session_id = request_data.get('session_id', 'default')

        from database import get_conversation
        messages = get_conversation(db, current_user.id, session_id)

        return JSONResponse(content=messages)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/parse_jd")
async def parse_jd_endpoint(request: Request, current_user = Depends(get_current_user)):
    """
    解析JD文本/图片为结构化JSON
    """
    try:
        import re
        request_data = await request.json()
        jd_text = request_data.get('text', '')
        jd_image = request_data.get('image', '')

        from resume_agent import jd_parser_llm, JD_PARSER_PROMPT

        if jd_image:
            if jd_image.startswith('data:image'):
                jd_image = jd_image.split(',')[1]

            message = HumanMessage(
                content=[
                    {"type": "text", "text": "请解析这张JD图片，提取结构化信息为JSON"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{jd_image}"}}
                ]
            )
        else:
            if not jd_text.strip():
                return JSONResponse(content={"error": "没有收到JD内容"}, status_code=400)
            message = HumanMessage(content=f"请解析以下JD内容：\n\n{jd_text}")

        response = await jd_parser_llm.ainvoke([
            SystemMessage(content=JD_PARSER_PROMPT),
            message
        ])

        content = response.content.strip()
        content = re.sub(r'^```json\s*', '', content)
        content = re.sub(r'^```\s*', '', content)
        content = re.sub(r'\s*```$', '', content)

        try:
            parsed_jd = json.loads(content)
        except json.JSONDecodeError:
            parsed_jd = {"error": "解析失败", "raw": content}

        return JSONResponse(content=parsed_jd)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/export_pdf")
async def export_pdf_endpoint(request: Request, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    """
    导出 PDF（从数据库读取简历）
    """
    try:
        # 尝试获取JSON，如果请求体为空则使用空字典
        try:
            request_data = await request.json()
        except Exception:
            request_data = {}
        style = request_data.get('style', {})

        # 从数据库获取简历
        resume_data = get_user_resume(db, current_user.id)
        if not resume_data:
            return JSONResponse(content="错误: 没有找到简历数据，请先创建或加载简历", status_code=400)

        generate_pdf = get_pdf_generator()
        pdf_bytes = generate_pdf(resume_data, style)

        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=resume_{current_user.id}.pdf"}
        )
    except Exception as e:
        print(f"PDF 导出错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse(content=f"错误: {str(e)}", status_code=500)


@app.post("/chat")
async def chat_endpoint(
    message: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    session_id: str = Form(""),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    聊天接口

    - 需要认证
    - 从数据库加载用户数据
    - 设置全局用户ID供工具使用
    """
    try:
        # 生成会话 ID
        if not session_id:
            session_id = generate_session_id()

        # 检测用户是否点击了确认按钮（必须在使用 message 之前）
        is_confirm_click = '[CONFIRM_REPLY:' in message.strip()

        print(f"[DEBUG] session_id: {session_id}")
        print(f"[DEBUG] is_confirm_click: {is_confirm_click}")
        print(f"[DEBUG] message.strip(): {message.strip()[:100]}...")

        # 构建消息内容
        message_content = []
        if message.strip():
            message_content.append({"type": "text", "text": message.strip()})

        # 处理文件上传
        for file in files:
            content = await file.read()
            if file.content_type.startswith("image/"):
                base64_content = base64.b64encode(content).decode("utf-8")
                message_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{file.content_type};base64,{base64_content}"}
                })
            elif file.content_type == "application/pdf":
                base64_content = base64.b64encode(content).decode("utf-8")
                message_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{file.content_type};base64,{base64_content}"}
                })

        # 从数据库加载用户数据
        resume_data = get_user_resume(db, current_user.id)
        jd_data = get_user_jd(db, current_user.id)

        # 创建用户消息（包含文本和图片附件）
        # 检查是否有图片附件
        has_image = any(item.get("type") == "image_url" for item in message_content)
        if has_image:
            # 有图片附件，使用多模态内容（包含文本和图片）
            current_message = HumanMessage(content=message_content)
        else:
            # 只有文本
            current_message = HumanMessage(content=message.strip())

        # 从数据库获取压缩后的上下文
        from database import get_conversation_context
        db_context_raw = get_conversation_context(db, current_user.id, session_id)

        # 只提取 HumanMessage，过滤掉 ToolMessage 和 AIMessage
        db_context = []
        for msg_dict in db_context_raw:
            msg_type = msg_dict.get("type", "")
            if msg_type == "human":
                content = msg_dict.get("content", "")
                db_context.append(HumanMessage(content=content))

        # 从 checkpointer 获取历史消息
        # 在 config 中包含 user_id，确保每个用户的状态隔离
        config = {"configurable": {"thread_id": f"user_{current_user.id}_session_{session_id}"}}
        print(f"[DEBUG] config: {config}")
        try:
            saved_state = graph.get_state(config)
            print(f"[DEBUG] saved_state: {saved_state}")
            print(f"[DEBUG] saved_state.values: {saved_state.values if saved_state else None}")

            if saved_state and saved_state.values:
                saved_messages = saved_state.values.get("messages", [])
                print(f"[DEBUG] saved_messages count: {len(saved_messages)}")
                for i, msg in enumerate(saved_messages):
                    print(f"  [DEBUG] saved_msg[{i}]: {type(msg).__name__}: {str(getattr(msg, 'content', ''))[:50]}...")
                saved_messages = saved_state.values.get("messages", [])

                # 只保留 HumanMessage 和 AIMessage，过滤掉 ToolMessage
                filtered_messages = []
                for msg in saved_messages:
                    if isinstance(msg, ToolMessage):
                        # 跳过 ToolMessage
                        continue
                    else:
                        filtered_messages.append(msg)

                # 只使用 checkpointer 中的 HumanMessage（这是上一轮处理后的结果）
                if filtered_messages:
                    historical_messages = filtered_messages
                    print(f"[DEBUG] 使用 checkpointer 历史消息: {len(historical_messages)} 条")
                elif db_context:
                    # 如果 checkpointer 为空，使用数据库中的 HumanMessage
                    historical_messages = db_context
                    print(f"[DEBUG] 使用 db_context 历史消息: {len(historical_messages)} 条")
                else:
                    historical_messages = []
                    print(f"[DEBUG] 无历史消息")

                # 构建 all_messages：历史 HumanMessage + 当前 HumanMessage
                all_messages = list(historical_messages) + [current_message]
                print(f"[DEBUG] all_messages 构建完成: {len(all_messages)} 条")
                for i, msg in enumerate(all_messages):
                    print(f"  [DEBUG] all_msg[{i}]: {type(msg).__name__}: {str(getattr(msg, 'content', ''))[:50]}...")

                # 优先使用数据库中的数据
                initial_resume_data = resume_data if resume_data else saved_state.values.get("resume_data", {})
                initial_jd_data = jd_data if jd_data else saved_state.values.get("jd_data", {})
            else:
                # checkpointer 为空，从数据库加载
                if db_context:
                    all_messages = list(db_context) + [current_message]
                else:
                    all_messages = [current_message]
                initial_resume_data = resume_data or {}
                initial_jd_data = jd_data or {}
        except Exception as e:
            # 异常情况下从数据库加载
            if db_context:
                all_messages = list(db_context) + [current_message]
            else:
                all_messages = [current_message]
            initial_resume_data = resume_data or {}
            initial_jd_data = jd_data or {}

        # 创建初始状态
        # 用户点击确认时：清除 pending_confirmation，从 formatter_llm 开始
        # 注意：当用户点击确认时，initial_state 包含完整的消息历史
        # 这样 tool_node 和 conversation_llm 才能正确访问上下文
        initial_state = {
            "messages": all_messages,  # 保留完整的历史消息
            "resume_data": initial_resume_data,
            "jd_data": initial_jd_data,
            "pending_confirmation": None,  # 用户点击确认时清除 pending_confirmation
            "user_id": current_user.id  # 添加用户ID，用于数据隔离
        }
        print(f"[InitState] initial_state 创建完成: {len(all_messages)} 条消息")
        for i, msg in enumerate(all_messages):
            print(f"  {i}: {type(msg).__name__}: {getattr(msg, 'content', '')[:30]}...")

        async def save_state_async(db, user_id, session_id, messages_list, resume_data_result, initial_jd_data, has_pending_confirmation, config):
            """异步保存状态到数据库，不阻塞 SSE 响应"""
            try:
                # 注意：不再使用 messages_list，因为它可能包含重复消息
                # 只依赖 checkpointer 来获取消息历史
                print(f"[SaveStateAsync] 开始保存状态")
                
                # 从 checkpointer 获取当前状态
                current_state = graph.get_state(config)
                existing_messages = []
                if current_state and current_state.values:
                    existing_messages = current_state.values.get("messages", [])
                    print(f"[SaveState] checkpointer 中已有: {len(existing_messages)} 条消息")
                    for i, msg in enumerate(existing_messages):
                        tc = getattr(msg, 'tool_calls', [])
                        tc_names = [t.get('name') if isinstance(t, dict) else getattr(t, 'name', None) for t in tc]
                        print(f"  [{i}] {type(msg).__name__}: tool_calls={tc_names}")
                
                # 从数据库获取已有的 HumanMessage（用于增量保存）
                from database import get_conversation_context
                db_context_raw = get_conversation_context(db, user_id, session_id)
                db_human_contents = set()
                for msg_dict in db_context_raw:
                    if msg_dict.get("type") == "human":
                        content = msg_dict.get("content", "")
                        if isinstance(content, list):
                            content = str(content)
                        db_human_contents.add(content)
                
                # 构建去重映射（使用内容+类型作为key）
                existing_map = {}
                for msg in existing_messages:
                    if isinstance(msg, ToolMessage):
                        continue  # 不保存 ToolMessage
                    content = getattr(msg, 'content', '')
                    if isinstance(content, list):
                        content = str(content)
                    key = (str(content), type(msg).__name__)
                    existing_map[key] = msg
                
                # 只添加不在已有历史中的新消息
                new_messages_added = []
                for msg in existing_messages:
                    if isinstance(msg, ToolMessage):
                        continue
                    content = getattr(msg, 'content', '')
                    if isinstance(content, list):
                        content = str(content)
                    key = (str(content), type(msg).__name__)
                    if key not in existing_map:
                        new_messages_added.append(msg)
                        existing_map[key] = msg
                        print(f"[SaveState] 添加新消息: {type(msg).__name__}: {str(content)[:50]}...")
                
                # 合并：历史消息 + 新消息（保持 Human -> AI 的顺序）
                all_human = [msg for msg in existing_messages if isinstance(msg, HumanMessage)]
                all_human.extend([msg for msg in new_messages_added if isinstance(msg, HumanMessage)])
                
                all_ai = [msg for msg in existing_messages if isinstance(msg, AIMessage)]
                all_ai.extend([msg for msg in new_messages_added if isinstance(msg, AIMessage)])
                
                # 保持正确的顺序：Human -> AI
                messages_to_save = all_human + all_ai
                
                # 提取最后一条 AIMessage 用于上下文压缩
                new_ai = all_ai[-1] if all_ai else None
                
                # 确定 final_resume_data 和 final_jd_data
                final_resume_data = resume_data_result if resume_data_result else {}
                final_jd_data = initial_jd_data if initial_jd_data else {}
                
                # 确定 pending_confirmation 状态
                if has_pending_confirmation:
                    current_pending = None
                    if current_state and current_state.values:
                        current_pending = current_state.values.get("pending_confirmation")
                else:
                    current_pending = None
                
                print(f"[SaveState] 保存 checkpointer: {len(messages_to_save)} total messages (Human: {len(all_human)}, AI: {len(all_ai)})")
                for i, msg in enumerate(messages_to_save):
                    print(f"  [{i}] {type(msg).__name__}: {str(getattr(msg, 'content', ''))[:50]}...")

                # 更新 checkpointer 之前，先获取当前状态
                before_update = graph.get_state(config)
                print(f"[SaveState] update 前 checkpointer: {len(before_update.values.get('messages', [])) if before_update and before_update.values else 0} messages")

                graph.update_state(
                    config,
                    {
                        "messages": messages_to_save,
                        "resume_data": final_resume_data,
                        "jd_data": final_jd_data,
                        "pending_confirmation": current_pending
                    }
                )

                # 更新后立即读取验证
                after_update = graph.get_state(config)
                print(f"[SaveState] update 后 checkpointer: {len(after_update.values.get('messages', [])) if after_update and after_update.values else 0} messages")
                for i, msg in enumerate(after_update.values.get('messages', []) if after_update and after_update.values else []):
                    print(f"  {i}: {type(msg).__name__}: {getattr(msg, 'content', '')[:30]}...")

                # 保存到数据库
                if final_resume_data:
                    save_user_resume(db, user_id, final_resume_data)
                if final_jd_data:
                    save_user_jd(db, user_id, final_jd_data)

                # 保存上下文（带压缩逻辑）
                from database import save_conversation_context

                # 1. 构建压缩上下文（只保存 HumanMessage + 最后一条 AIMessage）
                compressed_context = []
                for msg in all_human:
                    if hasattr(msg, 'model_dump'):
                        compressed_context.append({**msg.model_dump(), "type": "human"})
                    else:
                        compressed_context.append({**dict(msg), "type": "human"})
                if new_ai:
                    if hasattr(new_ai, 'model_dump'):
                        compressed_context.append({**new_ai.model_dump(), "type": "ai"})
                    else:
                        compressed_context.append({**dict(new_ai), "type": "ai"})

                # 2. 构建完整历史（用于前端显示，包含 HumanMessage + AIMessage）
                # 注意：只使用 messages_to_save（来自 checkpointer），避免 messages_list 的重复问题
                full_history = []
                for msg in messages_to_save:
                    if isinstance(msg, HumanMessage):
                        if hasattr(msg, 'model_dump'):
                            full_history.append({**msg.model_dump(), "type": "human"})
                        else:
                            full_history.append({**dict(msg), "type": "human"})
                    elif isinstance(msg, AIMessage) and msg.content:
                        if hasattr(msg, 'model_dump'):
                            full_history.append({**msg.model_dump(), "type": "ai"})
                        else:
                            full_history.append({**dict(msg), "type": "ai"})

                # 3. 检查是否需要压缩
                if len(all_human) > MAX_HUMAN_MESSAGES:
                    # 设置压缩状态
                    compression_state.compressing = True
                    print(f"[Context Compression] 开始压缩上下文 ({len(all_human)} 条 HumanMessage)")

                    try:
                        # 压缩前 N-K 条为摘要
                        to_compress = all_human[:-(KEEP_RECENT)]
                        recent = all_human[-(KEEP_RECENT):]  # 最近 K 条 HumanMessage
                        compressed = await compress_context_with_llm(to_compress)

                        # 将压缩结果转换为字典
                        new_compressed_context = []
                        for msg in compressed:
                            if hasattr(msg, 'model_dump'):
                                msg_dict = {**msg.model_dump(), "type": type(msg).__name__.lower()}
                            else:
                                msg_dict = {**dict(msg), "type": type(msg).__name__.lower()}
                            new_compressed_context.append(msg_dict)

                        # 添加最近 K 条 HumanMessage
                        for msg in recent:
                            if hasattr(msg, 'model_dump'):
                                new_compressed_context.append({**msg.model_dump(), "type": "human"})
                            else:
                                new_compressed_context.append({**dict(msg), "type": "human"})

                        # 添加最后一条 AIMessage
                        if new_ai:
                            if hasattr(new_ai, 'model_dump'):
                                new_compressed_context.append({**new_ai.model_dump(), "type": "ai"})
                            else:
                                new_compressed_context.append({**dict(new_ai), "type": "ai"})

                        # 替换 compressed_context 为压缩后的版本
                        compressed_context = new_compressed_context
                    finally:
                        # 通知压缩完成
                        notify_compression_complete()

                # 4. 保存到数据库（只保存 compressed_context，不保存 full_history 到 messages 字段）
                # full_history 由前端通过 /save_conversation 端点保存
                save_conversation_context(db, user_id, session_id, compressed_context)

            except Exception as e:
                print(f"[Warning] 异步保存失败: {e}")
                import traceback
                traceback.print_exc()

        async def stream_response(config):
            """流式生成响应"""
            import time
            total_start = time.time()

            # 累积所有消息，而不是每轮重置
            # 这样 save_state_async 才能获取完整的消息历史
            messages_list = list(all_messages)  # 从 initial_state 开始
            print(f"[StreamResponse] messages_list 初始化: {len(messages_list)} 条消息")
            resume_data_result = {}
            has_pending_confirmation = False
            final_content = None
            accumulated_content = ""
            current_node = None
            node_start_time = {}

            try:
                # 统一使用 graph.astream_events
                # 入口路由会在 Graph 内部处理（通过 entry_router）
                async for event in graph.astream_events(initial_state, config=config, version="v1"):
                    event_type = event.get("event", "")
                    node_name = event.get("name", "")

                    if event_type == "on_chain_start":
                        current_node = node_name
                        node_start_time[node_name] = time.time()

                    if event_type == "on_chat_model_stream" and current_node == "conversation_llm":
                        chunk = event.get("data", {}).get("chunk", {})
                        token = ""
                        if hasattr(chunk, "content"):
                            content = chunk.content
                            if isinstance(content, str):
                                token = content
                            elif hasattr(content, "text"):
                                text = content.text
                                if isinstance(text, str):
                                    token = text

                        if not token and hasattr(chunk, "text"):
                            text = chunk.text
                            if isinstance(text, str):
                                token = text

                        if token:
                            accumulated_content += token
                            yield f'data: {json.dumps({"type": "stream", "content": accumulated_content})}\n\n'

                    elif event_type == "on_chain_end":
                        if node_name in node_start_time:
                            del node_start_time[node_name]

                        # 跳过内部节点（__start__, entry_router），只处理实际的工作节点
                        if node_name in ["__start__", "entry_router"]:
                            continue

                        if node_name == "tool_node":
                            if isinstance(event.get("data", {}).get("output"), dict):
                                output = event["data"]["output"]
                                if "pending_confirmation" in output and output["pending_confirmation"]:
                                    has_pending_confirmation = True
                                    confirm_data = output["pending_confirmation"]
                                    confirm_msg_id = str(uuid.uuid4())
                                    yield 'data: ' + json.dumps({
                                        "type": "confirm",
                                        "id": confirm_msg_id,
                                        "content": confirm_data["content"],
                                        "options": confirm_data["options"],
                                        "confirm_id": confirm_data["confirm_id"],
                                        "session_id": session_id
                                    }) + '\n\n'
                                    if "messages" in output:
                                        messages_list.extend(output["messages"])
                                    continue

                        if isinstance(event.get("data", {}).get("output"), dict):
                            output = event["data"]["output"]
                            if "messages" in output:
                                messages_list.extend(output["messages"])
                            if "resume_data" in output and not output.get("pending_confirmation"):
                                resume_data_result = output["resume_data"]

                if not accumulated_content:
                    for msg in reversed(messages_list):
                        if isinstance(msg, AIMessage) and msg.content and msg.content != "简历已成功保存到数据库":
                            final_content = str(msg.content)
                            break
                        # 也检查 ToolMessage（如 save_resume_tool 的返回）
                        if isinstance(msg, ToolMessage) and msg.content:
                            final_content = str(msg.content)
                            break
                else:
                    final_content = accumulated_content

            except Exception as e:
                print(f"[Error] 执行错误: {str(e)}")
                final_content = f"抱歉，处理请求时出错: {str(e)}"

            if not final_content:
                final_content = "抱歉，我无法理解您的请求。"

            yield 'data: ' + json.dumps({
                "type": "final",
                "content": final_content,
                "session_id": session_id
            }) + '\n\n'

            # 将用户消息添加到 messages_list（用户消息在 initial_state 的最后）
            if initial_state.get("messages"):
                user_message = initial_state["messages"][-1]
                if isinstance(user_message, HumanMessage):
                    messages_list = [user_message] + messages_list

            # 保存消息到 checkpointer 和数据库（异步执行，不阻塞 SSE 响应）
            import asyncio
            asyncio.create_task(save_state_async(
                db, current_user.id, session_id,
                messages_list, resume_data_result, initial_jd_data, has_pending_confirmation, config
            ))

            yield 'data: ' + json.dumps({"type": "end", "session_id": session_id}) + '\n\n'

        return StreamingResponse(stream_response(config), media_type="text/event-stream")

    except Exception as e:
        print(f"聊天接口错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse(content=f"错误: {str(e)}", status_code=500)


@app.post("/confirm")
async def confirm_endpoint(
    confirm_id: str = Form(""),
    action: str = Form(""),  # "confirm" or "cancel"
    session_id: str = Form(""),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    确认按钮点击接口

    直接处理确认/取消操作，不经过 LLM
    """
    try:
        # 设置全局用户ID
        import resume_agent
        resume_agent.current_user_id = current_user.id

        # 获取当前状态，使用包含 user_id 的 config
        config = {"configurable": {"thread_id": f"user_{current_user.id}_session_{session_id}"}}
        saved_state = graph.get_state(config)

        if not saved_state or not saved_state.values:
            return JSONResponse(content={"error": "会话不存在"}, status_code=404)

        state = saved_state.values
        messages = state.get("messages", [])
        resume_data = state.get("resume_data", {})

        # 检查 pending_confirmation
        pending_confirmation = state.get("pending_confirmation", None)
        if not pending_confirmation:
            return JSONResponse(content={"error": "没有待确认的操作"}, status_code=400)

        if pending_confirmation.get("confirm_id") != confirm_id:
            return JSONResponse(content={"error": "确认ID不匹配"}, status_code=400)

        # 根据操作处理
        if action == "confirm":
            # 保存简历
            from tools import update_resume
            result = update_resume(resume_data, user_id=current_user.id)

            # 保存到数据库
            save_user_resume(db, current_user.id, resume_data)

            # 清除 pending_confirmation 状态
            graph.update_state(config, {
                "resume_data": resume_data,
                "jd_data": state.get("jd_data", {}),
                "pending_confirmation": None
            })

            return JSONResponse(content={
                "success": True,
                "message": result,
                "action": "saved"
            })

        else:
            # 取消 - 清除状态和临时消息
            # 过滤掉 pending 期间添加的临时 ToolMessage（ask_confirmation 相关的）
            cleaned_messages = []
            for msg in messages:
                if isinstance(msg, ToolMessage):
                    # 保留有 name 的 ToolMessage，过滤掉临时消息
                    if getattr(msg, 'name', None) and '等待确认' not in str(msg.content):
                        cleaned_messages.append(msg)
                else:
                    cleaned_messages.append(msg)

            graph.update_state(config, {
                "messages": cleaned_messages,
                "resume_data": resume_data,
                "jd_data": state.get("jd_data", {}),
                "pending_confirmation": None
            })

            return JSONResponse(content={
                "success": True,
                "message": "已取消保存操作",
                "action": "cancelled"
            })

    except Exception as e:
        print(f"确认接口错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"error": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    from database import cleanup_old_contexts, SessionLocal, get_user_by_email, create_user
    from auth import get_password_hash

    print("Resume Assistant MCP 服务启动中...")
    print("支持多用户认证和数据库持久化")

    # 启动时清理 7 天未访问的上下文
    try:
        db = SessionLocal()
        deleted = cleanup_old_contexts(db, days=7)
        if deleted:
            print(f"[Context] 已清理 {deleted} 条过期上下文")
        db.close()
    except Exception as e:
        print(f"[Context] 清理过期上下文失败: {e}")

    # 创建默认管理员账号
    try:
        db = SessionLocal()
        admin_email = "admin@qq.com"
        admin_password = "admin"
        existing_admin = get_user_by_email(db, admin_email)
        if existing_admin:
            print(f"[User] 管理员账号已存在: {admin_email}")
        else:
            hashed_pw = get_password_hash(admin_password)
            create_user(db, admin_email, hashed_pw, invite_code="admin")
            print(f"[User] 已创建默认管理员账号: {admin_email} (密码: {admin_password})")
        db.close()
    except Exception as e:
        print(f"[User] 创建管理员账号失败: {e}")

    uvicorn.run(app, host="0.0.0.0", port=8000)
