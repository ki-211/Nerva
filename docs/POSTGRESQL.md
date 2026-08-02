# Windows 本地 PostgreSQL 配置

Nerva 本地开发直接使用 PostgreSQL 安装时创建的 `postgres` 管理员账号，并单独创建 `nerva` 数据库。

## 1. 下载与安装

从 [PostgreSQL 官方 Windows 下载页](https://www.postgresql.org/download/windows/) 进入 EDB 图形安装器。Nerva 支持 PostgreSQL 17；你已经安装的版本可以直接使用。

保留以下组件：

- PostgreSQL Server
- pgAdmin 4
- Command Line Tools

安装向导中：

1. 安装目录和数据目录使用默认值即可。
2. 为管理员 `postgres` 设置强密码，并保存到密码管理器。
3. 端口使用默认 `5432`。
4. Locale 使用系统默认。
5. Stack Builder 当前可以跳过。

## 2. 创建 `nerva` 数据库

打开 PowerShell。路径按 PostgreSQL 17 默认安装目录编写：

```powershell
$nervaPgBin = 'C:\Program Files\PostgreSQL\17\bin'

& "$nervaPgBin\createdb.exe" `
  -U postgres -h 127.0.0.1 -p 5432 `
  -W -O postgres -E UTF8 nerva
```

输入安装时设置的 `postgres` 密码。密码输入时终端不会显示字符，这是正常现象。

也可以执行仓库中的建库 SQL：

```powershell
& "$nervaPgBin\psql.exe" `
  -U postgres -h 127.0.0.1 -p 5432 `
  -W -d postgres -f database/create_database.sql
```

两种方式选择一种即可。数据库已经存在时不要重复执行建库语句。

## 3. 创建数据表

仓库提供完整 PostgreSQL DDL：[database/schema.sql](../database/schema.sql)。执行：

```powershell
& "$nervaPgBin\psql.exe" `
  -U postgres -h 127.0.0.1 -p 5432 `
  -W -d nerva -f database/schema.sql
```

该脚本创建：

- 原始资料表 `sources`
- 正式文档表 `documents`
- 不可变文档版本表 `document_versions`
- AI 变更草案表 `change_sets`
- 逐项变更表 `change_items`
- 知识成长日志表 `knowledge_events`
- 外键、检查约束和常用索引

建表语句使用 `IF NOT EXISTS`，可以安全地重新执行。应用启动时 SQLAlchemy 也会补建缺失表，但数据库初始化建议明确执行该 SQL 文件。

## 4. 配置本机 `.env`

在仓库根目录执行：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

```text
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=nerva
POSTGRES_USER=postgres
POSTGRES_PASSWORD=
```

只在本机 `.env` 最后一行的等号后填写安装时设置的 `postgres` 密码。`.env` 已被 `.gitignore` 忽略，不要将密码写入 `.env.example`、README、SQL 文件或截图。

云数据库如果提供完整连接地址，也可以设置 `DATABASE_URL`；提供后，分开的 `POSTGRES_*` 配置不再生效。

## 5. 验证连接和表

```powershell
python -m pip install -r apps/api/requirements.txt
python apps/api/check_db.py
```

成功时应显示：

```text
Database: nerva
User: postgres
Server: PostgreSQL ...
Nerva PostgreSQL connection is ready.
```

查看数据表：

```powershell
& "$nervaPgBin\psql.exe" -U postgres -h 127.0.0.1 -p 5432 -d nerva -W
```

进入 psql 后运行 `\dt`，应该看到 6 张表；运行 `\q` 退出。

## 6. 启动 Nerva

```powershell
python -m uvicorn app.main:app --reload --app-dir apps/api --port 8000
```

另开终端：

```powershell
pnpm --dir apps/web dev
```

## 常见问题

- `connection refused`：确认 PostgreSQL Windows 服务正在运行，端口为 5432。
- `password authentication failed`：确认 `.env` 中是安装时设置的 `postgres` 密码。
- `database "nerva" does not exist`：执行建库命令或 `create_database.sql`。
- 找不到 `psql`：确认实际版本，并使用完整的 `PostgreSQL\版本\bin` 路径。
- 忘记密码：在 pgAdmin 中修改 `postgres` 密码，再同步更新 `.env`。

本地开发无需开放 Windows 防火墙端口，也不要把 PostgreSQL 直接暴露到公网。若未来把 Nerva 部署为公开服务，应再改回独立的最小权限应用账号。
