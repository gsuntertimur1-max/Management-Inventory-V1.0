import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, CircleDot, RefreshCcw, Search, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError } from '../lib/api';

const STAGES = [
  ['document', 'Dokumen'],
  ['queue', 'Antrean'],
  ['reservation', 'Reservasi'],
  ['stack', 'Tumpukan'],
  ['fefo', 'FEFO'],
  ['transaction', 'Transaksi'],
  ['suratJalan', 'SJ'],
  ['cost', 'Biaya'],
  ['postCommit', 'Post'],
];

const tone = (status) => status === 'ERROR'
  ? 'border-[#7f1d1d] bg-[#7f1d1d]/15 text-[#fca5a5]'
  : status === 'WARNING'
    ? 'border-[#78350f] bg-[#78350f]/15 text-[#fcd34d]'
    : 'border-[#14532d] bg-[#14532d]/10 text-[#86efac]';

const icon = (status) => status === 'ERROR'
  ? <XCircle size={12} />
  : status === 'WARNING'
    ? <AlertTriangle size={12} />
    : <CheckCircle2 size={12} />;

const stageLabel = (key) => STAGES.find(([value]) => value === key)?.[1] || key || '—';

const MainWarehouseE2EPanel = () => {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState({});
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [severity, setSeverity] = useState('SEMUA');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/integrity-control');
      setRows(data?.mainWarehouseE2E || []);
      setSummary(data?.summary || {});
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase();
    return rows.filter((row) => {
      if (severity !== 'SEMUA' && row.severity !== severity) return false;
      if (!query) return true;
      return [
        row.bonNo,
        row.queue,
        row.referenceNo,
        row.party,
        ...(row.documents || []),
      ].some((value) => String(value || '').toLowerCase().includes(query));
    });
  }, [rows, q, severity]);

  const stageErrors = summary.mainWarehouseE2EStageErrors || {};

  return (
    <div className="card-surface p-5 border border-[#26364c]">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <div className="label-mono text-[10px] text-[#93c5fd]">Tahap 14 · Gudang Utama</div>
          <h2 className="font-display text-xl font-bold mt-1">Rekonsiliasi End-to-End Pemuatan</h2>
          <p className="text-xs text-[#8b93a1] mt-1">
            Dokumen → Antrean → Reservasi → Tumpukan → FEFO → Transaksi → Surat Jalan → Biaya → Post-commit.
          </p>
        </div>
        <button type="button" onClick={load} disabled={loading} className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-[#2a3443] text-xs disabled:opacity-50">
          <RefreshCcw size={14} className={loading ? 'animate-spin' : ''} /> Periksa
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-6 gap-2 mb-4">
        <div className="rounded-lg bg-[#0b0f17] p-3"><div className="label-mono text-[9px]">Total Load</div><div className="font-mono text-xl font-bold mt-1">{summary.mainWarehouseE2ETotal ?? '—'}</div></div>
        <div className="rounded-lg border border-[#14532d] bg-[#14532d]/10 p-3"><div className="label-mono text-[9px] text-[#86efac]">Sehat</div><div className="font-mono text-xl font-bold text-[#4ade80] mt-1">{summary.mainWarehouseE2EHealthy ?? '—'}</div></div>
        <div className="rounded-lg border border-[#78350f] bg-[#78350f]/10 p-3"><div className="label-mono text-[9px] text-[#fcd34d]">Peringatan</div><div className="font-mono text-xl font-bold text-[#fbbf24] mt-1">{summary.mainWarehouseE2EWarnings ?? '—'}</div></div>
        <div className="rounded-lg border border-[#7f1d1d] bg-[#7f1d1d]/10 p-3"><div className="label-mono text-[9px] text-[#fca5a5]">Terputus</div><div className="font-mono text-xl font-bold text-[#ef4444] mt-1">{summary.mainWarehouseE2EErrors ?? '—'}</div></div>
        <div className="rounded-lg bg-[#0b0f17] p-3"><div className="label-mono text-[9px]">Aktif</div><div className="font-mono text-xl font-bold mt-1">{summary.mainWarehouseE2EActive ?? '—'}</div></div>
        <div className="rounded-lg bg-[#0b0f17] p-3"><div className="label-mono text-[9px]">Selesai</div><div className="font-mono text-xl font-bold mt-1">{summary.mainWarehouseE2ECompleted ?? '—'}</div></div>
      </div>

      {Object.keys(stageErrors).length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          {STAGES.filter(([key]) => Number(stageErrors[key] || 0) > 0).map(([key, label]) => (
            <span key={key} className="inline-flex items-center gap-1.5 rounded-full border border-[#7f1d1d] bg-[#7f1d1d]/10 px-2.5 py-1 text-[10px] font-mono text-[#fca5a5]">
              <AlertTriangle size={11} />{label}: {stageErrors[key]}
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2 mb-4">
        <div className="relative min-w-[220px] flex-1 max-w-xl">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari Bon / antrian / SO / penerima..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2 text-xs outline-none" />
        </div>
        <select value={severity} onChange={(e) => setSeverity(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-xs">
          <option value="SEMUA">Semua</option>
          <option value="ERROR">Terputus</option>
          <option value="WARNING">Peringatan</option>
          <option value="OK">Sehat</option>
        </select>
      </div>

      {loading ? (
        <div className="py-8 text-center text-sm text-[#8b93a1]">Merekonsiliasi rantai pemuatan...</div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-[#14532d] bg-[#14532d]/10 p-4 text-sm text-[#86efac] flex gap-2">
          <CheckCircle2 size={17} />Tidak ada pemuatan yang sesuai filter.
        </div>
      ) : (
        <div className="space-y-3 max-h-[680px] overflow-y-auto pr-1">
          {filtered.map((row) => (
            <div key={row.loadId} className={`rounded-xl border p-4 ${row.severity === 'ERROR' ? 'border-[#7f1d1d] bg-[#7f1d1d]/5' : row.severity === 'WARNING' ? 'border-[#78350f] bg-[#78350f]/5' : 'border-[#1f3a2c] bg-[#0b0f17]'}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`inline-flex items-center gap-1.5 border rounded-full px-2 py-1 text-[10px] font-mono ${tone(row.severity)}`}>{icon(row.severity)}{row.severity}</span>
                    <span className="font-mono text-xs text-[#93c5fd]">{row.bonNo || 'Bon —'}</span>
                    <span className="font-mono text-xs text-[#8b93a1]">{row.queue || 'Antrian —'}</span>
                  </div>
                  <div className="mt-2 font-semibold">{row.referenceNo || (row.documents || []).join(', ') || 'Dokumen —'}</div>
                  <div className="text-[11px] text-[#6b7688] mt-1">{row.status} · {row.operationalDate || '—'} · {row.party || '—'}</div>
                </div>
                {(row.brokenAt || row.warningAt) && (
                  <div className={`rounded-lg border px-3 py-2 text-xs ${tone(row.brokenAt ? 'ERROR' : 'WARNING')}`}>
                    <div className="label-mono text-[9px]">{row.brokenAt ? 'Titik Putus' : 'Perlu Cek'}</div>
                    <div className="font-semibold mt-1">{stageLabel(row.brokenAt || row.warningAt)}</div>
                  </div>
                )}
              </div>

              <div className="mt-4 grid grid-cols-3 md:grid-cols-5 xl:grid-cols-9 gap-2">
                {STAGES.map(([key, label]) => {
                  const stage = row.stages?.[key] || { status: 'WARNING', message: 'Belum diperiksa' };
                  return (
                    <div key={key} title={stage.message} className={`rounded-lg border px-2 py-2 min-h-[58px] ${tone(stage.status)}`}>
                      <div className="flex items-center gap-1 text-[10px] font-semibold">{icon(stage.status)}{label}</div>
                      <div className="text-[9px] opacity-80 mt-1 line-clamp-2">{stage.message}</div>
                    </div>
                  );
                })}
              </div>

              {row.severity !== 'OK' && (
                <div className="mt-3 flex items-start gap-2 text-[11px] text-[#8b93a1]">
                  <CircleDot size={12} className="mt-0.5 shrink-0" />
                  Kontrol ini hanya menunjukkan titik putus. Koreksi tetap melalui alur Koreksi Operasional, Stock Opname, atau Repair Completion agar stok tidak berubah diam-diam.
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default MainWarehouseE2EPanel;
