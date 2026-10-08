"""Web Push URL policy; provider references live in the F01 remediation report."""
import re
from urllib.parse import urlsplit


class UnsafePushEndpoint(ValueError):
    pass


def validate_endpoint(endpoint: str) -> str:
    if not 1 <= len(endpoint) <= 2048 or not endpoint.isascii() or any(
        ord(char) <= 32 or ord(char) == 127 for char in endpoint
    ) or "\\" in endpoint:
        raise UnsafePushEndpoint("Некорректный push endpoint")
    try:
        parts = urlsplit(endpoint)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        raise UnsafePushEndpoint("Некорректный push endpoint") from None
    allowed = host in {"fcm.googleapis.com", "updates.push.services.mozilla.com"} or bool(
        re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:push\.apple\.com|notify\.windows\.com)", host)
    )
    if (parts.scheme != "https" or not allowed or parts.username is not None
            or parts.password is not None or port not in {None, 443}
            or parts.netloc.lower() not in {host, host + ":443"}
            or parts.fragment or not parts.path.startswith("/") or parts.path == "/"):
        raise UnsafePushEndpoint("Недопустимый push endpoint")
    return endpoint
