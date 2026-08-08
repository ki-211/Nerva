# Nerva 项目指引

欢迎！你正在参与 **Nerva** 项目的开发。这是一个个人知识操作系统，使用 AI 自动提取、整合碎片化知识，并学习用户的个性化偏好。

## 快速上手

### 必读文档
开始工作前，请先阅读：
1. **[knowledge/00_READ_FIRST.md](knowledge/00_READ_FIRST.md)** — 项目概览、技术栈、快速定位指南
2. **[knowledge/01_architecture.md](knowledge/01_architecture.md)** — 系统架构、核心设计决策

### 知识库导航
根据你的任务类型，阅读对应的深度文档：

| 任务类型                        | 阅读文档                                    |
|--------------------------------|---------------------------------------------|
| 理解 AI 知识处理流程            | [03_ai_pipeline.md](knowledge/03_ai_pipeline.md) |
| 修改记忆系统                    | [04_memory_system.md](knowledge/04_memory_system.md) |
| 添加/修改 REST API             | [05_api_reference.md](knowledge/05_api_reference.md) |
| 前端开发（React）               | [06_frontend_guide.md](knowledge/06_frontend_guide.md) |
| 数据库迁移/查询                 | [02_data_models.md](knowledge/02_data_models.md) |
| 本地环境设置、测试、部署         | [07_development_workflow.md](knowledge/07_development_workflow.md) |
| 代码风格、命名约定              | [08_conventions.md](knowledge/08_conventions.md) |

## 项目核心概念（速览）

### 两阶段知识整合流水线
```
用户输入 → Extract（提取知识单元） → Retrieve（检索候选文档） 
         → Plan（规划变更方案） → 用户审查 → 应用变更
```
- Extract 阶段：从原始输入提取结构化知识单元，每个单元必须有 evidence（杜绝 AI 幻觉）
- Plan 阶段：决定创建新文档、追加到现有文档，还是标记为重复/冲突

### 静默记忆注入
- 前端没有聊天窗口，记忆不是对话上下文
- 用户偏好（写作风格、组织习惯等）静默注入到系统提示词
- 三级信任模型：`active`（生效中）、`candidate`（待确认）、`suppressed`（已停用）

### 技术栈
- **后端**：FastAPI + Python 3.12 + PostgreSQL + Alembic
- **前端**：React 18 + TypeScript + Vite
- **AI**：阿里云百炼平台（通义千问系列模型）

## 关键文件索引

### 后端（apps/api/app/）
- `main.py` — FastAPI 路由、pipeline 编排、HTTP 端点
- `store.py` — 数据库操作（纯 SQLAlchemy Core）
- `ai.py` — AI 适配器（BailianAI、LocalDemoAI）
- `schemas.py` — Pydantic 请求/响应模型
- `memories.py` — 记忆加载与格式化
- `prompts.py` — 所有 AI 提示词（集中管理）
- `alembic/versions/` — 数据库迁移文件

### 前端（apps/web/src/）
- `main.tsx` — 路由配置、入口文件
- `app/AppShell.tsx` — 主布局（侧边栏+导航）
- `features/capture/` — 知识录入（文本/图片）
- `features/changes/` — 变更草案审查
- `features/documents/` — 文档列表与详情、导出
- `features/memories/` — 偏好记忆管理
- `lib/api.ts` — API 客户端
- `lib/types.ts` — TypeScript 类型定义

### 数据库迁移
位置：`apps/api/alembic/versions/`

运行迁移：
```bash
cd /d/AICoding/Nerva
.venv/Scripts/python.exe -m alembic upgrade head
```

## 开发环境启动

### 后端
```bash
cd /d/AICoding/Nerva
.venv/Scripts/python.exe -m uvicorn apps.api.app.main:app --reload
```
访问：http://localhost:8000/docs

### 前端
```bash
cd apps/web
pnpm dev
```
访问：http://localhost:5173

## 代码修改后的必做事项

