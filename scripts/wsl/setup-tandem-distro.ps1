<#
.SYNOPSIS
    创建 tandem 专用 WSL2 发行版，并写入关闭 automount / interop / appendWindowsPath 的 /etc/wsl.conf。

.DESCRIPTION
    这个脚本做什么（按顺序）：
      1. 检查前提：wsl.exe 可用、源发行版存在、目标发行版不存在（除非加 -Recreate）；
      2. 把源发行版（默认 Ubuntu）导出成一个临时 tar；
      3. 用这个 tar 导入成新的发行版（默认 tandem，WSL 2）；
      4. 把 scripts/wsl/wsl.conf 以 LF 换行写入发行版的 /etc/wsl.conf；
      5. 终止这个发行版，让它下次以新配置启动，并打印验证命令。

    它不做什么：
      - 不改 .wslconfig（那是全局配置，会影响你所有的发行版）；
      - 不安装任何软件，不登录任何 AI；
      - 不删除已有的发行版（只有 -Recreate 会，而且会再确认一次）；
      - 不联网下载镜像：用「导出再导入」的方式，所以源发行版必须已经存在。

    破坏性操作（注销已有发行版、导入覆盖目录）之前都会要求确认；加 -DryRun 只打印计划。

.PARAMETER DistroName
    新发行版的名字，默认 tandem。

.PARAMETER SourceDistro
    导出 tar 用的现有发行版，默认 Ubuntu。

.PARAMETER InstallDir
    新发行版的数据放在 Windows 的哪个目录，默认 %LOCALAPPDATA%\tandem\wsl\tandem。

.PARAMETER TarPath
    导出用的临时 tar，默认 %TEMP%\tandem-source.tar（导出期间可能占几个 GB）。

.PARAMETER Recreate
    目标发行版已存在时，先注销它再重建。这会丢掉里面的一切。

.PARAMETER DryRun
    只打印计划，不执行任何会改变系统状态的命令。

.PARAMETER Yes
    跳过交互确认（给自动化用；慎用）。

.EXAMPLE
    .\scripts\wsl\setup-tandem-distro.ps1 -DryRun

.EXAMPLE
    .\scripts\wsl\setup-tandem-distro.ps1 -SourceDistro Ubuntu
#>
[CmdletBinding()]
param(
    [string]$DistroName = "tandem",
    [string]$SourceDistro = "Ubuntu",
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "tandem\wsl\tandem"),
    [string]$TarPath = (Join-Path $env:TEMP "tandem-source.tar"),
    [switch]$Recreate,
    [switch]$DryRun,
    [switch]$Yes
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "== $Message" -ForegroundColor Cyan
}

function Invoke-External {
    <# 执行一条外部命令；DryRun 时只打印。失败就抛异常。 #>
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
    <# 破坏性操作前问一句；-Yes 直接过，-DryRun 只说明会问。 #>
    param([string]$Question)
    if ($Yes) { return }
    if ($DryRun) {
        Write-Host "[dry-run] 会要求确认：$Question"
        return
    }
    $answer = Read-Host "$Question`n输入 yes 继续，其它任意输入取消"
    if ($answer -ne "yes") {
        throw "用户取消，未做任何改动。"
    }
}

# ---------------------------------------------------------------- 1. 前提检查
Write-Step "检查前提"

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw "找不到 wsl.exe。请先确认 WSL 已安装（wsl --install）。"
}

$confPath = Join-Path $PSScriptRoot "wsl.conf"
if (-not (Test-Path -LiteralPath $confPath)) {
    throw "找不到要写入的配置：$confPath"
}

$distros = Get-WslDistroNames
Write-Host ("现有发行版：{0}" -f ($(if ($distros) { $distros -join ", " } else { "（无）" })))

if ($distros -notcontains $SourceDistro) {
    throw "源发行版 '$SourceDistro' 不存在。可用的有：$($distros -join ', ')。用 -SourceDistro 指定。"
}

