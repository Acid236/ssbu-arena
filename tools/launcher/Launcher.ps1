# SPDX-License-Identifier: GPL-3.0-or-later
# SSBU recomp launcher: one window to set the player name (and the account id made from it), local wireless over the
# internet (server, room, ping), the save folder (open it, bring in a save from Ryujinx or from any folder), the DLC list,
# check what the game needs and start it. Windows PowerShell 5.1 + WinForms: nothing to install.
# Lives in build\ (scripts\setup.py link copies it there, with "Avvia SSBU.bat"); in the portable copy too.
# Files it writes: build\config\online.ini, build\config\account.txt, build\config\dlc.txt, build\config\launcher.ini,
# and some keys of build\config\graphics.ini (aspect, window, width, height, latency) and controllers.ini ([players], [keyboard]).
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
$f.Size = New-Object System.Drawing.Size(560, 800)
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
$pingOn.Size = New-Object System.Drawing.Size(170, 22); $pingOn.Checked = ($O['ping_overlay'] -ne 'off'); $go.Controls.Add($pingOn)
Add-Label $go 'Ritardo input' 305 111 80 | Out-Null
$delay = New-Object System.Windows.Forms.ComboBox; $delay.DropDownStyle = 'DropDownList'; $delay.Location = New-Object System.Drawing.Point(388, 108)
$delay.Size = New-Object System.Drawing.Size(120, 22); $go.Controls.Add($delay)
[void]$delay.Items.Add('Auto (gioco)'); 0..8 | ForEach-Object { [void]$delay.Items.Add($(if ($_ -eq 0) { '0 (minimo)' } else { [string]$_ })) }
$delay.SelectedIndex = $(if ($O['input_delay'] -match '^\d+$' -and [int]$O['input_delay'] -le 8) { [int]$O['input_delay'] + 1 } else { 0 })
$tip.SetToolTip($delay, 'Frame di anticipo dell''input nel Wireless locale. Auto: quelli che sceglie il gioco (circa 4 + il ping; 5-6 frame dal tasto all''azione, offline 1). 0: 2 frame in tutto. Se e'' troppo basso per il ping il gioco aspetta l''altro giocatore (scatti): alza di 1. Ognuno puo'' usare il suo valore.')
if (-not $HasOnline) {
    $onlineOn.Checked = $false; $onlineOn.Enabled = $false; $server.Enabled = $false; $room.Enabled = $false; $pingOn.Enabled = $false; $delay.Enabled = $false
    Add-Label $go 'Questa build non ha l''online (setup.py --ldn-online on)' 200 22 300 | Out-Null
}
function Update-Online { $e = $onlineOn.Checked -and $HasOnline; $server.Enabled = $e; $room.Enabled = $e; $pingOn.Enabled = $e; $delay.Enabled = $e }
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

# ini files of the game: change some keys, keep everything else (comments, other sections) as it is
function Set-IniValues([string]$path, [string]$section, [hashtable]$vals) {
    $lines = if (Test-Path $path) { @(Get-Content $path) } else { @() }
    $out = New-Object System.Collections.Generic.List[string]
    $left = @{}; foreach ($k in $vals.Keys) { $left[$k.ToLower()] = $vals[$k] }
    $inTarget = -not $section; $seen = -not $section
    foreach ($l in $lines) {
        if ($section -and $l -match '^\s*\[(.+?)\]\s*$') {
            $hdr = $Matches[1].Trim()
            if ($inTarget) { foreach ($k in @($left.Keys)) { $out.Add($k + ' = ' + $left[$k]) }; $left.Clear() }
            $inTarget = ($hdr -ieq $section); if ($inTarget) { $seen = $true }
        } elseif ($inTarget -and $l -notmatch '^\s*[#;]' -and $l -match '^\s*([A-Za-z0-9_.]+)\s*=' -and $left.ContainsKey($Matches[1].ToLower())) {
            $k = $Matches[1].ToLower(); $out.Add($Matches[1] + ' = ' + $left[$k]); $left.Remove($k); continue
        }
        $out.Add($l)
    }
    if ($left.Count) {
        if (-not $seen) { $out.Add(''); $out.Add('[' + $section + ']') }
        foreach ($k in @($left.Keys)) { $out.Add($k + ' = ' + $left[$k]) }
    }
    Set-Content -Path $path -Value $out -Encoding ASCII
}
function Add-Combo($parent, $items, $x, $y, $w, $editable = $false) {
    $c = New-Object System.Windows.Forms.ComboBox; $c.Location = New-Object System.Drawing.Point($x, $y); $c.Size = New-Object System.Drawing.Size($w, 22)
    if (-not $editable) { $c.DropDownStyle = 'DropDownList' }; foreach ($i in $items) { [void]$c.Items.Add($i) }; $parent.Controls.Add($c); return $c
}

