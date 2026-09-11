import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { Upload, Download, Plus, Search, Pencil, Trash2, X, Info } from 'lucide-react';
import { useData } from '../context/DataContext';
import { apiError, downloadApiFile } from '../lib/api';
import { formatRp, formatNum, catColor, CATEGORIES } from '../mock';
import { toast } from 'sonner';
import { packagingText, totalWeight } from '../lib/packaging';

const empty = {
  name: '', sku: '', category: 'F&B / Bahan Makanan', cost: 0,
  location: '', supplier: '', min: 0, unit: 'Pack', weight: 0, secondary: '', secondaryQty: 0,
};
const STACKS = [...Array.from({ length: 8 }, (_, i) => String(i + 17)).flatMap((unit) => ['A', 'B', 'C'].flatMap((zone) => Array.from({ length: 4 }, (_, i) => `${unit}/${zone}${String(i + 1).padStart(2, '0')}`))), ...['A', 'B'].flatMap((zone) => Array.from({ length: 8 }, (_, i) => `MP/${zone}${String(i + 1).padStart(2, '0')}`))];

const masterPayload = (data) => ({
  name: data.name || '',
  sku: data.sku || '',
  category: data.category || '',
  cost: Number(data.cost || 0),
  location: data.location || '',
  supplier: data.supplier || '',
  min: Number(data.min || 0),
  unit: data.unit || 'Pcs',
  weight: Number(data.weight || 0),
  secondary: data.secondary || '',
  secondaryQty: Number(data.secondaryQty || 0),
});

