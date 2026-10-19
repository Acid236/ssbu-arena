# Install SSBU.bat runs this: it finds Python 3.10 or newer with tkinter, or offers to install it (the official
# python.org installer, checked against its published SHA-256, installed for this user only), then opens the
# installer window (scripts\installer_gui.py). Nothing else is installed here.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$repo = Split-Path -Parent $PSScriptRoot
$pyVersion = '3.13.16'
$pyUrl = "https://www.python.org/ftp/python/$pyVersion/python-$pyVersion-amd64.exe"
$pySha256 = 'fb4f9f5d438b2396da0086dc70b935c530cb578e37adc6d354f7ad2037fee83b'   # python.org release page, 2026-10-19

function Test-Python([string]$exe) {
    if (-not $exe -or -not (Test-Path $exe)) { return $false }
    if ($exe -like '*\WindowsApps\*') { return $false }          # the Microsoft Store alias, not a Python
    try {
        & $exe -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Find-Python {
    $c = @()
    try { $c += (& py -3 -c "import sys; print(sys.executable)" 2>$null) } catch {}
    try { $c += (Get-Command python.exe -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source }) } catch {}
    foreach ($root in @("$env:LOCALAPPDATA\Programs\Python", $env:ProgramFiles, 'C:\')) {
        if (Test-Path $root) {
            $c += Get-ChildItem $root -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue |
                  Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName 'python.exe' }
        }
    }
    foreach ($exe in $c) { if (Test-Python $exe) { return $exe } }
    return $null
}

function Say([string]$text, [string]$buttons = 'OK', [string]$icon = 'Information') {
    return [System.Windows.Forms.MessageBox]::Show($text, 'SSBU installer', $buttons, $icon)
}

try {
    $py = Find-Python
    if (-not $py) {
        $ans = Say ("The installer needs Python (free, about 30 MB), which is not on this PC.`n`n" +
                    "Download Python $pyVersion from python.org and install it for your user only?`n" +
                    "(It can be removed later from Settings > Apps.)") 'YesNo' 'Question'
        if ($ans -ne 'Yes') { exit 1 }
        $dl = Join-Path $repo 'build\downloads'
        New-Item -ItemType Directory -Force $dl | Out-Null
        $file = Join-Path $dl "python-$pyVersion-amd64.exe"
        if (-not (Test-Path $file) -or (Get-FileHash $file -Algorithm SHA256).Hash -ne $pySha256.ToUpper()) {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -Uri $pyUrl -OutFile $file -UseBasicParsing
        }
        $hash = (Get-FileHash $file -Algorithm SHA256).Hash
        if ($hash -ne $pySha256.ToUpper()) {
            Remove-Item $file -Force
            Say "The downloaded Python installer does not match its published SHA-256 (got $hash). Nothing was installed." 'OK' 'Error' | Out-Null
            exit 1
        }
        # /passive: a progress bar and no questions; for this user only, no PATH or file-type changes
        $p = Start-Process -FilePath $file -Wait -PassThru -ArgumentList '/passive', 'InstallAllUsers=0', 'Include_launcher=0',
             'Include_test=0', 'Include_doc=0', 'Shortcuts=0', 'AssociateFiles=0', 'PrependPath=0'
        $py = Find-Python
        if ($p.ExitCode -ne 0 -or -not $py) {
            Say "Python could not be installed (code $($p.ExitCode)). Install it from https://www.python.org/downloads/ and run Install SSBU.bat again." 'OK' 'Error' | Out-Null
            exit 1
        }
    }
    $pyw = Join-Path (Split-Path -Parent $py) 'pythonw.exe'
    if (-not (Test-Path $pyw)) { $pyw = $py }
    New-Item -ItemType Directory -Force (Join-Path $repo 'build') | Out-Null
    Set-Content -Path (Join-Path $repo 'build\python_path.txt') -Value $py -Encoding ASCII -ErrorAction SilentlyContinue
    Start-Process -FilePath $pyw -ArgumentList "`"$repo\scripts\installer_gui.py`"" -WorkingDirectory $repo
} catch {
    Say "The installer could not start: $($_.Exception.Message)" 'OK' 'Error' | Out-Null
    exit 1
}
