<#
.SYNOPSIS
    用本地 rootfs 镜像创建 tandem 专用 WSL2 发行版，并写入关闭 automount / interop / appendWindowsPath 的 /etc/wsl.conf。

.DESCRIPTION
    这个脚本做什么（按顺序）：
      1. 检查前提：wsl.exe 可用；目标发行版名不与任何已有发行版重名；rootfs 文件存在；
      2. 校验 rootfs 的 SHA256 是否等于你提供的期望值（不一致就停，不导入）；
      3. 在专用运行目录里记一份阶段报告（唯一名字，绝不复用已有目录）；
      4. 用 `wsl --import` 把 rootfs 导入成新发行版（WSL 2）；
      5. 把 scripts/wsl/wsl.conf 以 LF 换行写入发行版的 /etc/wsl.conf；
      6. 终止这个发行版，让它下次以新配置启动，并打印只读的验证结果。

    它**不会**做什么：
      - 不会复制你现有的发行版（第一轮的 `--export` 会把私人资料一起带进"隔离"环境，已删除）；
      - 不会注销、删除、覆盖任何已有发行版（`-Recreate` 已删除）；
      - 不会修改 .wslconfig（那是全局配置）；
      - 不联网下载镜像：rootfs 要你自己准备好，并且自己核对哈希。

    任何阶段失败都会打印"已完成 / 失败在 / 未完成"，不会说"未做任何改动"。

.PARAMETER RootfsPath
    本地 rootfs 文件（例如从 Ubuntu 官方发布的 WSL 镜像里解出来的 install.tar.gz）。

.PARAMETER ExpectedSha256
    rootfs 的期望 SHA256（64 位十六进制）。必须提供，脚本不会相信未经校验的镜像。

.PARAMETER DistroName
    新发行版的名字，默认 tandem。必须与已有发行版都不同。

.PARAMETER InstallDir
    新发行版的数据目录，默认 %LOCALAPPDATA%\tandem\wsl\tandem。已存在则拒绝（不覆盖）。

.PARAMETER RunsRoot
    阶段报告和临时文件的父目录，默认 %LOCALAPPDATA%\tandem\wsl\runs。

.PARAMETER DryRun
    只做只读检查并打印计划，不创建目录、不导入、不写配置。

.PARAMETER Yes
    跳过交互确认（给自动化用；慎用）。

.EXAMPLE
    .\scripts\wsl\setup-tandem-distro.ps1 -RootfsPath D:\images\ubuntu-wsl-rootfs.tar.gz -ExpectedSha256 <64 位十六进制> -DryRun

.EXAMPLE
    .\scripts\wsl\setup-tandem-distro.ps1 -RootfsPath D:\images\ubuntu-wsl-rootfs.tar.gz -ExpectedSha256 <64 位十六进制>
#>
[CmdletBinding()]
param(
    [string]$RootfsPath = "",
    [string]$ExpectedSha256 = "",
    [string]$DistroName = "tandem",
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "tandem\wsl\tandem"),
    [string]$RunsRoot = (Join-Path $env:LOCALAPPDATA "tandem\wsl\runs"),
    [switch]$DryRun,
    [switch]$Yes
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ==========================================================================
# 纯逻辑：测试脚本会 dot-source 本文件后直接调用这些函数
# ==========================================================================

function Assert-DistroNameFresh {
    <# 目标名字必须合法、且与任何已有发行版都不同（G2）。绝不注销已有发行版。 #>
    param(
        [string]$DistroName,
        [string[]]$Existing = @()
    )
    if ([string]::IsNullOrWhiteSpace($DistroName)) {
        throw "发行版名字不能为空。"
    }
    if ($DistroName -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
        throw "发行版名字只能包含字母、数字、点、下划线、短横线：$DistroName"
    }
    if ($Existing -contains $DistroName) {
        throw ("发行版 '$DistroName' 已经存在。这个脚本不会注销任何已有发行版：" +
            "要重建请按 docs/runbooks/wsl-isolation.md 的回滚一节手动删除，或者换一个 -DistroName。")
    }
}

function Assert-RootfsReady {
    <# rootfs 必须存在、是普通文件、并且哈希等于你给的期望值（G1）。 #>
    param(
        [string]$Path,
        [string]$ExpectedSha256
    )
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "必须用 -RootfsPath 指定一个本地 rootfs 文件：不会从你现有的发行版复制。"
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "rootfs 文件不存在：$Path"
    }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.LinkType) {
        throw "rootfs 不能是符号链接：$Path"
    }
    if ([string]::IsNullOrWhiteSpace($ExpectedSha256)) {
        throw "必须用 -ExpectedSha256 提供期望的 SHA256：脚本不会导入未经校验的镜像。"
    }
    if ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw "ExpectedSha256 必须是 64 位十六进制：$ExpectedSha256"
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    $expected = $ExpectedSha256.ToUpperInvariant()
    if ($actual -ne $expected) {
        throw ("rootfs 哈希不符：期望 $expected，实际 $actual。" +
            "镜像可能损坏或被替换，已停止，未导入任何东西。")
    }
}

