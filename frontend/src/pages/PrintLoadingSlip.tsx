import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Printer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiGet } from "@/lib/api";
import { angka, waktu } from "@/lib/format";
import type { AppSettings, Transaction } from "@/lib/types";

const THERMAL_STYLE = `@page { size: 80mm auto; margin: 0; }`;

export default function PrintLoadingSlip() {
  const { id = "" } = useParams();

  useEffect(() => {
    document.body.classList.add("print-thermal-mode");
    return () => document.body.classList.remove("print-thermal-mode");
  }, []);

  const txQ = useQuery({
    queryKey: ["tx-by-ids", id],
    queryFn: () => apiGet<Transaction[]>(`/transactions/by-ids?ids=${encodeURIComponent(id)}`),
    enabled: id.length > 0,
  });
  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: () => apiGet<AppSettings>("/settings") });

  const tx = (txQ.isError ? [] : txQ.data ?? [])[0];
  const settings: AppSettings =
    (settingsQ.isError ? undefined : settingsQ.data) ?? {
      company_name: "GudangPro",
      address: "-",
      phone: "-",
      email: "-",
      footer_note: "",
    };

  return (
    <div className="min-h-screen bg-neutral-200 py-6 print:bg-white print:py-0">
      <style>{THERMAL_STYLE}</style>

      <div className="no-print mx-auto mb-6 flex max-w-md items-center justify-between gap-3 px-4">
        <Link
          to="/transactions"
          className="inline-flex items-center gap-2 text-sm font-medium text-neutral-800"
          data-testid="print-back-link"
        >
          <ArrowLeft className="size-4" /> Kembali
        </Link>
        <Button onClick={() => window.print()} data-testid="btn-print-loading-slip">
          <Printer className="size-4" /> Cetak Bon Muat
        </Button>
      </div>

      {!tx ? (
        <p className="no-print text-center text-sm text-neutral-700" data-testid="print-empty">
          Data transaksi tidak ditemukan.
        </p>
      ) : (
        <div
          className="print-root print-thermal mx-auto bg-white px-[3mm] py-[4mm] font-mono text-[9pt] leading-tight text-black shadow-lg print:shadow-none"
          data-testid="loading-slip"
        >
          <div className="text-center">
            <p className="text-[11pt] font-bold uppercase">{settings.company_name}</p>
            <p className="text-[7pt] leading-snug">{settings.address}</p>
            <p className="text-[7pt]">Telp: {settings.phone}</p>
          </div>

          <p className="my-1 border-y border-dashed border-black py-1 text-center text-[10pt] font-bold uppercase">
            Bon Muat
          </p>

          <div className="my-2 border border-black py-1 text-center">
            <p className="text-[7pt] uppercase tracking-widest">Nomor Antrian</p>
            <p className="text-[22pt] font-bold leading-none" data-testid="slip-queue-no">
              {tx.queue_no || "-"}
            </p>
          </div>

          <div className="space-y-0.5 text-[8pt]">
            <p>Waktu : {waktu(tx.created_at)}</p>
            <p>No. SJ: {tx.reference_no || "-"}</p>
            <p>Tujuan: {tx.party || "-"}</p>
          </div>

          <div className="my-1 border-t border-dashed border-black pt-1 text-[8.5pt]">
            <p className="font-bold">{tx.product_name}</p>
            <p>SKU: {tx.product_sku}</p>
            <div className="mt-1 flex justify-between text-[10pt] font-bold">
              <span>JUMLAH MUAT</span>
              <span data-testid="slip-quantity">{angka(tx.quantity)}</span>
            </div>
            <div className="flex justify-between text-[8pt]">
              <span>Sisa stok gudang</span>
              <span>{angka(tx.stock_after)}</span>
            </div>
          </div>

          {tx.notes && (
            <p className="border-t border-dashed border-black pt-1 text-[7.5pt]">Cat: {tx.notes}</p>
          )}

          <div className="mt-3 grid grid-cols-2 gap-2 text-center text-[7pt]">
            <div>
              <p>Petugas</p>
              <div className="mt-6 border-t border-black pt-0.5">Gudang</div>
            </div>
            <div>
              <p>Pemuat</p>
              <div className="mt-6 border-t border-black pt-0.5">Sopir</div>
            </div>
          </div>

          <p className="mt-2 text-center text-[7pt]">--- Tunjukkan bon ini saat pemuatan ---</p>
        </div>
      )}
    </div>
  );
}
