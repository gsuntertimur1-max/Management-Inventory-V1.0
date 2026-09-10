import React, { useState } from 'react';
import { Search, Download, Printer } from 'lucide-react';
import { useData } from '../context/DataContext';
import { apiError, downloadApiFile } from '../lib/api';
import { formatNum, formatDate } from '../mock';
import { toast } from 'sonner';

const Riwayat = () => {
  const { transactions } = useData();
  const [q, setQ] = useState('');
  const [type, setType] = useState('SEMUA');
  const [kondisi, setKondisi] = useState('SEMUA');
  const [exporting, setExporting] = useState(false);

  const filtered = transactions.filter((t) => (type === 'SEMUA' || t.type === type) && (kondisi === 'SEMUA' || t.kondisi === kondisi) && (t.ref?.toLowerCase().includes(q.toLowerCase()) || t.product.toLowerCase().includes(q.toLowerCase()) || t.sku.toLowerCase().includes(q.toLowerCase()) || (t.penerima || '').toLowerCase().includes(q.toLowerCase())));
  const totalIn = transactions.filter((t) => t.type === 'MASUK').reduce((a, t) => a + t.change, 0);
  const totalOut = transactions.filter((t) => t.type === 'KELUAR').reduce((a, t) => a + t.change, 0);

  const exportCurrentMonth = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      await downloadApiFile('/export/transactions.xlsx', 'riwayat_transaksi.xlsx');
      toast.success('File Excel riwayat bulan ini berhasil diunduh');
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Audit Trail</div>
          <h1 className="font-display text-4xl font-bold">Riwayat Transaksi Stok</h1>
          <p className="text-[#8b93a1] mt-2">{filtered.length} transaksi ditampilkan</p>
        </div>
        <div className="flex gap-3">
          <div className="card-surface px-5 py-3"><div className="label-mono text-[9px] mb-1">Total Masuk</div><div className="font-mono text-2xl font-bold text-[#22c55e]">+{formatNum(totalIn)}</div></div>
          <div className="card-surface px-5 py-3"><div className="label-mono text-[9px] mb-1">Total Keluar</div><div className="font-mono text-2xl font-bold text-[#ef4444]">{formatNum(totalOut)}</div></div>
        </div>
      </div>

      <div className="card-surface p-6">
        <div className="flex flex-wrap gap-3 mb-4">
          <div className="relative flex-1 min-w-[240px]"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" /><input data-testid="riwayat-search-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari No. Ref, produk, SKU, pihak terkait..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
          <select data-testid="riwayat-type-filter" value={type} onChange={(e) => setType(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none"><option value="SEMUA">SEMUA</option><option value="MASUK">MASUK</option><option value="KELUAR">KELUAR</option></select>
          <select data-testid="riwayat-kondisi-filter" value={kondisi} onChange={(e) => setKondisi(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none"><option value="SEMUA">SEMUA</option><option value="BAIK">BAIK</option><option value="RUSAK">RUSAK</option></select>
          <button onClick={exportCurrentMonth} disabled={exporting} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24] disabled:opacity-60 disabled:cursor-wait"><Download size={15} /> {exporting ? 'Menyiapkan…' : 'Unduh Excel Bulan Ini'}</button>
        </div>
        <p className="text-xs text-[#6b7688] mb-4">Cetak surat jalan & bon muat ada di halaman Pengeluaran.</p>

        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['Waktu', 'No. Referensi', 'Antrian', 'Tipe', 'Kondisi', 'Produk', 'Perubahan', 'Pihak Terkait', 'Dicatat Oleh'].map((h) => <th key={h} className="py-2.5 pr-4 font-semibold whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {filtered.length === 0 ? <tr><td colSpan={9} className="py-8 text-center text-[#6b7688]">Belum ada transaksi. Muat data contoh atau catat transaksi baru.</td></tr> : filtered.map((t) => (
                <tr key={t.id} className="tbl-row border-b border-[#131a24]">
                  <td className="py-3 pr-4 whitespace-nowrap text-[#8b93a1]">{formatDate(t.time)}</td>
                  <td className="py-3 pr-4 font-mono text-xs">{t.ref}</td>
                  <td className="py-3 pr-4 font-mono text-xs">{t.antrian || '—'}</td>
                  <td className="py-3 pr-4"><span className="text-[10px] font-mono px-2 py-0.5 rounded" style={{ background: t.type === 'MASUK' ? 'rgba(34,197,94,.15)' : 'rgba(239,68,68,.15)', color: t.type === 'MASUK' ? '#22c55e' : '#ef4444' }}>{t.type}</span></td>
                  <td className="py-3 pr-4"><span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#1a222e] text-[#8b93a1]">{t.kondisi}</span></td>
                  <td className="py-3 pr-4"><div className="font-medium">{t.product}</div><div className="label-mono text-[10px]">{t.sku}</div></td>
                  <td className={`py-3 pr-4 font-mono font-semibold ${t.change > 0 ? 'text-[#22c55e]' : 'text-[#ef4444]'}`}>{t.change > 0 ? '+' : ''}{t.change}</td>
                  <td className="py-3 pr-4 text-[#c7d0dc]">{t.penerima}</td>
                  <td className="py-3 pr-4 text-[#8b93a1] text-xs">{t.operator}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default Riwayat;
