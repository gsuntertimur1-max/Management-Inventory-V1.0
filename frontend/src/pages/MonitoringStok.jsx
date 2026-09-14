import React, { useMemo, useState } from 'react';
import { Download, Search, ShieldAlert } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatNum } from '../mock';
import { downloadApiFile } from '../lib/api';
import { toast } from 'sonner';

const statusClass = {
  EXPIRED: 'bg-[#ef4444]/15 text-[#ef4444]',
  MENDEKATI: 'bg-[#f59e0b]/15 text-[#f59e0b]',
  AMAN: 'bg-[#22c55e]/15 text-[#22c55e]',
  BELUM_DICATAT: 'bg-[#64748b]/15 text-[#94a3b8]',
  TIDAK_VALID: 'bg-[#ef4444]/15 text-[#ef4444]',
};

const MonitoringStok = () => {
  const { monitoringStock } = useData();
  const [q, setQ] = useState('');
  const [condition, setCondition] = useState('');
  const [expiry, setExpiry] = useState('');

  const rows = useMemo(() => monitoringStock.filter((row) => {
    const haystack = `${row.sku} ${row.name} ${row.komoditi} ${row.saluran} ${row.stackCode} ${row.batch}`.toLowerCase();
    return (!q || haystack.includes(q.toLowerCase()))
      && (!condition || row.condition === condition)
      && (!expiry || row.expiryStatus === expiry);
  }), [monitoringStock, q, condition, expiry]);

  const totalKg = rows.reduce((sum, row) => sum + Number(row.kg || 0), 0);
  const unplaced = rows.filter((row) => row.stackCode === 'BELUM_DICATAT' || row.source === 'products').length;

  return (
    <div className="space-y-6">
      <div className="flex flex-col xl:flex-row xl:items-end xl:justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Saldo Terpadu</div>
          <h1 className="font-display text-3xl md:text-4xl font-bold">Monitoring Stok</h1>
          <p className="text-[#8b93a1] mt-2 max-w-3xl">Satu tampilan saldo berdasarkan SKU, kondisi, batch, expired, gudang, dan lokasi tumpukan. Data lama tanpa batch tetap tampil sebagai MASTER_STOCK.</p>
        </div>
        <button onClick={() => downloadApiFile('/export/products.xlsx', 'master_produk.xlsx').catch(() => toast.error('Export gagal'))} className="btn-primary inline-flex items-center gap-2 px-4 py-2.5 rounded-xl">
          <Download size={16} /> Export Excel
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="card-surface p-5"><div className="label-mono">Baris saldo</div><div className="font-display text-3xl font-bold mt-2">{formatNum(rows.length)}</div></div>
        <div className="card-surface p-5"><div className="label-mono">Total netto</div><div className="font-display text-3xl font-bold mt-2">{formatNum(totalKg)} kg</div></div>
        <div className="card-surface p-5"><div className="label-mono">Belum ditempatkan</div><div className="font-display text-3xl font-bold mt-2">{formatNum(unplaced)}</div></div>
      </div>

      <div className="card-surface p-5">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_180px_180px] gap-3 mb-4">
          <div className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari SKU, nama barang, batch, lokasi..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" />
          </div>
          <select value={condition} onChange={(e) => setCondition(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm">
            <option value="">Semua kondisi</option><option>BAIK</option><option>RUSAK</option><option>ON_PROSES</option>
          </select>
          <select value={expiry} onChange={(e) => setExpiry(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm">
            <option value="">Semua expired</option><option value="EXPIRED">Expired</option><option value="MENDEKATI">Mendekati</option><option value="AMAN">Aman</option><option value="BELUM_DICATAT">Belum dicatat</option>
          </select>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['SKU', 'Nama Barang', 'Saluran/Komoditi', 'Gudang/Lokasi', 'Kondisi', 'Batch', 'Expired', 'Jumlah', 'Kg', 'Status'].map((h) => <th key={h} className="py-2.5 pr-4">{h}</th>)}</tr></thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${row.productId}-${row.stackCode}-${row.condition}-${index}`} className="tbl-row border-b border-[#131a24]">
                  <td className="py-3 pr-4 font-mono text-xs text-[#93c5fd]">{row.sku}</td>
                  <td className="py-3 pr-4 font-medium min-w-[220px]">{row.name}</td>
                  <td className="py-3 pr-4 text-xs text-[#8b93a1]">{row.saluran || '-'}<br />{row.komoditi || '-'}</td>
                  <td className="py-3 pr-4 text-xs">{row.warehouse || '-'}<br /><span className="text-[#8b93a1]">{row.stackCode}</span></td>
                  <td className="py-3 pr-4"><span className="px-2 py-1 rounded-full bg-[#2563eb]/15 text-[#60a5fa] text-xs">{row.condition}</span></td>
                  <td className="py-3 pr-4 font-mono text-xs">{row.batch}</td>
                  <td className="py-3 pr-4 font-mono text-xs">{row.expired || '-'}</td>
                  <td className="py-3 pr-4 font-mono">{formatNum(row.qty)}</td>
                  <td className="py-3 pr-4 font-mono">{formatNum(row.kg)}</td>
                  <td className="py-3"><span className={`px-2 py-1 rounded-full text-xs ${statusClass[row.expiryStatus] || statusClass.BELUM_DICATAT}`}>{row.expiryStatus}</span></td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={10} className="py-10 text-center text-[#8b93a1]"><ShieldAlert className="mx-auto mb-2" />Tidak ada saldo sesuai filter.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default MonitoringStok;
