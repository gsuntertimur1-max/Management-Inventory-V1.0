import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Printer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiGet } from "@/lib/api";
import { angka, waktu } from "@/lib/format";
import type { AppSettings, Shipment } from "@/lib/types";

const THERMAL_STYLE = `@page { size: 80mm auto; margin: 0; }`;

export default function PrintLoadingSlip() {
  const { id = "" } = useParams();

  useEffect(() => {
    document.body.classList.add("print-thermal-mode");
    return () => document.body.classList.remove("print-thermal-mode");
  }, []);

  const shipmentQ = useQuery({
    queryKey: ["shipment", id],
    queryFn: () => apiGet<Shipment>(`/shipments/${id}`),
    enabled: id.length > 0,
  });
  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: () => apiGet<AppSettings>("/settings") });

  const s = shipmentQ.isError ? undefined : shipmentQ.data;
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
          to="/shipments"
          className="inline-flex items-center gap-2 text-sm font-medium text-neutral-800"
          data-testid="print-back-link"
        >
          <ArrowLeft className="size-4" /> Kembali
        </Link>
        <Button onClick={() => window.print()} data-testid="btn-print-loading-slip">
          <Printer className="size-4" /> Cetak Bon Muat
        </Button>
      </div>

      {!s ? (
        <p className="no-print text-center text-sm text-neutral-700" data-testid="print-empty">
          Data pengeluaran tidak ditemukan.
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
            <p className="text-[24pt] font-bold leading-none" data-testid="slip-queue-no">
              {s.queue_no || "-"}
            </p>
          </div>

          <div className="space-y-0.5 text-[8pt]">
            <p>Waktu : {waktu(s.created_at)}</p>
            <p>No. SJ: {s.doc_no}</p>
            <p>Ref   : {s.reference_no || "-"}</p>
            <p>Tujuan: {s.party || "-"}</p>
            <p>Status: {s.status}</p>
          </div>

          <div className="my-1 border-t border-dashed border-black pt-1 text-[8.5pt]">
            <p className="mb-1 font-bold uppercase">Daftar Muat</p>
            {s.items.map((item, idx) => (
              <div key={item.product_id} className="mb-1" data-testid="slip-item">
                <p className="font-bold">
                  {idx + 1}. {item.product_name}
                </p>
                <div className="flex justify-between">
                  <span>{item.product_sku}</span>
                  <span className="font-bold">
                    {angka(item.quantity)} {item.unit}
                  </span>
                </div>
              </div>
            ))}
            <div className="mt-1 flex justify-between border-t border-dashed border-black pt-1 text-[10pt] font-bold">
              <span>TOTAL MUAT</span>
              <span data-testid="slip-total-quantity">{angka(s.total_quantity)}</span>
            </div>
            <div className="flex justify-between text-[8pt]">
              <span>Jumlah jenis barang</span>
              <span>{s.items.length}</span>
            </div>
          </div>

          {s.notes && (
            <p className="border-t border-dashed border-black pt-1 text-[7.5pt]">Cat: {s.notes}</p>
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
