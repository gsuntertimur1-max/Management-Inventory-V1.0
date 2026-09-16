from contextlib import asynccontextmanager
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.server import app
from backend.inventory_flow import router as inventory_flow_router
from backend.master_products import router as master_products_router
from backend.outbound_flow import router as outbound_flow_router
from backend.consignment import router as consignment_router
from backend.stack_allocations import router as stack_allocations_router
from backend.pdf_documents import router as pdf_documents_router
from backend.queue_flow import router as queue_flow_router
from backend.runtime_hardening import ensure_performance_indexes, hardening_middleware
from backend.operational_guards import router as operational_guards_router, ensure_operational_guard_indexes
from backend.operational_corrections import router as operational_corrections_router
from backend.integrity_control import router as integrity_control_router

# Koreksi penerimaan mendaftarkan pembungkus /api/receipts lebih dulu agar
# metadata tumpukan/area rusak tersimpan sebelum route operasional lama.
app.include_router(operational_corrections_router)
# Guard routes must be registered before the original operational routers so
# the same public paths are serialized across Railway workers.
app.include_router(operational_guards_router)
app.include_router(inventory_flow_router)
app.include_router(master_products_router)
app.include_router(outbound_flow_router)
app.include_router(consignment_router)
app.include_router(stack_allocations_router)
app.include_router(pdf_documents_router)
app.include_router(queue_flow_router)
app.include_router(integrity_control_router)

_original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def hardened_lifespan(application):
    async with _original_lifespan(application):
        await ensure_performance_indexes()
        await ensure_operational_guard_indexes()
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
