# DeepAgents 多用户上线改造计划

## 一、改造目标

将目前本地单用户运行的简历助手，改造为支持多用户、有用户认证、数据持久化的生产级应用。

### 技术选型

| 组件 | 方案 | 原因 |
|------|------|------|
| 数据库 | SQLite | 轻量、单文件、零运维，100-1000用户完全够用 |
| 认证 | JWT Token | 无状态、可扩展，无需 session 服务 |
| 注册 | 邀请码 | 前期无需 Redis 和邮件服务器，控制用户增长 |
| 并发 | FastAPI 异步 + workers | I/O 并发能力强，无需 Celery |
| 数据存储 | 混合模式 | 用户数据存 SQLite，简历/JD/对话存 JSON 文件 |

---

## 二、架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                       阿里云 ECS                                 │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Docker 容器 (单容器)                         │   │
│  │  ┌─────────────────────────────────────────────────┐   │   │
│  │  │               FastAPI (8000)                     │   │   │
│  │  │  ├── REST API (认证、简历、JD、对话)             │   │   │
│  │  │  └── SSE 流式响应 (聊天)                         │   │   │
│  │  └─────────────────────────────────────────────────┘   │   │
│  │                              │                            │
│  │  ┌─────────────────────────────────────────────────┐   │   │
│  │  │         data/ (数据目录，挂载到主机)             │   │   │
│  │  │  ├── deepagents.db          (SQLite: 用户/邀请码)│   │   │
│  │  │  └── users/{user_id}/       (JSON: 简历/JD/对话) │   │   │
│  │  └─────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 为什么不需要 Celery？

| 场景 | FastAPI 异步 | Celery |
|------|-------------|--------|
| 聊天对话 | SSE 流式，用户实时看到输出 | 不适合（用户体验差）|
| 并发能力 | asyncio 事件循环，I/O 并发强 | 过度设计 |
| 复杂度 | 单服务简单 | 增加运维复杂度 |

**结论**：FastAPI 异步架构 + `--workers 4` 多进程已能支撑 100-1000 用户。

---

## 三、数据存储设计

### 3.1 SQLite 数据库（用户系统）

```
data/
  deepagents.db
    └── users 表
        - id
        - email (唯一)
        - hashed_password
        - invite_code
        - created_at
        - is_active

    └── invite_codes 表
        - code (主键)
        - is_used
        - created_at
```

### 3.2 JSON 文件（用户数据）

```
data/
  users/
    user_1/
      resume.json        # 用户简历
      jd.json            # 用户保存的JD列表
      conversations/
        session_abc/
          messages.json  # 对话历史
```

---

## 四、数据库设计 (SQLite)

### 4.1 SQLAlchemy 模型

```python
# database.py

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/deepagents.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    invite_code = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)


class InviteCode(Base):
    __tablename__ = "invite_codes"
    code = Column(String(50), primary_key=True)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
```

---

## 五、认证系统

### 5.1 JWT 工具函数

```python
# auth.py

from datetime import datetime, timedelta
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24小时

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = data.copy()
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=401, detail="认证失败", headers={"WWW-Authenticate": "Bearer"}
    )
    payload = decode_token(token)
    if not payload:
        raise credentials_exception
    email = payload.get("sub")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise credentials_exception
    return user
```

### 5.2 认证接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/auth/register` | POST | 邮箱+密码+邀请码注册 |
| `/auth/login` | POST | 登录返回 JWT Token |
| `/auth/me` | GET | 获取当前用户信息 |
| `/auth/invite-codes` | POST | 生成邀请码（管理员） |

---

## 六、聊天上下文持久化

**不需要改造 LangGraph 核心代码**，在应用层拦截：

```python
# mcp_service_simple.py

# 调用 graph 前：从数据库加载历史
messages = load_conversation_history(user_id, session_id)

# 调用 graph 时：把历史传进去
result = graph.invoke({
    "messages": messages,
    "input": user_message
})

# 调用 graph 后：保存新消息到数据库
save_conversation_history(user_id, session_id, new_messages)
```

### 数据结构

```python
# conversations 表
{
    "id": 1,
    "user_id": "user_abc123",
    "session_id": "session_1",
    "role": "user",      # 或 "assistant"
    "content": "帮我优化简历",
    "created_at": "2026-01-11 10:00:00"
}
```

---

## 七、改造文件清单

### 7.1 新建文件

| 文件 | 说明 |
|------|------|
| `database.py` | SQLite 连接和 SQLAlchemy 模型 |
| `auth.py` | JWT 工具函数、密码加密 |
| `Dockerfile` | Docker 镜像构建 |
| `docker-compose.yml` | Docker 服务编排 |
| `frontend/src/views/Login.vue` | 登录页 |
| `frontend/src/views/Register.vue` | 注册页 |

### 7.2 改造文件

| 文件 | 改造内容 |
|------|----------|
| `mcp_service_simple.py` | 新增认证端点、用户关联逻辑、聊天历史持久化 |
| `frontend/src/App.vue` | 添加 token 状态、请求拦截器、认证守卫 |
| `.env` | 新增 JWT_SECRET_KEY、DATABASE_URL |

---

## 八、详细实现步骤

### Phase 1：创建数据库和认证模块

**新建 `database.py`：**
- SQLite 连接配置
- User、InviteCode 模型
- get_db 依赖函数
- init_db 初始化函数

