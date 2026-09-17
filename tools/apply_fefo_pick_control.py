from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str):
    p = ROOT / path
    text = p.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Patch needle not found in {path}: {old[:120]!r}')
    p.write_text(text.replace(old, new, 1), encoding='utf-8')


# --- backend FEFO selection guide ---
fefo_selection = '''from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException

from backend.server import db, get_current_user
from backend.stack_lots import EPS, _n, expiry_status, lot_sort_key

router = APIRouter(prefix="/api")


def build_fefo_pick_guide(product_id: str, allocations: list[dict], lots: list[dict]) -> dict:
    stack_qty = defaultdict(float)
    stack_meta = {}
    for allocation in allocations:
        code = str(allocation.get("stackCode") or "").strip().upper()
        if not code:
            continue
        qty = _n(allocation.get("primaryQty"))
        if qty <= EPS:
            continue
        stack_qty[code] += qty
        stack_meta.setdefault(code, {
            "stackCode": code,
            "unit": allocation.get("unit", ""),
            "product": allocation.get("productName", ""),
            "sku": allocation.get("sku", ""),
        })

    lots_by_stack: dict[str, list[dict]] = defaultdict(list)
    for raw in lots:
        code = str(raw.get("stackCode") or "").strip().upper()
        if not code or _n(raw.get("remainingQty")) <= EPS or str(raw.get("status") or "").upper() == "DIBATALKAN":
            continue
        lot = dict(raw)
        lot["stackCode"] = code
        lot["expiryStatus"] = expiry_status(lot.get("exp", ""))
        lots_by_stack[code].append(lot)

    rows = []
    for code in sorted(stack_qty):
        stack_lots = sorted(lots_by_stack.get(code, []), key=lot_sort_key)
        tracked = sum(_n(lot.get("remainingQty")) for lot in stack_lots)
        physical = stack_qty[code]
        row = {
            **stack_meta.get(code, {}),
            "stackCode": code,
            "stackQty": physical,
            "trackedQty": tracked,
            "untrackedQty": max(physical - tracked, 0.0),
            "overtrackedQty": max(tracked - physical, 0.0),
            "coveragePct": (tracked / physical * 100) if physical > EPS else 100.0,
            "nextLot": stack_lots[0] if stack_lots else None,
            "activeLotCount": len(stack_lots),
        }
        rows.append(row)

    integrity_error = any(row["overtrackedQty"] > EPS for row in rows)
    legacy_rows = [row for row in rows if row["untrackedQty"] > EPS]
    tracked_rows = [row for row in rows if row.get("nextLot")]

    if integrity_error:
        recommended = []
        mode = "INTEGRITY_ERROR"
        reason = "Coverage lot melebihi stok tumpukan. Perbaiki Kontrol Integritas sebelum menjadikan FEFO sebagai acuan wajib."
    elif legacy_rows:
        recommended = [row["stackCode"] for row in sorted(legacy_rows, key=lambda row: row["stackCode"])]
        mode = "LEGACY_FIRST"
        reason = "Stok legacy/untracked diprioritaskan untuk verifikasi/pengeluaran sebelum lot bernama dikurangi."
    elif tracked_rows:
        ordered = sorted(tracked_rows, key=lambda row: (lot_sort_key(row["nextLot"]), row["stackCode"]))
        recommended = [ordered[0]["stackCode"]]
        mode = "FEFO_TRACKED"
        reason = "Semua stok telah terlacak lot; pilih tumpukan dengan lot kedaluwarsa terdekat."
    else:
        recommended = [row["stackCode"] for row in rows]
        mode = "LEGACY_ONLY" if rows else "NO_STOCK"
        reason = "Belum ada lot terlacak; pilih tumpukan stok fisik yang tersedia."

    priority = {code: index for index, code in enumerate(recommended)}
    rows.sort(key=lambda row: (
        0 if row["stackCode"] in priority else 1,
        priority.get(row["stackCode"], 9999),
        lot_sort_key(row.get("nextLot") or {}),
        row["stackCode"],
    ))
    return {
        "productId": product_id,
        "policy": "CONSERVATIVE_LEGACY_FIRST",
        "mode": mode,
        "reason": reason,
        "recommendedStacks": recommended,
        "requiresManualVerification": mode in {"LEGACY_FIRST", "LEGACY_ONLY", "INTEGRITY_ERROR"},
        "stacks": rows,
    }


def selection_requires_reason(guide: dict, stack_code: str) -> bool:
    selected = str(stack_code or "").strip().upper()
    recommended = [str(code or "").strip().upper() for code in guide.get("recommendedStacks", []) if str(code or "").strip()]
    return bool(selected and recommended and selected not in recommended)


async def get_fefo_pick_guide(product_id: str) -> dict:
    product = await db.products.find_one({"id": product_id}, {"_id": 0, "id": 1})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    allocations = await db.stack_allocations.find(
        {"productId": product_id, "primaryQty": {"$gt": EPS}},
        {"_id": 0},
    ).to_list(10000)
    lots = await db.stack_lots.find(
        {"productId": product_id, "remainingQty": {"$gt": EPS}, "status": {"$ne": "DIBATALKAN"}},
        {"_id": 0},
    ).to_list(10000)
    return build_fefo_pick_guide(product_id, allocations, lots)


@router.get("/fefo-pick-guide/{product_id}")
async def fefo_pick_guide(product_id: str, user: dict = Depends(get_current_user)):
    return await get_fefo_pick_guide(product_id)
'''
(ROOT / 'backend/fefo_selection.py').write_text(fefo_selection, encoding='utf-8')

