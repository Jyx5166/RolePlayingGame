# 开发与接口指南

[返回项目首页](../README.md) · [部署与维护](../guides/deployment.md) · [环境配置](../guides/configuration.md)

本指南介绍源码布局、前端开发、回归验证、Windows 启动器打包和公开接口。以下命令从仓库根目录执行，Windows 示例使用 PowerShell。首次安装依赖和启动后端，请先完成[源码部署](../guides/deployment.md)。

## 源码目录与命名

```text
RolePlayingGame/
├── backend/
│   ├── app/                    # FastAPI 服务、游戏规则与 Agent 实现
│   ├── config/                 # 公开环境变量模板与 workflow.yaml
│   ├── resources/              # 内置剧本和 JSON Schema
│   ├── tests/                  # 后端测试与 fixtures
│   ├── verification/           # 专项检查工具
│   └── requirements.txt
├── frontend/
│   ├── src/                    # Vue / TypeScript 源码与组件测试
│   │   ├── components/         # 页面与共享组件
│   │   ├── queries/            # 服务端数据查询
│   │   ├── stores/             # Pinia 状态
│   │   └── legacy-app.js       # 既有 DOM 交互适配
│   ├── assets/                 # Logo、头像和案件封面等静态资源
│   ├── scripts/                # 构建资源同步工具
│   ├── index.html              # 同源页面入口
│   ├── styles.css              # 全局样式
│   └── app.js / app.css        # 构建后的生产入口
├── launcher/                   # 本地 Web 启动器与 Windows 打包脚本
├── guides/                     # 公开使用与开发指南
├── media/screenshots/          # README 界面截图
├── Dockerfile
├── compose.yaml
├── docker.env.example          # Docker 配置模板
├── start-local.bat             # Windows 本地 Web 启动入口
└── README.md
```

新增文件遵循以下约定，已有模块名和剧本 ID 保持接口兼容：

| 文件类型 | 命名约定 |
| --- | --- |
| 普通文档、CSS、TS/JS 模块和资源 | 小写英文 `kebab-case` |
| Python 模块、测试和剧本 ID | `snake_case`；测试使用 `test_*.py` |
| Vue 组件及对应测试 | `PascalCase.vue`、`PascalCase.test.ts` |
| PowerShell 与批处理入口 | 小写英文 `kebab-case` |
| 带日期的记录或验收批次 | `YYYY-MM-DD-topic.md` 或 `YYYY-MM-DD/topic/` |
| 目录说明入口 | `README.md` |

### Agent 与游戏运行模块

`backend/app/` 中的相关模块按以下职责组织：

| 目录 | 职责与主要文件 |
| --- | --- |
| `agent/` | `instance.py`、`pool.py` 管理角色实例；`context.py` 构造授权上下文；`director.py` 处理 DM 模型决策；`execution.py`、`action.py`、`autonomy.py` 处理角色调用与行为。 |
| `memory/` | `selection.py` 选择、整理预算内的记忆与对话输入；`archive.py` 保存记忆原文、摘要和检索索引，并提供分段读取。 |
| `llm/` | `base.py`、`factory.py`、`openai_compatible.py`、`echo.py` 提供统一模型接入；`budget.py` 管理上下文预算；`tools.py` 处理模型侧工具调用格式。 |
| `tools/` | `contracts.py` 定义工具参数和结果；`gateway.py` 校验权限、运行范围与预算并提交收据；`domain.py` 将工具提案转为游戏操作。 |
| `workflow/` | `state.py` 定义图过程状态；`actor_graph.py` 实现单个行动者的模型与工具循环；`director_graph.py` 实现外层调度和 `GameWorkflow` 请求入口。 |
| `runtime/` | `contracts.py` 定义运行范围和回合标识；`store.py` 记录运行批次与调用；`models.py` 包装模型执行；`leases.py` 管理控制权与心跳；`decisions.py` 校验结构化控制决策。 |
| `dm/` | `engine.py` 组合游戏引擎；其余模块负责信息权限、轮次、发言校验、任务检查和终局复盘。 |
| `domain/` | `state.py` 保存游戏事实；其余模块实现场景流转、交互、结算、事件记录与状态快照。 |
| `mechanics/` | `base.py` 定义玩法接口；`search.py` 实现游戏搜证；`whisper.py` 实现私聊。 |

