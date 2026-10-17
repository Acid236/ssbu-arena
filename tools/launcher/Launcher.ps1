# SPDX-License-Identifier: GPL-3.0-or-later
# SSBU recomp launcher: one window to set the player name (and the account id made from it), local wireless over the
# internet (server, room, ping), the save folder (open it, bring in a save from Ryujinx or from any folder), the DLC list,
# check what the game needs and start it. Windows PowerShell 5.1 + WinForms: nothing to install.
# Lives in build\ (scripts\setup.py link copies it there, with "Avvia SSBU.bat"); in the portable copy too.
# Files it writes: build\config\online.ini, build\config\account.txt, build\config\dlc.txt, build\config\launcher.ini.
# The game's own data is only read. ASCII only (Windows PowerShell reads scripts in the ANSI code page).
param([switch]$Check)
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- where things are
$Build = Split-Path -Parent $MyInvocation.MyCommand.Path
$Work = Join-Path $Build 'work'
$Cfg = Join-Path $Build 'config'
$Exe = Join-Path $Work 'ssbu_native.exe'
$MainElf = Join-Path $Build 'binaries\13.0.4\main.elf'
$Fonts = Join-Path $Build 'sysdata\fonts'
$Portable = Test-Path (Join-Path $Build '..\dump\romfs')
$RomFS = $null
if ($Portable) { $RomFS = (Resolve-Path (Join-Path $Build '..\dump\romfs')).Path }
elseif (Test-Path (Join-Path $Build 'state.json')) {
    try { $RomFS = (Get-Content (Join-Path $Build 'state.json') -Raw | ConvertFrom-Json).dump.romfs } catch { }
}
New-Item -ItemType Directory -Force $Cfg | Out-Null

function Read-Ini($path) {
    $h = @{}
    if (Test-Path $path) { foreach ($l in Get-Content $path) { if ($l -match '^\s*([A-Za-z_]+)\s*=\s*(.*?)\s*$' -and $l -notmatch '^\s*[#;]') { $h[$Matches[1].ToLower()] = $Matches[2] } } }
    return $h
}
$LauncherIni = Join-Path $Cfg 'launcher.ini'
$OnlineIni = Join-Path $Cfg 'online.ini'
$L = Read-Ini $LauncherIni
$O = Read-Ini $OnlineIni
$DefaultSaves = if ($Portable) { Join-Path (Split-Path $Build -Parent) 'saves' } else { Join-Path $Build 'saves' }
$Saves = if ($L['saves']) { $L['saves'] } else { $DefaultSaves }
$HasOnline = (Test-Path $Exe) -and ([System.IO.File]::ReadAllText($Exe, [System.Text.Encoding]::ASCII).Contains('ssbu-ldn-fingerprint'))

# the account id from the name: the same name always gives the same id (two players must use two names)
function Get-UidFromName([string]$name) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $b = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes('ssbu-recomp account id|' + $name))
    return (($b[0..15] | ForEach-Object { $_.ToString('x2') }) -join '')
}

# ---------------------------------------------------------------- the window
$f = New-Object System.Windows.Forms.Form
$f.Text = 'SSBU recomp - Launcher'
$f.Size = New-Object System.Drawing.Size(560, 640)
$f.StartPosition = 'CenterScreen'
$f.FormBorderStyle = 'FixedDialog'
$f.MaximizeBox = $false
$font = New-Object System.Drawing.Font('Segoe UI', 9)
$bold = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
$f.Font = $font
$tip = New-Object System.Windows.Forms.ToolTip

function Add-Label($parent, $text, $x, $y, $w = 120, $b = $false) {
    $l = New-Object System.Windows.Forms.Label; $l.Text = $text; $l.Location = New-Object System.Drawing.Point($x, $y)
    $l.Size = New-Object System.Drawing.Size($w, 20); if ($b) { $l.Font = $bold }; $parent.Controls.Add($l); return $l
}
function Add-Box($parent, $text, $x, $y, $w) {
    $t = New-Object System.Windows.Forms.TextBox; $t.Text = $text; $t.Location = New-Object System.Drawing.Point($x, $y)
    $t.Size = New-Object System.Drawing.Size($w, 22); $parent.Controls.Add($t); return $t
}
function Add-Button($parent, $text, $x, $y, $w, $action) {
    $b = New-Object System.Windows.Forms.Button; $b.Text = $text; $b.Location = New-Object System.Drawing.Point($x, $y)
    $b.Size = New-Object System.Drawing.Size($w, 26); $b.Add_Click($action); $parent.Controls.Add($b); return $b
}
function Add-Group($text, $y, $h) {
    $g = New-Object System.Windows.Forms.GroupBox; $g.Text = $text; $g.Location = New-Object System.Drawing.Point(12, $y)
    $g.Size = New-Object System.Drawing.Size(520, $h); $f.Controls.Add($g); return $g
}

