"""Offline AI-00 preparation. Standard library only; no API, DB or .env access."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from statistics import median
import sys


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "yandexgpt"
FILES = {"repair_cases.jsonl": ("repair_draft", 50),
         "history_cases.jsonl": ("equipment_brief", 30)}
TIMINGS = ("text_seconds", "history_seconds", "network_seconds",
           "review_seconds", "correction_seconds")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def strings(value, label, nonempty=False):
    require(isinstance(value, list), f"{label}: expected list")
    require(not nonempty or len(value) > 0, f"{label}: empty list")
    require(all(isinstance(x, str) and x.strip() for x in value),
            f"{label}: expected nonempty strings")
    require(len(set(value)) == len(value), f"{label}: duplicates")


def load_cases(directory=DATASET):
    cases, identifiers, fingerprints, families = [], set(), set(), {}
    for filename, (scenario, minimum) in FILES.items():
        path = directory / filename
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        require(len(rows) >= minimum, f"{filename}: expected at least {minimum} cases")
        for row in rows:
            require(isinstance(row, dict), f"{filename}: case must be an object")
            label = row.get("id", "missing id")
            require(isinstance(label, str) and bool(label.strip()) and label not in identifiers,
                    f"{label}: missing/duplicate case ID")
            identifiers.add(label)
            require(row.get("scenario") == scenario, f"{label}: wrong scenario")
            require(row.get("origin") == "synthetic", f"{label}: starter fixtures must be synthetic")
            require(row.get("review_status") in {"needs_domain_review", "domain_reviewed"},
                    f"{label}: invalid review status")
            split = row.get("split")
            require(split in {"tune", "holdout"}, f"{label}: invalid split")
            family = row.get("family")
            require(isinstance(family, str) and bool(family.strip()), f"{label}: missing family")
            key = (scenario, family)
            require(families.setdefault(key, split) == split, f"{label}: family leaks across splits")
            strings(row.get("tags"), f"{label}.tags", nonempty=True)
            payload = row.get("input")
            require(isinstance(payload, dict), f"{label}: missing input")
            # Detect exact duplicate inputs even if the case ID has been changed.
            fingerprint = (scenario, json.dumps(payload, ensure_ascii=False, sort_keys=True))
            require(fingerprint not in fingerprints, f"{label}: duplicate input")
            fingerprints.add(fingerprint)
            expected = row.get("expected")
            require(isinstance(expected, dict), f"{label}: missing expected rubric")
            for field in ("required_facts", "forbidden_claims", "question_topics", "source_ids"):
                strings(expected.get(field), f"{label}.{field}",
                        nonempty=field in {"required_facts", "forbidden_claims"})
            require(isinstance(expected.get("acceptable_rendering"), str)
                    and expected["acceptable_rendering"].strip(), f"{label}: missing example rendering")
            if scenario == "repair_draft":
                require(isinstance(payload.get("note"), str) and payload["note"].strip(),
                        f"{label}: missing note")
                require(not expected["source_ids"], f"{label}: unexpected sources")
            else:
                sources = payload.get("sources")
                require(isinstance(sources, list), f"{label}: missing sources")
                source_ids = []
                for source in sources:
                    require(isinstance(source, dict), f"{label}: invalid source")
                    source_ids.append(source.get("id"))
                    require(isinstance(source.get("text"), str) and source["text"].strip(),
                            f"{label}: empty source text")
                    require(isinstance(source.get("kind"), str) and source["kind"].strip(),
                            f"{label}: missing source kind")
                    date.fromisoformat(source["date"])
                strings(source_ids, f"{label}.sources")
                require(set(expected["source_ids"]) <= set(source_ids), f"{label}: unknown expected source")
                coverage = payload.get("coverage", {})
                require(type(coverage.get("included_count")) is int
                        and coverage["included_count"] == len(sources), f"{label}: incorrect coverage count")
                require(type(coverage.get("truncated")) is bool, f"{label}: missing coverage flag")
            cases.append(row)
        require({r["split"] for r in rows} == {"tune", "holdout"}, f"{filename}: both splits required")
    return cases


def dataset_summary(directory=DATASET):
    cases = load_cases(directory)
    return {"status": "fixtures_valid_not_model_evaluation", "cases": len(cases),
            "counts": dict(sorted(Counter(f'{r["scenario"]}/{r["split"]}' for r in cases).items())),
            "domain_review_pending": sum(r["review_status"] == "needs_domain_review" for r in cases),
            "sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in FILES}}


def baseline_summary(path):
    document = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(document, dict) and document.get("schema_version") == 1,
            "baseline: unsupported schema")
    rows = document.get("sessions")
    require(isinstance(rows, list), "baseline: sessions must be a list")
    groups, identifiers = defaultdict(list), set()
    for row in rows:
        require(isinstance(row, dict), "baseline: invalid session")
        identifier = row.get("sample_id")
        require(isinstance(identifier, str) and identifier.strip() and identifier not in identifiers,
                "baseline: missing/duplicate sample ID")
        identifiers.add(identifier)
        require(row.get("mode") in {"manual", "ai"}, f"{identifier}: invalid mode")
        require(row.get("complexity") in {"simple", "standard", "complex"}, f"{identifier}: invalid complexity")
        for field in TIMINGS:
            value = row.get(field)
            require(type(value) in {int, float} and math.isfinite(value) and value >= 0,
                    f"{identifier}: {field} must be finite and nonnegative")
        total = sum(row[field] for field in TIMINGS)
        require(total > 0, f"{identifier}: zero-duration observation")
        groups[(row["mode"], row["complexity"])].append((row, total))
    manual_count = sum(len(values) for (mode, _), values in groups.items() if mode == "manual")
    return {"status": "minimum_sample_collected" if manual_count >= 20 else "insufficient_baseline",
            "manual_samples": manual_count, "minimum_manual_samples": 20,
            "groups": [{"mode": mode, "complexity": complexity, "samples": len(values),
                        "median_total_seconds": median(total for _, total in values),
                        "median_components_seconds": {field: median(row[field] for row, _ in values) for field in TIMINGS}}
                       for (mode, complexity), values in sorted(groups.items())]}


def export_inputs(cases, split):
    # Gold facts, examples and family labels must never become model input.
    return [{"id": row["id"], "scenario": row["scenario"], "input": row["input"]}
            for row in cases if row["split"] == split]


def review_template(cases, split, candidate):
    return {"schema_version": 1, "status": "not_run", "candidate": candidate,
            "split": split, "prompt_version": None, "model_uri": None,
            "reviews": [{"case_id": row["id"], "rubric": row["expected"], "output": None,
                         "schema_valid": None, "all_required_facts_preserved": None,
                         "critical_fabrication": None, "sources_supported": None,
                         "latency_seconds": None, "input_tokens": None, "output_tokens": None,
                         "cost_rub": None, "reviewer_code": None, "notes": ""}
                        for row in cases if row["split"] == split]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    baseline = sub.add_parser("baseline-summary")
    baseline.add_argument("--input", type=Path, required=True)
    export = sub.add_parser("export-inputs")
    export.add_argument("--split", choices=("tune", "holdout"), required=True)
    review = sub.add_parser("review-template")
    review.add_argument("--split", choices=("tune", "holdout"), required=True)
    review.add_argument("--candidate", choices=("pro-51", "pro-5"), required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            result = dataset_summary()
        elif args.command == "baseline-summary":
            result = baseline_summary(args.input)
        elif args.command == "export-inputs":
            result = export_inputs(load_cases(), args.split)
        else:
            result = review_template(load_cases(), args.split, args.candidate)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"AI preflight failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
