#!/usr/bin/env python3

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402

VOLATILE_KEYS = {
    "generatedAt",
    "estimatedSubscriptionCapturedAt",
    "estimatedSubscriptionLastCheckedAt",
    "estimatedSubscriptionStatus",
}


def without_volatile(value):
    if isinstance(value, dict):
        return {
            key: without_volatile(item)
            for key, item in value.items()
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [without_volatile(item) for item in value]
    return value


def significant_payload_changed(before, after):
    return without_volatile(before) != without_volatile(after)


def main():
    before = app.read_official_updates()
    before_text = app.OFFICIAL_UPDATES_FILE.read_text(encoding="utf-8") if app.OFFICIAL_UPDATES_FILE.exists() else None
    result = app.build_check_official_updates_response()
    after = app.read_official_updates()
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if before_text is not None and not significant_payload_changed(before, after):
        app.OFFICIAL_UPDATES_FILE.write_text(before_text, encoding="utf-8")
        print("No significant data changes; restored timestamp-only update.")

    failures = [
        item
        for item in result.get("items", [])
        if item.get("status") in {"error", "apply_error"}
    ]
    if failures:
        print(f"warning: {len(failures)} update item(s) need attention", file=sys.stderr)


if __name__ == "__main__":
    main()