# player
$gp = Add-Group 'Giocatore' 10 82
Add-Label $gp 'Nome' 12 26 | Out-Null
$name = Add-Box $gp ($(if ($O['nickname']) { $O['nickname'] } else { '' })) 130 23 200
$tip.SetToolTip($name, 'Il nome che vedono gli altri giocatori (1-32 caratteri). Non viene mai usato il nome utente di Windows.')
$uidLabel = Add-Label $gp '' 130 52 380
function Update-Uid { $uidLabel.Text = if ($name.Text.Trim()) { 'ID giocatore (dal nome): ' + (Get-UidFromName $name.Text.Trim()).Substring(0, 16) + '...' } else { 'Scrivi un nome' } }
$name.Add_TextChanged({ Update-Uid }); Update-Uid

# online
$go = Add-Group 'Online (Wireless locale via internet)' 100 150
$onlineOn = New-Object System.Windows.Forms.CheckBox; $onlineOn.Text = 'Attiva'; $onlineOn.Location = New-Object System.Drawing.Point(12, 22)
$onlineOn.Checked = [bool]($O['server'] -and $O['room']); $go.Controls.Add($onlineOn)
Add-Label $go 'Server (ip:porta)' 12 52 | Out-Null
$server = Add-Box $go ($(if ($O['server']) { $O['server'] } else { '' })) 130 49 250
Add-Label $go 'Stanza (password)' 12 82 | Out-Null
$room = Add-Box $go ($(if ($O['room']) { $O['room'] } else { '' })) 130 79 250
$tip.SetToolTip($room, 'Chi usa la stessa password vede le stesse stanze nel Wireless locale.')
$pingOn = New-Object System.Windows.Forms.CheckBox; $pingOn.Text = 'Mostra il ping a schermo'; $pingOn.Location = New-Object System.Drawing.Point(130, 108)
$pingOn.Size = New-Object System.Drawing.Size(250, 22); $pingOn.Checked = ($O['ping_overlay'] -ne 'off'); $go.Controls.Add($pingOn)
if (-not $HasOnline) {
    $onlineOn.Checked = $false; $onlineOn.Enabled = $false; $server.Enabled = $false; $room.Enabled = $false; $pingOn.Enabled = $false
    Add-Label $go 'Questa build non ha l''online (setup.py --ldn-online on)' 200 22 300 | Out-Null
}
function Update-Online { $e = $onlineOn.Checked -and $HasOnline; $server.Enabled = $e; $room.Enabled = $e; $pingOn.Enabled = $e }
$onlineOn.Add_CheckedChanged({ Update-Online }); Update-Online

