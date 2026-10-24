# Windows + Android, self-hosted LAN demo. No public tunnel or APK required.
# Prerequisites on Windows: running Docker Engine/Compose CLI and mkcert.
[CmdletBinding()]
param(
    [string]$LanIp = "",
    [switch]$SkipBuild,
    [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

function Invoke-Checked {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed (exit $LASTEXITCODE). Read the error above before retrying."
    }
}

foreach ($Tool in @("docker", "mkcert")) {
    if (-not (Get-Command $Tool -ErrorAction SilentlyContinue)) {
        throw "$Tool was not found. Install the prerequisite and reopen PowerShell. See MOBILE_DEMO_WINDOWS_ANDROID.md."
    }
}
& docker info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw "Start Docker Desktop/your Docker Engine and wait until it is running." }

if ([string]::IsNullOrWhiteSpace($LanIp)) {
    $Candidates = @(
        Get-NetIPConfiguration | Where-Object {
            $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" -and
            $_.InterfaceAlias -notmatch 'vEthernet|Loopback|Docker|WSL'
        } | ForEach-Object {
            $Configuration = $_
            foreach ($Address in @($Configuration.IPv4Address)) {
                if ($Address.IPAddress -and $Address.IPAddress -notmatch '^(127\.|169\.254\.)') {
                    [PSCustomObject]@{ Interface = $Configuration.InterfaceAlias; Address = $Address.IPAddress }
                }
            }
        }
    )
    if ($Candidates.Count -eq 0) {
        throw "No LAN adapter was found. Connect to Wi-Fi, run ipconfig, and rerun with -LanIp followed by your laptop's Wi-Fi IPv4 address."
    }
    if ($Candidates.Count -eq 1) {
        $LanIp = $Candidates[0].Address
    } else {
        Write-Host "Choose the adapter on the SAME network as your phone:"
        for ($Index = 0; $Index -lt $Candidates.Count; $Index++) {
            Write-Host ("{0}. {1}  {2}" -f ($Index + 1), $Candidates[$Index].Interface, $Candidates[$Index].Address)
        }
        $Selection = Read-Host "Adapter number"
        $Choice = 0
        if (-not [int]::TryParse($Selection, [ref]$Choice) -or $Choice -lt 1 -or $Choice -gt $Candidates.Count) {
            throw "Invalid adapter number. Run the script again."
        }
        $LanIp = $Candidates[$Choice - 1].Address
    }
}
$ParsedAddress = $null
if (-not [System.Net.IPAddress]::TryParse($LanIp, [ref]$ParsedAddress) -or
    $ParsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork -or
    [System.Net.IPAddress]::IsLoopback($ParsedAddress) -or $LanIp -eq "0.0.0.0") {
    throw "LanIp must be the laptop's non-loopback IPv4 address, not localhost, a URL, or the phone's IP."
}
$LocalAddresses = @(Get-NetIPAddress -AddressFamily IPv4 | ForEach-Object { $_.IPAddress })
if ($LocalAddresses -notcontains $LanIp) { throw "The chosen IP is not assigned to this Windows machine." }

$Certificates = Join-Path $ProjectRoot "certs"
$PhoneSetup = Join-Path $ProjectRoot "phone-setup"
New-Item -ItemType Directory -Force -Path $Certificates, $PhoneSetup | Out-Null
Write-Host "Creating local HTTPS certificates for $LanIp and localhost..."
Write-Host "mkcert may ask permission to trust YOUR local development CA on Windows."
Invoke-Checked -Command "mkcert" -Arguments @("-install")
Invoke-Checked -Command "mkcert" -Arguments @("-cert-file", (Join-Path $Certificates "safewalk.pem"), "-key-file", (Join-Path $Certificates "safewalk-key.pem"), $LanIp, "localhost", "127.0.0.1", "::1")
$CaRoot = (& mkcert -CAROOT | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path (Join-Path $CaRoot "rootCA.pem"))) { throw "mkcert's public root CA was not found." }
Copy-Item -LiteralPath (Join-Path $CaRoot "rootCA.pem") -Destination (Join-Path $PhoneSetup "SafeWalk-CA.crt") -Force

