"""F01: synthetic network only; no requests to real push or internal hosts."""
import base64
import asyncio
import socket
import threading
import time
import uuid
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid
from requests import Response
from pydantic import ValidationError
from app.schemas.push import PushSubscriptionIn
from app.services import push_service
from app.services import push_transport


@pytest.fixture(autouse=True)
def forbid_unmocked_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unmocked network is forbidden in F01 regression tests")
    monkeypatch.setattr("requests.Session.request", blocked)
    monkeypatch.setattr("urllib3.HTTPConnectionPool.urlopen", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


UNSAFE_ENDPOINTS = [
    "http://127.0.0.1/push", "http://localhost/push", "https://localhost/push",
    "https://127.0.0.1/push", "https://10.0.0.1/push", "https://172.16.0.1/push",
    "https://192.168.0.1/push", "https://169.254.169.254/push", "https://[::1]/push",
    "https://[fe80::1]/push", "https://[::ffff:127.0.0.1]/push", "https://2130706433/push",
    "https://0177.0.0.1/push", "https://0x7f000001/push", "https://127.1/push",
    "https://fcm.googleapis.com:8443/push", "https://fcm.googleapis.com:80/push",
    "https://user:pass@fcm.googleapis.com/push", "https://@fcm.googleapis.com/push",
    "https://fcm.googleapis.com.evil.invalid/push", "https://evilpush.apple.com/push",
    "https://push.apple.com.evil.invalid/push", "https://evil.invalid/push",
    "https://fcm.googleapis.com./push", "https://fcm%2egoogleapis.com/push",
    "https://fcm.googleapis.com\\@127.0.0.1/push", "https://fcm.googleapis.com/push#fragment",
    " https://fcm.googleapis.com/push", "https://fcm.googleapis.com\n/push",
]


@pytest.mark.parametrize("endpoint", UNSAFE_ENDPOINTS)
def test_registration_rejects_unsafe_urls(endpoint):
    with pytest.raises(ValidationError) as error:
        PushSubscriptionIn(endpoint=endpoint, keys={"p256dh": "synthetic", "auth": "synthetic"})
    assert any(item["loc"] == ("endpoint",) for item in error.value.errors())


@pytest.mark.parametrize("endpoint", [
    "https://fcm.googleapis.com/fcm/send/synthetic", "https://fcm.googleapis.com/wp/synthetic",
    "https://updates.push.services.mozilla.com/wpush/v2/synthetic",
    "https://web.push.apple.com/Qsynthetic", "https://a.b.push.apple.com/synthetic",
    "https://wns2-par02p.notify.windows.com/w/?token=synthetic",
    "https://FCM.GOOGLEAPIS.COM:443/fcm/send/synthetic",
])
def test_supported_provider_urls_remain_valid(endpoint, subscription):
    assert PushSubscriptionIn(endpoint=endpoint, keys={
        "p256dh": subscription.p256dh, "auth": subscription.auth}).endpoint == endpoint


def synthetic_keys():
    def b64(data):
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    key = ec.generate_private_key(ec.SECP256R1())
    return {"p256dh": b64(key.public_key().public_bytes(serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)), "auth": b64(bytes(range(16)))}


def test_registration_rejects_loopback_endpoint():
    with pytest.raises(ValidationError):
        PushSubscriptionIn(endpoint="http://127.0.0.1/push", keys={"p256dh": "synthetic", "auth": "synthetic"})


@pytest.fixture
def subscription(monkeypatch):
    vapid = Vapid()
    vapid.generate_keys()
    monkeypatch.setattr(push_service, "settings", NS(vapid_public_key="synthetic",
        vapid_private_key=vapid, vapid_subject="mailto:test@example.com"))
    return NS(id=uuid.uuid4(), endpoint="https://fcm.googleapis.com/fcm/send/synthetic",
        **synthetic_keys(), is_active=True)


@pytest.fixture
def network(monkeypatch):
    """Both old requests and new pinned transport stop at a mocked HTTP boundary."""
    reply = NS(status=201, close=Mock())
    pool = Mock()
    pool.__enter__ = Mock(return_value=pool)
    pool.__exit__ = Mock(return_value=False)
    pool.urlopen.return_value = reply
    factory = Mock(return_value=pool)
    monkeypatch.setattr(push_transport.urllib3, "HTTPSConnectionPool", factory)
    resolver = Mock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    old_post = Mock(return_value=NS(status_code=201, text=""))
    monkeypatch.setattr("requests.post", old_post)
    return NS(pool=pool, factory=factory, resolver=resolver, reply=reply, old_post=old_post)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "0.0.0.0",
    "100.64.0.1", "192.0.2.1", "224.0.0.1", "::1", "fe80::1", "fc00::1", "ff02::1",
    "::ffff:93.184.216.34", "2002:7f00:1::", "64:ff9b:1::1", "64:ff9b::7f00:1"])
def test_delivery_rejects_special_dns_answers(subscription, network, address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    network.resolver.return_value = [(family, socket.SOCK_STREAM, 6, "", (address, 443))]
    with pytest.raises(ValueError):
        push_service._send(subscription, {"title": "Synthetic"})
    network.factory.assert_not_called()
    network.old_post.assert_not_called()


def test_mixed_public_private_dns_fails_closed(subscription, network):
    network.resolver.return_value.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)))
    with pytest.raises(ValueError):
        push_service._send(subscription, {"title": "Synthetic"})
    network.factory.assert_not_called()


