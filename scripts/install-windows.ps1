param(
    [switch]$PlanOnly,
    [switch]$SkipMachineInstall,
    [switch]$SkipSkillInstall,
    [switch]$SkipASRPrep
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$logDir = Join-Path $root 'install-logs'
$reportPath = Join-Path $logDir 'install-report.json'
$report = [ordered]@{
    started_at = (Get-Date).ToString('o')
    status = 'running'
    root = $root
    steps = @()
    tools = [ordered]@{}
    errors = @()
}

function Add-Step([string]$name, [string]$status, [string]$detail) {
    $script:report.steps += [ordered]@{ name = $name; status = $status; detail = $detail }
    Write-Host "[$status] $name - $detail"
}

function Save-Report {
    if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
    $json = $script:report | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText($reportPath, $json, [System.Text.UTF8Encoding]::new($false))
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $links = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links'
    $env:Path = (@($machinePath, $userPath, $links, $env:Path) | Where-Object { $_ }) -join ';'
}

function Find-CommandPath([string]$name) {
    $found = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found -and $found.Source -and (Test-Path -LiteralPath $found.Source -PathType Leaf)) { return $found.Source }
    return $null
}

function Invoke-Checked([string]$executable, [string[]]$arguments, [string]$label) {
    Write-Host "`n== $label =="
    & $executable @arguments
    $code = $LASTEXITCODE
    if ($code -ne 0) { throw "$label failed (exit $code)" }
}

function Install-NpmLocked([string]$directory, [string]$label) {
    $lockfile = Join-Path $directory 'package-lock.json'
    $modules = Join-Path $directory 'node_modules'
    $stamp = Join-Path $modules '.install-lock-hash'
    $hash = (Get-FileHash -LiteralPath $lockfile -Algorithm SHA256).Hash
    if ((Test-Path -LiteralPath $stamp -PathType Leaf) -and
        ((Get-Content -LiteralPath $stamp -Raw).Trim() -eq $hash)) {
        Add-Step $label 'reused' 'Installed package-lock hash matches'
        return
    }
    Invoke-Checked $npm @('ci','--prefix',$directory,'--no-audit','--no-fund') $label
    [System.IO.File]::WriteAllText($stamp, $hash, [System.Text.UTF8Encoding]::new($false))
}

function Install-WingetPackage([string]$id) {
    if ($SkipMachineInstall) { throw "$id is missing; -SkipMachineInstall was specified" }
    $winget = Find-CommandPath 'winget.exe'
    if (-not $winget) { throw 'WinGet is unavailable. Install Microsoft App Installer, then rerun this file.' }
    Write-Host "`n== WinGet: $id =="
    & $winget install --id $id --exact --source winget --silent --accept-source-agreements --accept-package-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        & $winget upgrade --id $id --exact --source winget --silent --accept-source-agreements --accept-package-agreements --disable-interactivity
        if ($LASTEXITCODE -ne 0) { throw "WinGet could not install or upgrade $id" }
    }
    Refresh-ProcessPath
}

function Test-Node([string]$path) {
    if (-not $path) { return $false }
    $version = & $path --version 2>$null
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^v(\d+)') { return $false }
    return ([int]$matches[1] -ge 22)
}

function Find-Node {
    $candidates = @((Find-CommandPath 'node.exe'), (Join-Path $env:ProgramFiles 'nodejs\node.exe'))
    foreach ($candidate in $candidates) { if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf) -and (Test-Node $candidate)) { return $candidate } }
    return $null
}

function Test-Python([string]$path) {
    if (-not $path -or -not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
    & $path -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Find-Python {
    $candidates = @(
        $env:VIDEO_WORKFLOW_PYTHON,
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:ProgramFiles 'Python312\python.exe'),
        (Find-CommandPath 'python.exe')
    )
    foreach ($candidate in $candidates) { if (Test-Python $candidate) { return $candidate } }
    $launcher = Find-CommandPath 'py.exe'
    if ($launcher) {
        $path = & $launcher -3.12 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and (Test-Python $path)) { return $path.Trim() }
    }
    return $null
}

function Find-FFmpeg {
    $candidates = @((Find-CommandPath 'ffmpeg.exe'))
    $packages = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    if (Test-Path -LiteralPath $packages -PathType Container) {
        $folders = Get-ChildItem -LiteralPath $packages -Directory -Filter 'Gyan.FFmpeg_*' -ErrorAction SilentlyContinue
        foreach ($folder in $folders) {
            $candidates += @(Get-ChildItem -LiteralPath $folder.FullName -File -Recurse -Filter 'ffmpeg.exe' -ErrorAction SilentlyContinue | ForEach-Object FullName)
        }
    }
    foreach ($candidate in $candidates) {
        if (-not $candidate -or -not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        if (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $candidate) 'ffprobe.exe') -PathType Leaf) { return $candidate }
    }
    return $null
}

