"""Minimal HTTP client helpers for Keycloak admin interactions."""

from __future__ import annotations

import json
import ssl
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class HttpClient:
    """JSON-centric HTTP client with bearer-token support."""

    def request_json(
        self,
        url: str,
        method: str = "GET",
        data: bytes | None = None,
        content_type: str = "application/json",
        token: str | None = None,
    ) -> Any:
        """Execute request and parse JSON payload when present."""
        request = Request(url, method=method, headers=self._headers(content_type, token), data=data)
        return self._read_json_response(request, url)

    def request_empty(
        self,
        url: str,
        method: str,
        token: str,
        json_data: dict[str, Any] | None = None,
    ) -> None:
        """Execute a request where only status code matters."""
        data = None if json_data is None else json.dumps(json_data).encode("utf-8")
        self.request_json(url, method=method, data=data, token=token)

    def _headers(self, content_type: str, token: str | None) -> dict[str, str]:
        """Build request headers for optional content type and token."""
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _read_json_response(self, request: Request, url: str) -> Any:
        """Perform request and decode JSON, raising useful error details."""
        try:
            ctx = ssl.create_default_context()
            with urlopen(request, timeout=30, context=ctx) as response:  # noqa: S310
                return self._decode_json_body(response.read())
        except HTTPError as exc:
            error_body = self._read_error_body(exc)
            raise RuntimeError(f"HTTP {exc.code} from {url}: {error_body}") from exc

    def _decode_json_body(self, raw_body: bytes) -> Any:
        """Decode a raw response body into JSON when data exists."""
        if not raw_body:
            return {}
        decoded = raw_body.decode("utf-8")
        if not decoded.strip():
            return {}
        return json.loads(decoded)

    def _read_error_body(self, exc: HTTPError) -> str:
        """Read HTTP error response body for diagnostics."""
        with exc:
            return exc.read().decode("utf-8")