const DaftarProduk = () => {
  const navigate = useNavigate();
  const { products, suppliers, addProduct, updateProduct, deleteProduct, canManageMasterData } = useData();
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('SEMUA');
  const [modal, setModal] = useState(null);
  const [exporting, setExporting] = useState(false);

  const filtered = products
    .filter((p) => (cat === 'SEMUA' || p.category === cat)
      && (p.name.toLowerCase().includes(q.toLowerCase()) || p.sku.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => a.name.localeCompare(b.name));

  const save = async () => {
    const data = masterPayload(modal.data);
    if (!data.name.trim() || !data.sku.trim()) {
      toast.error('Nama & SKU wajib diisi');
      return;
    }
    if (data.secondary && data.secondaryQty <= 0) {
      toast.error('Isi per kemasan sekunder harus lebih dari 0');
      return;
    }
    if (data.secondaryQty > 0 && !data.secondary) {
      toast.error('Nama kemasan sekunder wajib diisi');
      return;
    }
    if (data.secondaryQty > 0 && !Number.isInteger(data.secondaryQty)) {
      toast.error('Isi kemasan sekunder harus berupa jumlah pack utuh');
      return;
    }
    try {
      if (modal.mode === 'add') {
        await addProduct(data);
        toast.success('Master produk ditambahkan dengan stok awal 0');
      } else {
        await updateProduct(modal.data.id, data);
        toast.success('Master produk diperbarui');
      }
      setModal(null);
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  const exportProducts = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      await downloadApiFile('/export/products.xlsx', 'daftar_produk.xlsx');
      toast.success('File Excel daftar produk berhasil diunduh');
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Master Data</div>
          <h1 className="font-display text-4xl font-bold">Daftar Produk</h1>
          <p className="text-[#8b93a1] mt-2">{filtered.length} dari {products.length} produk ditampilkan</p>
        </div>
        <div className="flex gap-2">
          {canManageMasterData && <button onClick={() => navigate('/import')} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24] transition-colors"><Upload size={15} /> Import Data</button>}
          <button onClick={exportProducts} disabled={exporting} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24] transition-colors disabled:opacity-60 disabled:cursor-wait"><Download size={15} /> {exporting ? 'Menyiapkan…' : 'Unduh Excel'}</button>
          {canManageMasterData && <button data-testid="add-product-btn" onClick={() => setModal({ mode: 'add', data: { ...empty } })} className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg"><Plus size={15} /> Tambah Produk</button>}
        </div>
      </div>

      <div className="card-surface p-6">
        <div className="flex flex-wrap gap-3 mb-5">
          <div className="relative flex-1 min-w-[240px]">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" />
            <input data-testid="product-search-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari nama produk atau kode SKU..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" />
          </div>
          <select value={cat} onChange={(e) => setCat(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb] min-w-[200px]">
            <option value="SEMUA">SEMUA</option>
            {CATEGORIES.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['Nama Produk', 'SKU', 'Kategori', 'Stok Baik', 'Konversi Kemasan', 'Stok Rusak', 'Harga Modal', 'Nilai Total', 'Supplier / Lokasi', 'Aksi'].map((h) => <th key={h} className="py-2.5 pr-4 font-semibold whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {filtered.length === 0 ? <tr><td colSpan={10} className="py-8 text-center text-[#6b7688]">Tidak ada produk.</td></tr> : filtered.map((p) => (
                <tr key={p.id} className="tbl-row border-b border-[#131a24]">
                  <td className="py-3 pr-4 font-medium">{p.name}</td>
                  <td className="py-3 pr-4 font-mono text-xs text-[#8b93a1]">{p.sku}</td>
                  <td className="py-3 pr-4"><span className="text-xs px-2 py-0.5 rounded-full whitespace-nowrap" style={{ background: `${catColor(p.category)}1f`, color: catColor(p.category) }}>{p.category}</span></td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(p.stock || 0)} {p.unit}</td>
                  <td className="py-3 pr-4 text-xs min-w-[210px]"><div className="text-[#c7d0dc]">{packagingText(p.stock, p, formatNum) || 'Belum diatur'}</div>{Number(p.weight || 0) > 0 && <div className="text-[#6b7688] mt-1">{formatNum(totalWeight(p.stock, p))} kg</div>}</td>
                  <td className="py-3 pr-4 font-mono">{formatNum(p.damaged || 0)}</td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatRp(p.cost)}</td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatRp((p.stock || 0) * (p.cost || 0))}</td>
                  <td className="py-3 pr-4 text-xs"><div className="text-[#c7d0dc]">{p.supplier || '—'}</div><div className="text-[#6b7688]">{p.location || '—'}</div></td>
                  <td className="py-3 pr-4">{canManageMasterData ? <div className="flex gap-1.5">
                    <button data-testid={`edit-product-btn-${p.sku}`} onClick={() => setModal({ mode: 'edit', data: { ...p } })} className="w-8 h-8 rounded-lg border border-[#242f3d] flex items-center justify-center text-[#8b93a1] hover:text-[#60a5fa] hover:border-[#2563eb] transition-colors"><Pencil size={14} /></button>
                    <button data-testid={`delete-product-btn-${p.sku}`} onClick={() => { if (window.confirm('Hapus master produk ini?')) { deleteProduct(p.id); toast.success('Produk dihapus'); } }} className="w-8 h-8 rounded-lg border border-[#242f3d] flex items-center justify-center text-[#8b93a1] hover:text-[#ef4444] hover:border-[#ef4444] transition-colors"><Trash2 size={14} /></button>
                  </div> : <span className="text-xs text-[#6b7688]">Lihat saja</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {modal && createPortal(
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-4 sm:p-6 overflow-y-auto">
          <div className="w-full max-w-2xl translate-y-6 sm:translate-y-8">
            <div className="card-surface w-full p-6 fade-up max-h-[calc(100dvh-4rem)] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-5">
                <div>
                  <h2 className="font-display text-xl font-bold">{modal.mode === 'add' ? 'Tambah Master Produk' : 'Edit Master Produk'}</h2>
                  <p className="text-xs text-[#6b7688] mt-1">Jumlah stok tidak diubah dari master produk.</p>
                </div>
                <button data-testid="product-modal-close-btn" onClick={() => setModal(null)} className="text-[#8b93a1] hover:text-white"><X size={20} /></button>
              </div>

              <div className="mb-5 flex gap-2 rounded-lg border border-[#1f3657] bg-[#0d1b2f] px-3 py-2.5 text-xs text-[#93c5fd]">
                <Info size={15} className="shrink-0 mt-0.5" />
                <span>Produk baru selalu dimulai dari stok 0. Stok hanya bertambah atau berkurang melalui menu Catat Stok.</span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {[['name', 'Nama Produk', 'text'], ['sku', 'SKU', 'text'], ['cost', 'Harga Modal (Rp)', 'number'], ['min', 'Stok Minimum', 'number'], ['weight', 'Berat/Unit (kg)', 'number']].map(([k, l, t]) => (
                  <div key={k}>
                    <label className="text-xs font-medium mb-1 block text-[#8b93a1]">{l}</label>
                    <input data-testid={`product-form-${k}`} type={t} value={modal.data[k] ?? ''} onChange={(e) => setModal({ ...modal, data: { ...modal.data, [k]: t === 'number' ? Number(e.target.value) : e.target.value } })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-sm outline-none focus:border-[#2563eb]" />
                  </div>
                ))}
                <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Lokasi Tumpukan Default</label><select value={modal.data.location || ''} onChange={(e) => setModal({ ...modal, data: { ...modal.data, location: e.target.value } })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-sm"><option value="">Belum ditentukan</option>{STACKS.map((code) => <option key={code} value={code}>{code}</option>)}</select></div>
                <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Kategori</label><select value={modal.data.category || ''} onChange={(e) => setModal({ ...modal, data: { ...modal.data, category: e.target.value } })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-sm outline-none focus:border-[#2563eb]">{CATEGORIES.map((c) => <option key={c.name}>{c.name}</option>)}</select></div>
                <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Supplier Default</label><select value={modal.data.supplier || ''} onChange={(e) => setModal({ ...modal, data: { ...modal.data, supplier: e.target.value } })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-sm outline-none focus:border-[#2563eb]"><option value="">Pilih supplier...</option>{suppliers.map((s) => <option key={s.id}>{s.name}</option>)}</select></div>
                <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Kemasan Primer / Satuan Dasar</label><input value={modal.data.unit || ''} placeholder="Contoh: Pack" onChange={(e) => setModal({ ...modal, data: { ...modal.data, unit: e.target.value } })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-sm outline-none focus:border-[#2563eb]" /></div>
                <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Kemasan Sekunder</label><input value={modal.data.secondary || ''} placeholder="Contoh: Karung atau Dus" onChange={(e) => setModal({ ...modal, data: { ...modal.data, secondary: e.target.value } })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-sm outline-none focus:border-[#2563eb]" /></div>
                <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Isi per Kemasan Sekunder</label><input type="number" min="0" step="1" value={modal.data.secondaryQty ?? 0} placeholder="Contoh: 8" onChange={(e) => setModal({ ...modal, data: { ...modal.data, secondaryQty: Number(e.target.value) } })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-sm outline-none focus:border-[#2563eb]" /><div className="text-[10px] text-[#566173] mt-1">Jumlah {modal.data.unit || 'kemasan primer'} dalam 1 {modal.data.secondary || 'kemasan sekunder'}.</div></div>
                <div className="rounded-lg border border-[#1f3657] bg-[#0d1728] px-3 py-2.5 text-xs text-[#93c5fd] self-end">{Number(modal.data.weight || 0) > 0 && Number(modal.data.secondaryQty || 0) > 0 ? `1 ${modal.data.secondary || 'kemasan sekunder'} = ${formatNum(modal.data.secondaryQty)} ${modal.data.unit || 'unit'} = ${formatNum(Number(modal.data.weight) * Number(modal.data.secondaryQty))} kg` : 'Isi berat/unit dan isi kemasan sekunder untuk melihat konversi.'}</div>
              </div>
              <div className="flex justify-end gap-2 mt-6">
                <button onClick={() => setModal(null)} className="px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm hover:bg-[#141a24]">Batal</button>
                <button data-testid="product-save-btn" onClick={save} className="btn-primary px-5 py-2.5 rounded-lg text-sm font-semibold">Simpan Master</button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};

export default DaftarProduk;
