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
  notes: string;
  date: string;
  created_at: string;
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

export const CATEGORIES = [
  "Elektronik & Gadget",
  "Peralatan Kantor",
  "F&B / Bahan Makanan",
  "Pakaian & Tekstil",
  "Hardware & Perkakas",
  "Lainnya",
];

export const UNITS = ["Pcs", "Box", "Unit", "Kg", "Liter", "Pack", "Roll", "Set"];
