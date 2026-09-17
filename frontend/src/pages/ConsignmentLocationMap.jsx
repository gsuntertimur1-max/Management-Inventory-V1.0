import React, { useMemo } from 'react';
import { Boxes, FileText, MapPin, PackageSearch, Warehouse } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatNum } from '../mock';

const arrangementText = (layout, secondary, secondaryQty) => {
  if (!layout) return 'Perkalian belum dicatat';
  const rows = layout.arrangements || [];
  const secondaryCount = rows.reduce((sum, row) => sum + Number(row.hamparan || 0) * Number(row.kaki || 0) * Number(row.height || 0), 0) + Number(layout.extraSecondary || 0);
  const primary = secondaryCount * Number(secondaryQty || 0) + Number(layout.extraPrimary || 0);
  const detail = rows.map((row) => `${row.hamparan}×${row.kaki}×${row.height}`).join(' + ');
  return `${detail || '0'}${Number(layout.extraSecondary || 0) ? ` + ${formatNum(layout.extraSecondary)} ${secondary || 'sekunder'}` : ''}${Number(layout.extraPrimary || 0) ? ` + ${formatNum(layout.extraPrimary)} primer` : ''} = ${formatNum(primary)} primer`;
};

const ConsignmentLocationMap = ({ destination }) => {
  const { consignmentStock, consignmentLayouts, outboundLoads } = useData();
  const rows = useMemo(
    () => (consignmentStock || []).filter((item) => item.destination === destination).sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'id')),
    [consignmentStock, destination],
  );

  const sourceStacks = useMemo(() => {
    const result = {};
    (outboundLoads || [])
      .filter((load) => load.status === 'Selesai' && load.consignment_destination === destination)
      .forEach((load) => (load.items || []).forEach((item) => {
        if (!item.productId) return;
        const stack = item.stackCode || item.location;
        if (!stack) return;
        result[item.productId] = result[item.productId] || [];
        if (!result[item.productId].includes(stack)) result[item.productId].push(stack);
      }));
    return result;
  }, [outboundLoads, destination]);

  const totalPrimary = rows.reduce((sum, row) => sum + Number(row.qty || 0), 0);
  const totalWeight = rows.reduce((sum, row) => sum + Number(row.totalWeight || 0), 0);
  const label = destination === 'Gudang Bazar' ? 'BAZAR' : 'E-COMMERCE';

  return <div className="space-y-5" data-testid={`consignment-map-${label.toLowerCase()}`}>
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      <div className="card-surface p-4"><div className="label-mono">Lokasi</div><div className="font-display text-xl font-bold mt-2 flex items-center gap-2"><MapPin size={18} className="text-[#60a5fa]" />{destination}</div></div>
      <div className="card-surface p-4"><div className="label-mono">Produk Aktif</div><div className="font-display text-2xl font-bold mt-2">{rows.length}</div><div className="text-xs text-[#8b93a1] mt-1">SKU dengan saldo konsinyasi</div></div>
      <div className="card-surface p-4"><div className="label-mono">Saldo Primer</div><div className="font-display text-2xl font-bold mt-2">{formatNum(totalPrimary)}</div><div className="text-xs text-[#8b93a1] mt-1">Kuantum primer · fisik {formatNum(totalWeight)}</div></div>
    </div>

    <section className="card-surface p-4 md:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div><h2 className="font-display text-xl font-bold">Peta Persediaan {label}</h2><p className="text-xs text-[#8b93a1] mt-1">Lokasi ini adalah sub-ledger persediaan. Saldo di sini tidak menambah stok Gudang Utama; hanya menunjukkan stok fisik yang sudah dipindahkan.</p></div>
        <div className="inline-flex items-center gap-2 rounded-lg border border-[#334155] px-3 py-2 text-xs text-[#93c5fd]"><Warehouse size={15} />Gudang Utama → {label}</div>
      </div>

      {rows.length === 0 ? <div className="rounded-xl border border-dashed border-[#334155] p-10 text-center text-sm text-[#8b93a1]"><PackageSearch size={28} className="mx-auto mb-3 opacity-60" />Belum ada stok aktif di {destination}.</div> : <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {rows.map((item) => {
          const layout = (consignmentLayouts || []).find((row) => row.destination === destination && row.productId === item.productId);
          const origins = sourceStacks[item.productId] || [];
          return <div key={`${destination}-${item.productId}-${item.channel}`} className="rounded-xl border border-[#334155] bg-[#111827]/55 p-4">
            <div className="flex items-start justify-between gap-3"><div><div className="font-semibold leading-5">{item.name}</div><div className="font-mono text-[10px] text-[#93c5fd] mt-1">{item.sku || '—'} · {item.channel || 'KOM'}</div></div><Boxes size={18} className="text-[#60a5fa] shrink-0" /></div>
            <div className="grid grid-cols-2 gap-2 mt-4"><div className="rounded-lg bg-[#0f172a] p-2.5"><div className="text-[10px] text-[#8b93a1]">Saldo</div><div className="font-mono font-bold mt-1">{formatNum(item.qty)} {item.unit}</div></div><div className="rounded-lg bg-[#0f172a] p-2.5"><div className="text-[10px] text-[#8b93a1]">Fisik</div><div className="font-mono font-bold mt-1">{formatNum(item.totalWeight)} {item.measureUnit || 'kg'}</div></div></div>
            <div className="mt-3 text-xs"><div className="text-[#8b93a1]">Perkalian / susunan</div><div className="font-mono text-[11px] mt-1 text-[#d9e3ef]">{arrangementText(layout, item.secondary, item.secondaryQty)}</div></div>
            <div className="mt-3 pt-3 border-t border-[#334155] text-xs space-y-2"><div className="flex gap-2"><MapPin size={13} className="mt-0.5 text-[#f59e0b] shrink-0" /><span><span className="text-[#8b93a1]">Asal terakhir:</span> {origins.length ? origins.join(', ') : 'tidak tercatat pada data lama'}</span></div><div className="flex gap-2"><FileText size={13} className="mt-0.5 text-[#60a5fa] shrink-0" /><span><span className="text-[#8b93a1]">Dokumen:</span> {(item.documents || []).join(', ') || '—'}</span></div></div>
          </div>;
        })}
      </div>}
    </section>
  </div>;
};

export default ConsignmentLocationMap;
