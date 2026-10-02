param(
    [string]$IndexPath = 'C:\Backup\Mulino-Libero\Archivio-versioni\history-index.json',
    [string]$PrivateKey = 'C:\Users\Utente\Mulino-Recupero\CHIAVE-PRIVATA-RECUPERO.asc',
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$taskGpg = 'C:\Program Files\Git\usr\bin\gpg.exe'
function Convert-HistoryMsysPath([string]$path) {
    $p = [System.IO.Path]::GetFullPath($path).Replace('\','/')
    if ($p -notmatch '^[A-Za-z]:/') { throw 'Percorso locale non valido' }
    return '/' + $p.Substring(0,1).ToLowerInvariant() + $p.Substring(2)
}
if (Test-Path -LiteralPath $OutputDirectory) { throw 'La cartella di recupero deve essere nuova' }
$taskIndex = Get-Content -LiteralPath $IndexPath -Raw | ConvertFrom-Json
if ($taskIndex.format -ne 'mulino-shared-images-v1' -or $taskIndex.ciphertext_sha256 -notmatch '^[a-f0-9]{64}$' -or $taskIndex.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Indice non valido' }
if ($taskIndex.local_file -ne ('history-' + $taskIndex.ciphertext_sha256 + '.tar.gpg') -or $taskIndex.archive -ne ($taskIndex.sha256 + '.tar.gz')) { throw 'Nome archivio non valido' }
$taskSource = Join-Path (Split-Path -Parent ([System.IO.Path]::GetFullPath($IndexPath))) $taskIndex.local_file
if ((Get-FileHash -LiteralPath $taskSource -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskIndex.ciphertext_sha256) { throw 'Copia cifrata alterata' }
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
$taskSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $OutputDirectory /inheritance:r /grant:r "*${taskSid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Protezione cartella fallita' }
$taskKeyRoot = Split-Path -Parent ([System.IO.Path]::GetFullPath($PrivateKey))
$taskKeyring = Join-Path $taskKeyRoot ('tmp-archivi-' + [guid]::NewGuid().ToString('N').Substring(0,12))
New-Item -ItemType Directory -Path $taskKeyring | Out-Null
& icacls.exe $taskKeyring /inheritance:r /grant:r "*${taskSid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Protezione del keyring temporaneo fallita' }
try {
    & $taskGpg --homedir (Convert-HistoryMsysPath $taskKeyring) --batch --import (Convert-HistoryMsysPath $PrivateKey) 2> (Join-Path $OutputDirectory 'import.log')
    if ($LASTEXITCODE -ne 0) { throw 'Importazione della chiave di recupero fallita' }
    $taskPartial = Join-Path $OutputDirectory 'images.tar.gz.partial'
    & $taskGpg --homedir (Convert-HistoryMsysPath $taskKeyring) --batch --output (Convert-HistoryMsysPath $taskPartial) --decrypt (Convert-HistoryMsysPath $taskSource) 2> (Join-Path $OutputDirectory 'decrypt.log')
    if ($LASTEXITCODE -ne 0) { throw 'Decifratura fallita: non usare il file parziale' }
    if ((Get-FileHash -LiteralPath $taskPartial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskIndex.sha256 -or (Get-Item -LiteralPath $taskPartial).Length -ne $taskIndex.bytes) { throw 'Archivio decifrato diverso dall originale' }
    Move-Item -LiteralPath $taskPartial -Destination (Join-Path $OutputDirectory $taskIndex.archive)
} finally {
    # The recovery key stays separate from the backup archives. Delete only the
    # disposable keyring created beside the existing recovery key. Its short
    # path also keeps the GnuPG agent's Unix socket below its length limit.
    $taskGpgConf = 'C:\Program Files\Git\usr\bin\gpgconf.exe'
    if (Test-Path -LiteralPath $taskGpgConf) {
        & $taskGpgConf --homedir (Convert-HistoryMsysPath $taskKeyring) --kill gpg-agent 2> (Join-Path $OutputDirectory 'agent.log')
    }
    $taskResolvedKeyRoot = (Resolve-Path -LiteralPath $taskKeyRoot).Path
    $taskResolvedKeyring = (Resolve-Path -LiteralPath $taskKeyring).Path
    if ((Split-Path -Parent $taskResolvedKeyring) -ne $taskResolvedKeyRoot -or (Split-Path -Leaf $taskResolvedKeyring) -notmatch '^tmp-archivi-[a-f0-9]{12}$') { throw 'Percorso del keyring temporaneo inatteso' }
    Remove-Item -LiteralPath $taskResolvedKeyring -Recurse -Force
}
$taskIndex | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'shared-images.json') -Encoding UTF8
Write-Output ('Archivio decifrato e verificato: ' + @($taskIndex.images).Count + ' immagini. Nessun servizio avviato.')
