from __future__ import annotations

from collections import OrderedDict
import re


def _unit_from_source(source: str) -> str:
    text = str(source or "").strip().upper()
    match = re.search(r"(?:^|\b)(MP1|(?:UNIT\s*)?(?:1[7-9]|2[0-4]))(?=/|\b)", text)
    if not match:
        return ""
    return match.group(1).replace("UNIT", "").strip()


def build_loading_plan(items: list[dict]) -> list[dict]:
    """Group an outbound load by physical loading unit without losing stack/document detail."""
    groups: OrderedDict[str, dict] = OrderedDict()
    for item in items or []:
        stack = str(item.get("stackCode") or item.get("location") or "").strip().upper()
        unit = _unit_from_source(stack) or "LAINNYA"
        group = groups.setdefault(unit, {"unit": unit, "stacks": [], "documents": [], "products": [], "qty": 0.0})

        if stack and stack not in group["stacks"]:
            group["stacks"].append(stack)
        document = str(item.get("documentNo") or "").strip()
        if document and document not in group["documents"]:
            group["documents"].append(document)
        product = str(item.get("name") or item.get("sku") or "").strip()
        if product and product not in group["products"]:
            group["products"].append(product)
        try:
            group["qty"] += float(item.get("qty") or 0)
        except (TypeError, ValueError):
            pass

    return list(groups.values())


def loading_route_label(items: list[dict]) -> str:
    parts = []
    for group in build_loading_plan(items):
        unit = "MP1" if group["unit"] == "MP1" else (f"Unit {group['unit']}" if group["unit"] != "LAINNYA" else "Lokasi lain")
        stacks = ", ".join(group["stacks"]) or "-"
        parts.append(f"{unit} ({stacks})")
    return " -> ".join(parts) or "Lokasi belum tercatat"
