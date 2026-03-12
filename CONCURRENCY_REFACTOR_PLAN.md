# DeepAgents 并发与部署改造计划（可落地版）

## 1. 当前现状（基于你仓库）
1. 服务框架是 FastAPI，入口在 [`/Users/weihaohuang/Desktop/DeepAgents/mcp_service_simple.py`](/Users/weihaohuang/Desktop/DeepAgents/mcp_service_simple.py)。
2. 生产启动是 `gunicorn + uvicorn worker + 6 workers`，见 [`/Users/weihaohuang/Desktop/DeepAgents/Dockerfile:41`](/Users/weihaohuang/Desktop/DeepAgents/Dockerfile:41)。
3. 数据库是 SQLite，见 [`/Users/weihaohuang/Desktop/DeepAgents/database.py:13-16`](/Users/weihaohuang/Desktop/DeepAgents/database.py:13-16) 和 [`.env`](/Users/weihaohuang/Desktop/DeepAgents/.env)。
4. `export_pdf` 中有同步 CPU/IO 重任务，见 [`/Users/weihaohuang/Desktop/DeepAgents/mcp_service_simple.py:1041-1042`](/Users/weihaohuang/Desktop/DeepAgents/mcp_service_simple.py:1041-1042)。
5. `chat` 是 SSE 流式接口，见 [`/Users/weihaohuang/Desktop/DeepAgents/mcp_service_simple.py:1056-1456`](/Users/weihaohuang/Desktop/DeepAgents/mcp_service_simple.py:1056-1456)。

---

## 2. 目标与验收标准

1. 2C4G ECS 下先稳定运行，不再频繁 OOM。
2. 在 5-10 并发请求时，接口可用性明显提升。
3. 迁移 PostgreSQL 后，写入阻塞和锁冲突下降。
4. 重任务（PDF）不再拖慢在线聊天。
5. 部署流程从手工变成可重复、可回滚。

### 验收指标（建议）
1. 容器内存长期 `< 75%`，峰值 `< 90%`。
2. `/chat` P95 响应首包时间 `< 3s`（不含模型本身慢请求）。
3. `/export_pdf` 不影响同时在线聊天请求。
4. 无 OOM 重启（7 天）。

---

## 3. 分阶段改造路线

## Phase A（当天可做，先止血）

### A1. 调整 Gunicorn worker 数量（核心）
1. 将 worker 从 `6` 降到 `2`（最多 `3`）。
2. 保持 `uvicorn.workers.UvicornWorker` 不变。
3. 先不要引入 `gthread`，你当前模型下主瓶颈不在这里。

建议命令：
```bash
gunicorn mcp_service_simple:app \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --timeout 120 \
  --graceful-timeout 30 \
  --keep-alive 5 \
  --max-requests 800 \
  --max-requests-jitter 100 \
  --access-logfile - \
  --error-logfile -
```

### A2. 把启动参数从 Dockerfile 中抽到配置文件
1. 新增 `gunicorn.conf.py`，参数可调、可复用。
2. Dockerfile 只保留 `CMD ["gunicorn", "-c", "gunicorn.conf.py", "mcp_service_simple:app"]`。
3. 后续调优不需要改镜像构建层。

### A3. 容器资源保护
1. `docker-compose` 给 `backend` 设置内存上限和重启策略。
2. 使用 `docker stats` 观察 24 小时，再迭代 worker 数。

---

## Phase B（1-3 天，降低阻塞）

### B1. PDF 导出改线程池执行（最先改）
1. `generate_pdf(...)` 是同步重任务，放入线程池。
2. 在 `export_pdf` 中使用 `from starlette.concurrency import run_in_threadpool`。
3. 改造后即使 PDF 慢，也不直接卡住事件循环。

示例：
```python
from starlette.concurrency import run_in_threadpool

pdf_bytes = await run_in_threadpool(
    generate_pdf, resume_data, style, photo, lang
)
```

### B2. 明确在线请求 vs 离线任务边界
1. `chat` 保持在线 SSE，不进任务队列（否则失去实时流式体验）。
2. `export_pdf` 提供两种模式：同步下载（保留）+ 异步任务（新增）。

### B3. 补充可观测性
1. 增加请求耗时日志、状态码统计、OOM 前内存快照日志。
2. 重点追踪 `/chat`、`/export_pdf`、数据库写入慢点。

---

## Phase C（3-7 天，SQLite -> PostgreSQL）

