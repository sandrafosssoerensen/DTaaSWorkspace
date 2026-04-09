package workspace.authz

import future.keywords.if

default allow := false

allow if {
    path_matches_username
}

path_matches_username if {
    preferred_username := input.extra.preferred_username
    preferred_username != null
    preferred_username != ""
    path_segments := split(input.url.path, "/")
    count(path_segments) >= 2
    path_segments[1] == preferred_username
}
