import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SupplierCreate(BaseModel):
    name: str
    contact_person: str = ""
    phone: str
    email: str = ""
    address: str = ""
    category_supplied: str = ""


class Supplier(SupplierCreate):
    id: str = Field(default_factory=_uid)
    created_at: datetime = Field(default_factory=_now)


class ProductCreate(BaseModel):
    name: str
    sku: str
    category: str = "Lainnya"
    unit: str = "Pcs"
    # Packaging: 1 primary unit (unit, e.g. Pcs/Pack) weighs weight_per_unit weight_unit (Kg/Liter),
    # and units_per_secondary of them are repacked into 1 secondary_unit (Dus/Karung).
    weight_per_unit: float = 1
    weight_unit: str = "Kg"
    secondary_unit: str = "Dus"
    units_per_secondary: int = 1
    min_stock: int = 0
    purchase_price: float = 0
    selling_price: float = 0
    current_stock: int = 0
    damaged_stock: int = 0          # stok kondisi RUSAK (current_stock = kondisi BAIK)
    expiry_date: Optional[str] = None   # tanggal kedaluwarsa (EXP) format YYYY-MM-DD
    supplier_id: Optional[str] = None
    location: str = ""


class Product(ProductCreate):
    id: str = Field(default_factory=_uid)
    supplier_name: str = ""
    created_at: datetime = Field(default_factory=_now)


MovementType = Literal["MASUK", "KELUAR"]
StockCondition = Literal["BAIK", "RUSAK"]


class TransactionCreate(BaseModel):
    product_id: str
    type: MovementType
    quantity: int = Field(gt=0)
    condition: StockCondition = "BAIK"
    party: str = ""
    reference_no: str = ""
    vehicle_plate: str = ""
    notes: str = ""
    date: Optional[str] = None


class Transaction(BaseModel):
    id: str = Field(default_factory=_uid)
    product_id: str
    product_name: str
    product_sku: str
    category: str = "Lainnya"
    type: MovementType
    quantity: int
    stock_after: int
    condition: StockCondition = "BAIK"
    party: str = ""
    reference_no: str = ""
    vehicle_plate: str = ""
    queue_no: str = ""
    shipment_id: Optional[str] = None
    created_by: Optional[str] = None
    created_by_name: str = ""
    notes: str = ""
    date: str
    created_at: datetime = Field(default_factory=_now)


class CategoryStat(BaseModel):
    category: str
    units: int


class TimelinePoint(BaseModel):
    date: str
    masuk: int
    keluar: int


class Stats(BaseModel):
    total_products: int
    total_units: int
    total_damaged: int = 0
    total_valuation: float
    recent_movements: int
    by_category: List[CategoryStat]
    timeline: List[TimelinePoint]
