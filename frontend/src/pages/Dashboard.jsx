import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, Layers, AlertTriangle, Sparkles, Activity, Upload, Plus, Search, ClipboardList, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatRp, formatRpShort, formatNum, formatDate, catColor, CATEGORIES } from '../mock';

const StatCard = ({ icon: Icon, label, value, sub, color }) => (
  <div className="card-surface stat-card p-5">
    <div className="w-10 h-10 rounded-xl flex items-center justify-center mb-8" style={{ background: `${color}1f`, color }}><Icon size={20} /></div>
    <div className="label-mono mb-1">{label}</div>
    <div className="font-display text-3xl font-bold">{value}</div>
    <div className="text-xs text-[#6b7688] mt-1">{sub}</div>
  </div>
);

const Dashboard = () => {
  const { products, transactions, settings } = useData();
  const navigate = useNavigate();
  const [q, setQ] = useState('');

  const totalUnits = products.reduce((a, p) => a + p.stock, 0);
  const totalDamaged = products.reduce((a, p) => a + (p.damaged || 0), 0);
  const totalValue = products.reduce((a, p) => a + p.stock * p.cost, 0);
  const thirtyDaysAgo = new Date();
  thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
  const activity30 = transactions
    .filter((t) => new Date(t.time) >= thirtyDaysAgo)
    .reduce((a, t) => a + Math.abs(t.change), 0);
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

  const chart = useMemo(() => {
    const days = [];
    for (let i = 6; i >= 0; i--) { const d = new Date(); d.setDate(d.getDate() - i); days.push(d); }
    return days.map((d) => {
      const key = `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      const vol = transactions.filter((t) => { const td = new Date(t.time); return td.getMonth() === d.getMonth() && td.getDate() === d.getDate(); }).reduce((a, t) => a + Math.abs(t.change), 0);
      return { key, vol };
    });
  }, [transactions]);
  const maxVol = Math.max(...chart.map((c) => c.vol), 1);

  const byCat = CATEGORIES.map((c) => ({ ...c, count: products.filter((p) => p.category === c.name).length, val: products.filter((p) => p.category === c.name).reduce((a, p) => a + p.stock * p.cost, 0) })).filter((c) => c.count > 0);
  const totCat = byCat.reduce((a, c) => a + c.val, 0) || 1;

  const filtered = products.filter((p) => p.name.toLowerCase().includes(q.toLowerCase()) || p.sku.toLowerCase().includes(q.toLowerCase())).sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Pusat Kendali Gudang</div>
          <h1 className="font-display text-4xl font-bold">Ringkasan Penyimpanan Stok</h1>
          <p className="text-[#8b93a1] mt-2 max-w-xl">Pantau nilai aset inventori, perputaran barang, dan aktivitas terakhir gudang Anda.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => navigate('/import')} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24] transition-colors"><Upload size={15} /> Import Data SKU</button>
          <button onClick={() => navigate('/produk')} className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg"><Plus size={15} /> Tambah Produk</button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={Box} label="Total Ragam Produk" value={formatNum(products.length)} sub="SKU aktif terdaftar" color="#3b82f6" />
        <StatCard icon={Layers} label="Total Unit Fisik Stok" value={formatNum(totalUnits)} sub="Kuantitas seluruh gudang" color="#a855f7" />
        <StatCard icon={AlertTriangle} label="Stok Rusak (Damage)" value={formatNum(totalDamaged)} sub="Unit kondisi rusak" color="#ef4444" />
        <StatCard icon={Sparkles} label="Total Nilai Inventori" value={formatRpShort(totalValue)} sub="Harga modal × jumlah stok" color="#22c55e" />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={Activity} label="Aktivitas 30 Hari" value={formatNum(activity30)} sub="Unit masuk & keluar" color="#eab308" />
      </div>

      {(settings?.lowAlert ?? true) && (
        <div className="card-surface p-6">
          <div className="flex items-center gap-3 mb-4">
            <AlertTriangle size={20} className="text-[#eab308]" />
            <h2 className="font-display text-xl font-bold">Peringatan Stok Minimum</h2>
            <span className="text-xs px-2.5 py-1 rounded-full bg-[#eab308]/15 text-[#eab308] font-medium">{lowStock.length} barang</span>
          </div>
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
        </div>
      )}

      {(settings?.expAlert ?? true) && (
        <div className="card-surface p-6">
          <div className="flex items-center gap-3 mb-4">
            <AlertTriangle size={20} className="text-[#ef4444]" />
            <h2 className="font-display text-xl font-bold">Peringatan Kedaluwarsa</h2>
            <span className="text-xs px-2.5 py-1 rounded-full bg-[#ef4444]/15 text-[#ef4444] font-medium">{expiringProducts.length} barang</span>
          </div>
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
                      {p.daysToExpiry < 0
                        ? `Lewat ${Math.abs(p.daysToExpiry)} hari`
                        : p.daysToExpiry === 0
                          ? 'Kedaluwarsa hari ini'
                          : `${p.daysToExpiry} hari lagi`}
                    </div>
                  </div>
                  <div className="font-mono text-sm">{formatNum(p.stock)} {p.unit}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="card-surface p-6">
        <h2 className="font-display text-xl font-bold mb-4">Sisa Stok per Barang (A → Z)</h2>
        <div className="relative mb-4 max-w-md">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari nama barang atau SKU..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['Nama Barang', 'SKU', 'Kategori', 'Sisa Stok', 'Rusak', 'Nilai Stok', 'Lokasi'].map((h) => <th key={h} className="py-2.5 pr-4 font-semibold">{h}</th>)}</tr></thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr><td colSpan={7} className="py-8 text-center text-[#6b7688]">Belum ada produk terdaftar. Tambah produk atau import data SKU.</td></tr>
              ) : filtered.map((p) => (
                <tr key={p.id} className="tbl-row border-b border-[#131a24]">
                  <td className="py-3 pr-4 font-medium">{p.name}</td>
                  <td className="py-3 pr-4 font-mono text-xs text-[#8b93a1]">{p.sku}</td>
                  <td className="py-3 pr-4"><span className="text-xs px-2 py-0.5 rounded-full" style={{ background: `${catColor(p.category)}1f`, color: catColor(p.category) }}>{p.category}</span></td>
                  <td className="py-3 pr-4 font-mono">{formatNum(p.stock)} {p.unit}</td>
                  <td className="py-3 pr-4 font-mono">{p.damaged || 0}</td>
                  <td className="py-3 pr-4 font-mono">{formatRp(p.stock * p.cost)}</td>
                  <td className="py-3 pr-4 text-[#8b93a1]">{p.location}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="card-surface p-6 lg:col-span-2">
          <h2 className="font-display text-lg font-bold mb-6">Perputaran 7 Hari Terakhir</h2>
          <div className="flex items-end justify-between gap-3 h-52">
            {chart.map((c) => (
              <div key={c.key} className="flex-1 flex flex-col items-center gap-2 h-full justify-end">
                <div className="w-full rounded-t-md bar" style={{ height: `${(c.vol / maxVol) * 100}%`, minHeight: c.vol > 0 ? '4px' : '0', background: 'linear-gradient(180deg,#3b82f6,#1d4ed8)' }} />
                <div className="label-mono text-[9px]">{c.key}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="card-surface p-6">
          <h2 className="font-display text-lg font-bold mb-4">Stok per Kategori</h2>
          {byCat.length === 0 ? <p className="text-sm text-[#8b93a1]">Belum ada produk terdaftar.</p> : (
            <div className="space-y-3">
              {byCat.map((c) => (
                <div key={c.name}>
                  <div className="flex justify-between text-xs mb-1"><span>{c.name}</span><span className="font-mono text-[#8b93a1]">{formatRpShort(c.val)}</span></div>
                  <div className="h-2 rounded-full bg-[#0b0f17] overflow-hidden"><div className="h-full rounded-full" style={{ width: `${(c.val / totCat) * 100}%`, background: c.color }} /></div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="card-surface p-6">
        <h2 className="font-display text-lg font-bold mb-4">Aktivitas Terakhir</h2>
        <div className="space-y-2">
          {transactions.slice(0, 8).map((t) => (
            <div key={t.id} className="flex items-center justify-between gap-3 p-3 rounded-lg bg-[#0b0f17] border border-[#151d28]">
              <div><div className="font-medium text-sm">{t.product}</div><div className="label-mono text-[10px]">{t.sku} · {formatDate(t.time)}</div></div>
              <div className={`flex items-center gap-2 text-sm font-mono ${t.type === 'MASUK' ? 'text-[#22c55e]' : 'text-[#ef4444]'}`}>
                {t.type === 'MASUK' ? <ArrowDownRight size={15} /> : <ArrowUpRight size={15} />}
                <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: t.type === 'MASUK' ? 'rgba(34,197,94,.15)' : 'rgba(239,68,68,.15)' }}>{t.type}</span>
                <span className="font-semibold">{t.change > 0 ? '+' : ''}{t.change}</span>
              </div>
            </div>
          ))}
          {transactions.length === 0 && <p className="text-sm text-[#8b93a1]">Belum ada aktivitas.</p>}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
