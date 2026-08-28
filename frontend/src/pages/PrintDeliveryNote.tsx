import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Printer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiGet } from "@/lib/api";
import { angka, tanggal, waktu } from "@/lib/format";
import type { AppSettings, Transaction } from "@/lib/types";

const A4_STYLE = `@page { size: A4 portrait; margin: 0; }`;

function Note({ tx, settings }: { tx: Transaction; settings: AppSettings }) {
  return (
    <div className="print-half flex flex-col border-b border-dashed border-black p-[10mm] text-[10pt] text-black">
      <div className="flex items-start justify-between border-b-2 border-black pb-2">
        <div>
          <p className="text-[13pt] font-bold uppercase leading-tight">{settings.company_name}</p>
          <p className="max-w-[95mm] text-[8pt] leading-snug">{settings.address}</p>
          <p className="text-[8pt]">
            Telp: {settings.phone} · {settings.email}
          </p>
        </div>
        <div className="text-right">
          <p className="text-[12pt] font-bold uppercase">Surat Jalan</p>
          <p className="text-[8pt]">No: {tx.reference_no || tx.queue_no || tx.id.slice(0, 8)}</p>
          <p className="text-[8pt]">Tanggal: {tanggal(tx.date)}</p>
          {tx.queue_no && <p className="text-[8pt]">No. Antrian: {tx.queue_no}</p>}
        </div>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-3 text-[8.5pt]">
        <div>
          <p className="font-semibold">Dikirim Kepada:</p>
          <p>{tx.party || "-"}</p>
        </div>
        <div>
          <p className="font-semibold">Keterangan:</p>
          <p className="line-clamp-2">{tx.notes || "-"}</p>
        </div>
      </div>

      <table className="mt-2 w-full border-collapse text-[9pt]">
        <thead>
          <tr>
            <th className="border border-black px-1 py-0.5 text-left">No</th>
            <th className="border border-black px-1 py-0.5 text-left">Nama Barang</th>
            <th className="border border-black px-1 py-0.5 text-left">Kode SKU</th>
            <th className="border border-black px-1 py-0.5 text-right">Jumlah</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="border border-black px-1 py-0.5">1</td>
            <td className="border border-black px-1 py-0.5">{tx.product_name}</td>
            <td className="border border-black px-1 py-0.5">{tx.product_sku}</td>
            <td className="border border-black px-1 py-0.5 text-right">{angka(tx.quantity)}</td>
          </tr>
        </tbody>
      </table>

      <p className="mt-1.5 text-[7.5pt] italic">{settings.footer_note}</p>

      <div className="mt-auto grid grid-cols-3 gap-2 pt-2 text-center text-[8pt]">
        <div>
          <p>Pengirim</p>
          <div className="mt-8 border-t border-black pt-0.5">Petugas Gudang</div>
        </div>
        <div>
          <p>Pengemudi</p>
          <div className="mt-8 border-t border-black pt-0.5">Nama & Tanda Tangan</div>
        </div>
        <div>
          <p>Penerima</p>
          <div className="mt-8 border-t border-black pt-0.5">{tx.party || "Nama & Tanda Tangan"}</div>
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

  const txQ = useQuery({
    queryKey: ["tx-by-ids", ids],
    queryFn: () => apiGet<Transaction[]>(`/transactions/by-ids?ids=${encodeURIComponent(ids)}`),
    enabled: ids.length > 0,
  });
  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: () => apiGet<AppSettings>("/settings") });

  const items = txQ.isError ? [] : txQ.data ?? [];
  const settings: AppSettings =
    (settingsQ.isError ? undefined : settingsQ.data) ?? {
      company_name: "GudangPro",
      address: "-",
      phone: "-",
      email: "-",
      footer_note: "",
    };

  // Two delivery notes per A4 sheet.
  const sheets: Transaction[][] = [];
  for (let i = 0; i < items.length; i += 2) sheets.push(items.slice(i, i + 2));

  return (
    <div className="min-h-screen bg-neutral-200 py-6 print:bg-white print:py-0">
      <style>{A4_STYLE}</style>

      <div className="no-print mx-auto mb-6 flex max-w-[210mm] items-center justify-between gap-3 px-4">
        <Link
          to="/transactions"
          className="inline-flex items-center gap-2 text-sm font-medium text-neutral-800"
          data-testid="print-back-link"
        >
          <ArrowLeft className="size-4" /> Kembali ke Riwayat
        </Link>
        <div className="flex items-center gap-3">
          <span className="text-sm text-neutral-700" data-testid="print-count">
            {items.length} surat jalan · {sheets.length} lembar A4
          </span>
          <Button onClick={() => window.print()} data-testid="btn-print-delivery-note">
            <Printer className="size-4" /> Cetak
          </Button>
        </div>
      </div>

      <div className="print-root mx-auto space-y-6 print:space-y-0">
        {items.length === 0 && (
          <p className="no-print text-center text-sm text-neutral-700" data-testid="print-empty">
            Tidak ada transaksi keluar yang dipilih untuk dicetak.
          </p>
        )}
        {sheets.map((pair, idx) => (
          <div
            key={idx}
            className="print-a4 print-sheet mx-auto bg-white shadow-lg print:shadow-none"
            data-testid="delivery-note-sheet"
          >
            {pair.map((tx) => (
              <Note key={tx.id} tx={tx} settings={settings} />
            ))}
            {pair.length === 1 && (
              <div className="print-half flex items-center justify-center text-[8pt] text-neutral-400">
                (bagian ini sengaja dikosongkan)
              </div>
            )}
          </div>
        ))}
      </div>

      <p className="no-print mt-6 text-center text-xs text-neutral-600">
        Dicetak pada {waktu(new Date().toISOString())} · 1 lembar A4 = 2 surat jalan
      </p>
    </div>
  );
}
