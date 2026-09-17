import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

from app import app
from backend.integrity_documents import analyze_outbound_document_integrity


def _first_endpoint(path: str, method: str):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    return None


def test_document_integrity_wrapper_is_authoritative_route():
    endpoint = _first_endpoint("/api/integrity-control", "GET")
    assert endpoint is not None
    assert endpoint.__module__ == "backend.integrity_documents"


def test_document_integrity_accepts_consistent_completed_load():
    loads = [{
        "id": "L1", "status": "Selesai", "bon_no": "BM/2026/09/001", "antrian": "18-001",
        "surat_jalan_id": "SJ1", "items": [{"productId": "P1", "stackCode": "18/A01", "qty": 10}],
    }]
    sj = [{"id": "SJ1", "load_id": "L1", "no": "SJ-202609-001", "bon_no": "BM/2026/09/001", "antrian": "18-001"}]
    tx = [{"id": "T1", "load_id": "L1", "type": "KELUAR", "product_id": "P1", "stackCode": "18/A01", "change": -10, "bon_no": "BM/2026/09/001"}]
    assert analyze_outbound_document_integrity(loads, sj, tx) == []


def test_document_integrity_flags_duplicate_sj_wrong_link_and_qty_mismatch():
    loads = [
        {"id": "L1", "status": "Selesai", "bon_no": "BM-001", "antrian": "18-001", "surat_jalan_id": "SJ2", "items": [{"productId": "P1", "stackCode": "18/A01", "qty": 10}]},
        {"id": "L2", "status": "Menunggu", "bon_no": "BM-002", "antrian": "18-002", "items": []},
    ]
    sj = [
        {"id": "SJ1", "load_id": "L1", "no": "SJ-1", "bon_no": "BM-001", "antrian": "18-001"},
        {"id": "SJX", "load_id": "L1", "no": "SJ-X", "bon_no": "BM-001", "antrian": "18-001"},
        {"id": "SJ2", "load_id": "L2", "no": "SJ-2", "bon_no": "BM-002", "antrian": "18-002"},
    ]
    tx = [{"id": "T1", "load_id": "L1", "type": "KELUAR", "product_id": "P1", "stackCode": "18/A01", "change": -8, "bon_no": "BM-001"}]
    codes = {row["code"] for row in analyze_outbound_document_integrity(loads, sj, tx)}
    assert "DUPLICATE_SURAT_JALAN_PER_LOAD" in codes
    assert "SURAT_JALAN_WRONG_LOAD_LINK" in codes
    assert "SURAT_JALAN_LOAD_NOT_COMPLETED" in codes
    assert "OUTBOUND_TRANSACTION_QTY_MISMATCH" in codes


def test_document_integrity_flags_duplicate_bon_and_missing_transaction():
    loads = [
        {"id": "L1", "status": "Selesai", "bon_no": "BM-001", "antrian": "18-001", "items": []},
        {"id": "L2", "status": "Selesai", "bon_no": "BM-001", "antrian": "18-002", "items": []},
    ]
    codes = [row["code"] for row in analyze_outbound_document_integrity(loads, [], [])]
    assert "DUPLICATE_BON_MUAT" in codes
    assert codes.count("COMPLETED_OUTBOUND_MISSING_TRANSACTION") == 2
