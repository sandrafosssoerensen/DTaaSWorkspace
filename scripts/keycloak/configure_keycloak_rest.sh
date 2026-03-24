#!/usr/bin/env sh
set -eu

# Configures DTaaS Keycloak mappers using Admin REST API directly (curl + jq).
# No kcadm required. Windows/Linux/Mac compatible.

KEYCLOAK_BASE_URL="${KEYCLOAK_BASE_URL:-http://localhost}"
KEYCLOAK_CONTEXT_PATH="${KEYCLOAK_CONTEXT_PATH:-/auth}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-dtaas}"
KEYCLOAK_CLIENT_ID="${KEYCLOAK_CLIENT_ID:-dtaas-workspace}"
KEYCLOAK_SHARED_SCOPE_NAME="${KEYCLOAK_SHARED_SCOPE_NAME:-dtaas-shared}"

# Admin credentials
KEYCLOAK_ADMIN="${KEYCLOAK_ADMIN:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"

# If set, users are updated with profile attribute ${PROFILE_BASE_URL}/{username}.
PROFILE_BASE_URL="${PROFILE_BASE_URL:-https://localhost/gitlab}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd curl
require_cmd jq

normalize_path() {
  case "$1" in
    "") echo "" ;;
    /) echo "" ;;
    */) echo "${1%/}" ;;
    *) echo "$1" ;;
  esac
}

SERVER_URL="${KEYCLOAK_BASE_URL}$(normalize_path "${KEYCLOAK_CONTEXT_PATH}")"
ADMIN_URL="${SERVER_URL}/admin/realms"

echo "Requesting admin access token from ${SERVER_URL} ..."
TOKEN_RESPONSE="$(curl -fsS -X POST \
  "${SERVER_URL}/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=password" \
  --data-urlencode "client_id=admin-cli" \
  --data-urlencode "username=${KEYCLOAK_ADMIN}" \
  --data-urlencode "password=${KEYCLOAK_ADMIN_PASSWORD}")"

ACCESS_TOKEN="$(echo "$TOKEN_RESPONSE" | jq -r '.access_token // empty')"
if [ -z "$ACCESS_TOKEN" ]; then
  echo "Failed to retrieve access token." >&2
  echo "Response: $TOKEN_RESPONSE" >&2
  exit 1
fi

echo "Token obtained. Resolving client UUID for ${KEYCLOAK_CLIENT_ID} ..."
CLIENTS_RESPONSE="$(curl -fsS "${ADMIN_URL}/${KEYCLOAK_REALM}/clients?max=200" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}")"
CLIENT_UUID="$(echo "$CLIENTS_RESPONSE" | jq -r --arg cid "${KEYCLOAK_CLIENT_ID}" '.[] | select(.clientId == $cid) | .id' | head -n 1)"

if [ -z "$CLIENT_UUID" ]; then
  echo "Client not found: ${KEYCLOAK_CLIENT_ID}" >&2
  exit 1
fi

echo "Client UUID: ${CLIENT_UUID}"
echo "Resolving or creating shared client scope ${KEYCLOAK_SHARED_SCOPE_NAME} ..."
SCOPE_RESPONSE="$(curl -fsS "${ADMIN_URL}/${KEYCLOAK_REALM}/client-scopes?q=${KEYCLOAK_SHARED_SCOPE_NAME}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}")"
SCOPE_ID="$(echo "$SCOPE_RESPONSE" | jq -r ".[] | select(.name == \"${KEYCLOAK_SHARED_SCOPE_NAME}\") | .id" | head -n 1)"

