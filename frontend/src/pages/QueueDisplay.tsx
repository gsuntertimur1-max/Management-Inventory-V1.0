import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowLeft, PackageCheck, Truck } from "lucide-react";
import { apiGet } from "@/lib/api";
import { angka } from "@/lib/format";
import type { Shipment } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Warehouse floor display — drivers watch this for their loading queue number. */
export default function QueueDisplay() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const queueQ = useQuery({
    queryKey: ["queue"],
    queryFn: () => apiGet<Shipment[]>("/shipments/queue"),
    refetchInterval: 5000,
  });

  const queue = queueQ.isError ? [] : queueQ.data ?? [];
  const loading = queue.filter((s) => s.status === "DIMUAT");
  const waiting = queue.filter((s) => s.status === "MENUNGGU");
  const current = loading[0];

  return (
    <div className="min-h-screen bg-[#070B12] text-white">
      <div
        className="pointer-events-none fixed inset-x-0 top-0 h-96 opacity-70"
        style={{
          background:
            "radial-gradient(60% 100% at 50% 0%, rgba(37,99,235,0.25) 0%, rgba(7,11,18,0) 70%)",
        }}
      />

      <header className="relative flex flex-wrap items-center justify-between gap-4 border-b border-white/10 px-6 py-5 sm:px-10">
        <div className="flex items-center gap-4">
          <span className="grid size-12 place-items-center rounded-xl bg-primary shadow-lg shadow-primary/30">
            <Truck className="size-6" />
          </span>
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-blue-300">
              Layar Antrian Pemuatan
            </p>
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Antrian Gudang</h1>
          </div>
        </div>
        <div className="text-right">
          <p className="font-mono text-3xl font-bold tabular-nums sm:text-4xl" data-testid="queue-clock">
            {now.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </p>
          <p className="text-sm text-white/60">
            {now.toLocaleDateString("id-ID", {
              weekday: "long",
              day: "numeric",
              month: "long",
              year: "numeric",
            })}
          </p>
        </div>
        <Link
          to="/shipments"
          className="no-print absolute right-4 top-1 inline-flex items-center gap-1 text-xs text-white/40 hover:text-white/80"
          data-testid="queue-back-link"
        >
          <ArrowLeft className="size-3" /> panel
        </Link>
      </header>

      <main className="relative grid grid-cols-1 gap-6 px-6 py-8 sm:px-10 lg:grid-cols-12">
        {/* Now loading */}
        <section className="lg:col-span-5" data-testid="queue-now-loading">
          <p className="font-mono text-xs uppercase tracking-[0.3em] text-emerald-300">
            Sedang Dimuat
          </p>
          {current ? (
            <div className="mt-4 rounded-3xl border border-emerald-400/30 bg-emerald-400/10 p-8 shadow-2xl">
              <p
                className="font-mono text-[64pt] font-bold leading-none text-emerald-300 sm:text-[86pt]"
                data-testid="queue-current-number"
              >
                {current.queue_no}
              </p>
              <p className="mt-4 text-2xl font-semibold" data-testid="queue-current-party">
                {current.party || "—"}
              </p>
              <p className="mt-1 font-mono text-sm text-white/60">{current.doc_no}</p>
              <div className="mt-5 space-y-1 border-t border-white/10 pt-4 text-sm text-white/80">
                {current.items.map((i) => (
                  <p key={i.product_id} className="flex justify-between gap-4">
                    <span className="truncate">{i.product_name}</span>
                    <span className="font-mono font-semibold">
                      {angka(i.quantity)} {i.unit}
                    </span>
                  </p>
                ))}
                <p className="flex justify-between gap-4 border-t border-white/10 pt-2 font-semibold">
                  <span>Total</span>
                  <span className="font-mono">{angka(current.total_quantity)}</span>
                </p>
              </div>
            </div>
          ) : (
            <div className="mt-4 rounded-3xl border border-white/10 bg-white/5 p-10 text-center">
              <PackageCheck className="mx-auto size-10 text-white/30" />
              <p className="mt-3 text-lg text-white/60" data-testid="queue-idle">
                Tidak ada pemuatan berjalan
              </p>
            </div>
          )}

          {loading.length > 1 && (
            <p className="mt-3 text-sm text-white/50">
              +{loading.length - 1} dermaga lain juga sedang memuat
            </p>
          )}
        </section>

        {/* Waiting list */}
        <section className="lg:col-span-7" data-testid="queue-waiting-list">
          <div className="flex items-baseline justify-between">
            <p className="font-mono text-xs uppercase tracking-[0.3em] text-amber-300">
              Menunggu Antrian
            </p>
            <p className="font-mono text-sm text-white/50" data-testid="queue-waiting-count">
              {angka(waiting.length)} kendaraan
            </p>
          </div>

          <div className="mt-4 space-y-3">
            {waiting.length === 0 && (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-8 text-center text-white/60">
                Antrian kosong — semua pengeluaran sudah diproses.
              </div>
            )}
            {waiting.slice(0, 8).map((s, idx) => (
              <div
                key={s.id}
                data-testid="queue-waiting-row"
                className={cn(
                  "flex flex-wrap items-center gap-4 rounded-2xl border p-4 transition-colors duration-200",
                  idx === 0
                    ? "border-amber-400/40 bg-amber-400/10"
                    : "border-white/10 bg-white/5",
                )}
              >
                <p className="font-mono text-4xl font-bold tabular-nums text-amber-200">
                  {s.queue_no}
                </p>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-lg font-semibold">{s.party || "—"}</p>
                  <p className="truncate font-mono text-xs text-white/50">
                    {s.doc_no} · {s.items.length} jenis barang
                  </p>
                </div>
                <p className="font-mono text-xl font-semibold text-white/80">
                  {angka(s.total_quantity)} unit
                </p>
                {idx === 0 && (
                  <span className="rounded-full bg-amber-400/20 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-amber-200">
                    Berikutnya
                  </span>
                )}
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="relative px-6 pb-8 text-center text-xs text-white/40 sm:px-10">
        Layar diperbarui otomatis setiap 5 detik · Sopir menunggu nomor antrian dipanggil
      </footer>
    </div>
  );
}
