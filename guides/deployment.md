# 部署指南

[返回项目首页](../README.md) · [配置参考](configuration.md) · [开发与剧本参考](development.md)

本文说明 Docker、Windows 源码部署及日常维护。所有命令均从仓库根目录执行。首次下载项目：

```sh
git clone https://github.com/Jyx5166/RolePlayingGame.git
cd RolePlayingGame
```

## Docker 部署

### 环境与默认启动

需要 Docker Engine，或启用 Linux 容器的 Docker Desktop，以及 Docker Compose **2.24.0+**。宿主机无需安装 Python、Node.js 或 npm；镜像先用 Node.js 22 构建前端，再用 Python 3.11 运行 Web 服务。

```sh
docker compose up -d --build --wait
docker compose ps
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)，注册账号进入剧本库。默认使用 Echo，不需要模型密钥，适合验证流程。首次构建需要联网下载基础镜像和依赖。

默认部署信息：

| 项目 | 默认值 |
| --- | --- |
| Compose 项目 / 服务 | `jujing` / `web` |
| 本地构建镜像 | `jujing-web:local` |
| 宿主机发布地址 | `127.0.0.1:8000` |
| 容器监听地址 | `0.0.0.0:8000` |
| 数据卷 / 容器挂载路径 | `jujing_data` / `/data` |
| 应用用户 / worker 数量 | UID `10001` / `1` |

### 配置模型与端口

将 [docker.env.example](../docker.env.example) 复制为本地 `docker.env`；已有配置请直接编辑，保留自己的连接信息。

Windows PowerShell：

```powershell
if (-not (Test-Path docker.env)) { Copy-Item docker.env.example docker.env }
```

Linux/macOS shell：

```sh
test -f docker.env || cp docker.env.example docker.env
```

例如接入远程模型，并将本机端口改为 `8080`：

```dotenv
JUJING_BIND_ADDRESS=127.0.0.1
JUJING_PORT=8080
LLM_PROVIDER=openai_compatible
LLM_MODEL=your-model-id
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=your-api-key
```

```sh
docker compose --env-file docker.env up -d --build --wait
```

此时访问 `http://127.0.0.1:8080`。API 根地址会自动追加 `/chat/completions`。宿主机 Ollama 等模型服务使用 `http://host.docker.internal:11434/v1`；模型服务需监听容器可达的地址，并允许 Docker 网络访问。容器内的 `localhost` 指向容器自身。

`docker.env` 同时用于 Compose 插值和容器应用配置，后续管理命令应始终带上 `--env-file docker.env`。没有创建该文件的默认试运行，可以省略这个参数。Compose 可选环境文件的版本要求见 [Docker 官方说明](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)。

端口由 `JUJING_BIND_ADDRESS`、`JUJING_PORT` 控制；`APP_HOST`、`APP_PORT` 不改变容器启动命令。数据目录由 Compose 固定为 `/data`。其他模型预算、配置文件位置和环境变量优先级见[配置参考](configuration.md)。

修改环境配置后重建容器，载入新的环境变量：

```sh
docker compose --env-file docker.env up -d --force-recreate --wait
```

单独执行 `restart` 不会更新容器环境。修改源码、前端或 `backend/config/workflow.yaml` 时，需要重新构建镜像。

### 启动验收

`--wait` 会等待应用健康检查通过。也可查看状态、健康接口和日志：

```sh
docker compose --env-file docker.env ps
docker compose --env-file docker.env exec web python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
docker compose --env-file docker.env logs --tail 100 web
```

健康接口应返回 `{"status":"ok"}`。再从宿主机打开实际发布地址，确认：

1. 注册或登录正常，剧本库、图片和页面资源能加载。
2. 能选择角色、进入游戏，完成调查操作。
3. 能保存手记，暂停后恢复案件。
4. 接入真实模型后，能完成实际对话和工具调用。

健康检查只说明应用可响应；Echo 验收不能代替真实模型效果、费用或生产负载验证。

## 源码部署（Windows）

需要 Python 3.10+、Node.js 22.12+ 和 npm。以下使用 PowerShell，从仓库根目录执行。

### 安装依赖并构建前端

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
```

构建生成 `frontend/app.js`、`frontend/app.css` 并更新 HTML 的资源版本号。修改 Vue 源码后需重新构建；热更新方式见[开发指南](development.md#前端开发与构建)。

### 创建配置并启动

```powershell
if (-not (Test-Path backend\config\.env)) {
    Copy-Item backend\config\.env.example backend\config\.env
}
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend\app --host 127.0.0.1 --port 8000 --workers 1
```

模板默认使用 Echo。接入真实模型时，编辑 `backend/config/.env` 后重启服务，参数见[配置参考](configuration.md)。

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。前端页面、生产资源、API 与 WebSocket 由 FastAPI 同源提供。

也可双击根目录的 [start-local.bat](../start-local.bat)。它优先使用 `.venv` 中的 Python，启动服务后打开系统默认浏览器，关闭启动窗口会停止其启动的服务。启动器监听地址与端口的设置方式见[配置参考](configuration.md#应用环境cookie-与端口)。

### 源码部署验收

在另一个 PowerShell 终端执行：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
@('/', '/static/app.js', '/static/app.css', '/static/styles.css') | ForEach-Object {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000$_" -UseBasicParsing
    '{0}: {1}' -f $_, $response.StatusCode
}
```

健康接口应返回 `status: ok`，四个页面或资源请求均应为 `200`。随后按前述 Docker 启动验收流程，在浏览器检查登录、选角和调查操作。

