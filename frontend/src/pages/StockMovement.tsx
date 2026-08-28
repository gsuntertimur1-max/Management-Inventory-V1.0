import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowDownLeft, ArrowUpRight, Printer, Receipt, Save } from "lucide-react";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { angka, rupiah } from "@/lib/format";
import type { MovementType, Product, Supplier, Transaction, TransactionCreate } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function StockMovement() {
  const qc = useQueryClient();
  const [type, setType] = useState<MovementType>("MASUK");
  const [productId, setProductId] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [party, setParty] = useState("");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [lastOut, setLastOut] = useState<Transaction | null>(null);

  const productsQ = useQuery({ queryKey: ["products"], queryFn: () => apiGet<Product[]>("/products") });
  const suppliersQ = useQuery({ queryKey: ["suppliers"], queryFn: () => apiGet<Supplier[]>("/suppliers") });

  const products = productsQ.isError ? [] : productsQ.data ?? [];
  const suppliers = suppliersQ.isError ? [] : suppliersQ.data ?? [];
  const selected = useMemo(() => products.find((p) => p.id === productId), [products, productId]);

  const submitMovement = useMutation({
    mutationFn: (payload: TransactionCreate) => apiPost<Transaction>("/transactions", payload),
    onSuccess: (tx) => {
      void qc.invalidateQueries({ queryKey: ["products"] });
      void qc.invalidateQueries({ queryKey: ["transactions"] });
      void qc.invalidateQueries({ queryKey: ["stats"] });
      toast.success(
        `Stok ${tx.type} ${angka(tx.quantity)} unit dicatat. Sisa stok ${angka(tx.stock_after)}`,
      );
      setLastOut(tx.type === "KELUAR" ? tx : null);
      setQuantity("1");
      setReference("");
      setNotes("");
      setParty("");
    },
    onError: (e) => {
      const msg =
        e instanceof ApiError && typeof (e.body as { detail?: string })?.detail === "string"
          ? (e.body as { detail: string }).detail
          : "Gagal mencatat transaksi";
      toast.error(msg);
    },
  });

  const submit = () => {
    const qty = Number(quantity);
    if (!productId) {
      toast.error("Pilih produk terlebih dahulu");
      return;
    }
    if (!Number.isFinite(qty) || qty < 1) {
      toast.error("Jumlah unit minimal 1");
      return;
    }
    submitMovement.mutate({ product_id: productId, type, quantity: qty, party, reference_no: reference, notes });
  };

  return (
    <AppShell>
      <div className="animate-rise space-y-6">
        <div>
          <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Operasional Gudang</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">
            Pencatatan Stok Masuk / Keluar
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Setiap transaksi otomatis memperbarui jumlah stok produk dan masuk ke riwayat.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          <Card className="lg:col-span-7">
            <CardHeader>
              <CardTitle className="text-lg">Formulir Transaksi</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  data-testid="form-movement-type-in"
                  onClick={() => setType("MASUK")}
                  className={cn(
                    "flex items-center justify-center gap-2 rounded-xl border px-4 py-3 text-sm font-semibold transition-colors duration-150",
                    type === "MASUK"
                      ? "border-emerald-500/60 bg-emerald-500/10 text-emerald-400"
                      : "border-border text-muted-foreground hover:bg-secondary",
                  )}
                >
                  <ArrowDownLeft className="size-4" /> STOK MASUK
                </button>
                <button
                  type="button"
                  data-testid="form-movement-type-out"
                  onClick={() => setType("KELUAR")}
                  className={cn(
                    "flex items-center justify-center gap-2 rounded-xl border px-4 py-3 text-sm font-semibold transition-colors duration-150",
                    type === "KELUAR"
                      ? "border-red-500/60 bg-red-500/10 text-red-400"
                      : "border-border text-muted-foreground hover:bg-secondary",
                  )}
                >
                  <ArrowUpRight className="size-4" /> STOK KELUAR
                </button>
              </div>

              <div className="space-y-2">
                <Label>Pilih Produk</Label>
                <Select value={productId} onValueChange={(v: string) => setProductId(v)}>
                  <SelectTrigger data-testid="form-movement-product-select">
                    <SelectValue>
                      {(v) => {
                        const found = products.find((p) => p.id === v);
                        return found ? `${found.name} (${found.sku})` : "Pilih produk...";
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

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="m-qty">Jumlah Unit</Label>
                  <Input
                    id="m-qty"
                    type="number"
                    min={1}
                    data-testid="form-movement-quantity"
                    value={quantity}
                    onChange={(e) => setQuantity(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="m-ref">No. Surat Jalan / PO</Label>
                  <Input
                    id="m-ref"
                    placeholder="PO-2026-001"
                    data-testid="form-movement-reference"
                    value={reference}
                    onChange={(e) => setReference(e.target.value)}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label>{type === "MASUK" ? "Supplier Pengirim" : "Penerima / Customer"}</Label>
                {type === "MASUK" ? (
                  <Select value={party} onValueChange={(v: string) => setParty(v)}>
                    <SelectTrigger data-testid="form-movement-party-select">
                      <SelectValue>{(v) => (v ? String(v) : "Pilih supplier...")}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {suppliers.map((s) => (
                        <SelectItem key={s.id} value={s.name}>
                          {s.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    placeholder="Nama penerima / toko"
                    data-testid="form-movement-party-input"
                    value={party}
                    onChange={(e) => setParty(e.target.value)}
                  />
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="m-notes">Keterangan</Label>
                <Textarea
                  id="m-notes"
                  rows={3}
                  placeholder="Pengiriman batch 2 atau retur barang cacat..."
                  data-testid="form-movement-notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                />
              </div>

              <Button
                className="w-full"
                onClick={submit}
                disabled={submitMovement.isPending}
                data-testid="btn-submit-movement"
              >
                <Save className="size-4" />
                {submitMovement.isPending ? "Menyimpan..." : "Simpan Transaksi"}
              </Button>

              {lastOut && (
                <div
                  className="space-y-2 rounded-xl border border-border bg-secondary/40 p-3"
                  data-testid="last-outbound-print"
                >
                  <p className="text-xs text-muted-foreground">
                    Transaksi keluar tersimpan — No. Antrian{" "}
                    <span className="font-mono font-semibold text-foreground">{lastOut.queue_no}</span>
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Link
                      to={`/print/surat-jalan?ids=${lastOut.id}`}
                      target="_blank"
                      data-testid="btn-print-note-after-save"
                      className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors duration-150 hover:bg-secondary"
                    >
                      <Printer className="size-4" /> Cetak Surat Jalan (A4)
                    </Link>
                    <Link
                      to={`/print/bon-muat/${lastOut.id}`}
                      target="_blank"
                      data-testid="btn-print-slip-after-save"
                      className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors duration-150 hover:bg-secondary"
                    >
                      <Receipt className="size-4" /> Cetak Bon Muat (80mm)
                    </Link>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="lg:col-span-5" data-testid="movement-preview-card">
            <CardHeader>
              <CardTitle className="text-lg">Ringkasan Produk Terpilih</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {!selected ? (
                <p className="text-sm text-muted-foreground">
                  Pilih produk untuk melihat stok saat ini dan perkiraan stok setelah transaksi.
                </p>
              ) : (
                <div className="space-y-4">
                  <div>
                    <p className="text-base font-semibold">{selected.name}</p>
                    <p className="font-mono text-xs text-muted-foreground">{selected.sku}</p>
                  </div>
                  <Badge variant="secondary">{selected.category}</Badge>
                  <dl className="space-y-3 text-sm">
                    <div className="flex justify-between border-b border-border pb-2">
                      <dt className="text-muted-foreground">Stok saat ini</dt>
                      <dd className="font-mono font-semibold" data-testid="preview-current-stock">
                        {angka(selected.current_stock)} {selected.unit}
                      </dd>
                    </div>
                    <div className="flex justify-between border-b border-border pb-2">
                      <dt className="text-muted-foreground">Perkiraan setelah transaksi</dt>
                      <dd
                        className={cn(
                          "font-mono font-semibold",
                          type === "MASUK" ? "text-emerald-400" : "text-red-400",
                        )}
                        data-testid="preview-next-stock"
                      >
                        {angka(
                          type === "MASUK"
                            ? selected.current_stock + (Number(quantity) || 0)
                            : selected.current_stock - (Number(quantity) || 0),
                        )}{" "}
                        {selected.unit}
                      </dd>
                    </div>
                    <div className="flex justify-between border-b border-border pb-2">
                      <dt className="text-muted-foreground">Harga modal</dt>
                      <dd className="font-mono">{rupiah(selected.purchase_price)}</dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-muted-foreground">Lokasi</dt>
                      <dd>{selected.location || "—"}</dd>
                    </div>
                  </dl>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