### 1. 同步更新知识库
- 修改 API 端点 → 更新 `knowledge/05_api_reference.md`
- 数据库迁移 → 更新 `knowledge/02_data_models.md`
- AI 流水线变更 → 更新 `knowledge/03_ai_pipeline.md`
- 前端组件重构 → 更新 `knowledge/06_frontend_guide.md`

### 2. 修改文档顶部日期
```markdown
> 最后更新：2026-08-08
```

### 3. 更新 .env.example（如有新环境变量）
禁止把真实 API Key 提交到 Git，只提交占位符。

## 重要约定

### 安全约束
- 真实 Key 只能放在本机 `.env`、CI Secret 或云密钥管理服务
- 禁止把 Key 写进 React 代码；浏览器只能调用 Nerva 后端
- `.env.example` 可以提交，但必须保持 Key 为空

### 用户隔离
所有数据库操作都必须在 WHERE 子句中加上 `user_id` 校验：
```python
# 正确
doc = store.get_document(user_id, doc_id)

# 错误（任何人都能访问任何文档）
doc = store.get_document_by_id(doc_id)
```

### 提示词管理
所有 AI 提示词集中在 `apps/api/app/prompts.py`，禁止在其他文件硬编码提示词内容。

## 常见任务快速参考

### 添加新的 REST API 端点
1. 在 `main.py` 添加路由处理函数
2. 在 `schemas.py` 添加 Pydantic 模型（如有请求/响应体）
3. 在 `store.py` 添加数据库操作方法（如需访问数据库）
4. 更新 `knowledge/05_api_reference.md`

### 创建数据库迁移
```bash
cd /d/AICoding/Nerva
.venv/Scripts/python.exe -m alembic revision -m "add_user_settings"
# 编辑生成的文件：apps/api/alembic/versions/NNNN_add_user_settings.py
.venv/Scripts/python.exe -m alembic upgrade head
```

### 添加新的记忆类型（kind）
1. 在 `schemas.py` 的 `MemoryKind` Literal 添加新类型
2. 在 `memories.py` 的 `_KIND_LABELS` 添加中文标签
3. 在 `memories.py` 的 `_EXTRACT_KINDS` 或 `_PLAN_KINDS` 添加注入规则
4. 更新数据库 CHECK 约束（新建迁移）
5. 更新 `knowledge/04_memory_system.md`

### 修改 AI 提示词
1. 编辑 `apps/api/app/prompts.py` 中的对应提示词常量
2. 升级版本号（例如 `extract-v2` → `extract-v3`）
3. 更新 `knowledge/03_ai_pipeline.md` 中的提示词说明

## 测试

### 运行后端测试
```bash
cd apps/api
../../.venv/Scripts/python.exe -m pytest tests/ -v
```

### 测试 AI 推断（需要真实 API Key）
```bash
cd scripts/
../. venv/Scripts/python.exe real_bailian_smoke.py
```

## 问题排查

### 后端无法启动
1. 检查 `.env` 配置是否完整
2. 检查数据库连接：`python apps/api/check_db.py`
3. 检查端口占用：`netstat -ano | findstr :8000`

### AI 调用失败
1. 检查 `DASHSCOPE_API_KEY` 是否有效
2. 查看日志：`grep "ai_call" logs/nerva.log`
3. 切换到本地模式测试：`.env` 设置 `NERVA_AI_PROVIDER=local`

### 数据库迁移失败
```bash
# 查看当前版本
.venv/Scripts/python.exe -m alembic current

# 回滚上一版本
.venv/Scripts/python.exe -m alembic downgrade -1
```

## 项目愿景

Nerva 致力于成为个人知识管理的智能操作系统：
- **无摩擦录入**：文本/图片随手记录，AI 自动整合
- **渐进式学习**：从用户行为中学习偏好，自动应用
- **透明可控**：所有 AI 提议必须审查，用户始终掌控知识库

---

**有疑问？** 先查阅对应的知识库文档，文档未覆盖的再提问。

**发现知识库与代码不一致？** 请立即更新知识库并同步提交。
