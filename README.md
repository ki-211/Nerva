# Nerva

> 让你的知识库随着每一次输入持续成长。

Nerva 是一个开源的 AI 个人知识系统。它不会只把图片或文字转换成孤立笔记，而会检索已有知识、生成可审阅的合并草案，并记录知识如何发生变化。

## 当前进度

当前版本实现第一条可运行闭环：

1. 输入文字资料；
2. 生成知识变更草案；
3. 审阅并接受变更；
4. 生成文档版本和知识成长日志。

默认使用本地演示 AI，无需注册云服务或配置 Key。现有静态视觉稿保留在 `UI/`，产品代码位于 `apps/`。完整代码说明见 [架构文档](docs/ARCHITECTURE.md)。

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
python apps/api/check_db.py

# API（终端 1）
python -m uvicorn app.main:app --reload --app-dir apps/api --port 8000

# Web（终端 2）
pnpm --dir apps/web dev
```

打开 http://localhost:5173。Windows 安装、账号、密码和数据库配置见 [PostgreSQL 配置指南](docs/POSTGRESQL.md)。

## AI 配置

默认使用确定性的本地演示适配器，无需 API Key。云端百炼适配器会通过相同接口接入。

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
python -m unittest discover -s apps/api/tests -v
pnpm --dir apps/web run build
powershell -ExecutionPolicy Bypass -File scripts/check-secrets.ps1
```

## 开源说明

项目尚未选择最终开源许可证。在添加 `LICENSE` 前，需要在 MIT、Apache-2.0 或其他许可证中明确选择，避免贡献和商业使用边界不清。
