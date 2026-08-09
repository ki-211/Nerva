# Nerva 用户端 Windows 桌面版

本目录中的 Tauri 2 客户端只包含普通用户功能。它不内置 Python、PostgreSQL、SMTP/AI 密钥或后端进程，运行时连接 `apps/user-desktop/user-profile.json` 中配置的 API 地址。

## 环境要求

- Windows 10/11 x64
- Node.js 与 pnpm
- Rust stable MSVC（目标 `x86_64-pc-windows-msvc`）
- Microsoft C++ Build Tools，包含“使用 C++ 的桌面开发”和 Windows SDK
- WebView2；安装程序使用嵌入式 bootstrapper，在系统缺少运行库时联网补装

## 本地运行和构建

先单独启动 FastAPI、PostgreSQL、SMTP 和 AI 服务，确认 API 可访问 `http://localhost:8000`，然后在仓库根目录执行：

```powershell
pnpm dev:user-desktop
pnpm build:user-desktop:web
pnpm check:user-desktop
pnpm build:user-desktop
```

四条命令依次用于桌面开发运行、只构建隔离的用户前端、执行 Rust 格式/测试/Clippy 检查、生成 x64 NSIS 安装程序。安装程序输出在 `apps/user-desktop/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/`，不应提交到 Git。

## 切换正式服务器

只修改 `apps/user-desktop/user-profile.json` 的 `apiUrl` 为正式 HTTPS Origin（不能带账号、查询参数或 fragment），再重新执行 `pnpm build:user-desktop`。构建脚本会同时生成：

- `VITE_API_URL`
- `VITE_CLIENT_TYPE=user-desktop`
- `VITE_APP_VERSION=0.1.0`
- 精确限定到该 Origin 的 Tauri HTTP 权限

用户构建完成后会自动扫描产物，拒绝包含管理员登录 API、`/v1/admin/` 或管理员控制台文案的安装包前端资源。

## 安装行为

NSIS 使用当前用户安装模式，创建开始菜单和桌面快捷方式，并注册卸载入口。当前版本未签名，因此 Windows 可能显示“未知发布者”。桌面日志写入 `%LOCALAPPDATA%\Nerva\logs`，按 10 MB 轮转并保留最近 5 份。
