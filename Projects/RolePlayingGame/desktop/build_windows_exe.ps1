$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Npm = Get-Command npm.cmd -ErrorAction Stop
$env:npm_config_cache = "$ProjectRoot\.npm-cache"
Push-Location "$ProjectRoot\frontend"
try {
  & $Npm.Source ci
  if ($LASTEXITCODE -ne 0) {
    throw "前端依赖安装失败，退出码：$LASTEXITCODE"
  }
  & $Npm.Source run build
  if ($LASTEXITCODE -ne 0) {
    throw "前端构建失败，退出码：$LASTEXITCODE"
  }
}
finally {
  Pop-Location
}

python -m PyInstaller `
  --noconfirm `
  --clean `
  --name "AIMurderMysteryDesktop" `
  --paths "$ProjectRoot\backend\app" `
  --add-data "$ProjectRoot\frontend;frontend" `
  --add-data "$ProjectRoot\backend\resources;backend/resources" `
  --workpath "$ProjectRoot\build\pyinstaller" `
  --specpath "$ProjectRoot\build\spec" `
  --distpath "$ProjectRoot\dist" `
  "$ProjectRoot\desktop\desktop_launcher.py"

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller 构建失败，退出码：$LASTEXITCODE"
}
