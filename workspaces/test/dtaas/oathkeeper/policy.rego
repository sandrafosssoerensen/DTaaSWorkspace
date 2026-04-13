package workspace.authz

import future.keywords.if
import future.keywords.in

# RBAC policy for DTaaS workspaces.
#
# Roles are Keycloak realm roles emitted as a flat 'roles' array in the JWT
# access token via the 'oidc-usermodel-realm-role-mapper' protocol mapper.
#
# Defined roles:
#   dtaas-admin   — full access to any workspace (cross-user)
#   dtaas-user    — full access to own workspace (all HTTP methods)
#   dtaas-viewer  — read-only access to own workspace (GET/HEAD/OPTIONS only)

# No default — unmatched requests are undefined, causing OPA v0 API to return
# HTTP 404, which Oathkeeper treats as deny. Explicit false would be defined
# and return HTTP 200, which Oathkeeper would incorrectly treat as allow.

# Admins can access any workspace path regardless of the username in the URL.
allow if {
    has_valid_token
    is_admin
}

# Users can access only their own workspace (all HTTP methods).
allow if {
    path_matches_username
    is_user
}

# Viewers can access only their own workspace, read-only.
allow if {
    path_matches_username
    is_viewer
    is_readonly_method
}

# --- role checks ---

is_admin if {
    some role in input.extra.roles
    role == "dtaas-admin"
}

is_user if {
    some role in input.extra.roles
    role in {"dtaas-admin", "dtaas-user"}
}

is_viewer if {
    some role in input.extra.roles
    role == "dtaas-viewer"
}

# --- helpers ---

has_valid_token if {
    preferred_username := input.extra.preferred_username
    preferred_username != null
    preferred_username != ""
}

is_readonly_method if {
    input.method in {"GET", "HEAD", "OPTIONS"}
}

path_matches_username if {
    preferred_username := input.extra.preferred_username
    preferred_username != null
    preferred_username != ""
    path_segments := split(input.url.path, "/")
    count(path_segments) >= 2
    path_segments[1] == preferred_username
}