# --- backend outbound validation + audit ---
replace_once(
    'backend/outbound_flow.py',
    'from backend.stack_allocations import valid_stack_codes, allocate_stock_to_stack, decrease_stack_allocation, reconcile_product_allocations\n',
    'from backend.stack_allocations import valid_stack_codes, allocate_stock_to_stack, decrease_stack_allocation, reconcile_product_allocations\nfrom backend.fefo_selection import get_fefo_pick_guide, selection_requires_reason\n',
)
replace_once(
    'backend/outbound_flow.py',
    '    channel: str = ""\n\n\nclass OutboundCreateInput',
    '    channel: str = ""\n    fefoExceptionReason: str = Field(default="", max_length=500)\n\n\nclass OutboundCreateInput',
)
replace_once(
    'backend/outbound_flow.py',
    '    multi_source = len(refs) > 1 or len(body.items) > 1\n    load_items = []\n    for item in body.items:\n',
    '    multi_source = len(refs) > 1 or len(body.items) > 1\n    load_items = []\n    fefo_guides = {}\n    for item in body.items:\n',
)
replace_once(
    'backend/outbound_flow.py',
    '        stack_code = item.stackCode.strip().upper()\n        if multi_source and not stack_code:\n            raise HTTPException(status_code=400, detail=f"Pilih tumpukan asal untuk setiap barang pada pemuatan multi-SO/multi-produk ({product.get(\'name\', \'\')})")\n        channel = normalize_channel(item.channel, normalize_channel(product.get("channel")))\n        if stack_code and stack_code not in await valid_stack_codes():\n            raise HTTPException(status_code=400, detail="Tumpukan asal tidak valid")\n        actual_location = stack_code or product.get("location", "")\n        load_items.append({"productId": item.productId, "documentNo": item_ref, "sku": product.get("sku", ""), "name": product.get("name", ""), "channel": channel, "qty": qty, "unit": product.get("unit", ""), "weight": weight, "measureUnit": product.get("measureUnit", "kg") or "kg", "berat": weight * qty, "secondary": product.get("secondary", ""), "secondaryQty": float(product.get("secondaryQty", 0) or 0), "location": product.get("location", ""), "stackCode": stack_code, "crewGroup": _crew_group(actual_location), "loadingFee": _loading_fee(product, qty, charge_mode_override=body.loadingFeeChargeMode)})\n',
    '        stack_code = item.stackCode.strip().upper()\n        if body.kondisi == "BAIK" and not stack_code:\n            raise HTTPException(status_code=400, detail=f"Pilih tumpukan asal untuk {product.get(\'name\', \'\')} agar kontrol FEFO dan lokasi pemuatan tercatat")\n        channel = normalize_channel(item.channel, normalize_channel(product.get("channel")))\n        if stack_code and stack_code not in await valid_stack_codes():\n            raise HTTPException(status_code=400, detail="Tumpukan asal tidak valid")\n        guide = {}\n        selection_status = "NOT_APPLICABLE"\n        exception_reason = item.fefoExceptionReason.strip()\n        if body.kondisi == "BAIK":\n            if item.productId not in fefo_guides:\n                fefo_guides[item.productId] = await get_fefo_pick_guide(item.productId)\n            guide = fefo_guides[item.productId]\n            is_exception = selection_requires_reason(guide, stack_code)\n            if is_exception and not exception_reason:\n                priorities = ", ".join(guide.get("recommendedStacks", [])) or "-"\n                raise HTTPException(status_code=400, detail=f"Tumpukan {stack_code} bukan prioritas {guide.get(\'mode\', \'FEFO\')} untuk {product.get(\'name\', \'\')}. Prioritas: {priorities}. Isi alasan pengecualian.")\n            selection_status = "EXCEPTION" if is_exception else ("PRIORITY" if stack_code in guide.get("recommendedStacks", []) else "NO_GUIDE")\n        actual_location = stack_code or product.get("location", "")\n        load_items.append({"productId": item.productId, "documentNo": item_ref, "sku": product.get("sku", ""), "name": product.get("name", ""), "channel": channel, "qty": qty, "unit": product.get("unit", ""), "weight": weight, "measureUnit": product.get("measureUnit", "kg") or "kg", "berat": weight * qty, "secondary": product.get("secondary", ""), "secondaryQty": float(product.get("secondaryQty", 0) or 0), "location": product.get("location", ""), "stackCode": stack_code, "crewGroup": _crew_group(actual_location), "loadingFee": _loading_fee(product, qty, charge_mode_override=body.loadingFeeChargeMode), "fefoPolicy": guide.get("policy", "") if guide else "", "fefoMode": guide.get("mode", "") if guide else "", "fefoRecommendedStacks": guide.get("recommendedStacks", []) if guide else [], "fefoSelectionStatus": selection_status, "fefoExceptionReason": exception_reason if selection_status == "EXCEPTION" else ""})\n',
)
replace_once(
    'backend/outbound_flow.py',
    '    revised_items = []\n    for index, submitted in enumerate(body.items):\n',
    '    revised_items = []\n    edit_fefo_guides = {}\n    for index, submitted in enumerate(body.items):\n',
)
replace_once(
    'backend/outbound_flow.py',
    '        stack_code = str(submitted.stackCode or previous.get("stackCode") or "").strip().upper()\n        if stack_code:\n            allocation = await db.stack_allocations.find_one({"productId": submitted.productId, "stackCode": stack_code}, {"_id": 0, "primaryQty": 1})\n            if not allocation or float(allocation.get("primaryQty", 0) or 0) + 1e-9 < qty:\n                raise HTTPException(status_code=400, detail=f"Stok {product.get(\'name\', \'\')} pada {stack_code} tidak mencukupi")\n        channel = normalize_channel(submitted.channel, normalize_channel(product.get("channel")))\n        revised_items.append({**previous, "documentNo": document_no, "qty": qty, "channel": channel, "berat": float(product.get("weight", 0) or 0) * qty, "loadingFee": _loading_fee(product, qty, charge_mode_override=(previous.get("loadingFee") or {}).get("mode", "")), "stackCode": stack_code, "crewGroup": _crew_group(stack_code or product.get("location", ""))})\n',
    '        stack_code = str(submitted.stackCode or previous.get("stackCode") or "").strip().upper()\n        if load.get("kondisi", "BAIK") == "BAIK" and not stack_code:\n            raise HTTPException(status_code=400, detail=f"Pilih tumpukan asal untuk {product.get(\'name\', \'\')} agar kontrol FEFO tetap tercatat")\n        if stack_code:\n            allocation = await db.stack_allocations.find_one({"productId": submitted.productId, "stackCode": stack_code}, {"_id": 0, "primaryQty": 1})\n            if not allocation or float(allocation.get("primaryQty", 0) or 0) + 1e-9 < qty:\n                raise HTTPException(status_code=400, detail=f"Stok {product.get(\'name\', \'\')} pada {stack_code} tidak mencukupi")\n        exception_reason = submitted.fefoExceptionReason.strip() or str(previous.get("fefoExceptionReason") or "").strip()\n        guide = {}\n        selection_status = previous.get("fefoSelectionStatus", "NOT_APPLICABLE")\n        if load.get("kondisi", "BAIK") == "BAIK":\n            if submitted.productId not in edit_fefo_guides:\n                edit_fefo_guides[submitted.productId] = await get_fefo_pick_guide(submitted.productId)\n            guide = edit_fefo_guides[submitted.productId]\n            is_exception = selection_requires_reason(guide, stack_code)\n            if is_exception and not exception_reason:\n                raise HTTPException(status_code=400, detail=f"Tumpukan {stack_code} bukan prioritas FEFO. Isi alasan pengecualian sebelum menyimpan edit.")\n            selection_status = "EXCEPTION" if is_exception else ("PRIORITY" if stack_code in guide.get("recommendedStacks", []) else "NO_GUIDE")\n        channel = normalize_channel(submitted.channel, normalize_channel(product.get("channel")))\n        revised_items.append({**previous, "documentNo": document_no, "qty": qty, "channel": channel, "berat": float(product.get("weight", 0) or 0) * qty, "loadingFee": _loading_fee(product, qty, charge_mode_override=(previous.get("loadingFee") or {}).get("mode", "")), "stackCode": stack_code, "crewGroup": _crew_group(stack_code or product.get("location", "")), "fefoPolicy": guide.get("policy", previous.get("fefoPolicy", "")) if guide else previous.get("fefoPolicy", ""), "fefoMode": guide.get("mode", previous.get("fefoMode", "")) if guide else previous.get("fefoMode", ""), "fefoRecommendedStacks": guide.get("recommendedStacks", previous.get("fefoRecommendedStacks", [])) if guide else previous.get("fefoRecommendedStacks", []), "fefoSelectionStatus": selection_status, "fefoExceptionReason": exception_reason if selection_status == "EXCEPTION" else ""})\n',
)
replace_once(
    'backend/outbound_flow.py',
    '                "consignment_zone": load.get("consignment_zone", ""),\n            })\n',
    '                "consignment_zone": load.get("consignment_zone", ""),\n                "fefo_policy": item.get("fefoPolicy", ""),\n                "fefo_mode": item.get("fefoMode", ""),\n                "fefo_selection_status": item.get("fefoSelectionStatus", ""),\n                "fefo_exception_reason": item.get("fefoExceptionReason", ""),\n            })\n',
)

