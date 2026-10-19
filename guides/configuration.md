# 配置指南

[返回 README](../README.md) · [部署与维护](deployment.md) · [开发指南](development.md)

本指南说明公开配置项、模型接入和数据路径。以下命令均从仓库根目录执行；配置模板中的地址和密钥均为示例，请将真实凭据保存在自己的私有配置文件中。

## 选择配置文件

| 运行方式 | 公开模板 | 实际配置来源 | 修改后生效方式 |
| --- | --- | --- | --- |
| 源码运行 | [backend/config/.env.example](../backend/config/.env.example) | `backend/config/.env` | 重启服务 |
| Docker Compose | [docker.env.example](../docker.env.example) | 根目录 `docker.env` 注入容器环境 | 重建容器 |
| Windows 打包版 | [backend/config/.env.example](../backend/config/.env.example) | `<数据目录>/config/.env` | 重启启动器 |

源码及打包运行时，**进程环境变量优先于 `.env`**。遇到修改文件后配置未变化的情况，先检查启动终端或服务管理器中是否已经设置同名变量。不要覆盖已有私有配置文件；按模板补充需要的字段即可。

Docker 默认无需配置文件即可使用 Echo。需要自定义时复制 `docker.env.example` 为 `docker.env`，编辑后执行：

```shell
docker compose --env-file docker.env up -d --build --wait
```

这里的 `--env-file docker.env` 为 Compose 的端口等插值提供配置；服务的 `env_file` 将同一文件中的应用变量注入容器。后续管理命令也保留 `--env-file docker.env`，确保使用相同的发布端口。Compose 显式声明的数据目录固定为 `/data`。

修改 `docker.env` 后，单独 `restart` 不会载入新的容器环境，需执行：

```shell
docker compose --env-file docker.env up -d --force-recreate --wait
```

若要从仓库外读取 Docker 配置，在运行命令前将进程变量 `JUJING_ENV_FILE` 设为私有文件路径，并将 `--env-file` 指向同一文件。不要把 `JUJING_ENV_FILE` 写入配置文件来切换文件自身。完整操作见[部署与维护](deployment.md)。

## 模型接入

### Echo 模式

```dotenv
LLM_PROVIDER=echo
```

Echo 不发送外部模型请求，适合检查页面、账号、游戏流程和部署配置；它不能用于评价真实模型的推理、叙事效果或费用。模板中的其他模型连接字段只有切换到 `openai_compatible` 后才用于 API 调用。

### OpenAI-compatible API

在所选部署方式的私有配置文件中填写：

```dotenv
LLM_PROVIDER=openai_compatible
LLM_MODEL=your-model-id
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=your-api-key
LLM_TIMEOUT_SECONDS=120
```

客户端会在 `LLM_BASE_URL` 后追加 `/chat/completions`。根地址是否包含 `/v1` 以服务商说明为准，不要填写完整的 `/chat/completions` 请求路径。确认服务支持所用模型、输出额度、工具调用和 `reasoning_effort` 参数；仅能正常聊天不足以证明游戏工具回合兼容。

本地 Ollama 的连接参考如下，模型名需替换为已经部署的实际模型：

```dotenv
LLM_PROVIDER=openai_compatible
LLM_MODEL=qwen3-32b
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
```

Docker 访问宿主机模型时，将上述地址改为 `http://host.docker.internal:11434/v1`；Compose 已配置对应宿主机网关。容器内的 `localhost` 指向容器自身，宿主模型还需监听容器可达的地址，并允许 Docker 网络访问。`ollama` 是示例占位值，不代表远程服务的真实密钥。

### 模型配置与预算

以下为应用默认值；Docker 镜像将 `LLM_BASE_URL` 默认值改为宿主机网关地址。

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `LLM_PROVIDER` | `echo` | `echo` 或 `openai_compatible` |
| `LLM_MODEL` | `qwen3-32b` | 模型 ID，需与服务商或本地部署一致 |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | API 根地址；Docker 默认使用 `host.docker.internal` |
| `LLM_API_KEY` | `ollama` | 示例占位；远程服务按需提供真实密钥 |
| `LLM_TIMEOUT_SECONDS` | `120` | 单次模型请求的总等待上限，单位为秒 |
| `LLM_CONTEXT_WINDOW` | `32768` | 应用侧配置的上下文总窗口 |
| `LLM_INPUT_TOKEN_LIMIT` | `23000` | 输入预算上限 |
| `LLM_MAX_OUTPUT_TOKENS` | `8192` | 输出预留，同时作为请求的 `max_tokens` |
| `LLM_TOKEN_SAFETY_MARGIN` | `1024` | 安全余量 |
| `LLM_REASONING_EFFORT` | 留空 | 可选供应商参数，非空值需由所用 API 支持 |

四项预算必须为正整数，并满足：

```text
输入上限 + 输出预留 + 安全余量 <= 上下文总窗口
```

输入预算采用 UTF-8 字节保守估算，服务商返回的实际 token 用量另行记录。配置窗口不会自动识别模型的真实容量，也不会改变服务商的模型容量。遇到必要上下文超限，应按模型容量调整预算或缩短输入；输出被截断时也需检查输出额度。

游戏内工作流的非空 `reasoning_effort` 会覆盖环境变量，AI 创作流程也可使用自己的覆盖值。当前[工作流配置](../backend/config/workflow.yaml)为 `none`；若服务不接受该参数，需一并检查 YAML，单独将环境变量留空可能仍会发送该字段。

角色自主行动、DM 主持及剧本创作都可能产生模型调用。每回合调用上限和剧本的 `investigation.autonomy` 配置会影响调用频率，它们不等同于整局费用上限；接入付费模型后应结合实际用量和服务商账单评估成本。

