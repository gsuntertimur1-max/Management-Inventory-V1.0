import React, { useState } from 'react';
import { Upload, Download, Plus, Search, Pencil, Trash2, X } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatRp, formatNum, catColor, CATEGORIES } from '../mock';
import { toast } from 'sonner';

const empty = { name: '', sku: '', category: 'F&B / Bahan Makanan', stock: 0, damaged: 0, cost: 0, exp: '', location: '', supplier: '', min: 0, unit: 'Pcs', weight: 0, secondary: 'Dus' };

const DaftarProduk = () => {
  const { products, suppliers, addProduct, updateProduct, deleteProduct } = useData();
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('SEMUA');
  const [modal, setModal] = useState(null); // {mode, data}

  const filtered = products.filter((p) => (cat === 'SEMUA' || p.category === cat) && (p.name.toLowerCase().includes(q.toLowerCase()) || p.sku.toLowerCase().includes(q.toLowerCase()))).sort((a, b) => a.name.localeCompare(b.name));

  const save = () => {
    const d = modal.data;
    if (!d.name || !d.sku) { toast.error('Nama & SKU wajib diisi'); return; }
    if (modal.mode === 'add') { addProduct(d); toast.success('Produk ditambahkan'); }
    else { updateProduct(d.id, d); toast.success('Produk diperbarui'); }
    setModal(null);
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
          <button onClick={() => toast.info('Fitur import tersedia di halaman Import Data')} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24] transition-colors"><Upload size={15} /> Import Data</button>
          <button onClick={() => toast.success('Excel diunduh (mock)')} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24] transition-colors"><Download size={15} /> Unduh Excel</button>
          <button data-testid="add-product-btn" onClick={() => setModal({ mode: 'add', data: { ...empty } })} className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg"><Plus size={15} /> Tambah Produk</button>
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
            <thead><tr className="text-left border-b border-[#1a222e]">{['Nama Produk', 'SKU', 'Kategori', 'Stok Baik', 'Stok Rusak', 'Harga Modal', 'Nilai Total', 'Supplier / Lokasi', 'Aksi'].map((h) => <th key={h} className="py-2.5 pr-4 font-semibold whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {filtered.length === 0 ? <tr><td colSpan={9} className="py-8 text-center text-[#6b7688]">Tidak ada produk.</td></tr> : filtered.map((p) => (
                <tr key={p.id} className="tbl-row border-b border-[#131a24]">
                  <td className="py-3 pr-4 font-medium">{p.name}</td>
                  <td className="py-3 pr-4 font-mono text-xs text-[#8b93a1]">{p.sku}</td>
                  <td className="py-3 pr-4"><span className="text-xs px-2 py-0.5 rounded-full whitespace-nowrap" style={{ background: `${catColor(p.category)}1f`, color: catColor(p.category) }}>{p.category}</span></td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(p.stock)} {p.unit}</td>
                  <td className="py-3 pr-4 font-mono">{p.damaged || 0}</td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatRp(p.cost)}</td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatRp(p.stock * p.cost)}</td>
                  <td className="py-3 pr-4 text-xs"><div className="text-[#c7d0dc]">{p.supplier}</div><div className="text-[#6b7688]">{p.location}</div></td>
                  <td className="py-3 pr-4"><div className="flex gap-1.5">
                    <button data-testid={`edit-product-btn-${p.sku}`} onClick={() => setModal({ mode: 'edit', data: { ...p } })} className="w-8 h-8 rounded-lg border border-[#242f3d] flex items-center justify-center text-[#8b93a1] hover:text-[#60a5fa] hover:border-[#2563eb] transition-colors"><Pencil size={14} /></button>
                    <button data-testid={`delete-product-btn-${p.sku}`} onClick={() => { if (window.confirm('Hapus produk ini?')) { deleteProduct(p.id); toast.success('Produk dihapus'); } }} className="w-8 h-8 rounded-lg border border-[#242f3d] flex items-center justify-center text-[#8b93a1] hover:text-[#ef4444] hover:border-[#ef4444] transition-colors"><Trash2 size={14} /></button>
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={() => setModal(null)}>
          <div className="card-surface w-full max-w-2xl p-6 fade-up" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5"><h2 className="font-display text-xl font-bold">{modal.mode === 'add' ? 'Tambah Produk' : 'Edit Produk'}</h2><button data-testid="product-modal-close-btn" onClick={() => setModal(null)} className="text-[#8b93a1] hover:text-white"><X size={20} /></button></div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {[['name', 'Nama Produk', 'text'], ['sku', 'SKU', 'text'], ['stock', 'Stok Baik', 'number'], ['damaged', 'Stok Rusak', 'number'], ['cost', 'Harga Modal (Rp)', 'number'], ['min', 'Stok Minimum', 'number'], ['location', 'Lokasi', 'text'], ['weight', 'Berat/Unit (kg)', 'number']].map(([k, l, t]) => (
                <div key={k}><label className="text-xs font-medium mb-1 block text-[#8b93a1]">{l}</label><input data-testid={`product-form-${k}`} type={t} value={modal.data[k]} onChange={(e) => setModal({ ...modal, data: { ...modal.data, [k]: t === 'number' ? Number(e.target.value) : e.target.value } })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-sm outline-none focus:border-[#2563eb]" /></div>
              ))}
              <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Kategori</label><select value={modal.data.category} onChange={(e) => setModal({ ...modal, data: { ...modal.data, category: e.target.value } })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-sm outline-none focus:border-[#2563eb]">{CATEGORIES.map((c) => <option key={c.name}>{c.name}</option>)}</select></div>
              <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Supplier</label><select value={modal.data.supplier} onChange={(e) => setModal({ ...modal, data: { ...modal.data, supplier: e.target.value } })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-sm outline-none focus:border-[#2563eb]"><option value="">Pilih supplier...</option>{suppliers.map((s) => <option key={s.id}>{s.name}</option>)}</select></div>
              <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Satuan</label><input value={modal.data.unit} onChange={(e) => setModal({ ...modal, data: { ...modal.data, unit: e.target.value } })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-sm outline-none focus:border-[#2563eb]" /></div>
            </div>
            <div className="flex justify-end gap-2 mt-6"><button onClick={() => setModal(null)} className="px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm hover:bg-[#141a24]">Batal</button><button data-testid="product-save-btn" onClick={save} className="btn-primary px-5 py-2.5 rounded-lg text-sm font-semibold">Simpan</button></div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DaftarProduk;
