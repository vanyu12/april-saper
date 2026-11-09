[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root ".env.example") $envFile
}

$content = Get-Content $envFile -Raw -Encoding UTF8
$token = ""
if ($content -match '(?m)^[ \t]*BOT_TOKEN[ \t]*=[ \t]*(\S*)') { $token = $Matches[1].Trim() }

if ([string]::IsNullOrWhiteSpace($token)) {
    Write-Host "BOT_TOKEN не заполнен." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Открой Telegram -> @BotFather -> /newbot"
    Write-Host "Придумай имя и юзернейм, скопируй токен и вставь его в .env:"
    Write-Host "  BOT_TOKEN=123456:AA..."
    Write-Host ""
    Write-Host "После этого запусти этот скрипт снова."
    exit 1
}

$port = "8080"
if ($content -match '(?m)^[ \t]*PORT[ \t]*=[ \t]*(\d+)') { $port = $Matches[1] }

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python -or $python -like "*WindowsApps*") {
    $python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
}
if (-not (Test-Path $python)) {
    Write-Host "Python не найден. Установи Python 3.12 и повтори." -ForegroundColor Red
    exit 1
}

$cf = Join-Path $root "tools\cloudflared.exe"
if (-not (Test-Path $cf)) { $cf = "cloudflared" }

$log = Join-Path $env:TEMP ("saper-tunnel-" + [guid]::NewGuid().ToString("N") + ".log")
Write-Host "Поднимаю HTTPS-туннель..." -ForegroundColor Cyan
$tunnel = Start-Process -FilePath $cf -ArgumentList @(
    "tunnel", "--url", "http://localhost:$port", "--no-autoupdate",
    "--logfile", $log, "--loglevel", "info"
) -PassThru -WindowStyle Hidden

$publicUrl = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-Path $log) {
        $text = Get-Content $log -Raw -ErrorAction SilentlyContinue
        if ($text -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
            $publicUrl = $Matches[0]
            break
        }
    }
    if ($tunnel.HasExited) { break }
}

if (-not $publicUrl) {
    Write-Host "Не удалось получить адрес туннеля. Лог: $log" -ForegroundColor Red
    if (-not $tunnel.HasExited) { $tunnel.Kill() }
    exit 1
}

$newContent = [regex]::Replace($content, '(?m)^[ \t]*PUBLIC_URL[ \t]*=.*$', "PUBLIC_URL=$publicUrl")
if ($newContent -notmatch '(?m)^[ \t]*PUBLIC_URL[ \t]*=') {
    $newContent = $newContent.TrimEnd() + "`r`nPUBLIC_URL=$publicUrl`r`n"
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($envFile, $newContent, $utf8NoBom)

Write-Host "Mini App: $publicUrl/" -ForegroundColor Green
Write-Host "Туннель: PID $($tunnel.Id). Запускаю бота..." -ForegroundColor Cyan

$code = 0
try {
    & $python main.py
    $code = $LASTEXITCODE
}
finally {
    if ($tunnel -and -not $tunnel.HasExited) { $tunnel.Kill() }
    Write-Host "Остановлено." -ForegroundColor Yellow
}
exit $code
