import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCcw } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError } from '../lib/api';
import { formatNum } from '../mock';
import TumpukanStok from './TumpukanStok';

const badgeClass = (status) => ({
  VERIFIED: 'border-[#14532d] bg-[#14532d]/20 text-[#86efac]',
  MIXED: 'border-[#78350f] bg-[#78350f]/20 text-[#fcd34d]',
  LEGACY: 'border-[#7c2d12] bg-[#7c2d12]/20 text-[#fdba74]',
  PENDING_RETURN_RECONCILIATION: 'border-[#7f1d1d] bg-[#7f1d1d]/20 text-[#fca5a5]',
}[status] || 'border-[#334155] bg-[#1e293b] text-[#cbd5e1]');

const badgeLabel = (status) => ({
  VERIFIED: 'TERVERIFIKASI',
  MIXED: 'MIXED',
  LEGACY: 'LEGACY',
  PENDING_RETURN_RECONCILIATION: 'RETUR PENDING',
}[status] || status || '—');

const TumpukanWithLotStatus = () => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/fefo-recommendations');
      setRows(data || []);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const stackRows = useMemo(() => rows.flatMap((row) => (row.stackCoverage || []).map((stack) => ({
    ...stack,
    productId: row.productId,
    product: row.product,
    sku: row.sku,
    unit: row.unit,
  }))).sort((a, b) => String(a.stackCode).localeCompare(String(b.stackCode), 'id', { numeric: true })), [rows]);

  const attention = stackRows.filter((row) => row.coverageStatus !== 'VERIFIED');
  const verified = stackRows.filter((row) => row.coverageStatus === 'VERIFIED').length;
  const pendingQty = stackRows.reduce((sum, row) => sum + Number(row.pendingReturnQty || 0), 0);

  return <div className="space-y-5">
    <section className="card-surface p-4 border border-[#26364c]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="label-mono text-[10px] text-[#93c5fd]">Status Lot Peta Tumpukan</div>
          <h2 className="font-display text-xl font-bold mt-1">Coverage Lot per Tumpukan</h2>
          <p className="text-xs text-[#8b93a1] mt-1">Ringkasan ini berada langsung di halaman Peta Tumpukan. Tumpukan legacy/mixed/retur pending tetap terlihat tanpa harus membuka menu FEFO.</p>
        </div>
        <button type="button" onClick={load} disabled={loading} className="px-3 py-2 rounded-lg border border-[#294263] text-xs inline-flex gap-2 items-center disabled:opacity-50"><RefreshCcw size={14} className={loading ? 'animate-spin' : ''} /> Perbarui status</button>
      </div>

      <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
        <div className="rounded-lg bg-[#0b0f17] p-3"><div className="text-[#6b7688]">Produk/Tumpukan</div><div className="font-mono text-lg font-bold mt-1">{stackRows.length}</div></div>
        <div className="rounded-lg bg-[#0b0f17] p-3 border border-[#14532d]"><div className="text-[#86efac]">Terverifikasi</div><div className="font-mono text-lg font-bold mt-1 text-[#86efac]">{verified}</div></div>
        <div className="rounded-lg bg-[#0b0f17] p-3 border border-[#78350f]"><div className="text-[#fcd34d]">Perlu perhatian</div><div className="font-mono text-lg font-bold mt-1 text-[#fbbf24]">{attention.length}</div></div>
        <div className="rounded-lg bg-[#0b0f17] p-3 border border-[#7f1d1d]"><div className="text-[#fca5a5]">Retur pending</div><div className="font-mono text-lg font-bold mt-1 text-[#f87171]">{formatNum(pendingQty)}</div></div>
      </div>

      {loading ? <div className="py-4 text-center text-xs text-[#8b93a1]">Memuat status lot...</div> : attention.length === 0 ? <div className="mt-3 rounded-lg border border-[#14532d] bg-[#14532d]/15 p-3 text-xs text-[#86efac] flex items-center gap-2"><CheckCircle2 size={15} />Semua tumpukan yang memiliki stok sudah tercakup lot terverifikasi.</div> : <div className="mt-3 overflow-x-auto"><table className="w-full text-xs tbl"><thead><tr className="text-left border-b border-[#1a222e]"><th className="py-2 pr-3">Tumpukan</th><th className="py-2 pr-3">Komoditi</th><th className="py-2 pr-3">Fisik</th><th className="py-2 pr-3">Lot</th><th className="py-2 pr-3">Untracked</th><th className="py-2 pr-3">Coverage</th><th className="py-2 pr-3">Status</th></tr></thead><tbody>{attention.slice(0, 20).map((row) => <tr key={`${row.productId}-${row.stackCode}`} className="border-b border-[#131a24]"><td className="py-2.5 pr-3 font-mono font-semibold">{row.stackCode}</td><td className="py-2.5 pr-3"><div className="font-medium">{row.product}</div><div className="font-mono text-[9px] text-[#6b7688]">{row.sku}</div></td><td className="py-2.5 pr-3 font-mono">{formatNum(row.physicalQty)} {row.unit}</td><td className="py-2.5 pr-3 font-mono">{formatNum(row.trackedQty)}</td><td className="py-2.5 pr-3 font-mono text-[#fbbf24]">{formatNum(row.untrackedQty)}</td><td className="py-2.5 pr-3 font-mono">{Number(row.coveragePct || 0).toFixed(1)}%</td><td className="py-2.5 pr-3"><span className={`inline-flex items-center gap-1 border rounded-full px-2 py-0.5 text-[9px] ${badgeClass(row.coverageStatus)}`}><AlertTriangle size={10} />{badgeLabel(row.coverageStatus)}</span>{Number(row.pendingReturnQty || 0) > 0 && <div className="text-[9px] text-[#fca5a5] mt-1">Retur {formatNum(row.pendingReturnQty)} {row.unit}</div>}</td></tr>)}</tbody></table>{attention.length > 20 && <div className="text-[10px] text-[#6b7688] mt-2">Menampilkan 20 baris prioritas dari {attention.length}. Detail lengkap tersedia di Lot & FEFO.</div>}</div>}
    </section>

    <TumpukanStok />
  </div>;
};

export default TumpukanWithLotStatus;
