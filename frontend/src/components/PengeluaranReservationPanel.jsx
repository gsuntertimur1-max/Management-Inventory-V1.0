import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatNum } from '../mock';
import api from '../lib/api';

const PengeluaranReservationPanel = () => {
  const { outboundLoads } = useData();
  const [data, setData] = useState({ rows: [], unassigned: [], summary: {} });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  const loadReservations = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    try {
      const response = await api.get('/outbound-reservations');
      setData(response.data || { rows: [], unassigned: [], summary: {} });
      setLoadError('');
    } catch (error) {
      setLoadError(error?.response?.data?.detail || 'Kontrol reservasi belum dapat dimuat dari server.');
    } finally {
      if (showSpinner) setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadReservations(true);
  }, [loadReservations]);

  useEffect(() => {
    if (!loading) loadReservations(false);
    // Refresh after outbound context changes so the server remains the source of truth.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outboundLoads]);

  useEffect(() => {
    const timer = window.setInterval(() => loadReservations(false), 15000);
    return () => window.clearInterval(timer);
  }, [loadReservations]);

  const rows = data.rows || [];
  const missingStacks = data.unassigned || [];
  const overReserved = rows.filter((row) => row.overReserved);

  if (loading && !rows.length && !missingStacks.length) {
    return (
      <div className="card-surface p-5 border border-[#294263] text-sm text-[#8b93a1] flex items-center gap-2">
        <RefreshCw size={15} className="animate-spin" /> Memeriksa reservasi tumpukan dari server...
      </div>
    );
  }

  if (!rows.length && !missingStacks.length && !loadError) return null;

  return (
    <div className={`card-surface p-5 border ${overReserved.length || missingStacks.length || loadError ? 'border-[#7f1d1d]' : 'border-[#294263]'}`}>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <div className="label-mono text-[10px] text-[#93c5fd]">Kontrol Reservasi Pengeluaran</div>
          <h2 className="font-display text-xl font-bold mt-1">Fisik | Reservasi | Tersedia</h2>
          <p className="text-xs text-[#8b93a1] mt-1">Saldo stok Baik per tumpukan dari server untuk antrean Menunggu dan Sedang Dimuat.</p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => loadReservations(true)} className="inline-flex items-center gap-1.5 rounded-lg border border-[#294263] px-3 py-2 text-xs text-[#93c5fd] hover:bg-[#172033]">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Perbarui
          </button>
          {overReserved.length || missingStacks.length || loadError ? (
            <div className="inline-flex items-center gap-2 rounded-lg border border-[#7f1d1d] bg-[#7f1d1d]/25 px-3 py-2 text-xs font-semibold text-[#fca5a5]">
              <AlertTriangle size={15} />
              {loadError ? 'Data reservasi bermasalah' : <>{overReserved.length ? `${overReserved.length} over-reserved` : ''}{overReserved.length && missingStacks.length ? ' · ' : ''}{missingStacks.length ? `${missingStacks.length} tanpa tumpukan` : ''}</>}
            </div>
          ) : (
            <div className="inline-flex items-center gap-2 rounded-lg border border-[#14532d] bg-[#14532d]/20 px-3 py-2 text-xs font-semibold text-[#86efac]"><CheckCircle2 size={15} /> Reservasi aman</div>
          )}
        </div>
      </div>

      {loadError && (
        <div className="mb-4 rounded-xl border border-[#7f1d1d] bg-[#7f1d1d]/20 px-4 py-3 text-sm text-[#fca5a5]">
          <div className="font-semibold">Kontrol reservasi tidak sinkron</div>
          <div className="mt-1 text-xs">{loadError} Jangan mulai pemuatan sebelum panel ini berhasil dimuat kembali.</div>
        </div>
      )}

      {overReserved.length > 0 && (
        <div className="mb-4 rounded-xl border border-[#7f1d1d] bg-[#7f1d1d]/20 px-4 py-3 text-sm text-[#fca5a5]">
          <div className="font-semibold">Alarm over-reserved</div>
          <div className="mt-1 text-xs">Reservasi aktif sudah melebihi stok fisik pada {overReserved.length} tumpukan. Jangan lanjutkan pemuatan terkait sebelum reservasi dikoreksi.</div>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-xs tbl">
          <thead><tr className="text-left border-b border-[#1a222e]"><th className="py-2.5 pr-4">Tumpukan</th><th className="py-2.5 pr-4">Produk</th><th className="py-2.5 pr-4 text-right">Fisik</th><th className="py-2.5 pr-4 text-right">Reservasi</th><th className="py-2.5 pr-4 text-right">Tersedia</th><th className="py-2.5">Antrian</th></tr></thead>
          <tbody>
            {rows.map((row) => <tr key={`${row.productId}-${row.stackCode}`} className={`border-b border-[#131a24] ${row.overReserved ? 'bg-[#7f1d1d]/10' : ''}`}><td className="py-2.5 pr-4 font-mono font-semibold text-[#93c5fd] whitespace-nowrap">{row.stackCode}</td><td className="py-2.5 pr-4"><div className="font-semibold">{row.name}</div>{row.sku && <div className="label-mono text-[9px]">{row.sku}</div>}</td><td className="py-2.5 pr-4 text-right font-mono whitespace-nowrap">{formatNum(row.physical)} {row.unit}</td><td className="py-2.5 pr-4 text-right font-mono text-[#fbbf24] whitespace-nowrap">{formatNum(row.reserved)} {row.unit}</td><td className={`py-2.5 pr-4 text-right font-mono font-bold whitespace-nowrap ${row.overReserved ? 'text-[#ef4444]' : 'text-[#4ade80]'}`}>{formatNum(row.available)} {row.unit}{row.overReserved && <div className="text-[9px]">OVER-RESERVED</div>}</td><td className="py-2.5 font-mono text-[10px] min-w-[150px]">{(row.queues || []).join(', ') || '—'}</td></tr>)}
            {!rows.length && <tr><td colSpan={6} className="py-5 text-center text-[#8b93a1]">Belum ada reservasi dengan tumpukan sumber.</td></tr>}
          </tbody>
        </table>
      </div>

      {missingStacks.length > 0 && <div className="mt-4 rounded-xl border border-[#7f1d1d] bg-[#7f1d1d]/10 p-4"><div className="font-semibold text-sm text-[#fca5a5]">Reservasi aktif tanpa tumpukan sumber</div><div className="mt-2 space-y-1">{missingStacks.map((item, index) => <div key={`${item.loadId}-${item.productId}-${index}`} className="text-xs text-[#fca5a5]"><span className="font-mono">{item.queue || item.ref || '—'}</span> · {item.name || item.sku || item.productId} · {formatNum(item.qty)} {item.unit}</div>)}</div></div>}
    </div>
  );
};

export default PengeluaranReservationPanel;
