from typing import List, Literal, Optional

from pydantic import BaseModel, Field

ImportMode = Literal["add", "replace"]


class ProductImportRow(BaseModel):
    sku: str
    name: str = ""
    quantity: int = 0
    category: Optional[str] = None
    unit: Optional[str] = None
    purchase_price: Optional[float] = None
    selling_price: Optional[float] = None
    supplier_name: Optional[str] = None
    location: Optional[str] = None


class ProductImportRequest(BaseModel):
    mode: ImportMode = "add"
    supplier_id: Optional[str] = None
    items: List[ProductImportRow] = Field(default_factory=list)


class ProductImportResult(BaseModel):
    created: int = 0
    updated: int = 0
    units_added: int = 0
    suppliers_created: int = 0
    errors: List[str] = Field(default_factory=list)
