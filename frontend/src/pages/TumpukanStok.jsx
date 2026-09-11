import React from 'react';
import { useData } from '../context/DataContext';
import { catColor, formatNum, formatRp } from '../mock';
import { packagingText, totalWeight } from '../lib/packaging';

const TumpukanStok = () => {
  const { products } = useData();
  // Group by location zone (first char / rak)
  const zones = {};
  products.forEach((p) => { const zone = p.location.split(' ')[0] === 'Rak' ? p.location.split('-')[0].trim() : p.location; (zones[zone] = zones[zone] || []).push(p); });

  return (
    <div className="space-y-6">
      <div>
        <div className="label-mono mb-2">Tata Letak Gudang</div>
        <h1 className="font-display text-4xl font-bold">Tumpukan Stok per Lokasi</h1>
        <p className="text-[#8b93a1] mt-2">Visualisasi sebaran barang berdasarkan rak & zona penyimpanan</p>
      </div>

      {Object.keys(zones).length === 0 ? (
        <div className="card-surface p-8 text-center text-[#6b7688]">Belum ada produk terdaftar. Muat data contoh untuk melihat tata letak.</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {Object.entries(zones).sort().map(([zone, items]) => {
            const totalUnits = items.reduce((a, p) => a + p.stock, 0);
            return (
              <div key={zone} className="card-surface stat-card p-5">
                <div className="flex items-center justify-between mb-4">
                  <div className="font-display font-bold text-lg">{zone}</div>
                  <span className="label-mono text-[9px]">{formatNum(totalUnits)} unit</span>
                </div>
                <div className="space-y-2">
                  {items.map((p) => (
                    <div key={p.id} className="p-3 rounded-lg bg-[#0b0f17] border border-[#151d28]">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium truncate pr-2">{p.name}</span>
                        <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: catColor(p.category) }} />
                      </div>
                      <div className="flex items-center justify-between mt-1.5">
                        <span className="label-mono text-[9px]">{p.location}</span>
                        <span className="font-mono text-xs text-[#aab4c4]">{formatNum(p.stock)} {p.unit}</span>
                      </div>
                      {(packagingText(p.stock, p, formatNum) || Number(p.weight || 0) > 0) && <div className="text-[10px] text-[#6b7688] mt-1">{packagingText(p.stock, p, formatNum)}{packagingText(p.stock, p, formatNum) && Number(p.weight || 0) > 0 ? ' · ' : ''}{Number(p.weight || 0) > 0 ? `${formatNum(totalWeight(p.stock, p))} kg` : ''}</div>}
                      <div className="h-1.5 rounded-full bg-[#151d28] mt-2 overflow-hidden"><div className="h-full rounded-full" style={{ width: `${Math.min((p.stock / (p.min * 4 || 100)) * 100, 100)}%`, background: catColor(p.category) }} /></div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default TumpukanStok;
