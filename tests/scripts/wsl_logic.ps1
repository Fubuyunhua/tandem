<#
    setup-tandem-distro.ps1 的纯逻辑测试（G1–G4）。

    不创建发行版、不导入、不联网：只 dot-source 脚本，然后调用其中的纯函数。
    由 tests/scripts/test_wsl_script.py 调用；也可以单独运行。
#>
param(
    [string]$ScriptPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ScriptPath)) {
    $ScriptPath = Join-Path $PSScriptRoot "..\..\scripts\wsl\setup-tandem-distro.ps1"
}
$ScriptPath = (Resolve-Path -LiteralPath $ScriptPath).Path
. $ScriptPath

$failures = New-Object System.Collections.ArrayList

function Check-True {
    param([bool]$Condition, [string]$Name)
    if (-not $Condition) {
        [void]$failures.Add("$Name：期望成立，实际不成立")
    }
}

function Check-Throws {
    param([scriptblock]$Block, [string]$Pattern, [string]$Name)
    $message = $null
    try {
        & $Block
    }
    catch {
        $message = $_.Exception.Message
    }
    if ($null -eq $message) {
        [void]$failures.Add("$Name：期望抛错，实际没有抛")
        return
    }
    if ($Pattern -and $message -notmatch $Pattern) {
        [void]$failures.Add("$Name：错误信息里没有匹配 '$Pattern'，实际是：$message")
    }
}

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("tandem-wsl-test-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

try {
    # --- G2：发行版名字 ---
    Check-Throws { Assert-DistroNameFresh -DistroName "tandem" -Existing @("Ubuntu", "tandem") } "已经存在" "G2 同名必须拒绝"
    Check-Throws { Assert-DistroNameFresh -DistroName "tandem" -Existing @("tandem") } "不会注销" "G2 错误信息要说明不会注销"
    Check-Throws { Assert-DistroNameFresh -DistroName "a b" -Existing @() } "只能包含" "G2 非法名字必须拒绝"
    Check-Throws { Assert-DistroNameFresh -DistroName "" -Existing @() } "不能为空" "G2 空名字必须拒绝"
    $ok = $true
    try { Assert-DistroNameFresh -DistroName "tandem" -Existing @("Ubuntu") } catch { $ok = $false }
    Check-True $ok "G2 新名字应该通过"

    # --- G1：rootfs 校验 ---
    $rootfs = Join-Path $tmp "rootfs.tar.gz"
    Set-Content -LiteralPath $rootfs -Value "fake rootfs" -NoNewline
    $good = (Get-FileHash -LiteralPath $rootfs -Algorithm SHA256).Hash
    $bad = ("0" * 64)
    Check-Throws { Assert-RootfsReady -Path $rootfs -ExpectedSha256 $bad } "哈希不符" "G1 哈希不符必须拒绝"
    Check-Throws { Assert-RootfsReady -Path (Join-Path $tmp "missing.tar.gz") -ExpectedSha256 $good } "不存在" "G1 文件不存在必须拒绝"
    Check-Throws { Assert-RootfsReady -Path $rootfs -ExpectedSha256 "" } "ExpectedSha256" "G1 必须要求期望哈希"
    Check-Throws { Assert-RootfsReady -Path $rootfs -ExpectedSha256 "abc" } "64 位" "G1 期望哈希格式必须校验"
    Check-Throws { Assert-RootfsReady -Path "" -ExpectedSha256 $good } "RootfsPath" "G1 必须要求 rootfs 路径"
    $ok = $true
    try { Assert-RootfsReady -Path $rootfs -ExpectedSha256 $good.ToLowerInvariant() } catch { $ok = $false }
    Check-True $ok "G1 正确哈希（小写）应该通过"

    # --- G3：目录与临时文件 ---
    $busy = Join-Path $tmp "busy-install"
    New-Item -ItemType Directory -Path $busy -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $busy "keep.txt") -Value "不要覆盖我"
    Check-Throws { Assert-InstallDirFree -InstallDir $busy } "拒绝覆盖" "G3 非空安装目录必须拒绝"
    $ok = $true
    try { Assert-InstallDirFree -InstallDir (Join-Path $tmp "new-install") } catch { $ok = $false }
    Check-True $ok "G3 不存在的安装目录应该通过"

    $runsRoot = Join-Path $tmp "runs"
    New-Item -ItemType Directory -Path $runsRoot -Force | Out-Null
    $first = New-RunDirectory -RunsRoot $runsRoot -DistroName "tandem" -Stamp "20260101T000000" -Suffix "111111"
    $second = New-RunDirectory -RunsRoot $runsRoot -DistroName "tandem" -Stamp "20260101T000000" -Suffix "222222"
    Check-True (Test-Path -LiteralPath $first) "G3 运行目录应该被创建"
    Check-True ($first -ne $second) "G3 两次运行目录必须不同"
    Check-Throws { New-RunDirectory -RunsRoot $runsRoot -DistroName "tandem" -Stamp "20260101T000000" -Suffix "111111" } "拒绝复用" "G3 已存在的运行目录必须拒绝复用"

    # --- G4：阶段报告 ---
    $report = Format-StageReport -Completed @("检查前提", "校验 rootfs") -Failed "导入发行版" -Remaining @("写入 /etc/wsl.conf")
    Check-True ($report -match "已完成") "G4 报告要有已完成"
    Check-True ($report -match "校验 rootfs") "G4 报告要列出已完成的步骤"
    Check-True ($report -match "失败在") "G4 报告要有失败位置"
    Check-True ($report -match "未完成") "G4 报告要有未完成"
    Check-True ($report -notmatch "未做任何改动") "G4 不能说未做任何改动"
    $empty = Format-StageReport
    Check-True ($empty -match "已完成：无") "G4 空报告要明确写无"

    # --- G1/G2 静态检查：可执行代码里不能有破坏性命令（注释和帮助文字里提到不算） ---
    $scriptText = Get-Content -LiteralPath $ScriptPath -Raw -Encoding UTF8
    $codeOnly = [regex]::Replace($scriptText, "(?s)<#.*?#>", "")
    $codeOnly = ($codeOnly -split "`r?`n" | Where-Object { $_.TrimStart() -notmatch "^#" }) -join "`n"
    Check-True ($codeOnly -notmatch "--unregister") "G2 代码里不能出现 --unregister"
    Check-True ($codeOnly -notmatch "--export") "G1 代码里不能出现 --export"
    Check-True ($codeOnly -notmatch "-Recreate") "G2 代码里不能出现 -Recreate"
}
finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

if ($failures.Count -gt 0) {
    foreach ($failure in $failures) {
        Write-Output "FAIL: $failure"
    }
    exit 1
}
Write-Output "ALL PASS"
exit 0
