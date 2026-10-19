param([switch]$SkipDependencyInstall)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Npm = Get-Command npm.cmd -ErrorAction Stop
$env:npm_config_cache = "$ProjectRoot\.npm-cache"
Push-Location "$ProjectRoot\frontend"
try {
  if (-not $SkipDependencyInstall) {
    & $Npm.Source ci
    if ($LASTEXITCODE -ne 0) { throw "前端依赖安装失败，退出码：$LASTEXITCODE" }
  }
  & $Npm.Source run build
  if ($LASTEXITCODE -ne 0) {
    throw "前端构建失败，退出码：$LASTEXITCODE"
  }
}
finally {
  Pop-Location
}

$ProjectPython = if (Test-Path "$ProjectRoot\.venv\Scripts\python.exe") { "$ProjectRoot\.venv\Scripts\python.exe" } else { "python" }
& $ProjectPython -m PyInstaller `
  --noconfirm `
  --clean `
  --name "JujingLauncher" `
  --paths "$ProjectRoot\backend\app" `
  --add-data "$ProjectRoot\frontend\index.html;frontend" `
  --add-data "$ProjectRoot\frontend\styles.css;frontend" `
  --add-data "$ProjectRoot\frontend\app.js;frontend" `
  --add-data "$ProjectRoot\frontend\app.css;frontend" `
  --add-data "$ProjectRoot\frontend\assets;frontend/assets" `
  --add-data "$ProjectRoot\backend\resources;backend/resources" `
  --add-data "$ProjectRoot\backend\config\workflow.yaml;backend/config" `
  --collect-submodules langgraph `
  --collect-submodules langchain_core `
  --collect-submodules mechanics `
  --collect-submodules skill `
  --collect-submodules llm `
  --hidden-import main `
  --workpath "$ProjectRoot\build\pyinstaller" `
  --specpath "$ProjectRoot\build\spec" `
  --distpath "$ProjectRoot\dist" `
  "$ProjectRoot\launcher\windows_launcher.py"

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller 构建失败，退出码：$LASTEXITCODE"
}
