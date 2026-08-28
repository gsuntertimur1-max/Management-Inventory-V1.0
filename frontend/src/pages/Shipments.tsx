import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Monitor, Plus, Printer, Receipt, Search } from "lucide-react";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
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
import { apiGet, apiPatch } from "@/lib/api";
import { angka, waktu } from "@/lib/format";
import type { Shipment, ShipmentStatus } from "@/lib/types";

const STATUS_VARIANT: Record<ShipmentStatus, "outline" | "default" | "secondary"> = {
  MENUNGGU: "outline",
  DIMUAT: "default",
  SELESAI: "secondary",
};

const STATUS_LABELS: Record<string, string> = {
  SEMUA: "Semua Status",
  MENUNGGU: "Menunggu",
  DIMUAT: "Sedang Dimuat",
  SELESAI: "Selesai",
};

export default function Shipments() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("SEMUA");
  const [selected, setSelected] = useState<string[]>([]);

  const shipmentsQ = useQuery({
    queryKey: ["shipments"],
    queryFn: () => apiGet<Shipment[]>("/shipments"),
  });
  const shipments = shipmentsQ.isError ? [] : shipmentsQ.data ?? [];

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return shipments.filter((s) => {
      if (status !== "SEMUA" && s.status !== status) return false;
      if (q === "") return true;
      return (
        s.doc_no.toLowerCase().includes(q) ||
        s.queue_no.toLowerCase().includes(q) ||
        s.party.toLowerCase().includes(q) ||
        s.reference_no.toLowerCase().includes(q) ||
        s.items.some(
          (i) => i.product_name.toLowerCase().includes(q) || i.product_sku.toLowerCase().includes(q),
        )
      );
    });
  }, [shipments, search, status]);

  const setStatusMut = useMutation({
    mutationFn: (vars: { id: string; status: ShipmentStatus }) =>
      apiPatch<Shipment>(`/shipments/${vars.id}/status`, { status: vars.status }),
    onSuccess: (s) => {
      void qc.invalidateQueries({ queryKey: ["shipments"] });
      void qc.invalidateQueries({ queryKey: ["queue"] });
      toast.success(`${s.doc_no} → ${STATUS_LABELS[s.status]}`);
    },
    onError: () => toast.error("Gagal memperbarui status pemuatan"),
  });

  const toggle = (id: string, on: boolean) =>
    setSelected((prev) => (on ? [...new Set([...prev, id])] : prev.filter((x) => x !== id)));

  const printSelected = () => {
    if (selected.length === 0) {
      toast.error("Pilih minimal satu surat jalan untuk dicetak");
      return;
    }
    window.open(`/print/surat-jalan?ids=${selected.join(",")}`, "_blank");
  };

  return (
    <AppShell>
      <div className="animate-rise space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              Pengiriman Barang
            </p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">
              Pengeluaran & Surat Jalan
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {angka(filtered.length)} surat jalan · setiap dokumen bisa memuat beberapa jenis barang
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              to="/antrian"
              target="_blank"
              data-testid="link-queue-display"
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors duration-150 hover:bg-secondary"
            >
              <Monitor className="size-4" /> Layar Antrian
            </Link>
            <Link
              to="/stock-movement"
              data-testid="link-new-shipment"
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground transition-transform duration-150 hover:-translate-y-0.5"
            >
              <Plus className="size-4" /> Pengeluaran Baru
            </Link>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-60 flex-1">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              placeholder="Cari No. SJ, antrian, penerima, atau barang..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              data-testid="shipment-search-input"
            />
          </div>
          <Select value={status} onValueChange={(v: string) => setStatus(v)}>
            <SelectTrigger className="w-48" data-testid="shipment-status-filter">
              <SelectValue>{(v) => STATUS_LABELS[String(v)] ?? "Semua Status"}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="SEMUA">Semua Status</SelectItem>
              <SelectItem value="MENUNGGU">Menunggu</SelectItem>
              <SelectItem value="DIMUAT">Sedang Dimuat</SelectItem>
              <SelectItem value="SELESAI">Selesai</SelectItem>
            </SelectContent>
          </Select>
          <Button onClick={printSelected} data-testid="btn-print-selected-delivery-notes">
            <Printer className="size-4" /> Cetak Surat Jalan ({selected.length})
          </Button>
          <span className="text-xs text-muted-foreground">A4 — 2 rangkap per lembar</span>
        </div>

        <Card className="overflow-hidden p-0">
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">
                    <Checkbox
                      aria-label="Pilih semua surat jalan"
                      data-testid="select-all-shipments"
                      checked={filtered.length > 0 && selected.length === filtered.length}
                      onCheckedChange={(v) => setSelected(v ? filtered.map((s) => s.id) : [])}
                    />
                  </TableHead>
                  <TableHead>No. Surat Jalan</TableHead>
                  <TableHead>Antrian</TableHead>
                  <TableHead>Waktu</TableHead>
                  <TableHead>Penerima</TableHead>
                  <TableHead>Barang</TableHead>
                  <TableHead className="text-right">Total Unit</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Aksi</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody data-testid="table-shipments-body">
                {filtered.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={9} className="py-10 text-center text-sm text-muted-foreground">
                      Belum ada pengeluaran barang.
                    </TableCell>
                  </TableRow>
                )}
                {filtered.map((s) => (
                  <TableRow key={s.id} data-testid={`shipment-row-${s.doc_no}`}>
                    <TableCell>
                      <Checkbox
                        aria-label={`Pilih ${s.doc_no}`}
                        data-testid={`select-shipment-${s.id}`}
                        checked={selected.includes(s.id)}
                        onCheckedChange={(v) => toggle(s.id, Boolean(v))}
                      />
                    </TableCell>
                    <TableCell className="font-mono text-xs font-semibold">{s.doc_no}</TableCell>
                    <TableCell className="font-mono text-sm font-bold text-primary">
                      {s.queue_no}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs">{waktu(s.created_at)}</TableCell>
                    <TableCell className="text-sm">{s.party || "—"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {s.items.map((i) => (
                        <span key={i.product_id} className="block">
                          {i.product_name} × {angka(i.quantity)} {i.unit}
                        </span>
                      ))}
                    </TableCell>
                    <TableCell className="text-right font-mono">{angka(s.total_quantity)}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[s.status]} data-testid={`shipment-status-${s.doc_no}`}>
                        {STATUS_LABELS[s.status]}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        {s.status === "MENUNGGU" && (
                          <Button
                            size="sm"
                            variant="outline"
                            data-testid={`btn-start-loading-${s.doc_no}`}
                            onClick={() => setStatusMut.mutate({ id: s.id, status: "DIMUAT" })}
                          >
                            Mulai Muat
                          </Button>
                        )}
                        {s.status === "DIMUAT" && (
                          <Button
                            size="sm"
                            variant="outline"
                            data-testid={`btn-finish-loading-${s.doc_no}`}
                            onClick={() => setStatusMut.mutate({ id: s.id, status: "SELESAI" })}
                          >
                            Selesai
                          </Button>
                        )}
                        <Link
                          to={`/print/surat-jalan?ids=${s.id}`}
                          target="_blank"
                          aria-label={`Cetak surat jalan ${s.doc_no}`}
                          data-testid={`btn-print-note-${s.doc_no}`}
                          className="inline-flex size-8 items-center justify-center rounded-md hover:bg-secondary"
                        >
                          <Printer className="size-4" />
                        </Link>
                        <Link
                          to={`/print/bon-muat/${s.id}`}
                          target="_blank"
                          aria-label={`Cetak bon muat ${s.doc_no}`}
                          data-testid={`btn-print-slip-${s.doc_no}`}
                          className="inline-flex size-8 items-center justify-center rounded-md hover:bg-secondary"
                        >
                          <Receipt className="size-4" />
                        </Link>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