# --- app route ---
replace_once(
    'app.py',
    'from backend.fefo_flow import router as fefo_flow_router\n',
    'from backend.fefo_flow import router as fefo_flow_router\nfrom backend.fefo_selection import router as fefo_selection_router\n',
)
replace_once(
    'app.py',
    'app.include_router(stack_lots_router)\n',
    'app.include_router(stack_lots_router)\napp.include_router(fefo_selection_router)\n',
)

# --- frontend FEFO controls ---
replace_once(
    'frontend/src/pages/CatatStok.jsx',
    "import { downloadApiFile } from '../lib/api';\n",
    "import api, { downloadApiFile } from '../lib/api';\n",
)
replace_once(
    'frontend/src/pages/CatatStok.jsx',
    "const emptyRow = () => ({ productId: '', inputMode: 'QTY', inputValue: 1, qty: 1, goodQty: 1, damagedQty: 0, exp: '', stackCode: '', documentNo: '', channel: '' });\n",
    "const emptyRow = () => ({ productId: '', inputMode: 'QTY', inputValue: 1, qty: 1, goodQty: 1, damagedQty: 0, exp: '', stackCode: '', documentNo: '', channel: '', fefoExceptionReason: '' });\n",
)
replace_once(
    'frontend/src/pages/CatatStok.jsx',
    "  const [feeChargeMode, setFeeChargeMode] = useState('PENGAMBIL');\n",
    "  const [feeChargeMode, setFeeChargeMode] = useState('PENGAMBIL');\n  const [fefoGuides, setFefoGuides] = useState({});\n",
)
replace_once(
    'frontend/src/pages/CatatStok.jsx',
    "  const selectedPO = purchaseOrders.find((po) => po.id === poId);\n\n  const resetForm",
    "  const selectedPO = purchaseOrders.find((po) => po.id === poId);\n  const selectedOutboundProductIds = useMemo(() => type === 'KELUAR' && kondisi === 'BAIK' ? [...new Set(rows.map((row) => row.productId).filter(Boolean))] : [], [rows, type, kondisi]);\n\n  useEffect(() => {\n    if (!selectedOutboundProductIds.length) return;\n    const missing = selectedOutboundProductIds.filter((id) => !fefoGuides[id]);\n    if (!missing.length) return;\n    let cancelled = false;\n    Promise.all(missing.map(async (id) => {\n      try { const response = await api.get(`/fefo-pick-guide/${id}`); return [id, response.data]; }\n      catch { return [id, null]; }\n    })).then((entries) => {\n      if (cancelled) return;\n      const resolved = Object.fromEntries(entries.filter(([, guide]) => guide));\n      if (Object.keys(resolved).length) setFefoGuides((prev) => ({ ...prev, ...resolved }));\n    });\n    return () => { cancelled = true; };\n  }, [selectedOutboundProductIds, fefoGuides]);\n\n  useEffect(() => {\n    if (type !== 'KELUAR' || kondisi !== 'BAIK') return;\n    setRows((prev) => {\n      let changed = false;\n      const next = prev.map((row) => {\n        if (!row.productId || row.stackCode) return row;\n        const recommended = fefoGuides[row.productId]?.recommendedStacks || [];\n        if (recommended.length !== 1) return row;\n        changed = true;\n        return { ...row, stackCode: recommended[0], fefoExceptionReason: '' };\n      });\n      return changed ? next : prev;\n    });\n  }, [type, kondisi, fefoGuides]);\n\n  const resetForm",
)
replace_once(
    'frontend/src/pages/CatatStok.jsx',
    "  const availableStacksFor = (productId) => (stackAllocations || [])\n    .filter((allocation) => allocation.productId === productId && Number(allocation.primaryQty || 0) > 0)\n    .sort((a, b) => String(a.stackCode || '').localeCompare(String(b.stackCode || '')));\n",
    "  const fefoGuideFor = (productId) => fefoGuides[productId] || null;\n  const fefoStackMeta = (productId, stackCode) => (fefoGuideFor(productId)?.stacks || []).find((item) => item.stackCode === stackCode);\n  const isFefoException = (row) => {\n    const guide = fefoGuideFor(row.productId);\n    return Boolean(type === 'KELUAR' && kondisi === 'BAIK' && row.stackCode && guide?.recommendedStacks?.length && !guide.recommendedStacks.includes(row.stackCode));\n  };\n  const availableStacksFor = (productId) => {\n    const guide = fefoGuideFor(productId);\n    const priorities = new Map((guide?.recommendedStacks || []).map((code, index) => [code, index]));\n    const meta = new Map((guide?.stacks || []).map((item) => [item.stackCode, item]));\n    return (stackAllocations || [])\n      .filter((allocation) => allocation.productId === productId && Number(allocation.primaryQty || 0) > 0)\n      .sort((a, b) => {\n        const ac = String(a.stackCode || ''); const bc = String(b.stackCode || '');\n        const ap = priorities.has(ac) ? priorities.get(ac) : 9999; const bp = priorities.has(bc) ? priorities.get(bc) : 9999;\n        if (ap !== bp) return ap - bp;\n        const ae = meta.get(ac)?.nextLot?.exp || '9999-12-31'; const be = meta.get(bc)?.nextLot?.exp || '9999-12-31';\n        return ae.localeCompare(be) || ac.localeCompare(bc);\n      });\n  };\n",
)
replace_once(
    'frontend/src/pages/CatatStok.jsx',
    "    if (type === 'KELUAR' && kondisi === 'BAIK' && (chosen.length > 1 || isMultiDocumentOutbound) && chosen.some((row) => !row.stackCode)) {\n      toast.error('Pilih tumpukan asal pada setiap barang untuk pemuatan multi-SO/multi-produk');\n      return;\n    }\n",
    "    if (type === 'KELUAR' && kondisi === 'BAIK' && chosen.some((row) => !row.stackCode)) {\n      toast.error('Pilih tumpukan asal pada setiap barang agar lokasi pemuatan dan kontrol FEFO tercatat');\n      return;\n    }\n    if (type === 'KELUAR' && kondisi === 'BAIK') {\n      const withoutReason = chosen.filter((row) => isFefoException(row) && !String(row.fefoExceptionReason || '').trim());\n      if (withoutReason.length) {\n        toast.error(`Isi alasan pengecualian FEFO untuk ${withoutReason[0].product.name}`);\n        return;\n      }\n    }\n",
)
replace_once(
    'frontend/src/pages/CatatStok.jsx',
    "          items: chosen.map((row) => ({ productId: row.productId, qty: Number(row.qty), documentNo: row.documentNo || documentRefs[0], stackCode: kondisi === 'RUSAK' ? '' : (row.stackCode || ''), channel: row.channel || row.product.channel || 'KOM' })),\n",
    "          items: chosen.map((row) => ({ productId: row.productId, qty: Number(row.qty), documentNo: row.documentNo || documentRefs[0], stackCode: kondisi === 'RUSAK' ? '' : (row.stackCode || ''), channel: row.channel || row.product.channel || 'KOM', fefoExceptionReason: kondisi === 'BAIK' ? String(row.fefoExceptionReason || '').trim() : '' })),\n",
)
replace_once(
    'frontend/src/pages/CatatStok.jsx',
    "onChange={(e) => { const chosenProduct = products.find((item) => item.id === e.target.value); setTransactionInput(index, { productId: e.target.value, inputMode: 'QTY', inputValue: 1, stackCode: '', channel: chosenProduct?.channel || 'KOM' }); }}",
    "onChange={(e) => { const chosenProduct = products.find((item) => item.id === e.target.value); setTransactionInput(index, { productId: e.target.value, inputMode: 'QTY', inputValue: 1, stackCode: '', channel: chosenProduct?.channel || 'KOM', fefoExceptionReason: '' }); }}",
)
old_stack = '''<><select value={row.stackCode || ''} onChange={(e) => setRow(index, { stackCode: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2.5 text-xs"><option value="">{isMultiDocumentOutbound || rows.length > 1 ? "Pilih tumpukan asal (wajib)" : "Otomatis (pilih dari stok tersedia)"}</option>{availableStacks.map((allocation) => { const secondaryQty = Number(allocation.secondaryQty || 0); const qty = Number(allocation.primaryQty || 0); const secondary = secondaryQty > 0 ? Math.floor(qty / secondaryQty) : 0; const remainder = secondaryQty > 0 ? qty - (secondary * secondaryQty) : 0; const packaging = secondaryQty > 0 ? ` · ${formatNum(secondary)} ${allocation.secondary || 'sekunder'}${remainder > 0 ? ` + ${formatNum(remainder)} ${allocation.unit || 'pcs'}` : ''}` : ''; return <option key={allocation.id} value={allocation.stackCode}>{allocation.stackCode} — sisa {formatNum(qty)} {allocation.unit || 'pcs'}{packaging}</option>; })}</select>{row.productId && availableStacks.length === 0 && <p className="text-[9px] text-[#fbbf24] mt-1">Belum ada alokasi tumpukan untuk produk ini; sistem akan menentukan otomatis.</p>}</>'''
new_stack = '''<><select value={row.stackCode || ''} onChange={(e) => { const stackCode = e.target.value; const guide = fefoGuideFor(row.productId); setRow(index, { stackCode, fefoExceptionReason: guide?.recommendedStacks?.includes(stackCode) ? '' : row.fefoExceptionReason }); }} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2.5 text-xs"><option value="">Pilih tumpukan asal (wajib)</option>{availableStacks.map((allocation) => { const secondaryQty = Number(allocation.secondaryQty || 0); const qty = Number(allocation.primaryQty || 0); const secondary = secondaryQty > 0 ? Math.floor(qty / secondaryQty) : 0; const remainder = secondaryQty > 0 ? qty - (secondary * secondaryQty) : 0; const packaging = secondaryQty > 0 ? ` · ${formatNum(secondary)} ${allocation.secondary || 'sekunder'}${remainder > 0 ? ` + ${formatNum(remainder)} ${allocation.unit || 'pcs'}` : ''}` : ''; const guide = fefoGuideFor(row.productId); const meta = fefoStackMeta(row.productId, allocation.stackCode); const priority = guide?.recommendedStacks?.includes(allocation.stackCode); const marker = priority ? (guide?.mode === 'FEFO_TRACKED' ? '★ FEFO' : '★ PRIORITAS') : (meta?.untrackedQty > 0 ? 'LEGACY' : (meta?.nextLot?.exp ? `EXP ${meta.nextLot.exp}` : '')); return <option key={allocation.id} value={allocation.stackCode}>{marker ? `${marker} · ` : ''}{allocation.stackCode} — sisa {formatNum(qty)} {allocation.unit || 'pcs'}{packaging}</option>; })}</select>{row.productId && fefoGuideFor(row.productId) && <div className={`mt-1 rounded border px-2 py-1.5 text-[9px] ${fefoGuideFor(row.productId).mode === 'FEFO_TRACKED' ? 'border-[#14532d] text-[#86efac]' : 'border-[#78350f] text-[#fcd34d]'}`}><b>{fefoGuideFor(row.productId).mode}</b> · Prioritas: {(fefoGuideFor(row.productId).recommendedStacks || []).join(', ') || 'periksa integritas'}<br/>{fefoGuideFor(row.productId).reason}</div>}{isFefoException(row) && <div className="mt-1"><label className="text-[9px] text-[#fbbf24] block mb-1">Alasan memilih di luar prioritas FEFO *</label><input value={row.fefoExceptionReason || ''} onChange={(e) => setRow(index, { fefoExceptionReason: e.target.value })} placeholder="Contoh: akses tumpukan tertutup / dokumen mensyaratkan batch tertentu" className="w-full bg-[#160f05] border border-[#78350f] rounded px-2 py-1.5 text-[10px] text-[#fde68a]" /></div>}{row.productId && availableStacks.length === 0 && <p className="text-[9px] text-[#fbbf24] mt-1">Belum ada alokasi tumpukan untuk produk ini.</p>}</>'''
replace_once('frontend/src/pages/CatatStok.jsx', old_stack, new_stack)

