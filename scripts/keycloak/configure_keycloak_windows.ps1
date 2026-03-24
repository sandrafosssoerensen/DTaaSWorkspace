#!/usr/bin/env pwsh
# Configures DTaaS Keycloak mappers using Admin REST API (PowerShell, Windows-native, no jq/kcadm required)

param(
    [string]$KeycloakBaseUrl = "http://localhost",
    [string]$KeycloakContextPath = "/auth",
    [string]$KeycloakRealm = "dtaas",
    [string]$KeycloakClientId = "dtaas-workspace",
    [string]$KeycloakSharedScopeName = "dtaas-shared",
    [string]$KeycloakAdmin = "admin",
    [securestring]$KeycloakAdminPassword,
    [string]$ProfileBaseUrl = "https://localhost/gitlab"
)

# Load from environment if available
if ($env:KEYCLOAK_BASE_URL) { $KeycloakBaseUrl = $env:KEYCLOAK_BASE_URL }
if ($env:KEYCLOAK_CONTEXT_PATH) { $KeycloakContextPath = $env:KEYCLOAK_CONTEXT_PATH }
if ($env:KEYCLOAK_REALM) { $KeycloakRealm = $env:KEYCLOAK_REALM }
if ($env:KEYCLOAK_CLIENT_ID) { $KeycloakClientId = $env:KEYCLOAK_CLIENT_ID }
if ($env:KEYCLOAK_SHARED_SCOPE_NAME) { $KeycloakSharedScopeName = $env:KEYCLOAK_SHARED_SCOPE_NAME }
if ($env:KEYCLOAK_ADMIN) { $KeycloakAdmin = $env:KEYCLOAK_ADMIN }
if ($env:KEYCLOAK_ADMIN_PASSWORD) {
    $securePassword = New-Object System.Security.SecureString
    $env:KEYCLOAK_ADMIN_PASSWORD.ToCharArray() | ForEach-Object { $securePassword.AppendChar($_) }
    $securePassword.MakeReadOnly()
    $KeycloakAdminPassword = $securePassword
}
if ($env:PROFILE_BASE_URL) { $ProfileBaseUrl = $env:PROFILE_BASE_URL }

if (-not $KeycloakAdminPassword) {
    if ($Host.Name -and -not [Console]::IsInputRedirected) {
        $KeycloakAdminPassword = Read-Host "Enter Keycloak admin password" -AsSecureString
    } else {
        throw "Keycloak admin password is required. Pass -KeycloakAdminPassword or set KEYCLOAK_ADMIN_PASSWORD."
    }
}

$ServerUrl = "$KeycloakBaseUrl$($KeycloakContextPath.TrimEnd('/'))"
$AdminUrl = "$ServerUrl/admin/realms"

function Invoke-MapperSync {
    param(
        [string]$MapperName,
        [string]$ProtocolMapper,
        [hashtable]$Config
    )
    Write-Host "  Ensuring mapper '$MapperName' ..." -ForegroundColor Cyan
    $mappersUri = "$script:AdminUrl/$script:KeycloakRealm/client-scopes/$script:ScopeId/protocol-mappers/models"
    $existingMappers = Invoke-RestMethod -Uri $mappersUri -Headers $script:headers -ErrorAction Stop
    $existing = $existingMappers | Where-Object { $_.name -eq $MapperName } | Select-Object -First 1
    if ($existing) {
        Write-Host "    Removing existing mapper ($($existing.id)) ..." -ForegroundColor Yellow
        Invoke-RestMethod -Uri "$mappersUri/$($existing.id)" -Method Delete -Headers $script:headers -ErrorAction Stop | Out-Null
    }
    Write-Host "    Creating mapper '$MapperName' ..." -ForegroundColor Yellow
    $mapperBody = @{
        name            = $MapperName
        protocol        = "openid-connect"
        protocolMapper  = $ProtocolMapper
        consentRequired = $false
        config          = $Config
    } | ConvertTo-Json -Compress
    Invoke-RestMethod -Uri $mappersUri -Method Post -Headers $script:headers -ContentType "application/json" -Body $mapperBody -ErrorAction Stop | Out-Null
}

