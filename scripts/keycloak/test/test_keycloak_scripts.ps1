#!/usr/bin/env powershell
#Requires -Version 5.1
# Integration test for all three Keycloak configuration scripts.
# Spins up a Keycloak dev-mode container, seeds a test realm + client, runs
# each script, and verifies protocol mappers and scope assignment were created.

[CmdletBinding()]
param(
    [string]$KeycloakImage = "quay.io/keycloak/keycloak:26.2",
    [string]$ContainerName = "keycloak-test-$PID",
    [string]$AdminUser = "admin",
    [string]$AdminPass,
    [int]$Port = 18080,
    [int]$TimeoutSeconds = 180,
    [switch]$KeepContainer
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir   = Split-Path -Parent $PSScriptRoot
$BaseUrl     = "http://localhost:$Port"
$AdminUrl    = "$BaseUrl/realms/master/protocol/openid-connect/token"
$ApiBase     = "$BaseUrl/admin/realms"
$Realm       = "dtaas"
$ClientId    = "dtaas-workspace"
$SharedScope = "dtaas-shared"
$PassedTests = 0
$FailedTests = 0

if (-not $AdminPass) {
    # Use an ephemeral password per run to avoid hardcoded credentials in source.
    $AdminPass = "Test-" + [Guid]::NewGuid().ToString("N")
}

# ─── helpers ──────────────────────────────────────────────────────────────────

function Write-Step  { param([string]$Msg) Write-Host "`n==> $Msg" -ForegroundColor Cyan }
function Write-Pass  { param([string]$Msg) Write-Host "  [PASS] $Msg" -ForegroundColor Green; $script:PassedTests++ }
function Write-Fail  { param([string]$Msg) Write-Host "  [FAIL] $Msg" -ForegroundColor Red;  $script:FailedTests++ }
function Write-Info  { param([string]$Msg) Write-Host "        $Msg" -ForegroundColor DarkGray }

function Get-AdminToken {
    $body = "grant_type=password&client_id=admin-cli&username=$AdminUser&password=$AdminPass"
    (Invoke-RestMethod -Uri $AdminUrl -Method Post -Body $body -ContentType "application/x-www-form-urlencoded").access_token
}

function Get-AuthHeaders {
    @{ Authorization = "Bearer $(Get-AdminToken)" }
}

function Wait-KeycloakReady {
    Write-Info "Waiting for Keycloak to become ready (up to ${TimeoutSeconds}s) ..."
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri "$BaseUrl/realms/master" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) { Write-Info "Keycloak is ready."; return }
        } catch { }
        Start-Sleep -Seconds 5
    }
    docker logs $script:ContainerName 2>&1 | Select-Object -Last 20 | ForEach-Object { Write-Info $_ }
    throw "Keycloak did not become ready within ${TimeoutSeconds}s."
}

function New-TestRealm {
    $h = Get-AuthHeaders
    $exists = $false
    try { Invoke-RestMethod -Uri "$ApiBase/$Realm" -Headers $h -ErrorAction Stop | Out-Null; $exists = $true } catch { }
    if ($exists) { Write-Info "Realm '$Realm' already exists."; return }
    Write-Info "Creating realm '$Realm' ..."
    $body = @{ realm = $Realm; enabled = $true } | ConvertTo-Json
    Invoke-RestMethod -Uri $ApiBase -Method Post -Headers $h -ContentType "application/json" -Body $body | Out-Null
}

function New-TestClient {
    $h = Get-AuthHeaders
    $existing = @(Invoke-RestMethod -Uri "$ApiBase/$Realm/clients?max=200" -Headers $h)
    $match = $existing | Where-Object { $_.PSObject.Properties['clientId'] -and $_.clientId -eq $ClientId } | Select-Object -First 1
    if ($match) { Write-Info "Client '$ClientId' already exists."; return }
    Write-Info "Creating client '$ClientId' ..."
    $body = @{
        clientId               = $ClientId
        enabled                = $true
        publicClient           = $true
        standardFlowEnabled    = $true
        directAccessGrantsEnabled = $true
        redirectUris           = @("*")
    } | ConvertTo-Json
    Invoke-RestMethod -Uri "$ApiBase/$Realm/clients" -Method Post -Headers $h -ContentType "application/json" -Body $body | Out-Null
}

