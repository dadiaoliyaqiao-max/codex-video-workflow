param(
    [string]$Destination = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'CodexVideoWorkflow'),
    [switch]$DownloadOnly
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$archiveUrl = 'https://codeload.github.com/dadiaoliyaqiao-max/codex-video-workflow/zip/refs/heads/main'
$folderName = 'codex-video-workflow-main'
$destinationFull = [System.IO.Path]::GetFullPath($Destination)
$projectRoot = Join-Path $destinationFull $folderName
$installer = Join-Path $projectRoot '一键安装并检查.cmd'
$installerScript = Join-Path $projectRoot 'scripts\install-windows.ps1'

if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    if (Test-Path -LiteralPath $projectRoot) {
        throw "An incomplete folder already exists: $projectRoot. Choose another -Destination or move the incomplete folder aside."
    }
    New-Item -ItemType Directory -Path $destinationFull -Force | Out-Null
    $archive = Join-Path $env:TEMP ('codex-video-workflow-' + [guid]::NewGuid().ToString('N') + '.zip')
    try {
        Write-Host "Downloading public workflow from GitHub..."
        Invoke-WebRequest -Uri $archiveUrl -OutFile $archive -UseBasicParsing
        Expand-Archive -LiteralPath $archive -DestinationPath $destinationFull
    } finally {
        if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
    }
}

if (-not (Test-Path -LiteralPath $installer -PathType Leaf) -or
    -not (Test-Path -LiteralPath $installerScript -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $projectRoot 'AGENTS.md') -PathType Leaf)) {
    throw "Workflow package is incomplete: $projectRoot"
}

Write-Host "Workflow folder: $projectRoot"
if ($DownloadOnly) { Write-Host 'Download check complete.'; exit 0 }

Write-Host 'Installing related tools and running checks...'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installerScript
if ($LASTEXITCODE -ne 0) { throw "Installation failed. See $projectRoot\install-logs\install-report.json" }
Write-Host "Open this folder in Codex: $projectRoot"
