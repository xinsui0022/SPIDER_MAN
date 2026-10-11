param([string]$GameDirectory)
$ErrorActionPreference = 'Stop'
$expectedGame = 'e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1'
$expectedCore = 'b7ab575100f2346af25180d74bf9641e24ce09bf549ce47446be09c3462606c7'
$expectedProxy = 'ec59e8537eb9c6ec144897f64ccd8a79618309dd1bb3a62b65ad70b308bcab85'
if (-not $GameDirectory) { $GameDirectory = Read-Host '输入 Steam 浏览本地文件打开的游戏目录（包含 Spider-Man.exe）' }
$gameRoot = (Resolve-Path -LiteralPath $GameDirectory).Path.TrimEnd('\')
if (Get-Process -Name 'Spider-Man' -ErrorAction SilentlyContinue) { throw '请先从游戏菜单正常退出，再运行安装。' }
foreach ($item in @(@('Spider-Man.exe',$expectedGame),@('SMT\Scripts\smt.dll',$expectedCore),@('winmm.dll',$expectedProxy))) {
    $path = Join-Path $gameRoot $item[0]
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "缺少已安装的联机文件：$($item[0])" }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item[1]) { throw "版本不匹配，未安装：$($item[0])" }
}
$sourceDir = Join-Path $PSScriptRoot '安装文件\SMT\Scripts'
$sourceDll = Join-Path $sourceDir 'DoorStep.dll'
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot '文件校验.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ((Get-FileHash -LiteralPath $sourceDll -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.dll_sha256) { throw '候选文件校验失败。' }
$targetDir = (Resolve-Path -LiteralPath (Join-Path $gameRoot 'SMT\Scripts')).Path.TrimEnd('\')
if (-not $targetDir.StartsWith($gameRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw '目标目录越界。' }
if ((Get-Item -LiteralPath $targetDir).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '拒绝链接目标目录。' }
$targetDll = Join-Path $targetDir 'DoorStep.dll'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
if (Test-Path -LiteralPath $targetDll) { Copy-Item -LiteralPath $targetDll -Destination (Join-Path $targetDir "DoorStep.dll.backup.$stamp") }
Copy-Item -LiteralPath $sourceDll -Destination $targetDll -Force
$targetIni = Join-Path $targetDir 'DoorStep.ini'
if (-not (Test-Path -LiteralPath $targetIni)) { Copy-Item -LiteralPath (Join-Path $sourceDir 'DoorStep.ini') -Destination $targetIni }
if ((Get-FileHash -LiteralPath $targetDll -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.dll_sha256) { throw '安装后校验失败。请退出游戏使用停用脚本。' }
Write-Host '安装完成。按原有 -mp 方式启动游戏，进入可控制角色的场景后 F7 启用、F8 穿门、PageUp 上移、PageDown 下移、F9 返回。'
Write-Host '首次测试先在平地试方向。离开游戏窗口或关闭功能后，返回点会清除。'
