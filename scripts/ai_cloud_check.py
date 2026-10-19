"""Explicit, budgeted Yandex AI Studio evaluation on synthetic AI-00 cases only.

Not a production adapter. No imports from the application and no database access.
Credentials and reports stay in ignored local files. Unknown calls retain reserve.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal, ROUND_UP
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from scripts.ai_preflight import DATASET, ROOT, load_cases, require
from scripts.ai_semantics import PROMPTS, RAW_SCHEMAS, VERSION, grounded_output


ENDPOINT = "https://ai.api.cloud.yandex.net/v1/chat/completions"
LOCAL = DATASET / "local"
CASE_IDS = ("R001", "R011", "H001", "H026")
MAX_OUTPUT = 512
PROMPT_VERSION = VERSION


def object_schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


STRING = {"type": "string"}
STRINGS = {"type": "array", "items": STRING}
SCHEMAS = {
    "repair_draft": object_schema({"diagnostic": STRING, "work": STRING, "comment": STRING,
                                    "questions": STRINGS, "warnings": STRINGS}),
    "equipment_brief": object_schema({"summary": STRING, "facts": {"type": "array", "items":
        object_schema({"text": STRING, "source_ids": STRINGS})}, "warnings": STRINGS}),
}


def validate_output(value, schema):
    kind = schema["type"]
    if kind == "object":
        require(isinstance(value, dict) and set(value) == set(schema["properties"]), "Output object schema mismatch")
        for key, spec in schema["properties"].items():
            validate_output(value[key], spec)
    elif kind == "array":
        require(isinstance(value, list) and len(value) <= 30, "Output array invalid")
        for item in value:
            validate_output(item, schema["items"])
    else:
        require(isinstance(value, str) and len(value) <= 8000, "Output string invalid")


def save_private(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    os.replace(temporary, path)


def amount(row):
    # A missing response is not evidence of a free call.
    return Decimal(str(row.get("cost_rub") if row.get("cost_rub") is not None else row["reserved_rub"]))


def reserve(ledger, key, ceiling, stamp, policy):
    require(not any(row["key"] == key for row in ledger), "Already attempted: explicit review required before any repeat")
    day, month = stamp[:10], stamp[:7]
    for limit, spent in (
        (policy["daily_limit_rub"], sum((amount(r) for r in ledger if r["at"][:10] == day), Decimal(0))),
        (policy["monthly_budget_rub"], sum((amount(r) for r in ledger if r["at"][:7] == month), Decimal(0))),
        (policy["evaluation_budget_rub"], sum((amount(r) for r in ledger), Decimal(0))),
    ):
        require(spent + ceiling <= Decimal(str(limit)), "Budget limit: cannot reserve next call")
    row = {"key": key, "at": stamp, "status": "pending", "reserved_rub": str(ceiling), "cost_rub": None}
    ledger.append(row)
    return row


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirect refused; credentials may only be sent to the fixed Yandex endpoint")


def run(case_ids=CASE_IDS):
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    credential_path = ROOT / ".env.yandex.local"
    require(credential_path.stat().st_mode & 0o077 == 0, "Credentials require private permissions")
    credentials = dict(line.split("=", 1) for line in credential_path.read_text().splitlines()
                       if "=" in line and not line.startswith("#"))
    require(all(credentials.get(key) for key in ("YANDEX_GPT_API_KEY", "YANDEX_GPT_FOLDER_ID")), "Missing credentials")
    policy = json.loads((DATASET / "pilot.template.json").read_text())
    # Explicit --run authorizes this bounded evaluation, not the application feature.
    require(policy["monthly_budget_rub"] <= 300 and policy["daily_limit_rub"] <= 10
            and policy["evaluation_budget_rub"] <= 30, "Policy exceeds pilot authorization")
    cases = {row["id"]: row for row in load_cases()}
    ledger_path = LOCAL / "cloud-ledger.json"
    with (LOCAL / "cloud-ledger.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
        for candidate in policy["candidates"]:
            for case_id in case_ids:
                case = cases[case_id]
                require(case["origin"] == "synthetic" and case["split"] == "tune", "Only synthetic tune cases permitted")
                schema = RAW_SCHEMAS[case["scenario"]]
                model_uri = candidate["model_uri_template"].replace("<folder_id>", credentials["YANDEX_GPT_FOLDER_ID"])
                payload = {"model": model_uri, "messages": [
                    {"role": "system", "content": PROMPTS[case["scenario"]]},
                    {"role": "user", "content": json.dumps({"scenario": case["scenario"], "input": case["input"]}, ensure_ascii=False)}],
                    "temperature": 0, "max_tokens": MAX_OUTPUT, "stream": False,
                    "response_format": {"type": "json_schema", "json_schema": {"name": case["scenario"], "schema": schema}}}
                encoded = json.dumps(payload, ensure_ascii=False).encode()
                fingerprint = hashlib.sha256(encoded).hexdigest()
                key = f'{candidate["id"]}:{case_id}:{PROMPT_VERSION}:{fingerprint}'
                if any(row["key"] == key for row in ledger):
                    print(f'{candidate["id"]}/{case_id}: already recorded, skipped')
                    continue
                input_rate = Decimal(str(candidate["sync_input_rub_per_1000_tokens"]))
                output_rate = Decimal(str(candidate["sync_output_rub_per_1000_tokens"]))
                # Conservative local estimate: every UTF-8 request byte as one input
                # token plus 1024 overhead, and the entire output limit. Provider
                # billing/discounts still need reconciliation; this is not a cloud cap.
                ceiling = (((len(encoded) + 1024) * input_rate + MAX_OUTPUT * output_rate) / 1000).quantize(Decimal("0.000001"), rounding=ROUND_UP)
                stamp = datetime.now(ZoneInfo("Asia/Yekaterinburg")).isoformat()
                record = reserve(ledger, key, ceiling, stamp, policy)
                record.update(candidate=candidate["id"], case_id=case_id, prompt_version=PROMPT_VERSION,
                              input_sha256=fingerprint, logging_disabled_header=True)
                save_private(ledger_path, ledger)  # Reserve durably before transmission.
                request = Request(ENDPOINT, data=encoded, headers={
                    "Content-Type": "application/json", "Authorization": "Api-Key " + credentials["YANDEX_GPT_API_KEY"],
                    "OpenAI-Project": credentials["YANDEX_GPT_FOLDER_ID"], "x-data-logging-enabled": "false"}, method="POST")
                started = time.monotonic()
                try:
                    with build_opener(NoRedirect()).open(request, timeout=30) as response:
                        result = json.load(response)
                    record["latency_seconds"] = round(time.monotonic() - started, 3)
                    usage = result.get("usage", {})
                    incoming, outgoing = usage.get("prompt_tokens"), usage.get("completion_tokens")
                    require(type(incoming) is int and incoming >= 0 and type(outgoing) is int and outgoing >= 0,
                            "Usage missing; cost reserve retained")
                    cost = (incoming * input_rate + outgoing * output_rate) / 1000
                    record.update(input_tokens=incoming, output_tokens=outgoing, cost_rub=str(cost),
                                  price_basis="public_sync_RUB_including_VAT_not_invoice_reconciled")
                    require(cost <= ceiling, "Usage exceeded conservative reserve; stop and reconcile")
                    choice = result["choices"][0]
                    require(choice["finish_reason"] == "stop", "Incomplete or refused response")
                    raw = json.loads(choice["message"]["content"])
                    report_path = LOCAL / f'{candidate["id"]}-{case_id}-{PROMPT_VERSION}.json'
                    # Keep paid evidence even if subsequent semantic validation fails.
                    save_private(report_path, {"candidate": candidate["id"], "case_id": case_id,
                        "prompt_version": PROMPT_VERSION, "raw_output": raw, "usage": usage,
                        "semantic_review": "validation_pending", "input_sha256": fingerprint})
                    validate_output(raw, schema)
                    output = grounded_output(case["input"], raw)
                    validate_output(output, SCHEMAS[case["scenario"]])
                    if case["scenario"] == "equipment_brief":
                        allowed = {s["id"] for s in case["input"]["sources"]}
                        require(all(fact["source_ids"] and set(fact["source_ids"]) <= allowed for fact in output["facts"]),
                                "Unknown or empty source references")
                    report = {"candidate": candidate["id"], "case_id": case_id, "prompt_version": PROMPT_VERSION,
                              "input_sha256": fingerprint, "output": output, "raw_output": raw, "usage": usage,
                              "returned_model": result.get("model", "").replace(credentials["YANDEX_GPT_FOLDER_ID"], "<folder_id>"),
                              "semantic_review": "pending", "schema_valid": True}
                    save_private(report_path, report)
                    record.update(status="succeeded", schema_valid=True)
                    save_private(ledger_path, ledger)
                    print(f'{candidate["id"]}/{case_id}: JSON OK, {record["latency_seconds"]}s, estimated {cost} RUB')
                except Exception as exc:
                    # Never print a raw provider exception/body, header or credential.
                    record.update(status="failed" if record.get("cost_rub") is not None else "unknown",
                                  error_kind=type(exc).__name__)
                    if isinstance(exc, HTTPError):
                        record["http_status"] = exc.code
                    save_private(ledger_path, ledger)
                    print(f'{candidate["id"]}/{case_id}: stopped ({record["error_kind"]}); see private ledger')
                    return 1
    print(f'Estimated total evaluation spend/reserve: {sum((amount(r) for r in ledger), Decimal(0))} RUB')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Perform paid synthetic evaluation within the stored pilot limits")
    parser.add_argument("--cases", nargs="+", choices=CASE_IDS, default=CASE_IDS,
                        help="Restrict a paid rerun to the affected synthetic tune cases")
    args = parser.parse_args()
    if not args.run:
        parser.error("No network calls by default; --run is required")
    try:
        return run(tuple(dict.fromkeys(args.cases)))
    except Exception as exc:
        print(f'Cloud check stopped: {type(exc).__name__}; credentials not displayed')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