function Invoke-UserProfileAttributeSync {
    param(
        [string]$AttrName,
        [string]$DisplayName
    )
    Write-Host "  Ensuring user profile attribute '$AttrName' ..." -ForegroundColor Cyan
    $profileUri = "$script:AdminUrl/$script:KeycloakRealm/users/profile"
    $profileConfig = Invoke-RestMethod -Uri $profileUri -Headers $script:headers -ErrorAction Stop
    $attrDef = @{
        name        = $AttrName
        displayName = $DisplayName
        permissions = @{ view = @("admin"); edit = @("admin") }
        multivalued = $false
    }
    if (-not $profileConfig.attributes) {
        $profileConfig | Add-Member -NotePropertyName attributes -NotePropertyValue @($attrDef) -Force
    } else {
        $profileConfig.attributes = @($profileConfig.attributes | Where-Object { $_.name -ne $AttrName }) + @($attrDef)
    }
    Invoke-RestMethod -Uri $profileUri -Method Put -Headers $script:headers -ContentType "application/json" -Body ($profileConfig | ConvertTo-Json -Depth 30 -Compress) -ErrorAction Stop | Out-Null
}

Write-Host "Requesting admin access token from $ServerUrl ..." -ForegroundColor Green

try {
    $tokenUri = "$ServerUrl/realms/master/protocol/openid-connect/token"
    $passwordPtr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($KeycloakAdminPassword)
    try {
        $plainPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPtr)
        $tokenBody = "grant_type=password&client_id=admin-cli&username=$KeycloakAdmin&password=$plainPassword"
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPtr)
    }
    
    $tokenResponse = Invoke-RestMethod -Uri $tokenUri -Method Post -Headers @{ "Content-Type" = "application/x-www-form-urlencoded" } -Body $tokenBody -ErrorAction Stop
    
    $AccessToken = $tokenResponse.access_token
    if (-not $AccessToken) {
        Write-Host "Failed to retrieve access token." -ForegroundColor Red
        exit 1
    }

    Write-Host "Token obtained. Resolving client UUID for $KeycloakClientId ..." -ForegroundColor Green
    $headers = @{ "Authorization" = "Bearer $AccessToken" }
    
    $clientUri = "$AdminUrl/$KeycloakRealm/clients?max=200"
    $clientsResponse = Invoke-RestMethod -Uri $clientUri -Headers $headers
    $ClientUuid = $null

    if ($clientsResponse -is [array]) {
        $matchedClient = $clientsResponse | Where-Object { $_.clientId -eq $KeycloakClientId } | Select-Object -First 1
        if ($matchedClient) { $ClientUuid = $matchedClient.id }
    } elseif ($clientsResponse.clientId -is [array] -and $clientsResponse.id -is [array]) {
        $idx = [Array]::IndexOf($clientsResponse.clientId, $KeycloakClientId)
        if ($idx -ge 0 -and $idx -lt $clientsResponse.id.Count) { $ClientUuid = $clientsResponse.id[$idx] }
    } elseif ($clientsResponse.clientId -eq $KeycloakClientId) {
        $ClientUuid = $clientsResponse.id
    }

    if (-not $ClientUuid) {
        Write-Host "Client not found: $KeycloakClientId" -ForegroundColor Red
        exit 1
    }

    Write-Host "Client UUID: $ClientUuid"
    Write-Host "Resolving or creating shared client scope $KeycloakSharedScopeName ..." -ForegroundColor Green
    
    $scopeUri = "$AdminUrl/$KeycloakRealm/client-scopes?q=$KeycloakSharedScopeName"
    $scopeResponse = Invoke-RestMethod -Uri $scopeUri -Headers $headers
    
    $ScopeId = ($scopeResponse | Where-Object { $_.name -eq $KeycloakSharedScopeName } | Select-Object -First 1).id

    if (-not $ScopeId) {
        Write-Host "  Creating scope '$KeycloakSharedScopeName' ..." -ForegroundColor Yellow
        $newScopeBody = @{ name = $KeycloakSharedScopeName; protocol = "openid-connect" } | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri "$AdminUrl/$KeycloakRealm/client-scopes" -Method Post -Headers $headers -ContentType "application/json" -Body $newScopeBody -ErrorAction Stop | Out-Null
        $scopeResponse = Invoke-RestMethod -Uri $scopeUri -Headers $headers -ErrorAction Stop
        $ScopeId = ($scopeResponse | Where-Object { $_.name -eq $KeycloakSharedScopeName } | Select-Object -First 1).id
    }
    Write-Host "Scope ID: $ScopeId"

    Write-Host "Creating mappers in shared scope ..." -ForegroundColor Green

    Invoke-MapperSync "profile" "oidc-usermodel-attribute-mapper" @{
        "user.attribute" = "profile"
        "claim.name" = "profile"
        "jsonType.label" = "String"
        "id.token.claim" = "false"
        "access.token.claim" = "false"
        "userinfo.token.claim" = "true"
    }

    Invoke-MapperSync "groups" "oidc-group-membership-mapper" @{
        "full.path" = "false"
        "id.token.claim" = "false"
        "access.token.claim" = "true"
        "claim.name" = "groups"
        "userinfo.token.claim" = "true"
        "multivalued" = "true"
    }

    Invoke-MapperSync "groups_owner" "oidc-group-membership-mapper" @{
        "full.path" = "false"
        "id.token.claim" = "false"
        "access.token.claim" = "true"
        "claim.name" = "https://gitlab.org/claims/groups/owner"
        "userinfo.token.claim" = "true"
        "multivalued" = "true"
    }

    Invoke-MapperSync "sub_legacy" "oidc-usermodel-attribute-mapper" @{
        "user.attribute" = "sub_legacy"
        "claim.name" = "sub_legacy"
        "jsonType.label" = "String"
        "id.token.claim" = "false"
        "access.token.claim" = "false"
        "userinfo.token.claim" = "true"
    }

    Invoke-UserProfileAttributeSync "profile" "Profile URL"
    Invoke-UserProfileAttributeSync "sub_legacy" "Legacy Subject"

    Write-Host "Assigning shared scope to client ..." -ForegroundColor Green
    $assignScopeUri = "$AdminUrl/$KeycloakRealm/clients/$ClientUuid/default-client-scopes"
    $assignedScopes = Invoke-RestMethod -Uri $assignScopeUri -Headers $headers
    
    $ScopeAssigned = ($assignedScopes | Where-Object { $_.id -eq $ScopeId } | Select-Object -First 1)
    
    if (-not $ScopeAssigned) {
        Write-Host "  Adding scope to client default scopes ..." -ForegroundColor Yellow
        Invoke-RestMethod -Uri "$assignScopeUri/$ScopeId" -Method Put -Headers $headers | Out-Null
    }

    if ($ProfileBaseUrl) {
        Write-Host "Updating users with profile attribute ($ProfileBaseUrl/{username}) ..." -ForegroundColor Green
        $usersUri = "$AdminUrl/$KeycloakRealm/users?max=200"
        $usersResponse = Invoke-RestMethod -Uri $usersUri -Headers $headers
        
        foreach ($user in $usersResponse) {
            $UserId = $user.id
            $Username = $user.username
            
            if ($UserId -and $Username) {
                Write-Host "  Setting profile for $Username ..." -ForegroundColor Cyan
                $userUri = "$AdminUrl/$KeycloakRealm/users/$UserId"
                $userDetails = Invoke-RestMethod -Uri $userUri -Headers $headers
                $attrMap = @{}

                if ($userDetails.attributes) {
                    $userDetails.attributes.PSObject.Properties | ForEach-Object {
                        $attrMap[$_.Name] = $_.Value
                    }
                }

                $attrMap["profile"] = @("$ProfileBaseUrl/$Username")
                $firstName = if ($userDetails.firstName) { $userDetails.firstName } else { $Username }
                $lastName = if ($userDetails.lastName) { $userDetails.lastName } else { $Username }
                $email = if ($userDetails.email) { $userDetails.email } else { "$Username@example.invalid" }

                $userPayload = @{
                    firstName = $firstName
                    lastName = $lastName
                    email = $email
                    emailVerified = $false
                    attributes = $attrMap
                }

                Invoke-RestMethod -Uri $userUri -Method Put -Headers $headers -ContentType "application/json" -Body ($userPayload | ConvertTo-Json -Compress) | Out-Null
            }
        }
    }

    Write-Host "Done! Keycloak shared scope and mappers configured (PowerShell REST API)." -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "1. Add user attributes via Keycloak UI: Users > select user > Attributes"
    Write-Host "   Add: sub_legacy = legacy-user-id"
    Write-Host ""
    Write-Host "2. Get access token and verify custom claims:"
    Write-Host "   TOKEN = (Invoke-RestMethod '$ServerUrl/realms/$KeycloakRealm/protocol/openid-connect/token' -Method Post -Body 'grant_type=password&client_id=admin-cli&username=sandra&password=PASSWORD').access_token"
    Write-Host "   Invoke-RestMethod '$ServerUrl/realms/$KeycloakRealm/protocol/openid-connect/userinfo' -Headers @{Authorization='Bearer TOKEN'} | ConvertTo-Json"

} catch {
    $ErrorMessage = $_.Exception.Message
    Write-Host "Error: $ErrorMessage" -ForegroundColor Red
    exit 1
}