业务代码从 `memory.selection`、`memory.archive` 和 `workflow` 导入对应能力。原 `agent.memory`、`agent.archive` 和 `runtime.workflow` 保留薄兼容出口，共用同一实现，不维护第二套逻辑。

角色私有状态由 Agent 实例持有，记忆模块负责存取与输入选择；游戏事实状态、图过程状态和运行调用记录分别归属 `domain`、`workflow`、`runtime`。模型提出的行动统一经过工具网关和游戏规则层，角色记忆不会直接替代游戏事实。

## 前端开发与构建

### 热更新

保持后端在 `127.0.0.1:8000` 运行，在另一个终端执行：

```powershell
npm.cmd --prefix frontend run dev
```

访问 Vite 输出的地址，默认端口为 `5173`；端口占用时 Vite 会尝试其他端口。开发代理将 `/api`、`/ws` 和 `/static/assets` 转发到后端。后端端口变更后，也需修改 [vite.config.ts](../frontend/vite.config.ts) 中的代理目标。

页面、交互与组件样式主要在 `frontend/src/` 中修改，既有全局样式位于 `frontend/styles.css`。开发服务器和后端是两个进程，日常游戏只保持一个后端实例。

### 生产资源

```powershell
npm.cmd --prefix frontend run build
```

构建会先写入 `frontend/.build/`，再由 [sync-build.mjs](../frontend/scripts/sync-build.mjs) 同步 `app.js`、`app.js.map`、`app.css`，并更新 `index.html` 中 `app.js`、`app.css` 和 `styles.css` 的内容版本号。不要手动编辑生成的 JS/CSS 或资源版本号。

源码部署时，FastAPI 从 `/static/` 提供生产资源。更新前端时应一起部署 `index.html`、`app.js`、`app.css`、`styles.css` 和 `assets/`；Docker 镜像及 Windows 发行包需要重新构建。

## 测试与验证

已安装依赖后，可运行：

```powershell
.\.venv\Scripts\python.exe -m backend.tests.run_isolated --report backend/reports/backend-regression.json
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
node --check frontend/app.js
```

后端 [run_isolated.py](../backend/tests/run_isolated.py) 使用临时数据目录，强制 `LLM_PROVIDER=echo`，在运行结束后清理临时数据库；`--report` 生成本地 JSON 结果。单项回归可以指定文件匹配规则：

```powershell
.\.venv\Scripts\python.exe -m backend.tests.run_isolated --pattern test_script_schema.py
```

前端 `test` 执行 Vitest，`typecheck` 检查 TypeScript，`build` 验证构建与资源同步，`node --check` 检查生成 JS 的语法。它们分别覆盖不同范围，不能互相替代。

`backend/verification/` 中的工具各有参数与数据要求，部分会启动独立服务或调用真实模型，运行前应阅读相应脚本。自动化回归通过不等于真实模型整局质量、模型费用或生产负载已完成验证。部署后的页面、登录、局内连接和数据恢复检查见[部署与维护](../guides/deployment.md)。

## Windows 本地 Web 启动器打包

Windows 启动器启动本机 Web 服务，并打开系统默认浏览器。界面由浏览器承载，目前没有独立桌面窗口。

