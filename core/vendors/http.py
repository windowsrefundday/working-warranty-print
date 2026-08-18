"""Restricted HTTPS transport for fixed-origin vendor lookups."""

from __future__ import annotations

import urllib.parse
import urllib.request
from contextlib import contextmanager
from typing import Any, Iterator


def _validate_allowed_origin(url: str, allowed_host: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Vendor request URL has an invalid port") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != allowed_host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise ValueError("Vendor request URL is outside the allowed HTTPS origin")


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject a redirect before urllib sends a request to another origin."""

    def __init__(self, allowed_host: str) -> None:
        super().__init__()
        self.allowed_host = allowed_host

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        _validate_allowed_origin(newurl, self.allowed_host)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@contextmanager
def open_allowed_https(
    request: urllib.request.Request,
    *,
    allowed_host: str,
    timeout: int,
) -> Iterator[Any]:
    """Open a fixed vendor URL and reject unsafe origins or redirects."""
    _validate_allowed_origin(request.full_url, allowed_host)

    opener = urllib.request.build_opener(_SameOriginRedirectHandler(allowed_host))
    with opener.open(  # nosec B310  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        request,
        timeout=timeout,
    ) as response:
        final_value = response.geturl()
        _validate_allowed_origin(final_value, allowed_host)
        yield response
