from contextlib import asynccontextmanager
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.server import app
import backend.role_four_config  # noqa: F401 - consolidates legacy roles into four warehouse roles
from backend.inventory_flow import router as inventory_flow_router
from backend.master_products import router as master_products_router
from backend.outbound_flow import router as outbound_flow_router
from backend.outbound_reservation_view import router as outbound_reservation_view_router
from backend.outbound_start_guard import router as outbound_start_guard_router
from backend.reservation_mutation_guards import router as reservation_mutation_guards_router
from backend.supplier_lifecycle_guards import router as supplier_lifecycle_guards_router
from backend.document_settlement_guards import router as document_settlement_guards_router
from backend.return_lot_reconciliation import router as return_lot_reconciliation_router
from backend.outbound_completion_hardening import router as outbound_completion_hardening_router
from backend.consignment import router as consignment_router
from backend.stack_allocations import router as stack_allocations_router
from backend.outbound_pdf_multi import router as outbound_pdf_multi_router
from backend.pdf_documents import router as pdf_documents_router
from backend.queue_flow import router as queue_flow_router
from backend.runtime_hardening import ensure_performance_indexes, hardening_middleware
from backend.operational_guards import router as operational_guards_router, ensure_operational_guard_indexes
from backend.operational_corrections import router as operational_corrections_router
from backend.qc_receipt_guard import router as qc_receipt_guard_router
from backend.integrity_control import router as integrity_control_router
from backend.integrity_lots import router as integrity_lots_router
from backend.integrity_postcommit import router as integrity_postcommit_router
from backend.integrity_documents import router as integrity_documents_router
from backend.stock_opname import router as stock_opname_router
from backend.opname_lots import router as opname_lots_router
from backend.opname_lots_conservative import router as opname_lots_conservative_router
from backend.opname_reconcile_guard import router as opname_reconcile_guard_router
from backend.stack_lots import router as stack_lots_router, ensure_stack_lot_indexes
from backend.fefo_flow import router as fefo_flow_router
from backend.fefo_selection import router as fefo_selection_router
from backend.lot_corrections import router as lot_corrections_router
from backend.damaged_stock_area import router as damaged_stock_area_router
from backend.damaged_outbound import router as damaged_outbound_router
import backend.opname_lot_atomic  # noqa: F401 - installs compensated lot reducer for opname engines

# QC state is authoritative for explicit QC-linked receipts. PENDING/REJECTED must
# stop before any stock mutation; approved receipts delegate to the hardened receipt path.
app.include_router(qc_receipt_guard_router)
# Lot-aware wrappers must precede the generic correction/guard routes.
app.include_router(lot_corrections_router)
# Koreksi penerimaan mendaftarkan pembungkus /api/receipts lebih dulu agar
# metadata tumpukan/area rusak dan lot penerimaan tersimpan.
app.include_router(operational_corrections_router)
# Hardened completion owns the public completion path. Core stock completion stays authoritative;
# post-commit metadata/SJ/FEFO enrichment is repairable and cannot create a false failure response.
app.include_router(outbound_completion_hardening_router)
# Legacy FEFO wrapper remains behind the hardened route for compatibility only.
app.include_router(fefo_flow_router)
# Manual lot reconciliation is normalized first so one lot is mutated only once per request.
app.include_router(opname_reconcile_guard_router)
# Conservative approval/sync protects identified lots while legacy stock is still mixed in a stack.
app.include_router(opname_lots_conservative_router)
# Legacy lot-aware opname routes remain available behind the conservative wrappers.
app.include_router(opname_lots_router)
# Damaged outbound has a dedicated physical source and R-series queue; good stock delegates to normal guard.
app.include_router(damaged_outbound_router)
# Revalidate stack/master reservations immediately before Menunggu -> Sedang Dimuat.
# It must precede the generic outbound router because both expose the same public path.
app.include_router(outbound_start_guard_router)
# Any mutation that can reduce stock while an outbound queue is active must validate reservations
# inside the same product lock before delegating to the core inventory operation.
app.include_router(reservation_mutation_guards_router)
# Supplier replacement must be serialized per return + product and retry-safe before the raw inventory route.
app.include_router(supplier_lifecycle_guards_router)
# Return/CR/SO settlement mutations are serialized per source load and document number.
# This must precede generic operational guards and outbound routes exposing the same paths.
app.include_router(document_settlement_guards_router)
# Return stock with later-verified batch/expiry can be reconciled into FEFO lots without touching physical stock.
app.include_router(return_lot_reconciliation_router)
# Guard routes must be registered before the original operational routers so
# the same public paths are serialized across Railway workers. The core outbound flow
# performs the per-stack reservation check while these guards serialize product writes.
app.include_router(operational_guards_router)
app.include_router(inventory_flow_router)
app.include_router(master_products_router)
app.include_router(outbound_flow_router)
app.include_router(consignment_router)
app.include_router(stack_allocations_router)
# Multi-document Bon Muat/Surat Jalan owns these export paths and must precede legacy PDF routes.
app.include_router(outbound_pdf_multi_router)
app.include_router(pdf_documents_router)
app.include_router(queue_flow_router)
# Authoritative outbound reservation view is available to authenticated operators.
app.include_router(outbound_reservation_view_router)
# Outbound document wrapper is the authoritative /integrity-control route: it layers
# Bon Muat/SJ/transaction cross-checks over post-commit + lot/document checks.
app.include_router(integrity_documents_router)
app.include_router(integrity_postcommit_router)
app.include_router(integrity_lots_router)
app.include_router(integrity_control_router)
app.include_router(stock_opname_router)
app.include_router(stack_lots_router)
app.include_router(fefo_selection_router)
app.include_router(damaged_stock_area_router)

_original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def hardened_lifespan(application):
    async with _original_lifespan(application):
        await ensure_performance_indexes()
        await ensure_operational_guard_indexes()
        await ensure_stack_lot_indexes()
        yield


app.router.lifespan_context = hardened_lifespan
app.middleware("http")(hardening_middleware)

ROOT_DIR = Path(__file__).resolve().parent
BUILD_DIR = ROOT_DIR / "frontend" / "build"
STATIC_DIR = BUILD_DIR / "static"

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    """Serve React build files and fall back to index.html for SPA routes."""
    build_root = BUILD_DIR.resolve()
    requested = (BUILD_DIR / full_path).resolve()

    try:
        requested.relative_to(build_root)
    except ValueError:
        requested = BUILD_DIR / "index.html"

    if full_path and requested.is_file():
        return FileResponse(requested)

    return FileResponse(BUILD_DIR / "index.html")