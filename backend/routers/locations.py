"""Lokasi gudang (kompleks → unit → tumpukan) dan penempatan stok per tumpukan."""
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from lib.auth import principal
from lib.db import db
from models.locations import (
    WAREHOUSE_UNITS,
    DistributeResult,
    Location,
    LocationCreate,
    LocationStackSummary,
    Placement,
    PlacementCreate,
)

router = APIRouter()


async def ensure_locations() -> None:
    """Seed katalog tumpukan sekali; tumpukan tambahan buatan admin tidak disentuh."""
    await _normalise_stack_names()
    existing = {doc["code"] async for doc in db.locations.find({}, {"code": 1})}
    fresh: List[Dict[str, Any]] = []
    for unit_name, complex_name, stacks in WAREHOUSE_UNITS:
        for stack in stacks:
            code = f"{unit_name}/{stack}"
            if code in existing:
                continue
            fresh.append(
                Location(code=code, complex_name=complex_name, unit_name=unit_name, stack=stack).model_dump()
            )
    if fresh:
        await db.locations.insert_many(fresh)


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    doc.pop("_id", None)
    return doc


async def _normalise_stack_names() -> None:
    """Nama tumpukan lama dengan segmen ekstra (A02.1.1.1) dirapikan jadi A02.1.1."""
    async for loc in db.locations.find({"stack": {"$regex": r"\.1\.1\.1$"}}):
        new_stack = loc["stack"].replace(".1.1.1", ".1.1")
        new_code = f"{loc['unit_name']}/{new_stack}"
        if await db.locations.find_one({"code": new_code}):
            await db.locations.delete_one({"id": loc["id"]})
        else:
            await db.locations.update_one(
                {"id": loc["id"]}, {"$set": {"stack": new_stack, "code": new_code}}
            )
        await db.placements.update_many(
            {"location_code": loc["code"]},
            {"$set": {"stack": new_stack, "location_code": new_code}},
        )


def _sort_key(code: str) -> tuple:
    unit, _, stack = code.partition("/")
    prefix = "".join(ch for ch in unit if ch.isalpha())
    digits = "".join(ch for ch in unit if ch.isdigit())
    return (prefix, int(digits or 0), stack)


@router.get("/locations", response_model=List[Location])
async def list_locations() -> List[Location]:
    docs = await db.locations.find().to_list(2000)
    items = [Location(**_clean(d)) for d in docs]
    items.sort(key=lambda l: _sort_key(l.code))
    return items


@router.post("/locations", response_model=Location)
async def create_location(payload: LocationCreate) -> Location:
    stack = payload.stack.strip()
    unit_name = payload.unit_name.strip()
    if not stack or not unit_name:
        raise HTTPException(status_code=400, detail="Unit gudang dan nama tumpukan wajib diisi")
    code = f"{unit_name}/{stack}"
    if await db.locations.find_one({"code": code}):
        raise HTTPException(status_code=400, detail=f"Tumpukan {code} sudah ada")
    loc = Location(
        code=code, complex_name=payload.complex_name.strip() or "Gudang Sunter Timur I",
        unit_name=unit_name, stack=stack,
    )
    await db.locations.insert_one(loc.model_dump())
    return loc