function Remove-SharedScope {
    # Reset state between script runs by removing the shared scope
    $h = Get-AuthHeaders
    $scopes = Invoke-RestMethod -Uri "$ApiBase/$Realm/client-scopes" -Headers $h
    $scope  = $scopes | Where-Object { $_.name -eq $SharedScope } | Select-Object -First 1
    if (-not $scope) { return }
    Write-Info "Removing shared scope to reset state ..."
    # Unassign from client first
    $clients = Invoke-RestMethod -Uri "$ApiBase/$Realm/clients?clientId=$ClientId" -Headers $h
    $uuid = $clients[0].id
    try { Invoke-RestMethod -Uri "$ApiBase/$Realm/clients/$uuid/default-client-scopes/$($scope.id)" -Method Delete -Headers $h | Out-Null } catch { }
    Invoke-RestMethod -Uri "$ApiBase/$Realm/client-scopes/$($scope.id)" -Method Delete -Headers $h | Out-Null
}

function Assert-MapperExists {
    param([string]$MapperName, [string]$ScopeId, [hashtable]$Headers)
    $mappers = Invoke-RestMethod -Uri "$ApiBase/$Realm/client-scopes/$ScopeId/protocol-mappers/models" -Headers $Headers
    $found   = $mappers | Where-Object { $_.name -eq $MapperName } | Select-Object -First 1
    if ($found) {
        Write-Pass "Mapper '$MapperName' exists (id=$($found.id))"
    } else {
        Write-Fail "Mapper '$MapperName' NOT found"
    }
}

function Assert-ScopeAssignedToClient {
    param([string]$ScopeId, [string]$ClientUuid, [hashtable]$Headers)
    $assigned = Invoke-RestMethod -Uri "$ApiBase/$Realm/clients/$ClientUuid/default-client-scopes" -Headers $Headers
    $found    = $assigned | Where-Object { $_.id -eq $ScopeId } | Select-Object -First 1
    if ($found) {
        Write-Pass "Scope '$SharedScope' is assigned as default scope to client '$ClientId'"
    } else {
        Write-Fail "Scope '$SharedScope' is NOT assigned to client '$ClientId'"
    }
}

function Test-ScriptResults {
    param([string]$ScriptLabel)
    Write-Step "Verifying state after $ScriptLabel"
    $h = Get-AuthHeaders

    $scopes  = Invoke-RestMethod -Uri "$ApiBase/$Realm/client-scopes" -Headers $h
    $scope   = $scopes | Where-Object { $_.name -eq $SharedScope } | Select-Object -First 1
    if (-not $scope) { Write-Fail "Shared scope '$SharedScope' does not exist"; return }
    Write-Pass "Shared scope '$SharedScope' exists (id=$($scope.id))"

    foreach ($mapper in @("profile", "groups", "groups_owner", "sub_legacy")) {
        Assert-MapperExists -MapperName $mapper -ScopeId $scope.id -Headers $h
    }

    $clients = Invoke-RestMethod -Uri "$ApiBase/$Realm/clients?clientId=$ClientId" -Headers $h
    Assert-ScopeAssignedToClient -ScopeId $scope.id -ClientUuid $clients[0].id -Headers $h
}

# ─── container lifecycle ──────────────────────────────────────────────────────

function Start-KeycloakContainer {
    Write-Step "Starting Keycloak container '$ContainerName' on port $Port"
    docker run -d --name $ContainerName `
        -p "${Port}:8080" `
        -e KEYCLOAK_ADMIN=$AdminUser `
        -e KEYCLOAK_ADMIN_PASSWORD=$AdminPass `
        $KeycloakImage start-dev
    if ($LASTEXITCODE -ne 0) { throw "Failed to start Keycloak container." }
    Write-Info "Container started."
}