function Find-Git {
    $candidates = @((Find-CommandPath 'git.exe'), (Join-Path $env:ProgramFiles 'Git\cmd\git.exe'))
    foreach ($candidate in $candidates) { if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $candidate } }
    return $null
}

function Find-CMake {
    $candidates = @((Find-CommandPath 'cmake.exe'), (Join-Path $env:ProgramFiles 'CMake\bin\cmake.exe'))
    foreach ($candidate in $candidates) { if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $candidate } }
    return $null
}

if ($PlanOnly) {
    @(
        'Check Node >=22, Python >=3.10, FFmpeg/FFprobe, Git, and CMake',
        'Install missing machine tools with exact WinGet package IDs',
        'Create .venv and install Pillow',
        'Install pinned Hypit 0.3.1, HyperFrames 0.9.30, and Puppeteer 25.17.0',
        'Prepare a Chrome browser for HyperFrames and Puppeteer',
        'Install Hypit and HyperFrames Codex skills unless skipped',
        'Prepare Chinese Whisper ASR with a synthetic 1-second WAV unless skipped',
        'Write runtime.local.json and run workflow doctor'
    ) | ForEach-Object { Write-Host "[PLAN] $_" }
    exit 0
}

$exitCode = 0
$transcriptStarted = $false
try {
    if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
    Start-Transcript -LiteralPath (Join-Path $logDir 'install-transcript.txt') -Append | Out-Null
    $transcriptStarted = $true
    Refresh-ProcessPath

    $node = Find-Node
    if (-not $node) { Install-WingetPackage 'OpenJS.NodeJS.LTS'; $node = Find-Node }
    if (-not $node) { throw 'Node.js 22+ was not found after installation' }
    $report.tools.node = $node
    Add-Step 'Node.js' 'ok' (& $node --version)

    $python = Find-Python
    if (-not $python) { Install-WingetPackage 'Python.Python.3.12'; $python = Find-Python }
    if (-not $python) { throw 'Python 3.10+ was not found after installation' }
    $report.tools.python_base = $python
    Add-Step 'Python' 'ok' (& $python --version)

    $ffmpeg = Find-FFmpeg
    if (-not $ffmpeg) { Install-WingetPackage 'Gyan.FFmpeg'; $ffmpeg = Find-FFmpeg }
    if (-not $ffmpeg) { throw 'FFmpeg and FFprobe were not found after installation' }
    $env:Path = (Split-Path -Parent $ffmpeg) + ';' + $env:Path
    $report.tools.ffmpeg = $ffmpeg
    Add-Step 'FFmpeg/FFprobe' 'ok' $ffmpeg

    $git = Find-Git
    if (-not $git) { Install-WingetPackage 'Git.Git'; $git = Find-Git }
    if (-not $git) { throw 'Git was not found after installation' }
    $env:Path = (Split-Path -Parent $git) + ';' + $env:Path
    $report.tools.git = $git
    Add-Step 'Git' 'ok' $git

    if (-not $SkipASRPrep) {
        $cmake = Find-CMake
        if (-not $cmake) { Install-WingetPackage 'Kitware.CMake'; $cmake = Find-CMake }
        if (-not $cmake) { throw 'CMake was not found after installation' }
        $env:Path = (Split-Path -Parent $cmake) + ';' + $env:Path
        $report.tools.cmake = $cmake
        Add-Step 'CMake' 'ok' $cmake
    }

    $venvPython = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) { Invoke-Checked $python @('-m','venv',(Join-Path $root '.venv')) 'Create Python environment' }
    Invoke-Checked $venvPython @('-m','pip','install','--disable-pip-version-check','--no-input','-r',(Join-Path $root 'requirements-minimal.txt')) 'Install Python packages'
    $report.tools.python = $venvPython
    Add-Step 'Pillow' 'ok' (& $venvPython -c 'import PIL; print(PIL.__version__)')

    $npm = Find-CommandPath 'npm.cmd'
    if (-not $npm) { $npm = Join-Path (Split-Path -Parent $node) 'npm.cmd' }
    if (-not (Test-Path -LiteralPath $npm -PathType Leaf)) { throw 'npm.cmd was not found with Node.js' }
    $env:PUPPETEER_SKIP_DOWNLOAD = '1'
    Install-NpmLocked (Join-Path $root 'hypit-local') 'Install Hypit 0.3.1'
    Install-NpmLocked (Join-Path $root 'animation-local') 'Install HyperFrames and Puppeteer'
    $hypitEntry = Join-Path $root 'hypit-local\node_modules\@hypit\hypit\bin\hypit.mjs'
    $hyperframes = Join-Path $root 'animation-local\node_modules\.bin\hyperframes.cmd'
    if (-not (Test-Path -LiteralPath $hypitEntry -PathType Leaf)) { throw 'Hypit CLI entry is missing after npm ci' }
    if (-not (Test-Path -LiteralPath $hyperframes -PathType Leaf)) { throw 'HyperFrames CLI is missing after npm ci' }
    Invoke-Checked $node @($hypitEntry,'version') 'Check Hypit CLI'
    Write-Host "`n== Find or prepare animation browser =="
    $browserOutput = & $hyperframes browser path
    if ($LASTEXITCODE -ne 0) { throw 'HyperFrames could not find or prepare a browser' }
    $browser = ($browserOutput | Select-Object -Last 1).Trim()
    if (-not (Test-Path -LiteralPath $browser -PathType Leaf)) { throw 'Animation browser path is invalid' }
    $report.tools.hypit_dir = Join-Path $root 'hypit-local\node_modules\@hypit\hypit'
    $report.tools.hyperframes = $hyperframes
    $report.tools.browser = $browser
    Add-Step 'Animation browser' 'ok' $browser

    if (-not $SkipSkillInstall) {
        $npx = Find-CommandPath 'npx.cmd'
        if (-not $npx) { $npx = Join-Path (Split-Path -Parent $node) 'npx.cmd' }
        if (-not (Test-Path -LiteralPath $npx -PathType Leaf)) { throw 'npx.cmd was not found with Node.js' }
        Push-Location $root
        try {
            Invoke-Checked $npx @('-y','skills@latest','add','hypit-ai/hypit','--agent','codex','--yes') 'Install Hypit Codex skill'
            Invoke-Checked $hyperframes @('skills') 'Install HyperFrames Codex skills'
        } finally { Pop-Location }
        Add-Step 'Codex skills' 'ok' 'Hypit and HyperFrames skills installed'
    } else { Add-Step 'Codex skills' 'skipped' 'SkipSkillInstall was specified' }

    if (-not $SkipASRPrep) {
        $asrDir = Join-Path $logDir 'asr-prep'
        New-Item -ItemType Directory -Path $asrDir -Force | Out-Null
        $sample = Join-Path $asrDir 'sample.wav'
        Invoke-Checked $ffmpeg @('-hide_banner','-loglevel','error','-y','-f','lavfi','-i','anullsrc=r=16000:cl=mono','-t','1','-c:a','pcm_s16le',$sample) 'Create synthetic ASR check audio'
        Invoke-Checked $hyperframes @('transcribe',$sample,'--engine','whisper','--model','small','--language','zh','--dir',$asrDir,'--json') 'Prepare local Chinese ASR'
        Add-Step 'Chinese ASR' 'ok' 'Whisper runtime and model prepared with synthetic audio'
    } else { Add-Step 'Chinese ASR' 'skipped' 'SkipASRPrep was specified' }

    $configPath = Join-Path $root 'runtime.local.json'
    $config = @{ python = ''; ffmpeg = ''; hypit_dir = ''; hyperframes = ''; browser = '' }
    if (Test-Path -LiteralPath $configPath -PathType Leaf) {
        $existing = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($property in $existing.PSObject.Properties) { $config[$property.Name] = $property.Value }
    }
    $config.python = $venvPython
    $config.ffmpeg = $ffmpeg
    $config.hypit_dir = $report.tools.hypit_dir
    $config.hyperframes = $hyperframes
    $config.browser = $browser
    [System.IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
    Add-Step 'Local configuration' 'ok' $configPath

    $workflowCmd = Join-Path $root '工作流工具.cmd'
    Invoke-Checked $workflowCmd @('doctor') 'Workflow doctor'
    Add-Step 'Workflow doctor' 'ok' 'Core checks passed'
    $report.status = 'complete'
    Write-Host "`nInstallation complete. Open this folder in Codex and read 开始使用.md."
} catch {
    $exitCode = 1
    $report.status = 'incomplete'
    $report.errors += $_.Exception.Message
    Write-Error $_.Exception.Message -ErrorAction Continue
} finally {
    $report.finished_at = (Get-Date).ToString('o')
    Save-Report
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
    Write-Host "Report: $reportPath"
}
exit $exitCode
