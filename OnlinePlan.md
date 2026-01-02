# DeepAgents 多用户上线改造计划

## 一、改造目标

将目前本地单用户运行的简历助手，改造为支持多用户、有用户认证、数据持久化、支持异步任务的生产级应用。

### 技术选型确认

| 组件 | 方案 | 原因 |
|------|------|------|
| 数据库 | PostgreSQL | 生产环境推荐，支持高并发 |
| 消息队列 | Redis + Celery | 个人项目推荐，架构简单且可扩展 |
| 后端框架 | FastAPI | 高性能，异步原生支持 |
| 前端部署 | Nginx | 静态资源分离，性能更好 |
| 部署平台 | 阿里云 ECS | 单服务器部署 |

---

## 二、架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                         阿里云 ECS                               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                      Nginx (80, 443)                     │   │
│  │  ├── 前端静态资源 (/)                                    │   │
│  │  └── 反向代理 (/api/* → FastAPI:8000)                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   FastAPI (8000)                         │   │
│  │  ├── REST API (认证、简历、JD)                           │   │
│  │  ├── SSE 流式响应 (聊天)                                 │   │
│  │  └── Celery 任务提交                                     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   Celery Worker (8001)                   │   │
│  │  ├── 聊天任务 (LangGraph 执行)                           │   │
│  │  ├── PDF 导出任务                                        │   │
│  │  └── JD 解析任务                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Redis (6379)                                │   │
│  │  ├── Celery Broker (任务队列)                            │   │
│  │  ├── LangGraph Checkpoint (状态持久化)                   │   │
│  │  └── 会话缓存                                            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              PostgreSQL (5432)                           │   │
│  │  ├── users (用户表)                                      │   │
│  │  ├── resumes (简历表)                                    │   │
│  │  ├── job_descriptions (JD表)                             │   │
│  │  ├── conversations (会话表)                              │   │
│  │  └── async_tasks (任务表)                                │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、数据库设计 (PostgreSQL)

### 3.1 ER 图

```
┌─────────────┐       ┌─────────────────┐       ┌──────────────────┐
│    users    │──────▶│    resumes      │◀──────│ job_descriptions │
│─────────────│       │─────────────────│       │──────────────────│
│ id          │       │ id              │       │ id               │
│ username    │       │ user_id (FK)    │       │ resume_id (FK)   │
│ email       │       │ name            │       │ company          │
│ pwd_hash    │       │ resume_data     │       │ position         │
│ created_at  │       │ created_at      │       │ ...              │
└─────────────┘       └─────────────────┘       └──────────────────┘
        │                      │
        │                      │
        ▼                      ▼
┌─────────────────┐    ┌─────────────────┐
│  conversations  │    │   async_tasks   │
│─────────────────│    │─────────────────│
│ id              │    │ id              │
│ user_id (FK)    │    │ task_id         │
│ resume_id (FK)  │    │ user_id (FK)    │
│ thread_id       │    │ task_type       │
│ messages        │    │ status          │
└─────────────────┘    └─────────────────┘
```

### 3.2 数据库初始化脚本

```sql
-- 创建数据库
CREATE DATABASE deepagents;

-- 连接数据库后执行：

-- 用户表
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 简历表
CREATE TABLE resumes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) DEFAULT '默认简历',
    resume_data JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- JD表
CREATE TABLE job_descriptions (
    id SERIAL PRIMARY KEY,
    resume_id INTEGER NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    company VARCHAR(100),
    position VARCHAR(100),
    department VARCHAR(100),
    location VARCHAR(100),
    job_type VARCHAR(20),
    salary VARCHAR(50),
    description TEXT,
    requirements JSONB DEFAULT '{}',
    preferred_qualifications JSONB DEFAULT '[]',
    highlights JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 会话表
CREATE TABLE conversations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    resume_id INTEGER REFERENCES resumes(id) ON DELETE SET NULL,
    thread_id VARCHAR(36) UNIQUE NOT NULL,
    messages JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 异步任务表
CREATE TABLE async_tasks (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(36) UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    result JSONB,
    error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引优化
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_resumes_user_id ON resumes(user_id);
CREATE INDEX idx_conversations_thread_id ON conversations(thread_id);
CREATE INDEX idx_async_tasks_task_id ON async_tasks(task_id);
CREATE INDEX idx_async_tasks_user_id ON async_tasks(user_id);
```

---

## 四、改造文件清单

### 4.1 新建文件

```
backend/
├── __init__.py
├── config.py                    # 配置文件（环境变量）
├── main.py                      # FastAPI 主入口
├── requirements.txt             # Python 依赖
├── init_db.sql                  # 数据库初始化脚本
├── docker-compose.yml           # Docker 部署配置（可选）
│
├── models/
│   ├── __init__.py
│   └── database.py              # SQLAlchemy 模型
│
├── auth/
│   ├── __init__.py
│   └── jwt_auth.py              # JWT 认证逻辑
│
├── api/
│   ├── __init__.py
│   ├── deps.py                  # 依赖注入（get_db, get_current_user）
│   └── v1/
│       ├── __init__.py
│       ├── auth.py              # 认证接口（登录/注册）
│       ├── chat.py              # 聊天接口
│       ├── resumes.py           # 简历接口
│       └── jd.py                # JD接口
│
├── core/
│   ├── __init__.py
│   └── checkpoint.py            # Redis Checkpointer 配置
│
├── services/
│   ├── __init__.py
│   └── storage.py               # 数据库存储服务
│
└── tasks/
    ├── __init__.py
    ├── celery_app.py            # Celery 配置
    ├── chat_tasks.py            # 聊天异步任务
    └── export_tasks.py          # 导出异步任务

frontend/src/
├── api/
│   └── index.js                 # API 封装（新增）
├── stores/
│   └── auth.js                  # Pinia 认证状态（新增）
└── router/
    └── index.js                 # 路由守卫（新增）
```

### 4.2 改造文件

| 文件 | 改造内容 |
|------|----------|
| `resume_agent.py` | MemorySaver → RedisSaver |
| `tools.py` | read_file/write_file → 数据库操作 |
| `frontend/src/App.vue` | 添加登录/注册弹窗、认证守卫 |
| `frontend/src/main.js` | 注册 Pinia |
| `pdf_generator.py` | 改造为可导入的函数 |

---

## 五、详细实现步骤

### Phase 1: 环境准备

#### 1.1 安装依赖

```bash
# requirements.txt 新增

# Web 框架
fastapi>=0.104.0
uvicorn[standard]>=0.24.0

# 数据库
sqlalchemy>=2.0.0
psycopg2-binary>=2.9.0  # PostgreSQL 驱动
alembic>=1.12.0         # 数据库迁移工具

# 认证
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.6

# 异步任务
celery>=5.3.0
redis>=5.0.0

# LangGraph
langgraph>=0.0.20

# 配置
python-dotenv>=1.0.0
pydantic>=2.5.0
```

#### 1.2 环境变量配置

```bash
# .env

# 数据库
DATABASE_URL=postgresql://deepagents:your_password@localhost:5432/deepagents

# Redis
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# JWT
JWT_SECRET_KEY=your-super-secret-key-change-this-in-production
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=10080  # 7天

# LLM
LLM_API_KEY=sk-your-api-key
BASE_URL=https://api.bltcy.ai/v1

# TAVILY
TAVILY_API_KEY=tvly-your-api-key

# 服务器
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
```

### Phase 2: 数据库层

#### 2.1 SQLAlchemy 模型

```python
# backend/models/database.py

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from datetime import datetime
import os

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    resumes = relationship("Resume", back_populates="owner")
    conversations = relationship("Conversation", back_populates="user")
    async_tasks = relationship("AsyncTask", back_populates="user")


class Resume(Base):
    __tablename__ = "resumes"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), default="默认简历")
    resume_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="resumes")
    jds = relationship("JobDescription", back_populates="resume")
    conversations = relationship("Conversation", back_populates="resume")


class JobDescription(Base):
    __tablename__ = "job_descriptions"
    id = Column(Integer, primary_key=True, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"), nullable=False)
    company = Column(String(100))
    position = Column(String(100))
    department = Column(String(100))
    location = Column(String(100))
    job_type = Column(String(20))
    salary = Column(String(50))
    description = Column(Text)
    requirements = Column(JSON)
    preferred_qualifications = Column(JSON)
    highlights = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    resume = relationship("Resume", back_populates="jds")


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    resume_id = Column(Integer, ForeignKey("resumes.id"), nullable=True)
    thread_id = Column(String(36), unique=True, index=True)
    messages = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="conversations")
    resume = relationship("Resume", back_populates="conversations")


class AsyncTask(Base):
    __tablename__ = "async_tasks"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(36), unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    task_type = Column(String(50))
    status = Column(String(20), default="pending")
    result = Column(JSON)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="async_tasks")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
```

### Phase 3: 认证系统

#### 3.1 JWT 认证

```python
# backend/auth/jwt_auth.py

from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from models.database import User, get_db

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 10080))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": data["sub"], "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(status_code=401, detail="认证失败", headers={"WWW-Authenticate": "Bearer"})
    payload = decode_token(token)
    if not payload: raise credentials_exception
    username = payload.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user: raise credentials_exception
    return user
```

#### 3.2 认证接口

```python
# backend/api/v1/auth.py

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
from auth.jwt_auth import verify_password, get_password_hash, create_access_token, get_current_user
from models.database import User, get_db

router = APIRouter(prefix="/auth", tags=["认证"])


class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict


class UserCreate(BaseModel):
    username: str
    email: str
    password: str


@router.post("/register", response_model=Token)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(status_code=400, detail="邮箱已注册")

    user = User(username=user_data.username, email=user_data.email,
                hashed_password=get_password_hash(user_data.password))
    db.add(user); db.commit(); db.refresh(user)
    token = create_access_token({"sub": user.username})
    return Token(access_token=token, token_type="bearer",
                 user={"id": user.id, "username": user.username, "email": user.email})


@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token({"sub": user.username})
    return Token(access_token=token, token_type="bearer",
                 user={"id": user.id, "username": user.username, "email": user.email})


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "username": current_user.username, "email": current_user.email}
```

### Phase 4: Redis Checkpointer

```python
# backend/core/checkpoint.py

import os, redis
from langgraph.checkpoint.redis import RedisSaver
from langgraph.checkpoint.memory import MemorySaver

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def get_redis_client():
    return redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)


def get_checkpointer():
    """生产环境用 RedisSaver，开发环境用 MemorySaver"""
    if os.getenv("USE_REDIS_CHECKPOINTER", "true").lower() == "true":
        return RedisSaver(get_redis_client())
    return MemorySaver()
```

### Phase 5: Celery 异步任务

```python
# backend/tasks/celery_app.py

from celery import Celery
import os

REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")

celery_app = Celery("deepagents", broker=REDIS_URL, backend=REDIS_URL,
                    include=["tasks.chat_tasks", "tasks.export_tasks"])

celery_app.conf.update(
    task_serializer="json", accept_content=["json"], result_serializer="json",
    timezone="Asia/Shanghai", enable_utc=True, task_track_started=True,
    task_time_limit=600, worker_prefetch_multiplier=1, worker_concurrency=4,
)
```

```python
# backend/tasks/chat_tasks.py

from celery import shared_task
from sqlalchemy.orm import Session
import uuid
from datetime import datetime
from langchain_core.messages import HumanMessage

from core.checkpoint import get_checkpointer
from models.database import get_db, Conversation, AsyncTask
from resume_agent import graph


@shared_task(bind=True, max_retries=3)
def process_chat_task(self, user_id: int, message: str, thread_id: str = None):
    db = next(get_db())
    task_id = self.request.id

    # 更新任务状态
    task = db.query(AsyncTask).filter(AsyncTask.task_id == task_id).first()
    if task:
        task.status = "processing"; db.commit()

    thread_id = thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = {"messages": [HumanMessage(content=message)], "resume_data": {}, "jd_data": {}}

    for chunk in graph.astream(initial_state, config=config):
        pass  # 处理流式输出

    # 保存会话
    conversation = db.query(Conversation).filter(Conversation.thread_id == thread_id).first()
    if conversation:
        saved_state = graph.get_state(config)
        if saved_state and saved_state.values:
            conversation.messages = saved_state.values.get("messages", [])
    else:
        conversation = Conversation(user_id=user_id, thread_id=thread_id, messages=[{"role": "user", "content": message}])
        db.add(conversation)
    db.commit()

    if task:
        task.status = "completed"; task.result = {"thread_id": thread_id}; db.commit()
    return {"thread_id": thread_id, "status": "completed"}
```

### Phase 6: 前端改造

#### 6.1 API 封装

```javascript
// frontend/src/api/index.js

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'

const authRequest = async (url, options = {}) => {
  const token = localStorage.getItem('authToken')
  const headers = { 'Content-Type': 'application/json', ...options.headers }
  if (token) headers['Authorization'] = `Bearer ${token}`
  return fetch(`${API_BASE}${url}`, { ...options, headers })
}

export const authAPI = {
  async login(username, password) {
    const formData = new URLSearchParams()
    formData.append('username', username)
    formData.append('password', password)
    const res = await fetch(`${API_BASE}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: formData })
    if (!res.ok) throw new Error('登录失败')
    return res.json()
  },
  async register(username, email, password) {
    const res = await authRequest('/auth/register', { method: 'POST', body: JSON.stringify({ username, email, password }) })
    if (!res.ok) throw new Error('注册失败')
    return res.json()
  },
  logout() {
    localStorage.removeItem('authToken')
    localStorage.removeItem('user')
  },
}

export const resumeAPI = {
  async get() { return authRequest('/resumes/') },
  async save(data) {
    return authRequest('/resumes/', { method: 'POST', body: JSON.stringify({ resume_data: data }) })
  },
}

export const jdAPI = {
  async get() { return authRequest('/jd/') },
  async save(data) {
    return authRequest('/jd/', { method: 'POST', body: JSON.stringify({ jd_data: data }) })
  },
}

export const chatAPI = {
  async send(message, files = [], threadId = null) {
    const formData = new FormData()
    formData.append('message', message)
    if (threadId) formData.append('thread_id', threadId)
    files.forEach(f => formData.append('files', f))
    const token = localStorage.getItem('authToken')
    const res = await fetch(`${API_BASE}/chat/`, { method: 'POST', headers: { 'Authorization': `Bearer ${token}` }, body: formData })
    if (!res.ok) throw new Error('发送失败')
    return res.json()
  },
  async getResult(taskId) {
    return authRequest(`/chat/task/${taskId}`)
  },
}
```

#### 6.2 Pinia 认证状态

```javascript
// frontend/src/stores/auth.js

import { defineStore } from 'pinia'
import { authAPI } from '@/api'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('authToken') || null,
    user: JSON.parse(localStorage.getItem('user') || 'null'),
  }),
  getters: {
    isAuthenticated: (state) => !!state.token,
    currentUser: (state) => state.user,
  },
  actions: {
    async login(username, password) {
      const result = await authAPI.login(username, password)
      this.token = result.access_token
      this.user = result.user
      localStorage.setItem('authToken', result.access_token)
      localStorage.setItem('user', JSON.stringify(result.user))
    },
    async register(username, email, password) {
      const result = await authAPI.register(username, email, password)
      this.token = result.access_token
      this.user = result.user
      localStorage.setItem('authToken', result.access_token)
      localStorage.setItem('user', JSON.stringify(result.user))
    },
    logout() {
      this.token = null
      this.user = null
      localStorage.removeItem('authToken')
      localStorage.removeItem('user')
    },
  },
})
```

### Phase 7: 部署配置

#### 7.1 Nginx 配置

```nginx
# /etc/nginx/sites-available/deepagents

server {
    listen 80;
    server_name your-domain.com;

    location / {
        root /var/www/deepagents/dist;
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```

#### 7.2 Systemd 服务

```ini
# /etc/systemd/system/deepagents.service
[Unit]
Description=DeepAgents Backend
After=network.target redis-postgresql.target

[Service]
User=www-data
WorkingDirectory=/opt/deepagents
Environment="PATH=/opt/deepagents/venv/bin"
ExecStart=/opt/deepagents/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/deepagents-worker.service
[Unit]
Description=DeepAgents Celery Worker
After=network.target redis-postgresql.target

[Service]
User=www-data
WorkingDirectory=/opt/deepagents
Environment="PATH=/opt/deepagents/venv/bin"
ExecStart=/opt/deepagents/venv/bin/celery -A tasks.celery_app worker --loglevel=info
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## 六、为什么需要 Celery？

| 场景 | 无 Celery | 有 Celery |
|------|-----------|-----------|
| LLM 耗时 | HTTP 超时风险 | 任务队列，用户无感知 |
| 高峰期 | 服务器阻塞 | 任务排队，自动削峰 |
| 失败处理 | 用户需重试 | 自动重试，状态追踪 |
| 用户体验 | 一直等待 | 可关闭页面，后台完成 |

---

## 七、执行顺序清单

| 阶段 | 任务 |
|------|------|
| **Phase 1** | 安装 PostgreSQL、Redis，创建数据库和表，创建虚拟环境安装依赖 |
| **Phase 2** | 创建 backend 目录结构，实现 database.py 模型、jwt_auth.py 认证、auth.py 接口 |
| **Phase 3** | 实现 checkpoint.py、storage.py 服务、celery_app.py、chat_tasks.py |
| **Phase 4** | 改造 resume_agent.py (RedisSaver)、tools.py (数据库操作)、main.py 主入口 |
| **Phase 5** | 实现前端 API 封装、Pinia 认证状态、改造 App.vue 添加登录 |
| **Phase 6** | 配置 Nginx、Systemd 服务、测试部署 |

---

## 八、启动命令

```bash
# 启动 Redis
redis-server

# 启动 PostgreSQL (Docker)
docker run --name postgres -e POSTGRES_PASSWORD=password -p 5432:5432 -d postgres

# 启动后端
uvicorn main:app --host 0.0.0.0 --port 8000

# 启动 Celery Worker
celery -A tasks.celery_app worker --loglevel=info
```

---

## 九、关键风险点

1. **LLM API 成本**：建议设置每日调用限额
2. **Redis 内存**：定期清理过期 checkpoint
3. **PostgreSQL 连接池**：配置合理的 pool_size
4. **Celery Worker 数量**：根据 ECS 配置调整
5. **JWT Secret**：生产环境必须使用强密码
