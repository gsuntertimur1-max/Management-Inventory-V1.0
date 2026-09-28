"""Capacity regression tests using an isolated, query-aware database double."""
import asyncio
import copy
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")
from backend import outbound_flow as flow


def values(row, path):
    if not path:
        return row if isinstance(row, list) else [row]
    if isinstance(row, list):
        return [v for item in row for v in values(item, path)]
    return values(row.get(path[0]), path[1:]) if isinstance(row, dict) else [None]


def matches(row, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(matches(row, part) for part in expected):
                return False
            continue
        actual = values(row, key.split("."))
        if isinstance(expected, dict):
            if "$ne" in expected and expected["$ne"] in actual:
                return False
            if "$regex" in expected and not any(re.search(expected["$regex"], str(v or ""), re.I if expected.get("$options") == "i" else 0) for v in actual):
                return False
        elif expected not in actual:
            return False
    return True


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, length):
        return copy.deepcopy(self.rows if length is None else self.rows[:length])


class Collection:
    def __init__(self):
        self.rows = []

    def find(self, query, projection=None):
        return Cursor([r for r in self.rows if matches(r, query)])

    async def find_one(self, query, projection=None):
        return next((copy.deepcopy(r) for r in self.rows if matches(r, query)), None)

    async def insert_one(self, row):
        self.rows.append(copy.deepcopy(row))

    async def delete_one(self, query):
        self.rows = [r for r in self.rows if not matches(r, query)]

    async def update_one(self, query, update):
        for row in self.rows:
            if matches(row, query):
                row.update(copy.deepcopy(update.get("$set", {})))
                return

    async def replace_one(self, query, row, upsert=False):
        for i, current in enumerate(self.rows):
            if matches(current, query):
                self.rows[i] = copy.deepcopy(row)
                return
        if upsert:
            self.rows.append(copy.deepcopy(row))


@pytest.fixture
def database(monkeypatch):
    db = SimpleNamespace(outbound_documents=Collection(), outbound_loads=Collection())
    monkeypatch.setattr(flow, "db", db)
    return db


PRODUCTS = {k: {"id": k, "name": k, "unit": "pack", "channel": "KOM"} for k in ["P1", "P2"]}


def item(doc, qty, total=0, product="P1"):
    return flow.OutboundItemInput(productId=product, documentNo=doc, qty=qty, documentQty=total)


async def prepare(refs, rows, parties=None, exclude=""):
    return await flow._prepare_so_documents(refs=refs, body_items=rows, products=PRODUCTS,
        party="Recipient A", document_parties=parties, exclude_load_id=exclude)


def load(doc, qty, status="Menunggu", ident="L1"):
    return {"id": ident, "ref": doc, "documents": [doc], "document_type": flow._document_type(doc),
        "status": status, "items": [{"productId": "P1", "qty": qty, "documentNo": doc}]}


@pytest.mark.parametrize("kind", ["SO", "TM", "ND", "MEMO", "CT"])
def test_vehicles_reservations_completion_cancel_and_exhaustion(database, kind):
    async def scenario():
        doc = kind + "/001"
        masters, progress = await prepare([doc], [item(doc, 40, 100)])
        assert progress[doc][0]["remainingAfter"] == 60
        await flow._persist_so_documents(masters, "tester")
        database.outbound_loads.rows.append(load(doc, 40))
        balance = await flow._so_balance(doc)
        assert balance["documentType"] == kind
        assert balance["items"][0]["reservedQty"] == 40
        with pytest.raises(HTTPException) as error:
            await prepare([doc], [item(doc, 61)])
        assert error.value.status_code == 409
        database.outbound_loads.rows[0]["status"] = "Selesai"
        await prepare([doc], [item(doc, 60)])
        database.outbound_loads.rows.append(load(doc, 60, ident="L2"))
        balance = await flow._so_balance(doc)
        assert balance["status"] == "SEBAGIAN"
        assert balance["items"][0]["completedQty"] == 40
        assert balance["items"][0]["remainingQty"] == 0
        with pytest.raises(HTTPException):
            await prepare([doc], [item(doc, 1)])
        database.outbound_loads.rows[1]["status"] = "Dibatalkan"
        assert (await flow._so_balance(doc))["items"][0]["remainingQty"] == 60
        database.outbound_loads.rows[1]["status"] = "Selesai"
        assert (await flow._so_balance(doc))["status"] == "SELESAI"
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["TM", "ND", "MEMO", "CT"])
def test_multi_document_product_recipient_and_edit(database, kind):
    async def scenario():
        a, b = kind + "/A", kind + "/B"
        parties = {a: "Recipient A", b: "Recipient B"}
        masters, _ = await prepare([a, b], [item(a, 20, 100), item(a, 30, 100), item(a, 5, 20, "P2"), item(b, 10, 30)], parties)
        await flow._persist_so_documents(masters, "tester")
        assert [m["party"] for m in masters] == ["Recipient A", "Recipient B"]
        database.outbound_loads.rows.append(load(a, 50))
        _, progress = await prepare([a], [item(a, 100)], exclude="L1")
        assert progress[a][0]["remainingAfter"] == 0
        with pytest.raises(HTTPException):
            await prepare([a], [item(a, 51)])
        with pytest.raises(HTTPException):
            await prepare([a], [item(a, 1)], {a: "Other recipient"})
        with pytest.raises(HTTPException):
            await prepare([a], [item(a, 1, 101)])
        with pytest.raises(HTTPException):
            await prepare([b], [item(b, 1, 30), item(b, 1, 31)], {b: "Recipient B"})
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["TM", "ND", "MEMO", "CT"])
def test_legacy_fallback_requires_original_total(database, kind):
    async def scenario():
        doc = kind + "/LEGACY"
        old = load(doc.lower(), 40, "Selesai")
        old["items"][0].pop("documentNo")
        database.outbound_loads.rows.append(old)
        balance = await flow._so_balance(doc)
        assert not balance["exists"]
        assert balance["legacyUsage"]["P1"]["completedQty"] == 40
        with pytest.raises(HTTPException):
            await prepare([doc], [item(doc, 10)])
        with pytest.raises(HTTPException):
            await prepare([doc], [item(doc, 61, 100)])
        masters, _ = await prepare([doc], [item(doc, 60, 100)])
        await flow._persist_so_documents(masters, "tester")
        assert (await flow._so_balance(doc))["items"][0]["remainingQty"] == 60
    asyncio.run(scenario())