## 对外部署

通过支持 WebSocket 升级和长连接的 HTTPS 反向代理，在同一域名下转发页面、`/static/`、`/api/` 和 `/ws/`。仓库未附带反向代理、证书或系统服务配置。

- 代理运行在宿主机时，可保留应用默认的本机端口绑定。
- 代理运行在另一容器时，将其接入应用网络并转发到 `web:8000`。
- 配置 `APP_ENV=production`、`COOKIE_SECURE=true`，重启源码服务或重建 Docker 容器，在实际 HTTPS 地址验收登录和局内实时连接。
- 需要局域网直接访问时，再调整宿主机发布地址；Docker 对应 `JUJING_BIND_ADDRESS=0.0.0.0`，源码部署对应 `--host 0.0.0.0`，并配合防火墙和访问控制。

保持**一个应用实例和一个 worker**。游戏会话、WebSocket 与创作任务包含进程内状态，当前不能通过增加 worker、扩容 `web` 或多个实例共用数据卷来横向扩展。日常运行关闭 `--reload`，避免重载中断任务。

## 数据备份与恢复

### 备份范围

暂停游戏，完成或取消创作任务，再停止服务。备份整个实际数据目录，包含 `app.db`、`app.workflow.db`、SQLite 伴随文件和其他运行数据；另外保存私有配置及部署所用的 `backend/config/workflow.yaml`。

源码运行默认数据目录是 `backend/data/`；打包版默认是 `%LOCALAPPDATA%/AIMurderMystery/`；Docker 使用命名卷。自定义路径以[配置参考](configuration.md#配置文件与数据目录)为准。服务写入时只复制一个数据库文件，可能得到不一致的备份。

### Docker 备份

下面使用默认项目的 `jujing_data` 卷。在宿主机先创建备份目录，将 `/absolute/path/backup` 替换为实际**绝对路径**，Windows 例如 `D:/Backups/jujing`。备份文件包含用户数据和案件内容。

```sh
docker compose --env-file docker.env stop web
docker run --rm --user 0 --mount type=volume,source=jujing_data,target=/data,readonly --mount type=bind,source=/absolute/path/backup,target=/backup jujing-web:local python -c "import tarfile; archive = tarfile.open('/backup/jujing-data.tar.gz', 'w:gz'); archive.add('/data', arcname='data'); archive.close()"
docker compose --env-file docker.env up -d --wait
```

### Docker 恢复

先停止服务并保存现有数据，在新环境或准备好的**空卷**中恢复。以下命令检测到非空卷会退出，避免混入现有案件；已有卷需先妥善备份，再选择恢复目标。

```sh
docker compose --env-file docker.env stop web
docker volume create jujing_data
docker run --rm --user 0 --mount type=volume,source=jujing_data,target=/data --mount type=bind,source=/absolute/path/backup,target=/backup,readonly jujing-web:local python -c "from pathlib import Path; import tarfile; assert not any(Path('/data').iterdir()), 'Target data volume must be empty'; archive = tarfile.open('/backup/jujing-data.tar.gz', 'r:gz'); archive.extractall('/'); archive.close()"
docker compose --env-file docker.env up -d --wait
```

恢复后检查账号、案件和手记，再恢复正常使用。若启动时通过 `-p` 自定义项目名，后续 Compose 命令应继续使用该项目名，数据卷名也随之改变，先用 `docker volume ls` 核对。原理见 [Docker 卷备份与恢复](https://docs.docker.com/engine/storage/volumes/#back-up-restore-or-migrate-data-volumes)。

## 更新与停止

升级前按上一节停服备份，随后更新仓库代码并重新构建：

```sh
docker compose --env-file docker.env up -d --build --wait
```

源码升级时，停止服务，重新安装依赖、构建前端，再启动并验收。每局保留创建时的工作流快照，修改工作流只影响后续创建的游戏。

临时停止或移除 Docker 应用：

```sh
docker compose --env-file docker.env stop web
docker compose --env-file docker.env down
```

`down` 保留命名数据卷；**增加 `-v` 会删除数据卷**。重建应用容器也会保留卷。备份恢复以整个数据目录为单位。

## 常见问题

| 现象 | 检查方式 |
| --- | --- |
| 首次构建下载失败 | 检查 Docker 的镜像访问与构建网络；基础镜像、npm 和 pip 依赖都需下载 |
| 端口被占用或地址打不开 | 用 `docker compose ps` 核对映射和健康状态，修改 `JUJING_PORT` 后用相同环境文件重建容器；源码部署检查 `--port` |
| 修改模型或端口后没有变化 | 源码服务重启；Docker 使用 `up -d --force-recreate --wait`，并确认 `--env-file` 与启动时一致 |
| 容器无法连接宿主机模型 | 检查 `host.docker.internal`、模型服务监听地址、防火墙及 Docker 网络；API 根地址不包含 `/chat/completions` |
| HTTPS 部署后无法登录或局内连接断开 | 核对 Secure Cookie、实际访问协议、WebSocket 升级、代理长连接配置及同域转发 |
| 模型响应或工具调用报错 | 检查模型 ID、接口根地址、工具调用能力、预算及 `reasoning_effort` 兼容性，详见[配置参考](configuration.md) |
| 源码页面仍显示旧界面 | 重新构建前端，确认 HTML 与 `app.js`、`app.css`、`styles.css`、`assets/` 一起更新 |

真实密钥、运行数据及内部设计资料仅本地保存。公开仓库与镜像使用无真实凭据的模板；`.gitignore` 不会移除已经进入 Git 历史的内容。
