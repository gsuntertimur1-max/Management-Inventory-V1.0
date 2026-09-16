import React, { useState } from 'react';
import { Search, Download } from 'lucide-react';
import { useData } from '../context/DataContext';
import { apiError, downloadApiFile } from '../lib/api';
import { formatNum, formatDate } from '../mock';
import { toast } from 'sonner';
import { packagingText, totalWeight } from '../lib/packaging';

const typeBadge = (type) => {
  if (type === 'MASUK') return { background: 'rgba(34,197,94,.15)', color: '#22c55e' };
  if (type === 'KELUAR') return { background: 'rgba(239,68,68,.15)', color: '#ef4444' };
  if (type === 'KOREKSI') return { background: 'rgba(245,158,11,.15)', color: '#f59e0b' };
  if (type === 'PENYESUAIAN') return { background: 'rgba(59,130,246,.15)', color: '#60a5fa' };
  return { background: 'rgba(148,163,184,.15)', color: '#94a3b8' };
};

const transactionChannel = (transaction) => {
  if (transaction.channel) return transaction.channel;
  return transaction.type === 'KOREKSI' ? '' : 'KOM';
};

const Riwayat = () => {
  const { transactions } = useData();
  const [q, setQ] = useState('');
  const [type, setType] = useState('SEMUA');
  const [kondisi, setKondisi] = useState('SEMUA');
  const [channel, setChannel] = useState('SEMUA');
  const [exporting, setExporting] = useState(false);

  const filtered = transactions.filter((t) => {
    const query = q.toLowerCase();
    const auditChannel = transactionChannel(t);
    return (type === 'SEMUA' || t.type === type)
      && (kondisi === 'SEMUA' || t.kondisi === kondisi)
      && (channel === 'SEMUA' || auditChannel === channel)
      && (
        (t.ref || '').toLowerCase().includes(query)
        || (t.po_no || '').toLowerCase().includes(query)
        || (t.product || '').toLowerCase().includes(query)
        || (t.sku || '').toLowerCase().includes(query)
        || (t.penerima || '').toLowerCase().includes(query)
        || (t.correction_reason || '').toLowerCase().includes(query)
      );
  });
  const totalIn = transactions.filter((t) => t.type === 'MASUK' && !t.voided).reduce((a, t) => a + Number(t.change || 0), 0);
  const totalOut = transactions.filter((t) => t.type === 'KELUAR' && !t.voided).reduce((a, t) => a + Number(t.change || 0), 0);
  const totalCorrections = transactions.filter((t) => t.type === 'KOREKSI').length;

  const exportCurrentMonth = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      await downloadApiFile('/export/transactions-v2.xlsx', 'riwayat_transaksi.xlsx');
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
        <div className="flex flex-wrap gap-3">
          <div className="card-surface px-5 py-3"><div className="label-mono text-[9px] mb-1">Masuk Aktif</div><div className="font-mono text-2xl font-bold text-[#22c55e]">+{formatNum(totalIn)}</div></div>
          <div className="card-surface px-5 py-3"><div className="label-mono text-[9px] mb-1">Total Keluar</div><div className="font-mono text-2xl font-bold text-[#ef4444]">{formatNum(totalOut)}</div></div>
          <div className="card-surface px-5 py-3"><div className="label-mono text-[9px] mb-1">Koreksi Audit</div><div className="font-mono text-2xl font-bold text-[#f59e0b]">{formatNum(totalCorrections)}</div></div>
        </div>
      </div>

      <div className="card-surface p-6">
        <div className="flex flex-wrap gap-3 mb-4">
          <div className="relative flex-1 min-w-[240px]"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" /><input data-testid="riwayat-search-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari No. Ref/PO, produk, SKU, pihak terkait, alasan koreksi..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
          <select data-testid="riwayat-type-filter" value={type} onChange={(e) => setType(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none"><option value="SEMUA">SEMUA TIPE</option><option value="MASUK">MASUK</option><option value="KELUAR">KELUAR</option><option value="PENYESUAIAN">PENYESUAIAN</option><option value="KOREKSI">KOREKSI</option></select>
          <select value={channel} onChange={(e) => setChannel(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none"><option value="SEMUA">Semua Saluran</option><option value="PSO">PSO</option><option value="KOM">KOM</option></select>
          <select data-testid="riwayat-kondisi-filter" value={kondisi} onChange={(e) => setKondisi(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none"><option value="SEMUA">SEMUA KONDISI</option><option value="BAIK">BAIK</option><option value="RUSAK">RUSAK</option><option value="DOKUMEN">DOKUMEN</option></select>
          <button onClick={exportCurrentMonth} disabled={exporting} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24] disabled:opacity-60 disabled:cursor-wait"><Download size={15} /> {exporting ? 'Menyiapkan…' : 'Unduh Excel Bulan Ini'}</button>
        </div>
        <p className="text-xs text-[#6b7688] mb-4">Transaksi yang dibatalkan tetap tampil sebagai audit trail dan tidak dihitung pada Masuk Aktif. Koreksi tidak pernah menghapus riwayat transaksi asli.</p>

        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['Waktu', 'No. Referensi', 'Saluran', 'Rangkaian Dokumen', 'No. PO', 'Antrian', 'Tipe', 'Kondisi', 'Produk', 'Perubahan', 'Kadaluarsa', 'Pihak Terkait', 'Dicatat Oleh'].map((h) => <th key={h} className="py-2.5 pr-4 font-semibold whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {filtered.length === 0 ? <tr><td colSpan={13} className="py-8 text-center text-[#6b7688]">Belum ada transaksi yang sesuai filter.</td></tr> : filtered.map((t) => {
                const auditChannel = transactionChannel(t);
                const badge = typeBadge(t.type);
                return (
                  <tr key={t.id} className={`tbl-row border-b border-[#131a24] ${t.voided ? 'opacity-55' : ''}`}>
                    <td className="py-3 pr-4 whitespace-nowrap text-[#8b93a1]">{formatDate(t.time)}</td>
                    <td className="py-3 pr-4 font-mono text-xs"><div>{t.ref || '—'}</div>{t.voided && <span className="inline-block mt-1 text-[9px] px-1.5 py-0.5 rounded bg-[#7f1d1d]/30 text-[#fca5a5]">DIBATALKAN</span>}</td>
                    <td className="py-3 pr-4">{auditChannel ? <span className={`text-[10px] font-mono px-2 py-0.5 rounded ${auditChannel === 'PSO' ? 'bg-[#2563eb]/15 text-[#60a5fa]' : 'bg-[#a855f7]/15 text-[#c084fc]'}`}>{auditChannel}</span> : <span className="text-[#6b7688]">—</span>}</td>
                    <td className="py-3 pr-4 font-mono text-xs whitespace-nowrap"><span className="text-[#93c5fd]">{t.document_type || '—'}</span>{t.parent_document && <span className="text-[#6b7688]"> ← {t.parent_document}</span>}</td>
                    <td className="py-3 pr-4 font-mono text-xs text-[#60a5fa]">{t.po_no || '—'}</td>
                    <td className="py-3 pr-4 font-mono text-xs">{t.antrian || '—'}</td>
                    <td className="py-3 pr-4"><span className="text-[10px] font-mono px-2 py-0.5 rounded" style={badge}>{t.type}</span></td>
                    <td className="py-3 pr-4"><span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#1a222e] text-[#8b93a1]">{t.kondisi || '—'}</span></td>
                    <td className="py-3 pr-4"><div className="font-medium">{t.product}</div><div className="label-mono text-[10px]">{t.sku}</div>{t.correction_reason && <div className="mt-1 text-[10px] text-[#f59e0b] max-w-[240px]">Alasan: {t.correction_reason}</div>}</td>
                    <td className={`py-3 pr-4 font-mono font-semibold ${Number(t.change || 0) > 0 ? 'text-[#22c55e]' : Number(t.change || 0) < 0 ? 'text-[#ef4444]' : 'text-[#8b93a1]'}`}><div>{Number(t.change || 0) > 0 ? '+' : ''}{formatNum(Number(t.change || 0))} {t.unit || ''}</div>{(packagingText(Math.abs(Number(t.change || 0)), t, formatNum) || Number(t.weight || 0) > 0) && <div className="mt-1 text-[10px] font-sans font-normal text-[#8b93a1]">{packagingText(Math.abs(Number(t.change || 0)), t, formatNum)}{packagingText(Math.abs(Number(t.change || 0)), t, formatNum) && Number(t.weight || 0) > 0 ? ' · ' : ''}{Number(t.weight || 0) > 0 ? `${formatNum(Math.abs(Number(t.total_weight || totalWeight(Math.abs(Number(t.change || 0)), t))))} kg` : ''}</div>}</td>
                    <td className="py-3 pr-4 font-mono text-xs whitespace-nowrap">{t.exp || '—'}</td>
                    <td className="py-3 pr-4 text-[#c7d0dc]">{t.penerima || '—'}</td>
                    <td className="py-3 pr-4 text-[#8b93a1] text-xs">{t.operator || '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default Riwayat;
