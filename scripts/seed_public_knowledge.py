"""Idempotently seed the application-wide public knowledge library."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from app.auth import hash_password
from app.settings import settings
from app.store import Store


def technical_article(
    title: str,
    overview: str,
    example: str,
    practices: list[str],
    caveat: str,
    source_name: str,
    source_url: str,
) -> str:
    practice_list = "\n".join(f"- {item}" for item in practices)
    return f"""# {title}

## 说明

{overview}

## 示例

{example}

## 实践建议

{practice_list}

## 常见误区

{caveat}

## 来源

[{source_name}]({source_url})
"""


ARTICLES = [
    (
        "pub_java_virtual_threads",
        "Java 虚拟线程：高并发 I/O 服务的实践指南",
        """# Java 虚拟线程：高并发 I/O 服务的实践指南

## 核心概念

虚拟线程是由 JVM 调度的轻量线程，适合大量等待网络、数据库或文件 I/O 的任务。它提升的是吞吐能力，不是单个任务的 CPU 计算速度。

## 典型写法

```java
try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
    executor.submit(() -> callRemoteService());
}
```

## 使用边界

- 适合阻塞式 I/O 和 thread-per-request 服务。
- 不适合用来加速长时间 CPU 密集计算。
- 仍要限制数据库连接、远程 API 并发和下游配额。

## 参考