# video (graphics.ini)
$GfxIni = Join-Path $Cfg 'graphics.ini'
$G = Read-Ini $GfxIni
$gv = Add-Group 'Video' 454 150
$gv.Size = New-Object System.Drawing.Size(255, 150)
Add-Label $gv 'Proporzioni' 10 25 80 | Out-Null
$aspect = Add-Combo $gv @('16:9 (bande nere)', 'Stirata (riempie)') 92 22 150
$aspect.SelectedIndex = $(if ($G['aspect'] -eq 'stretch') { 1 } else { 0 })
$tip.SetToolTip($aspect, '16:9: il gioco tiene le sue proporzioni, con bande nere se la finestra o lo schermo hanno un''altra forma. Stirata: riempie tutto.')
Add-Label $gv 'Finestra' 10 55 80 | Out-Null
$winMode = Add-Combo $gv @('Finestra', 'Senza bordi', 'Schermo intero') 92 52 150
$winMode.SelectedIndex = $(switch ($G['window']) { 'borderless' { 1 } 'fullscreen' { 2 } default { 0 } })
Add-Label $gv 'Dimensione' 10 85 80 | Out-Null
$winSize = Add-Combo $gv @('1280x720', '1600x900', '1920x1080', '2560x1440') 92 82 150 $true
$winSize.Text = $(if ($G['width'] -and $G['height']) { $G['width'] + 'x' + $G['height'] } else { '1280x720' })
$tip.SetToolTip($winSize, 'Dimensione della finestra (solo in modalita'' Finestra). Puoi scriverne una tua, es. 1366x768.')
Add-Label $gv 'Latenza input' 10 115 80 | Out-Null
$latency = Add-Combo $gv @('Normale', 'Bassa', 'Minima') 92 112 150
$latency.SelectedIndex = $(switch ($G['latency']) { 'low' { 1 } 'lowest' { 2 } default { 0 } })
$tip.SetToolTip($latency, 'Bassa: il gioco legge il controller piu'' tardi in ogni frame (2-5 ms in meno). Minima: anche l''immagine va a schermo appena pronta (circa 4 ms in meno ancora, ma i frame non durano tutti uguale). Non cambia i frame di logica del gioco ne'' il buffer del Wireless locale.')
function Update-WinSize { $winSize.Enabled = ($winMode.SelectedIndex -eq 0) }
$winMode.Add_SelectedIndexChanged({ Update-WinSize }); Update-WinSize

