# DeepAgents Dockerfile
# 多用户版 - 简历助手

FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖（WeasyPrint 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libharfbuzz0a \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p data && touch data/deepagents.db

# 暴露端口
EXPOSE 8000

# 使用 Gunicorn（生产环境推荐）
CMD ["gunicorn", "mcp_service_simple:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-"]
