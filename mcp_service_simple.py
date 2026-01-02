"""
简历助手 MCP 服务

提供 HTTP API 接口，连接前端和 AI 代理。

核心职责：
1. HTTP 请求处理和响应
2. SSE 流式输出
3. 状态同步（LangGraph checkpointer <-> 前端缓存）
4. PDF 导出
"""

import json
import asyncio
import base64
import platform
import subprocess
import os
import sys
import uuid
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入 resume_agent 中的 graph 和 conversation_llm
from resume_agent import graph, conversation_llm
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

# PDF 生成器 - 懒加载（在 API 调用时才导入）
_pdf_generator = None


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


# 简历数据缓存 - 用于前端预览（与 LangGraph checkpointer 同步）
resume_data_cache = {}

# JD数据缓存 - 用于前端预览（与 LangGraph checkpointer 同步）
jd_data_cache = {}


def generate_session_id() -> str:
    """生成唯一会话 ID"""
    return str(uuid.uuid4())


# =============================================================================
# LLM 上下文压缩
# =============================================================================

async def compress_context_with_llm(messages, max_summary_length=150):
    """
    使用 LLM 对早期对话进行语义压缩

    Args:
        messages: 对话消息列表
        max_summary_length: 摘要最大长度（汉字数）

    Returns:
        压缩后的消息列表
    """
    if len(messages) <= 5:
        return messages

    # 分离早期消息和最近消息
    early_messages = messages[:-5]
    recent_messages = messages[-5:]

    # 构建摘要提示
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
        print(f"✅ LLM 摘要生成成功: {len(summary_content)}字")

        summary_message = SystemMessage(content=summary_content)
        return [summary_message] + recent_messages

    except Exception as e:
        print(f"❌ LLM 摘要生成失败: {e}")
        return list(messages[-10:])


# =============================================================================
# FastAPI 应用
# =============================================================================

app = FastAPI(title="Resume Assistant MCP Service", version="2.0.0")

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# API 端点
# =============================================================================

@app.post("/health")
async def health_check(request: Request):
    """健康检查"""
    return {"status": "ok", "version": "2.0.0"}


@app.post("/load_resume")
async def load_resume_endpoint(request: Request):
    """加载简历数据"""
    try:
        from tools import load_resume
        result = load_resume()
        if isinstance(result, dict):
            return JSONResponse(content=result)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(content=f"错误: {str(e)}", status_code=500)


@app.post("/load_jd")
async def load_jd_endpoint(request: Request):
    """加载JD数据"""
    try:
        try:
            with open('jd.json', 'r', encoding='utf-8') as f:
                jd_data = json.load(f)
            return JSONResponse(content=jd_data)
        except FileNotFoundError:
            return JSONResponse(content={})
    except Exception as e:
        return JSONResponse(content=f"错误: {str(e)}", status_code=500)


@app.post("/parse_jd")
async def parse_jd_endpoint(request: Request):
    """
    解析JD文本/图片为结构化JSON
    - 输入：text 或 image(base64)
    - 输出：结构化 JD JSON
    - 无多轮对话，直接返回结果
    """
    try:
        import re
        request_data = await request.json()
        jd_text = request_data.get('text', '')
        jd_image = request_data.get('image', '')

        # 调用 resume_agent.py 中的 jd_parser_llm 解析
        from resume_agent import jd_parser_llm, JD_PARSER_PROMPT

        # 构建消息
        if jd_image:
            # 移除 base64 前缀（如果有）
            if jd_image.startswith('data:image'):
                jd_image = jd_image.split(',')[1]

            # 使用正确的 image_url 格式传递图片
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

        # 调用 LLM 解析
        response = await jd_parser_llm.ainvoke([
            SystemMessage(content=JD_PARSER_PROMPT),
            message
        ])

        # 解析 JSON
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