function Assert-InstallDirFree {
    <# 安装目录不能是已经存在且非空的目录（G3：不覆盖别人的东西）。 #>
    param([string]$InstallDir)
    if ([string]::IsNullOrWhiteSpace($InstallDir)) {
        throw "必须指定 -InstallDir。"
    }
    if (Test-Path -LiteralPath $InstallDir) {
        $item = Get-Item -LiteralPath $InstallDir -Force
        if (-not $item.PSIsContainer) {
            throw "安装目录路径已被一个文件占用：$InstallDir"
        }
        if (@(Get-ChildItem -LiteralPath $InstallDir -Force).Count -gt 0) {
            throw "安装目录非空，拒绝覆盖：$InstallDir"
        }
    }
}

function New-RunDirectory {
    <# 专用运行目录：唯一名字，已存在就报错，绝不复用（G3）。 #>
    param(
        [string]$RunsRoot,
        [string]$DistroName,
        [string]$Stamp = "",
        [string]$Suffix = ""
    )
    if ([string]::IsNullOrWhiteSpace($RunsRoot)) {
        throw "必须指定 -RunsRoot。"
    }
    if ([string]::IsNullOrWhiteSpace($Stamp)) {
        $Stamp = Get-Date -Format "yyyyMMddTHHmmss"
    }
    if ([string]::IsNullOrWhiteSpace($Suffix)) {
        $Suffix = [string](Get-Random -Minimum 100000 -Maximum 999999)
    }
    $path = Join-Path $RunsRoot ("{0}-{1}-{2}" -f $Stamp, $DistroName, $Suffix)
    if (Test-Path -LiteralPath $path) {
        throw "运行目录已存在，拒绝复用：$path"
    }
    New-Item -ItemType Directory -Path $path -Force | Out-Null
    return $path
}

function Format-StageReport {
    <# 每个阶段失败时都要说清楚做了什么、还剩什么（G4）。 #>
    param(
        [string[]]$Completed = @(),
        [string]$Failed = "",
        [string[]]$Remaining = @()
    )
    $lines = New-Object System.Collections.ArrayList
    if ($Completed.Count -gt 0) {
        [void]$lines.Add("已完成：")
        foreach ($item in $Completed) {
            [void]$lines.Add("  - $item")
        }
    }
    else {
        [void]$lines.Add("已完成：无")
    }
    if (-not [string]::IsNullOrWhiteSpace($Failed)) {
        [void]$lines.Add("失败在：$Failed")
    }
    if ($Remaining.Count -gt 0) {
        [void]$lines.Add("未完成：")
        foreach ($item in $Remaining) {
            [void]$lines.Add("  - $item")
        }
    }
    else {
        [void]$lines.Add("未完成：无")
    }
    return ($lines -join [Environment]::NewLine)
}

# ==========================================================================
# IO：只在这一段里调用外部命令
# ==========================================================================

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "== $Message" -ForegroundColor Cyan
}

function Invoke-External {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    $pretty = "$FilePath $($Arguments -join ' ')"
    if ($DryRun) {
        Write-Host "[dry-run] $pretty"
        return
    }
    Write-Host "+ $pretty" -ForegroundColor DarkGray
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "命令失败（退出码 $LASTEXITCODE）：$pretty"
    }
}

function Get-WslDistroNames {
    <# wsl -l -q 输出是 UTF-16，需要临时改控制台编码才能正确解析。 #>
    $previous = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [System.Text.Encoding]::Unicode
        $raw = & wsl.exe -l -q
    }
    finally {
        [Console]::OutputEncoding = $previous
    }
    return @(
        $raw |
            ForEach-Object { ($_ -replace "`0", "").Trim() } |
            Where-Object { $_ -ne "" }
    )
}

function Confirm-Action {
    param([string]$Question)
    if ($Yes) { return }
    if ($DryRun) {
        Write-Host "[dry-run] 会要求确认：$Question"
        return
    }
    $answer = Read-Host "$Question`n输入 yes 继续，其它任意输入取消"
    if ($answer -ne "yes") {
        throw "用户取消。已完成的步骤见下面的阶段报告。"
    }
}

