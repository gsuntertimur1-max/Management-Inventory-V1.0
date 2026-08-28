// Hand-written mirrors of the Pydantic models in backend/models/inventory.py.
export interface Supplier {
  id: string;
  name: string;
  contact_person: string;
  phone: string;
  email: string;
  address: string;
  category_supplied: string;
  created_at: string;
}

export interface SupplierCreate {
  name: string;
  contact_person: string;
  phone: string;
  email: string;
  address: string;
  category_supplied: string;
}

export interface Product {
  id: string;
  name: string;
  sku: string;
  category: string;
  unit: string;
  purchase_price: number;
  selling_price: number;
  current_stock: number;
  supplier_id: string | null;
  supplier_name: string;
  location: string;
  created_at: string;
}

export interface ProductCreate {
  name: string;
  sku: string;
  category: string;
  unit: string;
  purchase_price: number;
  selling_price: number;
  current_stock: number;
  supplier_id: string | null;
  location: string;
}

export type MovementType = "MASUK" | "KELUAR";

export interface Transaction {
  id: string;
  product_id: string;
  product_name: string;
  product_sku: string;
  category: string;
  type: MovementType;
  quantity: number;
  stock_after: number;
  party: string;
  reference_no: string;
  queue_no: string;
  shipment_id: string | null;
  created_by: string | null;
  created_by_name: string;
  notes: string;
  date: string;
  created_at: string;
}

export type ShipmentStatus = "MENUNGGU" | "DIMUAT" | "SELESAI";

export interface ShipmentItem {
  product_id: string;
  product_name: string;
  product_sku: string;
  unit: string;
  quantity: number;
  stock_after: number;
}

export interface ShipmentItemInput {
  product_id: string;
  quantity: number;
}

export interface Shipment {
  id: string;
  doc_no: string;
  queue_no: string;
  party: string;
  reference_no: string;
  notes: string;
  date: string;
  items: ShipmentItem[];
  total_quantity: number;
  status: ShipmentStatus;
  created_by: string | null;
  created_by_name: string;
  created_at: string;
}

export interface ShipmentCreate {
  party: string;
  reference_no: string;
  notes: string;
  date?: string | null;
  items: ShipmentItemInput[];
}

export type POStatus = "MENUNGGU" | "DITERIMA" | "DIBATALKAN";

export interface POItem {
  product_id: string;
  product_name: string;
  product_sku: string;
  unit: string;
  quantity: number;
  unit_price: number;
  subtotal: number;
}

export interface POItemInput {
  product_id: string;
  quantity: number;
  unit_price: number;
}

export interface PurchaseOrder {
  id: string;
  po_number: string;
  supplier_id: string;
  supplier_name: string;
  status: POStatus;
  items: POItem[];
  total: number;
  notes: string;
  order_date: string;
  expected_date: string | null;
  received_at: string | null;
  created_at: string;
}

export interface PurchaseOrderCreate {
  supplier_id: string;
  items: POItemInput[];
  notes: string;
  expected_date?: string | null;
}

export interface AppSettings {
  company_name: string;
  address: string;
  phone: string;
  email: string;
  footer_note: string;
}

export interface TransactionCreate {
  product_id: string;
  type: MovementType;
  quantity: number;
  party: string;
  reference_no: string;
  notes: string;
  date?: string | null;
}

export interface CategoryStat {
  category: string;
  units: number;
}

export interface TimelinePoint {
  date: string;
  masuk: number;
  keluar: number;
}

export interface Stats {
  total_products: number;
  total_units: number;
  total_valuation: number;
  recent_movements: number;
  by_category: CategoryStat[];
  timeline: TimelinePoint[];
}

export type ImportMode = "add" | "replace";

export interface ProductImportRow {
  sku: string;
  name: string;
  quantity: number;
  category?: string | null;
  unit?: string | null;
  purchase_price?: number | null;
  selling_price?: number | null;
  supplier_name?: string | null;
  location?: string | null;
}

export interface ProductImportRequest {
  mode: ImportMode;
  supplier_id: string | null;
  items: ProductImportRow[];
}

export interface ProductImportResult {
  created: number;
  updated: number;
  units_added: number;
  suppliers_created: number;
  errors: string[];
}

export const CATEGORIES = [
  "Elektronik & Gadget",
  "Peralatan Kantor",
  "F&B / Bahan Makanan",
  "Pakaian & Tekstil",
  "Hardware & Perkakas",
  "Lainnya",
];

export const UNITS = ["Pcs", "Box", "Unit", "Kg", "Liter", "Pack", "Roll", "Set"];