@app.post("/save_jd")
async def save_jd_endpoint(request: Request):
    """
    保存JD数据
    - 写入 jd.json 文件
    - 更新 checkpointer 中的 jd_data
    - 更新 jd_data_cache
    """
    try:
        request_data = await request.json()
        jd_data = request_data.get('jd_data', {})
        session_id = request_data.get('session_id', '')

        # 1. 保存到文件
        with open('jd.json', 'w', encoding='utf-8') as f:
            json.dump(jd_data, f, ensure_ascii=False, indent=2)

        # 2. 更新 checkpointer（如果session存在）
        from resume_agent import graph
        if session_id:
            config = {"configurable": {"thread_id": session_id}}
            try:
                # 获取当前状态，只更新 jd_data
                saved_state = graph.get_state(config)
                current_jd = saved_state.values.get("jd_data", {}) if saved_state else {}

                graph.update_state(
                    config,
                    {"jd_data": {**current_jd, **jd_data}}
                )
                print(f"已更新 checkpointer 中的 jd_data")
            except Exception as e:
                print(f"更新 checkpointer 失败: {e}")

        # 3. 更新缓存
        jd_data_cache[session_id] = jd_data

        return JSONResponse(content={"success": True})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/export_pdf")
async def export_pdf_endpoint(request: Request):
    """导出 PDF"""
    try:
        request_data = await request.json()
        resume_data = request_data.get('resume', request_data.get('resume_data', request_data))
        style = request_data.get('style', {})

        if not resume_data:
            return JSONResponse(content="错误: 没有收到简历数据", status_code=400)

        generate_pdf = get_pdf_generator()
        pdf_bytes = generate_pdf(resume_data, style)

        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=resume.pdf"}
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
    session_id: str = Form("")
):
    """
    聊天接口

    核心逻辑：
    1. 接收用户消息
    2. 从 LangGraph checkpointer 恢复状态
    3. 调用 graph 处理
    4. 流式返回结果
    5. 同步状态到缓存
    """
    try:
        # 生成会话 ID
        if not session_id:
            session_id = generate_session_id()

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

        # 获取简历数据缓存
        cached_resume_data = resume_data_cache.get(session_id, None)
        cached_jd_data = jd_data_cache.get(session_id, None)

        # 创建用户消息
        current_message = HumanMessage(content=message.strip())

        # 从 checkpointer 获取历史消息
        try:
            config = {"configurable": {"thread_id": session_id}}
            saved_state = graph.get_state(config)

            if saved_state and saved_state.values:
                # 恢复历史消息
                historical_messages = saved_state.values.get("messages", [])
                # 添加新消息
                all_messages = list(historical_messages) + [current_message]
                initial_resume_data = saved_state.values.get("resume_data", cached_resume_data)
                initial_jd_data = saved_state.values.get("jd_data", cached_jd_data)
            else:
                all_messages = [current_message]
                initial_resume_data = cached_resume_data
                initial_jd_data = cached_jd_data
        except Exception:
            all_messages = [current_message]
            initial_resume_data = cached_resume_data
            initial_jd_data = cached_jd_data

        # 上下文压缩
        MAX_MESSAGES = 15
        if len(all_messages) > MAX_MESSAGES:
            print(f"🔄 对话历史过长（{len(all_messages)}条），正在压缩...")
            # 只压缩 HumanMessage 和 AIMessage
            compressible_messages = [
                msg for msg in all_messages
                if isinstance(msg, (HumanMessage, AIMessage))
            ]
            if len(compressible_messages) > MAX_MESSAGES:
                compressed = await compress_context_with_llm(compressible_messages)
                # 重新构建消息列表
                tool_messages = [msg for msg in all_messages if isinstance(msg, ToolMessage)]
                all_messages = compressed + tool_messages
            print(f"✅ 压缩完成，当前 {len(all_messages)} 条消息")

        # 创建初始状态
        initial_state = {
            "messages": all_messages,
            "resume_data": initial_resume_data,
            "jd_data": initial_jd_data
        }

        async def stream_response():
            """流式生成响应 - 使用 astream_events 实现 LLM 级别流式输出"""
            import time
            total_start = time.time()

            messages_list = []
            resume_data = {}
            final_content = None
            accumulated_content = ""
            current_node = None
            node_start_time = {}  # 记录每个节点开始时间

            try:
                # 使用 astream_events 实现 LLM 级别的流式输出
                async for event in graph.astream_events(initial_state, config=config, version="v1"):
                    event_type = event.get("event", "")
                    node_name = event.get("name", "")

                    # 节点开始执行
                    if event_type == "on_chain_start":
                        current_node = node_name
                        node_start_time[node_name] = time.time()
                        # 工具调用
                        if node_name.startswith("tool_node") or node_name in ["read_file", "write_file"]:
                            print(f"🔧 工具调用: {node_name}")
                        elif node_name == "conversation_llm":
                            print(f"🤖 开始生成回复...")
                        elif node_name == "formatter_llm":
                            print(f"📝 开始格式化简历...")

                    # 🔒 只流式输出 conversation_llm 的 LLM 内容
                    if event_type == "on_chat_model_stream" and current_node == "conversation_llm":
                        chunk = event.get("data", {}).get("chunk", {})

                        # 提取 token
                        token = ""
                        if hasattr(chunk, "content"):
                            content = chunk.content
                            if isinstance(content, str):
                                token = content
                            elif callable(content) and hasattr(chunk, "text"):
                                text = chunk.text
                                if isinstance(text, str):
                                    token = text
                            elif isinstance(content, list) and len(content) > 0:
                                for item in content:
                                    if isinstance(item, str):
                                        token += item
                                    elif hasattr(item, "text"):
                                        text = item.text
                                        if isinstance(text, str):
                                            token += text
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

                    # 节点执行完成
                    elif event_type == "on_chain_end":
                        if node_name in node_start_time:
                            elapsed = time.time() - node_start_time[node_name]
                            if elapsed > 0.1:  # 只显示耗时超过 0.1s 的节点
                                print(f"✅ {node_name} 完成 ({elapsed:.2f}s)")
                            del node_start_time[node_name]

                        if isinstance(event.get("data", {}).get("output"), dict):
                            output = event["data"]["output"]
                            if "messages" in output:
                                messages_list.extend(output["messages"])
                            if "resume_data" in output:
                                resume_data = output["resume_data"]
                                resume_data_cache[session_id] = resume_data
                            if "jd_data" in output:
                                jd_data = output["jd_data"]
                                jd_data_cache[session_id] = jd_data

                # 提取最终内容
                if not accumulated_content:
                    for msg in reversed(messages_list):
                        if isinstance(msg, AIMessage) and msg.content and msg.content != "简历已成功保存到 resume.json":
                            final_content = str(msg.content)
                            break
                else:
                    final_content = accumulated_content

            except Exception as e:
                print(f"❌ 执行错误: {str(e)}")
                final_content = f"抱歉，处理请求时出错: {str(e)}"

            # 发送最终响应
            if not final_content:
                final_content = "抱歉，我无法理解您的请求。"

            yield 'data: ' + json.dumps({
                "type": "final",
                "content": final_content,
                "session_id": session_id
            }) + '\n\n'

            # 清理并保存消息（只保留 HumanMessage 和最后一个 AIMessage）
            cleaned = []
            last_ai = None
            for msg in messages_list:
                if isinstance(msg, HumanMessage):
                    cleaned.append(msg)
                elif isinstance(msg, AIMessage) and msg.content:
                    last_ai = msg
            if last_ai:
                cleaned.append(last_ai)

            # 手动更新 checkpointer
            try:
                # 获取最新的 resume_data 和 jd_data（从缓存或当前状态）
                final_resume_data = resume_data if 'resume_data' in dir() and resume_data else resume_data_cache.get(session_id, {})
                final_jd_data = jd_data if 'jd_data' in dir() and jd_data else jd_data_cache.get(session_id, {})

                graph.update_state(
                    config,
                    {
                        "messages": cleaned,
                        "resume_data": final_resume_data,
                        "jd_data": final_jd_data
                    }
                )
            except Exception as e:
                print(f"⚠️ 更新 checkpointer 失败: {e}")

            yield 'data: ' + json.dumps({"type": "end", "session_id": session_id}) + '\n\n'

        return StreamingResponse(stream_response(), media_type="text/event-stream")

    except Exception as e:
        print(f"聊天接口错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse(content=f"错误: {str(e)}", status_code=500)


@app.post("/save_resume")
async def save_resume_endpoint(request: Request):
    """保存简历数据"""
    try:
        request_data = await request.json()
        resume_data = request_data.get('resume_data', {})

        # 写入 resume.json
        with open('resume.json', 'w', encoding='utf-8') as f:
            json.dump(resume_data, f, ensure_ascii=False, indent=2)

        return JSONResponse(content={"success": True})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"error": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    print("🚀 Resume Assistant MCP 服务启动中...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
