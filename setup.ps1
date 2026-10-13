param([string]$PythonPath = 'python')
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    & $PythonPath -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 이상 설치와 venv 생성 결과를 확인해 주세요.' }
    & '.venv\Scripts\python.exe' -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python 의존성 설치에 실패했습니다.' }
    Push-Location -LiteralPath (Join-Path $PSScriptRoot 'frontend')
    try {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw '화면 의존성 설치에 실패했습니다.' }
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw '화면 빌드에 실패했습니다.' }
    } finally { Pop-Location }
    Write-Host '설치가 완료됐습니다. .\start.ps1로 실행해 주세요.'
} finally { Pop-Location }
