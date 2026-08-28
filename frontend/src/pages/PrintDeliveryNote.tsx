import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Printer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiGet } from "@/lib/api";
import { angka, tanggal } from "@/lib/format";
import type { AppSettings, Shipment } from "@/lib/types";

const A4_STYLE = `@page { size: A4 portrait; margin: 0; }`;

const COPY_LABELS = ["Rangkap 1 — Untuk Penerima", "Rangkap 2 — Untuk Arsip Gudang"];

/** One copy (rangkap) of a delivery note — half of an A4 sheet. */
function NoteCopy({
  shipment,
  settings,
  copyLabel,
}: {
  shipment: Shipment;
  settings: AppSettings;
  copyLabel: string;
}) {
  return (
    <div className="print-half flex flex-col border-b border-dashed border-black px-[10mm] py-[6mm] text-[9.5pt] text-black">
      <div className="flex items-start justify-between border-b-2 border-black pb-1.5">
        <div>
          <p className="text-[12.5pt] font-bold uppercase leading-tight">{settings.company_name}</p>
          <p className="max-w-[95mm] text-[7.5pt] leading-snug">{settings.address}</p>
          <p className="text-[7.5pt]">
            Telp: {settings.phone} · {settings.email}
          </p>
        </div>
        <div className="text-right">
          <p className="text-[12pt] font-bold uppercase">Surat Jalan</p>
          <p className="text-[8pt]">No: {shipment.doc_no}</p>
          <p className="text-[8pt]">Tanggal: {tanggal(shipment.date)}</p>
          <p className="text-[8pt] font-semibold">No. Antrian: {shipment.queue_no}</p>
        </div>
      </div>

      <p className="mt-1 text-[7pt] font-semibold uppercase tracking-wider">{copyLabel}</p>

      <div className="mt-1 grid grid-cols-2 gap-3 text-[8pt]">
        <div>
          <p className="font-semibold">Dikirim Kepada:</p>
          <p>{shipment.party || "-"}</p>
        </div>
        <div>
          <p className="font-semibold">No. Referensi / Keterangan:</p>
          <p className="line-clamp-2">
            {shipment.reference_no}
            {shipment.notes ? ` · ${shipment.notes}` : ""}
          </p>
        </div>
      </div>

      <table className="mt-1.5 w-full border-collapse text-[8.5pt]">
        <thead>
          <tr>
            <th className="w-8 border border-black px-1 py-0.5 text-left">No</th>
            <th className="border border-black px-1 py-0.5 text-left">Nama Barang</th>
            <th className="border border-black px-1 py-0.5 text-left">Kode SKU</th>
            <th className="border border-black px-1 py-0.5 text-right">Jumlah</th>
            <th className="border border-black px-1 py-0.5 text-left">Satuan</th>
          </tr>
        </thead>
        <tbody>
          {shipment.items.map((item, idx) => (
            <tr key={item.product_id}>
              <td className="border border-black px-1 py-0.5">{idx + 1}</td>
              <td className="border border-black px-1 py-0.5">{item.product_name}</td>
              <td className="border border-black px-1 py-0.5">{item.product_sku}</td>
              <td className="border border-black px-1 py-0.5 text-right">{angka(item.quantity)}</td>
              <td className="border border-black px-1 py-0.5">{item.unit}</td>
            </tr>
          ))}
          <tr>
            <td className="border border-black px-1 py-0.5 font-semibold" colSpan={3}>
              Total ({shipment.items.length} jenis barang)
            </td>
            <td className="border border-black px-1 py-0.5 text-right font-semibold">
              {angka(shipment.total_quantity)}
            </td>
            <td className="border border-black px-1 py-0.5" />
          </tr>
        </tbody>
      </table>

      <p className="mt-1 text-[7pt] italic">{settings.footer_note}</p>

      <div className="mt-auto grid grid-cols-2 gap-8 pt-1.5 text-center text-[8pt]">
        <div>
          <p>Pengirim</p>
          <div className="mt-7 border-t border-black pt-0.5">Petugas Gudang</div>
        </div>
        <div>
          <p>Penerima</p>
          <div className="mt-7 border-t border-black pt-0.5">{shipment.party || "Nama & Tanda Tangan"}</div>
        </div>
      </div>
    </div>
  );
}

export default function PrintDeliveryNote() {
  const [params] = useSearchParams();
  const ids = params.get("ids") ?? "";

  useEffect(() => {
    document.body.classList.add("print-a4-mode");
    return () => document.body.classList.remove("print-a4-mode");
  }, []);

  const shipmentsQ = useQuery({
    queryKey: ["shipments-by-ids", ids],
    queryFn: () => apiGet<Shipment[]>(`/shipments/by-ids?ids=${encodeURIComponent(ids)}`),
    enabled: ids.length > 0,
  });
  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: () => apiGet<AppSettings>("/settings") });

  const shipments = shipmentsQ.isError ? [] : shipmentsQ.data ?? [];
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
      <style>{A4_STYLE}</style>

      <div className="no-print mx-auto mb-6 flex max-w-[210mm] items-center justify-between gap-3 px-4">
        <Link
          to="/shipments"
          className="inline-flex items-center gap-2 text-sm font-medium text-neutral-800"
          data-testid="print-back-link"
        >
          <ArrowLeft className="size-4" /> Kembali ke Pengeluaran
        </Link>
        <div className="flex items-center gap-3">
          <span className="text-sm text-neutral-700" data-testid="print-count">
            {shipments.length} surat jalan · {shipments.length} lembar A4 (2 rangkap per lembar)
          </span>
          <Button onClick={() => window.print()} data-testid="btn-print-delivery-note">
            <Printer className="size-4" /> Cetak
          </Button>
        </div>
      </div>

      <div className="print-root mx-auto space-y-6 print:space-y-0">
        {shipments.length === 0 && (
          <p className="no-print text-center text-sm text-neutral-700" data-testid="print-empty">
            Tidak ada surat jalan yang dipilih untuk dicetak.
          </p>
        )}
        {/* One A4 sheet per shipment, containing the SAME note twice (2 rangkap). */}
        {shipments.map((s) => (
          <div
            key={s.id}
            className="print-a4 print-sheet mx-auto bg-white shadow-lg print:shadow-none"
            data-testid="delivery-note-sheet"
          >
            {COPY_LABELS.map((label) => (
              <NoteCopy key={label} shipment={s} settings={settings} copyLabel={label} />
            ))}
          </div>
        ))}
      </div>

      <p className="no-print mt-6 text-center text-xs text-neutral-600">
        1 lembar A4 = 2 rangkap surat jalan yang sama (penerima & arsip gudang)
      </p>
    </div>
  );
}
