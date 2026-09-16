import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CalendarClock, CheckCircle2, RefreshCcw, Search } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError } from '../lib/api';
import { formatNum } from '../mock';

const statusClass = (status) => ({
  EXPIRED: 'bg-[#7f1d1d]/35 text-[#fca5a5] border-[#7f1d1d]',
  LE_30_HARI: 'bg-[#7f1d1d]/25 text-[#fca5a5] border-[#7f1d1d]',
  LE_90_HARI: 'bg-[#78350f]/30 text-[#fcd34d] border-[#78350f]',
  AMAN: 'bg-[#14532d]/25 text-[#86efac] border-[#14532d]',
  TANPA_EXPIRED: 'bg-[#1e293b] text-[#cbd5e1] border-[#334155]',
}[status] || 'bg-[#1e293b] text-[#cbd5e1] border-[#334155]');

const statusLabel = (status) => ({
  EXPIRED: 'EXPIRED', LE_30_HARI: '≤ 30 HARI', LE_90_HARI: '≤ 90 HARI',
  AMAN: 'AMAN', TANPA_EXPIRED: 'TANPA EXP', TANGGAL_INVALID: 'INVALID',
}[status] || status || '—');

const FefoLot = () => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [onlyAttention, setOnlyAttention] = useState(false);
  const [expanded, setExpanded] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get('/fefo-recommendations');
      setRows(response.data || []);
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => rows.filter((row) => {
    const query = q.trim().toLowerCase();
    const nextStatus = row.nextLot?.expiryStatus || '';
    const attention = Number(row.coveragePct || 0) < 99.999 || ['EXPIRED', 'LE_30_HARI', 'LE_90_HARI'].includes(nextStatus);
    return (!query || String(row.product || '').toLowerCase().includes(query) || String(row.sku || '').toLowerCase().includes(query))
      && (!onlyAttention || attention);
  }), [rows, q, onlyAttention]);

  const trackedProducts = rows.filter((row) => Number(row.trackedQty || 0) > 0).length;
  const untrackedProducts = rows.filter((row) => Number(row.untrackedQty || 0) > 0.000001).length;
  const urgentLots = rows.reduce((count, row) => count + (row.lots || []).filter((lot) => ['EXPIRED', 'LE_30_HARI'].includes(lot.expiryStatus)).length, 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><div className="label-mono mb-2">First Expired First Out</div><h1 className="font-display text-4xl font-bold">Lot & FEFO</h1><p className="text-[#8b93a1] mt-2 max-w-3xl">Penerimaan baru otomatis menjadi lot per tumpukan. Stok historis yang belum mempunyai lot ditampilkan sebagai legacy/untracked, bukan diberi tanggal secara otomatis.</p></div>
        <button type="button" onClick={load} disabled={loading} className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm disabled:opacity-50"><RefreshCcw size={16} className={loading ? 'animate-spin' : ''} /> Periksa FEFO</button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="card-surface p-4"><div className="label-mono text-[9px]">Produk Punya Lot</div><div className="font-mono text-2xl font-bold mt-1">{trackedProducts}</div></div>
        <div className="card-surface p-4 border border-[#78350f]"><div className="label-mono text-[9px] text-[#fcd34d]">Produk Legacy / Untracked</div><div className="font-mono text-2xl font-bold text-[#fbbf24] mt-1">{untrackedProducts}</div></div>
        <div className="card-surface p-4 border border-[#7f1d1d]"><div className="label-mono text-[9px] text-[#fca5a5]">Lot Expired / ≤30 Hari</div><div className="font-mono text-2xl font-bold text-[#ef4444] mt-1">{urgentLots}</div></div>
      </div>

      <div className="card-surface p-5">
        <div className="flex flex-wrap gap-3 mb-4">
          <div className="relative flex-1 min-w-[240px]"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari SKU / produk..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm" /></div>
          <label className="inline-flex items-center gap-2 px-3 py-2.5 rounded-lg border border-[#242f3d] text-sm"><input type="checkbox" checked={onlyAttention} onChange={(e) => setOnlyAttention(e.target.checked)} /> Hanya yang perlu perhatian</label>
        </div>

        <div className="space-y-3">
          {loading ? <div className="py-12 text-center text-[#8b93a1]">Memuat subledger lot...</div> : filtered.length === 0 ? <div className="py-12 text-center text-[#8b93a1]">Belum ada data FEFO yang sesuai.</div> : filtered.map((row) => {
            const next = row.nextLot;
            const coverage = Number(row.coveragePct || 0);
            const isOpen = expanded === row.productId;
            return <div key={row.productId} className="rounded-xl border border-[#1a222e] bg-[#0b0f17] overflow-hidden">
              <button type="button" onClick={() => setExpanded(isOpen ? '' : row.productId)} className="w-full p-4 text-left grid grid-cols-1 lg:grid-cols-[1.5fr_.8fr_.9fr_.9fr_1fr] gap-3 items-center hover:bg-[#111722]">
                <div><div className="font-semibold">{row.product}</div><div className="label-mono text-[10px] mt-1">{row.sku}</div></div>
                <div><div className="label-mono text-[9px]">Stok Tumpukan</div><div className="font-mono font-semibold mt-1">{formatNum(row.stackQty)} {row.unit}</div></div>
                <div><div className="label-mono text-[9px]">Coverage Lot</div><div className={`font-mono font-semibold mt-1 ${coverage >= 99.999 ? 'text-[#4ade80]' : 'text-[#fbbf24]'}`}>{coverage.toFixed(1)}%</div><div className="text-[10px] text-[#6b7688]">Untracked {formatNum(row.untrackedQty)} {row.unit}</div></div>
                <div><div className="label-mono text-[9px]">FEFO Berikutnya</div>{next ? <><div className="font-mono text-xs font-semibold mt-1">{next.stackCode}</div><div className="text-[10px] text-[#8b93a1]">{next.exp || 'Tanpa expired'}</div></> : <div className="text-xs text-[#8b93a1] mt-1">Belum ada lot</div>}</div>
                <div className="flex justify-start lg:justify-end">{next ? <span className={`inline-flex items-center gap-1.5 border rounded-full px-2.5 py-1 text-[10px] font-mono ${statusClass(next.expiryStatus)}`}><CalendarClock size={12} />{statusLabel(next.expiryStatus)}</span> : <span className="inline-flex items-center gap-1.5 border border-[#78350f] bg-[#78350f]/20 text-[#fcd34d] rounded-full px-2.5 py-1 text-[10px]"><AlertTriangle size={12} /> LEGACY</span>}</div>
              </button>

              {isOpen && <div className="border-t border-[#1a222e] p-4">
                {(row.lots || []).length === 0 ? <div className="text-sm text-[#8b93a1]">Stok ini berasal dari data historis sebelum subledger lot diaktifkan. Jangan mengarang expired; lot dapat dilengkapi saat verifikasi fisik berikutnya.</div> : <div className="overflow-x-auto"><table className="w-full text-sm tbl"><thead><tr className="text-left border-b border-[#1a222e]">{['Urutan', 'Lot', 'Tumpukan', 'Referensi', 'Expired', 'Sisa', 'Status'].map((h) => <th key={h} className="py-2 pr-4 whitespace-nowrap">{h}</th>)}</tr></thead><tbody>{row.lots.map((lot, index) => <tr key={lot.id} className="border-b border-[#131a24]"><td className="py-2.5 pr-4 font-mono text-xs">#{index + 1}</td><td className="py-2.5 pr-4 font-mono text-xs">{lot.lotCode}</td><td className="py-2.5 pr-4 font-mono text-xs">{lot.stackCode}</td><td className="py-2.5 pr-4"><div className="font-mono text-xs">{lot.sourceRef || '—'}</div><div className="text-[10px] text-[#6b7688]">{lot.poNo || ''}</div></td><td className="py-2.5 pr-4 font-mono text-xs">{lot.exp || '—'}</td><td className="py-2.5 pr-4 font-mono">{formatNum(lot.remainingQty)} {lot.unit}</td><td className="py-2.5 pr-4"><span className={`inline-flex items-center gap-1 border rounded-full px-2 py-0.5 text-[9px] ${statusClass(lot.expiryStatus)}`}>{lot.expiryStatus === 'AMAN' ? <CheckCircle2 size={11} /> : <AlertTriangle size={11} />}{statusLabel(lot.expiryStatus)}</span></td></tr>)}</tbody></table></div>}
              </div>}
            </div>;
          })}
        </div>
      </div>
    </div>
  );
};

export default FefoLot;
