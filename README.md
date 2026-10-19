# 剧镜 · AI 剧本杀

剧镜是由 AI 角色 Agent 驱动的悬疑推理 Web 项目。玩家从剧本库选择案件和一个角色，DM 与其他角色共同推进调查、搜证、秘密询问、阶段投票和最终指认。剧本创作有独立的导入、AI 草稿、编辑、审稿与发布流程。

当前以悬疑推理和 `deduction` 模式为主。Windows 启动器启动本地服务并打开浏览器，前端由 FastAPI 同源托管。

## 界面预览

以下为当前 Web 界面的实际截图，使用独立 Echo 演示数据。点击图片可查看原图。

### 登录入口

![剧镜登录入口](media/screenshots/01-login.jpg)

### 剧本库

![剧本库与案件预览](media/screenshots/02-script-library.jpg)

### 角色选择

![选择玩家角色](media/screenshots/04-role-selection.jpg)

### 调查界面

![公开询问、现场搜证与角色 Agent](media/screenshots/06-investigation.jpg)

<details>
<summary>更多界面：剧本详情、第一幕开场与剧本创作</summary>

### 剧本详情

![剧本详情与入场准备](media/screenshots/03-case-detail.jpg)

### 第一幕开场

![DM 主持第一幕开场](media/screenshots/05-dm-opening.jpg)

### 剧本创作

![剧本导入与发布入口](media/screenshots/07-script-creator.jpg)

</details>

## 当前能力

- 案件与角色：六个内置案件，独立游戏编号、剧本版本和工作流快照；全剧开幕、选角、私人剧本与逐幕调查。
- 多 Agent：LangGraph 编排 DM 和角色，原生 Function Calling 通过工具网关校验权限；角色持有独立任务、记忆和私有线索。
- 调查与结局：公开交流、搜证、私聊、线索披露、结束投票、阶段结算、最终指认及终局角色审计。
- 创作与档案：JSON 导入、Schema 与语义校验、AI 创作任务和发布；按用户隔离案件、手记、事件与调用日志，支持暂停和恢复。
- 技术栈：Vue 3、Vue Router、Pinia、TanStack Query、TypeScript、Vite；FastAPI、Pydantic、SQLite、LangGraph。
- 模型接入：Echo 离线模式和 OpenAI-compatible API。离线回归、历史真实模型验收和当前模型质量分别记录。

内置推理案件为《雾港档案·钟楼夜宴》《雨夜来信》《末班列车》《深海回声》《旧宅回廊》《无声剧院》。《西游记·火焰山》作为旧叙事样例保留，不加入推理剧本库。来源信息见各剧本的 `script_meta.provenance`；旧样例未登记的来源不作补充推定。

## 源码部署（Windows）

以下 PowerShell 命令均从仓库根目录执行。需要 Python 3.10+、Node.js 22.12+ 和 npm。

### 1. 安装依赖并构建前端

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
```

生产构建生成 `frontend/app.js`、`frontend/app.css`，并更新 HTML 内的资源版本号。`frontend/.build/` 是中间产物；日常修改在 `frontend/src/` 中完成，构建后再访问后端服务。

### 2. 创建本地配置

```powershell
if (-not (Test-Path backend\config\.env)) {
    Copy-Item backend\config\.env.example backend\config\.env
}
```

模板默认 `LLM_PROVIDER=echo`，无需密钥即可调试流程。已有 `.env` 请按[配置模板](backend/config/.env.example)补充所需项，保留自己的密钥和连接配置。

### 3. 启动服务

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend\app --host 127.0.0.1 --port 8000 --workers 1
```

