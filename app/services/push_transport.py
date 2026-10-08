"""Direct TLS to a checked numeric address: no second hostname DNS or redirects."""
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit

import requests
import urllib3

from app.services.push_endpoint import UnsafePushEndpoint, validate_endpoint

CONNECT_TIMEOUT = 2.0
READ_TIMEOUT = 3.0


def resolve_endpoint(endpoint: str) -> tuple[str, str]:
    host = urlsplit(validate_endpoint(endpoint)).hostname
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = []
    for family, _, _, _, sockaddr in answers:
        address = ipaddress.ip_address(sockaddr[0])
        if (family not in {socket.AF_INET, socket.AF_INET6} or not address.is_global
                or address.is_multicast or address.is_reserved or address.is_unspecified
                or (address.version == 6 and (address.ipv4_mapped or address.sixtofour
                                             or address.teredo or address.scope_id
                                             or address not in ipaddress.ip_network("2000::/3")))):
            raise UnsafePushEndpoint("Push DNS содержит специальный адрес")
        addresses.append(str(address))
    if not addresses:
        raise UnsafePushEndpoint("Push DNS не вернул адресов")
    return host, addresses[0]


class PushSession:
    """The narrow requests_session.post interface consumed by pywebpush 2.0.3.

    Ignore environment proxies. Preserve original Host, TLS SNI and certificate
    hostname while opening the socket exclusively to the validated numeric IP.
    Do not read the gateway response body (which could drip forever).
    """

    def post(self, endpoint: str, *, data: bytes, headers: dict, timeout: tuple) -> requests.Response:
        host, address = resolve_endpoint(endpoint)
        parts = urlsplit(endpoint)
        target = parts.path + ("?" + parts.query if parts.query else "")
        with urllib3.HTTPSConnectionPool(address, port=443, server_hostname=host,
                assert_hostname=host, cert_reqs=ssl.CERT_REQUIRED,
                ca_certs=requests.certs.where(), maxsize=1, retries=False) as pool:
            response = pool.urlopen("POST", target, body=data, headers={**headers, "Host": host},
                timeout=urllib3.Timeout(connect=timeout[0], read=timeout[1], total=sum(timeout)),
                retries=False, redirect=False, preload_content=False)
            try:
                if 300 <= response.status < 400:
                    raise UnsafePushEndpoint("Push redirects запрещены")
                result = requests.Response()
                result.status_code = response.status
                result._content = b""
                return result
            finally:
                response.close()
