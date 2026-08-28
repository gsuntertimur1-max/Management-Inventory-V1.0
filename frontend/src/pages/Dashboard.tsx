import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Activity,
  ArrowDownLeft,
  ArrowUpRight,
  Coins,
  Layers,
  Package,
  Plus,
  Search,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import AppShell from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiGet } from "@/lib/api";
import { can, useAuth } from "@/lib/session";
import { angka, compactRupiah, rupiah, tanggal, waktu } from "@/lib/format";
import type { Product, Stats, Transaction } from "@/lib/types";

interface Kpi {
  id: string;
  title: string;
  subtitle: string;
  value: string;
  icon: typeof Package;
  tone: string;
}

export default function Dashboard() {
  const [stockSearch, setStockSearch] = useState("");
  const { role } = useAuth();
  const showMoney = can(role, "inventory:read");
  const canWrite = can(role, "inventory:write");

  const statsQ = useQuery({ queryKey: ["stats"], queryFn: () => apiGet<Stats>("/stats") });
  // Viewers may not read transaction history, so never fire the request for them.
  const txQ = useQuery({
    queryKey: ["transactions"],
    queryFn: () => apiGet<Transaction[]>("/transactions"),
    enabled: showMoney,
  });
  const productsQ = useQuery({ queryKey: ["products"], queryFn: () => apiGet<Product[]>("/products") });

  const stats = statsQ.isError ? undefined : statsQ.data;
  const recent = (txQ.isError ? [] : txQ.data ?? []).slice(0, 8);
  const products = productsQ.isError ? [] : productsQ.data ?? [];

  // Remaining stock per product, sorted A→Z by product name.
  const stockList = useMemo(() => {
    const q = stockSearch.trim().toLowerCase();
    return [...products]
      .filter(
        (p) => q === "" || p.name.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q),
      )
      .sort((a, b) => a.name.localeCompare(b.name, "id"));
  }, [products, stockSearch]);

  const kpis: Kpi[] = [
    {
      id: "stat-total-products",
      title: "Total Ragam Produk",
      subtitle: "SKU aktif terdaftar",
      value: stats ? angka(stats.total_products) : "—",
      icon: Package,
      tone: "text-blue-400 bg-blue-500/10",
    },
    {
      id: "stat-total-units",
      title: "Total Unit Fisik Stok",
      subtitle: "Kuantitas seluruh gudang",
      value: stats ? angka(stats.total_units) : "—",
      icon: Layers,
      tone: "text-indigo-400 bg-indigo-500/10",
    },
    ...(showMoney
      ? [
          {
            id: "stat-total-valuation",
            title: "Total Nilai Inventori",
            subtitle: "Harga modal × jumlah stok",
            value: stats ? compactRupiah(stats.total_valuation) : "—",
            icon: Coins,
            tone: "text-emerald-400 bg-emerald-500/10",
          },
        ]
      : []),
    {
      id: "stat-recent-movements",
      title: "Aktivitas 30 Hari",
      subtitle: "Unit masuk & keluar",
      value: stats ? angka(stats.recent_movements) : "—",
      icon: Activity,
      tone: "text-amber-400 bg-amber-500/10",
    },
  ];

  return (
    <AppShell>
      <div className="animate-rise space-y-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              Pusat Kendali Gudang
            </p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl lg:text-4xl">
              Ringkasan Penyimpanan Stok
            </h1>
            <p className="mt-2 max-w-xl text-sm text-muted-foreground sm:text-base">
              Pantau nilai aset inventori, perputaran barang, dan aktivitas terakhir gudang Anda.
            </p>
          </div>
          <div className="flex gap-2">
            {canWrite && (
              <>
                <Link
                  to="/import"
                  data-testid="dashboard-import-link"
                  className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors duration-150 hover:bg-secondary"
                >
                  <Plus className="size-4" /> Import Data SKU
                </Link>
                <Link
                  to="/products"
                  data-testid="dashboard-add-product-link"
                  className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors duration-150 hover:bg-secondary"
                >
                  <Plus className="size-4" /> Tambah Produk
                </Link>
              </>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 sm:gap-6">
          {kpis.map((k) => (
            <Card
              key={k.id}
              data-testid={k.id}
              className="border-border/80 transition-transform duration-150 hover:-translate-y-0.5"
            >
              <CardContent className="space-y-3 pt-1">
                <div className="flex items-start justify-between">
                  <span className={`grid size-9 place-items-center rounded-lg ${k.tone}`}>
                    <k.icon className="size-4.5" />
                  </span>
                </div>
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                    {k.title}
                  </p>
                  <p className="mt-1 text-2xl font-bold tracking-tight">{k.value}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{k.subtitle}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        <Card data-testid="stock-per-product-card">
          <CardHeader>
            <CardTitle className="text-lg">Sisa Stok per Barang (A → Z)</CardTitle>
            <div className="relative mt-3 max-w-sm">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                placeholder="Cari nama barang atau SKU..."
                value={stockSearch}
                onChange={(e) => setStockSearch(e.target.value)}
                data-testid="dashboard-stock-search"
              />
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <div className="max-h-[28rem] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nama Barang</TableHead>
                    <TableHead>SKU</TableHead>
                    <TableHead>Kategori</TableHead>
                    <TableHead className="text-right">Sisa Stok</TableHead>
                    {showMoney && <TableHead className="text-right">Nilai Stok</TableHead>}
                    <TableHead>Lokasi</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody data-testid="dashboard-stock-body">
                  {stockList.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={showMoney ? 6 : 5} className="py-10 text-center text-sm text-muted-foreground">
                        Belum ada produk terdaftar. Tambah produk atau import data SKU.
                      </TableCell>
                    </TableRow>
                  )}
                  {stockList.map((p) => (
                    <TableRow key={p.id} data-testid={`dashboard-stock-row-${p.sku}`}>
                      <TableCell className="font-medium">{p.name}</TableCell>
                      <TableCell className="font-mono text-xs">{p.sku}</TableCell>
                      <TableCell>
                        <Badge variant="secondary">{p.category}</Badge>
                      </TableCell>
                      <TableCell
                        className="text-right font-mono font-semibold"
                        data-testid={`dashboard-stock-value-${p.sku}`}
                      >
                        {angka(p.current_stock)} {p.unit}
                      </TableCell>
                      {showMoney && (
                        <TableCell className="text-right font-mono text-xs text-muted-foreground">
                          {rupiah(p.purchase_price * p.current_stock)}
                        </TableCell>
                      )}
                      <TableCell className="text-xs text-muted-foreground">
                        {p.location || "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          <Card className="lg:col-span-7" data-testid="chart-timeline-card">
            <CardHeader>
              <CardTitle className="text-lg">Perputaran 7 Hari Terakhir</CardTitle>
            </CardHeader>
            <CardContent className="h-72">
              {stats && stats.timeline.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={stats.timeline}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" vertical={false} />
                    <XAxis
                      dataKey="date"
                      tickFormatter={(v: string) => v.slice(5)}
                      stroke="#64748B"
                      fontSize={11}
                    />
                    <YAxis stroke="#64748B" fontSize={11} />
                    <Tooltip
                      contentStyle={{ background: "#111827", border: "1px solid #1E293B", borderRadius: 8 }}
                      labelFormatter={(v) => tanggal(String(v))}
                    />
                    <Area type="monotone" dataKey="masuk" stroke="#10B981" fill="#10B98133" name="Masuk" />
                    <Area type="monotone" dataKey="keluar" stroke="#EF4444" fill="#EF444433" name="Keluar" />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <p className="pt-10 text-center text-sm text-muted-foreground">
                  Belum ada data perputaran. Muat data contoh atau catat transaksi.
                </p>
              )}
            </CardContent>
          </Card>

          <Card className="lg:col-span-5" data-testid="chart-category-card">
            <CardHeader>
              <CardTitle className="text-lg">Stok per Kategori</CardTitle>
            </CardHeader>
            <CardContent className="h-72">
              {stats && stats.by_category.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={stats.by_category} layout="vertical" margin={{ left: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" horizontal={false} />
                    <XAxis type="number" stroke="#64748B" fontSize={11} />
                    <YAxis
                      type="category"
                      dataKey="category"
                      width={92}
                      stroke="#64748B"
                      fontSize={10}
                      tickFormatter={(v: string) => v.split(" ")[0]}
                    />
                    <Tooltip
                      contentStyle={{ background: "#111827", border: "1px solid #1E293B", borderRadius: 8 }}
                    />
                    <Bar dataKey="units" fill="#3B82F6" radius={[0, 6, 6, 0]} name="Unit" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="pt-10 text-center text-sm text-muted-foreground">
                  Belum ada produk terdaftar.
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        {showMoney && (
        <Card data-testid="recent-activity-card">
          <CardHeader>
            <CardTitle className="text-lg">Aktivitas Terakhir</CardTitle>
          </CardHeader>
          <CardContent className="divide-y divide-border">
            {recent.length === 0 && (
              <p className="py-6 text-center text-sm text-muted-foreground">
                Belum ada transaksi tercatat.
              </p>
            )}
            {recent.map((t) => (
              <div key={t.id} className="flex flex-wrap items-center gap-3 py-3" data-testid="recent-activity-row">
                <span
                  className={`grid size-8 place-items-center rounded-lg ${
                    t.type === "MASUK" ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"
                  }`}
                >
                  {t.type === "MASUK" ? (
                    <ArrowDownLeft className="size-4" />
                  ) : (
                    <ArrowUpRight className="size-4" />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{t.product_name}</p>
                  <p className="font-mono text-xs text-muted-foreground">
                    {t.product_sku} · {waktu(t.created_at)}
                  </p>
                </div>
                <Badge variant={t.type === "MASUK" ? "secondary" : "destructive"}>{t.type}</Badge>
                <span
                  className={`w-20 text-right font-mono text-sm font-semibold ${
                    t.type === "MASUK" ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {t.type === "MASUK" ? "+" : "-"}
                  {angka(t.quantity)}
                </span>
                <span className="hidden w-28 text-right text-xs text-muted-foreground sm:block">
                  Sisa {angka(t.stock_after)}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
        )}
      </div>
    </AppShell>
  );
}
