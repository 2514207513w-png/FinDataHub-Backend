# FinDataHub: 金融产品资料管理与异步 PDF 入库后端（学习用 MVP）

独立后端服务，供另一个 **LangGraph 金融 RAG Agent** 通过 REST API 获取结构化产品信息与已解析的 PDF 文本。使用公开/合成数据；不是证券交易、真实投顾或生产金融系统。

## 技术选型
Python 3.11 / FastAPI / SQLAlchemy 2 / PostgreSQL / Redis / Celery / JWT (PyJWT + Argon2) / pypdf / pytest / Docker Compose。

## 启动
1. `cp .env.example .env`（Windows 可复制并重命名）；务必修改 `JWT_SECRET` 至至少32位随机字符串和 `BOOTSTRAP_ADMIN_PASSWORD`。
2. `docker compose up --build -d`
3. 打开 `http://127.0.0.1:8000/docs` 查看 Swagger API。
4. 先请求 `POST /api/v1/auth/token`：`{"email":"admin@example.test","password":"自己设置的密码"}`，从响应复制 `access_token`，在 Swagger 中点击 Authorize 使用 Bearer token。
5. `POST /api/v1/products` 创建一个模拟产品，如 `{"code":"DEMO001","name":"公开基金样例","risk_level":"R2"}`。
6. `POST /api/v1/products/DEMO001/documents` 上传一份**可提取文本**的 PDF；复制返回的 `job_id`。
7. 轮询 `GET /api/v1/jobs/{job_id}`，状态完成后调用 `GET /api/v1/documents/{document_id}/chunks`。
8. Agent 的 `Product Info Tool` 调用 GET 产品信息；RAG 入库脚本调用 GET 文档 chunks 后自行进行 Embedding 和 FAISS 索引。

## API 摘要
| Method | API | 作用 |
|---|---|---|
| POST | `/api/v1/auth/token` | JWT 登录 |
| POST | `/api/v1/users` | admin 创建 analyst/viewer 账号 |
| POST | `/api/v1/products` | 创建产品（admin/analyst） |
| GET | `/api/v1/products` | 产品分页列表 |
| PATCH | `/api/v1/products/{code}` | 修改产品及缓存失效 |
| GET | `/api/v1/products/{code}` | 查询产品（Redis TTL 缓存） |
| POST | `/api/v1/products/{code}/documents` | 上传 PDF / SHA256 去重 / 投递异步任务 |
| GET | `/api/v1/jobs/{job_id}` | 轮询后台处理状态 |
| POST | `/api/v1/jobs/{job_id}/retry` | 人工重投失败任务 |
| GET | `/api/v1/documents/{document_id}/chunks` | Agent/RAG 读取文档分块 |

## 关键实现路径
- `app/main.py`：API、参数校验、权限、Redis 查询缓存、文件上传、任务下发。
- `app/models.py`：5张业务表：users, products, documents, ingestion_jobs, document_chunks。
- `app/worker.py`：Celery 消费任务、PDF 解析、分块、事务性落库、指数退避重试。
- `app/security.py`：JWT 及角色检查。
- `app/utils.py`：PDF 头部与大小校验、文本分块。
- `tests/test_utils.py`：纯函数测试；运行 `docker compose run --rm api pytest -q`。

## 给大厂面试的验证项（需要自己完成）
- 产品 API 的正常、404、409、未授权、越权测试；提交至少30个自动化测试用例。
- Redis Cache hit/miss 比较，固定并发及样本，记录 P50/P95 延迟；真实数值不得伪造。
- 上传相同文档两次：验证 SHA256 去重，且不会生成第二个处理作业。
- 模拟 Worker 处理失败：观察状态与重试次数；不要在生产服务中注入故障。
- 用 Agent 调用 `/api/v1/products/{code}` 查询产品，再通过文档 chunks 做 RAG 问答。

## 这个版本的边界与待改进事项（重要）
1. 当前是 **学习用起步项目，不是生产就绪系统**。表创建使用 `create_all`，正式项目应通过 Alembic 管理版本。
2. 文档上传是内存读取、基础 PDF 头检测；生产应采用流式上传、完整 MIME/恶意文件扫描、隔离转换、配额限制。
3. 扫描 PDF 无 OCR，处理会标记失败。没有向量索引生成，它应由项目一负责。
4. Celery 使用 at-least-once 语义；Worker 崩溃边界和“running 卡住”的恢复尚需补足监控与租约/超时重置；不能声称 exactly-once。
5. API DB 提交与 Celery 投递不是一个事务。这里的 `dispatch_failed` + 人工重投只是教学级兜底，生产需 Transactional Outbox + Dispatcher + 巡检补偿。
6. Redis 缓存失效与数据库提交之间仍存在非原子窗口；接口限流、数据行级授权、上传内容清洗、日志脱敏、审计追踪、完整集成测试以及分页查询尚待增加。
7. Docker Compose 中 PostgreSQL 的口令是本地演示凭据；不要直接部署到外网，需替换安全配置并关闭外部端口暴露。
8. 任何招聘简历的“性能提升XX%”“任务成功率XX%”“已上线”都必须在实际完成并验证后才填写。

## 顺序请求延迟测量（用于学习，不是并发压测）
获取一个有效 Token 后，主机环境安装 httpx，再运行：
```bash
python scripts/benchmark.py --token '<JWT_TOKEN>' --code DEMO001 --requests 100
```
输出 P50/P95 是**当前机器的真实观测值**；如需测并发吞吐，另外使用 Locust/k6，并固定压测环境及缓存命中率。


## 作品说明
这是独立学习用的金融产品后端 MVP，不包含企业内部代码、凭据或真实客户数据。现有基础单元测试不等于完整 Docker/业务集成测试；请运行并完善后再将其列为已完成项目。

## 连接 Finance-RAG-Agent
项目一可通过产品查询、文档文本分块 API 调用此服务。