[Oracle Java 虚拟线程文档](https://docs.oracle.com/en/java/javase/26/core/virtual-threads.html)
""",
    ),
    (
        "pub_spring_boot_operations",
        "Spring Boot 配置、Actuator 与生产运维",
        """# Spring Boot 配置、Actuator 与生产运维

## 配置原则

把环境差异放进 profile 和环境变量，业务代码只读取类型安全的配置对象；敏感值使用 Secret 管理，不写进仓库。

## Actuator 建议

只暴露健康检查和必要指标，管理端点放在内网或单独的管理端口，并为暴露的端点配置认证。

## 发布检查

1. 检查数据库迁移是否可重复执行。
2. 验证健康检查能区分应用存活和依赖就绪。
3. 为关键配置提供启动时校验和清晰错误信息。

## 参考

[Spring Boot Reference Documentation](https://docs.spring.io/spring-boot/reference/)
""",
    ),
    (
        "pub_mysql_indexes",
        "MySQL 索引设计与查询优化",
        """# MySQL 索引设计与查询优化

## 基本原理

B-Tree 索引可以快速定位等值、范围和排序数据，但索引也会增加写入成本和存储成本。

## 设计清单

- 先用真实查询和 `EXPLAIN` 找出高频慢查询。
- 组合索引遵循最左前缀原则。
- 选择性低的单列字段不一定适合单独建索引。
- 不要为每个字段机械地添加索引。

## 维护建议

定期观察索引命中率、写入放大和执行计划变化；上线前用接近生产规模的数据验证。

## 参考

[MySQL 8.4 How MySQL Uses Indexes](https://dev.mysql.com/doc/refman/8.4/en/mysql-indexes.html)
""",
    ),
    (
        "pub_postgresql_indexes",
        "PostgreSQL 索引、执行计划与全文检索",
        """# PostgreSQL 索引、执行计划与全文检索

## 常见索引

B-tree 适合通用等值和范围查询；GIN 常用于数组、JSONB 和全文检索；BRIN 适合与物理顺序高度相关的大表。

## 排查流程

使用 `EXPLAIN (ANALYZE, BUFFERS)` 比较估算行数和实际行数，关注顺序扫描、错误统计信息和不必要的排序。

## 注意事项

索引不是越多越好。每次插入、更新和删除都可能维护多个索引，创建索引前要确认查询收益。

## 参考

[PostgreSQL Indexes](https://www.postgresql.org/docs/current/indexes.html)
""",
    ),
    (
        "pub_http_fundamentals",
        "HTTP 请求、响应、缓存与安全基础",
        """# HTTP 请求、响应、缓存与安全基础

## 请求生命周期

客户端发送方法、目标、请求头和可选请求体；服务器返回状态码、响应头和响应体。资源语义应通过正确的 HTTP 方法和状态码表达。

## 缓存实践

静态资源可以使用长期缓存并配合内容哈希；动态资源要根据隐私性、更新频率和验证策略设置 `Cache-Control`、ETag 或 Last-Modified。

## 安全底线

生产环境启用 HTTPS，校验 Origin/CSRF 边界，避免把令牌放在可被脚本读取的位置，并对输入和输出分别做验证与编码。

## 参考

[MDN HTTP Overview](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Overview)
""",
    ),
    (
        "pub_docker_getting_started",
        "Docker 容器与 Compose 入门",
        """# Docker 容器与 Compose 入门

## 容器模型

容器是隔离的进程环境，不是虚拟机。镜像应尽量小、可重复构建，并通过环境变量或 Secret 注入配置。

## Compose 适用场景

本地开发可以用 Compose 编排 Web、API、数据库等服务，统一网络、端口、卷和健康检查配置。

## 生产注意事项

- 不要把密码写入镜像或提交到仓库。
- 使用固定镜像版本并扫描依赖漏洞。
- 持久化数据库卷并制定备份策略。

## 参考

[Docker Get Started](https://docs.docker.com/get-started/)
""",
    ),
    (
        "pub_owasp_top10",
        "Web 应用访问控制与 OWASP Top 10",
        """# Web 应用访问控制与 OWASP Top 10

## 最小权限

权限必须在后端强制执行，不能只依赖前端隐藏按钮。每个资源请求都要验证当前用户、资源归属和操作权限。

## 常见风险

重点关注访问控制失效、安全配置错误、注入、身份认证失败、日志告警缺失和异常信息泄露。

## 实践清单

1. 为普通用户和管理员分别写接口级权限测试。
2. 跨用户请求统一返回安全的 404 或 403。
3. 日志记录操作结果，但不记录密码、令牌和敏感正文。

## 参考

[OWASP Top 10 2025](https://owasp.org/Top10/2025/)
""",
    ),
    (
        "pub_full_stack_debugging",
        "Java、MySQL、Spring Boot 项目综合排错清单",
        """# Java、MySQL、Spring Boot 项目综合排错清单

## 先定位边界

按“客户端请求 → 网关/API → 应用日志 → 数据库执行 → 外部依赖”的顺序缩小范围，先确认问题发生在哪一层。

## 常用证据

- 请求 ID、HTTP 状态码和响应时间。
- 应用异常堆栈和数据库慢查询日志。
- `EXPLAIN` 执行计划、连接池状态和线程池队列。

## 修复原则

先建立可复现的最小案例，再修复并补充回归测试；不要用扩大超时、重启服务或盲目加索引掩盖根因。
""",
    ),
]


ARTICLES.extend([
    (
        "pub_java_records",
        "Java Record：简化不可变数据载体",
        technical_article(
            "Java Record：简化不可变数据载体",
            "Record 是一种面向数据聚合的特殊类。编译器会根据组件自动生成访问器、规范构造器、equals、hashCode 和 toString，字段保持 final，适合 DTO、值对象和消息载荷。",
            """```java
record UserSummary(long id, String name) {
    UserSummary {
        if (name == null || name.isBlank()) throw new IllegalArgumentException("name");
    }
}
```""",
            ["在紧凑构造器中校验对象不变量。", "把 Record 用于表达数据，而不是承载大量可变业务状态。", "序列化协议变更时仍要评估字段兼容性。"],
            "Record 并不等于深度不可变；如果组件本身是可变集合，外部仍可能修改集合内容。",
            "Oracle Record Classes", "https://docs.oracle.com/en/java/javase/25/language/records.html",
        ),
    ),
    (
        "pub_java_streams",
        "Java Stream：声明式集合处理",
        technical_article(
            "Java Stream：声明式集合处理",
            "Stream 用流水线表达过滤、映射、排序和归约。中间操作通常是惰性的，只有终止操作触发计算；它适合数据变换，但不是所有循环的替代品。",
            """```java
var names = users.stream()
    .filter(User::active)
    .map(User::name)
    .distinct()
    .sorted()
    .toList();
```""",
            ["流水线中的函数尽量保持无副作用。", "大数据量处理前测量内存和排序成本。", "仅在任务可拆分且收益明确时使用 parallelStream。"],
            "在 Stream 中修改外部集合或依赖执行顺序，容易产生难以复现的问题；并行流也不会自动让代码更快。",
            "Dev.java Stream API", "https://dev.java/learn/api/streams/",
        ),
    ),
    (
        "pub_java_completable_future",
        "CompletableFuture：异步任务编排",
        technical_article(
            "CompletableFuture：异步任务编排",
            "CompletableFuture 同时实现 Future 和 CompletionStage，可组合异步计算、转换结果、合并任务并集中处理异常，适合已有异步 API 的编排。",
            """```java
CompletableFuture.supplyAsync(this::loadUser, ioPool)
    .thenCombine(CompletableFuture.supplyAsync(this::loadOrders, ioPool), View::new)
    .orTimeout(2, TimeUnit.SECONDS)
    .exceptionally(error -> View.empty());
```""",
            ["为阻塞 I/O 提供独立且有界的 Executor。", "为外部调用设置超时、降级和可观测日志。", "在链尾明确消费异常，避免静默失败。"],
            "默认公共线程池适合计算任务，不应无边界地承载数据库或网络阻塞调用。",
            "Oracle CompletableFuture API", "https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/CompletableFuture.html",
        ),
    ),
    (
        "pub_java_gc_tuning",
        "JVM GC：从证据出发的调优方法",
        technical_article(
            "JVM GC：从证据出发的调优方法",
            "垃圾收集器负责分配、识别存活对象并回收内存。调优目标通常是在吞吐量、暂停时间和内存占用之间取舍，应先定义服务级目标，再分析 GC 日志。",
            """```bash
java -Xlog:gc*:file=gc.log:time,level,tags -Xms2g -Xmx2g app.jar
```""",
            ["先记录暂停分位数、分配速率和堆占用趋势。", "保持压测流量和对象生命周期接近生产。", "一次只调整少量参数并保留对照结果。"],
            "盲目增大堆可能降低 GC 频率，却延长单次回收和故障恢复时间。",
            "Oracle GC Tuning Guide", "https://docs.oracle.com/en/java/javase/25/gctuning/introduction-garbage-collection-tuning.html",
        ),
    ),
    (
        "pub_maven_lifecycle",
        "Maven 生命周期与可重复构建",
        technical_article(
            "Maven 生命周期与可重复构建",
            "Maven 的 default、clean、site 生命周期由多个阶段组成。执行某个阶段时，其之前的阶段也会依次执行；插件 goal 绑定到阶段后参与标准构建流程。",
            """```bash
mvn -B clean verify
```""",
            ["CI 使用 Wrapper 或固定 Maven/JDK 版本。", "把单元测试放在 test，集成验证放在 verify 前后的合适插件阶段。", "锁定插件版本，避免构建结果随时间漂移。"],
            "直接调用某个插件 goal 可能绕过项目约定的生命周期检查，不适合作为唯一的发布命令。",
            "Apache Maven Build Lifecycle", "https://maven.apache.org/guides/introduction/introduction-to-the-lifecycle.html",
        ),
    ),
    (
        "pub_gradle_java_build",
        "Gradle Java 构建、Toolchain 与缓存",
        technical_article(
            "Gradle Java 构建、Toolchain 与缓存",
            "Gradle Java 插件提供编译、测试、打包和文档任务。Toolchain 固定编译所用 JDK，增量构建和 Build Cache 则通过输入输出声明减少重复工作。",
            """```kotlin
plugins { `java-library` }
java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }
```""",
            ["提交 Gradle Wrapper 并在 CI 校验 Wrapper。", "任务只读取声明的输入并写入声明的输出。", "用依赖锁定或版本目录管理升级。"],
            "使用本机默认 JDK 会让开发机和 CI 产生不同字节码或测试行为。",
            "Gradle Building Java Projects", "https://docs.gradle.org/current/userguide/building_java_projects.html",
        ),
    ),
    (
        "pub_spring_security_authorization",
        "Spring Security：后端授权与最小权限",
        technical_article(
            "Spring Security：后端授权与最小权限",
            "授权应在请求入口和方法层依据已认证主体、角色及资源归属执行。前端隐藏按钮只能改善体验，不能构成安全边界。",
            """```java
@PreAuthorize("hasRole('ADMIN')")
public void publish(DocumentCommand command) { ... }
```""",
            ["默认拒绝未明确允许的路由。", "对管理员、普通用户和跨用户资源分别写集成测试。", "授权失败日志不要泄露令牌或敏感数据。"],
            "仅检查 URL 角色而不检查具体资源归属，仍可能产生水平越权。",
            "Spring Security Authorization", "https://docs.spring.io/spring-security/reference/servlet/authorization/index.html",
        ),
    ),
    (
        "pub_spring_data_jpa",
        "Spring Data JPA：实体、查询与事务边界",
        technical_article(
            "Spring Data JPA：实体、查询与事务边界",
            "Spring Data JPA 用 Repository 抽象常见持久化操作，但实体生命周期、抓取策略、事务和生成 SQL 仍需要显式理解。复杂查询应通过日志和执行计划验证。",
            """```java
interface OrderRepository extends JpaRepository<Order, Long> {
    @EntityGraph(attributePaths = "items")
    Optional<Order> findByIdAndOwnerId(long id, long ownerId);
}
```""",
            ["查询方法同时带上资源归属条件。", "列表接口避免无界加载关联集合。", "在服务层定义清晰、短小的事务边界。"],
            "依赖 Open Session in View 掩盖懒加载问题，常导致 N+1 查询和不可预测的数据库访问。",
            "Spring Data JPA Reference", "https://docs.spring.io/spring-data/jpa/reference/jpa.html",
        ),
    ),
    (
        "pub_redis_data_types",
        "Redis 数据类型与建模选择",
        technical_article(
            "Redis 数据类型与建模选择",
            "Redis 提供 String、Hash、List、Set、Sorted Set、Stream 等数据类型。模型选择应由访问模式、原子操作、排序需求和内存成本决定。",
            """```text
HSET user:42 name "Lin" status "active"
EXPIRE user:42 3600
```""",
            ["为缓存键定义统一命名和 TTL 策略。", "优先使用数据类型自带的原子命令。", "监控大键、热键、命中率和淘汰量。"],
            "把 Redis 当作无限内存数据库，或对单个键存入过大的集合，会放大阻塞和迁移风险。",
            "Redis Data Types", "https://redis.io/docs/latest/develop/data-types/",
        ),
    ),
    (
        "pub_redis_persistence",
        "Redis RDB、AOF 与数据恢复",
        technical_article(
            "Redis RDB、AOF 与数据恢复",
            "RDB 生成时间点快照，AOF 记录写操作，两者在恢复速度、数据丢失窗口、文件体积和运行开销上各有取舍，可根据数据价值组合使用。",
            """```conf
appendonly yes
appendfsync everysec
save 900 1
```""",
            ["在独立环境定期演练备份恢复。", "监控重写耗时、磁盘空间和最近一次持久化状态。", "缓存与事实数据采用不同的恢复目标。"],
            "开启持久化不等于拥有备份；误删除、损坏和整机故障仍需要异地副本。",
            "Redis Persistence", "https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/",
        ),
    ),
    (
        "pub_mongodb_data_modeling",
        "MongoDB 文档建模：嵌入还是引用",
        technical_article(
            "MongoDB 文档建模：嵌入还是引用",
            "MongoDB 建模应围绕应用访问模式。一起读取、生命周期一致且规模受控的数据适合嵌入；独立增长、共享或需要单独查询的数据更适合引用。",
            """```javascript
{ _id: 42, customer: "Lin", items: [{ sku: "A1", qty: 2 }] }
```""",
            ["先列出核心读写路径再设计集合。", "限制数组和文档的无界增长。", "通过 schema validation 约束关键字段。"],
            "把关系模型逐表照搬为集合，往往造成大量客户端连接查询；反过度嵌入也会制造巨大文档。",
            "MongoDB Data Modeling", "https://www.mongodb.com/docs/manual/data-modeling/",
        ),
    ),
    (
        "pub_sqlite_transactions",
        "SQLite 事务、并发与锁",
        technical_article(
            "SQLite 事务、并发与锁",
            "SQLite 会自动为单条语句建立事务，也支持显式 BEGIN、COMMIT 和 ROLLBACK。读事务可并发，但同一数据库文件同时只能有一个写事务。",
            """```sql
BEGIN IMMEDIATE;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;
```""",
            ["业务上的多步修改必须放在同一事务。", "写竞争明显时设置合理 busy timeout 并缩短事务。", "服务部署前确认共享文件系统是否适合 SQLite。"],
            "长时间持有读写事务会阻塞其他请求；SQLite 适合许多本地场景，但不是高写入并发的通用替代品。",
            "SQLite Transactions", "https://www.sqlite.org/lang_transaction.html",
        ),
    ),
    (
        "pub_postgresql_isolation",
        "PostgreSQL 事务隔离与并发异常",
        technical_article(
            "PostgreSQL 事务隔离与并发异常",
            "隔离级别决定并发事务能观察到哪些变化。Read Committed 是 PostgreSQL 默认级别；Repeatable Read 提供稳定快照；Serializable 可能因冲突要求事务重试。",
            """```sql
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;
UPDATE inventory SET stock = stock - 1 WHERE sku = 'A1' AND stock > 0;
COMMIT;
```""",
            ["依据业务不变量选择隔离级别。", "Serializable 失败要重试整个事务。", "锁等待和死锁日志应纳入监控。"],
            "提高隔离级别不能替代正确的条件更新、唯一约束和重试策略。",
            "PostgreSQL Transaction Isolation", "https://www.postgresql.org/docs/current/transaction-iso.html",
        ),
    ),
    (
        "pub_mysql_transactions",
        "MySQL InnoDB 事务与锁排查",
        technical_article(
            "MySQL InnoDB 事务与锁排查",
            "InnoDB 通过多版本并发控制和行级锁支持事务。索引选择会影响扫描和加锁范围，因此慢查询、锁等待与索引设计需要一起分析。",
            """```sql
START TRANSACTION;
SELECT status FROM orders WHERE id = 42 FOR UPDATE;
UPDATE orders SET status = 'paid' WHERE id = 42;
COMMIT;
```""",
            ["事务内避免远程调用和用户交互。", "用稳定顺序更新多行以降低死锁概率。", "记录死锁报告并验证访问路径是否命中索引。"],
            "锁是加在索引记录和范围上的；缺少合适索引可能让看似单行的更新锁住更大范围。",
            "MySQL InnoDB Transaction Model", "https://dev.mysql.com/doc/refman/8.4/en/innodb-transaction-model.html",
        ),
    ),
    (
        "pub_postgresql_backup",
        "PostgreSQL pg_dump 备份与恢复演练",
        technical_article(
            "PostgreSQL pg_dump 备份与恢复演练",
            "pg_dump 生成逻辑备份，支持纯 SQL 和归档格式。自定义格式可由 pg_restore 选择对象、控制恢复顺序并进行并行恢复。",
            """```bash
pg_dump -Fc --file=nerva.dump nerva
createdb nerva_restore
pg_restore --clean --if-exists --dbname=nerva_restore nerva.dump
```""",
            ["备份文件加密并限制访问权限。", "定期恢复到临时数据库并运行一致性检查。", "记录 RPO、RTO 和数据库版本兼容要求。"],
            "备份命令成功不代表备份可用；只有完成恢复并验证业务数据才算有效演练。",
            "PostgreSQL SQL Dump", "https://www.postgresql.org/docs/current/backup-dump.html",
        ),
    ),
    (
        "pub_http_semantics",
        "HTTP 方法、状态码与幂等语义",
        technical_article(
            "HTTP 方法、状态码与幂等语义",
            "HTTP 语义规定方法、状态码和字段的通用含义。GET、HEAD、PUT、DELETE 属于幂等方法，但幂等描述的是重复相同请求的预期效果，不代表响应完全相同。",
            """```http
PUT /profiles/42 HTTP/1.1
Content-Type: application/json

{"displayName":"Lin"}
```""",
            ["用状态码准确区分认证、授权、冲突和校验失败。", "重试写请求前确认方法语义或使用幂等键。", "缓存策略与资源语义一起设计。"],
            "把所有操作都塞进 POST 并统一返回 200，会削弱代理、缓存、监控和客户端的正确行为。",
            "RFC 9110 HTTP Semantics", "https://datatracker.ietf.org/doc/html/rfc9110",
        ),
    ),
    (
        "pub_websocket",
        "WebSocket 实时通信与连接治理",
        technical_article(
            "WebSocket 实时通信与连接治理",
            "WebSocket 在一次 HTTP 握手后建立双向长连接，适合聊天、协作和实时状态推送。应用仍需自行定义消息格式、身份续期、心跳、重连和背压策略。",
            """```javascript
const socket = new WebSocket('wss://example.com/events');
socket.addEventListener('message', event => render(JSON.parse(event.data)));
```""",
            ["生产环境使用 wss 并校验 Origin 和身份。", "定义心跳、最大消息、空闲超时和指数退避。", "在服务端限制每用户连接数和发送速率。"],
            "浏览器 WebSocket API 本身不提供背压；生产者过快时可能造成缓冲、内存和延迟持续增长。",
            "MDN WebSocket API", "https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API",
        ),
    ),
    (
        "pub_cors",
        "CORS：跨源请求的正确配置",
        technical_article(
            "CORS：跨源请求的正确配置",
            "CORS 由服务器通过响应头告诉浏览器哪些跨源前端可以读取响应。复杂请求可能先发送预检 OPTIONS；它是浏览器安全机制，不是服务端认证。",
            """```http
Access-Control-Allow-Origin: https://app.example.com
Access-Control-Allow-Credentials: true
Vary: Origin
```""",
            ["生产环境使用明确的 Origin 白名单。", "携带 Cookie 时同时配置凭据和 SameSite 策略。", "代理缓存动态 Origin 响应时设置 Vary。"],
            "允许任意 Origin 并不会让私有 API 自动安全；非浏览器客户端也不受浏览器 CORS 限制。",
            "MDN CORS Guide", "https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS",
        ),
    ),
    (
        "pub_web_storage",
        "浏览器 Web Storage 的边界与安全",
        technical_article(
            "浏览器 Web Storage 的边界与安全",
            "localStorage 在同源页面间持久保存字符串，sessionStorage 通常限定在标签页会话。两者是同步 API，容量和可用性取决于浏览器策略。",
            """```javascript
localStorage.setItem('theme', 'dark');
const theme = localStorage.getItem('theme') ?? 'system';
```""",
            ["只保存低敏感、体积小且可丢失的偏好。", "读取后进行 JSON 解析和结构校验。", "提供版本字段和清理旧数据的迁移逻辑。"],
            "不要把会话令牌、密码或敏感正文放进 localStorage；任何同源脚本都可能读取它。",
            "MDN Web Storage API", "https://developer.mozilla.org/en-US/docs/Web/API/Web_Storage_API",
        ),
    ),
    (
        "pub_react_state",
        "React 状态设计：单一事实来源",
        technical_article(
            "React 状态设计：单一事实来源",
            "良好的状态结构应避免矛盾和重复，把共享状态提升到最近公共父组件，并用 props 形成可追踪的数据流。可由现有数据计算出的值通常不必再存入 state。",
            """```tsx
const [selectedId, setSelectedId] = useState<string | null>(null);
const selected = items.find(item => item.id === selectedId) ?? null;
```""",
            ["保存 ID 而不是重复保存完整选中对象。", "复杂更新用 reducer 表达事件。", "服务端数据、URL 状态和本地 UI 状态分层管理。"],
            "在多个 state 中保存同一份业务数据，更新其中一个时很容易产生不一致界面。",
            "React Managing State", "https://react.dev/learn/managing-state",
        ),
    ),
    (
        "pub_typescript_narrowing",
        "TypeScript 类型收窄与穷尽检查",
        technical_article(
            "TypeScript 类型收窄与穷尽检查",
            "TypeScript 会根据 typeof、in、instanceof、真值判断和自定义类型谓词缩小联合类型。可辨识联合让不同业务状态拥有不同必填字段。",
            """```ts
type Result = { kind: 'ok'; value: string } | { kind: 'error'; message: string };
function text(result: Result) {
  return result.kind === 'ok' ? result.value : result.message;
}
```""",
            ["使用字面量 kind 表达状态机。", "边界输入先校验再断言类型。", "在 switch 默认分支用 never 做穷尽检查。"],
            "as 类型断言不会做运行时校验；对 API、存储和用户输入直接断言会隐藏真实错误。",
            "TypeScript Narrowing", "https://www.typescriptlang.org/docs/handbook/2/narrowing.html",
        ),
    ),
    (
        "pub_node_event_loop",
        "Node.js 事件循环与阻塞排查",
        technical_article(
            "Node.js 事件循环与阻塞排查",
            "Node.js 通过事件循环协调定时器、I/O 回调和其他阶段。JavaScript 回调执行时间过长会阻塞同一进程中的其他请求，即使该应用大量使用 async/await。",
            """```javascript
import { setImmediate } from 'node:timers/promises';
for (const batch of batches) {
  processBatch(batch);
  await setImmediate();
}
```""",
            ["监控事件循环延迟和长任务。", "CPU 密集工作移到 Worker 或独立服务。", "为外部 I/O 设置并发上限和超时。"],
            "async 函数不会自动把同步计算移出主线程；一个大循环仍然会阻塞所有连接。",
            "Node.js Event Loop", "https://nodejs.org/learn/asynchronous-work/event-loop-timers-and-nexttick",
        ),
    ),
    (
        "pub_npm_audit",
        "npm 依赖审计与供应链安全",
        technical_article(
            "npm 依赖审计与供应链安全",
            "npm audit 会根据锁文件中的依赖树查询已知漏洞并给出报告。安全修复仍需理解升级范围、验证变更并重新运行测试，而不是机械接受所有自动修改。",
            """```bash
npm ci
npm audit --omit=dev
```""",
            ["提交并审查 lockfile。", "CI 使用 npm ci 保持确定安装。", "结合可达性、运行环境和修复版本评估漏洞优先级。"],
            "强制升级可能引入破坏性版本；审计无告警也不代表依赖或安装脚本绝对安全。",
            "npm Dependency Auditing", "https://docs.npmjs.com/auditing-package-dependencies-for-security-vulnerabilities/",
        ),
    ),
    (
        "pub_git_branching",
        "Git 分支、提交与安全合并",
        technical_article(
            "Git 分支、提交与安全合并",
            "Git 分支本质上是指向提交的轻量指针。创建分支成本很低，适合隔离功能和修复；合并前应同步目标分支并通过测试。",
            """```bash
git switch -c feature/public-library
git add apps/web
git commit -m "Add public library pagination"
```""",
            ["提交聚焦单一意图并写清原因。", "合并前检查 diff、测试和迁移影响。", "共享分支避免强制覆盖他人提交。"],
            "分支不是备份策略；未提交文件和只存在本地的提交仍可能丢失。",
            "Pro Git: Branches in a Nutshell", "https://git-scm.com/book/en/v2/Git-Branching-Branches-in-a-Nutshell",
        ),
    ),
    (
        "pub_github_actions",
        "GitHub Actions：可靠的 CI/CD 工作流",
        technical_article(
            "GitHub Actions：可靠的 CI/CD 工作流",
            "GitHub Actions 工作流由事件触发，包含一个或多个 job；job 在 runner 上执行若干 step，并可通过 needs 建立依赖或使用 matrix 并行验证多种环境。",
            """```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci && npm test
```""",
            ["第三方 Action 固定到可信版本或提交 SHA。", "Secret 只授予必要环境和最小权限。", "构建、测试、迁移检查通过后才能部署。"],
            "把不受信任的拉取请求代码与高权限 Secret 放在同一个工作流中会形成供应链风险。",
            "GitHub Actions Documentation", "https://docs.github.com/en/actions/get-started/understand-github-actions",
        ),
    ),
    (
        "pub_kubernetes_deployments",
        "Kubernetes Deployment：声明式发布与回滚",
        technical_article(
            "Kubernetes Deployment：声明式发布与回滚",
            "Deployment 管理无状态应用的 Pod 副本和滚动更新。控制器持续让实际状态接近期望状态，并通过 ReplicaSet 保存发布演进。",
            """```yaml
apiVersion: apps/v1
kind: Deployment
metadata: {name: api}
spec:
  replicas: 3
  selector: {matchLabels: {app: api}}
  template:
    metadata: {labels: {app: api}}
    spec:
      containers: [{name: api, image: example/api:1.4.2}]
```""",
            ["镜像使用不可变版本或摘要。", "设置资源 requests/limits 和发布超时。", "上线前验证滚动更新与回滚路径。"],
            "Deployment 只保证编排状态，不会自动判断应用是否业务可用；仍需探针、监控和发布门禁。",
            "Kubernetes Deployments", "https://kubernetes.io/docs/concepts/workloads/controllers/deployment/",
        ),
    ),
    (
        "pub_kubernetes_probes",
        "Kubernetes 存活、就绪与启动探针",
        technical_article(
            "Kubernetes 存活、就绪与启动探针",
            "存活探针决定容器是否需要重启；就绪探针决定是否接收流量；启动探针为慢启动应用提供保护，成功后才启用其他探针。",
            """```yaml
readinessProbe:
  httpGet: {path: /ready, port: 8080}
  periodSeconds: 5
livenessProbe:
  httpGet: {path: /live, port: 8080}
```""",
            ["存活检查只验证进程能否自愈。", "就绪检查覆盖接流量所需的关键条件。", "根据启动分布设置 initialDelay 和 failureThreshold。"],
            "把数据库短暂不可用直接作为存活失败条件，可能触发所有副本同时重启并放大故障。",
            "Kubernetes Probes", "https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/",
        ),
    ),
    (
        "pub_nginx_reverse_proxy",
        "NGINX 反向代理、请求头与超时",
        technical_article(
            "NGINX 反向代理、请求头与超时",
            "NGINX 可以把客户端请求转发到上游服务，并控制请求头、缓冲、连接和超时。代理层配置必须与应用的流式响应、上传和长连接特性匹配。",
            """```nginx
location /api/ {
    proxy_pass http://api:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```""",
            ["只信任由受控代理写入的转发头。", "分别设置连接、发送和读取超时。", "SSE 或流式接口按需关闭代理缓冲。"],
            "任意增大超时只能让失败请求占用资源更久；应先定位上游延迟和容量问题。",
            "NGINX Reverse Proxy", "https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/",
        ),
    ),
    (
        "pub_prometheus_metrics",
        "Prometheus 指标类型与命名实践",
        technical_article(
            "Prometheus 指标类型与命名实践",
            "Counter 只增不减，Gauge 可升可降，Histogram 按桶统计分布，Summary 在客户端计算分位数。类型选择影响可聚合性和查询方式。",
            """```promql
sum by (route) (rate(http_requests_total{status=~"5.."}[5m]))
```""",
            ["名称包含单位并使用基础单位。", "标签只使用有界枚举值。", "延迟分位优先评估 Histogram 的跨实例聚合能力。"],
            "把用户 ID、URL 全路径或错误正文放进标签会造成高基数，迅速增加内存和查询成本。",
            "Prometheus Metric Types", "https://prometheus.io/docs/concepts/metric_types/",
        ),
    ),
    (
        "pub_opentelemetry",
        "OpenTelemetry：统一采集 Trace、Metric 与 Log",
        technical_article(
            "OpenTelemetry：统一采集 Trace、Metric 与 Log",
            "OpenTelemetry 提供厂商中立的 API、SDK、语义约定和 Collector，用于生成、处理与导出链路、指标和日志；它本身不是可视化后端。",
            """```text
应用 SDK → OTLP → OpenTelemetry Collector → 可观测性后端
```""",
            ["跨服务传播 trace context。", "统一服务名、环境和版本资源属性。", "在 Collector 中集中做采样、过滤和敏感字段处理。"],
            "全量采集不一定更好；高流量系统必须设计采样、保留期、成本和隐私边界。",
            "OpenTelemetry Overview", "https://opentelemetry.io/docs/what-is-opentelemetry/",
        ),
    ),
    (
        "pub_pytest_fixtures",
        "pytest Fixture：清晰复用测试上下文",
        technical_article(
            "pytest Fixture：清晰复用测试上下文",
            "Fixture 通过依赖注入向测试提供数据、资源和清理逻辑。scope 控制复用范围，yield 之后的代码负责逆序释放资源。",
            """```python
@pytest.fixture
def client(app):
    with TestClient(app) as value:
        yield value
```""",
            ["Fixture 名称表达能力而不是实现细节。", "测试之间避免共享可变状态。", "数据库测试使用事务回滚或独立临时库。"],
            "把大量无关准备塞进 autouse Fixture，会隐藏测试前置条件并增加执行时间。",
            "pytest Fixtures", "https://docs.pytest.org/en/stable/how-to/fixtures.html",
        ),
    ),
    (
        "pub_docker_multistage",
        "Docker 多阶段构建与最小运行镜像",
        technical_article(
            "Docker 多阶段构建与最小运行镜像",
            "多阶段构建使用多个 FROM，把编译工具和依赖留在构建阶段，只复制运行所需产物到最终镜像，从而减小体积和攻击面。",
            """```dockerfile
FROM node:22 AS build
WORKDIR /app
COPY . .
RUN npm ci && npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
```""",
            ["按变化频率安排 COPY 以利用层缓存。", "最终阶段使用非 root 用户。", "固定基础镜像版本并持续扫描重建。"],
            "多阶段构建不会自动删除复制进最终阶段的 Secret；构建凭据应使用专用 secret mount。",
            "Docker Multi-stage Builds", "https://docs.docker.com/build/building/multi-stage/",
        ),
    ),
])


def main() -> int:
    store = Store(settings.sqlalchemy_url(), create_schema=False)
    try:
        admin = store.get_user_by_username(settings.admin_username)
        if not admin:
            store.ensure_admin(
                username=settings.admin_username, email=settings.admin_email,
                password_hash=hash_password(settings.admin_password),
            )
            admin = store.get_user_by_username(settings.admin_username)
        if not admin:
            raise RuntimeError("administrator bootstrap failed")
        created = 0
        for document_id, title, markdown in ARTICLES:
            if store.get_document(admin["id"], document_id):
                continue
            store.create_public_document(
                admin["id"], document_id=document_id, title=title, markdown=markdown,
            )
            created += 1
        print(f"Public knowledge articles ready: {len(ARTICLES)} (created: {created})")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
