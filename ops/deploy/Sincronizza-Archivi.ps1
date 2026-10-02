$ErrorActionPreference = 'Stop'
$taskHistoryRoot = 'C:\Backup\Mulino-Libero\Archivio-versioni'
$taskHistoryRemote = '/srv/mulino-backups-export/history'
$taskHistoryKey = Join-Path $env:USERPROFILE '.ssh\mulino_backup'
$taskHistoryTarget = 'backupmulino@80.211.133.89'
$taskHistoryMutex = [System.Threading.Mutex]::new($false, 'Local\MulinoHistoryBackupSync')
$taskHistoryLocked = $false
try {
    $taskHistoryLocked = $taskHistoryMutex.WaitOne(0)
    if (-not $taskHistoryLocked) { return }
    New-Item -ItemType Directory -Force -Path $taskHistoryRoot | Out-Null
    $taskIndexDownload = Join-Path $taskHistoryRoot 'history-index.json.download'
    & scp.exe -i $taskHistoryKey -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes "${taskHistoryTarget}:$taskHistoryRemote/history-index.json" $taskIndexDownload
    if ($LASTEXITCODE -ne 0) { throw 'Indice storico non disponibile' }
    $taskHistoryIndex = Get-Content -LiteralPath $taskIndexDownload -Raw | ConvertFrom-Json
    if ($taskHistoryIndex.format -ne 'mulino-shared-images-v1' -or $taskHistoryIndex.file -ne 'history-images.tar.gpg' -or $taskHistoryIndex.ciphertext_sha256 -notmatch '^[a-f0-9]{64}$' -or $taskHistoryIndex.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Indice storico non valido' }
    if (@($taskHistoryIndex.images).Count -eq 0) { throw 'Elenco immagini vuoto' }
    foreach ($taskImage in $taskHistoryIndex.images) { if ($taskImage -notmatch '^sha256:[a-f0-9]{64}$') { throw 'Identita immagine non valida' } }
    $taskCurrentIndex = Join-Path $taskHistoryRoot 'history-index.json'
    if (Test-Path -LiteralPath $taskCurrentIndex) {
        $taskOld = Get-Content -LiteralPath $taskCurrentIndex -Raw | ConvertFrom-Json
        foreach ($taskImage in $taskOld.images) { if ($taskHistoryIndex.images -notcontains $taskImage) { throw 'La nuova copia non conserva tutte le versioni precedenti' } }
    }
    $taskName = 'history-' + $taskHistoryIndex.ciphertext_sha256 + '.tar.gpg'
    $taskImagePath = Join-Path $taskHistoryRoot $taskName
    $taskValid = (Test-Path -LiteralPath $taskImagePath) -and ((Get-Item -LiteralPath $taskImagePath).Length -eq $taskHistoryIndex.ciphertext_bytes) -and ((Get-FileHash -LiteralPath $taskImagePath -Algorithm SHA256).Hash.ToLowerInvariant() -eq $taskHistoryIndex.ciphertext_sha256)
    if (-not $taskValid) {
        $taskPartial = "$taskImagePath.download"
        & scp.exe -i $taskHistoryKey -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes "${taskHistoryTarget}:$taskHistoryRemote/history-images.tar.gpg" $taskPartial
        if ($LASTEXITCODE -ne 0) { throw 'Trasferimento storico incompleto' }
        if ((Get-Item -LiteralPath $taskPartial).Length -ne $taskHistoryIndex.ciphertext_bytes -or (Get-FileHash -LiteralPath $taskPartial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskHistoryIndex.ciphertext_sha256) { throw 'Copia storica diversa dall indice: verra riprovata' }
        Move-Item -LiteralPath $taskPartial -Destination $taskImagePath -Force
    }
    $taskHistoryIndex | Add-Member -NotePropertyName local_file -NotePropertyValue $taskName -Force
    $taskHistoryIndex | Add-Member -NotePropertyName verified_at -NotePropertyValue (Get-Date).ToUniversalTime().ToString('o') -Force
    $taskHistoryIndex | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $taskIndexDownload -Encoding UTF8
    Move-Item -LiteralPath $taskIndexDownload -Destination $taskCurrentIndex -Force
    # Previous encrypted generations can be removed only after the verified
    # new index includes every previous immutable image identity.
    $taskResolvedRoot = (Resolve-Path -LiteralPath $taskHistoryRoot).Path
    foreach ($taskFile in Get-ChildItem -LiteralPath $taskHistoryRoot -File) {
        if ($taskFile.Name -match '^history-[a-f0-9]{64}\.tar\.gpg$' -and $taskFile.Name -ne $taskName) {
            if ($taskFile.DirectoryName -ne $taskResolvedRoot) { throw 'Percorso di pulizia inatteso' }
            Remove-Item -LiteralPath $taskFile.FullName -Force
        }
    }
} finally {
    if ($taskHistoryLocked) { $taskHistoryMutex.ReleaseMutex() }
    $taskHistoryMutex.Dispose()
}