function Invoke-TandemSetup {
    param(
        [string]$RootfsPath,
        [string]$ExpectedSha256,
        [string]$DistroName,
        [string]$InstallDir,
        [string]$RunsRoot
    )

    $stages = @("检查前提", "校验 rootfs", "创建运行目录", "导入发行版", "写入 /etc/wsl.conf", "终止并验证")
    $completed = New-Object System.Collections.ArrayList
    $current = "检查前提"
    $runDir = $null

    try {
        Write-Step "检查前提"
        if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
            throw "找不到 wsl.exe。请先确认 WSL 已安装（wsl --install）。"
        }
        $confPath = Join-Path $PSScriptRoot "wsl.conf"
        if (-not (Test-Path -LiteralPath $confPath)) {
            throw "找不到要写入的配置：$confPath"
        }
        $existing = Get-WslDistroNames
        Write-Host ("现有发行版：{0}" -f ($(if ($existing) { $existing -join ", " } else { "（无）" })))
        Assert-DistroNameFresh -DistroName $DistroName -Existing $existing
        Assert-InstallDirFree -InstallDir $InstallDir
        [void]$completed.Add($current)

        $current = "校验 rootfs"
        Write-Step "校验 rootfs"
        Assert-RootfsReady -Path $RootfsPath -ExpectedSha256 $ExpectedSha256
        Write-Host "rootfs 哈希校验通过：$RootfsPath"
        [void]$completed.Add($current)

        $current = "创建运行目录"
        Write-Step "创建运行目录"
        if (-not $DryRun) {
            if (-not (Test-Path -LiteralPath $RunsRoot)) {
                New-Item -ItemType Directory -Path $RunsRoot -Force | Out-Null
            }
            $runDir = New-RunDirectory -RunsRoot $RunsRoot -DistroName $DistroName
            Write-Host "运行目录：$runDir"
        }
        else {
            Write-Host "[dry-run] 会在 $RunsRoot 下新建一个唯一名字的运行目录"
        }
        [void]$completed.Add($current)

        Write-Host "计划：把 $RootfsPath 导入为 '$DistroName'（WSL 2），安装到 $InstallDir"
        Confirm-Action "将导入一个新的 WSL 发行版 '$DistroName'（不会动你已有的发行版）。"

        $current = "导入发行版"
        Write-Step "导入 $DistroName"
        if (-not $DryRun -and -not (Test-Path -LiteralPath $InstallDir)) {
            New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
        }
        Invoke-External "wsl.exe" @("--import", $DistroName, $InstallDir, $RootfsPath, "--version", "2")
        [void]$completed.Add($current)

        $current = "写入 /etc/wsl.conf"
        Write-Step "写入 /etc/wsl.conf"
        # 先 CRLF→LF，再用 base64 传进去：避免 PowerShell 管道把换行改回 CRLF。
        # 必须显式 -Encoding UTF8：Windows PowerShell 5.1 对无 BOM 的文件默认按 ANSI 读。
        $confText = (Get-Content -LiteralPath $confPath -Raw -Encoding UTF8) -replace "`r`n", "`n"
        $confBase64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($confText))
        $writeCommand = "echo $confBase64 | base64 -d > /etc/wsl.conf && chmod 644 /etc/wsl.conf"
        Invoke-External "wsl.exe" @("-d", $DistroName, "-u", "root", "--", "bash", "-c", $writeCommand)
        [void]$completed.Add($current)

        $current = "终止并验证"
        Write-Step "终止 $DistroName，让新配置生效"
        Invoke-External "wsl.exe" @("--terminate", $DistroName)
        Write-Step "验证（只读）"
        Invoke-External "wsl.exe" @(
            "-d", $DistroName, "-u", "root", "--", "bash", "-c",
            "echo '--- /etc/wsl.conf ---'; cat /etc/wsl.conf; echo '--- /mnt（应该是空的）---'; ls -la /mnt"
        )
        [void]$completed.Add($current)
    }
    catch {
        Write-Host ""
        Write-Host "!! 阶段失败：$current" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
        $remaining = @($stages | Where-Object { $completed -notcontains $_ })
        Write-Host (Format-StageReport -Completed @($completed) -Failed $current -Remaining $remaining)
        if ($runDir) {
            $reportPath = Join-Path $runDir "stage-report.txt"
            try {
                (Format-StageReport -Completed @($completed) -Failed $current -Remaining $remaining) |
                    Set-Content -LiteralPath $reportPath -Encoding UTF8
                Write-Host "阶段报告：$reportPath"
            }
            catch {
                Write-Host "阶段报告写不进去：$reportPath"
            }
        }
        exit 1
    }

    Write-Step "完成，接下来手动做这几步"
    @"
1. 建一个日常用户（不要用 root 跑 Agent），例如：
     wsl -d $DistroName -u root -- bash -c "adduser --disabled-password --gecos '' tandem && usermod -aG sudo tandem"
   然后在 /etc/wsl.conf 末尾加 [user] default=tandem，再 wsl --terminate $DistroName。
2. 在发行版里装 Agent 和依赖，登录各家账号（claude、codex 等）。
3. 对每家 Agent 跑诱饵测试（prepare → probe → report），三项都被挡住才允许无人值守：
     python3 -m scripts.decoy.run_decoy prepare --run-dir ~/decoy-runs/1
4. 完整步骤、凭据清单和回滚办法见 docs/runbooks/wsl-isolation.md。
"@ | Write-Host
}

# 被测试脚本 dot-source 时只加载函数，不执行主流程
if ($MyInvocation.InvocationName -ne ".") {
    Invoke-TandemSetup -RootfsPath $RootfsPath -ExpectedSha256 $ExpectedSha256 `
        -DistroName $DistroName -InstallDir $InstallDir -RunsRoot $RunsRoot
}