def test_linked_number_stays_protected(database):
    database.outbound_loads.rows.append({"document_links": [{"no": "ND/LINKED"}]})
    with pytest.raises(HTTPException):
        asyncio.run(prepare(["ND/LINKED"], [item("ND/LINKED", 1, 10)]))


def test_nonfinite_quantities_rejected():
    for value in [float("inf"), float("nan")]:
        with pytest.raises(ValueError):
            item("TM/001", 1, value)


@pytest.mark.parametrize("kind", ["SO", "TM", "ND", "MEMO", "CT"])
@pytest.mark.parametrize("condition", ["BAIK", "RUSAK"])
def test_create_path_multiple_vehicles_and_edit(database, monkeypatch, kind, condition):
    from backend import damaged_outbound as damaged
    from unittest.mock import AsyncMock
    database.products = Collection()
    database.products.rows = [{**PRODUCTS["P1"], "stock": 1000, "damaged": 1000}]
    database.stack_allocations = Collection()
    database.stack_allocations.rows = [{"productId": "P1", "stackCode": "18/A01", "primaryQty": 1000}]
    for module in [flow, damaged]:
        monkeypatch.setattr(module, "db", database)
        monkeypatch.setattr(module, "ensure_channel_stock", AsyncMock())
        monkeypatch.setattr(module, "channel_balance", lambda *a: 1000)
        monkeypatch.setattr(module, "_reserved_qty", AsyncMock(return_value=0))
        monkeypatch.setattr(module, "max_suffix", AsyncMock(return_value=0))
        monkeypatch.setattr(module, "next_sequence", AsyncMock(return_value=1))
        monkeypatch.setattr(module, "get_operational_location", AsyncMock(return_value={}))
    monkeypatch.setattr(flow, "valid_stack_codes", AsyncMock(return_value=["18/A01"]))
    monkeypatch.setattr(flow, "get_fefo_pick_guide", AsyncMock(return_value={}))
    monkeypatch.setattr(flow, "selection_requires_reason", lambda *a: False)
    monkeypatch.setattr(flow, "available_stack_qty", AsyncMock(return_value=(0, 1000)))
    monkeypatch.setattr(flow, "_loading_fee", lambda *a, **k: {})

    async def scenario():
        doc = kind + "/CREATE"
        create = damaged.create_damaged_outbound_load if condition == "RUSAK" else flow.create_outbound_load
        def body(qty, total=0):
            return flow.OutboundCreateInput(documentType=kind, kondisi=condition,
                transferScope="LOKAL" if kind == "TM" else "", party="Recipient A",
                documents=[doc], items=[flow.OutboundItemInput(productId="P1",
                    documentNo=doc, qty=qty, documentQty=total,
                    stackCode="18/A01" if condition == "BAIK" else "")])
        first = await create(body(40, 100), {"name": "tester"})
        second = await create(body(60), {"name": "tester"})
        assert first["id"] != second["id"]
        assert first["document_parties"] == {doc: "Recipient A"}
        assert second["items"][0]["documentQty"] == 100
        assert second["document_progress"][doc][0]["remainingAfter"] == 0
        with pytest.raises(HTTPException):
            await create(body(1), {"name": "tester"})
        revised = await flow.edit_outbound_load(first["id"],
            flow.OutboundEditInput(documents=[doc], items=body(30).items), {"name": "tester"})
        assert revised["document_parties"] == {doc: "Recipient A"}
        assert revised["items"][0]["qty"] == 30
        assert revised["edit_history"]
        assert (await flow._so_balance(doc))["items"][0]["remainingQty"] == 10
        with pytest.raises(HTTPException):
            await flow.edit_outbound_load(first["id"],
                flow.OutboundEditInput(documents=[doc], items=body(41).items), {"name": "tester"})
    asyncio.run(scenario())
