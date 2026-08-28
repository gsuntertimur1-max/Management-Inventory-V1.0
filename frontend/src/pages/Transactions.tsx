import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { FileSpreadsheet, Printer, Receipt, Search } from "lucide-react";
import AppShell from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
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
import { apiGet } from "@/lib/api";
import { angka, waktu } from "@/lib/format";
import { CATEGORIES } from "@/lib/types";
import type { Transaction } from "@/lib/types";

const RANGE_LABELS: Record<string, string> = {
  SEMUA: "Semua Waktu",
  "7": "7 Hari Terakhir",
  "30": "30 Hari Terakhir",
};

export default function Transactions() {
  const [search, setSearch] = useState("");
  const [type, setType] = useState("SEMUA");
  const [range, setRange] = useState("SEMUA");
  const [category, setCategory] = useState("SEMUA");
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));

  const txQ = useQuery({
    queryKey: ["transactions"],
    queryFn: () => apiGet<Transaction[]>("/transactions"),
  });
  const transactions = txQ.isError ? [] : txQ.data ?? [];

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const now = Date.now();
    return transactions.filter((t) => {
      if (type !== "SEMUA" && t.type !== type) return false;
      if (category !== "SEMUA" && t.category !== category) return false;
      if (range !== "SEMUA") {
        const days = Number(range);
        const created = new Date(t.created_at).getTime();
        if (Number.isFinite(created) && now - created > days * 86_400_000) return false;
      }
      if (q === "") return true;
      return (
        t.product_name.toLowerCase().includes(q) ||
        t.product_sku.toLowerCase().includes(q) ||
        t.reference_no.toLowerCase().includes(q) ||
        t.created_by_name.toLowerCase().includes(q) ||
        t.party.toLowerCase().includes(q)
      );
    });
  }, [transactions, search, type, range, category]);

  const totalIn = filtered.filter((t) => t.type === "MASUK").reduce((s, t) => s + t.quantity, 0);
  const totalOut = filtered.filter((t) => t.type === "KELUAR").reduce((s, t) => s + t.quantity, 0);



  return (
    <AppShell>
      <div className="animate-rise space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Audit Trail</p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">Riwayat Transaksi Stok</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {angka(filtered.length)} transaksi ditampilkan
            </p>
          </div>
          <div className="flex gap-3 text-sm">
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2">
              <p className="font-mono text-[10px] uppercase tracking-widest text-emerald-400">Total Masuk</p>
              <p className="font-mono text-lg font-bold text-emerald-400" data-testid="summary-total-in">
                +{angka(totalIn)}
              </p>
            </div>
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2">
              <p className="font-mono text-[10px] uppercase tracking-widest text-red-400">Total Keluar</p>
              <p className="font-mono text-lg font-bold text-red-400" data-testid="summary-total-out">
                -{angka(totalOut)}
              </p>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-3">
          <div className="relative min-w-60 flex-1">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              placeholder="Cari No. Ref, produk, SKU, pihak terkait, atau petugas..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              data-testid="transaction-search-input"
            />
          </div>
          <Select value={type} onValueChange={(v: string) => setType(v)}>
            <SelectTrigger className="w-44" data-testid="transaction-type-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="SEMUA">Semua Tipe</SelectItem>
              <SelectItem value="MASUK">Masuk Saja</SelectItem>
              <SelectItem value="KELUAR">Keluar Saja</SelectItem>
            </SelectContent>
          </Select>
          <Select value={range} onValueChange={(v: string) => setRange(v)}>
            <SelectTrigger className="w-48" data-testid="transaction-range-select">
              <SelectValue>{(v) => RANGE_LABELS[String(v)] ?? "Semua Waktu"}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="SEMUA">Semua Waktu</SelectItem>
              <SelectItem value="7">7 Hari Terakhir</SelectItem>
              <SelectItem value="30">30 Hari Terakhir</SelectItem>
            </SelectContent>
          </Select>
          <Select value={category} onValueChange={(v: string) => setCategory(v)}>
            <SelectTrigger className="w-56" data-testid="transaction-category-select">
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

        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-3">
          <span className="text-xs text-muted-foreground">
            Cetak surat jalan & bon muat ada di halaman <strong>Pengeluaran</strong>
          </span>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <Input
              type="month"
              className="w-40"
              aria-label="Bulan laporan"
              data-testid="report-month-input"
              value={month}
              onChange={(e) => setMonth(e.target.value)}
            />
            <a
              href={`/api/reports/transactions.xlsx?month=${month}`}
              data-testid="btn-export-transactions-month"
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors duration-150 hover:bg-secondary"
            >
              <FileSpreadsheet className="size-4" /> Unduh Excel Bulan Ini
            </a>
            <a
              href="/api/reports/transactions.xlsx"
              data-testid="btn-export-transactions-all"
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors duration-150 hover:bg-secondary"
            >
              <FileSpreadsheet className="size-4" /> Semua Periode
            </a>
          </div>
        </div>

        <Card className="overflow-hidden p-0">
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Waktu</TableHead>
                  <TableHead>No. Referensi</TableHead>
                  <TableHead>No. Antrian</TableHead>
                  <TableHead>Tipe</TableHead>
                  <TableHead>Produk</TableHead>
                  <TableHead className="text-right">Perubahan</TableHead>
                  <TableHead className="text-right">Stok Akhir</TableHead>
                  <TableHead>Pihak Terkait</TableHead>
                  <TableHead>Dicatat Oleh</TableHead>
                  <TableHead className="text-right">Cetak</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody data-testid="table-transactions-body">
                {filtered.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={10} className="py-10 text-center text-sm text-muted-foreground">
                      Belum ada transaksi yang cocok dengan filter.
                    </TableCell>
                  </TableRow>
                )}
                {filtered.map((t) => (
                  <TableRow key={t.id} data-testid="transaction-row">
                    <TableCell className="whitespace-nowrap text-xs">{waktu(t.created_at)}</TableCell>
                    <TableCell className="font-mono text-xs">{t.reference_no || "—"}</TableCell>
                    <TableCell className="font-mono text-xs">{t.queue_no || "—"}</TableCell>
                    <TableCell>
                      <Badge variant={t.type === "MASUK" ? "secondary" : "destructive"}>{t.type}</Badge>
                    </TableCell>
                    <TableCell>
                      <span className="block text-sm font-medium">{t.product_name}</span>
                      <span className="font-mono text-xs text-muted-foreground">{t.product_sku}</span>
                    </TableCell>
                    <TableCell
                      className={`text-right font-mono font-semibold ${
                        t.type === "MASUK" ? "text-emerald-400" : "text-red-400"
                      }`}
                    >
                      {t.type === "MASUK" ? "+" : "-"}
                      {angka(t.quantity)}
                    </TableCell>
                    <TableCell className="text-right font-mono">{angka(t.stock_after)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{t.party || "—"}</TableCell>
                    <TableCell className="text-xs" data-testid={`tx-recorded-by-${t.id}`}>
                      {t.created_by_name || <span className="text-muted-foreground">Sistem</span>}
                    </TableCell>
                    <TableCell className="text-right">
                      {t.type === "KELUAR" && t.shipment_id ? (
                        <div className="flex justify-end gap-1">
                          <Link
                            to={`/print/surat-jalan?ids=${t.shipment_id}`}
                            target="_blank"
                            aria-label="Cetak surat jalan"
                            data-testid={`btn-print-note-${t.id}`}
                            className="inline-flex size-8 items-center justify-center rounded-md hover:bg-secondary"
                          >
                            <Printer className="size-4" />
                          </Link>
                          <Link
                            to={`/print/bon-muat/${t.shipment_id}`}
                            target="_blank"
                            aria-label="Cetak bon muat thermal"
                            data-testid={`btn-print-slip-${t.id}`}
                            className="inline-flex size-8 items-center justify-center rounded-md hover:bg-secondary"
                          >
                            <Receipt className="size-4" />
                          </Link>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
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
