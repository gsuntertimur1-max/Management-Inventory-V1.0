from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.server import app

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