## 应用环境、Cookie 与端口

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_TITLE` | `剧镜 · AI 剧本杀` | 后端应用标题 |
| `APP_ENV` | `development` | 对外 HTTPS 部署使用 `production` |
| `COOKIE_SECURE` | 根据 `APP_ENV` 决定 | 未设置时，`production` 自动启用 Secure Cookie |
| `APP_HOST` | `127.0.0.1` | 仅由本地 Web 启动器读取，须提前设为进程变量 |
| `APP_PORT` | `8000` | 仅由本地 Web 启动器读取，须提前设为进程变量 |
| `JUJING_BIND_ADDRESS` | `127.0.0.1` | Docker Compose 的宿主机发布地址 |
| `JUJING_PORT` | `8000` | Docker Compose 的宿主机发布端口 |

`COOKIE_SECURE=true` 要求浏览器通过 HTTPS 发送会话 Cookie，本地 HTTP 试运行保留 `APP_ENV=development`。使用 Cookie 会话的已认证写操作还会校验 CSRF token。对外部署需配置 HTTPS、WebSocket 转发并在实际域名检查登录和局内连接，见[部署与维护](deployment.md)。

启动器在加载 `.env` 前决定监听地址和端口，因此在 `.env` 中填写 `APP_HOST`、`APP_PORT` 不会改变该次启动的监听配置。PowerShell 示例：

```powershell
$env:APP_HOST = '127.0.0.1'
$env:APP_PORT = '8000'
.\start-local.bat
```

直接启动 Uvicorn 时，以命令行 `--host`、`--port` 为准。Docker 容器内固定监听 `0.0.0.0:8000`，通过 `JUJING_BIND_ADDRESS`、`JUJING_PORT` 调整宿主机发布方式，`APP_HOST`、`APP_PORT` 不改变这一行为。

## 配置文件与数据目录

| 用途 | 源码运行 | Docker Compose | Windows 打包运行 |
| --- | --- | --- | --- |
| 默认配置来源 | `backend/config/.env` | 宿主机 `docker.env` 注入容器环境 | `<数据目录>/config/.env` |
| 默认数据库 | `backend/data/app.db` | 默认 `jujing_data` 卷内的 `/data/app.db` | `%LOCALAPPDATA%/AIMurderMystery/app.db` |
| 工作流配置 | `backend/config/workflow.yaml` | 镜像内 `/app/backend/config/workflow.yaml` | 包内 `backend/config/workflow.yaml` |

游戏工作流还使用同一数据目录中的 `app.workflow.db`。数据目录须对运行账户可写；迁移和备份覆盖整个实际目录，停服备份方法见[部署与维护](deployment.md)。

源码或打包运行可在启动前设置以下进程变量，建议使用绝对路径：

```powershell
$env:AI_MURDER_MYSTERY_ENV_FILE = 'D:\private\jujing.env'
$env:AI_MURDER_MYSTERY_DATA_DIR = 'D:\jujing-data'
.\start-local.bat
```

- `AI_MURDER_MYSTERY_ENV_FILE`：指定要读取的配置文件。位置在模块导入时确定，把该变量写在 `.env` 内无法切换本次读取的文件。
- `AI_MURDER_MYSTERY_DATA_DIR`：指定运行数据目录。若打包版需要从 `<自定义数据目录>/config/.env` 加载配置，必须在启动前设置；在 `.env` 中设置只能影响后续数据路径选择。
- Docker 使用固定 `/data` 卷和容器环境，宿主机配置文件路径不会自动进入容器，不要在 `docker.env` 中另设宿主机数据路径。

`AIMurderMystery` 目录名和 `AI_MURDER_MYSTERY_*` 变量用于兼容已有配置及案件；Windows 本地 Web 启动器的名称不会改变现有数据位置。

真实密钥保存在本机 `.env`、`docker.env` 或独立私有文件中。仓库内的默认本地配置和运行数据已由 Git 忽略；自定义配置若放在其他位置，请自行确认其版本控制与分发范围。公开模板保留示例值。

## 游戏工作流

[backend/config/workflow.yaml](../backend/config/workflow.yaml) 管理游戏回合额度、工具调用次数、连接恢复和模型参数。公开字段定义见 [workflow_config.py](../backend/app/workflow_config.py)，修改前确认数值范围和所用模型服务的兼容性。

常用字段如下，数值为当前仓库 YAML 的配置：

| 字段 | 当前值 | 用途 |
| --- | --- | --- |
| `transport` | `native_tools` | 工具调用传输方式 |
| `max_model_requests_per_role_turn` | `4` | 每个角色回合的模型请求上限 |
| `max_tool_calls_per_role_turn` | `3` | 每个角色回合的工具调用上限 |
| `max_rounds_per_role_turn` | `3` | 每个角色回合的执行轮数上限 |
| `max_public_responders` | `3` | 公开回应角色数量上限 |
| `model_hosting` | `true` | 使用模型主持 |
| `reasoning_effort` | `none` | 游戏模型调用的参数覆盖值 |

默认使用原生工具调用；需要兼容路径时显式设置 `transport: validated_action_json`，不会因接口不兼容而静默降级。保持 `concurrency: 1` 和 `automatic_retries: 0`，这两个字段只接受当前值。应用单实例、单 worker 的部署限制见[部署与维护](deployment.md)。

源码运行修改 YAML 后重启服务；Docker 在构建时复制该文件，修改后执行：

```shell
docker compose --env-file docker.env up -d --build --wait
```

每局保存创建时的工作流快照。重启或重建后，新配置用于后续创建的游戏，已有游戏继续使用自己的快照。