function Stop-KeycloakContainer {
    if (-not $KeepContainer) {
        Write-Step "Removing test container '$ContainerName'"
        docker rm -f $ContainerName 2>&1 | Out-Null
    } else {
        Write-Info "Keeping container '$ContainerName' as requested (--KeepContainer)."
    }
}

# ─── main ─────────────────────────────────────────────────────────────────────

$containerStarted = $false
try {
    Start-KeycloakContainer
    $containerStarted = $true

    Wait-KeycloakReady

    Write-Step "Setting up test realm and client"
    New-TestRealm
    New-TestClient

    # ── Test 1: configure_keycloak_windows.ps1 (PowerShell 7 in Docker) ──────
    Write-Step "Running configure_keycloak_windows.ps1"
    docker run --rm `
        -v "${ScriptDir}:/scripts" `
        -e KEYCLOAK_BASE_URL="http://host.docker.internal:$Port" `
        -e KEYCLOAK_CONTEXT_PATH="/" `
        -e KEYCLOAK_REALM=$Realm `
        -e KEYCLOAK_CLIENT_ID=$ClientId `
        -e KEYCLOAK_SHARED_SCOPE_NAME=$SharedScope `
        -e KEYCLOAK_ADMIN=$AdminUser `
        -e KEYCLOAK_ADMIN_PASSWORD=$AdminPass `
        -e PROFILE_BASE_URL="https://localhost/gitlab" `
        mcr.microsoft.com/powershell:7.4-ubuntu-22.04 `
        pwsh -NoProfile -NonInteractive -File /scripts/configure_keycloak_windows.ps1
    if ($LASTEXITCODE -ne 0) { throw "configure_keycloak_windows.ps1 exited with code $LASTEXITCODE" }
    Test-ScriptResults -ScriptLabel "configure_keycloak_windows.ps1"

    # ── Test 2: configure_keycloak_rest.sh (via Docker/WSL) ───────────────────
    Write-Step "Running configure_keycloak_rest.sh"
    Remove-SharedScope  # reset so the script creates it fresh

    # On Docker Desktop (Windows/Mac) host.docker.internal resolves to the host.
    # On Linux fall back to the container gateway.
    $hostIp = "host.docker.internal"

    $shScript = "/scripts/configure_keycloak_rest.sh"
    docker run --rm `
        -v "${ScriptDir}:/scripts" `
        -e KEYCLOAK_BASE_URL="http://${hostIp}:$Port" `
        -e KEYCLOAK_CONTEXT_PATH="/" `
        -e KEYCLOAK_REALM=$Realm `
        -e KEYCLOAK_CLIENT_ID=$ClientId `
        -e KEYCLOAK_ADMIN=$AdminUser `
        -e KEYCLOAK_ADMIN_PASSWORD=$AdminPass `
        -e PROFILE_BASE_URL="https://localhost/gitlab" `
        "debian:bookworm-slim" `
        sh -c "apt-get -qq update && apt-get -qq install -y curl jq >/dev/null 2>&1 && sh $shScript"
    if ($LASTEXITCODE -ne 0) { throw "configure_keycloak_rest.sh exited with code $LASTEXITCODE" }
    Test-ScriptResults -ScriptLabel "configure_keycloak_rest.sh"

} finally {
    if ($containerStarted) { Stop-KeycloakContainer }
}

# ─── summary ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "---------------------------------------" -ForegroundColor DarkGray
Write-Host "  Results: $PassedTests passed, $FailedTests failed" -ForegroundColor (if ($FailedTests -eq 0) { "Green" } else { "Red" })
Write-Host "---------------------------------------" -ForegroundColor DarkGray

if ($FailedTests -gt 0) { exit 1 }
