"""Fixed-destination async Yandex client; no retries or persistent conversations."""
import httpx

from app.services.ai_evidence import PROMPTS, RAW_SCHEMAS

ENDPOINT = "https://ai.api.cloud.yandex.net/v1/chat/completions"
MAX_OUTPUT = 512


def request_body(note, settings):
    import json
    return {"model": f"gpt://{settings.yandex_gpt_folder_id}/{settings.ai_model}",
        "messages": [{"role": "system", "content": PROMPTS["repair_draft"]},
                     {"role": "user", "content": json.dumps({"note": note}, ensure_ascii=False)}],
        "temperature": 0, "max_tokens": MAX_OUTPUT, "stream": False,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "repair_draft", "schema": RAW_SCHEMAS["repair_draft"]}}}


async def generate(note, settings):
    async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds, follow_redirects=False) as client:
        response = await client.post(ENDPOINT, json=request_body(note, settings), headers={
            "Authorization": "Api-Key " + settings.yandex_gpt_api_key,
            "OpenAI-Project": settings.yandex_gpt_folder_id,
            "x-data-logging-enabled": "false"})
        response.raise_for_status()
        if len(response.content) > 256_000:
            raise ValueError("Provider response too large")
        return response.json()