$targetExists = $distros -contains $DistroName
if ($targetExists -and -not $Recreate) {
    throw "发行版 '$DistroName' 已存在。要继续请加 -Recreate（会先注销它，里面的一切都会丢）。"
}

Write-Host "计划：从 '$SourceDistro' 导出 → 导入为 '$DistroName'（WSL 2）→ 写入 /etc/wsl.conf"
Write-Host "安装目录：$InstallDir"
Write-Host "临时 tar：$TarPath"

# ------------------------------------------------------- 2. 注销（仅 -Recreate）
if ($targetExists) {
    Write-Step "注销已有发行版（-Recreate）"
    Confirm-Action "将注销发行版 '$DistroName'：里面的文件、已安装的软件、登录状态全部丢失。"
    Invoke-External "wsl.exe" @("--unregister", $DistroName)
}

Confirm-Action "将把 '$SourceDistro' 导出并导入为 '$DistroName'，占用磁盘空间约等于源发行版。"

# ---------------------------------------------------------------- 3. 导出/导入
Write-Step "导出 $SourceDistro"
if (-not $DryRun) {
    if (Test-Path -LiteralPath $TarPath) {
        Remove-Item -LiteralPath $TarPath -Force
    }
}
Invoke-External "wsl.exe" @("--export", $SourceDistro, $TarPath)

Write-Step "导入为 $DistroName"
if (-not $DryRun -and -not (Test-Path -LiteralPath $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}
Invoke-External "wsl.exe" @("--import", $DistroName, $InstallDir, $TarPath, "--version", "2")

# --------------------------------------------------------------- 4. 写 wsl.conf
Write-Step "写入 /etc/wsl.conf"
# 先把 CRLF 换成 LF，再用 base64 传进去：避免 PowerShell 管道把换行改回 CRLF。
# 必须显式指定 -Encoding UTF8：Windows PowerShell 5.1 对无 BOM 的文件默认按 ANSI 读，中文会乱码。
$confText = (Get-Content -LiteralPath $confPath -Raw -Encoding UTF8) -replace "`r`n", "`n"
$confBase64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($confText))
$writeCommand = "echo $confBase64 | base64 -d > /etc/wsl.conf && chmod 644 /etc/wsl.conf"
Invoke-External "wsl.exe" @("-d", $DistroName, "-u", "root", "--", "bash", "-c", $writeCommand)

Write-Step "终止 $DistroName，让新配置在下次启动时生效"
Invoke-External "wsl.exe" @("--terminate", $DistroName)

# ------------------------------------------------------------- 5. 只读验证
Write-Step "验证（只读）"
Invoke-External "wsl.exe" @(
    "-d", $DistroName, "-u", "root", "--", "bash", "-c",
    "echo '--- /etc/wsl.conf ---'; cat /etc/wsl.conf; echo '--- /mnt（应该是空的）---'; ls -la /mnt"
)

if (-not $DryRun -and (Test-Path -LiteralPath $TarPath)) {
    Write-Step "删除临时 tar"
    Remove-Item -LiteralPath $TarPath -Force
}

Write-Step "完成，接下来手动做这几步"
@"
1. 建一个日常用户（不要用 root 跑 Agent），例如：
     wsl -d $DistroName -u root -- bash -c "adduser --disabled-password --gecos '' tandem && usermod -aG sudo tandem"
   然后在 /etc/wsl.conf 末尾加 [user] default=tandem，再 wsl --terminate $DistroName。
2. 在发行版里装 Agent 和依赖，登录各家账号（claude、codex 等）。
3. 对每家 Agent 跑诱饵测试，三项都被挡住才允许无人值守：
     python3 -m scripts.decoy.run_decoy --agent claude --agent-cmd 'claude -p "{prompt}"'
4. 完整步骤和回滚办法见 docs/runbooks/wsl-isolation.md。
"@ | Write-Host