## C1. 基础设施选择
1. 推荐阿里云 RDS PostgreSQL，不占 ECS 内存。
2. 网络同 VPC，避免公网数据库连接延迟和风险。

## C2. 代码准备
1. 安装 PG 驱动（`psycopg` 或 `psycopg2-binary`）。
2. 将 `DATABASE_URL` 改为 PostgreSQL DSN。
3. `database.py` 按数据库类型设置 engine 参数。

建议 DSN：
```env
DATABASE_URL=postgresql+psycopg://user:password@host:5432/deepagents
```

## C3. 迁移步骤（零惊喜版本）
1. 冻结写入窗口（公告 5-15 分钟）。
2. 备份 SQLite 文件：`data/deepagents.db`。
3. 使用 `pgloader` 从 SQLite 导入 PostgreSQL。
4. 校验表数量、记录数、关键用户数据。
5. 切换 `.env` 并重启服务。
6. 观察 24 小时，确认后结束冻结策略。

示例迁移命令：
```bash
pgloader sqlite:///app/data/deepagents.db postgresql://user:pass@host:5432/deepagents
```

## C4. 迁移后必须做
1. 引入 Alembic，后续 schema 变更可追踪。
2. 增加索引（按高频查询字段：`user_id`、`session_id`、`created_at`）。
3. 慢查询日志开启并审计。

---

## Phase D（1-2 周，任务系统与服务拆分）

## D1. 引入任务队列（Redis + Celery/RQ）
1. 用于 PDF 生成、批量导出、通知等“可异步”任务。
2. API 服务只负责提交任务与查询状态。
3. Worker 独立进程运行，避免与 API 抢资源。

## D2. API 设计建议
1. `POST /export_pdf_async`：返回 `task_id`。
2. `GET /tasks/{task_id}`：返回 `PENDING/RUNNING/SUCCESS/FAILED`。
3. `GET /tasks/{task_id}/download`：成功后下载文件。

## D3. 是否需要单独实例
1. 初期可同一 ECS 上分容器运行 API + worker（成本最低）。
2. 并发上来后，把 worker 单独放一台机器。
3. 你的 2C4G 机器上，DB 外置到 RDS优先级高于“加更多 worker”。

---

## 4. 部署方式建议（按理解成本）

## 推荐路径：ECS + Docker Compose + RDS（短期）
1. 学习成本最低，和你现在最接近。
2. 先完成稳定性改造，再考虑平台迁移。

## 下一步：阿里云 SAE（中期）
1. 镜像部署友好，省去很多机器运维细节。
2. 自动弹性比手工 ECS 更省心。
3. 适合你这种容器化 FastAPI 服务。

## 不优先：函数计算/CF（当前阶段）
1. 你有 SSE、长连接、重依赖（WeasyPrint 等）和状态复杂度。
2. 函数平台可以做，但改造心智成本并不一定更低。
3. 等业务稳定后再评估“部分异步任务函数化”更合适。

---

## 5. 风险与回滚

1. 风险：降 worker 后吞吐下降。  
   处理：先压测 + 观察；若 CPU 空闲而延迟高，再从 2 调到 3。
2. 风险：SQLite -> PG 数据不一致。  
   处理：迁移前备份 + 迁移后逐表计数校验 + 回滚到 SQLite 预案。
3. 风险：异步任务引入后链路变复杂。  
   处理：先只迁一个任务（PDF），跑稳后再扩展。

回滚策略：
1. 保留旧镜像 tag。
2. 保留 SQLite 文件备份。
3. 一键切回旧 `DATABASE_URL` + 旧 compose 文件。

---

## 6. 执行清单（可直接按这个顺序做）

1. 调整 Gunicorn 到 `workers=2`，上线观察 24h。
2. 把 PDF 生成改为线程池执行，上线观察 24h。
3. 上 RDS PostgreSQL，完成一次迁移演练（测试环境）。
4. 生产切 PG，保留 SQLite 回滚点。
5. 引入 Redis + 任务 worker，先迁移 PDF 为异步任务。
6. 评估是否迁移到 SAE（稳定后再做）。

---

## 7. 我可以直接帮你做的下一步

1. 直接改你仓库里的 Gunicorn 配置与 Docker 启动参数。  
2. 直接改 `export_pdf` 为线程池执行版本。  
3. 给你生成一份 PostgreSQL 迁移脚本与验证脚本（按你当前表结构）。  

如果你同意，我下一条就开始按这个计划在代码里落地 Phase A + B。
