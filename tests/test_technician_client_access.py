from pathlib import Path

from sqlalchemy import select

from app.models.customer import TechnicianClientAccess


ROOT = Path(__file__).resolve().parents[1]


def test_technician_client_access_is_unique_per_tenant_technician_and_client():
    constraints = TechnicianClientAccess.__table__.constraints
    assert any(
        getattr(item, "name", None) == "uq_technician_client_access"
        for item in constraints
    )


def test_equipment_and_client_site_routes_are_scoped_by_explicit_fleet_access():
    equipment_source = (ROOT / "app" / "routers" / "equipment.py").read_text(encoding="utf-8")
    customers_source = (ROOT / "app" / "routers" / "customers.py").read_text(encoding="utf-8")
    policy_source = (ROOT / "app" / "services" / "access_policy.py").read_text(encoding="utf-8")
    assert "TechnicianClientAccess.client_id" in equipment_source
    assert "client_id: uuid.UUID | None" in equipment_source
    assert "site_id: uuid.UUID | None" in equipment_source
    assert customers_source.count("TechnicianClientAccess.client_id") >= 2
    assert "fleet_access" in policy_source
    assert "assigned_technician_id != user.id" in policy_source


def test_migration_does_not_infer_historical_fleet_access():
    migration = (ROOT / "alembic" / "versions" / "20260831_0010_technician_client_access.py").read_text(encoding="utf-8")
    assert "create_table(\"technician_client_access\"" in migration
    assert "INSERT" not in migration.upper()
    assert "ServiceRequest" not in migration


def test_technician_client_access_query_has_tenant_and_technician_keys():
    statement = select(TechnicianClientAccess.client_id).where(
        TechnicianClientAccess.organization_id == "org",
        TechnicianClientAccess.technician_id == "tech",
    )
    compiled = str(statement)
    assert "technician_client_access.organization_id" in compiled
    assert "technician_client_access.technician_id" in compiled


def test_frontend_offers_all_sites_and_hides_photo_deletion_for_technicians():
    source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'Все объекты' in source
    assert "const canDeletePhoto = ['admin', 'dispatcher'].includes(state.me.role);" in source
    assert "canDeletePhoto ? '<button type=\"button\" id=\"passport-photo-delete\">" in source
    assert 'после назначения клиента в обслуживание' in source
