import { Link, useLocation } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ArrowLeftRight,
  Boxes,
  ClipboardList,
  History,
  LayoutDashboard,
  RefreshCw,
  Settings as SettingsIcon,
  Truck,
  Warehouse,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/sonner";
import { apiPost } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAV = [
  { name: "Dashboard", path: "/", icon: LayoutDashboard, testid: "nav-dashboard-link" },
  { name: "Daftar Produk", path: "/products", icon: Boxes, testid: "nav-products-link" },
  { name: "Catat Stok", path: "/stock-movement", icon: ArrowLeftRight, testid: "nav-stock-movement-link" },
  { name: "Riwayat", path: "/transactions", icon: History, testid: "nav-transactions-link" },
  { name: "Purchase Order", path: "/purchase-orders", icon: ClipboardList, testid: "nav-purchase-orders-link" },
  { name: "Supplier", path: "/suppliers", icon: Truck, testid: "nav-suppliers-link" },
  { name: "Pengaturan", path: "/settings", icon: SettingsIcon, testid: "nav-settings-link" },
];

interface SeedResult {
  ok: boolean;
  products: number;
  suppliers: number;
  transactions: number;
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation();
  const qc = useQueryClient();

  const seed = useMutation({
    mutationFn: () => apiPost<SeedResult>("/seed"),
    onSuccess: (res) => {
      void qc.invalidateQueries();
      toast.success(`Data contoh dimuat: ${res.products} produk, ${res.transactions} transaksi`);
    },
    onError: () => toast.error("Gagal memuat data contoh"),
  });

  return (
    <div className="min-h-screen bg-background">
      <div
        className="pointer-events-none fixed inset-x-0 top-0 h-72 opacity-60"
        style={{
          background:
            "radial-gradient(70% 100% at 15% 0%, rgba(37,99,235,0.22) 0%, rgba(11,15,23,0) 70%)",
        }}
      />
      <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-4 px-4 py-3 sm:px-6">
          <Link to="/" className="flex items-center gap-2.5" data-testid="brand-link">
            <span className="grid size-9 place-items-center rounded-lg bg-primary text-primary-foreground shadow-lg shadow-primary/25">
              <Warehouse className="size-5" />
            </span>
            <span className="leading-tight">
              <span className="block text-base font-bold tracking-tight">GudangPro</span>
              <span className="block font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                Manajemen Stok
              </span>
            </span>
          </Link>

          <nav className="order-3 flex w-full flex-wrap items-center gap-1 lg:order-2 lg:w-auto lg:flex-1 lg:pl-6">
            {NAV.map((item) => {
              const active = pathname === item.path;
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  data-testid={item.testid}
                  className={cn(
                    "flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-150",
                    active
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-secondary hover:text-foreground",
                  )}
                >
                  <item.icon className="size-4" />
                  {item.name}
                </Link>
              );
            })}
          </nav>

          <div className="order-2 ml-auto flex items-center gap-2 lg:order-3">
            <Button
              variant="outline"
              size="sm"
              data-testid="btn-seed-data"
              disabled={seed.isPending}
              onClick={() => seed.mutate()}
            >
              <RefreshCw className={cn("size-4", seed.isPending && "animate-spin")} />
              <span className="hidden sm:inline">Muat Data Contoh</span>
            </Button>
            <Link
              to="/stock-movement"
              data-testid="btn-quick-movement"
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground shadow-lg shadow-primary/25 transition-transform duration-150 hover:-translate-y-0.5"
            >
              <ArrowLeftRight className="size-4" />
              Catat Transaksi
            </Link>
          </div>
        </div>
      </header>

      <main className="relative mx-auto max-w-7xl px-4 py-8 sm:px-6">{children}</main>
      <Toaster position="top-right" richColors />
    </div>
  );
}
