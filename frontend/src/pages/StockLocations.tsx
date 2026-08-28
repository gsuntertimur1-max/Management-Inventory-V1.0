import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, FileSpreadsheet, Layers, Pencil, Plus, Shuffle, Trash2 } from "lucide-react";
import { toast } from "sonner";
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
import { angka } from "@/lib/format";
import { can, useAuth } from "@/lib/session";
import type {
  DistributeResult,
  Location,
  Placement,
  PlacementCreate,
  Product,
} from "@/lib/types";

const EMPTY: PlacementCreate = {
  location_code: "",
  product_id: "",
  length: 10,
  width: 22,
  height: 25,
  notes: "",
};

export default function StockLocations() {
  const qc = useQueryClient();
  const { role } = useAuth();
  const canWrite = can(role, "procurement:write");

  const [complexFilter, setComplexFilter] = useState("ALL");
  const [unitFilter, setUnitFilter] = useState("ALL");
  const [open, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<PlacementCreate>(EMPTY);

  const locationsQ = useQuery({ queryKey: ["locations"], queryFn: () => apiGet<Location[]>("/locations") });
  const placementsQ = useQuery({ queryKey: ["placements"], queryFn: () => apiGet<Placement[]>("/placements") });
  const productsQ = useQuery({ queryKey: ["products"], queryFn: () => apiGet<Product[]>("/products") });

  const locations = locationsQ.data ?? [];
  const placements = placementsQ.data ?? [];
  const products = productsQ.data ?? [];

  const units = useMemo(() => {
    const seen: { unit: string; complex: string }[] = [];
    for (const l of locations) {
      if (!seen.some((s) => s.unit === l.unit_name)) seen.push({ unit: l.unit_name, complex: l.complex_name });
    }
    return seen;
  }, [locations]);

  const visibleUnits = useMemo(
    () => units.filter((u) => complexFilter === "ALL" || u.complex === complexFilter),
    [units, complexFilter],
  );

  const rows = useMemo(
    () =>
      placements.filter(
        (p) =>
          (complexFilter === "ALL" || p.complex_name === complexFilter) &&
          (unitFilter === "ALL" || p.unit_name === unitFilter),
      ),
    [placements, complexFilter, unitFilter],
  );

  const totals = useMemo(
    () => ({
      stacks: new Set(rows.map((r) => r.location_code)).size,
      secondary: rows.reduce((a, r) => a + r.secondary_count, 0),
      weight: rows.reduce((a, r) => a + r.total_weight, 0),
    }),
    [rows],
  );

  const stackOptions = useMemo(
    () =>
      locations.filter(
        (l) =>
          (complexFilter === "ALL" || l.complex_name === complexFilter) &&
          (unitFilter === "ALL" || l.unit_name === unitFilter),
      ),
    [locations, complexFilter, unitFilter],
  );

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["placements"] });
    void qc.invalidateQueries({ queryKey: ["locations"] });
  };

  const failMessage = (e: unknown, fallback: string) =>
    e instanceof ApiError && typeof (e.body as { detail?: string })?.detail === "string"
      ? (e.body as { detail: string }).detail
      : fallback;

  const save = useMutation({
    mutationFn: (payload: PlacementCreate) =>
      editingId
        ? apiPut<Placement>(`/placements/${editingId}`, payload)
        : apiPost<Placement>("/placements", payload),
    onSuccess: () => {
      invalidate();
      setOpen(false);
      toast.success(editingId ? "Penempatan stok diperbarui" : "Stok ditempatkan ke tumpukan");
    },
    onError: (e) => toast.error(failMessage(e, "Gagal menyimpan penempatan stok")),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiDelete<{ ok: boolean }>(`/placements/${id}`),
    onSuccess: () => {
      invalidate();
      toast.success("Penempatan stok dihapus");
    },
    onError: (e) => toast.error(failMessage(e, "Gagal menghapus penempatan")),
  });

  const distribute = useMutation({
    mutationFn: () => apiPost<DistributeResult>("/placements/distribute"),
    onSuccess: (res) => {
      invalidate();
      toast.success(
        `${res.placements} tumpukan terisi dari ${res.products} komoditas (${angka(Math.round(res.total_weight))} Kg)`,
      );
    },
    onError: (e) => toast.error(failMessage(e, "Gagal menyebar stok ke tumpukan")),
  });

  const openCreate = () => {
    setEditingId(null);
    setForm({ ...EMPTY, location_code: stackOptions[0]?.code ?? "", product_id: products[0]?.id ?? "" });
    setOpen(true);
  };

  const openEdit = (p: Placement) => {
    setEditingId(p.id);
    setForm({
      location_code: p.location_code,
      product_id: p.product_id,
      length: p.length,
      width: p.width,
      height: p.height,
      notes: p.notes,
    });
    setOpen(true);
  };

  const selectedProduct = products.find((p) => p.id === form.product_id);
  const previewSecondary = Math.max(1, form.length) * Math.max(1, form.width) * Math.max(1, form.height);
  const previewWeightPerSecondary = selectedProduct
    ? selectedProduct.weight_per_unit * (selectedProduct.units_per_secondary || 1)
    : 0;

  const submit = () => {
    if (!form.location_code || !form.product_id) {
      toast.error("Pilih tumpukan dan komoditas terlebih dahulu");
      return;
    }
    save.mutate({
      ...form,
      length: Math.max(1, Math.round(form.length)),
      width: Math.max(1, Math.round(form.width)),
      height: Math.max(1, Math.round(form.height)),
    });
  };

  return (
    <AppShell>
      <div className="animate-rise space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              Tata Letak Gudang
            </p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">
              Stok per Tumpukan
            </h1>
            <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
              Kode tumpukan gabungan unit gudang dan nomor tumpukan, contoh{" "}
              <span className="font-mono text-foreground">GBB 23/A01.1.1</span>. Satu tumpukan boleh
              berisi beberapa komoditas, dan jumlah stok dihitung dari perkalian tumpukan P × L × T.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <a
              href="/api/reports/stock-locations.xlsx"
              data-testid="btn-export-stack-excel"
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors duration-150 hover:bg-secondary"
            >
              <FileSpreadsheet className="size-4" /> Export Excel
            </a>
            {canWrite && (
              <>
                <Button
                  variant="outline"
                  data-testid="btn-distribute-stock"
                  disabled={distribute.isPending}
                  onClick={() => distribute.mutate()}
                >
                  <Shuffle className="size-4" />
                  {distribute.isPending ? "Menyebar..." : "Sebar Stok Otomatis"}
                </Button>
                <Button onClick={openCreate} data-testid="btn-create-placement">
                  <Plus className="size-4" /> Tempatkan Stok
                </Button>
              </>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Card>
            <CardContent className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-lg bg-secondary">
                <Layers className="size-5 text-primary" />
              </span>
              <div>
                <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                  Tumpukan Terisi
                </p>
                <p className="text-xl font-bold" data-testid="stat-filled-stacks">
                  {angka(totals.stacks)} / {angka(locations.length)}
                </p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-lg bg-secondary">
                <Boxes className="size-5 text-primary" />
              </span>
              <div>
                <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                  Total Kemasan Sekunder
                </p>
                <p className="text-xl font-bold" data-testid="stat-total-secondary">
                  {angka(totals.secondary)}
                </p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-lg bg-secondary">
                <Boxes className="size-5 text-emerald-400" />
              </span>
              <div>
                <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                  Total Berat Tersimpan
                </p>
                <p className="text-xl font-bold" data-testid="stat-total-weight">
                  {angka(Math.round(totals.weight))} Kg
                </p>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5">
            <Label>Kompleks Gudang</Label>
            <Select
              value={complexFilter}
              onValueChange={(v: string) => {
                setComplexFilter(v);
                setUnitFilter("ALL");
              }}
            >
              <SelectTrigger className="w-64" data-testid="filter-complex-select">
                <SelectValue>
                  {complexFilter === "ALL" ? "Semua Kompleks" : complexFilter}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">Semua Kompleks</SelectItem>
                <SelectItem value="Gudang Sunter Timur I">Gudang Sunter Timur I</SelectItem>
                <SelectItem value="Gudang Sunter Timur II">Gudang Sunter Timur II</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Unit Gudang</Label>
            <Select value={unitFilter} onValueChange={(v: string) => setUnitFilter(v)}>
              <SelectTrigger className="w-48" data-testid="filter-unit-select">
                <SelectValue>{unitFilter === "ALL" ? "Semua Unit" : unitFilter}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">Semua Unit</SelectItem>
                {visibleUnits.map((u) => (
                  <SelectItem key={u.unit} value={u.unit}>
                    {u.unit}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <Card>
          <CardContent className="overflow-x-auto p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Kode Tumpukan</TableHead>
                  <TableHead>Komoditas</TableHead>
                  <TableHead>Kemasan</TableHead>
                  <TableHead className="text-right">P × L × T</TableHead>
                  <TableHead className="text-right">Jumlah Kemasan</TableHead>
                  <TableHead className="text-right">Total Berat</TableHead>
                  {canWrite && <TableHead className="text-right">Aksi</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody data-testid="table-placements-body">
                {rows.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={canWrite ? 7 : 6} className="py-10 text-center text-muted-foreground">
                      Belum ada stok pada tumpukan ini. Gunakan "Sebar Stok Otomatis" atau tempatkan manual.
                    </TableCell>
                  </TableRow>
                )}
                {rows.map((p) => (
                  <TableRow key={p.id} data-testid="placement-row">
                    <TableCell>
                      <p className="font-mono text-sm font-semibold" data-testid="placement-code">
                        {p.location_code}
                      </p>
                      <p className="text-xs text-muted-foreground">{p.complex_name}</p>
                    </TableCell>
                    <TableCell>
                      <p className="text-sm font-medium">{p.product_name}</p>
                      <p className="font-mono text-xs text-muted-foreground">{p.product_sku}</p>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {p.units_per_secondary} {p.unit}/{p.secondary_unit}
                      <br />
                      {angka(p.weight_per_secondary)} {p.weight_unit} per {p.secondary_unit}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {p.length} × {p.width} × {p.height}
                    </TableCell>
                    <TableCell className="text-right">
                      <Badge variant="secondary" data-testid="placement-secondary-count">
                        {angka(p.secondary_count)} {p.secondary_unit}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm font-semibold" data-testid="placement-weight">
                      {angka(p.total_weight)} {p.weight_unit}
                    </TableCell>
                    {canWrite && (
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`Ubah ${p.location_code}`}
                            data-testid="btn-edit-placement"
                            onClick={() => openEdit(p)}
                          >
                            <Pencil className="size-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`Hapus ${p.location_code}`}
                            data-testid="btn-delete-placement"
                            onClick={() => remove.mutate(p.id)}
                          >
                            <Trash2 className="size-4 text-red-400" />
                          </Button>
                        </div>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editingId ? "Ubah Penempatan Stok" : "Tempatkan Stok ke Tumpukan"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Tumpukan</Label>
              <Select
                value={form.location_code}
                onValueChange={(v: string) => setForm({ ...form, location_code: v })}
              >
                <SelectTrigger data-testid="form-placement-location">
                  <SelectValue placeholder="Pilih tumpukan" />
                </SelectTrigger>
                <SelectContent className="max-h-72">
                  {(stackOptions.length ? stackOptions : locations).map((l) => (
                    <SelectItem key={l.code} value={l.code}>
                      {l.code} — {l.complex_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Komoditas</Label>
              <Select
                value={form.product_id}
                onValueChange={(v: string) => setForm({ ...form, product_id: v })}
              >
                <SelectTrigger data-testid="form-placement-product">
                  <SelectValue placeholder="Pilih komoditas">
                    {selectedProduct ? `${selectedProduct.name} (${selectedProduct.sku})` : undefined}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent className="max-h-72">
                  {products.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name} ({p.sku})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-2">
                <Label htmlFor="pl-p">P (Panjang)</Label>
                <Input
                  id="pl-p"
                  type="number"
                  min={1}
                  data-testid="form-placement-length"
                  value={form.length}
                  onChange={(e) => setForm({ ...form, length: Number(e.target.value) })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="pl-l">L (Lebar)</Label>
                <Input
                  id="pl-l"
                  type="number"
                  min={1}
                  data-testid="form-placement-width"
                  value={form.width}
                  onChange={(e) => setForm({ ...form, width: Number(e.target.value) })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="pl-t">T (Tinggi)</Label>
                <Input
                  id="pl-t"
                  type="number"
                  min={1}
                  data-testid="form-placement-height"
                  value={form.height}
                  onChange={(e) => setForm({ ...form, height: Number(e.target.value) })}
                />
              </div>
            </div>
            <div className="rounded-lg border border-border bg-secondary/40 p-3 text-sm" data-testid="placement-preview">
              <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                Hasil perkalian tumpukan
              </p>
              <p className="mt-1 font-semibold">
                {angka(previewSecondary)} {selectedProduct?.secondary_unit ?? "Kemasan"} ·{" "}
                {angka(Math.round(previewSecondary * previewWeightPerSecondary))}{" "}
                {selectedProduct?.weight_unit ?? "Kg"}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {selectedProduct
                  ? `1 ${selectedProduct.secondary_unit} = ${selectedProduct.units_per_secondary} ${selectedProduct.unit} = ${angka(previewWeightPerSecondary)} ${selectedProduct.weight_unit}`
                  : "Pilih komoditas untuk melihat konversi kemasan"}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="pl-note">Catatan</Label>
              <Input
                id="pl-note"
                data-testid="form-placement-notes"
                placeholder="Misal: sisa muatan truk B 9021 XY"
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} data-testid="btn-cancel-placement">
              Batal
            </Button>
            <Button onClick={submit} disabled={save.isPending} data-testid="btn-submit-placement">
              {save.isPending ? "Menyimpan..." : "Simpan Penempatan"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
