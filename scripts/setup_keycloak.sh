#!/bin/bash
# Script to automatically configure Keycloak for CI/CD testing
# This script creates the realm, client, and test users required for traefik-forward-auth

set -e

# Configuration
KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080/auth}"
KEYCLOAK_ADMIN_USER="${KEYCLOAK_ADMIN:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-dtaas}"
KEYCLOAK_CLIENT_ID="${KEYCLOAK_CLIENT_ID:-dtaas-workspace}"
KEYCLOAK_CLIENT_SECRET="${KEYCLOAK_CLIENT_SECRET:-test-client-secret-ci}"
REDIRECT_URI="${REDIRECT_URI:-http://localhost/_oauth/*}"
WEB_ORIGINS="${WEB_ORIGINS:-http://localhost}"

echo "🔧 Keycloak Setup Script"
echo "========================"
echo "Keycloak URL: $KEYCLOAK_URL"
echo "Realm: $KEYCLOAK_REALM"
echo "Client ID: $KEYCLOAK_CLIENT_ID"
echo ""

# Wait for Keycloak to be ready
echo "⏳ Waiting for Keycloak to be ready..."
MAX_RETRIES=30
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -sf "$KEYCLOAK_URL/realms/master" > /dev/null 2>&1; then
        echo "✅ Keycloak is ready"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "   Attempt $RETRY_COUNT/$MAX_RETRIES..."
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "❌ Keycloak failed to become ready"
    exit 1
fi

# Get admin access token
echo ""
echo "🔑 Obtaining admin access token..."
TOKEN_RESPONSE=$(curl -sf -X POST "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=$KEYCLOAK_ADMIN_USER" \
    -d "password=$KEYCLOAK_ADMIN_PASSWORD" \
    -d "grant_type=password" \
    -d "client_id=admin-cli")

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

if [ -z "$ACCESS_TOKEN" ]; then
    echo "❌ Failed to obtain access token"
    echo "Response: $TOKEN_RESPONSE"
    exit 1
fi
echo "✅ Access token obtained"

