
# PowerShell script to back up data.db
# Usage: .\backup_db.ps1

$ErrorActionPreference = 'Stop'
try {
    $Date = Get-Date -Format "yyyyMMdd"
    $Source = "C:\Users\msbas\Documents\projects\tradetracker\data.db"
    $DestDir = "C:\Users\msbas\iCloudDrive\Documents\Trading\backups"
    $Dest = Join-Path $DestDir "$Date.db"

    # Create destination directory if it doesn't exist
    if (!(Test-Path $DestDir)) {
        New-Item -ItemType Directory -Path $DestDir | Out-Null
    }

    # Copy the database file
    Copy-Item $Source $Dest -Force

    Write-Host "Backup complete: $Dest"
} catch {
    Write-Host "Error during backup: $_" -ForegroundColor Red
}

Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