# controllers (controllers.ini)
$PadIni = Join-Path $Cfg 'controllers.ini'
$gc = New-Object System.Windows.Forms.GroupBox; $gc.Text = 'Controller'; $gc.Location = New-Object System.Drawing.Point(277, 454)
$gc.Size = New-Object System.Drawing.Size(255, 150); $f.Controls.Add($gc)
Add-Label $gc 'Giocatore 1' 10 25 72 | Out-Null
$p1 = Add-Combo $gc @() 82 22 112
Add-Label $gc 'Giocatore 2' 10 55 72 | Out-Null
$p2 = Add-Combo $gc @() 82 52 112
Add-Label $gc 'Tastiera' 10 85 72 | Out-Null
$kb = Add-Combo $gc @('Automatica', 'Giocatore 1', 'Giocatore 2', 'Nessuna') 82 82 112
$tip.SetToolTip($kb, 'Automatica: la tastiera e'' il primo giocatore libero dopo i controller collegati all''avvio.')
$script:padGuids = @()
function Get-Pads {
    # the game's own view (SDL): ssbu_native.exe --pad-list prints "pad<TAB>GUID<TAB>name" per device
    $pads = @()
    if (-not (Test-Path $Exe)) { return ,$pads }
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo; $psi.FileName = $Exe; $psi.Arguments = '--pad-list'; $psi.WorkingDirectory = $Work
        $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.CreateNoWindow = $true
        $pr = [System.Diagnostics.Process]::Start($psi); $text = $pr.StandardOutput.ReadToEnd(); [void]$pr.WaitForExit(10000)
        foreach ($l in ($text -split "`r?`n")) { $c = $l -split "`t"; if ($c.Count -ge 3 -and $c[0] -eq 'pad') { $pads += ,@($c[1], $c[2]) } }
    } catch { }
    return ,$pads
}
function Fill-Pads {
    $pads = Get-Pads; $P = Read-Ini $PadIni
    $guids = @('auto', 'none'); $names = @('Automatico', 'Nessuno')
    foreach ($x in $pads) { $guids += $x[0].ToLower(); $names += $x[1] }
    foreach ($k in @('player1', 'player2')) {
        $v = if ($P[$k]) { $P[$k].ToLower() } else { 'auto' }
        if ($guids -notcontains $v) { $guids += $v; $names += ('(non collegato) ' + $v.Substring(0, [Math]::Min(8, $v.Length))) }
    }
    $script:padGuids = $guids
    foreach ($pair in @(@($p1, 'player1'), @($p2, 'player2'))) {
        $c = $pair[0]; $c.Items.Clear(); foreach ($n in $names) { [void]$c.Items.Add($n) }
        $v = if ($P[$pair[1]]) { $P[$pair[1]].ToLower() } else { 'auto' }
        $c.SelectedIndex = [Array]::IndexOf($guids, $v)
    }
    $kb.SelectedIndex = $(switch ($P['player']) { '1' { 1 } '2' { 2 } 'none' { 3 } default { 0 } })
    $tip.SetToolTip($p1, 'Controller trovati: ' + $pads.Count + '. Automatico: il primo controller che si collega. Premi Cerca dopo averne collegato uno.')
    $tip.SetToolTip($p2, 'Controller trovati: ' + $pads.Count + '. Nessuno: lo slot resta vuoto.')
}
Add-Button $gc 'Cerca' 198 21 50 { Fill-Pads } | Out-Null
Fill-Pads

# status + buttons
$status = New-Object System.Windows.Forms.TextBox; $status.Multiline = $true; $status.ReadOnly = $true; $status.ScrollBars = 'Vertical'
$status.Location = New-Object System.Drawing.Point(12, 612); $status.Size = New-Object System.Drawing.Size(520, 100); $status.Font = New-Object System.Drawing.Font('Consolas', 8.5)
$f.Controls.Add($status)
function Say($t) { $status.AppendText($t + "`r`n") }

