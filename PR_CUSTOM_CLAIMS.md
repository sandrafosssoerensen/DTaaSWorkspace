# PR: Automated Keycloak Configuration for DTaaS Custom Claims

## Summary

Adds automated Keycloak configuration for DTaaS custom claims via a shared
client scope, with full unit and integration test coverage.

## Changes

### `configure_keycloak_rest.py`

- Creates (or reuses) the `dtaas-shared` client scope
- Upserts four protocol mappers: `profile`, `groups`, `groups_owner`,
  `sub_legacy` — with correct `access.token.claim` / `userinfo.token.claim`
  flags per mapper
- Ensures `profile` and `sub_legacy` user profile attributes exist in the realm
- Assigns `dtaas-shared` to the target client's default scopes
- Optionally sets each user's `profile` attribute to
  `<PROFILE_BASE_URL>/<username>`
- **Bug fix**: `update_user_profiles` previously sent only
  `{"attributes": ...}` in the `PUT`, which is a full replace in Keycloak's
  API and silently wiped `enabled`, `emailVerified`, and other fields. Fixed
  to use the full fetched user representation as the base.

### `test_configure_keycloak_rest.py`

- Added `test_mapper_definitions_include_expected_claim_contract`: verifies all
  four mapper claim names and token emission flags without requiring Docker

### `test_integration_keycloak_rest.py`

- End-to-end test against a real Keycloak 26.0.7 container
- Sets up two users: one with a pre-existing custom attribute (`department`) to
  assert merge safety, one with no prior attributes
- Both users added to `dtaas-users` group
- Asserts: scope exists, all four mappers exist, scope assigned to client, both
  users get `profile` set, `department` preserved, access token and userinfo
  claims correct
- Fixed `HTTPError` objects in readiness-poll loop not being closed →
  `ResourceWarning` in Python 3.14
- Fixed `claim_value()` to use dot-split traversal — Keycloak builds nested
  JWT objects by splitting claim names on `.`, not `/`

### Documentation

- `TESTING.md` — updated integration test setup and verification lists,
  merge-safety note
- `OIDC_FLOWS.md` — corrected "Custom Claims" section: split into access token
  vs userinfo, fixed `profile` claim placement (userinfo-only)
- `KEYCLOAK_SETUP.md` — replaced generic placeholder with mapper table,
  automation command, and merge-safe behaviour note

## Why

Makes claim setup consistent, repeatable, and environment-independent
(Windows / Linux / CI), removing manual Keycloak UI steps. The merge-safe user
attribute update means the script is safe to re-run against a live realm
without data loss.

## Out of Scope

PKCE enforcement on `dtaas-client` is intentionally **not** automated — it
must be set manually in Keycloak UI:
**Clients → `dtaas-client` → Advanced → Proof Key for Code Exchange → `S256`**

## Validation

Both test layers are needed and cover different failure modes:

**Unit tests** use a `FakeConfigurator` test double — no Docker, no network.
They verify code logic: correct method call order, and that all four mapper
definitions have the right claim names and `access.token.claim` /
`userinfo.token.claim` flags. Fast, always runnable.

**Integration tests** run the actual script against a real Keycloak 26.0.7
container. They verify what unit tests fundamentally cannot: that Keycloak
*accepts* the REST payloads, that the mapper config produces the right claims
in a real signed JWT, and that the userinfo endpoint returns the expected
values. Both bugs found during this work (`update_user_profiles` wiping user
fields, `claim_value()` using the wrong split strategy) were invisible to unit
tests — they only surfaced against real Keycloak.

The integration test is opt-in in CI (`workflow_dispatch` only) because it
requires Docker and takes ~60s. Unit tests run on every push and PR.

- Unit tests:

  ```powershell
  py -3 -m unittest workspaces.test.dtaas.keycloak.test_configure_keycloak_rest
  ```

  → **9/9 passed**

- Integration tests:

  ```powershell
  $env:RUN_KEYCLOAK_INTEGRATION = "1"
  py -3 -W error::ResourceWarning -m unittest workspaces.test.dtaas.keycloak.test_integration_keycloak_rest
  ```

  → **1/1 passed, no warnings**