if [ -z "$SCOPE_ID" ]; then
  echo "Creating shared client scope ${KEYCLOAK_SHARED_SCOPE_NAME} ..."
  curl -fsS -X POST "${ADMIN_URL}/${KEYCLOAK_REALM}/client-scopes" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"${KEYCLOAK_SHARED_SCOPE_NAME}\",\"protocol\":\"openid-connect\"}" >/dev/null

  SCOPE_RESPONSE="$(curl -fsS "${ADMIN_URL}/${KEYCLOAK_REALM}/client-scopes?q=${KEYCLOAK_SHARED_SCOPE_NAME}" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}")"
  SCOPE_ID="$(echo "$SCOPE_RESPONSE" | jq -r ".[] | select(.name == \"${KEYCLOAK_SHARED_SCOPE_NAME}\") | .id" | head -n 1)"
fi

echo "Scope ID: ${SCOPE_ID}"
MAPPERS_ENDPOINT="${ADMIN_URL}/${KEYCLOAK_REALM}/client-scopes/${SCOPE_ID}/protocol-mappers/models"

# Helper: ensure a mapper exists (delete same mapper name, create new)
ensure_mapper() {
  MAPPER_NAME="$1"
  MAPPER_JSON="$2"

  echo "  Ensuring mapper '${MAPPER_NAME}' ..."
  EXISTING_MAPPERS="$(curl -fsS "${MAPPERS_ENDPOINT}" -H "Authorization: Bearer ${ACCESS_TOKEN}")"
  EXISTING_ID="$(echo "$EXISTING_MAPPERS" | jq -r ".[] | select(.name == \"${MAPPER_NAME}\") | .id" | head -n 1)"

  if [ -n "$EXISTING_ID" ]; then
    echo "    Removing existing mapper (${EXISTING_ID}) ..."
    curl -fsS -X DELETE "${MAPPERS_ENDPOINT}/${EXISTING_ID}" \
      -H "Authorization: Bearer ${ACCESS_TOKEN}" >/dev/null
  fi

  echo "    Creating mapper '${MAPPER_NAME}' ..."
  curl -fsS -X POST "${MAPPERS_ENDPOINT}" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$MAPPER_JSON" >/dev/null
}

ensure_user_profile_attribute() {
  ATTR_NAME="$1"
  DISPLAY_NAME="$2"
  PROFILE_URI="${ADMIN_URL}/${KEYCLOAK_REALM}/users/profile"
  PROFILE_JSON="$(curl -fsS "${PROFILE_URI}" -H "Authorization: Bearer ${ACCESS_TOKEN}")"
  UPDATED_PROFILE_JSON="$(echo "${PROFILE_JSON}" | jq --arg attr "${ATTR_NAME}" --arg display "${DISPLAY_NAME}" '
    .attributes = (.attributes // [])
    | if ([.attributes[]? | select(.name == $attr)] | length) == 0 then
        .attributes += [{
          "name": $attr,
          "displayName": $display,
          "permissions": {"view": ["admin"], "edit": ["admin"]},
          "multivalued": false
        }]
      else
        .attributes = (.attributes | map(
          if .name == $attr then
            . + {
              "displayName": $display,
              "permissions": {"view": ["admin"], "edit": ["admin"]},
              "multivalued": false
            } | del(.required)
          else
            .
          end
        ))
      end
  ')"

  curl -fsS -X PUT "${PROFILE_URI}" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${UPDATED_PROFILE_JSON}" >/dev/null
}

echo "Creating mappers in shared scope ..."

# Profile mapper (userinfo only)
ensure_mapper "profile" '{
  "name": "profile",
  "protocol": "openid-connect",
  "protocolMapper": "oidc-usermodel-attribute-mapper",
  "consentRequired": false,
  "config": {
    "user.attribute": "profile",
    "claim.name": "profile",
    "jsonType.label": "String",
    "id.token.claim": "false",
    "access.token.claim": "false",
    "userinfo.token.claim": "true"
  }
}'

# Groups mapper (userinfo only)
ensure_mapper "groups" '{
  "name": "groups",
  "protocol": "openid-connect",
  "protocolMapper": "oidc-group-membership-mapper",
  "consentRequired": false,
  "config": {
    "full.path": "false",
    "id.token.claim": "false",
    "access.token.claim": "true",
    "claim.name": "groups",
    "userinfo.token.claim": "true",
    "multivalued": "true"
  }
}'

