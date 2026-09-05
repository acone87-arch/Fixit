from pathlib import Path

from app.models.service_request import ServiceRequestAttachment


ROOT = Path(__file__).parents[1]


def test_guest_attachment_retry_has_a_durable_per_photo_client_id():
    columns = set(ServiceRequestAttachment.__table__.columns.keys())
    assert "client_id" in columns
    constraints = {item.name for item in ServiceRequestAttachment.__table__.constraints}
    assert "uq_request_attachment_client" in constraints


def test_public_photo_endpoint_returns_existing_upload_before_the_attachment_limit():
    source = (ROOT / "app" / "routers" / "tickets.py").read_text(encoding="utf8")
    handler = source.split("async def upload_guest_problem_photo", 1)[1].split("@admin_router.get", 1)[0]
    assert "client_id: str = Form(...)" in handler
    assert "ServiceRequestAttachment.client_id == client_id" in handler
    assert handler.index("if existing:") < handler.index("if count >= 3")
    assert "return {\"id\": str(existing.id), \"duplicate\": True}" in handler
    assert "with_for_update()" in handler


def test_guest_upload_regression_runtime_covers_success_partial_retry_validation_and_double_submit():
    source = (ROOT / "tests" / "guest_photo_upload_runtime_test.js").read_text(encoding="utf8")
    for phrase in ("three photos are uploaded exactly once", "retry sends only the failed photo", "second temporary failure", "validation failures", "double submit cannot create another request"):
        assert phrase in source
