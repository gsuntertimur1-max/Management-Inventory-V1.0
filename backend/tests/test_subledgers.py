import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

from fastapi import HTTPException

from app import app
from backend.integrity_lots import apply_lot_integrity
from backend.damaged_stock_area import damaged_movement_qty
from backend.damaged_outbound import DAMAGED_AREA, DAMAGED_QUEUE_PREFIX, damaged_loading_context
from backend.fefo_conservative import conservative_outbound_split
from backend.opname_lots import LotReconcileInput
from backend.opname_lots_conservative import conservative_shortage_split
from backend.opname_reconcile_guard import aggregate_lot_reconcile_input


def _first_endpoint(path: str, method: str):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    return None


def test_lot_integrity_wrapper_is_first_route():
    assert _first_endpoint("/api/integrity-control", "GET").__name__ == "integrity_control"


def test_stock_opname_lot_wrapper_is_first_approval_route():
    assert _first_endpoint("/api/stock-opnames/{opname_id}/approve", "POST").__name__ == "approve_stock_opname_conservative"
    assert _first_endpoint("/api/stock-opnames/{opname_id}/sync-lots", "POST").__name__ == "repair_stock_opname_lots_conservative"
    assert _first_endpoint("/api/stock-opnames/{opname_id}/reconcile-lots", "POST").__name__ == "guarded_reconcile_stock_opname_lots"


def test_conservative_outbound_uses_legacy_before_named_lot():
    untracked, tracked = conservative_outbound_split(physical_before=100, tracked_before=60, requested=10)
    assert untracked == 10
    assert tracked == 0

    untracked, tracked = conservative_outbound_split(physical_before=100, tracked_before=60, requested=50)
    assert untracked == 40
    assert tracked == 10


def test_conservative_opname_shortage_protects_named_lot_until_required():
    # Setelah opname: fisik 90, lot bernama 60. Selisih 10 masih sepenuhnya legacy.
    untracked, tracked = conservative_shortage_split(current_stack_qty=90, tracked_qty=60, needed=10)
    assert untracked == 10
    assert tracked == 0

    # Setelah opname: fisik 50, lot bernama masih 60. Hanya 10 yang wajib mengenai lot.
    untracked, tracked = conservative_shortage_split(current_stack_qty=50, tracked_qty=60, needed=50)
    assert untracked == 40
    assert tracked == 10


def test_lot_reconciliation_rejects_zero_quantity():
    try:
        LotReconcileInput(items=[{"productId": "p1", "stackCode": "18/A01", "lotId": "lot1", "qty": 0}])
    except Exception:
        return
    raise AssertionError("Kuantum rekonsiliasi lot nol harus ditolak")


def test_duplicate_lot_reconciliation_rows_are_aggregated_once():
    body = LotReconcileInput(items=[
        {"productId": "p1", "stackCode": "18/a01", "lotId": "lot1", "qty": 2},
        {"productId": "p1", "stackCode": "18/A01", "lotId": "lot1", "qty": 3},
    ], note="hitung ulang fisik")
    normalized = aggregate_lot_reconcile_input(body)
    assert len(normalized.items) == 1
    assert normalized.items[0].lotId == "lot1"
    assert normalized.items[0].stackCode == "18/A01"
    assert normalized.items[0].qty == 5
    assert normalized.note == "hitung ulang fisik"


def test_duplicate_lot_cannot_cross_stack_in_one_request():
    body = LotReconcileInput(items=[
        {"productId": "p1", "stackCode": "18/A01", "lotId": "lot1", "qty": 1},
        {"productId": "p1", "stackCode": "18/A02", "lotId": "lot1", "qty": 1},
    ])
    try:
        aggregate_lot_reconcile_input(body)
    except HTTPException as exc:
        assert exc.status_code == 400
        return
    raise AssertionError("Lot yang sama pada dua tumpukan harus ditolak")


def test_damaged_stock_area_route_is_registered():
    assert _first_endpoint("/api/damaged-stock-area", "GET").__name__ == "damaged_stock_area"


def test_damaged_outbound_wrapper_is_first_create_route():
    assert _first_endpoint("/api/outbound-loads", "POST").__name__ == "guarded_create_outbound"
    assert damaged_loading_context() == (DAMAGED_AREA, DAMAGED_QUEUE_PREFIX)
    assert DAMAGED_AREA == "AREA BARANG RUSAK"
    assert DAMAGED_QUEUE_PREFIX == "R"


def test_lot_integrity_marks_legacy_coverage_as_warning():
    row = {"productId": "p1", "stackGood": 100, "unit": "Pack", "severity": "OK", "issues": []}
    result = apply_lot_integrity(row, 60)
    assert result["severity"] == "WARNING"
    assert result["lotTracked"] == 60
    assert result["lotUntracked"] == 40
    assert result["lotCoveragePct"] == 60


def test_lot_integrity_marks_overtracked_as_error():
    row = {"productId": "p1", "stackGood": 100, "unit": "Pack", "severity": "OK", "issues": []}
    result = apply_lot_integrity(row, 110)
    assert result["severity"] == "ERROR"
    assert any("lebih besar" in issue for issue in result["issues"])


def test_damaged_movement_prefers_damaged_change_and_falls_back_to_condition():
    assert damaged_movement_qty({"damaged_change": 5, "change": 99, "kondisi": "BAIK"}) == 5
    assert damaged_movement_qty({"change": -3, "kondisi": "RUSAK"}) == -3
    assert damaged_movement_qty({"change": 8, "kondisi": "BAIK"}) == 0
