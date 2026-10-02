$ErrorActionPreference = 'Stop'
$taskRemoteRoot = '/srv/mulino-backups-export/system'
$taskLocalRoot = 'C:\Backup\Mulino-Libero\Completo'
$taskBackupKey = Join-Path $env:USERPROFILE '.ssh\mulino_backup'
$taskTarget = 'backupmulino@80.211.133.89'
$taskMutex = [System.Threading.Mutex]::new($false, 'Local\MulinoSystemBackupSync')
$taskLocked = $false
try {
    $taskLocked = $taskMutex.WaitOne(0)
    if (-not $taskLocked) { return }
    New-Item -ItemType Directory -Force -Path $taskLocalRoot | Out-Null
    $taskChecked = @{}
    function Receive-VerifiedFile([string]$name, [string]$expected = '') {
        if ($name -notmatch '^(system-[0-9TZ]+\.(json|tar\.gpg)|images-[a-f0-9]{64}\.tar\.gpg)$') { throw 'Nome file non valido' }
        if ($taskChecked.ContainsKey($name)) { return $taskChecked[$name] }
        $remote = "$taskRemoteRoot/$name"
        $target = Join-Path $taskLocalRoot $name
        $hashLine = & ssh.exe -i $taskBackupKey -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes $taskTarget "sha256sum '$remote'"
        if ($LASTEXITCODE -ne 0) { throw 'Impossibile verificare il file remoto' }
        $remoteHash = ($hashLine -split '\s+')[0].ToLowerInvariant()
        if ($remoteHash -notmatch '^[a-f0-9]{64}$') { throw 'Checksum remoto non valido' }
        if ($expected -and $remoteHash -ne $expected) { throw 'File diverso da quello indicato nel backup' }
        $valid = (Test-Path -LiteralPath $target) -and ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -eq $remoteHash)
        if (-not $valid) {
            $partial = "$target.download"
            & scp.exe -i $taskBackupKey -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes "${taskTarget}:$remote" $partial
            if ($LASTEXITCODE -ne 0) { throw 'Trasferimento incompleto' }
            if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $remoteHash) { throw 'Checksum della copia locale diverso' }
            Move-Item -LiteralPath $partial -Destination $target -Force
        }
        $taskChecked[$name] = $target
        return $target
    }
    $taskIndexes = & ssh.exe -i $taskBackupKey -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes $taskTarget "find '$taskRemoteRoot' -maxdepth 1 -type f -name 'system-*.json' -printf '%f\n'"
    if ($LASTEXITCODE -ne 0) { throw 'Elenco backup completi non disponibile' }
    $taskReceipt = $null
    foreach ($taskName in @($taskIndexes | Sort-Object)) {
        if (-not $taskName) { continue }
        $taskIndexPath = Receive-VerifiedFile $taskName.Trim()
        $taskIndex = Get-Content -LiteralPath $taskIndexPath -Raw | ConvertFrom-Json
        if ($taskIndex.format -ne 'mulino-system-index-v1') { throw 'Formato indice sconosciuto' }
        $null = Receive-VerifiedFile $taskIndex.file $taskIndex.sha256
        $null = Receive-VerifiedFile $taskIndex.image_asset.file $taskIndex.image_asset.sha256
        $taskReceipt = [pscustomobject]@{index=$taskName.Trim(); sha256=$taskIndex.sha256; verified=$true}
        [pscustomobject]@{verified_at=(Get-Date).ToUniversalTime().ToString('o'); index=$taskName; source_created_utc=$taskIndex.created_utc; current=$taskIndex.current; previous=$taskIndex.previous; ciphertext_verified=$true} |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskLocalRoot 'ultima-copia-verificata.json') -Encoding UTF8
    }
    if ($null -eq $taskReceipt) { throw 'Nessuna copia completa verificata: ricevuta non inviata' }
    $taskReceiptPath = Join-Path $taskLocalRoot 'ricevuta-PC.json'
    $taskReceipt | ConvertTo-Json | Set-Content -LiteralPath $taskReceiptPath -Encoding ASCII
    & scp.exe -i $taskBackupKey -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes $taskReceiptPath "${taskTarget}:/home/backupmulino/mulino-monitor-receipt.json.download"
    if ($LASTEXITCODE -ne 0) { throw 'Copie verificate, ma invio ricevuta non riuscito' }
    & ssh.exe -i $taskBackupKey -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes $taskTarget 'chmod 600 /home/backupmulino/mulino-monitor-receipt.json.download && mv -f /home/backupmulino/mulino-monitor-receipt.json.download /home/backupmulino/mulino-monitor-receipt.json'
    if ($LASTEXITCODE -ne 0) { throw 'Copie verificate, ma pubblicazione ricevuta non riuscita' }
    & 'C:\Backup\Mulino-Libero\Sistema\Sincronizza-Archivi.ps1'
} finally {
    if ($taskLocked) { $taskMutex.ReleaseMutex() }
    $taskMutex.Dispose()
}