def test_delivery_pins_ip_with_provider_tls_and_bounded_timeouts(subscription, network, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    push_service._send(subscription, {"title": "Synthetic"})
    assert network.factory.call_args.args == ("93.184.216.34",)
    options = network.factory.call_args.kwargs
    assert options["server_hostname"] == options["assert_hostname"] == "fcm.googleapis.com"
    assert options["cert_reqs"] == 2
    call = network.pool.urlopen.call_args
    assert call.args == ("POST", "/fcm/send/synthetic")
    assert call.kwargs["headers"]["Host"] == "fcm.googleapis.com"
    assert call.kwargs["redirect"] is False and call.kwargs["retries"] is False
    assert call.kwargs["preload_content"] is False
    assert call.kwargs["timeout"].connect_timeout == 2.0
    assert call.kwargs["timeout"].read_timeout <= 3.0
    network.old_post.assert_not_called()
    network.reply.close.assert_called_once()


def test_dns_rebinding_cannot_change_numeric_connection_target(subscription, network):
    network.resolver.side_effect = [network.resolver.return_value,
        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]]
    push_service._send(subscription, {"title": "Synthetic"})
    assert network.resolver.call_count == 1
    assert network.factory.call_args.args == ("93.184.216.34",)


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_gateway_redirect_is_rejected_without_second_request(subscription, network, code):
    network.reply.status = code
    network.reply.headers = {"Location": "http://127.0.0.1/internal"}
    with pytest.raises(ValueError):
        push_service._send(subscription, {"title": "Synthetic"})
    assert network.pool.urlopen.call_count == 1
    network.reply.close.assert_called_once()


@pytest.mark.asyncio
async def test_slow_delivery_does_not_hold_business_handler(subscription, monkeypatch):
    release = threading.Event()
    entered = threading.Event()
    def slow(*args):
        entered.set()
        release.wait(2)
    monkeypatch.setattr(push_service, "_send", slow)
    monkeypatch.setattr(push_service, "DELIVERY_BUDGET", 0.05, raising=False)
    db = NS(scalars=AsyncMock(return_value=NS(all=lambda: [subscription])), commit=AsyncMock())
    started = time.monotonic()
    try:
        await push_service.send_to_user(db, user_id=uuid.uuid4(), organization_id=uuid.uuid4(),
            title="Synthetic", body="Synthetic", url="/#requests/synthetic")
        assert entered.is_set()
        assert time.monotonic() - started < 0.5
    finally:
        release.set()


@pytest.mark.asyncio
async def test_database_cleanup_failure_cannot_fail_saved_business_operation(subscription, monkeypatch):
    subscription.endpoint = "http://localhost/synthetic"
    db = NS(scalars=AsyncMock(return_value=NS(all=lambda: [subscription])),
        commit=AsyncMock(side_effect=RuntimeError("synthetic cleanup failure")))
    await push_service.send_to_user(db, user_id=uuid.uuid4(), organization_id=uuid.uuid4(),
        title="Synthetic", body="Synthetic", url="/#requests/synthetic")


@pytest.mark.asyncio
async def test_recipient_lookup_failure_is_best_effort(subscription):
    db = NS(scalars=AsyncMock(side_effect=RuntimeError("synthetic unavailable DB")))
    await push_service.notify_dispatchers(db, NS(organization_id=uuid.uuid4()), "Synthetic")


@pytest.mark.asyncio
async def test_unavailable_endpoint_is_best_effort(subscription, network):
    network.pool.urlopen.side_effect = TimeoutError("synthetic endpoint unavailable")
    db = NS(scalars=AsyncMock(return_value=NS(all=lambda: [subscription])), commit=AsyncMock())
    await push_service.send_to_user(db, user_id=uuid.uuid4(), organization_id=uuid.uuid4(),
        title="Synthetic", body="Synthetic", url="/#requests/synthetic")
    assert subscription.is_active  # transient failure must not revoke a valid subscription


@pytest.mark.asyncio
async def test_outstanding_sends_have_no_unbounded_backlog(subscription, monkeypatch):
    release = threading.Event()
    entered = []
    def slow(*args):
        entered.append(1)
        release.wait(2)
    monkeypatch.setattr(push_service, "_send", slow)
    monkeypatch.setattr(push_service, "DELIVERY_BUDGET", 0.05, raising=False)
    async def notify():
        db = NS(scalars=AsyncMock(return_value=NS(all=lambda: [subscription])), commit=AsyncMock())
        await push_service.send_to_user(db, user_id=uuid.uuid4(), organization_id=uuid.uuid4(),
            title="Synthetic", body="Synthetic", url="/#requests/synthetic")
    try:
        await asyncio.gather(*(notify() for _ in range(30)))
        assert 1 <= len(entered) <= 4
        await asyncio.gather(*(notify() for _ in range(30)))
        assert len(entered) <= 4  # timed-out workers retain capacity until they finish
    finally:
        release.set()


@pytest.mark.parametrize("keys", [
    {}, {"p256dh": "bad", "auth": "bad"},
    {"p256dh": "A" * 20000, "auth": "A" * 20000},
])
def test_registration_rejects_malformed_or_oversized_keys(keys):
    with pytest.raises(ValidationError):
        PushSubscriptionIn(endpoint="https://fcm.googleapis.com/fcm/send/synthetic", keys=keys)


@pytest.mark.asyncio
async def test_saved_unsafe_subscription_never_reaches_network(subscription, monkeypatch):
    subscription.endpoint = "http://127.0.0.1/synthetic"
    post = Mock(return_value=NS(status_code=201, text=""))
    monkeypatch.setattr("requests.post", post)
    db = NS(scalars=AsyncMock(return_value=NS(all=lambda: [subscription])), commit=AsyncMock())
    await push_service.send_to_user(db, user_id=uuid.uuid4(), organization_id=uuid.uuid4(),
        title="Synthetic", body="Synthetic", url="/#requests/synthetic")
    post.assert_not_called()