# saves
$gs = Add-Group 'Salvataggi' 260 120
$savesLabel = Add-Label $gs '' 12 22 495
function Update-Saves {
    $sd = Join-Path $Saves 'save\save_data\system_data.bin'
    $savesLabel.Text = 'Cartella: ' + $Saves + $(if (Test-Path $sd) { '   (salvataggio presente)' } else { '   (vuota: il gioco ne crea uno nuovo)' })
}
Update-Saves
Add-Button $gs 'Apri cartella' 12 48 110 { New-Item -ItemType Directory -Force $Saves | Out-Null; Start-Process explorer.exe $Saves } | Out-Null
Add-Button $gs 'Cambia cartella...' 130 48 120 {
    $d = New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description = 'Cartella dei salvataggi del gioco'
    if ($d.ShowDialog() -eq 'OK') { $script:Saves = $d.SelectedPath; Update-Saves }
} | Out-Null
function Import-Save([string]$from) {
    # $from: a folder holding save_data\ (or the files of save_data themselves)
    $src = if (Test-Path (Join-Path $from 'save_data\system_data.bin')) { Join-Path $from 'save_data' } elseif (Test-Path (Join-Path $from 'system_data.bin')) { $from } else { $null }
    if (-not $src) { [System.Windows.Forms.MessageBox]::Show('In quella cartella non c''e'' un salvataggio di Smash (manca system_data.bin).', 'Salvataggio') | Out-Null; return }
    if (Get-Process ssbu_native -ErrorAction SilentlyContinue) { [System.Windows.Forms.MessageBox]::Show('Chiudi il gioco prima di importare un salvataggio.', 'Salvataggio') | Out-Null; return }
    $dst = Join-Path $Saves 'save'
    if (Test-Path $dst) {
        $bak = Join-Path $Saves ('save-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        Move-Item $dst $bak
    }
    New-Item -ItemType Directory -Force (Join-Path $dst 'save_data') | Out-Null
    Copy-Item (Join-Path $src '*') (Join-Path $dst 'save_data') -Recurse -Force
    Get-ChildItem $Saves -Directory -Filter 'save.work.*' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
    Update-Saves
    [System.Windows.Forms.MessageBox]::Show('Salvataggio importato. Quello di prima, se c''era, e'' in ' + $(if ($bak) { $bak } else { '(nessuno)' }), 'Salvataggio') | Out-Null
}
Add-Button $gs 'Importa da Ryujinx' 258 48 130 {
    $root = Join-Path $env:APPDATA 'Ryujinx\bis\user\save'
    $found = $null
    if (Test-Path $root) {
        foreach ($d in Get-ChildItem $root -Directory) {
            $x = Join-Path $d.FullName 'ExtraData0'
            if ((Test-Path $x) -and ([System.IO.File]::ReadAllBytes($x)[0..7] -join ',') -eq '0,224,22,0,128,106,0,1') {
                $c = @('0', '1') | ForEach-Object { Join-Path $d.FullName $_ } | Where-Object { Test-Path (Join-Path $_ 'save_data\system_data.bin') } |
                     Sort-Object { (Get-Item (Join-Path $_ 'save_data\system_data.bin')).LastWriteTime } -Descending | Select-Object -First 1
                if ($c) { $found = $c }
            }
        }
    }
    if ($found) { Import-Save $found } else { [System.Windows.Forms.MessageBox]::Show('Nessun salvataggio di Smash trovato in Ryujinx (' + $root + '). Usa "Importa da cartella".', 'Salvataggio') | Out-Null }
} | Out-Null
Add-Button $gs 'Importa da cartella...' 396 48 115 {
    $d = New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description = 'La cartella che contiene save_data (o system_data.bin): da Ryujinx, yuzu e simili, o da un dump della console'
    if ($d.ShowDialog() -eq 'OK') { Import-Save $d.SelectedPath }
} | Out-Null
$saveHelp = Add-Label $gs 'Vanno bene i salvataggi di Ryujinx, yuzu e simili o della console: la cartella con save_data.' 12 84 500

# DLC
$gd = Add-Group 'DLC' 390 56
$dlcFile = Join-Path $Cfg 'dlc.txt'
function Dlc-Count { if (Test-Path $dlcFile) { @(Get-Content $dlcFile | Where-Object { $_ -match '^\s*0x[0-9a-fA-F]+|^\s*[0-9]+' }).Count } else { 0 } }
$dlcLabel = Add-Label $gd ('DLC attivi: ' + (Dlc-Count)) 12 24 150
Add-Button $gd 'Attiva da cartella dei tuoi DLC...' 170 20 220 {
    $d = New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description = 'La cartella con i dump dei TUOI DLC di Smash (file con [01006A800016Fxxx] nel nome)'
    if ($d.ShowDialog() -ne 'OK') { return }
    $rows = @{}
    foreach ($fl in Get-ChildItem $d.SelectedPath -File -Recurse) {
        foreach ($m in [regex]::Matches($fl.Name, '\[([0-9A-Fa-f]{16})\]')) {
            $tid = [Convert]::ToUInt64($m.Groups[1].Value, 16); $idx = $tid - 0x01006A800016E000 - 0x1000
            if ($idx -gt 0 -and $idx -lt 0x1000) { $rows[[int]$idx] = $fl.BaseName }
        }
    }
    if ($rows.Count -eq 0) { [System.Windows.Forms.MessageBox]::Show('Nessun DLC di Smash riconosciuto dai nomi dei file.', 'DLC') | Out-Null; return }
    $out = @('# add-on contents owned; written by the launcher from the file names of the player''s own DLC dumps')
    foreach ($k in ($rows.Keys | Sort-Object)) { $out += ('0x{0:x3}   # {1}' -f $k, $rows[$k]) }
    Set-Content -Path $dlcFile -Value $out -Encoding ASCII
    $dlcLabel.Text = 'DLC attivi: ' + (Dlc-Count)
} | Out-Null
Add-Button $gd 'Disattiva' 398 20 110 { if (Test-Path $dlcFile) { Remove-Item $dlcFile }; $dlcLabel.Text = 'DLC attivi: 0' } | Out-Null

# status + buttons
$status = New-Object System.Windows.Forms.TextBox; $status.Multiline = $true; $status.ReadOnly = $true; $status.ScrollBars = 'Vertical'
$status.Location = New-Object System.Drawing.Point(12, 452); $status.Size = New-Object System.Drawing.Size(520, 100); $status.Font = New-Object System.Drawing.Font('Consolas', 8.5)
$f.Controls.Add($status)
function Say($t) { $status.AppendText($t + "`r`n") }

function Save-Settings {
    $n = $name.Text.Trim()
    if ($onlineOn.Checked -and $HasOnline) {
        Set-Content -Path $OnlineIni -Encoding ASCII -Value @(
            '# written by the launcher (build\Launcher.ps1); see tools/online/online.ini.example',
            ('server = ' + $server.Text.Trim()), ('room = ' + $room.Text.Trim()), ('nickname = ' + $n),
            ('ping_overlay = ' + $(if ($pingOn.Checked) { 'on' } else { 'off' })))
        if ($n) { Set-Content -Path (Join-Path $Cfg 'account.txt') -Value (Get-UidFromName $n) -Encoding ASCII }
    } elseif (Test-Path $OnlineIni) {
        Move-Item -Force $OnlineIni (Join-Path $Cfg 'online.ini.off')      # off: kept aside, back when it is turned on again
    }
    Set-Content -Path $LauncherIni -Encoding ASCII -Value @('# written by the launcher', ('saves = ' + $Saves), ('nickname = ' + $n))
}
if (-not (Test-Path $OnlineIni) -and (Test-Path (Join-Path $Cfg 'online.ini.off'))) {
    $O = Read-Ini (Join-Path $Cfg 'online.ini.off')
    if ($O['server']) { $server.Text = $O['server'] }; if ($O['room']) { $room.Text = $O['room'] }
    if (-not $name.Text -and $O['nickname']) { $name.Text = $O['nickname'] }
}
if (-not $name.Text -and $L['nickname']) { $name.Text = $L['nickname'] }

function Test-All([switch]$Quiet) {
    $status.Clear(); $bad = 0
    $files = @(@($Exe, 'eseguibile'), @((Join-Path $Work 'ssbu_game_eh_o1.dll'), 'codice del gioco'), @($MainElf, 'main.elf'))
    foreach ($x in $files) { if (-not (Test-Path $x[0])) { Say ('[NO] manca ' + $x[1] + ': ' + $x[0]); $bad++ } }
    $mods = @(Get-ChildItem (Join-Path $Work 'nro_bin_eh_o2') -Filter *.dll -ErrorAction SilentlyContinue).Count
    if ($mods -lt 98) { Say "[NO] moduli dei personaggi: $mods su 98"; $bad++ }
    if (-not $RomFS -or -not (Test-Path (Join-Path $RomFS 'data.arc'))) { Say '[NO] data.arc non trovato (RomFS del dump)'; $bad++ }
    if (-not (Test-Path "$env:WINDIR\System32\vulkan-1.dll")) { Say '[NO] Vulkan non trovato: aggiorna il driver della scheda video'; $bad++ }
    foreach ($c in @(@('Microsoft.WebMediaExtensions', 'Web Media Extensions', '9N5TDP8VCMHS'), @('Microsoft.VP9VideoExtensions', 'VP9 Video Extensions', '9N4D0MSMP0PT'))) {
        if (-not (Get-AppxPackage $c[0] -ErrorAction SilentlyContinue)) {
            if (-not $Quiet -and [System.Windows.Forms.MessageBox]::Show("Manca " + $c[1] + " (serve al filmato d'apertura: senza, schermo nero). La installo dal Microsoft Store?", 'Requisiti', 'YesNo') -eq 'Yes') {
                if (Get-Command winget -ErrorAction SilentlyContinue) { & winget install --id $c[2] --source msstore --accept-package-agreements --accept-source-agreements | Out-Null }
                else { Start-Process "ms-windows-store://pdp/?ProductId=$($c[2])" }
            }
            if (-not (Get-AppxPackage $c[0] -ErrorAction SilentlyContinue)) { Say ('[NO] manca ' + $c[1]); $bad++ } else { Say ('[OK] ' + $c[1] + ' installata') }
        }
    }
    if ($onlineOn.Checked) {
        if (-not $name.Text.Trim()) { Say '[NO] online: scrivi un nome'; $bad++ }
        elseif ([System.Text.Encoding]::UTF8.GetByteCount($name.Text.Trim()) -gt 32) { Say '[NO] nome troppo lungo (max 32 byte)'; $bad++ }
        if ($server.Text.Trim() -notmatch '^[^\s:]+(:\d+)?$') { Say '[NO] online: server nel formato ip:porta'; $bad++ }
        if (-not $room.Text.Trim()) { Say '[NO] online: scrivi la password della stanza'; $bad++ }
    }
    if (Get-Process ssbu_native -ErrorAction SilentlyContinue) { Say '[NO] il gioco e'' gia'' aperto'; $bad++ }
    if ($bad -eq 0) { Say ('[OK] tutto pronto' + $(if ($onlineOn.Checked) { ' (online attivo come "' + $name.Text.Trim() + '")' } else { ' (online spento)' })) }
    return $bad
}

$script:game = $null
$timer = New-Object System.Windows.Forms.Timer; $timer.Interval = 1000
$timer.Add_Tick({
    if ($script:game -and $script:game.HasExited) {
        $timer.Stop(); $f.WindowState = 'Normal'; $play.Enabled = $true
        $code = $script:game.ExitCode; $script:game = $null
        if ($code -ne 0) {
            Say "Il gioco si e' chiuso con il codice $code. Ultime righe di game.log:"
            Get-Content (Join-Path $Build 'game.log') -Tail 8 -ErrorAction SilentlyContinue | ForEach-Object { Say ('  ' + $_) }
        } else { Say 'Gioco chiuso.' }
    }
})
Add-Button $f 'Controlla' 12 562 120 { Save-Settings; Test-All | Out-Null } | Out-Null
$play = Add-Button $f 'GIOCA' 392 562 140 {
    Save-Settings
    if ((Test-All) -gt 0) { return }
    New-Item -ItemType Directory -Force $Saves, (Join-Path $Build 'cache') | Out-Null
    $env:SSBU_ROMFS = $RomFS; $env:SSBU_USERDATA = $Saves; $env:SSBU_FONTS = $Fonts
    $cacheMark = @(Get-ChildItem (Join-Path $Build 'cache\vk') -Filter 'prepared_*.txt' -ErrorAction SilentlyContinue).Count
    if ($cacheMark -eq 0) { Say 'Primo avvio: prima di giocare il gioco prepara gli shader per questa scheda video (qualche minuto).' }
    $script:game = Start-Process -FilePath $Exe -ArgumentList @('"' + $MainElf + '"', '0') -WorkingDirectory $Work -PassThru `
                   -RedirectStandardOutput (Join-Path $Build 'game.log')
    Say 'Gioco avviato (log: build\game.log).'
    $play.Enabled = $false; $f.WindowState = 'Minimized'; $timer.Start()
}
$play.Font = $bold
Add-Button $f 'Apri log' 140 562 90 { $p = Join-Path $Build 'game.log'; if (Test-Path $p) { Start-Process notepad.exe $p } } | Out-Null

if ($Check) { Test-All -Quiet | Out-Null; $status.Lines | ForEach-Object { Write-Output $_ }; exit }
Test-All -Quiet | Out-Null
[void]$f.ShowDialog()