$FirewallCommand = "New-NetFirewallRule -DisplayName 'SafeWalk HTTPS demo' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8443 -Profile Private -RemoteAddress LocalSubnet"
if ($OpenFirewall) {
    $Principal = New-Object -TypeName System.Security.Principal.WindowsPrincipal -ArgumentList ([System.Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "-OpenFirewall needs an Administrator PowerShell. Otherwise run without this switch and add the printed rule separately."
    }
    if (-not (Get-NetFirewallRule -DisplayName "SafeWalk HTTPS demo" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName "SafeWalk HTTPS demo" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8443 -Profile Private -RemoteAddress LocalSubnet | Out-Null
    }
} else {
    Write-Host "If Windows blocks the phone, run this once in Administrator PowerShell on your trusted Private network:"
    Write-Host $FirewallCommand -ForegroundColor Yellow
}

# These are process-local settings. No existing .env or archive key is overwritten.
$env:BACKEND_BIND = "127.0.0.1"
$env:APP_ENV = "production"
$Compose = @("compose", "-f", "docker-compose.yml", "-f", "docker-compose.https.yml")
$BackendUp = $Compose + @("up", "-d", "--wait", "--wait-timeout", "240")
if (-not $SkipBuild) { $BackendUp += "--build" }
$BackendUp += "backend"
Write-Host "Starting real database, MQTT, Redis, MinIO, and FastAPI services. The first source build can take a while."
Invoke-Checked -Command "docker" -Arguments $BackendUp
# Recreate only the TLS proxy so a changed LAN address/certificate takes effect.
Invoke-Checked -Command "docker" -Arguments ($Compose + @("up", "-d", "--no-deps", "--force-recreate", "--wait", "--wait-timeout", "120", "https"))

$PhoneUrl = "https://${LanIp}:8443/specs/"
$PhoneUrl | Set-Content -LiteralPath (Join-Path $PhoneSetup "OPEN_ON_PHONE.txt") -Encoding UTF8
$DeviceCode = 'from backend.app.config import Settings; print(Settings().load_secrets().device_api_token)'
$DeviceToken = (& docker @Compose exec -T backend python -c $DeviceCode | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $DeviceToken.Length -lt 32) { throw "Could not retrieve the generated device token." }
$DeviceToken | Set-Content -LiteralPath (Join-Path $PhoneSetup "DEVICE_TOKEN.txt") -Encoding ASCII

# A one-line, single-quoted Python payload avoids Windows PowerShell 5's
# legacy native-command handling of embedded double quotes.
$QrCode = "import sys,cv2,base64; q=cv2.QRCodeEncoder_create().encode(sys.argv[1]); q=cv2.copyMakeBorder(q,4,4,4,4,cv2.BORDER_CONSTANT,value=255); q=cv2.resize(q,None,fx=8,fy=8,interpolation=cv2.INTER_NEAREST); ok,png=cv2.imencode('.png',q); print(base64.b64encode(png).decode())"
$QrBase64 = (& docker @Compose exec -T backend python -c $QrCode $PhoneUrl | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Could not generate the phone URL QR code." }
[System.IO.File]::WriteAllBytes((Join-Path $PhoneSetup "PHONE_QR.png"), [System.Convert]::FromBase64String($QrBase64))

Write-Host ""
Write-Host "READY - self-hosted mobile demo" -ForegroundColor Green
Write-Host "Laptop dashboard: https://localhost:8443/portal/"
Write-Host "Phone: $PhoneUrl"
Write-Host "Phone setup folder: $PhoneSetup"
Write-Host "Transfer SafeWalk-CA.crt and DEVICE_TOKEN.txt privately to the phone."
Write-Host "Install only SafeWalk-CA.crt as a CA certificate in Android Settings. Never transfer rootCA-key.pem or safewalk-key.pem."
Write-Host "Scan PHONE_QR.png after installing the CA, then paste the device token into Specs Settings."
Write-Host "Keep the phone unlocked, foregrounded, and on the same network."
Write-Host "Caregiver token (keep this terminal private):"
Invoke-Checked -Command "docker" -Arguments ($Compose + @("exec", "-T", "backend", "python", "-m", "backend.app.cli", "credentials"))
Write-Host "Read MOBILE_DEMO_WINDOWS_ANDROID.md for the exact demo order and troubleshooting."
