from fastapi.testclient import TestClient

from app.main import app


def test_retired_tech_worker_can_upgrade_without_reopening_legacy_ui():
    with TestClient(app) as client:
        response = client.get('/tech/sw.js', follow_redirects=False)
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('application/javascript')
        assert response.headers['cache-control'] == 'no-cache'
        assert "importScripts('/static/offline/engine.js" in response.text
        for path in ['/tech', '/tech/', '/tech/app.js']:
            redirect = client.get(path, follow_redirects=False)
            assert redirect.status_code == 307
            assert redirect.headers['location'] == '/#requests'
