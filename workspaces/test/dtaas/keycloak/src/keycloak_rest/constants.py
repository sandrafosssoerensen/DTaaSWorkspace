"""Static Keycloak mapper definitions, client templates, and paging constants."""

from typing import Any

MAPPERS: list[dict[str, Any]] = [
    {
        "name": "profile",
        "consentText": "DTaaS custom mapper for profile claim",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-usermodel-attribute-mapper",
        "consentRequired": False,
        "config": {
            "user.attribute": "profile",
            "claim.name": "profile",
            "jsonType.label": "String",
            "id.token.claim": "false",
            "access.token.claim": "false",
            "userinfo.token.claim": "true",
        },
    },
    {
        "name": "groups",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-group-membership-mapper",
        "consentRequired": False,
        "config": {
            "full.path": "false",
            "id.token.claim": "false",
            "access.token.claim": "true",
            "claim.name": "groups",
            "userinfo.token.claim": "true",
            "multivalued": "true",
        },
    },
]

PAGE_SIZE = 200


def workspace_client_config(root_url: str) -> dict[str, Any]:
    """Return a client-representation dict for the dtaas-workspace client.

    The client is confidential (client authentication on), supports standard
    flow, direct grants, and service accounts. Redirect URIs include the
    OAuth2-proxy callback path (/_oauth/*) expected by the Traefik auth flow.
    """
    url = root_url.rstrip("/")
    return {
        "clientId": "dtaas-workspace",
        "protocol": "openid-connect",
        "enabled": True,
        "publicClient": False,
        "standardFlowEnabled": True,
        "directAccessGrantsEnabled": True,
        "implicitFlowEnabled": False,
        "serviceAccountsEnabled": True,
        "frontchannelLogout": True,
        "rootUrl": url,
        "redirectUris": [
            f"{url}/_oauth/*",
            f"{url}/*",
            "https://oauth.pstmn.io/v1/callback",
        ],
        "webOrigins": [url],
        "attributes": {
            "post.logout.redirect.uris": f"{url}/*",
            "backchannel.logout.session.required": "true",
            "backchannel.logout.revoke.offline.tokens": "false",
        },
    }


def dtaas_client_config(root_url: str) -> dict[str, Any]:
    """Return a client-representation dict for the dtaas-client client.

    The client is public (client authentication off), supports standard flow
    and direct grants, and enforces PKCE with S256.
    """
    url = root_url.rstrip("/")
    return {
        "clientId": "dtaas-client",
        "protocol": "openid-connect",
        "enabled": True,
        "publicClient": True,
        "standardFlowEnabled": True,
        "directAccessGrantsEnabled": True,
        "implicitFlowEnabled": False,
        "serviceAccountsEnabled": False,
        "frontchannelLogout": True,
        "rootUrl": url + "/",
        "redirectUris": [
            f"{url}/*",
            "https://oauth.pstmn.io/v1/callback",
        ],
        "webOrigins": [url],
        "attributes": {
            "pkce.code.challenge.method": "S256",
            "post.logout.redirect.uris": f"{url}/*",
            "backchannel.logout.session.required": "true",
            "backchannel.logout.revoke.offline.tokens": "false",
        },
    }
