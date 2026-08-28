import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, Pencil, Plus, Search, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import AppShell from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import { angka, rupiah } from "@/lib/format";
import { CATEGORIES, SECONDARY_UNITS, UNITS, WEIGHT_UNITS } from "@/lib/types";
import type { Product, ProductCreate, Supplier } from "@/lib/types";

const EMPTY: ProductCreate = {
  name: "",
  sku: "",
  category: "Elektronik & Gadget",
  unit: "Pcs",
  weight_per_unit: 1,
  weight_unit: "Kg",
  secondary_unit: "Dus",
  units_per_secondary: 1,
  min_stock: 0,
  purchase_price: 0,
  selling_price: 0,
  current_stock: 0,
  supplier_id: null,
  location: "",
};

export default function Products() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("SEMUA");
  const [open, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<ProductCreate>(EMPTY);

  const productsQ = useQuery({ queryKey: ["products"], queryFn: () => apiGet<Product[]>("/products") });
  const suppliersQ = useQuery({ queryKey: ["suppliers"], queryFn: () => apiGet<Supplier[]>("/suppliers") });

  const products = productsQ.isError ? [] : productsQ.data ?? [];
  const suppliers = suppliersQ.isError ? [] : suppliersQ.data ?? [];

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return products.filter(
      (p) =>
        (category === "SEMUA" || p.category === category) &&
        (q === "" || p.name.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q)),
    );
  }, [products, search, category]);

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["products"] });
    void qc.invalidateQueries({ queryKey: ["stats"] });
  };

  const save = useMutation({
    mutationFn: (payload: ProductCreate) =>
      editingId
        ? apiPut<Product>(`/products/${editingId}`, payload)
        : apiPost<Product>("/products", payload),
    onSuccess: () => {
      invalidate();
      setOpen(false);
      toast.success(editingId ? "Produk berhasil diperbarui" : "Produk baru ditambahkan");
    },
    onError: (e) => {
      const msg = e instanceof ApiError && typeof (e.body as { detail?: string })?.detail === "string"
        ? (e.body as { detail: string }).detail
        : "Gagal menyimpan produk";
      toast.error(msg);
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiDelete<{ ok: boolean }>(`/products/${id}`),
    onSuccess: () => {
      invalidate();
      toast.success("Produk dihapus");
    },
    onError: () => toast.error("Gagal menghapus produk"),
  });

  const openCreate = () => {
    setEditingId(null);
    setForm(EMPTY);
    setOpen(true);
  };

  const openEdit = (p: Product) => {
    setEditingId(p.id);
    setForm({
      name: p.name,
      sku: p.sku,
      category: p.category,
      unit: p.unit,
      weight_per_unit: p.weight_per_unit,
      weight_unit: p.weight_unit,
      secondary_unit: p.secondary_unit,
      units_per_secondary: p.units_per_secondary,
      min_stock: p.min_stock,
      purchase_price: p.purchase_price,
      selling_price: p.selling_price,
      current_stock: p.current_stock,
      supplier_id: p.supplier_id,
      location: p.location,
    });
    setOpen(true);
  };

  const submit = () => {
    if (!form.name.trim() || !form.sku.trim()) {
      toast.error("Nama produk dan kode SKU wajib diisi");
      return;
    }
    save.mutate(form);
  };

  return (
    <AppShell>
      <div className="animate-rise space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Master Data</p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">Daftar Produk</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {angka(filtered.length)} dari {angka(products.length)} produk ditampilkan
            </p>
          </div>
          <div className="flex gap-2">
            <Link
              to="/import"
              data-testid="btn-goto-import"
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors duration-150 hover:bg-secondary"
            >
              <Upload className="size-4" /> Import Data
            </Link>
            <a
              href="/api/reports/products.xlsx"
              data-testid="btn-export-products"
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors duration-150 hover:bg-secondary"
            >
              <FileSpreadsheet className="size-4" /> Unduh Excel
            </a>
            <Button onClick={openCreate} data-testid="btn-create-product">
              <Plus className="size-4" /> Tambah Produk
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap gap-3">
          <div className="relative min-w-60 flex-1">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              placeholder="Cari nama produk atau kode SKU..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              data-testid="product-search-input"
            />
          </div>
          <Select value={category} onValueChange={(v: string) => setCategory(v)}>
            <SelectTrigger className="w-60" data-testid="product-category-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="SEMUA">Semua Kategori</SelectItem>
              {CATEGORIES.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Card className="overflow-hidden p-0">
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nama Produk</TableHead>
                  <TableHead>SKU</TableHead>
                  <TableHead>Kategori</TableHead>
                  <TableHead className="text-right">Stok</TableHead>
                  <TableHead className="text-right">Harga Modal</TableHead>
                  <TableHead className="text-right">Nilai Total</TableHead>
                  <TableHead>Supplier / Lokasi</TableHead>
                  <TableHead className="text-right">Aksi</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody data-testid="table-products-body">
                {filtered.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={8} className="py-10 text-center text-sm text-muted-foreground">
                      Belum ada produk. Tambah produk baru atau muat data contoh.
                    </TableCell>
                  </TableRow>
                )}
                {filtered.map((p) => (
                  <TableRow key={p.id} data-testid={`product-row-${p.sku}`}>
                    <TableCell className="font-medium">{p.name}</TableCell>
                    <TableCell className="font-mono text-xs">{p.sku}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{p.category}</Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono" data-testid={`product-stock-${p.sku}`}>
                      {angka(p.current_stock)} {p.unit}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">{rupiah(p.purchase_price)}</TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {rupiah(p.purchase_price * p.current_stock)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {p.supplier_name || "—"}
                      <br />
                      {p.location || "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Edit ${p.name}`}
                          data-testid={`btn-edit-product-${p.sku}`}
                          onClick={() => openEdit(p)}
                        >
                          <Pencil className="size-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Hapus ${p.name}`}
                          data-testid={`btn-delete-product-${p.sku}`}
                          onClick={() => remove.mutate(p.id)}
                        >
                          <Trash2 className="size-4 text-red-400" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editingId ? "Ubah Produk" : "Tambah Produk Baru"}</DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="p-name">Nama Produk / Barang</Label>
              <Input
                id="p-name"
                data-testid="form-product-name"
                placeholder="Contoh: Laptop ThinkPad T14"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="p-sku">Kode SKU / Barcode</Label>
              <Input
                id="p-sku"
                data-testid="form-product-sku"
                placeholder="ELEC-TP-001"
                value={form.sku}
                onChange={(e) => setForm({ ...form, sku: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Kategori</Label>
              <Select value={form.category} onValueChange={(v: string) => setForm({ ...form, category: v })}>
                <SelectTrigger data-testid="form-product-category">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Satuan</Label>
              <Select value={form.unit} onValueChange={(v: string) => setForm({ ...form, unit: v })}>
                <SelectTrigger data-testid="form-product-unit">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {UNITS.map((u) => (
                    <SelectItem key={u} value={u}>
                      {u}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="p-stock">Jumlah Stok</Label>
              <Input
                id="p-stock"
                type="number"
                data-testid="form-product-stock"
                value={String(form.current_stock)}
                onChange={(e) => setForm({ ...form, current_stock: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="p-min">Stok Minimum (peringatan)</Label>
              <Input
                id="p-min"
                type="number"
                data-testid="form-product-min-stock"
                value={String(form.min_stock)}
                onChange={(e) => setForm({ ...form, min_stock: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-2 sm:col-span-2">
              <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                Kemasan Sekunder
              </p>
              <p className="text-xs text-muted-foreground">
                Contoh: Gula 1 Kg per Pcs, 24 Pcs dikemas dalam 1 Dus.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="p-wpu">Berat / Isi per Satuan</Label>
              <Input
                id="p-wpu"
                type="number"
                step="0.01"
                data-testid="form-product-weight-per-unit"
                value={String(form.weight_per_unit)}
                onChange={(e) => setForm({ ...form, weight_per_unit: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-2">
              <Label>Satuan Berat</Label>
              <Select
                value={form.weight_unit}
                onValueChange={(v: string) => setForm({ ...form, weight_unit: v })}
              >
                <SelectTrigger data-testid="form-product-weight-unit">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {WEIGHT_UNITS.map((u) => (
                    <SelectItem key={u} value={u}>
                      {u}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Satuan Kemasan Sekunder</Label>
              <Select
                value={form.secondary_unit}
                onValueChange={(v: string) => setForm({ ...form, secondary_unit: v })}
              >
                <SelectTrigger data-testid="form-product-secondary-unit">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SECONDARY_UNITS.map((u) => (
                    <SelectItem key={u} value={u}>
                      {u}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="p-ups">Isi per Kemasan Sekunder</Label>
              <Input
                id="p-ups"
                type="number"
                data-testid="form-product-units-per-secondary"
                value={String(form.units_per_secondary)}
                onChange={(e) => setForm({ ...form, units_per_secondary: Number(e.target.value) })}
              />
              <p className="text-xs text-muted-foreground">
                {form.units_per_secondary || 1} {form.unit} = 1 {form.secondary_unit} ·{" "}
                {((form.units_per_secondary || 1) * (form.weight_per_unit || 0)).toFixed(2)}{" "}
                {form.weight_unit} per {form.secondary_unit}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="p-buy">Harga Modal / Beli (Rp)</Label>
              <Input
                id="p-buy"
                type="number"
                data-testid="form-product-purchase-price"
                value={String(form.purchase_price)}
                onChange={(e) => setForm({ ...form, purchase_price: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="p-sell">Harga Jual (Rp)</Label>
              <Input
                id="p-sell"
                type="number"
                data-testid="form-product-selling-price"
                value={String(form.selling_price)}
                onChange={(e) => setForm({ ...form, selling_price: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-2">
              <Label>Supplier Utama</Label>
              <Select
                value={form.supplier_id ?? "NONE"}
                onValueChange={(v: string) => setForm({ ...form, supplier_id: v === "NONE" ? null : v })}
              >
                <SelectTrigger data-testid="form-product-supplier">
                  <SelectValue>
                    {(v) => {
                      const found = suppliers.find((s) => s.id === v);
                      return found ? found.name : "Tanpa Supplier";
                    }}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="NONE">Tanpa Supplier</SelectItem>
                  {suppliers.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="p-loc">Rak / Zona Penyimpanan</Label>
              <Input
                id="p-loc"
                data-testid="form-product-location"
                placeholder="Rak A-03 / Zona Barat"
                value={form.location}
                onChange={(e) => setForm({ ...form, location: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} data-testid="btn-cancel-product">
              Batal
            </Button>
            <Button onClick={submit} disabled={save.isPending} data-testid="btn-submit-product">
              {save.isPending ? "Menyimpan..." : "Simpan Produk"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