function Save-Settings {
    $n = $name.Text.Trim()
    if ($onlineOn.Checked -and $HasOnline) {
        Set-Content -Path $OnlineIni -Encoding ASCII -Value @(
            '# written by the launcher (build\Launcher.ps1); see tools/online/online.ini.example',
            ('server = ' + $server.Text.Trim()), ('room = ' + $room.Text.Trim()), ('nickname = ' + $n),
            ('ping_overlay = ' + $(if ($pingOn.Checked) { 'on' } else { 'off' })),
            ('input_delay = ' + $(if ($delay.SelectedIndex -le 0) { 'auto' } else { [string]($delay.SelectedIndex - 1) })))
        if ($n) { Set-Content -Path (Join-Path $Cfg 'account.txt') -Value (Get-UidFromName $n) -Encoding ASCII }
    } elseif (Test-Path $OnlineIni) {
        Move-Item -Force $OnlineIni (Join-Path $Cfg 'online.ini.off')      # off: kept aside, back when it is turned on again
    }
    Set-Content -Path $LauncherIni -Encoding ASCII -Value @('# written by the launcher', ('saves = ' + $Saves), ('nickname = ' + $n))
    $gfx = @{ aspect = @('keep', 'stretch')[[Math]::Max(0, $aspect.SelectedIndex)]; window = @('windowed', 'borderless', 'fullscreen')[[Math]::Max(0, $winMode.SelectedIndex)]
             latency = @('normal', 'low', 'lowest')[[Math]::Max(0, $latency.SelectedIndex)] }
    if ($winSize.Text.Trim() -match '^(\d{3,5})\s*[xX*]\s*(\d{3,5})$') { $gfx['width'] = $Matches[1]; $gfx['height'] = $Matches[2] }
    Set-IniValues $GfxIni $null $gfx
    if ($p1.SelectedIndex -ge 0 -and $p2.SelectedIndex -ge 0) {
        Set-IniValues $PadIni 'players' @{ player1 = $script:padGuids[$p1.SelectedIndex]; player2 = $script:padGuids[$p2.SelectedIndex] }
    }
    Set-IniValues $PadIni 'keyboard' @{ player = @('auto', '1', '2', 'none')[[Math]::Max(0, $kb.SelectedIndex)] }
}
if (-not (Test-Path $OnlineIni) -and (Test-Path (Join-Path $Cfg 'online.ini.off'))) {
    $O = Read-Ini (Join-Path $Cfg 'online.ini.off')
    if ($O['server']) { $server.Text = $O['server'] }; if ($O['room']) { $room.Text = $O['room'] }
    if ($O['input_delay'] -match '^\d+$' -and [int]$O['input_delay'] -le 8) { $delay.SelectedIndex = [int]$O['input_delay'] + 1 }
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
Add-Button $f 'Salva' 12 722 120 { Save-Settings; Test-All -Quiet | Out-Null; Say 'Impostazioni salvate.' } | Out-Null
$play = Add-Button $f 'GIOCA' 392 722 140 {
    Save-Settings
    if ((Test-All) -gt 0) { return }
    New-Item -ItemType Directory -Force $Saves, (Join-Path $Build 'cache') | Out-Null
    $env:SSBU_ROMFS = $RomFS; $env:SSBU_USERDATA = $Saves; $env:SSBU_FONTS = $Fonts
    $cacheMark = @(Get-ChildItem (Join-Path $Build 'cache\vk') -Filter 'prepared_*.txt' -ErrorAction SilentlyContinue).Count
    if ($cacheMark -eq 0) { Say 'Primo avvio: prima di giocare il gioco prepara gli shader per questa scheda video (qualche minuto).' }
    # no console window: the game's output goes to game.log through a hidden cmd.exe (its exit code is the game's)
    $psi = New-Object System.Diagnostics.ProcessStartInfo; $psi.FileName = "$env:WINDIR\System32\cmd.exe"; $psi.WorkingDirectory = $Work
    $psi.Arguments = '/d /c ""' + $Exe + '" "' + $MainElf + '" 0 > "' + (Join-Path $Build 'game.log') + '" 2>&1"'
    $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
    $script:game = [System.Diagnostics.Process]::Start($psi)
    Say 'Gioco avviato (log: build\game.log).'
    $play.Enabled = $false; $f.WindowState = 'Minimized'; $timer.Start()
}
$play.Font = $bold
Add-Button $f 'Apri log' 140 722 90 { $p = Join-Path $Build 'game.log'; if (Test-Path $p) { Start-Process notepad.exe $p } } | Out-Null

if ($Check) { Test-All -Quiet | Out-Null; $status.Lines | ForEach-Object { Write-Output $_ }; exit }
Test-All -Quiet | Out-Null
[void]$f.ShowDialog()
