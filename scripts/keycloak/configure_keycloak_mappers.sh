#!/usr/bin/env bash
set -eu

# Configures DTaaS Keycloak mappers using kcadm (official admin CLI).
# Uses a shared client scope for reusable claims and assigns it to the client.

KEYCLOAK_BASE_URL="${KEYCLOAK_BASE_URL:-http://localhost}"
KEYCLOAK_CONTEXT_PATH="${KEYCLOAK_CONTEXT_PATH:-/auth}"
KCADM_BIN="${KCADM_BIN:-kcadm.sh}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-dtaas}"
KEYCLOAK_CLIENT_ID="${KEYCLOAK_CLIENT_ID:-dtaas-workspace}"
KEYCLOAK_SHARED_SCOPE_NAME="${KEYCLOAK_SHARED_SCOPE_NAME:-dtaas-shared}"

# Preferred authentication mode: service account (client credentials).
KEYCLOAK_ADMIN_CLIENT_ID="${KEYCLOAK_ADMIN_CLIENT_ID:-}"
KEYCLOAK_ADMIN_CLIENT_SECRET="${KEYCLOAK_ADMIN_CLIENT_SECRET:-}"

# Fallback authentication mode: admin user/password.
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

require_cmd jq
require_cmd mktemp
require_cmd "${KCADM_BIN}"

normalize_path() {
  case "$1" in
    "")
      echo ""
      ;;
    /)
      echo ""
      ;;
    */)
      echo "${1%/}"
      ;;
    *)
      echo "$1"
      ;;
  esac
}

kcadm() {
  "${KCADM_BIN}" "$@"
}

SERVER_URL="${KEYCLOAK_BASE_URL}$(normalize_path "${KEYCLOAK_CONTEXT_PATH}")"

echo "Authenticating admin CLI against ${SERVER_URL} ..."
if [ -n "${KEYCLOAK_ADMIN_CLIENT_ID}" ] && [ -n "${KEYCLOAK_ADMIN_CLIENT_SECRET}" ]; then
  kcadm config credentials --server "${SERVER_URL}" --realm master \
    --client "${KEYCLOAK_ADMIN_CLIENT_ID}" \
    --secret "${KEYCLOAK_ADMIN_CLIENT_SECRET}" >/dev/null
  echo "Authenticated with service account client ${KEYCLOAK_ADMIN_CLIENT_ID}."
else
  echo "Service-account credentials not provided; falling back to admin username/password."
  kcadm config credentials --server "${SERVER_URL}" --realm master \
    --user "${KEYCLOAK_ADMIN}" \
    --password "${KEYCLOAK_ADMIN_PASSWORD}" >/dev/null
fi

echo "Resolving client and shared scope IDs in realm ${KEYCLOAK_REALM} ..."
CLIENT_UUID="$(kcadm get clients -r "${KEYCLOAK_REALM}" -q clientId="${KEYCLOAK_CLIENT_ID}" \
  | jq -r '.[0].id // empty')"

if [ -z "${CLIENT_UUID}" ]; then
  echo "Client not found: ${KEYCLOAK_CLIENT_ID}" >&2
  exit 1
fi

SCOPE_ID="$(kcadm get client-scopes -r "${KEYCLOAK_REALM}" -q name="${KEYCLOAK_SHARED_SCOPE_NAME}" \
  | jq -r '.[0].id // empty')"

if [ -z "${SCOPE_ID}" ]; then
  echo "Creating shared client scope ${KEYCLOAK_SHARED_SCOPE_NAME} ..."
  SCOPE_ID="$(kcadm create client-scopes -r "${KEYCLOAK_REALM}" \
    -s name="${KEYCLOAK_SHARED_SCOPE_NAME}" \
    -s protocol=openid-connect \
    -i)"
fi

ensure_scope_mapper() {
  MAPPER_NAME="$1"
  PROTOCOL_MAPPER="$2"
  shift 2

  EXISTING_ID="$(kcadm get "client-scopes/${SCOPE_ID}/protocol-mappers/models" -r "${KEYCLOAK_REALM}" \
    | jq -r ".[] | select(.name == \"${MAPPER_NAME}\") | .id" | head -n 1)"

  if [ -n "${EXISTING_ID}" ]; then
    kcadm delete "client-scopes/${SCOPE_ID}/protocol-mappers/models/${EXISTING_ID}" -r "${KEYCLOAK_REALM}" >/dev/null
  fi

  kcadm create "client-scopes/${SCOPE_ID}/protocol-mappers/models" -r "${KEYCLOAK_REALM}" \
    -s name="${MAPPER_NAME}" \
    -s protocol=openid-connect \
    -s protocolMapper="${PROTOCOL_MAPPER}" \
    -s consentRequired=false \
    "$@" >/dev/null
}

