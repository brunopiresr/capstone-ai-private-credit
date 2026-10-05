"""Deterministic combination of section facts without legal reconciliation."""

import json

from credit_monitoring.domain import CovenantExtraction


def combine_extractions(parts: list[CovenantExtraction]) -> CovenantExtraction:
    values = {}
    conflicts = []
    for name in CovenantExtraction.model_fields:
        candidates = [getattr(part, name) for part in parts]
        if CovenantExtraction.model_fields[name].default_factory is list:
            items, seen = [], set()
            for candidate in candidates:
                for item in candidate:
                    value = item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                    key = json.dumps(value, sort_keys=True, ensure_ascii=False)
                    if key not in seen:
                        seen.add(key)
                        items.append(item)
            values[name] = items
        else:
            distinct = list(dict.fromkeys(c for c in candidates if c is not None))
            values[name] = distinct[0] if len(distinct) == 1 else None
            if len(distinct) > 1:
                conflicts.append(f"Sections disclose distinct {name} values: {distinct}.")
    values["conflicts"].extend(conflicts)
    return CovenantExtraction(**values)