@router.delete("/locations/{location_id}")
async def delete_location(location_id: str) -> Dict[str, Any]:
    doc = await db.locations.find_one({"id": location_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Tumpukan tidak ditemukan")
    used = await db.placements.count_documents({"location_code": doc["code"]})
    if used:
        raise HTTPException(status_code=400, detail="Tumpukan masih berisi stok, kosongkan dulu")
    await db.locations.delete_one({"id": location_id})
    return {"ok": True, "id": location_id}


@router.get("/locations/summary", response_model=List[LocationStackSummary])
async def locations_summary() -> List[LocationStackSummary]:
    locs = await db.locations.find().to_list(2000)
    placements = await db.placements.find().to_list(5000)
    agg: Dict[str, Dict[str, float]] = {}
    for p in placements:
        bucket = agg.setdefault(p.get("location_code", ""), {"n": 0, "sec": 0, "kg": 0.0})
        bucket["n"] += 1
        bucket["sec"] += int(p.get("secondary_count", 0))
        bucket["kg"] += float(p.get("total_weight", 0))
    out = [
        LocationStackSummary(
            code=l["code"], complex_name=l.get("complex_name", ""), unit_name=l.get("unit_name", ""),
            stack=l.get("stack", ""),
            product_count=int(agg.get(l["code"], {}).get("n", 0)),
            total_secondary=int(agg.get(l["code"], {}).get("sec", 0)),
            total_weight=round(float(agg.get(l["code"], {}).get("kg", 0)), 3),
        )
        for l in locs
    ]
    out.sort(key=lambda s: _sort_key(s.code))
    return out


async def _build_placement(payload: PlacementCreate, actor_name: str, keep: Optional[Dict[str, Any]] = None) -> Placement:
    loc = await db.locations.find_one({"code": payload.location_code})
    if not loc:
        raise HTTPException(status_code=400, detail="Tumpukan tidak dikenal")
    product = await db.products.find_one({"id": payload.product_id})
    if not product:
        raise HTTPException(status_code=400, detail="Produk tidak ditemukan")

    ups = int(product.get("units_per_secondary", 1)) or 1
    wpu = float(product.get("weight_per_unit", 1) or 1)
    secondary = payload.length * payload.width * payload.height
    weight_per_secondary = round(wpu * ups, 4)

    return Placement(
        id=(keep or {}).get("id") or str(uuid.uuid4()),
        location_code=payload.location_code,
        product_id=payload.product_id,
        length=payload.length, width=payload.width, height=payload.height,
        notes=payload.notes,
        complex_name=loc.get("complex_name", ""), unit_name=loc.get("unit_name", ""),
        stack=loc.get("stack", ""),
        product_name=product.get("name", ""), product_sku=product.get("sku", ""),
        unit=product.get("unit", "Pcs"),
        secondary_unit=product.get("secondary_unit", "Karung"),
        units_per_secondary=ups,
        weight_per_unit=wpu, weight_unit=product.get("weight_unit", "Kg"),
        secondary_count=secondary,
        weight_per_secondary=weight_per_secondary,
        total_units=secondary * ups,
        total_weight=round(secondary * weight_per_secondary, 3),
        created_by_name=(keep or {}).get("created_by_name") or actor_name,
    )


@router.get("/placements", response_model=List[Placement])
async def list_placements(
    unit_name: Optional[str] = Query(None),
    location_code: Optional[str] = Query(None),
    product_id: Optional[str] = Query(None),
) -> List[Placement]:
    query: Dict[str, Any] = {}
    if unit_name:
        query["unit_name"] = unit_name
    if location_code:
        query["location_code"] = location_code
    if product_id:
        query["product_id"] = product_id
    docs = await db.placements.find(query).to_list(5000)
    items = [Placement(**_clean(d)) for d in docs]
    items.sort(key=lambda p: (_sort_key(p.location_code), p.product_name))
    return items


@router.post("/placements", response_model=Placement)
async def create_placement(payload: PlacementCreate, user=Depends(principal)) -> Placement:
    actor = getattr(user, "full_name", "") or getattr(user, "username", "")
    placement = await _build_placement(payload, actor)
    await db.placements.insert_one(placement.model_dump())
    return placement


@router.put("/placements/{placement_id}", response_model=Placement)
async def update_placement(placement_id: str, payload: PlacementCreate, user=Depends(principal)) -> Placement:
    existing = await db.placements.find_one({"id": placement_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Penempatan tidak ditemukan")
    actor = getattr(user, "full_name", "") or getattr(user, "username", "")
    placement = await _build_placement(payload, actor, keep=_clean(existing))
    await db.placements.replace_one({"id": placement_id}, placement.model_dump())
    return placement


@router.delete("/placements/{placement_id}")
async def delete_placement(placement_id: str) -> Dict[str, Any]:
    res = await db.placements.delete_one({"id": placement_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Penempatan tidak ditemukan")
    return {"ok": True, "id": placement_id}


def _factorize(n: int) -> tuple:
    """Pecah jumlah kemasan menjadi P × L × T yang serapat mungkin (T maks 25, L maks 22)."""
    best = (n, 1, 1)
    best_score = None
    for t in range(1, min(n, 25) + 1):
        if n % t:
            continue
        rest = n // t
        for l in range(1, min(rest, 22) + 1):
            if rest % l:
                continue
            p = rest // l
            score = max(p, l, t) - min(p, l, t)
            if best_score is None or score < best_score:
                best_score, best = score, (p, l, t)
    return best


@router.post("/placements/distribute", response_model=DistributeResult)
async def distribute_stock(user=Depends(principal)) -> DistributeResult:
    """Sebar seluruh stok produk saat ini ke tumpukan-tumpukan gudang (mengganti data lama)."""
    await ensure_locations()
    locs = await db.locations.find().to_list(2000)
    locs.sort(key=lambda l: _sort_key(l["code"]))
    if not locs:
        raise HTTPException(status_code=400, detail="Katalog tumpukan kosong")

    products = await db.products.find().sort("name", 1).to_list(2000)
    actor = getattr(user, "full_name", "") or getattr(user, "username", "")

    # Urutan interleaved: tumpukan ke-1 tiap unit gudang dulu, lalu ke-2, dst — supaya
    # stok tersebar merata ke kedua kompleks (GBB 17-24 + MP 1), bukan menumpuk di unit awal.
    by_unit: Dict[str, List[Dict[str, Any]]] = {}
    for loc in locs:
        by_unit.setdefault(loc["unit_name"], []).append(loc)
    interleaved: List[Dict[str, Any]] = []
    depth = max(len(v) for v in by_unit.values())
    for i in range(depth):
        for unit in by_unit:
            if i < len(by_unit[unit]):
                interleaved.append(by_unit[unit][i])
    locs = interleaved

    await db.placements.delete_many({})
    docs: List[Dict[str, Any]] = []
    skipped: List[str] = []
    used = 0
    counted_products = 0

    for product in products:
        stock = int(product.get("current_stock", 0))
        if stock <= 0:
            skipped.append(f"{product.get('name', '')} (stok 0)")
            continue
        ups = int(product.get("units_per_secondary", 1)) or 1
        wpu = float(product.get("weight_per_unit", 1) or 1)
        secondary_total = max(1, round(stock / ups))
        # pecah stok jadi beberapa tumpukan agar tersebar di beberapa unit gudang
        parts = 3 if secondary_total >= 60 else 2 if secondary_total >= 12 else 1
        base = secondary_total // parts
        chunks = [base] * (parts - 1) + [secondary_total - base * (parts - 1)]
        counted_products += 1
        for chunk in chunks:
            if chunk <= 0:
                continue
            loc = locs[used % len(locs)]
            used += 1
            p, l, t = _factorize(chunk)
            secondary = p * l * t
            wps = round(wpu * ups, 4)
            docs.append(Placement(
                location_code=loc["code"], product_id=product["id"],
                length=p, width=l, height=t,
                notes="Sebar otomatis dari stok tersedia",
                complex_name=loc.get("complex_name", ""), unit_name=loc.get("unit_name", ""),
                stack=loc.get("stack", ""),
                product_name=product.get("name", ""), product_sku=product.get("sku", ""),
                unit=product.get("unit", "Pcs"),
                secondary_unit=product.get("secondary_unit", "Karung"),
                units_per_secondary=ups, weight_per_unit=wpu,
                weight_unit=product.get("weight_unit", "Kg"),
                secondary_count=secondary, weight_per_secondary=wps,
                total_units=secondary * ups, total_weight=round(secondary * wps, 3),
                created_by_name=actor,
            ).model_dump())

    if docs:
        await db.placements.insert_many(docs)
    return DistributeResult(
        ok=True, placements=len(docs), products=counted_products,
        total_weight=round(sum(float(d["total_weight"]) for d in docs), 3),
        skipped=skipped[:20],
    )
