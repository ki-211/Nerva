# Windows 双客户端：错误、日志与监控运行说明

本阶段仍运行单个远程 FastAPI + PostgreSQL 服务，不部署 Web 前端，也不打包 EXE。`apps/web` 是未来 Tauri 用户端和管理端共享 UI/错误层的开发载体。

## 发布前顺序

1. 安装 `apps/api/requirements.txt`，执行 `alembic upgrade head`，确认版本为 `0012`。
2. 生产环境设置 `NERVA_ENV=production`、`NERVA_LOG_FORMAT=json`、HTTPS 安全 Cookie、随机验证码密钥、非默认管理员密码、`NERVA_METRICS_TOKEN` 与 Sentry DSN。
3. 只启动一个 API worker。索引任务仍是进程内单线程执行器；接入持久任务队列前不得水平扩容。
4. 监控系统探测 `/health/live` 和 `/health/ready`，携带 Bearer Token 抓取 `/metrics`。
5. 导入 `ops/prometheus/nerva-alerts.yml`。管理员登录告警按当前单管理员模型统计；失败详情通过 `audit_events` 中的哈希账号/IP 标识定位。

`/health/ready` 会检查必要配置、数据库连接和迁移版本。AI Provider 的必填凭据由配置校验负责；检查失败只返回稳定错误码，不返回驱动或供应商异常。

## 日志与隐私

生产 API 只输出 JSON stdout。本地开发额外写 `logs/nerva-api.log`，单文件 10 MB、保留 5 个轮转文件。Sentry 默认性能采样 10%，禁用默认 PII，并在发送前递归清除正文、Markdown、OCR、Embedding、密码、验证码、Cookie、Token、API Key 和邮箱。

客户端 `clientLogger` 在开发环境写控制台，生产上报脱敏 Sentry。它已经提供 Tauri 日志桥接入口 `window.__NERVA_DESKTOP_LOG__`，后续壳层必须按下列目录实现 10 MB × 5 文件轮转：

- 用户端：`%LOCALAPPDATA%\Nerva\logs`
- 管理端：`%LOCALAPPDATA%\Nerva Admin\logs`

“导出诊断日志”只导出再次脱敏后的 NDJSON，并由用户主动选择保存位置。两个正式客户端应分别设置 `VITE_CLIENT_TYPE=user-desktop` 与 `admin-desktop`，并使用独立版本号、应用 ID、安装目录和更新通道。

## 安全边界

管理端知识归属接口仅返回标题、用户标识、版本、可见性、索引状态和时间元数据。私有正文管理接口固定返回 `ADMIN_PRIVATE_CONTENT_FORBIDDEN`；管理端不包含对应 API 调用。管理员自己的公共文档仍可通过公共知识维护接口完整读写。

所有 REST 错误都使用 `error` envelope，SSE 错误事件也带稳定 `code` 和 `request_id`。客户端仍暂时兼容旧 `detail`，完成所有存量客户端迁移后可删除该分支。
