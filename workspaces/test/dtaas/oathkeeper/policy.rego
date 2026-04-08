package workspace.authz

import future.keywords.if

default allow := false

allow if {
    user_in_dtaas_group
    path_matches_username
}

user_in_dtaas_group if {
    groups := input.extra.groups
    groups[_] == "dtaas"
}

path_matches_username if {
    preferred_username := input.extra.preferred_username
    preferred_username != null
    preferred_username != ""
    path_segments := split(input.url.path, "/")
    count(path_segments) >= 2
    path_segments[1] == preferred_username
}
