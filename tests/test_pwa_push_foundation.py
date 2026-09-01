import uuid
from pathlib import Path

from app.models.push import PushSubscription
from app.services.push_service import safe_request_url


ROOT = Path(__file__).parents[1]


def test_push_subscription_is_tenant_scoped_and_endpoint_is_unique():
    columns = PushSubscription.__table__.columns
    assert {"organization_id", "user_id", "endpoint", "p256dh", "auth", "is_active"} <= set(columns)
    assert "uq_push_subscription_endpoint" in {item.name for item in PushSubscription.__table__.constraints}
    assert "ix_push_subscription_user_org_active" in {item.name for item in PushSubscription.__table__.indexes}


def test_push_deep_link_is_internal_and_request_specific():
    request_id = uuid.uuid4()
    assert safe_request_url(request_id) == f"/#requests/{request_id}"
    worker = (ROOT / "app/static/sw.js").read_text(encoding="utf-8")
    assert "data.url.startsWith('/#requests/')" in worker
    assert "clients.matchAll" in worker and "openWindow" in worker


def test_push_api_keeps_device_subscription_in_current_tenant_only():
    source = (ROOT / "app/routers/push.py").read_text(encoding="utf-8")
    assert "PushSubscription.endpoint == payload.endpoint" in source
    assert "item.user_id != user.id or item.organization_id != user.organization_id" in source
    assert "HTTP_409_CONFLICT" in source
    assert "PushSubscription.user_id == user.id" in source
    assert "PushSubscription.organization_id == user.organization_id" in source


def test_delivery_is_best_effort_and_stale_endpoints_are_deactivated():
    source = (ROOT / "app/services/push_service.py").read_text(encoding="utf-8")
    assert "if status_code in {404, 410}" in source
    assert "subscription.is_active = False" in source
    assert "except Exception as exc" in source


def test_pwa_uses_one_root_scoped_worker_without_losing_offline_sync():
    engine = (ROOT / "app/static/offline/engine.js").read_text(encoding="utf-8")
    worker = (ROOT / "app/static/sw.js").read_text(encoding="utf-8")
    app = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert "register('/sw.js?v=20260902-1', { scope: '/' })" in engine
    assert "fixit-sync-repairs" in worker and "FixitOffline.sync" in worker
    assert "fixit-tech-db" in engine and "pendingRepairs" in engine and "pendingAttachments" in engine
    assert "beforeinstallprompt" in app and "Notification.requestPermission()" in app
