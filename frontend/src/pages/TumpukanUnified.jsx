import React, { useEffect, useMemo, useState } from 'react';
import { ArrowLeftRight, Building2, Search, ShoppingBag, Store, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import TumpukanWithLotStatus from './TumpukanWithLotStatus';
import ConsignmentLocationMap from './ConsignmentLocationMap';
import { useData } from '../context/DataContext';
import { roleDestination } from '../lib/permissions';
import { formatNum } from '../mock';
import { packagingText, totalWeight } from '../lib/packaging';

const LOCATIONS = [
  { key: 'MAIN', label: 'Gudang Utama', icon: Building2 },
  { key: 'BAZAR', label: 'Bazar', icon: Store },
  { key: 'ECOM', label: 'E-commerce', icon: ShoppingBag },
];

const TumpukanUnified = () => {
  const navigate = useNavigate();
  const { user, canWrite, products, stackAllocations, consignmentStock, consignmentLayouts } = useData();
  const scopedDestination = roleDestination(user?.role);
  const forcedLocation = scopedDestination === 'Gudang Bazar' ? 'BAZAR' : scopedDestination === 'Gudang E-commerce' ? 'ECOM' : '';
  const [location, setLocation] = useState(forcedLocation || 'MAIN');
  const [stockQuery, setStockQuery] = useState('');
  const [stockLocationFilter, setStockLocationFilter] = useState(forcedLocation || 'ALL');

  useEffect(() => {
    if (forcedLocation) setLocation(forcedLocation);
  }, [forcedLocation]);

  const visibleLocations = forcedLocation ? LOCATIONS.filter((item) => item.key === forcedLocation) : LOCATIONS;

  const productById = useMemo(() => Object.fromEntries((products || []).map((item) => [item.id, item])), [products]);

  const stockSearchRows = useMemo(() => {
    const rows = [];
    const mainAllocated = {};
    const consignmentAllocated = {};

    (stackAllocations || []).forEach((item) => {
      const qty = Number(item.primaryQty || 0);
      if (qty <= 0) return;
      const product = productById[item.productId] || {};
      mainAllocated[item.productId] = Number(mainAllocated[item.productId] || 0) + qty;
      rows.push({
        key: `MAIN-${item.id || item.stackCode + '-' + item.productId}`,
        areaKey: 'MAIN',
        area: 'Gudang Utama',
        stackCode: item.stackCode || '—',
        productId: item.productId,
        name: product.name || item.productName || item.product || 'Komoditi',
        sku: product.sku || item.sku || '',
        qty,
        unit: product.unit || item.unit || '',
        product,
        mapped: true,
      });
    });

    (products || []).forEach((product) => {
      const balance = Number(product.stock || 0);
      const allocated = Number(mainAllocated[product.id] || 0);
      const unallocated = Math.max(balance - allocated, 0);
      if (unallocated <= 1e-9) return;
      rows.push({
        key: `MAIN-UNMAPPED-${product.id}`,
        areaKey: 'MAIN',
        area: 'Gudang Utama',
        stackCode: 'Belum ditempatkan',
        productId: product.id,
        name: product.name || 'Komoditi',
        sku: product.sku || '',
        qty: unallocated,
        unit: product.unit || '',
        product,
        mapped: false,
      });
    });

    (consignmentLayouts || []).forEach((layout) => {
      const qty = Number(layout.primaryQty ?? 0);
      if (qty <= 0) return;
      const areaKey = layout.destination === 'Gudang Bazar' ? 'BAZAR' : layout.destination === 'Gudang E-commerce' ? 'ECOM' : '';
      if (!areaKey) return;
      const mapKey = `${layout.destination}|${layout.productId}`;
      consignmentAllocated[mapKey] = Number(consignmentAllocated[mapKey] || 0) + qty;
      const product = productById[layout.productId] || {};
      rows.push({
        key: `${areaKey}-${layout.id || layout.stackCode + '-' + layout.productId}`,
        areaKey,
        area: layout.destination,
        stackCode: layout.stackCode || 'Belum terpetakan',
        productId: layout.productId,
        name: product.name || layout.productName || 'Komoditi',
        sku: product.sku || layout.sku || '',
        qty,
        unit: product.unit || layout.unit || '',
        product: { ...product, secondary: layout.secondary || product.secondary, secondaryQty: Number(layout.secondaryQty ?? product.secondaryQty ?? 0) },
        mapped: true,
      });
    });

    (consignmentStock || []).forEach((item) => {
      const areaKey = item.destination === 'Gudang Bazar' ? 'BAZAR' : item.destination === 'Gudang E-commerce' ? 'ECOM' : '';
      if (!areaKey) return;
      const balance = Number(item.qty || 0);
      const allocated = Number(consignmentAllocated[`${item.destination}|${item.productId}`] || 0);
      const unallocated = Math.max(balance - allocated, 0);
      if (unallocated <= 1e-9) return;
      const product = productById[item.productId] || {};
      rows.push({
        key: `${areaKey}-UNMAPPED-${item.productId}`,
        areaKey,
        area: item.destination,
        stackCode: 'Belum terpetakan',
        productId: item.productId,
        name: product.name || item.name || 'Komoditi',
        sku: product.sku || item.sku || '',
        qty: unallocated,
        unit: product.unit || item.unit || '',
        product: { ...product, secondary: item.secondary || product.secondary, secondaryQty: Number(item.secondaryQty ?? product.secondaryQty ?? 0) },
        mapped: false,
      });
    });

    return rows;
  }, [products, stackAllocations, consignmentStock, consignmentLayouts, productById]);

  const normalizedStockQuery = stockQuery.trim().toLowerCase();
  const stockSearchResults = useMemo(() => {
    if (normalizedStockQuery.length < 2) return [];
    return stockSearchRows
      .filter((row) => {
        if (forcedLocation && row.areaKey !== forcedLocation) return false;
        if (!forcedLocation && stockLocationFilter !== 'ALL' && row.areaKey !== stockLocationFilter) return false;
        return `${row.name} ${row.sku}`.toLowerCase().includes(normalizedStockQuery);
      })
      .sort((a, b) => a.name.localeCompare(b.name, 'id')
        || a.area.localeCompare(b.area, 'id')
        || String(a.stackCode).localeCompare(String(b.stackCode), 'id', { numeric: true }));
  }, [stockSearchRows, normalizedStockQuery, stockLocationFilter, forcedLocation]);

  const stockSearchTotals = useMemo(() => {
    const byUnit = {};
    let weight = 0;
    stockSearchResults.forEach((row) => {
      const unit = row.unit || 'Unit';
      byUnit[unit] = Number(byUnit[unit] || 0) + Number(row.qty || 0);
      weight += totalWeight(row.qty, row.product);
    });
    return { byUnit, weight };
  }, [stockSearchResults]);

  const totalQtyLabel = Object.entries(stockSearchTotals.byUnit)
    .map(([unit, qty]) => `${formatNum(qty)} ${unit}`)
    .join(' + ');

  return <div className="space-y-5">
    <section className="card-surface p-5 border border-[#2563eb]/30">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <div className="label-mono text-[10px] text-[#93c5fd]">Pencarian Lokasi Stok</div>
          <h2 className="font-display text-xl font-bold mt-1">Cari Produk di Semua Tumpukan</h2>
          <p className="text-xs text-[#8b93a1] mt-1">Cari nama produk atau SKU untuk melihat posisi fisik dan jumlah per tumpukan.</p>
        </div>
        {normalizedStockQuery.length >= 2 && <div className="text-right text-xs text-[#8b93a1]">
          <div><b className="text-[#e5e7eb]">{stockSearchResults.length}</b> lokasi/baris</div>
          {totalQtyLabel && <div className="mt-1">Total: <b className="text-[#86efac]">{totalQtyLabel}</b>{stockSearchTotals.weight > 0 ? <> · <b className="text-[#93c5fd]">{formatNum(stockSearchTotals.weight)} kg</b></> : null}</div>}
        </div>}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_210px] gap-3">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" />
          <input
            value={stockQuery}
            onChange={(e) => setStockQuery(e.target.value)}
            placeholder="Contoh: Punokawan 10 KG atau kode SKU..."
            className="w-full bg-[#0b0f17] border border-[#294263] rounded-lg pl-9 pr-10 py-3 text-sm outline-none focus:border-[#3b82f6]"
          />
          {stockQuery && <button type="button" onClick={() => setStockQuery('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-[#6b7688] hover:text-white" title="Hapus pencarian"><X size={15}/></button>}
        </div>
        {!forcedLocation && <select value={stockLocationFilter} onChange={(e) => setStockLocationFilter(e.target.value)} className="bg-[#0b0f17] border border-[#294263] rounded-lg px-3 py-3 text-sm outline-none focus:border-[#3b82f6]">
          <option value="ALL">Semua Lokasi</option>
          <option value="MAIN">Gudang Utama</option>
          <option value="BAZAR">Bazar</option>
          <option value="ECOM">E-commerce</option>
        </select>}
      </div>

      {normalizedStockQuery.length > 0 && normalizedStockQuery.length < 2 && <div className="mt-3 text-xs text-[#8b93a1]">Ketik minimal 2 karakter untuk mulai mencari.</div>}

      {normalizedStockQuery.length >= 2 && <div className="mt-4">
        {stockSearchResults.length === 0 ? <div className="rounded-xl border border-dashed border-[#334155] p-6 text-center text-sm text-[#8b93a1]">Produk tidak ditemukan pada lokasi stok yang dipilih.</div> : <div className="overflow-x-auto rounded-xl border border-[#243044]">
          <table className="w-full min-w-[900px] text-sm">
            <thead className="bg-[#111827] text-left text-xs text-[#94a3b8]">
              <tr>
                <th className="px-3 py-2.5">Produk</th>
                <th className="px-3 py-2.5">Lokasi</th>
                <th className="px-3 py-2.5">Tumpukan</th>
                <th className="px-3 py-2.5 text-right">Qty</th>
                <th className="px-3 py-2.5">Kemasan</th>
                <th className="px-3 py-2.5 text-right">Berat</th>
                <th className="px-3 py-2.5">Status Lokasi</th>
              </tr>
            </thead>
            <tbody>
              {stockSearchResults.map((row) => {
                const packaging = packagingText(row.qty, row.product, formatNum);
                const weight = totalWeight(row.qty, row.product);
                return <tr key={row.key} className="border-t border-[#1f2937]">
                  <td className="px-3 py-3"><div className="font-medium">{row.name}</div><div className="font-mono text-[10px] text-[#6b7688] mt-0.5">{row.sku || '—'}</div></td>
                  <td className="px-3 py-3 whitespace-nowrap"><span className={`text-xs px-2 py-1 rounded-full ${row.areaKey === 'MAIN' ? 'bg-[#2563eb]/15 text-[#60a5fa]' : row.areaKey === 'BAZAR' ? 'bg-[#f59e0b]/15 text-[#fbbf24]' : 'bg-[#0ea5e9]/15 text-[#38bdf8]'}`}>{row.area}</span></td>
                  <td className="px-3 py-3 font-mono font-semibold whitespace-nowrap">{row.stackCode}</td>
                  <td className="px-3 py-3 font-mono text-right whitespace-nowrap">{formatNum(row.qty)} {row.unit}</td>
                  <td className="px-3 py-3 text-xs">{packaging || '—'}</td>
                  <td className="px-3 py-3 font-mono text-right whitespace-nowrap">{weight > 0 ? `${formatNum(weight)} ${row.product?.measureUnit || 'kg'}` : '—'}</td>
                  <td className="px-3 py-3">{row.mapped ? <span className="text-xs text-[#86efac]">Terpetakan</span> : <span className="text-xs text-[#fbbf24]">{row.areaKey === 'MAIN' ? 'Belum ditempatkan' : 'Belum terpetakan'}</span>}</td>
                </tr>;
              })}
            </tbody>
          </table>
        </div>}
      </div>}
    </section>

    <section className="card-surface p-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="label-mono mr-2">Lokasi Persediaan</div>
        {visibleLocations.map((item) => <button key={item.key} type="button" onClick={() => setLocation(item.key)} className={`inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors ${location === item.key ? 'bg-[#2563eb] text-white' : 'bg-[#1e293b] text-[#94a3b8] hover:text-white'}`}><item.icon size={16} />{item.label}</button>)}
        {!forcedLocation && canWrite && <button type="button" onClick={() => navigate('/mutasi-tumpukan')} className="ml-auto inline-flex items-center gap-2 rounded-lg border border-[#3b82f6] px-4 py-2.5 text-sm font-semibold text-[#93c5fd] hover:bg-[#2563eb]/10"><ArrowLeftRight size={16} />Mutasi Tumpukan</button>}
      </div>
    </section>

    {location === 'MAIN' && !forcedLocation && <TumpukanWithLotStatus />}
    {location === 'BAZAR' && <ConsignmentLocationMap destination="Gudang Bazar" />}
    {location === 'ECOM' && <ConsignmentLocationMap destination="Gudang E-commerce" />}
  </div>;
};

export default TumpukanUnified;
