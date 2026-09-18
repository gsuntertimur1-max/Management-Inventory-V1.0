import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCcw, Search, ShieldAlert } from 'lucide-react';
import api, { apiError } from '../lib/api';
import { formatNum } from '../mock';
import { toast } from 'sonner';

const badgeClass = (severity) => severity === 'ERROR'
  ? 'bg-[#7f1d1d]/35 text-[#fca5a5] border-[#7f1d1d]'
  : severity === 'WARNING'
    ? 'bg-[#78350f]/30 text-[#fcd34d] border-[#78350f]'
    : 'bg-[#14532d]/25 text-[#86efac] border-[#14532d]';

const KontrolIntegritas = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [severity, setSeverity] = useState('SEMUA');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get('/integrity-control');
      setData(response.data);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => (data?.products || []).filter((row) => {
    const query = q.trim().toLowerCase();
    return (severity === 'SEMUA' || row.severity === severity)
      && (!query || String(row.name || '').toLowerCase().includes(query) || String(row.sku || '').toLowerCase().includes(query));
  }), [data, q, severity]);

  const stackReservations = useMemo(() => (data?.stackReservations || []).filter((row) => {
    const query = q.trim().toLowerCase();
    return !query
      || String(row.name || '').toLowerCase().includes(query)
      || String(row.sku || '').toLowerCase().includes(query)
      || String(row.stackCode || '').toLowerCase().includes(query)
      || (row.queues || []).some((queue) => String(queue).toLowerCase().includes(query));
  }), [data, q]);

  const summary = data?.summary || {};

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Database Health</div>
          <h1 className="font-display text-4xl font-bold">Kontrol Integritas</h1>
        </div>
        <button type="button" onClick={load} disabled={loading} className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border border-[#2a3443] text-sm hover:bg-[#141a24] disabled:opacity-50">
          <RefreshCcw size={16} className={loading ? 'animate-spin' : ''} /> Periksa Ulang
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-8 gap-3">
        <div className="card-surface p-4"><div className="label-mono text-[9px]">Produk</div><div className="font-mono text-2xl font-bold mt-1">{summary.products ?? '—'}</div></div>
        <div className="card-surface p-4 border border-[#14532d]"><div className="label-mono text-[9px] text-[#86efac]">OK</div><div className="font-mono text-2xl font-bold text-[#4ade80] mt-1">{summary.ok ?? '—'}</div></div>
        <div className="card-surface p-4 border border-[#78350f]"><div className="label-mono text-[9px] text-[#fcd34d]">Peringatan</div><div className="font-mono text-2xl font-bold text-[#fbbf24] mt-1">{summary.warnings ?? '—'}</div></div>
        <div className="card-surface p-4 border border-[#7f1d1d]"><div className="label-mono text-[9px] text-[#fca5a5]">Error</div><div className="font-mono text-2xl font-bold text-[#ef4444] mt-1">{summary.errors ?? '—'}</div></div>
        <div className="card-surface p-4"><div className="label-mono text-[9px]">Outbound Aktif</div><div className="font-mono text-2xl font-bold mt-1">{summary.activeOutboundLoads ?? '—'}</div></div>
        <div className="card-surface p-4"><div className="label-mono text-[9px]">Tumpukan Reservasi</div><div className="font-mono text-2xl font-bold mt-1">{summary.reservedStacks ?? '—'}</div></div>
        <div className={`card-surface p-4 border ${Number(summary.overReservedStacks || 0) > 0 ? 'border-[#7f1d1d]' : 'border-[#14532d]'}`}><div className={`label-mono text-[9px] ${Number(summary.overReservedStacks || 0) > 0 ? 'text-[#fca5a5]' : 'text-[#86efac]'}`}>Over-reserved</div><div className={`font-mono text-2xl font-bold mt-1 ${Number(summary.overReservedStacks || 0) > 0 ? 'text-[#ef4444]' : 'text-[#4ade80]'}`}>{summary.overReservedStacks ?? '—'}</div></div>
        <div className="card-surface p-4"><div className="label-mono text-[9px]">Txn tanpa ID</div><div className="font-mono text-2xl font-bold mt-1">{summary.missingProductIdTransactions ?? '—'}</div></div>
      </div>

      {(data?.systemIssues || []).length > 0 && (
        <div className="space-y-2">
          {data.systemIssues.map((issue) => (
            <div key={issue.code} className={`rounded-xl border px-4 py-3 text-sm flex items-start gap-3 ${badgeClass(issue.severity)}`}>
              <ShieldAlert size={18} className="shrink-0 mt-0.5" />
              <div><div className="font-semibold">{issue.code}</div><div className="opacity-90 mt-0.5">{issue.message}</div></div>
            </div>
          ))}
        </div>
      )}

      <div className="card-surface p-5">
        <div className="flex flex-wrap gap-3 mb-4">
          <div className="relative min-w-[240px] flex-1"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari SKU / nama produk / tumpukan / antrian..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm outline-none" /></div>
          <select value={severity} onChange={(e) => setSeverity(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm">
            <option value="SEMUA">Semua Status</option><option value="ERROR">Error</option><option value="WARNING">Peringatan</option><option value="OK">OK</option>
          </select>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['Status', 'Produk', 'Master Baik', 'Tumpukan', 'Selisih', 'Master Rusak', 'PSO/KOM Baik', 'PSO/KOM Rusak', 'Reservasi', 'Temuan'].map((h) => <th key={h} className="py-2.5 pr-4 whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={10} className="py-10 text-center text-[#8b93a1]">Memeriksa integritas...</td></tr> : rows.length === 0 ? <tr><td colSpan={10} className="py-10 text-center text-[#8b93a1]">Tidak ada data yang sesuai filter.</td></tr> : rows.map((row) => (
                <tr key={row.productId || row.sku} className="border-b border-[#131a24] align-top">
                  <td className="py-3 pr-4"><span className={`inline-flex items-center gap-1.5 border rounded-full px-2 py-1 text-[10px] font-mono ${badgeClass(row.severity)}`}>{row.severity === 'OK' ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}{row.severity}</span></td>
                  <td className="py-3 pr-4"><div className="font-semibold">{row.name}</div><div className="label-mono text-[10px]">{row.sku}</div></td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(row.masterGood)} {row.unit}</td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(row.stackGood)} {row.unit}</td>
                  <td className={`py-3 pr-4 font-mono whitespace-nowrap ${Math.abs(Number(row.stackDifference || 0)) > 0.000001 ? 'text-[#fbbf24]' : 'text-[#4ade80]'}`}>{formatNum(row.stackDifference)}</td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(row.masterDamaged)} {row.unit}</td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(row.channelGood)} <span className="text-[#6b7688]">Δ {formatNum(row.channelGoodDifference)}</span></td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(row.channelDamaged)} <span className="text-[#6b7688]">Δ {formatNum(row.channelDamagedDifference)}</span></td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap"><div>Baik {formatNum(row.reservedGood)}</div><div className="text-[#8b93a1]">Rusak {formatNum(row.reservedDamaged)}</div></td>
                  <td className="py-3 pr-4 min-w-[260px]">{row.issues?.length ? <ul className="space-y-1 text-xs text-[#fca5a5]">{row.issues.map((issue) => <li key={issue}>• {issue}</li>)}</ul> : <span className="text-xs text-[#4ade80]">Tidak ada selisih kritis</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card-surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
          <div><div className="label-mono text-[10px] text-[#93c5fd]">Reservasi Stok Baik</div><h2 className="font-display text-xl font-bold mt-1">Fisik | Reservasi | Tersedia per Tumpukan</h2><p className="text-xs text-[#8b93a1] mt-1">Menghitung antrean Menunggu dan Sedang Dimuat. Tersedia negatif menandakan over-reserved.</p></div>
          <div className={`border rounded-lg px-3 py-2 text-xs font-mono ${Number(summary.overReservedStacks || 0) > 0 ? badgeClass('ERROR') : badgeClass('OK')}`}>{Number(summary.overReservedStacks || 0) > 0 ? `${summary.overReservedStacks} OVER-RESERVED` : 'RESERVASI AMAN'}</div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['Status', 'Tumpukan', 'Produk', 'Fisik', 'Reservasi', 'Tersedia', 'Antrian Aktif'].map((h) => <th key={h} className="py-2.5 pr-4 whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={7} className="py-8 text-center text-[#8b93a1]">Memeriksa reservasi...</td></tr> : stackReservations.length === 0 ? <tr><td colSpan={7} className="py-8 text-center text-[#8b93a1]">Tidak ada reservasi tumpukan aktif.</td></tr> : stackReservations.map((row) => (
                <tr key={`${row.productId}-${row.stackCode}`} className={`border-b border-[#131a24] ${row.overReserved ? 'bg-[#7f1d1d]/10' : ''}`}>
                  <td className="py-3 pr-4"><span className={`inline-flex items-center gap-1.5 border rounded-full px-2 py-1 text-[10px] font-mono ${badgeClass(row.overReserved ? 'ERROR' : 'OK')}`}>{row.overReserved ? <AlertTriangle size={12} /> : <CheckCircle2 size={12} />}{row.overReserved ? 'OVER' : 'OK'}</span></td>
                  <td className="py-3 pr-4 font-mono font-semibold text-[#93c5fd] whitespace-nowrap">{row.stackCode}</td>
                  <td className="py-3 pr-4"><div className="font-semibold">{row.name}</div><div className="label-mono text-[10px]">{row.sku}</div></td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(row.physical)} {row.unit}</td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap text-[#fbbf24]">{formatNum(row.reserved)} {row.unit}</td>
                  <td className={`py-3 pr-4 font-mono font-bold whitespace-nowrap ${row.overReserved ? 'text-[#ef4444]' : 'text-[#4ade80]'}`}>{formatNum(row.available)} {row.unit}{row.overReserved && <div className="text-[10px] mt-1">lebih {formatNum(row.overBy)}</div>}</td>
                  <td className="py-3 pr-4 font-mono text-xs min-w-[170px]">{(row.queues || []).join(', ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {(data?.unassignedStackReservations || []).length > 0 && (
        <div className="card-surface p-5 border border-[#7f1d1d]">
          <div className="flex items-start gap-3 mb-4"><ShieldAlert size={20} className="text-[#ef4444] shrink-0 mt-0.5" /><div><h2 className="font-display text-lg font-bold text-[#fca5a5]">Reservasi Tanpa Tumpukan</h2><p className="text-xs text-[#8b93a1] mt-1">Baris berikut harus diberi sumber tumpukan sebelum pemuatan dilanjutkan.</p></div></div>
          <div className="overflow-x-auto"><table className="w-full text-sm tbl"><thead><tr className="text-left border-b border-[#1a222e]"><th className="py-2.5 pr-4">Antrian</th><th className="py-2.5 pr-4">Dokumen</th><th className="py-2.5 pr-4">Produk</th><th className="py-2.5 pr-4">Reservasi</th><th className="py-2.5">Temuan</th></tr></thead><tbody>{data.unassignedStackReservations.map((row, index) => <tr key={`${row.loadId}-${row.productId}-${index}`} className="border-b border-[#131a24]"><td className="py-3 pr-4 font-mono text-[#fca5a5]">{row.queue || '—'}</td><td className="py-3 pr-4 font-mono text-xs">{row.ref || '—'}</td><td className="py-3 pr-4"><div className="font-semibold">{row.name}</div><div className="label-mono text-[10px]">{row.sku}</div></td><td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(row.qty)} {row.unit}</td><td className="py-3 text-xs text-[#fca5a5]">{row.issue}</td></tr>)}</tbody></table></div>
        </div>
      )}
    </div>
  );
};

export default KontrolIntegritas;
