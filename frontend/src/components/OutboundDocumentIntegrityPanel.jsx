import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, FileWarning, RefreshCcw } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError } from '../lib/api';

const tone = (severity) => severity === 'ERROR'
  ? 'border-[#7f1d1d] bg-[#7f1d1d]/15 text-[#fca5a5]'
  : 'border-[#78350f] bg-[#78350f]/15 text-[#fcd34d]';

const OutboundDocumentIntegrityPanel = () => {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState({});
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/integrity-control');
      setRows(data?.outboundDocumentIntegrityIssues || []);
      setSummary(data?.summary || {});
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="card-surface p-5 border border-[#26364c]">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <div className="label-mono text-[10px] text-[#93c5fd]">Outbound Document Chain</div>
          <h2 className="font-display text-xl font-bold mt-1">Bon Muat ↔ Load ↔ Surat Jalan ↔ Transaksi</h2>
          <p className="text-xs text-[#8b93a1] mt-1">Mendeteksi dokumen ganda, salah-link, status tidak konsisten, serta kuantum transaksi KELUAR yang berbeda dari pemuatan selesai.</p>
        </div>
        <button type="button" onClick={load} disabled={loading} className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-[#2a3443] text-xs disabled:opacity-50"><RefreshCcw size={14} className={loading ? 'animate-spin' : ''} /> Periksa</button>
      </div>

      <div className="grid grid-cols-3 gap-2 mb-4">
        <div className="rounded-lg bg-[#0b0f17] p-3"><div className="label-mono text-[9px]">Temuan</div><div className="font-mono text-xl font-bold mt-1">{summary.outboundDocumentIntegrityIssues ?? '—'}</div></div>
        <div className="rounded-lg border border-[#7f1d1d] bg-[#7f1d1d]/10 p-3"><div className="label-mono text-[9px] text-[#fca5a5]">Error</div><div className="font-mono text-xl font-bold text-[#ef4444] mt-1">{summary.outboundDocumentIntegrityErrors ?? '—'}</div></div>
        <div className="rounded-lg border border-[#78350f] bg-[#78350f]/10 p-3"><div className="label-mono text-[9px] text-[#fcd34d]">Peringatan</div><div className="font-mono text-xl font-bold text-[#fbbf24] mt-1">{summary.outboundDocumentIntegrityWarnings ?? '—'}</div></div>
      </div>

      {loading ? <div className="py-8 text-center text-sm text-[#8b93a1]">Memeriksa relasi dokumen...</div> : rows.length === 0 ? (
        <div className="rounded-xl border border-[#14532d] bg-[#14532d]/10 p-4 text-sm text-[#86efac] flex gap-2"><CheckCircle2 size={17} />Tidak ditemukan masalah pada rantai dokumen outbound.</div>
      ) : (
        <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
          {rows.map((row, index) => <div key={`${row.code}-${row.loadId || row.bonNo || index}-${index}`} className={`rounded-xl border p-3 text-xs ${tone(row.severity)}`}>
            <div className="flex items-start gap-2"><span className="mt-0.5">{row.severity === 'ERROR' ? <FileWarning size={16} /> : <AlertTriangle size={16} />}</span><div className="min-w-0"><div className="font-semibold font-mono">{row.code}</div><div className="mt-1">{row.issue}</div><div className="mt-2 text-[10px] opacity-80 font-mono break-words">{[row.loadId && `Load ${row.loadId}`, row.bonNo && `Bon ${row.bonNo}`, row.queue && `Antrian ${row.queue}`, row.suratJalanNo && `SJ ${row.suratJalanNo}`, row.stackCode && `Tumpukan ${row.stackCode}`].filter(Boolean).join(' · ')}</div></div></div>
          </div>)}
        </div>
      )}
    </div>
  );
};

export default OutboundDocumentIntegrityPanel;