# Namespaced owner-group mapper (userinfo only)
ensure_mapper "groups_owner" '{
  "name": "groups_owner",
  "protocol": "openid-connect",
  "protocolMapper": "oidc-group-membership-mapper",
  "consentRequired": false,
  "config": {
    "full.path": "false",
    "id.token.claim": "false",
    "access.token.claim": "true",
    "claim.name": "https://gitlab.org/claims/groups/owner",
    "userinfo.token.claim": "true",
    "multivalued": "true"
  }
}'

# sub_legacy mapper (userinfo only)
ensure_mapper "sub_legacy" '{
  "name": "sub_legacy",
  "protocol": "openid-connect",
  "protocolMapper": "oidc-usermodel-attribute-mapper",
  "consentRequired": false,
  "config": {
    "user.attribute": "sub_legacy",
    "claim.name": "sub_legacy",
    "jsonType.label": "String",
    "id.token.claim": "false",
    "access.token.claim": "false",
    "userinfo.token.claim": "true"
  }
}'

echo "Ensuring required user profile attributes exist ..."
ensure_user_profile_attribute "profile" "Profile URL"
ensure_user_profile_attribute "sub_legacy" "Legacy Subject"

# Assign shared scope to client (if not already assigned)
echo "Assigning shared scope to client ..."
ASSIGNED_SCOPES="$(curl -fsS "${ADMIN_URL}/${KEYCLOAK_REALM}/clients/${CLIENT_UUID}/default-client-scopes" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}")"
SCOPE_ASSIGNED="$(echo "$ASSIGNED_SCOPES" | jq -r ".[] | select(.id == \"${SCOPE_ID}\") | .id")"

if [ -z "$SCOPE_ASSIGNED" ]; then
  echo "  Adding scope to client default scopes ..."
  curl -fsS -X PUT "${ADMIN_URL}/${KEYCLOAK_REALM}/clients/${CLIENT_UUID}/default-client-scopes/${SCOPE_ID}" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" >/dev/null
fi

# Update users with profile attribute
if [ -n "${PROFILE_BASE_URL}" ]; then
  echo "Updating users with profile attribute (${PROFILE_BASE_URL}/{username}) ..."
  USERS_RESPONSE="$(curl -fsS "${ADMIN_URL}/${KEYCLOAK_REALM}/users?max=200" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}")"

  echo "$USERS_RESPONSE" | jq -c '.[]' | while read -r USER_ROW; do
    USER_ID="$(echo "$USER_ROW" | jq -r '.id')"
    USERNAME="$(echo "$USER_ROW" | jq -r '.username')"

    if [ -n "$USER_ID" ] && [ -n "$USERNAME" ]; then
      echo "  Setting profile for ${USERNAME} ..."
      curl -fsS -X PUT "${ADMIN_URL}/${KEYCLOAK_REALM}/users/${USER_ID}" \
        -H "Authorization: Bearer ${ACCESS_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"attributes\":{\"profile\":[\"${PROFILE_BASE_URL}/${USERNAME}\"]}}" >/dev/null
    fi
  done
fi

echo "Keycloak shared scope and mappers configured successfully (REST API)."
echo ""
echo "Next steps:"
echo "1. Add user attributes via Keycloak UI:"
echo "   Users -> select user -> Attributes tab"
echo "   Add: sub_legacy = legacy-user-id"
echo ""
echo "2. Get access token and query userinfo:"
echo "   TOKEN=\$(curl -s -X POST ${SERVER_URL}/realms/${KEYCLOAK_REALM}/protocol/openid-connect/token -d 'grant_type=password&client_id=admin-cli&username=sandra&password=PASSWORD' | jq -r '.access_token')"
echo "   curl -H \"Authorization: Bearer \$TOKEN\" ${SERVER_URL}/realms/${KEYCLOAK_REALM}/protocol/openid-connect/userinfo | jq ."