import React, { useMemo, useState } from 'react';
import { CalendarRange, Download, FileSpreadsheet } from 'lucide-react';
import { toast } from 'sonner';
import { apiError, downloadApiFile } from '../lib/api';

const iso = (date) => date.toISOString().slice(0, 10);

const LaporanOperasional = () => {
  const today = useMemo(() => new Date(), []);
  const first = useMemo(() => new Date(today.getFullYear(), today.getMonth(), 1), [today]);
  const [start, setStart] = useState(iso(first));
  const [end, setEnd] = useState(iso(today));
  const [busy, setBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);

  const download = async () => {
    if (!start || !end) return toast.error('Pilih periode laporan');
    if (end < start) return toast.error('Tanggal akhir tidak boleh lebih kecil dari tanggal awal');
    setBusy(true);
    try {
      await downloadApiFile(
        `/reports/operational.xlsx?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
        `laporan_operasional_${start}_${end}.xlsx`,
      );
      toast.success('Laporan operasional berhasil dibuat');
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setBusy(false);
    }
  };

  const downloadPdf = async () => {
    if (!start || !end) return toast.error('Pilih periode laporan');
    if (end < start) return toast.error('Tanggal akhir tidak boleh lebih kecil dari tanggal awal');
    setPdfBusy(true);
    try {
      await downloadApiFile(
        `/reports/operational.pdf?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
        `laporan_operasional_${start}_${end}.pdf`,
      );
      toast.success('PDF laporan berhasil dibuat');
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setPdfBusy(false);
    }
  };

  return <div className="space-y-6">
    <div>
      <div className="label-mono mb-2">Riwayat & Laporan</div>
      <h1 className="font-display text-4xl font-bold">Laporan Operasional</h1>
      
    </div>

    <div className="card-surface p-6 max-w-3xl">
      <div className="flex items-center gap-2 mb-5"><CalendarRange size={18} className="text-[#60a5fa]"/><h2 className="font-display text-xl font-bold">Periode Laporan</h2></div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <label className="text-sm">
          <span className="label-mono text-[9px]">Tanggal Mulai</span>
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="mt-2 w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" />
        </label>
        <label className="text-sm">
          <span className="label-mono text-[9px]">Tanggal Akhir</span>
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="mt-2 w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" />
        </label>
      </div>

      <div className="mt-5 rounded-xl border border-[#1f3657] bg-[#0d1728] p-4 text-sm text-[#93c5fd]">
        <div className="flex items-start gap-3"><FileSpreadsheet size={18} className="mt-0.5 shrink-0"/><div>
          <div className="font-semibold">Isi workbook</div>
          <div className="text-xs mt-1 text-[#7892b5]">Info periode · Transaksi · Pengeluaran/Bon/SJ · Stock Opname · Bazar/E-commerce. Filter tanggal memakai waktu operasional WIB.</div>
        </div></div>
      </div>

      <div className="mt-5 flex flex-col sm:flex-row gap-2">
        <button onClick={download} disabled={busy || pdfBusy} className="btn-primary w-full sm:w-auto inline-flex items-center justify-center gap-2 px-5 py-3 rounded-lg font-semibold disabled:opacity-60">
          <Download size={16}/>{busy ? 'Membuat XLSX...' : 'Unduh XLSX'}
        </button>
        <button onClick={downloadPdf} disabled={busy || pdfBusy} className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-5 py-3 rounded-lg border border-[#294263] text-[#93c5fd] font-semibold disabled:opacity-60">
          <Download size={16}/>{pdfBusy ? 'Membuat PDF...' : 'Unduh PDF'}
        </button>
      </div>
    </div>
  </div>;
};

export default LaporanOperasional;
