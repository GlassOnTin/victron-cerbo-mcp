"""OAuth wiring for HTTP transport.

Wraps fastmcp's GitHubProvider with a single-user (or small-allowlist) check.
Without the allowlist, any GitHub user could complete OAuth and call the
tools — unacceptable for a server that toggles grid-side hardware.

Env vars (all required when VICTRON_TRANSPORT=http):
  OAUTH_UPSTREAM_CLIENT_ID       GitHub OAuth App client id
  OAUTH_UPSTREAM_CLIENT_SECRET   GitHub OAuth App client secret
  OAUTH_ALLOWED_GH_USERS         comma-separated GitHub logins permitted
  OAUTH_PUBLIC_BASE_URL          public URL of this Connector
                                 (e.g. https://cerbo.example.com)
"""

from __future__ import annotations

import logging
import os

from fastmcp.server.auth.providers.github import GitHubProvider

log = logging.getLogger(__name__)


class AllowlistedGitHubProvider(GitHubProvider):
    """GitHub OAuth provider that only admits an explicit username allowlist."""

    def __init__(self, *, allowed_logins: set[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self._allowed = {login.lower() for login in allowed_logins}
        if not self._allowed:
            raise ValueError("AllowlistedGitHubProvider requires a non-empty allowlist")

    async def verify_token(self, token: str):
        access_token = await super().verify_token(token)
        if access_token is None:
            return None
        login = (access_token.claims or {}).get("login")
        if not login or login.lower() not in self._allowed:
            log.warning(
                "github login %r not in allowlist (size=%d); rejecting token",
                login, len(self._allowed),
            )
            return None
        return access_token


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} must be set when VICTRON_TRANSPORT=http"
        )
    return value


def build_auth() -> AllowlistedGitHubProvider:
    client_id = _required_env("OAUTH_UPSTREAM_CLIENT_ID")
    client_secret = _required_env("OAUTH_UPSTREAM_CLIENT_SECRET")
    base_url = _required_env("OAUTH_PUBLIC_BASE_URL")
    allowed_csv = _required_env("OAUTH_ALLOWED_GH_USERS")
    allowed = {entry.strip() for entry in allowed_csv.split(",") if entry.strip()}
    return AllowlistedGitHubProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
        allowed_logins=allowed,
    )