# --- tests ---
replace_once(
    'backend/tests/test_subledgers.py',
    'from backend.opname_reconcile_guard import aggregate_lot_reconcile_input\n',
    'from backend.opname_reconcile_guard import aggregate_lot_reconcile_input\nfrom backend.fefo_selection import build_fefo_pick_guide, selection_requires_reason\n',
)
append = '''\n\ndef test_fefo_pick_guide_prefers_legacy_stacks_before_named_lots():\n    allocations = [\n        {"stackCode": "18/A01", "primaryQty": 40, "unit": "Pack"},\n        {"stackCode": "18/A02", "primaryQty": 60, "unit": "Pack"},\n    ]\n    lots = [\n        {"id": "lot1", "stackCode": "18/A02", "remainingQty": 60, "exp": "2026-10-01", "receivedAt": "2026-09-01"},\n    ]\n    guide = build_fefo_pick_guide("p1", allocations, lots)\n    assert guide["mode"] == "LEGACY_FIRST"\n    assert guide["recommendedStacks"] == ["18/A01"]\n    assert selection_requires_reason(guide, "18/A02") is True\n    assert selection_requires_reason(guide, "18/A01") is False\n\n\ndef test_fefo_pick_guide_uses_earliest_expiry_when_coverage_complete():\n    allocations = [\n        {"stackCode": "18/A01", "primaryQty": 20, "unit": "Pack"},\n        {"stackCode": "18/A02", "primaryQty": 20, "unit": "Pack"},\n    ]\n    lots = [\n        {"id": "later", "stackCode": "18/A01", "remainingQty": 20, "exp": "2026-12-01", "receivedAt": "2026-09-01"},\n        {"id": "early", "stackCode": "18/A02", "remainingQty": 20, "exp": "2026-10-01", "receivedAt": "2026-09-02"},\n    ]\n    guide = build_fefo_pick_guide("p1", allocations, lots)\n    assert guide["mode"] == "FEFO_TRACKED"\n    assert guide["recommendedStacks"] == ["18/A02"]\n    assert selection_requires_reason(guide, "18/A01") is True\n\n\ndef test_fefo_pick_guide_route_registered():\n    assert _first_endpoint("/api/fefo-pick-guide/{product_id}", "GET").__name__ == "fefo_pick_guide"\n'''
p = ROOT / 'backend/tests/test_subledgers.py'
p.write_text(p.read_text(encoding='utf-8') + append, encoding='utf-8')

print('FEFO pick-control patch applied')
