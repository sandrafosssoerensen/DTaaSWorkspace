"""Static Keycloak mapper definitions and paging constants."""

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
