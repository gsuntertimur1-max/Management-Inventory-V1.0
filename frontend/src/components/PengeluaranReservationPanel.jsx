import React, { useMemo } from 'react';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatNum } from '../mock';

const EPS = 1e-9;
const ACTIVE_STATUSES = new Set(['Menunggu', 'Sedang Dimuat']);
const normalizeStack = (value) => String(value || '').trim().toUpperCase();
const stackKey = (productId, stackCode) => `${String(productId || '')}|${normalizeStack(stackCode)}`;

const PengeluaranReservationPanel = () => {
  const { outboundLoads, stackAllocations } = useData();

  const { rows, missingStacks } = useMemo(() => {
    const physical = new Map();
    (stackAllocations || []).forEach((allocation) => {
      const productId = String(allocation.productId || '');
      const code = normalizeStack(allocation.stackCode);
      if (!productId || !code) return;
      const key = stackKey(productId, code);
      physical.set(key, (physical.get(key) || 0) + Number(allocation.primaryQty || 0));
    });

    const reserved = new Map();
    const missing = [];
    (outboundLoads || []).forEach((load) => {
      if (!ACTIVE_STATUSES.has(load.status) || String(load.kondisi || 'BAIK').toUpperCase() !== 'BAIK') return;
      (load.items || []).forEach((item) => {
        const productId = String(item.productId || '');
        const qty = Number(item.qty || 0);
        if (!productId || qty <= EPS) return;
        const code = normalizeStack(item.stackCode);
        if (!code) {
          missing.push({
            key: `${load.id}-${productId}-${missing.length}`,
            queue: load.antrian || load.ref || '—',
            name: item.name || item.sku || productId,
            qty,
            unit: item.unit || '',
          });
          return;
        }
        const key = stackKey(productId, code);
        const current = reserved.get(key) || {
          productId,
          stackCode: code,
          name: item.name || item.sku || productId,
          sku: item.sku || '',
          unit: item.unit || '',
          reserved: 0,
          queues: [],
        };
        current.reserved += qty;
        const queue = load.antrian || load.ref || load.id;
        if (queue && !current.queues.includes(queue)) current.queues.push(queue);
        reserved.set(key, current);
      });
    });

    const reservationRows = Array.from(reserved.entries()).map(([key, row]) => {
      const physicalQty = Number(physical.get(key) || 0);
      const available = physicalQty - row.reserved;
      return { ...row, physical: physicalQty, available, overReserved: available < -EPS };
    }).sort((a, b) => a.stackCode.localeCompare(b.stackCode) || a.name.localeCompare(b.name));

    return { rows: reservationRows, missingStacks: missing };
  }, [outboundLoads, stackAllocations]);

  const overReserved = rows.filter((row) => row.overReserved);
  if (!rows.length && !missingStacks.length) return null;

  return (
    <div className={`card-surface p-5 border ${overReserved.length || missingStacks.length ? 'border-[#7f1d1d]' : 'border-[#294263]'}`}>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <div className="label-mono text-[10px] text-[#93c5fd]">Kontrol Reservasi Pengeluaran</div>
          <h2 className="font-display text-xl font-bold mt-1">Fisik | Reservasi | Tersedia</h2>
          <p className="text-xs text-[#8b93a1] mt-1">Saldo stok Baik per tumpukan untuk antrean Menunggu dan Sedang Dimuat.</p>
        </div>
        {overReserved.length || missingStacks.length ? (
          <div className="inline-flex items-center gap-2 rounded-lg border border-[#7f1d1d] bg-[#7f1d1d]/25 px-3 py-2 text-xs font-semibold text-[#fca5a5]">
            <AlertTriangle size={15} />
            {overReserved.length ? `${overReserved.length} over-reserved` : ''}{overReserved.length && missingStacks.length ? ' · ' : ''}{missingStacks.length ? `${missingStacks.length} tanpa tumpukan` : ''}
          </div>
        ) : (
          <div className="inline-flex items-center gap-2 rounded-lg border border-[#14532d] bg-[#14532d]/20 px-3 py-2 text-xs font-semibold text-[#86efac]"><CheckCircle2 size={15} /> Reservasi aman</div>
        )}
      </div>

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
            {rows.map((row) => <tr key={`${row.productId}-${row.stackCode}`} className={`border-b border-[#131a24] ${row.overReserved ? 'bg-[#7f1d1d]/10' : ''}`}><td className="py-2.5 pr-4 font-mono font-semibold text-[#93c5fd] whitespace-nowrap">{row.stackCode}</td><td className="py-2.5 pr-4"><div className="font-semibold">{row.name}</div>{row.sku && <div className="label-mono text-[9px]">{row.sku}</div>}</td><td className="py-2.5 pr-4 text-right font-mono whitespace-nowrap">{formatNum(row.physical)} {row.unit}</td><td className="py-2.5 pr-4 text-right font-mono text-[#fbbf24] whitespace-nowrap">{formatNum(row.reserved)} {row.unit}</td><td className={`py-2.5 pr-4 text-right font-mono font-bold whitespace-nowrap ${row.overReserved ? 'text-[#ef4444]' : 'text-[#4ade80]'}`}>{formatNum(row.available)} {row.unit}{row.overReserved && <div className="text-[9px]">OVER-RESERVED</div>}</td><td className="py-2.5 font-mono text-[10px] min-w-[150px]">{row.queues.join(', ') || '—'}</td></tr>)}
            {!rows.length && <tr><td colSpan={6} className="py-5 text-center text-[#8b93a1]">Belum ada reservasi dengan tumpukan sumber.</td></tr>}
          </tbody>
        </table>
      </div>

      {missingStacks.length > 0 && <div className="mt-4 rounded-xl border border-[#7f1d1d] bg-[#7f1d1d]/10 p-4"><div className="font-semibold text-sm text-[#fca5a5]">Reservasi aktif tanpa tumpukan sumber</div><div className="mt-2 space-y-1">{missingStacks.map((item) => <div key={item.key} className="text-xs text-[#fca5a5]"><span className="font-mono">{item.queue}</span> · {item.name} · {formatNum(item.qty)} {item.unit}</div>)}</div></div>}
    </div>
  );
};

export default PengeluaranReservationPanel;