打开[应用首页](http://127.0.0.1:8000/)，使用[健康检查](http://127.0.0.1:8000/health)确认服务返回 `{"status":"ok"}`。生产资源由同一服务的 `/static/` 提供。

Windows 也可双击根目录的 [start-local.bat](start-local.bat)。它优先使用 `.venv` 中的 Python，启动本地 Web 服务后打开默认浏览器；关闭启动窗口会停止其启动的服务。

### 4. 部署验收

服务启动后，在另一个 PowerShell 终端检查健康状态和页面资源：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
@('/', '/static/app.js', '/static/app.css', '/static/styles.css') | ForEach-Object {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000$_" -UseBasicParsing
    '{0}: {1}' -f $_, $response.StatusCode
}
```

健康检查应返回 `status: ok`，四个页面或资源请求均应为 `200`。随后在浏览器注册或登录，确认剧本库可打开、能选角并进入调查。`/health` 只检查应用可响应；真实模型连通性、游戏效果和部署负载需要另外验证。

### 前端热更新

保持后端 8000 端口运行，在另一个终端执行：

```powershell
npm.cmd --prefix frontend run dev
```

访问 Vite 输出的地址（默认 5173）。开发代理将 `/api`、`/ws` 和 `/static/assets` 转发到 `127.0.0.1:8000`；如果改动后端端口，也需调整 [vite.config.ts](frontend/vite.config.ts) 中的代理目标。

## 环境配置

后端默认读取 `backend/config/.env`，**进程环境变量优先**，修改后需重启服务。全部变量、默认值及注释参考见 [backend/config/.env.example](backend/config/.env.example)。

### 模型 API

在本机 `.env` 中配置兼容服务，例如：

```dotenv
LLM_PROVIDER=openai_compatible
LLM_MODEL=your-model-id
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=your-api-key
LLM_TIMEOUT_SECONDS=120
```

客户端在 `LLM_BASE_URL` 后追加 `/chat/completions`。根地址是否包含 `/v1` 取决于供应商接口，不要填写完整请求路径。模板同时保留本地 Ollama 的连接参考；实际使用时需替换模型名、地址和密钥。

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `LLM_CONTEXT_WINDOW` | `32768` | 应用侧配置窗口 |
| `LLM_INPUT_TOKEN_LIMIT` | `23000` | 输入预算上限 |
| `LLM_MAX_OUTPUT_TOKENS` | `8192` | 输出预留 |
| `LLM_TOKEN_SAFETY_MARGIN` | `1024` | 安全余量 |
| `LLM_REASONING_EFFORT` | 留空 | 可选供应商参数 |

输入上限、输出预留和安全余量之和不得超过配置窗口。输入采用 UTF-8 字节保守估算，实际 usage 独立记录；配置窗口不会自动识别模型真实容量。调查期 Agent 自主行动会产生模型调用，频率和每幕上限还受剧本 `investigation.autonomy` 配置控制。

### Cookie 与监听地址

`APP_ENV=production` 且未显式设置 `COOKIE_SECURE` 时，后端自动启用 Secure Cookie。生产环境使用 HTTPS；本地 HTTP 开发保留 `APP_ENV=development`。使用 Cookie 会话的已认证写操作同时校验 CSRF token。

启动器在读取 `.env` 前决定监听地址和端口，因此 `APP_HOST`、`APP_PORT` 应在启动前设为**进程环境变量**：

```powershell
$env:APP_HOST = '127.0.0.1'
$env:APP_PORT = '8000'
.\start-local.bat
```

直接使用 uvicorn 时，以命令行 `--host`、`--port` 为准。

### 配置文件与数据路径

| 用途 | 源码运行 | PyInstaller 打包运行 |
| --- | --- | --- |
| 默认配置文件 | `backend/config/.env` | `<数据目录>/config/.env` |
| 默认数据库 | `backend/data/app.db` | `%LOCALAPPDATA%/AIMurderMystery/app.db` |
| 工作流配置 | `backend/config/workflow.yaml` | 包内 `backend/config/workflow.yaml` |

游戏工作流还会使用同一数据目录中的 `app.workflow.db`。数据目录需要当前运行账户具有写权限，迁移和备份应覆盖整个目录。

可在启动前设置 `AI_MURDER_MYSTERY_ENV_FILE` 指定另一份配置文件，或设置 `AI_MURDER_MYSTERY_DATA_DIR` 指定数据目录；建议使用绝对路径。配置位置在导入时确定，把 `AI_MURDER_MYSTERY_ENV_FILE` 写进 `.env` 不会切换本次读取的文件。打包时要从自定义数据目录读取 `config/.env`，也需提前设置数据目录环境变量。

真实密钥保存在本机 `.env` 或独立配置文件中。`.env` 及其本地变体、运行数据和本地归档均由 Git 忽略，`.env.example` 作为无真实凭据的参考文件保留。

### 游戏工作流

[backend/config/workflow.yaml](backend/config/workflow.yaml) 管理游戏回合额度、工具调用次数、连接恢复和模型参数。调整前确认所用服务商支持相应参数，并评估模型调用额度。

工作流中非空 `reasoning_effort` 优先于环境变量，当前为 `none`；服务商需要支持该参数。每局保存创建时的工作流快照，修改 YAML 只影响后续创建的游戏。兼容路径 `validated_action_json` 显式配置，不静默降级。

## 目录结构与命名

```text
RolePlayingGame/
├── backend/
│   ├── app/                    # FastAPI、领域规则及 Agent 实现
│   ├── config/                 # .env.example、workflow.yaml 与本机 .env
│   ├── resources/              # 内置剧本与 JSON Schema
│   ├── tests/                  # 单元、集成测试及 fixtures
│   ├── verification/           # 专项检查与人工验收工具
│   ├── reports/                # 本地生成报告，默认忽略
│   ├── data/                   # 本地运行数据，忽略
│   └── requirements.txt
├── frontend/
│   ├── src/                    # Vue/TypeScript 源码、页面样式及测试
│   │   ├── components/         # 页面与共享组件
│   │   ├── queries/            # 服务端状态与查询
│   │   ├── stores/             # Pinia 状态
│   │   └── legacy-app.js       # 迁移中的 DOM 交互适配
│   ├── assets/                 # Logo、头像、封面与参考资源
│   ├── scripts/                # 构建资源同步工具
│   ├── index.html              # 同源页面入口
│   ├── styles.css              # 既有全局样式
│   └── app.js / app.css        # 构建后的生产入口
├── launcher/                   # 本地 Web 启动器与 Windows 打包脚本
├── private-docs/               # 本地私有资料，忽略，不随代码分发
├── logs/                       # 本地服务日志，忽略
├── .local/                     # 本地归档与私有文件，忽略
├── build/ / dist/              # 打包中间产物与发行目录，忽略
├── start-local.bat             # Windows 双击启动本地 Web 服务
└── README.md
```

| 文件类型 | 命名规范 |
| --- | --- |
| 文档、CSS、TS/JS 模块和普通资源 | 小写英文 `kebab-case` |
| Python 模块、测试、剧本 ID | `snake_case`，测试使用 `test_*.py` |
| Vue 组件 | `PascalCase.vue`，对应测试 `PascalCase.test.ts` |
| PowerShell、批处理入口 | 小写英文 `kebab-case` |
| 开发记录与新增验收批次 | `YYYY-MM-DD-topic.md` 或 `YYYY-MM-DD/topic/` |
| 文档索引 | `README.md` |

文档正文继续使用中文，既有模块名和剧本 ID 保持其接口含义。历史设计和验收资料集中保留在本地 `private-docs/`，不影响部署。

2026-10-19 整理时，嵌套的 `Projects/RolePlayingGame/` 快照及根目录旧 `data/` 已完整保留到 `.local/archive/2026-10-19/`；当前运行数据库仍在 `backend/data/`。旧 `backend/test_reports/` 整体迁为 `backend/reports/`，根服务日志集中到 `logs/`。

## 测试与验证

```powershell
.\.venv\Scripts\python.exe -m backend.tests.run_isolated --report backend/reports/backend-regression.json
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
node --check frontend/app.js
```

后端隔离入口使用临时数据库并强制 Echo，避免写入日常案件或调用付费模型。单项回归可增加 `--pattern test_script_schema.py`。报告用途和命名见 [backend/reports/README.md](backend/reports/README.md)。

`backend/verification/` 中的专项工具各有参数和数据要求，部分会调用真实模型或启动独立服务。默认回归无需私有文档；人工专项检查可能依赖本机保存的验收数据。自动化通过不等于真实模型整局叙事质量、成本或生产负载通过。

## Windows 本地 Web 启动器打包

Windows 打包版启动本地服务并打开系统默认浏览器。它使用浏览器承载界面，尚未提供独立桌面窗口。

在已安装项目依赖的环境中执行：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
powershell -ExecutionPolicy Bypass -File launcher/build-windows-exe.ps1
```

构建脚本先安装前端依赖并构建资源，再调用 PyInstaller。已安装且无需重新安装 npm 依赖时可增加 `-SkipDependencyInstall`。发行入口为 `dist/JujingLauncher/JujingLauncher.exe`，分发时保留同目录的 `_internal`；本机 `.env` 不打入发行包。

分发整个 `dist/JujingLauncher/` 目录，接收方解压后双击 EXE。默认 Echo 模式可直接试运行；接入模型服务时，在接收方的 `%LOCALAPPDATA%/AIMurderMystery/config/.env` 中参照公开的 `.env.example` 填写配置，或在启动前设置 `AI_MURDER_MYSTERY_ENV_FILE` 指向独立配置。不要分发开发者本机的密钥、数据库或私有文档。

数据目录名 `AIMurderMystery` 与 `AI_MURDER_MYSTERY_*` 环境变量继续保留，用于兼容已有配置和案件；启动器名称调整不会迁移或重置用户数据。

## 部署注意事项

- **单进程运行**：使用 `--workers 1`。游戏会话、WebSocket 连接和创作任务包含进程内状态；避免同时启动多个实例指向同一数据目录。日常使用不要开启 `--reload`，代码重载会中断正在进行的任务。
- **前端资源更新**：修改前端源码后重新执行 `npm.cmd --prefix frontend run build`，并一起更新 `index.html`、`app.js`、`app.css`、`styles.css` 和 `assets/`。HTML 的版本号由构建工具生成。Windows 发行包需重新构建。
- **模型配置与费用**：初次部署先使用 Echo 检查流程，再配置真实模型。确认模型 ID、API 根地址、工具调用及 `reasoning_effort` 参数兼容；API 地址会自动追加 `/chat/completions`。角色自主行动也会产生付费请求，按剧本与工作流配置控制频率和额度。
- **配置与端口**：进程环境变量优先于 `.env`，修改后重启服务。启动器端口需通过进程环境变量指定；直接使用 uvicorn 时使用 `--port`。Vite 开发代理默认指向后端 8000 端口。先确认端口占用情况，保持同一服务只启动一次。
- **对外访问**：当前启动命令提供本机 HTTP 服务。对外部署需通过支持 WebSocket 升级和长连接的 HTTPS 反向代理，在同一域名下转发页面、`/static/`、`/api/` 和 `/ws/`；保持后端监听本机地址。使用 `APP_ENV=production` 和 Secure Cookie，并在实际 HTTPS 地址检查登录与实时连接。仓库未附带反向代理、证书或系统服务配置。
- **备份与升级**：暂停游戏、停止服务后备份整个实际数据目录，包括 `app.db`、`app.workflow.db` 及目录内其他运行文件；另行妥善备份私有 `.env` 和当前 `workflow.yaml`。升级前完成备份，升级后重新安装依赖、构建前端并执行部署验收。恢复数据时也应先停服。
- **提交与分发范围**：真实密钥、SSH 私钥、数据库、日志、生成报告和内部设计资料仅本地保存。`.gitignore` 负责排除指定文件，已进入 Git 历史的内容不会因此消失。开源源码仍会展示实际实现，请按计划公开的范围检查提交内容。

## 剧本与接口

新剧本使用 UTF-8 JSON，显式声明 `schema_version: "1.0"`。类型定义位于 [script_schema.py](backend/app/loader/script_schema.py)，导出的 [JSON Schema](backend/resources/schema/script.schema.json) 也可登录后通过 `GET /api/v1/scripts/schema` 获取。导入、AI 创作、发布和开局共用服务端结构及语义校验。

内置完整样例见 [fog_harbor_clocktower.json](backend/resources/scripts/fog_harbor_clocktower.json)。剧本包含角色逐幕知识、个人任务、`stage_flow`、线索机制、真相时间线和 `truth.evidence_chain`；聊天、手记、投票和运行事件保存在每局数据中。

| 接口 | 用途 |
| --- | --- |
| `GET /health` | 健康检查 |
| `/api/v1/auth/*`、`GET /api/v1/me` | 注册、登录、会话与 CSRF |
| `GET /api/v1/scripts`、`POST /api/v1/scripts/inspect` | 剧本库与导入校验 |
| `POST /api/v1/game-preparations`、`POST /api/v1/games/{game_id}/activate` | 创建游戏准备与选角开局 |
| `/api/v1/authoring-jobs`、`/api/v1/authoring-jobs/{job_id}/*` | AI 创作、查询、取消与发布 |
| `/api/v1/games`、`/api/v1/games/{game_id}/*` | 案件、手记、事件、暂停、导出与终局记录 |
| `POST /api/v1/games/{game_id}/ws-ticket` | 一次性 WebSocket 票据 |
| `WS /ws/v1/games/{game_id}` | 版本化局内通信与事件续传 |

运行后可在 [OpenAPI 文档](http://127.0.0.1:8000/docs)查看具体方法、参数和响应。v1 错误统一包含 `code`、`message`、`request_id` 和 `details`；WebSocket 使用命令请求 ID 和递增事件 ID 协调幂等与续传。

## 本地私有资料

`private-docs/` 统一保存需求与路线图、架构设计、UI 概念与生成提示词、开发复盘、工程评估、验收截图和模型运行证据。该目录已由 `.gitignore` 排除，不随开源仓库克隆或发行包分发；本机索引位于 `private-docs/README.md`。

公开使用和部署以本 README、[环境变量示例](backend/config/.env.example)、[工作流配置](backend/config/workflow.yaml)、[剧本 Schema](backend/resources/schema/script.schema.json)及运行后的 OpenAPI 文档为准。