# Check if realm already exists
echo ""
echo "🔍 Checking if realm '$KEYCLOAK_REALM' exists..."
REALM_EXISTS=$(curl -sf -X GET "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -o /dev/null -w "%{http_code}" || echo "000")

if [ "$REALM_EXISTS" = "200" ]; then
    echo "✅ Realm '$KEYCLOAK_REALM' already exists"
else
    # Create realm
    echo "📝 Creating realm '$KEYCLOAK_REALM'..."
    REALM_JSON=$(cat <<EOF
{
  "realm": "$KEYCLOAK_REALM",
  "enabled": true,
  "displayName": "DTaaS Realm",
  "sslRequired": "none",
  "registrationAllowed": false,
  "loginWithEmailAllowed": true,
  "duplicateEmailsAllowed": false,
  "resetPasswordAllowed": true,
  "editUsernameAllowed": false,
  "bruteForceProtected": true
}
EOF
)

    CREATE_REALM_RESPONSE=$(curl -sf -X POST "$KEYCLOAK_URL/admin/realms" \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        -H "Content-Type: application/json" \
        -d "$REALM_JSON" \
        -w "%{http_code}" || echo "Failed")

    if [ "$CREATE_REALM_RESPONSE" = "201" ] || [ "$CREATE_REALM_RESPONSE" = "409" ]; then
        echo "✅ Realm '$KEYCLOAK_REALM' created successfully"
    else
        echo "❌ Failed to create realm (HTTP $CREATE_REALM_RESPONSE)"
        exit 1
    fi
fi

# Check if client already exists
echo ""
echo "🔍 Checking if client '$KEYCLOAK_CLIENT_ID' exists..."
CLIENTS_RESPONSE=$(curl -sf -X GET "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/clients?clientId=$KEYCLOAK_CLIENT_ID" \
    -H "Authorization: Bearer $ACCESS_TOKEN")

CLIENT_EXISTS=$(echo "$CLIENTS_RESPONSE" | grep -c "\"clientId\":\"$KEYCLOAK_CLIENT_ID\"" || echo "0")

if [ "$CLIENT_EXISTS" -gt 0 ]; then
    echo "✅ Client '$KEYCLOAK_CLIENT_ID' already exists"
    # Get the client's internal ID for updating the secret
    CLIENT_ID=$(echo "$CLIENTS_RESPONSE" | grep -o '"id":"[^"]*' | head -1 | cut -d'"' -f4)
else
    # Create client
    echo "📝 Creating client '$KEYCLOAK_CLIENT_ID'..."
    CLIENT_JSON=$(cat <<EOF
{
  "clientId": "$KEYCLOAK_CLIENT_ID",
  "name": "DTaaS Workspace Client",
  "description": "OIDC client for DTaaS workspace authentication",
  "enabled": true,
  "protocol": "openid-connect",
  "publicClient": false,
  "bearerOnly": false,
  "standardFlowEnabled": true,
  "implicitFlowEnabled": false,
  "directAccessGrantsEnabled": true,
  "serviceAccountsEnabled": false,
  "authorizationServicesEnabled": false,
  "redirectUris": [
    "$REDIRECT_URI",
    "${REDIRECT_URI%/*}*"
  ],
  "webOrigins": [
    "$WEB_ORIGINS"
  ],
  "attributes": {
    "access.token.lifespan": "300",
    "client.secret.creation.time": "$(date +%s)"
  }
}
EOF
)

    CREATE_CLIENT_RESPONSE=$(curl -sf -X POST "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/clients" \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        -H "Content-Type: application/json" \
        -d "$CLIENT_JSON" \
        -w "%{http_code}" || echo "Failed")

    if [ "$CREATE_CLIENT_RESPONSE" = "201" ] || [ "$CREATE_CLIENT_RESPONSE" = "409" ]; then
        echo "✅ Client '$KEYCLOAK_CLIENT_ID' created successfully"
        # Get the newly created client's internal ID
        sleep 1
        CLIENTS_RESPONSE=$(curl -sf -X GET "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/clients?clientId=$KEYCLOAK_CLIENT_ID" \
            -H "Authorization: Bearer $ACCESS_TOKEN")
        CLIENT_ID=$(echo "$CLIENTS_RESPONSE" | grep -o '"id":"[^"]*' | head -1 | cut -d'"' -f4)
    else
        echo "❌ Failed to create client (HTTP $CREATE_CLIENT_RESPONSE)"
        exit 1
    fi
fi

# Set the client secret
if [ -n "$CLIENT_ID" ]; then
    echo ""
    echo "🔒 Setting client secret..."
    SECRET_JSON=$(cat <<EOF
{
  "type": "secret",
  "value": "$KEYCLOAK_CLIENT_SECRET"
}
EOF
)

    SET_SECRET_RESPONSE=$(curl -sf -X POST "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/clients/$CLIENT_ID/client-secret" \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        -H "Content-Type: application/json" \
        -d "$SECRET_JSON" \
        -w "%{http_code}" || echo "Failed")

    if [ "$SET_SECRET_RESPONSE" = "200" ] || [ "$SET_SECRET_RESPONSE" = "204" ]; then
        echo "✅ Client secret set successfully"
    else
        echo "⚠️  Warning: Failed to set client secret (HTTP $SET_SECRET_RESPONSE)"
        echo "   The client may already have a secret set"
    fi
fi

# Create test users (optional)
if [ "${CREATE_TEST_USERS:-true}" = "true" ]; then
    echo ""
    echo "👥 Creating test users..."
    
    for USERNAME in user1 user2 admin; do
        # Check if user exists
        USER_EXISTS=$(curl -sf -X GET "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/users?username=$USERNAME" \
            -H "Authorization: Bearer $ACCESS_TOKEN" | grep -c "\"username\":\"$USERNAME\"" || echo "0")
        
        if [ "$USER_EXISTS" -gt 0 ]; then
            echo "   ✅ User '$USERNAME' already exists"
            continue
        fi
        
        # Create user
        USER_JSON=$(cat <<EOF
{
  "username": "$USERNAME",
  "enabled": true,
  "emailVerified": true,
  "email": "$USERNAME@test.local",
  "firstName": "${USERNAME^}",
  "lastName": "Test",
  "credentials": [{
    "type": "password",
    "value": "test123",
    "temporary": false
  }]
}
EOF
)
        
        CREATE_USER_RESPONSE=$(curl -sf -X POST "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/users" \
            -H "Authorization: Bearer $ACCESS_TOKEN" \
            -H "Content-Type: application/json" \
            -d "$USER_JSON" \
            -w "%{http_code}" || echo "Failed")
        
        if [ "$CREATE_USER_RESPONSE" = "201" ] || [ "$CREATE_USER_RESPONSE" = "409" ]; then
            echo "   ✅ User '$USERNAME' created (password: test123)"
        else
            echo "   ⚠️  Warning: Failed to create user '$USERNAME' (HTTP $CREATE_USER_RESPONSE)"
        fi
    done
fi

echo ""
echo "✅ Keycloak setup completed successfully!"
echo ""
echo "Configuration summary:"
echo "  Realm: $KEYCLOAK_REALM"
echo "  Client ID: $KEYCLOAK_CLIENT_ID"
echo "  Client Secret: $KEYCLOAK_CLIENT_SECRET"
echo "  Issuer URL: $KEYCLOAK_URL/realms/$KEYCLOAK_REALM"
echo ""
