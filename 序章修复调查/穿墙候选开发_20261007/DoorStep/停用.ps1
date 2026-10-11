param([string]$GameDirectory)
$ErrorActionPreference = 'Stop'
if (-not $GameDirectory) { $GameDirectory = Read-Host '输入包含 Spider-Man.exe 的游戏目录' }
$gameRoot = (Resolve-Path -LiteralPath $GameDirectory).Path.TrimEnd('\')
if (Get-Process -Name 'Spider-Man' -ErrorAction SilentlyContinue) { throw '请先正常退出游戏，再停用。' }
if (-not (Test-Path -LiteralPath (Join-Path $gameRoot 'Spider-Man.exe') -PathType Leaf)) { throw '这不是游戏目录。' }
$targetDir = (Resolve-Path -LiteralPath (Join-Path $gameRoot 'SMT\Scripts')).Path.TrimEnd('\')
if (-not $targetDir.StartsWith($gameRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw '目标目录越界。' }
$target = Join-Path $targetDir 'DoorStep.dll'
if (Test-Path -LiteralPath $target) {
    $newTarget = Join-Path $targetDir ('DoorStep.disabled.'+(Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
    if (-not [IO.Path]::GetFullPath($newTarget).StartsWith($targetDir+'\',[StringComparison]::OrdinalIgnoreCase)) { throw '目标越界。' }
    Move-Item -LiteralPath $target -Destination $newTarget
}
Write-Host '穿门插件已停用；原有联机 MOD 和存档保留。'
