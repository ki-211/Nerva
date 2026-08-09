# Nerva

## 管理员与大众知识库

Nerva 提供应用内大众知识库：所有已登录用户可以阅读，只有管理员可以新增、编辑和下架。管理员控制台还会展示用户及知识库归属，普通用户既看不到入口，也无法访问管理员 API。

开发示例管理员为 `admin / admin`。复制 `.env.example` 后必须设置 `NERVA_ADMIN_PASSWORD`；生产上线前务必替换为强密码并通过部署平台 Secret 提供。API 每次启动会把数据库中的管理员密码哈希同步到当前环境变量值，密码变化时旧管理员会话会自动失效。真实密码不得写入 README、SQL、项目知识目录或 Git。

初始化或补齐内置大众知识文章：

```powershell
python -m alembic -c alembic.ini upgrade head
python scripts/seed_public_knowledge.py
```

> 让你的知识库随着每一次输入持续成长。

Nerva 是一个开源的 AI 个人知识系统。它不会只把图片或文字转换成孤立笔记，而会检索已有知识、生成可审阅的合并草案，并记录知识如何发生变化。

## 当前进度

当前版本实现第一条可运行闭环：

1. 使用邮箱验证码直接登录，首次登录自动创建独立账号；
2. 输入文字资料，或一次上传 1～10 张 JPG、PNG、WebP 文字图片；图片只在系统临时目录存在到 OCR 完成；
3. 生成知识变更草案；
4. 审阅并接受变更；
5. 在面向人的知识库中搜索、阅读和手工编辑 Markdown 文档；
6. 导出当前文档或全部知识：人类阅读版支持 Markdown 和浏览器打印 PDF，AI 版为带完整谱系的结构化 ZIP 知识包；
7. 查看版本历史，以及可展开到变更前后、依据和原始输入的知识成长日志。

当前支持本地 Mock 和真实阿里云百炼两种 Provider；百炼模式采用“知识提取 → 候选召回 → 多项变更规划 → 用户审批”两阶段结构化调用。现有静态视觉稿保留在 `UI/`，产品代码位于 `apps/`。完整代码说明见 [架构文档](docs/ARCHITECTURE.md)。

多图片录入会按图片校验知识覆盖。首次整体提取遗漏某张图时，只对遗漏 OCR 文本补提一次；仍不完整则明确失败，不生成残缺草案。不同主题会拆成不同文档。未审批草案支持填写组织建议并使用已保存文字重新分析，旧草案只在新草案成功后标记为已取代。

## 代码结构

```text
apps/web       React + TypeScript + Vite
apps/api       FastAPI + PostgreSQL
docs           架构和设计文档
scripts        仓库维护脚本
UI             原始视觉原型
```

## 本地启动

```powershell
# 首次安装
pnpm install
python -m pip install -r apps/api/requirements.txt

# 配置 PostgreSQL
Copy-Item .env.example .env
python -m alembic -c alembic.ini upgrade head
python apps/api/check_db.py

# API（终端 1）
python -m uvicorn app.main:app --reload --app-dir apps/api --port 8000

# Web（终端 2）
pnpm --dir apps/web dev
```

打开 http://localhost:5173。Windows 安装、账号、密码和数据库配置见 [PostgreSQL 配置指南](docs/POSTGRESQL.md)。

登录验证码通过 SMTP 发送。以 QQ 邮箱为例，在 `.env` 中填写 `SMTP_USERNAME` 和 QQ 邮箱生成的 SMTP 授权码 `SMTP_PASSWORD`；不要填写 QQ 登录密码。验证码 5 分钟有效，同一邮箱 60 秒内只能发送一次。

API 日志同时输出到控制台和 `logs/nerva-api.log`，达到 5 MB 后自动轮转并保留 3 份。前端只展示用户可理解的错误，SMTP 等内部异常详情记录在服务端日志中。

## AI 配置

默认使用确定性的本地演示适配器，无需 API Key。设置 `NERVA_AI_PROVIDER=bailian` 后会调用百炼 OpenAI-compatible API；失败来源会保留稳定错误码和 `source_id`，不会回退为关键词结果，可在页面直接重试。

图片录入使用 `qwen3.5-ocr`。后端只把图片写入随机系统临时目录，单图 OCR 请求完成后立即删除，任务结束再兜底清理；数据库只保存组合后的 OCR 文本、知识单元、变更草案和成长日志。OCR 失败必须重新上传，OCR 成功后的知识整合失败可以直接用已保存文本重试。

复制 `.env.example` 为本机 `.env`，将 Provider 切换为 `bailian` 并在本地填写真实值。不要直接修改示例文件存放真实值。`.gitignore` 会忽略 `.env`、私钥、签名密钥和本地数据库。提交前可运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-secrets.ps1
```

密钥安全规则：

- 真实 Key 只能放在本机 `.env`、CI Secret 或云密钥管理服务。
- 禁止把 Key 写进 React 代码；浏览器只能调用 Nerva 后端。
- `.env.example` 可以提交，但必须保持 Key 为空。
- Windows/iOS 的签名私钥同样禁止进入 Git。

## 验证

```powershell
Push-Location apps/api
python -m unittest discover -s tests -v
Pop-Location
python -m alembic -c alembic.ini check
pnpm --dir apps/web run build
powershell -ExecutionPolicy Bypass -File scripts/check-secrets.ps1
```

## 开源说明

项目尚未选择最终开源许可证。在添加 `LICENSE` 前，需要在 MIT、Apache-2.0 或其他许可证中明确选择，避免贡献和商业使用边界不清。
