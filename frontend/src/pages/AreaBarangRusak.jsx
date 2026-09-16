import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, PackageX, RefreshCcw, Search } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError } from '../lib/api';
import { formatNum } from '../mock';

const AreaBarangRusak = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get('/damaged-stock-area');
      setData(response.data);
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => (data?.products || []).filter((row) => {
    const query = q.trim().toLowerCase();
    return !query || String(row.product || '').toLowerCase().includes(query) || String(row.sku || '').toLowerCase().includes(query);
  }), [data, q]);

  const summary = data?.summary || {};

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Damaged Stock Subledger</div>
          <h1 className="font-display text-4xl font-bold">Area Barang Rusak</h1>
          <p className="text-[#8b93a1] mt-2 max-w-3xl">Saldo fisik barang rusak dipisahkan dari tumpukan stok Baik. Halaman ini menggabungkan saldo master, PSO/KOM, retur pemasok, dan audit pergerakan rusak.</p>
        </div>
        <button type="button" onClick={load} disabled={loading} className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm disabled:opacity-50"><RefreshCcw size={16} className={loading ? 'animate-spin' : ''} /> Periksa Ulang</button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="card-surface p-4"><div className="label-mono text-[9px]">Produk di Area Rusak</div><div className="font-mono text-2xl font-bold mt-1">{summary.productsInArea ?? '—'}</div></div>
        <div className="card-surface p-4 border border-[#78350f]"><div className="label-mono text-[9px] text-[#fcd34d]">Retur Pemasok Terbuka</div><div className="font-mono text-2xl font-bold text-[#fbbf24] mt-1">{summary.openSupplierClaims ?? '—'}</div></div>
        <div className="card-surface p-4 border border-[#7f1d1d]"><div className="label-mono text-[9px] text-[#fca5a5]">Mismatch PSO/KOM</div><div className="font-mono text-2xl font-bold text-[#ef4444] mt-1">{summary.productsWithChannelMismatch ?? '—'}</div></div>
      </div>

      {(data?.summaryByUnit || []).length > 0 && <div className="card-surface p-4 flex flex-wrap gap-3 items-center"><div className="text-xs text-[#8b93a1] mr-1">Saldo fisik per satuan:</div>{data.summaryByUnit.map((item) => <div key={item.unit} className="rounded-lg bg-[#0b0f17] border border-[#242f3d] px-3 py-2"><span className="font-mono font-semibold">{formatNum(item.qty)}</span> <span className="text-xs text-[#8b93a1]">{item.unit}</span></div>)}</div>}

      <div className="card-surface p-5">
        <div className="relative mb-4 max-w-xl"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari SKU / produk rusak..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm" /></div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['Status', 'Produk', 'Lokasi', 'Saldo Rusak', 'PSO/KOM', 'Retur Terbuka', 'Menunggu Pengganti'].map((h) => <th key={h} className="py-2.5 pr-4 whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={7} className="py-10 text-center text-[#8b93a1]">Memuat Area Barang Rusak...</td></tr> : rows.length === 0 ? <tr><td colSpan={7} className="py-10 text-center text-[#8b93a1]">Tidak ada saldo rusak yang sesuai.</td></tr> : rows.map((row) => <tr key={row.productId || row.sku} className="border-b border-[#131a24]">
                <td className="py-3 pr-4">{row.severity === 'OK' ? <span className="text-[10px] border border-[#14532d] bg-[#14532d]/25 text-[#86efac] rounded-full px-2 py-1">OK</span> : <span className="inline-flex items-center gap-1 text-[10px] border border-[#7f1d1d] bg-[#7f1d1d]/30 text-[#fca5a5] rounded-full px-2 py-1"><AlertTriangle size={11} />ERROR</span>}</td>
                <td className="py-3 pr-4"><div className="font-semibold">{row.product}</div><div className="label-mono text-[10px]">{row.sku}</div></td>
                <td className="py-3 pr-4"><span className="inline-flex items-center gap-1.5 text-xs"><PackageX size={14} className="text-[#f87171]" />{row.location}</span></td>
                <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(row.masterDamaged)} {row.unit}</td>
                <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(row.channelDamaged)} <span className="text-[#6b7688]">Δ {formatNum(row.channelDifference)}</span></td>
                <td className="py-3 pr-4 font-mono">{row.openClaims}</td>
                <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(row.pendingReplacement)} {row.unit}</td>
              </tr>)}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card-surface p-5">
        <h2 className="font-display text-lg font-bold mb-4">Pergerakan Barang Rusak Terbaru</h2>
        <div className="overflow-x-auto max-h-[420px]">
          <table className="w-full text-sm tbl"><thead className="sticky top-0 bg-[#0d121b]"><tr className="text-left border-b border-[#1a222e]">{['Waktu', 'Produk', 'Dokumen', 'Perubahan', 'Asal/Lokasi', 'Operator'].map((h) => <th key={h} className="py-2.5 pr-4 whitespace-nowrap">{h}</th>)}</tr></thead><tbody>{(data?.recentMovements || []).length === 0 ? <tr><td colSpan={6} className="py-8 text-center text-[#8b93a1]">Belum ada riwayat pergerakan rusak.</td></tr> : data.recentMovements.map((move) => <tr key={move.id} className="border-b border-[#131a24]"><td className="py-2.5 pr-4 text-xs whitespace-nowrap">{move.time ? new Date(move.time).toLocaleString('id-ID') : '—'}</td><td className="py-2.5 pr-4"><div>{move.product}</div><div className="label-mono text-[9px]">{move.sku}</div></td><td className="py-2.5 pr-4"><div className="font-mono text-xs">{move.ref || '—'}</div><div className="text-[10px] text-[#6b7688]">{move.documentType || move.type}</div></td><td className={`py-2.5 pr-4 font-mono ${Number(move.qty) < 0 ? 'text-[#fca5a5]' : 'text-[#86efac]'}`}>{Number(move.qty) > 0 ? '+' : ''}{formatNum(move.qty)} {move.unit}</td><td className="py-2.5 pr-4 text-xs">{move.sourceStackCode || move.location || 'AREA BARANG RUSAK'}</td><td className="py-2.5 pr-4 text-xs">{move.operator || '—'}</td></tr>)}</tbody></table>
        </div>
      </div>
    </div>
  );
};

export default AreaBarangRusak;
