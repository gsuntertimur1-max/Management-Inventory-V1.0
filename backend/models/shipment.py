import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


ShipmentStatus = Literal["MENUNGGU", "DIMUAT", "SELESAI"]


class ShipmentItemInput(BaseModel):
    product_id: str
    # Outbound is driven by weight only; primary + secondary quantities are derived server-side.
    weight: Optional[float] = Field(default=None, gt=0)
    quantity: Optional[int] = Field(default=None, gt=0)


class ShipmentItem(BaseModel):
    product_id: str
    product_name: str
    product_sku: str
    unit: str = "Pcs"
    quantity: int
    weight: float = 0
    weight_unit: str = "Kg"
    weight_per_unit: float = 1
    secondary_qty: float = 0
    secondary_unit: str = "Dus"
    units_per_secondary: int = 1
    stock_after: int = 0


class ShipmentCreate(BaseModel):
    party: str = ""
    reference_no: str = ""
    notes: str = ""
    date: Optional[str] = None
    items: List[ShipmentItemInput]


class Shipment(BaseModel):
    id: str = Field(default_factory=_uid)
    doc_no: str
    queue_no: str
    party: str = ""
    reference_no: str = ""
    notes: str = ""
    date: str
    items: List[ShipmentItem] = []
    total_quantity: int = 0
    total_weight: float = 0
    status: ShipmentStatus = "MENUNGGU"
    created_by: Optional[str] = None
    created_by_name: str = ""
    created_at: datetime = Field(default_factory=_now)


class ShipmentStatusUpdate(BaseModel):
    status: ShipmentStatus
