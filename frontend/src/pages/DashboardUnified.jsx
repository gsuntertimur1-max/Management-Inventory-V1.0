import React, { useMemo } from 'react';
import { Boxes, Layers3, RefreshCcw, ShoppingBag, Warehouse } from 'lucide-react';
import Dashboard from './Dashboard';
import './DashboardUnified.css';
import { useData } from '../context/DataContext';
import { formatNum } from '../mock';
import { roleDestination } from '../lib/permissions';

const addByUnit = (target, unit, qty) => {
  const key = String(unit || 'Unit').trim() || 'Unit';
  target[key] = (target[key] || 0) + Number(qty || 0);
};

const mergeTotals = (...totals) => totals.reduce((result, source) => {
  Object.entries(source).forEach(([unit, qty]) => { result[unit] = (result[unit] || 0) + Number(qty || 0); });
  return result;
}, {});

const formatTotals = (totals) => {
  const rows = Object.entries(totals).filter(([, qty]) => Math.abs(Number(qty || 0)) > 1e-9).sort(([a], [b]) => a.localeCompare(b, 'id'));
  return rows.length ? rows.map(([unit, qty]) => `${formatNum(qty)} ${unit}`).join(' + ') : '0';
};

const SummaryCard = ({ icon: Icon, label, value, accent }) => <div className="card-surface p-5">
  <div className="flex items-start justify-between gap-3"><div><div className="label-mono">{label}</div><div className="font-display text-2xl font-bold mt-2 leading-tight">{value}</div></div><div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0" style={{ background: `${accent}1f`, color: accent }}><Icon size={20} /></div></div>
</div>;

const DashboardUnified = () => {
  const { user, products, consignmentStock, monitoringStock, consignmentLastSync, consignmentSyncing, refreshConsignmentFlow } = useData();
  const scopedDestination = roleDestination(user?.role);
  const syncLabel = consignmentLastSync
    ? consignmentLastSync.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : 'belum sinkron';

  const SyncStatus = () => <div className="flex flex-wrap items-center gap-2 text-xs text-[#8b93a1]">
    <span>Auto-sync 15 detik · terakhir {syncLabel}</span>
    <button
      type="button"
      onClick={() => refreshConsignmentFlow().catch(() => {})}
      disabled={consignmentSyncing}
      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-[#243044] text-[#93c5fd] disabled:opacity-50"
    >
      <RefreshCcw size={12} className={consignmentSyncing ? 'animate-spin' : ''}/>
      {consignmentSyncing ? 'Sinkron…' : 'Sinkron sekarang'}
    </button>
  </div>;

  const totals = useMemo(() => {
    const main = {};
    const bazar = {};
    const ecommerce = {};
    (products || []).forEach((product) => addByUnit(main, product.unit, product.stock));
    (consignmentStock || []).forEach((item) => {
      if (item.destination === 'Gudang Bazar') addByUnit(bazar, item.unit, item.qty);
      if (item.destination === 'Gudang E-commerce') addByUnit(ecommerce, item.unit, item.qty);
    });
    return { main, bazar, ecommerce, physical: mergeTotals(main, bazar, ecommerce) };
  }, [products, consignmentStock]);

  if (scopedDestination) {
    const isBazar = scopedDestination === 'Gudang Bazar';
    const own = isBazar ? totals.bazar : totals.ecommerce;
    const rows = (monitoringStock || []).filter((item) => item.location === scopedDestination);
    return <div className="dashboard-unified space-y-6">
      <section>
        <div className="flex flex-wrap items-center justify-between gap-3 mb-2"><div className="label-mono">Area Kerja</div><SyncStatus /></div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <SummaryCard icon={isBazar ? ShoppingBag : Boxes} label={isBazar ? 'Stok Bazar' : 'Stok E-commerce'} value={formatTotals(own)} accent={isBazar ? '#f59e0b' : '#0ea5e9'} />
          <SummaryCard icon={Layers3} label="Ruang Lingkup Akses" value={isBazar ? 'BAZAR' : 'E-COM'} accent="#22c55e" />
        </div>
      </section>
      <section className="card-surface p-6">
        <div className="flex items-center justify-between gap-3 mb-4"><div><div className="label-mono text-[10px]">Monitoring Lokasi</div><h2 className="font-display text-xl font-bold mt-1">{scopedDestination}</h2></div><span className="text-xs px-2.5 py-1 rounded-full bg-[#2563eb]/15 text-[#60a5fa]">{rows.length} baris</span></div>
        {rows.length === 0 ? <p className="text-sm text-[#8b93a1]">Belum ada stok aktif pada lokasi ini.</p> : <div className="overflow-x-auto"><table className="w-full text-sm tbl"><thead><tr className="text-left border-b border-[#1a222e]"><th className="py-2.5 pr-3">SKU</th><th className="py-2.5 pr-3">Komoditi</th><th className="py-2.5 pr-3">Saluran</th><th className="py-2.5">Saldo</th></tr></thead><tbody>{rows.map((item) => <tr key={`${item.productId}-${item.channel}`} className="border-b border-[#131a24]"><td className="py-3 pr-3 font-mono text-xs text-[#93c5fd]">{item.sku || '—'}</td><td className="py-3 pr-3 font-medium">{item.name}</td><td className="py-3 pr-3">{item.channel}</td><td className="py-3 font-mono">{formatNum(item.qty)} {item.unit}</td></tr>)}</tbody></table></div>}
      </section>
    </div>;
  }

  return <div className="dashboard-unified space-y-6">
    <section>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2"><div className="label-mono">Posisi Persediaan Fisik</div><SyncStatus /></div>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <SummaryCard icon={Warehouse} label="Stok Gudang Utama" value={formatTotals(totals.main)} accent="#3b82f6" />
        <SummaryCard icon={ShoppingBag} label="Stok Bazar" value={formatTotals(totals.bazar)} accent="#f59e0b" />
        <SummaryCard icon={Boxes} label="Stok E-commerce" value={formatTotals(totals.ecommerce)} accent="#0ea5e9" />
        <SummaryCard icon={Layers3} label="Total Stok Fisik" value={formatTotals(totals.physical)} accent="#22c55e" />
      </div>
    </section>
    <Dashboard />
  </div>;
};

export default DashboardUnified;
