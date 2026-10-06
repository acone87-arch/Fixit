"""Queue identities come from the existing role-scoped joined read models."""
from datetime import datetime

import pytest
from app.models.customer import Client, Site
from app.models.service_request import ServiceRequest
from test_onboarding_postgres import pg, auth
from test_request_workflow_postgres import flow

pytestmark = pytest.mark.asyncio


async def test_request_queue_preserves_client_site_identity_and_role_scope(flow):
    async with flow.sessions() as db:
        client = await db.get(Client, flow.client.id)
        client.legal_name = 'АО Первый заказчик'
        other = await db.get(Client, flow.other.id)
        other.legal_name = 'ООО Второй заказчик'
        for site_id in (flow.sites[0].id, flow.sites[2].id):
            site = await db.get(Site, site_id)
            site.name = 'Склад'  # Same display name must not merge distinct sites.
        for i, equipment in enumerate(flow.equipment):
            db.add(ServiceRequest(organization_id=flow.org.id, number=i + 1,
                equipment_id=equipment.id, title='Проверка очереди', status='assigned',
                assigned_technician_id=flow.tech.id if i == 0 else None,
                created_at=datetime(2026, 10, 1)))
        await db.commit()
    owner = await flow.http.get('/api/service-requests', headers=auth(flow.owner, flow.org))
    assert owner.status_code == 200, owner.text
    rows = {item['number']: item for item in owner.json()}
    assert rows[1]['site_name'] == rows[3]['site_name'] == 'Склад'
    assert rows[1]['site_id'] != rows[3]['site_id']
    assert rows[1]['client_id'] == str(flow.client.id)
    assert rows[3]['client_id'] == str(flow.other.id)
    assert rows[1]['client_legal_name'] == 'АО Первый заказчик'
    tech = await flow.http.get('/api/service-requests', headers=auth(flow.tech, flow.org))
    assert tech.status_code == 200, tech.text
    assert [item['number'] for item in tech.json()] == [1]
    for endpoint in ('/api/service-requests', '/api/client-portal/requests'):
        response = await flow.http.get(endpoint, headers=flow.manager_headers)
        assert response.status_code == 200, response.text
        assert [item['number'] for item in response.json()] == [1]
        assert response.json()[0]['site_id'] == str(flow.sites[0].id)
        assert response.json()[0]['client_legal_name'] == 'АО Первый заказчик'