在已安装项目 Python 依赖、Node.js 和 npm 的 Windows 环境中执行：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
powershell -ExecutionPolicy Bypass -File launcher/build-windows-exe.ps1
```

[构建脚本](../launcher/build-windows-exe.ps1) 优先使用项目 `.venv` 中的 Python，先运行 `npm ci` 和前端生产构建，再执行 PyInstaller。前端依赖已经安装且锁文件未变时，可以跳过依赖安装：

```powershell
powershell -ExecutionPolicy Bypass -File launcher/build-windows-exe.ps1 -SkipDependencyInstall
```

发行入口为 `dist/JujingLauncher/JujingLauncher.exe`。分发整个 `dist/JujingLauncher/` 目录，保留同目录的 `_internal`；接收方解压后双击 EXE。默认 Echo 模式可用于试运行，启动窗口需要保持开启。

打包脚本只收集应用代码和指定资源，不包含开发者本机的 `.env`。接收方接入模型时，参照[应用环境变量模板](../backend/config/.env.example)，在 `%LOCALAPPDATA%/AIMurderMystery/config/.env` 中创建自己的配置，或在启动前设置 `AI_MURDER_MYSTERY_ENV_FILE` 指定独立配置文件。默认数据目录为 `%LOCALAPPDATA%/AIMurderMystery/`，可通过 `AI_MURDER_MYSTERY_DATA_DIR` 指定其他目录，详见[环境配置](../guides/configuration.md)。

`AIMurderMystery` 数据目录名及 `AI_MURDER_MYSTERY_*` 变量用于配置兼容。打包和分发时只使用发行目录，勿附加本机密钥、数据库、日志或生成报告。

## 剧本格式与 Schema

新剧本使用 UTF-8 JSON，显式声明 `"schema_version": "1.0"`。主要公开参考：

- [Pydantic 类型定义](../backend/app/loader/script_schema.py)：字段、类型和结构约束。
- [JSON Schema](../backend/resources/schema/script.schema.json)：供编辑器及外部工具使用。
- [完整内置样例《雾港档案·钟楼夜宴》](../backend/resources/scripts/fog_harbor_clocktower.json)：角色、逐幕知识、线索、调查机制、`stage_flow` 和真相证据链等字段的组合示例，包含剧透。

登录后可通过 `GET /api/v1/scripts/schema` 获取 Schema。导入、创作发布和开局会执行服务端校验；Schema 合法只代表结构满足约束，仍需关注语义审查结果与实际试玩表现。个人任务等私有角色内容和公开内容的可见性，由剧本字段及服务端规则处理。

## 接口概要

运行后访问 [OpenAPI 文档](http://127.0.0.1:8000/docs) 查看 HTTP 接口的方法、请求结构与响应。更改访问地址或端口后，使用同一服务地址下的 `/docs`，原始定义位于 `/openapi.json`。

| 接口 | 用途 |
| --- | --- |
| `GET /health` | 应用健康检查 |
| `/api/v1/auth/*`、`GET /api/v1/me` | 注册、登录、退出和会话 |
| `GET /api/v1/scripts`、`GET /api/v1/scripts/schema` | 剧本库与公开 Schema |
| `POST /api/v1/scripts/inspect`、`POST /api/v1/scripts` | 剧本校验与发布 |
| `POST /api/v1/game-preparations` | 创建选角前的游戏准备 |
| `POST /api/v1/games/{game_id}/activate` | 选择角色并开局 |
| `/api/v1/authoring-jobs`、`/api/v1/authoring-jobs/{job_id}/*` | 创作任务、状态、取消和发布 |
| `/api/v1/games`、`/api/v1/games/{game_id}/*` | 案件、手记、事件、暂停、记录与导出 |
| `POST /api/v1/games/{game_id}/ws-ticket` | 获取一次性 WebSocket 票据 |
| `WS /ws/v1/games/{game_id}` | 局内实时通信与事件续传 |

多数业务接口要求登录；使用 Cookie 会话的已认证写操作还需要有效 CSRF token。`/api/v1/` 错误响应包含 `code`、`message`、`request_id` 和 `details`。具体认证和请求封装可参考[前端 API 客户端](../frontend/src/api-client.ts)。

WebSocket 不列入 OpenAPI 的 HTTP 操作清单，其客户端消息结构与连接处理分别见 [ws-protocol.ts](../frontend/src/ws-protocol.ts) 和 [game-session.ts](../frontend/src/game-session.ts)。命令使用请求 ID，事件使用递增事件 ID，以支持命令去重和断线续传。
