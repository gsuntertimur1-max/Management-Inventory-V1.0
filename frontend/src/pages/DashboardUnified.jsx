import React, { useMemo } from 'react';
import { Boxes, Layers3, Warehouse } from 'lucide-react';
import Dashboard from './Dashboard';
import './DashboardUnified.css';
import { useData } from '../context/DataContext';
import { formatNum } from '../mock';

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

const SummaryCard = ({ icon: Icon, label, value, note, accent }) => <div className="card-surface p-5">
  <div className="flex items-start justify-between gap-3"><div><div className="label-mono">{label}</div><div className="font-display text-2xl font-bold mt-2 leading-tight">{value}</div></div><div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0" style={{ background: `${accent}1f`, color: accent }}><Icon size={20} /></div></div>
  <div className="text-xs text-[#8b93a1] mt-3">{note}</div>
</div>;

const DashboardUnified = () => {
  const { products, consignmentStock } = useData();

  const totals = useMemo(() => {
    const main = {};
    const consignment = {};
    (products || []).forEach((product) => addByUnit(main, product.unit, product.stock));
    (consignmentStock || []).forEach((item) => addByUnit(consignment, item.unit, item.qty));
    return { main, consignment, physical: mergeTotals(main, consignment) };
  }, [products, consignmentStock]);

  return <div className="dashboard-unified space-y-6">
    <section>
      <div className="label-mono mb-2">Posisi Persediaan Fisik</div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <SummaryCard icon={Warehouse} label="Stok Gudang Utama" value={formatTotals(totals.main)} note="Saldo yang masih berada di GBB/MP1. Tidak termasuk Bazar dan E-commerce." accent="#3b82f6" />
        <SummaryCard icon={Boxes} label="Stok Bazar / E-commerce" value={formatTotals(totals.consignment)} note="Saldo fisik pada sub-ledger Bazar dan E-commerce." accent="#f59e0b" />
        <SummaryCard icon={Layers3} label="Total Stok Fisik" value={formatTotals(totals.physical)} note="Gudang Utama + Bazar + E-commerce. Perpindahan lokasi tidak menambah total." accent="#22c55e" />
      </div>
    </section>
    <Dashboard />
  </div>;
};

export default DashboardUnified;
