import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, PackageCheck, Plus, Trash2 } from "lucide-react";
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
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { angka, rupiah, tanggal } from "@/lib/format";
import type { POItemInput, Product, PurchaseOrder, PurchaseOrderCreate, Supplier } from "@/lib/types";

interface Draft extends POItemInput {
  key: number;
}

const STATUS_VARIANT: Record<string, "secondary" | "destructive" | "outline"> = {
  MENUNGGU: "outline",
  DITERIMA: "secondary",
  DIBATALKAN: "destructive",
};

export default function PurchaseOrders() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [supplierId, setSupplierId] = useState("");
  const [notes, setNotes] = useState("");
  const [rows, setRows] = useState<Draft[]>([{ key: 1, product_id: "", quantity: 1, unit_price: 0 }]);

  const poQ = useQuery({
    queryKey: ["purchase-orders"],
    queryFn: () => apiGet<PurchaseOrder[]>("/purchase-orders"),
  });
  const productsQ = useQuery({ queryKey: ["products"], queryFn: () => apiGet<Product[]>("/products") });
  const suppliersQ = useQuery({ queryKey: ["suppliers"], queryFn: () => apiGet<Supplier[]>("/suppliers") });

  const orders = poQ.isError ? [] : poQ.data ?? [];
  const products = productsQ.isError ? [] : productsQ.data ?? [];
  const suppliers = suppliersQ.isError ? [] : suppliersQ.data ?? [];

  const draftTotal = useMemo(
    () =>
      rows.reduce((sum, r) => {
        const p = products.find((x) => x.id === r.product_id);
        const price = r.unit_price > 0 ? r.unit_price : p?.purchase_price ?? 0;
        return sum + price * r.quantity;
      }, 0),
    [rows, products],
  );

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["purchase-orders"] });
    void qc.invalidateQueries({ queryKey: ["products"] });
    void qc.invalidateQueries({ queryKey: ["transactions"] });
    void qc.invalidateQueries({ queryKey: ["stats"] });
  };

  const errMsg = (e: unknown, fallback: string) =>
    e instanceof ApiError && typeof (e.body as { detail?: string })?.detail === "string"
      ? (e.body as { detail: string }).detail
      : fallback;

  const create = useMutation({
    mutationFn: (payload: PurchaseOrderCreate) => apiPost<PurchaseOrder>("/purchase-orders", payload),
    onSuccess: (po) => {
      invalidate();
      setOpen(false);
      setRows([{ key: 1, product_id: "", quantity: 1, unit_price: 0 }]);
      setNotes("");
      toast.success(`${po.po_number} dibuat — menunggu kedatangan barang`);
    },
    onError: (e) => toast.error(errMsg(e, "Gagal membuat Purchase Order")),
  });

  const receive = useMutation({
    mutationFn: (id: string) => apiPost<PurchaseOrder>(`/purchase-orders/${id}/receive`),
    onSuccess: (po) => {
      invalidate();
      toast.success(`${po.po_number} diterima — stok masuk otomatis dicatat`);
    },
    onError: (e) => toast.error(errMsg(e, "Gagal memproses penerimaan barang")),
  });

  const cancel = useMutation({
    mutationFn: (id: string) => apiPost<PurchaseOrder>(`/purchase-orders/${id}/cancel`),
    onSuccess: (po) => {
      invalidate();
      toast.success(`${po.po_number} dibatalkan`);
    },
    onError: (e) => toast.error(errMsg(e, "Gagal membatalkan PO")),
  });

  const submit = () => {
    const items = rows
      .filter((r) => r.product_id && r.quantity > 0)
      .map((r) => ({ product_id: r.product_id, quantity: r.quantity, unit_price: r.unit_price }));
    if (!supplierId) {
      toast.error("Pilih supplier terlebih dahulu");
      return;
    }
    if (items.length === 0) {
      toast.error("Tambahkan minimal satu item produk");
      return;
    }
    create.mutate({ supplier_id: supplierId, items, notes });
  };

  return (
    <AppShell>
      <div className="animate-rise space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Pengadaan</p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">Purchase Order</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Buat pesanan ke supplier, lalu tekan "Barang Datang" untuk mengubahnya menjadi stok masuk.
            </p>
          </div>
          <Button onClick={() => setOpen(true)} data-testid="btn-create-po">
            <Plus className="size-4" /> Buat Purchase Order
          </Button>
        </div>

        <Card className="overflow-hidden p-0">
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>No. PO</TableHead>
                  <TableHead>Tanggal</TableHead>
                  <TableHead>Supplier</TableHead>
                  <TableHead>Item</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Aksi</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody data-testid="table-purchase-orders-body">
                {orders.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={7} className="py-10 text-center text-sm text-muted-foreground">
                      Belum ada Purchase Order.
                    </TableCell>
                  </TableRow>
                )}
                {orders.map((po) => (
                  <TableRow key={po.id} data-testid={`po-row-${po.po_number}`}>
                    <TableCell className="font-mono text-xs font-semibold">{po.po_number}</TableCell>
                    <TableCell className="text-xs">{tanggal(po.order_date)}</TableCell>
                    <TableCell className="text-sm">{po.supplier_name}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {po.items.map((i) => (
                        <span key={i.product_id} className="block">
                          {i.product_name} × {angka(i.quantity)} {i.unit}
                        </span>
                      ))}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">{rupiah(po.total)}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[po.status]} data-testid={`po-status-${po.po_number}`}>
                        {po.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {po.status === "MENUNGGU" ? (
                        <div className="flex justify-end gap-2">
                          <Button
                            size="sm"
                            onClick={() => receive.mutate(po.id)}
                            disabled={receive.isPending}
                            data-testid={`btn-receive-po-${po.po_number}`}
                          >
                            <PackageCheck className="size-4" /> Barang Datang
                          </Button>
                          <Button
                            size="icon-sm"
                            variant="ghost"
                            aria-label={`Batalkan ${po.po_number}`}
                            onClick={() => cancel.mutate(po.id)}
                            data-testid={`btn-cancel-po-${po.po_number}`}
                          >
                            <Ban className="size-4 text-red-400" />
                          </Button>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          {po.status === "DITERIMA" ? "Stok sudah masuk" : "—"}
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>Buat Purchase Order</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Supplier</Label>
              <Select value={supplierId} onValueChange={(v: string) => setSupplierId(v)}>
                <SelectTrigger data-testid="form-po-supplier">
                  <SelectValue>
                    {(v) => suppliers.find((s) => s.id === v)?.name ?? "Pilih supplier..."}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {suppliers.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-3">
              <Label>Item Pesanan</Label>
              {rows.map((row, idx) => (
                <div key={row.key} className="flex flex-wrap items-end gap-2" data-testid="po-item-row">
                  <div className="min-w-52 flex-1">
                    <Select
                      value={row.product_id}
                      onValueChange={(v: string) =>
                        setRows(rows.map((r) => (r.key === row.key ? { ...r, product_id: v } : r)))
                      }
                    >
                      <SelectTrigger data-testid={`form-po-product-${idx}`}>
                        <SelectValue>
                          {(v) => {
                            const p = products.find((x) => x.id === v);
                            return p ? `${p.name} (${p.sku})` : "Pilih produk...";
                          }}
                        </SelectValue>
                      </SelectTrigger>
                      <SelectContent className="max-h-72">
                        {products.map((p) => (
                          <SelectItem key={p.id} value={p.id}>
                            {p.name} — {p.sku}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <Input
                    className="w-24"
                    type="number"
                    min={1}
                    aria-label="Jumlah"
                    data-testid={`form-po-quantity-${idx}`}
                    value={String(row.quantity)}
                    onChange={(e) =>
                      setRows(
                        rows.map((r) =>
                          r.key === row.key ? { ...r, quantity: Number(e.target.value) } : r,
                        ),
                      )
                    }
                  />
                  <Input
                    className="w-36"
                    type="number"
                    aria-label="Harga satuan"
                    placeholder="Harga satuan"
                    data-testid={`form-po-price-${idx}`}
                    value={String(row.unit_price)}
                    onChange={(e) =>
                      setRows(
                        rows.map((r) =>
                          r.key === row.key ? { ...r, unit_price: Number(e.target.value) } : r,
                        ),
                      )
                    }
                  />
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Hapus item"
                    data-testid={`btn-remove-po-item-${idx}`}
                    onClick={() => setRows(rows.length > 1 ? rows.filter((r) => r.key !== row.key) : rows)}
                  >
                    <Trash2 className="size-4 text-red-400" />
                  </Button>
                </div>
              ))}
              <Button
                variant="outline"
                size="sm"
                data-testid="btn-add-po-item"
                onClick={() =>
                  setRows([...rows, { key: Date.now(), product_id: "", quantity: 1, unit_price: 0 }])
                }
              >
                <Plus className="size-4" /> Tambah Item
              </Button>
            </div>

            <div className="space-y-2">
              <Label htmlFor="po-notes">Catatan</Label>
              <Textarea
                id="po-notes"
                rows={2}
                data-testid="form-po-notes"
                placeholder="Pengiriman diharapkan minggu depan..."
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </div>

            <p className="text-right text-sm">
              Estimasi total:{" "}
              <span className="font-mono font-semibold" data-testid="po-draft-total">
                {rupiah(draftTotal)}
              </span>
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} data-testid="btn-cancel-po-dialog">
              Batal
            </Button>
            <Button onClick={submit} disabled={create.isPending} data-testid="btn-submit-po">
              {create.isPending ? "Menyimpan..." : "Simpan Purchase Order"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
