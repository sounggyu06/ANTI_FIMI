$ErrorActionPreference = 'Stop'
$dashboardRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'fimi-dashboard'
$previousLocation = Get-Location
try {
    Set-Location -LiteralPath $dashboardRoot
    node ./node_modules/typescript/bin/tsc -b
    if ($LASTEXITCODE -ne 0) { throw 'TypeScript build failed.' }
    node ./node_modules/vite/bin/vite.js build
    if ($LASTEXITCODE -ne 0) { throw 'Dashboard build failed.' }
} finally {
    Set-Location -LiteralPath $previousLocation.Path
}