**新建 `auth.py`：**
- 密码加密（bcrypt）
- JWT Token 创建/验证
- get_current_user 依赖

### Phase 2：改造后端 API

**改造 `mcp_service_simple.py`：**

1. 新增认证端点：
   - `POST /auth/register` - 注册（邮箱+密码+邀请码）
   - `POST /auth/login` - 登录
   - `GET /auth/me` - 获取用户信息

2. 改造现有端点：
   - `/chat` - 添加认证依赖，加载/保存对话历史
   - `/load_resume` - 从用户目录加载
   - `/save_resume` - 保存到用户目录

3. 新增对话历史接口：
   - `GET /conversations` - 获取用户对话列表
   - `GET /conversations/{session_id}` - 获取单条对话

### Phase 3：前端改造

**新建 `frontend/src/views/Login.vue`：**
- 登录表单（邮箱+密码）
- 调用登录 API
- 存储 token

**新建 `frontend/src/views/Register.vue`：**
- 注册表单（邮箱+密码+邀请码）
- 调用注册 API

**改造 `frontend/src/App.vue`：**
- 添加 token 状态管理
- 添加请求拦截器（Authorization Header）
- 未登录时跳转到登录页

### Phase 4：Docker 部署

**新建 `Dockerfile`：**
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN mkdir -p data/users

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "mcp_service_simple:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

**新建 `docker-compose.yml`：**
```yaml
version: '3.8'

services:
  backend:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    environment:
      - DATABASE_URL=sqlite:///./data/deepagents.db
      - JWT_SECRET_KEY=${JWT_SECRET_KEY}
    restart: unless-stopped
```

**新建 `requirements.txt`：**
```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
sqlalchemy>=2.0.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.6
pydantic>=2.5.0
python-dotenv>=1.0.0
# LangGraph 相关
langgraph>=0.0.20
langchain-openai>=0.1.0
# PDF 生成
weasyprint>=60.0
```

---

## 九、环境变量配置

```bash
# .env

# JWT 认证（必填）
JWT_SECRET_KEY=your-super-secret-key-change-this-in-production

# 数据库
DATABASE_URL=sqlite:///./data/deepagents.db

# LLM
LLM_API_KEY=sk-your-api-key
BASE_URL=https://api.bltcy.ai/v1

# TAVILY
TAVILY_API_KEY=tvly-your-api-key

# 服务器
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
```

---

## 十、启动命令

```bash
# 开发环境
uvicorn mcp_service_simple:app --host 0.0.0.0 --port 8000 --reload

# 生产环境（Docker）
docker-compose up -d --build

# 或直接运行（单服务器）
python -m uvicorn mcp_service_simple:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## 十一、目录结构

```
DeepAgents/
├── mcp_service_simple.py      # 主入口（改造）
├── resume_agent.py            # AI Agent（不改）
├── tools.py                   # 工具函数（不改）
├── pdf_generator.py           # PDF 生成（不改）
├── database.py                # 新建：数据库层
├── auth.py                    # 新建：认证模块
├── Dockerfile                 # 新建：Docker 构建
├── docker-compose.yml         # 新建：Docker 编排
├── requirements.txt           # 新建：依赖清单
├── .env                       # 新增：环境变量
│
├── data/                      # 数据目录（挂载）
│   ├── deepagents.db          # SQLite（自动创建）
│   └── users/
│       └── {user_id}/
│           ├── resume.json
│           ├── jd.json
│           └── conversations/
│               └── {session_id}.json
│
└── frontend/
    └── src/
        ├── App.vue            # 改造：认证逻辑
        ├── views/
        │   ├── Login.vue      # 新建
        │   └── Register.vue   # 新建
        └── router/
            └── index.js       # 新建：路由守卫
```

---

## 十二、工作量评估

| 阶段 | 工作量 | 说明 |
|------|--------|------|
| Phase 1 | 1天 | database.py, auth.py |
| Phase 2 | 1-2天 | mcp_service_simple.py 改造 |
| Phase 3 | 1-2天 | Login.vue, Register.vue, App.vue |
| Phase 4 | 0.5天 | Dockerfile, docker-compose.yml |
| **总计** | **4-6天** | - |

---

## 十三、关键问题解答

### Q: Redis 邮箱验证是否前期不需要？
A: 是的。邀请码机制不需要 Redis，SQLite 足够存储邀请码。

### Q: 为什么不用 Celery？
A: FastAPI 异步 + 多进程 workers 已能应对 100-1000 用户。Celery 适合"提交后等待"场景，但聊天需要实时 SSE 流式输出。

### Q: 之前的 MySQL + Redis + Celery 架构是否过度设计？
A: 是的。对于简历助手这种轻量级应用：
- MySQL 需要独立服务，运维复杂
- Redis 需要额外内存
- Celery 增加架构复杂度

### Q: LangGraph 代码需要改吗？
A: 不需要。只需在调用 graph 前后做数据持久化，LangGraph 核心代码保持不变。

---

## 十四、后续扩展（可选）

当用户量增长到 5000+ 时，可平滑升级：

| 升级项 | 从 | 到 |
|--------|-----|-----|
| 数据库 | SQLite | PostgreSQL |
| 任务队列 | 无 | Redis + Celery |
| 缓存 | 无 | Redis |
| 部署 | 单机 | 多实例 + 负载均衡 |
