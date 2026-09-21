import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layers, AlertTriangle, Search, ClipboardList, ArrowUpRight, ArrowDownRight, Link2, Printer, ChevronDown } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatNum, formatDate } from '../mock';
import { apiError, downloadApiFile } from '../lib/api';
import { toast } from 'sonner';

const StatCard = ({ icon: Icon, label, value, color }) => (
  <div className="card-surface stat-card p-5">
    <div className="w-10 h-10 rounded-xl flex items-center justify-center mb-8" style={{ background: `${color}1f`, color }}><Icon size={20} /></div>
    <div className="label-mono mb-1">{label}</div>
    <div className="font-display text-3xl font-bold">{value}</div>
  </div>
);

const AlertSection = ({ title, count, colorClass, iconClass, open, onToggle, children }) => (
  <div className="card-surface overflow-hidden">
    <button type="button" onClick={onToggle} aria-expanded={open} className="w-full flex items-center justify-between gap-4 p-5 sm:p-6 text-left hover:bg-white/[0.02] transition-colors">
      <div className="flex min-w-0 items-center gap-3">
        <AlertTriangle size={20} className={iconClass} />
        <h2 className="font-display text-lg sm:text-xl font-bold truncate">{title}</h2>
        <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${colorClass}`}>{count} barang</span>
      </div>
      <ChevronDown size={19} className={`shrink-0 text-[#8b93a1] transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
    </button>
    {open && <div className="px-5 sm:px-6 pb-5 sm:pb-6 border-t border-[#1a222e] pt-4">{children}</div>}
  </div>
);

const DashboardDropdown = ({ title, meta, open, onToggle, children }) => (
  <div className="card-surface overflow-hidden border border-[#1f3657]">
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className="w-full flex items-center justify-between gap-4 p-5 sm:p-6 text-left hover:bg-white/[0.02] transition-colors"
    >
      <div className="min-w-0">
        <h2 className="font-display text-lg sm:text-xl font-bold">{title}</h2>
        {meta && <div className="label-mono text-[10px] text-[#8b93a1] mt-1">{meta}</div>}
      </div>
      <ChevronDown size={19} className={`shrink-0 text-[#8b93a1] transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
    </button>
    {open && <div className="px-5 sm:px-6 pb-5 sm:pb-6 border-t border-[#1a222e] pt-4">{children}</div>}
  </div>
);

const Dashboard = () => {
  const { products, transactions, outboundLoads, consignmentStock, monitoringStock, settings } = useData();
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [lowAlertOpen, setLowAlertOpen] = useState(false);
  const [expiryAlertOpen, setExpiryAlertOpen] = useState(false);
  const [pendingDocsOpen, setPendingDocsOpen] = useState(false);
  const [monitoringOpen, setMonitoringOpen] = useState(false);
  const [bazarCardOpen, setBazarCardOpen] = useState(false);
  const [ecomCardOpen, setEcomCardOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);

  const totalUnits = products.reduce((a, p) => a + p.stock, 0);
  const totalDamaged = products.reduce((a, p) => a + (p.damaged || 0), 0);
  const lowStock = products.filter((p) => p.stock <= p.min);

  const expiringProducts = useMemo(() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return products
      .map((product) => {
        if (!product.exp) return null;
        const expiry = new Date(product.exp);
        if (Number.isNaN(expiry.getTime())) return null;
        expiry.setHours(0, 0, 0, 0);
        const days = Math.ceil((expiry - today) / 86400000);
        if (days > 30) return null;
        return { ...product, daysToExpiry: days };
      })
      .filter(Boolean)
      .sort((a, b) => a.daysToExpiry - b.daysToExpiry);
  }, [products]);

  const filtered = (monitoringStock || []).filter((p) => p.name.toLowerCase().includes(q.toLowerCase()) || p.sku.toLowerCase().includes(q.toLowerCase()) || p.location.toLowerCase().includes(q.toLowerCase())).sort((a, b) => `${a.location}-${a.channel}-${a.name}`.localeCompare(`${b.location}-${b.channel}-${b.name}`));
  const sourceDocumentFor = (load, item) => item.documentNo || load.ref || '';
  const linkedUsageFor = (load, sourceDocumentNo, productId) => (load.document_links || []).reduce((total, link) => {
    const linkSource = link.sourceDocumentNo || load.ref || '';
    if (linkSource !== sourceDocumentNo) return total;
    return total + (link.items || []).filter((item) => item.productId === productId).reduce((sum, item) => sum + (['CR', 'RETUR'].includes(link.type) ? Number(item.goodQty || 0) + Number(item.damagedQty || 0) : Number(item.qty || 0)), 0);
  }, 0);
  const remainingDocumentItems = (load) => {
    const grouped = {};
    (load.items || []).forEach((source) => {
      const sourceDocumentNo = sourceDocumentFor(load, source);
      const key = `${sourceDocumentNo}|${source.productId}`;
      grouped[key] = grouped[key] || { ...source, qty: 0, documentNo: sourceDocumentNo };
      grouped[key].qty += Number(source.qty || 0);
    });
    return Object.values(grouped).map((source) => ({ ...source, remaining: Math.max(Number(source.qty || 0) - linkedUsageFor(load, source.documentNo, source.productId), 0) })).filter((item) => item.remaining > 0);
  };
  const pendingDocuments = outboundLoads
    .filter((load) => ['CT', 'MEMO', 'ND'].includes(load.document_type) && load.status === 'Selesai')
    .map((load) => ({ ...load, pendingItems: remainingDocumentItems(load) }))
    .filter((load) => load.pendingItems.length > 0);
  const bazarStock = consignmentStock.filter((item) => item.destination === 'Gudang Bazar');
  const ecommerceStock = consignmentStock.filter((item) => item.destination === 'Gudang E-commerce');
  const documentAge = (value) => {
    const days = Math.max(0, Math.floor((Date.now() - new Date(value || Date.now()).getTime()) / 86400000));
    return days === 0 ? 'Hari ini' : `${days} hari`;
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Pusat Kendali Gudang</div>
          <h1 className="font-display text-4xl font-bold">Ringkasan Penyimpanan Stok</h1>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard icon={Layers} label="Stok Gudang Utama" value={formatNum(totalUnits)} color="#a855f7" />
        <StatCard icon={AlertTriangle} label="Stok Rusak (Damage)" value={formatNum(totalDamaged)} color="#ef4444" />
        <StatCard icon={Layers} label="Produk Aktif Bazar" value={formatNum(bazarStock.length)} color="#f59e0b" />
        <StatCard icon={Layers} label="Produk Aktif E-commerce" value={formatNum(ecommerceStock.length)} color="#0ea5e9" />
      </div>

      {(settings?.lowAlert ?? true) && (
        <AlertSection title="Peringatan Stok Minimum" count={lowStock.length} colorClass="bg-[#eab308]/15 text-[#eab308]" iconClass="text-[#eab308]" open={lowAlertOpen} onToggle={() => setLowAlertOpen((value) => !value)}>
          {lowStock.length === 0 ? (
            <p className="text-sm text-[#8b93a1]">Semua stok masih di atas batas minimum. Tidak ada yang perlu direstock.</p>
          ) : (
            <div className="space-y-2">
              {lowStock.map((p) => (
                <div key={p.id} className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-lg bg-[#0b0f17] border border-[#1a222e]">
                  <div><div className="font-medium text-sm">{p.name}</div><div className="label-mono text-[10px]">{p.sku} · {p.location}</div></div>
                  <div className="font-mono text-sm"><span className="text-[#eab308] font-semibold">{p.stock}</span> / min {p.min} {p.unit} <span className="text-[#6b7688] block text-[10px]">Saran pesan {Math.max(p.min - p.stock + Math.ceil(p.min * 0.2), p.min)} {p.unit}</span></div>
                  <div className="text-xs text-[#8b93a1]">Supplier<div className="text-[#c7d0dc]">{p.supplier}</div></div>
                  <button onClick={() => navigate('/po')} className="btn-primary inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg"><ClipboardList size={13} /> Buat PO</button>
                </div>
              ))}
            </div>
          )}
        </AlertSection>
      )}

      {(settings?.expAlert ?? true) && (
        <AlertSection title="Peringatan Kedaluwarsa" count={expiringProducts.length} colorClass="bg-[#ef4444]/15 text-[#ef4444]" iconClass="text-[#ef4444]" open={expiryAlertOpen} onToggle={() => setExpiryAlertOpen((value) => !value)}>
          {expiringProducts.length === 0 ? (
            <p className="text-sm text-[#8b93a1]">Tidak ada barang yang kedaluwarsa atau jatuh tempo dalam 30 hari.</p>
          ) : (
            <div className="space-y-2">
              {expiringProducts.slice(0, 10).map((p) => (
                <div key={p.id} className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-lg bg-[#0b0f17] border border-[#1a222e]">
                  <div>
                    <div className="font-medium text-sm">{p.name}</div>
                    <div className="label-mono text-[10px]">{p.sku} · {p.location}</div>
                  </div>
                  <div className="text-sm">
                    <div className="font-mono">{p.exp}</div>
                    <div className={`text-xs ${p.daysToExpiry < 0 ? 'text-[#ef4444]' : p.daysToExpiry <= 7 ? 'text-[#f97316]' : 'text-[#eab308]'}`}>
                      {p.daysToExpiry < 0 ? `Lewat ${Math.abs(p.daysToExpiry)} hari` : p.daysToExpiry === 0 ? 'Kedaluwarsa hari ini' : `${p.daysToExpiry} hari lagi`}
                    </div>
                  </div>
                  <div className="font-mono text-sm">{formatNum(p.stock)} {p.unit}</div>
                </div>
              ))}
            </div>
          )}
        </AlertSection>
      )}

      <DashboardDropdown
        title="CT / Memo / ND Belum Diselesaikan"
        meta={`${pendingDocuments.length} dokumen masih terbuka`}
        open={pendingDocsOpen}
        onToggle={() => setPendingDocsOpen((value) => !value)}
      >
        <div className="flex justify-end mb-4">
          <button onClick={() => navigate('/pengeluaran')} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#2563eb] text-[#60a5fa]"><Link2 size={13} /> Buka Pengeluaran</button>
        </div>
        {pendingDocuments.length === 0 ? <p className="text-sm text-[#8b93a1]">Tidak ada CT, Memo, atau ND terbuka. Semua dokumen sudah memiliki penyelesaian CR, SO, atau Retur.</p> : <div className="overflow-x-auto"><table className="w-full text-sm tbl"><thead><tr className="text-left border-b border-[#1a222e]"><th className="py-2.5 pr-4">Dokumen</th><th className="py-2.5 pr-4">Tujuan / Lokasi</th><th className="py-2.5 pr-4">Sisa Belum Diselesaikan</th><th className="py-2.5">Status</th></tr></thead><tbody>{pendingDocuments.map((load) => <tr key={load.id} className="border-b border-[#131a24]"><td className="py-3 pr-4"><div className="font-mono font-semibold text-[#93c5fd]">{load.document_type} · {load.ref}</div>{load.request_document && <div className="text-[11px] text-[#fbbf24] mt-1">Dasar: {load.request_document}</div>}<div className="text-[11px] text-[#6b7688] mt-1">Terbuka {documentAge(load.completed_at || load.created_at)}</div></td><td className="py-3 pr-4"><div>{load.consignment_destination || load.party || '—'}</div><div className="text-xs text-[#6b7688] mt-1">{load.consignment_zone || load.unit_loading || '—'}</div></td><td className="py-3 pr-4 text-xs">{load.pendingItems.map((item) => <div key={`${item.documentNo}-${item.productId}`}>{item.documentNo && <span className="text-[#6b7688]">{item.documentNo} · </span>}{item.name} · <span className="font-mono font-semibold">{formatNum(item.remaining)} {item.unit}</span></div>)}</td><td className="py-3 text-xs text-[#fbbf24]">{load.document_status || 'Menunggu CR/SO'}</td></tr>)}</tbody></table></div>}
      </DashboardDropdown>

      <DashboardDropdown
        title="Monitoring Stok Seluruh Lokasi"
        meta={`${filtered.length} baris stok`}
        open={monitoringOpen}
        onToggle={() => setMonitoringOpen((value) => !value)}
      >
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="relative w-full max-w-md">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari produk, SKU, atau lokasi..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" />
          </div>
          <button onClick={() => downloadApiFile('/export/monitoring-stock.pdf', 'monitoring_stok_seluruh_lokasi.pdf').catch((e) => toast.error(apiError(e)))} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-[#294263] text-xs text-[#93c5fd]"><Printer size={14} /> Unduh PDF</button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['Saluran', 'Lokasi', 'SKU', 'Nama Komoditi', 'Kuantum Pack/PCS', 'Kuantum Fisik', 'Rusak'].map((h) => <th key={h} className="py-2.5 pr-4 font-semibold">{h}</th>)}</tr></thead>
            <tbody>{filtered.length === 0 ? <tr><td colSpan={7} className="py-8 text-center text-[#6b7688]">Belum ada produk terdaftar. Tambah produk atau import data SKU.</td></tr> : filtered.map((p) => <tr key={`${p.location}-${p.productId}-${p.channel}`} className="tbl-row border-b border-[#131a24]"><td className="py-3 pr-4"><span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${p.channel === 'PSO' ? 'bg-[#2563eb]/15 text-[#60a5fa]' : 'bg-[#a855f7]/15 text-[#c084fc]'}`}>{p.channel}</span></td><td className="py-3 pr-4 text-[#8b93a1]">{p.location}</td><td className="py-3 pr-4 font-mono text-xs text-[#93c5fd]">{p.sku || '—'}</td><td className="py-3 pr-4 font-medium">{p.name}</td><td className="py-3 pr-4 font-mono">{formatNum(p.qty)} {p.unit}</td><td className="py-3 pr-4 font-mono">{p.weight > 0 ? `${formatNum(p.totalWeight)} ${p.measureUnit || 'kg'}` : '—'}</td><td className="py-3 pr-4 font-mono">{formatNum(p.damaged || 0)}</td></tr>)}</tbody>
          </table>
        </div>
      </DashboardDropdown>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">{[
        { destination: 'Gudang Bazar', title: 'Kartu Stok Gudang Bazar', rows: bazarStock, open: bazarCardOpen, toggle: () => setBazarCardOpen((value) => !value) },
        { destination: 'Gudang E-commerce', title: 'Kartu Stok Gudang E-commerce', rows: ecommerceStock, open: ecomCardOpen, toggle: () => setEcomCardOpen((value) => !value) },
      ].map(({ destination, title, rows, open, toggle }) => <DashboardDropdown key={destination} title={title} meta={`${rows.length} produk aktif`} open={open} onToggle={toggle}>
        <div className="flex justify-end mb-4">
          <button onClick={() => downloadApiFile(`/export/consignment-stock-card.pdf?destination=${encodeURIComponent(destination)}`, `kartu_stok_${destination.replaceAll(' ', '_')}.pdf`).catch((e) => toast.error(apiError(e)))} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-[#294263] text-xs text-[#93c5fd]"><Printer size={14} /> Download kartu</button>
        </div>
        {rows.length === 0 ? <p className="text-sm text-[#8b93a1]">Belum ada stok konsinyasi aktif.</p> : <div className="overflow-x-auto"><table className="w-full text-sm tbl"><thead><tr className="text-left border-b border-[#1a222e]"><th className="py-2.5 pr-3">Saluran</th><th className="py-2.5 pr-3">SKU</th><th className="py-2.5 pr-3">Nama Komoditi</th><th className="py-2.5 pr-3">Pack/pcs</th><th className="py-2.5 pr-3">Kuantum Fisik</th><th className="py-2.5">Dokumen ND/Memo</th></tr></thead><tbody>{rows.map((item) => <tr key={`${item.productId}-${item.channel}`} className="tbl-row border-b border-[#131a24]"><td className="py-3 pr-3"><span className={`text-[10px] px-2 py-0.5 rounded-full ${(item.channel || 'KOM') === 'PSO' ? 'bg-[#2563eb]/15 text-[#60a5fa]' : 'bg-[#a855f7]/15 text-[#c084fc]'}`}>{item.channel || 'KOM'}</span></td><td className="py-3 pr-3 font-mono text-xs text-[#93c5fd]">{item.sku || '—'}</td><td className="py-3 pr-3 font-medium">{item.name}</td><td className="py-3 pr-3 font-mono whitespace-nowrap">{formatNum(item.qty)} {item.unit}</td><td className="py-3 pr-3 font-mono whitespace-nowrap">{item.weight > 0 ? `${formatNum(item.totalWeight)} ${item.measureUnit || 'kg'}` : '—'}</td><td className="py-3 text-xs text-[#8b93a1]">{item.documents?.join(', ') || '—'}</td></tr>)}</tbody></table></div>}
      </DashboardDropdown>)}</div>

      <DashboardDropdown
        title="Aktivitas Terakhir"
        meta={`${Math.min(transactions.length, 8)} aktivitas terbaru`}
        open={activityOpen}
        onToggle={() => setActivityOpen((value) => !value)}
      >
        <div className="space-y-2">
          {transactions.slice(0, 8).map((t) => <div key={t.id} className="flex items-center justify-between gap-3 p-3 rounded-lg bg-[#0b0f17] border border-[#151d28]"><div><div className="font-medium text-sm">{t.product}</div><div className="label-mono text-[10px]">{t.sku} · {formatDate(t.time)}</div></div><div className={`flex items-center gap-2 text-sm font-mono ${t.type === 'MASUK' ? 'text-[#22c55e]' : 'text-[#ef4444]'}`}>{t.type === 'MASUK' ? <ArrowDownRight size={15} /> : <ArrowUpRight size={15} />}<span className="text-xs px-2 py-0.5 rounded-full" style={{ background: t.type === 'MASUK' ? 'rgba(34,197,94,.15)' : 'rgba(239,68,68,.15)' }}>{t.type}</span><span className="font-semibold">{t.change > 0 ? '+' : ''}{t.change}</span></div></div>)}
          {transactions.length === 0 && <p className="text-sm text-[#8b93a1]">Belum ada aktivitas.</p>}
        </div>
      </DashboardDropdown>
    </div>
  );
};

export default Dashboard;