ensure_user_profile_attribute() {
  ATTR_NAME="$1"
  DISPLAY_NAME="$2"
  PROFILE_JSON="$(kcadm get users/profile -r "${KEYCLOAK_REALM}")"
  TMP_PROFILE_FILE="$(mktemp)"

  echo "${PROFILE_JSON}" \
    | jq --arg attr "${ATTR_NAME}" --arg display "${DISPLAY_NAME}" '
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
    ' >"${TMP_PROFILE_FILE}"

  kcadm update users/profile -r "${KEYCLOAK_REALM}" -f "${TMP_PROFILE_FILE}" >/dev/null
  rm -f "${TMP_PROFILE_FILE}"
}

echo "Ensuring profile mapper exists in shared scope (userinfo only) ..."
ensure_scope_mapper "profile" "oidc-usermodel-attribute-mapper" \
  -s config.user.attribute=profile \
  -s config.claim.name=profile \
  -s config.jsonType.label=String \
  -s config.id.token.claim=false \
  -s config.access.token.claim=false \
  -s config.userinfo.token.claim=true

echo "Ensuring groups mapper exists in shared scope ..."
ensure_scope_mapper "groups" "oidc-group-membership-mapper" \
  -s config.full.path=false \
  -s config.id.token.claim=false \
  -s config.access.token.claim=true \
  -s config.claim.name=groups \
  -s config.userinfo.token.claim=true \
  -s config.multivalued=true

echo "Ensuring groups owner namespace mapper exists in shared scope ..."
ensure_scope_mapper "groups_owner" "oidc-group-membership-mapper" \
  -s config.full.path=false \
  -s config.id.token.claim=false \
  -s config.access.token.claim=true \
  "-s" "config.claim.name=https://gitlab.org/claims/groups/owner" \
  -s config.userinfo.token.claim=true \
  -s config.multivalued=true

echo "Ensuring sub_legacy mapper exists in shared scope (userinfo only) ..."
ensure_scope_mapper "sub_legacy" "oidc-usermodel-attribute-mapper" \
  -s config.user.attribute=sub_legacy \
  -s config.claim.name=sub_legacy \
  -s config.jsonType.label=String \
  -s config.id.token.claim=false \
  -s config.access.token.claim=false \
  -s config.userinfo.token.claim=true

echo "Ensuring required user profile attributes exist ..."
ensure_user_profile_attribute "profile" "Profile URL"
ensure_user_profile_attribute "sub_legacy" "Legacy Subject"

SCOPE_ASSIGNED="$(kcadm get "clients/${CLIENT_UUID}/default-client-scopes" -r "${KEYCLOAK_REALM}" \
  | jq -r ".[] | select(.id == \"${SCOPE_ID}\") | .id")"

if [ -z "${SCOPE_ASSIGNED}" ]; then
  echo "Assigning shared scope ${KEYCLOAK_SHARED_SCOPE_NAME} to client ${KEYCLOAK_CLIENT_ID} ..."
  kcadm create "clients/${CLIENT_UUID}/default-client-scopes/${SCOPE_ID}" -r "${KEYCLOAK_REALM}" >/dev/null
fi

if [ -n "${PROFILE_BASE_URL}" ]; then
  echo "Updating users with profile attribute (${PROFILE_BASE_URL}/{username}) ..."
  kcadm get users -r "${KEYCLOAK_REALM}" --fields id,username \
    | jq -r '.[] | [.id, .username] | @tsv' \
    | while IFS="$(printf '\t')" read -r USER_ID USERNAME; do
        if [ -n "${USER_ID}" ] && [ -n "${USERNAME}" ]; then
          USER_JSON="$(kcadm get "users/${USER_ID}" -r "${KEYCLOAK_REALM}")"
          TMP_USER_FILE="$(mktemp)"
          echo "${USER_JSON}" \
            | jq --arg profile "${PROFILE_BASE_URL}/${USERNAME}" '.attributes.profile = [$profile]' >"${TMP_USER_FILE}"
          kcadm update "users/${USER_ID}" -r "${KEYCLOAK_REALM}" -f "${TMP_USER_FILE}" >/dev/null
          rm -f "${TMP_USER_FILE}"
        fi
      done
fi

echo "Keycloak shared scope and mapper configuration completed successfully."