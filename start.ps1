param([string]$DataDir, [switch]$ChooseDataDir, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$runtimePython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtimePython)) {
    throw 'Python 환경이 없습니다. README의 최초 설치를 진행해 주세요.'
}
$launchArguments = @('-m', 'backend.launcher')
if ($DataDir) { $launchArguments += @('--data-dir', $DataDir) }
if ($ChooseDataDir) { $launchArguments += '--choose-data-dir' }
if ($NoBrowser) { $launchArguments += '--no-browser' }
Push-Location -LiteralPath $PSScriptRoot
try {
    & $runtimePython @launchArguments
    if ($LASTEXITCODE -ne 0) { throw '프로그램 실행에 실패했습니다. 위 오류를 확인해 주세요.' }
} finally {
    Pop-Location
}
