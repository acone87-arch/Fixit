import json
from types import SimpleNamespace

import httpx
import pytest

from app.services import ai_provider

pytestmark = pytest.mark.asyncio


def config():
    return SimpleNamespace(yandex_gpt_api_key='test-key', yandex_gpt_folder_id='test-folder',
                           ai_model='yandexgpt-5.1', ai_timeout_seconds=1)


async def test_provider_sends_only_note_with_logging_opt_out(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        assert str(request.url) == ai_provider.ENDPOINT
        assert request.headers['x-data-logging-enabled'] == 'false'
        assert request.headers['authorization'] == 'Api-Key test-key'
        body = json.loads(request.content)
        assert json.loads(body['messages'][1]['content']) == {'note': 'Очистил фильтр.'}
        assert body['response_format']['type'] == 'json_schema'
        assert 'tools' not in body
        return httpx.Response(200, json={'choices': [], 'usage': {}})
    client = httpx.AsyncClient
    monkeypatch.setattr(ai_provider.httpx, 'AsyncClient', lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))
    await ai_provider.generate('Очистил фильтр.', config())
    assert len(requests) == 1


async def test_provider_refuses_redirect_without_retries(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(307, headers={'Location': 'https://example.invalid/collect'})
    client = httpx.AsyncClient
    monkeypatch.setattr(ai_provider.httpx, 'AsyncClient', lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(httpx.HTTPStatusError):
        await ai_provider.generate('Очистил фильтр.', config())
    assert len(requests) == 1
