import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


POStatus = Literal["MENUNGGU", "DITERIMA", "DIBATALKAN"]


class POItemInput(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)
    unit_price: float = 0


class POItem(BaseModel):
    product_id: str
    product_name: str
    product_sku: str
    unit: str = "Pcs"
    quantity: int
    unit_price: float = 0
    subtotal: float = 0


class PurchaseOrderCreate(BaseModel):
    supplier_id: str
    items: List[POItemInput]
    notes: str = ""
    expected_date: Optional[str] = None


class PurchaseOrder(BaseModel):
    id: str = Field(default_factory=_uid)
    po_number: str
    supplier_id: str
    supplier_name: str = ""
    status: POStatus = "MENUNGGU"
    items: List[POItem] = []
    total: float = 0
    notes: str = ""
    order_date: str
    expected_date: Optional[str] = None
    received_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_now)


class Settings(BaseModel):
    company_name: str = "Bulog Gudang Sunter Timur I & II"
    address: str = "Jl. Industri Raya No. 12, Kawasan Pergudangan, Jakarta Barat 11710"
    phone: str = "021-5566789"
    email: str = "operasional@gudangpro.co.id"
    footer_note: str = "Barang yang sudah diterima tidak dapat dikembalikan tanpa persetujuan."
