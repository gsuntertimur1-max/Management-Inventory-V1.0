"""Warehouse locations (kompleks → unit gudang → tumpukan) and stock placements.

Kode tumpukan gabungan memakai format "GBB 23/A01.1.1".
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


COMPLEX_I = "Gudang Sunter Timur I"
COMPLEX_II = "Gudang Sunter Timur II"


def _gbb_stacks() -> List[str]:
    """12 tumpukan per unit GBB: A/B/C × 01..04, pola nomor .1.1."""
    return [f"{letter}{n:02d}.1.1" for letter in ("A", "B", "C") for n in (1, 2, 3, 4)]


def _mp_stacks() -> List[str]:
    """16 tumpukan di MP 1: A/B × 01..08, pola nomor .1.1."""
    return [f"{letter}{n:02d}.1.1" for letter in ("A", "B") for n in range(1, 9)]


# unit gudang -> (kompleks, daftar tumpukan)
WAREHOUSE_UNITS = [
    ("GBB 17", COMPLEX_I, _gbb_stacks()),
    ("GBB 18", COMPLEX_I, _gbb_stacks()),
    ("GBB 19", COMPLEX_I, _gbb_stacks()),
    ("GBB 20", COMPLEX_I, _gbb_stacks()),
    ("GBB 21", COMPLEX_II, _gbb_stacks()),
    ("GBB 22", COMPLEX_II, _gbb_stacks()),
    ("GBB 23", COMPLEX_II, _gbb_stacks()),
    ("GBB 24", COMPLEX_II, _gbb_stacks()),
    ("MP 1", COMPLEX_II, _mp_stacks()),
]


class LocationCreate(BaseModel):
    complex_name: str
    unit_name: str
    stack: str


class Location(LocationCreate):
    id: str = Field(default_factory=_uid)
    code: str = ""
    created_at: datetime = Field(default_factory=_now)


class PlacementCreate(BaseModel):
    location_code: str
    product_id: str
    length: int = Field(default=1, ge=1)   # P — panjang tumpukan (kemasan)
    width: int = Field(default=1, ge=1)    # L — lebar tumpukan
    height: int = Field(default=1, ge=1)   # T — tinggi tumpukan
    notes: str = ""


class Placement(PlacementCreate):
    id: str = Field(default_factory=_uid)
    complex_name: str = ""
    unit_name: str = ""
    stack: str = ""
    product_name: str = ""
    product_sku: str = ""
    unit: str = "Pcs"
    secondary_unit: str = "Karung"
    units_per_secondary: int = 1
    weight_per_unit: float = 1
    weight_unit: str = "Kg"
    secondary_count: int = 0     # P × L × T
    weight_per_secondary: float = 0
    total_units: int = 0         # satuan primer
    total_weight: float = 0      # berat total tumpukan
    created_by_name: str = ""
    created_at: datetime = Field(default_factory=_now)


class LocationStackSummary(BaseModel):
    code: str
    complex_name: str
    unit_name: str
    stack: str
    product_count: int
    total_secondary: int
    total_weight: float


class DistributeResult(BaseModel):
    ok: bool
    placements: int
    products: int
    total_weight: float
    skipped: List[str] = []


class PlacementDelete(BaseModel):
    ok: bool
    id: Optional[str] = None
