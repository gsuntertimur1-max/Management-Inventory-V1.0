import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowDownLeft, ArrowUpRight, Plus, Printer, Receipt, Save, Trash2 } from "lucide-react";
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
import type {
  MovementType,
  Product,
  Shipment,
  ShipmentCreate,
  Supplier,
  Transaction,
  TransactionCreate,
} from "@/lib/types";
import { cn } from "@/lib/utils";

interface Line {
  key: number;
  product_id: string;
  quantity: string;
}

const emptyLine = (): Line => ({ key: Date.now() + Math.random(), product_id: "", quantity: "1" });

export default function StockMovement() {
  const qc = useQueryClient();
  const [type, setType] = useState<MovementType>("MASUK");
  const [lines, setLines] = useState<Line[]>([{ key: 1, product_id: "", quantity: "1" }]);
  const [party, setParty] = useState("");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [lastShipment, setLastShipment] = useState<Shipment | null>(null);

  const productsQ = useQuery({ queryKey: ["products"], queryFn: () => apiGet<Product[]>("/products") });
  const suppliersQ = useQuery({ queryKey: ["suppliers"], queryFn: () => apiGet<Supplier[]>("/suppliers") });

  const products = productsQ.isError ? [] : productsQ.data ?? [];
  const suppliers = suppliersQ.isError ? [] : suppliersQ.data ?? [];

  const detailed = useMemo(
    () =>
      lines.map((l) => {
        const product = products.find((p) => p.id === l.product_id);
        const qty = Number(l.quantity) || 0;
        return { line: l, product, qty, shortage: !!product && type === "KELUAR" && qty > product.current_stock };
      }),
    [lines, products, type],
  );

  const totalUnits = detailed.reduce((s, d) => s + d.qty, 0);
  const totalValue = detailed.reduce((s, d) => s + (d.product?.purchase_price ?? 0) * d.qty, 0);

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["products"] });
    void qc.invalidateQueries({ queryKey: ["transactions"] });
    void qc.invalidateQueries({ queryKey: ["shipments"] });
    void qc.invalidateQueries({ queryKey: ["queue"] });
    void qc.invalidateQueries({ queryKey: ["stats"] });
  };

  const resetForm = () => {
    setLines([emptyLine()]);
    setReference("");
    setNotes("");
    setParty("");
  };

  const errMsg = (e: unknown, fallback: string) =>
    e instanceof ApiError && typeof (e.body as { detail?: string })?.detail === "string"
      ? (e.body as { detail: string }).detail
      : fallback;

  // Inbound: one transaction per line (each product independent).
  const saveInbound = useMutation({
    mutationFn: async (payloads: TransactionCreate[]) => {
      const results: Transaction[] = [];
      for (const payload of payloads) results.push(await apiPost<Transaction>("/transactions", payload));
      return results;
    },
    onSuccess: (txs) => {
      invalidate();
      setLastShipment(null);
      resetForm();
      toast.success(`Stok masuk dicatat untuk ${txs.length} jenis barang`);
    },
    onError: (e) => toast.error(errMsg(e, "Gagal mencatat stok masuk")),
  });

  // Outbound: one shipment document (surat jalan) carrying many lines.
  const saveOutbound = useMutation({
    mutationFn: (payload: ShipmentCreate) => apiPost<Shipment>("/shipments", payload),
    onSuccess: (s) => {
      invalidate();
      setLastShipment(s);
      resetForm();
      toast.success(
        `${s.doc_no} tersimpan · antrian ${s.queue_no} · ${s.items.length} jenis barang`,
      );
    },
    onError: (e) => toast.error(errMsg(e, "Gagal mencatat pengeluaran barang")),
  });

  const submit = () => {
    const items = detailed
      .filter((d) => d.product && d.qty > 0)
      .map((d) => ({ product_id: d.line.product_id, quantity: d.qty }));

    if (items.length === 0) {
      toast.error("Pilih produk dan isi jumlah minimal 1");
      return;
    }
    if (type === "KELUAR") {
      const short = detailed.find((d) => d.shortage);
      if (short) {
        toast.error(`Stok ${short.product?.name} tidak cukup (tersedia ${short.product?.current_stock})`);
        return;
      }
      saveOutbound.mutate({ party, reference_no: reference, notes, items });
      return;
    }
    saveInbound.mutate(
      items.map((i) => ({
        product_id: i.product_id,
        type: "MASUK" as MovementType,
        quantity: i.quantity,
        party,
        reference_no: reference,
        notes,
      })),
    );
  };

  const pending = saveInbound.isPending || saveOutbound.isPending;

  return (
    <AppShell>
      <div className="animate-rise space-y-6">
        <div>
          <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
            Operasional Gudang
          </p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">
            Pencatatan Stok Masuk / Keluar
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Satu pengeluaran bisa memuat beberapa jenis barang dan menghasilkan satu surat jalan
            beserta nomor antrian pemuatan.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          <Card className="lg:col-span-8">
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

              <div className="space-y-3">
                <Label>Daftar Barang</Label>
                {detailed.map((d, idx) => (
                  <div key={d.line.key} className="space-y-1" data-testid="movement-item-row">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="min-w-52 flex-1">
                        <Select
                          value={d.line.product_id}
                          onValueChange={(v: string) =>
                            setLines(
                              lines.map((l) => (l.key === d.line.key ? { ...l, product_id: v } : l)),
                            )
                          }
                        >
                          <SelectTrigger data-testid={`form-movement-product-${idx}`}>
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
                                {p.name} — {p.sku} (stok {angka(p.current_stock)})
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <Input
                        className="w-28"
                        type="number"
                        min={1}
                        aria-label="Jumlah unit"
                        data-testid={`form-movement-quantity-${idx}`}
                        value={d.line.quantity}
                        onChange={(e) =>
                          setLines(
                            lines.map((l) =>
                              l.key === d.line.key ? { ...l, quantity: e.target.value } : l,
                            ),
                          )
                        }
                      />
                      <span className="w-16 text-xs text-muted-foreground">
                        {d.product?.unit ?? "—"}
                      </span>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Hapus item"
                        data-testid={`btn-remove-movement-item-${idx}`}
                        onClick={() =>
                          setLines(lines.length > 1 ? lines.filter((l) => l.key !== d.line.key) : lines)
                        }
                      >
                        <Trash2 className="size-4 text-red-400" />
                      </Button>
                    </div>
                    {d.product && (
                      <p
                        className={cn(
                          "pl-1 text-xs",
                          d.shortage ? "text-red-400" : "text-muted-foreground",
                        )}
                      >
                        Stok saat ini {angka(d.product.current_stock)} {d.product.unit}
                        {d.shortage ? " — jumlah melebihi stok tersedia" : ""}
                      </p>
                    )}
                  </div>
                ))}
                <Button
                  variant="outline"
                  size="sm"
                  data-testid="btn-add-movement-item"
                  onClick={() => setLines([...lines, emptyLine()])}
                >
                  <Plus className="size-4" /> Tambah Barang
                </Button>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
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
                  <Label htmlFor="m-ref">No. Referensi / PO</Label>
                  <Input
                    id="m-ref"
                    placeholder={type === "MASUK" ? "PO-2026-001" : "REF-001 (opsional)"}
                    data-testid="form-movement-reference"
                    value={reference}
                    onChange={(e) => setReference(e.target.value)}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="m-notes">Keterangan</Label>
                <Textarea
                  id="m-notes"
                  rows={2}
                  placeholder="Muat pagi — truk B 9021 XX..."
                  data-testid="form-movement-notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                />
              </div>

              <Button
                className="w-full"
                onClick={submit}
                disabled={pending}
                data-testid="btn-submit-movement"
              >
                <Save className="size-4" />
                {pending
                  ? "Menyimpan..."
                  : type === "KELUAR"
                    ? "Simpan & Buat Surat Jalan"
                    : "Simpan Stok Masuk"}
              </Button>

              {lastShipment && (
                <div
                  className="space-y-2 rounded-xl border border-border bg-secondary/40 p-3"
                  data-testid="last-shipment-print"
                >
                  <p className="text-xs text-muted-foreground">
                    {lastShipment.doc_no} tersimpan — No. Antrian{" "}
                    <span className="font-mono font-semibold text-foreground">
                      {lastShipment.queue_no}
                    </span>{" "}
                    · {lastShipment.items.length} jenis barang
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Link
                      to={`/print/surat-jalan?ids=${lastShipment.id}`}
                      target="_blank"
                      data-testid="btn-print-note-after-save"
                      className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors duration-150 hover:bg-secondary"
                    >
                      <Printer className="size-4" /> Surat Jalan (A4, 2 rangkap)
                    </Link>
                    <Link
                      to={`/print/bon-muat/${lastShipment.id}`}
                      target="_blank"
                      data-testid="btn-print-slip-after-save"
                      className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors duration-150 hover:bg-secondary"
                    >
                      <Receipt className="size-4" /> Bon Muat (80mm)
                    </Link>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="lg:col-span-4" data-testid="movement-preview-card">
            <CardHeader>
              <CardTitle className="text-lg">Ringkasan Transaksi</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Badge variant={type === "MASUK" ? "secondary" : "destructive"}>{type}</Badge>
              <dl className="space-y-3 text-sm">
                <div className="flex justify-between border-b border-border pb-2">
                  <dt className="text-muted-foreground">Jenis barang</dt>
                  <dd className="font-mono font-semibold" data-testid="preview-item-count">
                    {angka(detailed.filter((d) => d.product && d.qty > 0).length)}
                  </dd>
                </div>
                <div className="flex justify-between border-b border-border pb-2">
                  <dt className="text-muted-foreground">Total unit</dt>
                  <dd className="font-mono font-semibold" data-testid="preview-total-units">
                    {angka(totalUnits)}
                  </dd>
                </div>
                <div className="flex justify-between border-b border-border pb-2">
                  <dt className="text-muted-foreground">Estimasi nilai</dt>
                  <dd className="font-mono">{rupiah(totalValue)}</dd>
                </div>
              </dl>

              <div className="space-y-2 text-xs">
                {detailed
                  .filter((d) => d.product && d.qty > 0)
                  .map((d) => (
                    <div
                      key={d.line.key}
                      className="flex justify-between gap-2 border-b border-border/60 pb-1"
                    >
                      <span className="truncate">{d.product?.name}</span>
                      <span
                        className={cn(
                          "font-mono font-semibold",
                          type === "MASUK" ? "text-emerald-400" : "text-red-400",
                        )}
                      >
                        {type === "MASUK" ? "+" : "-"}
                        {angka(d.qty)} →{" "}
                        {angka(
                          type === "MASUK"
                            ? (d.product?.current_stock ?? 0) + d.qty
                            : (d.product?.current_stock ?? 0) - d.qty,
                        )}
                      </span>
                    </div>
                  ))}
                {detailed.every((d) => !d.product || d.qty <= 0) && (
                  <p className="text-muted-foreground">
                    Pilih barang untuk melihat perkiraan stok setelah transaksi.
                  </p>
                )}
              </div>

              {type === "KELUAR" && (
                <p className="rounded-lg border border-border bg-background/60 p-3 text-xs text-muted-foreground">
                  Menyimpan pengeluaran otomatis membuat 1 surat jalan (2 rangkap per lembar A4) dan
                  1 nomor antrian pemuatan untuk bon muat thermal.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
