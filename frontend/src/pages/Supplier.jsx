import React, { useState } from 'react';
import { Plus, X, Phone, Mail, MapPin, User } from 'lucide-react';
import { useData } from '../context/DataContext';
import { catColor, formatNum } from '../mock';
import { toast } from 'sonner';

const Supplier = () => {
  const { suppliers, products, addSupplier } = useData();
  const [modal, setModal] = useState(false);
  const [form, setForm] = useState({ name: '', pic: '', phone: '', email: '', address: '', category: 'Beras' });

  const save = async () => {
    if (!form.name) { toast.error('Nama supplier wajib diisi'); return; }
    try {
      await addSupplier(form); toast.success('Supplier ditambahkan'); setModal(false); setForm({ name: '', pic: '', phone: '', email: '', address: '', category: 'Beras' });
    } catch { toast.error('Gagal menambah supplier'); }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Mitra Gudang</div>
          <h1 className="font-display text-4xl font-bold">Supplier</h1>
          <p className="text-[#8b93a1] mt-2">{suppliers.length} supplier terdaftar</p>
        </div>
        <button data-testid="add-supplier-btn" onClick={() => setModal(true)} className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg"><Plus size={15} /> Tambah Supplier</button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {suppliers.map((s) => {
          const count = products.filter((p) => p.supplier === s.name).length;
          return (
            <div key={s.id} className="card-surface stat-card p-5">
              <div className="flex items-start justify-between mb-3">
                <div className="font-display font-bold text-lg pr-2">{s.name}</div>
                <span className="text-[10px] px-2 py-0.5 rounded-full whitespace-nowrap" style={{ background: `${catColor(s.category)}1f`, color: catColor(s.category) }}>{s.category}</span>
              </div>
              <div className="space-y-2 text-sm text-[#aab4c4]">
                <div className="flex items-center gap-2"><User size={14} className="text-[#6b7688]" /> {s.pic}</div>
                <div className="flex items-center gap-2"><Phone size={14} className="text-[#6b7688]" /> {s.phone}</div>
                <div className="flex items-center gap-2"><Mail size={14} className="text-[#6b7688]" /> {s.email}</div>
                <div className="flex items-start gap-2"><MapPin size={14} className="text-[#6b7688] mt-0.5" /> {s.address}</div>
              </div>
              <div className="mt-4 pt-4 border-t border-[#151d28] flex justify-between text-xs"><span className="text-[#8b93a1]">Produk disuplai</span><span className="font-mono font-semibold text-[#60a5fa]">{formatNum(count)} SKU</span></div>
            </div>
          );
        })}
      </div>

      {modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={() => setModal(false)}>
          <div className="card-surface w-full max-w-md p-6 fade-up" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5"><h2 className="font-display text-xl font-bold">Tambah Supplier</h2><button onClick={() => setModal(false)} className="text-[#8b93a1] hover:text-white"><X size={20} /></button></div>
            <div className="space-y-4">
              {[['name', 'Nama Supplier'], ['pic', 'PIC / Narahubung'], ['phone', 'Telepon'], ['email', 'Email'], ['address', 'Alamat']].map(([k, l]) => (
                <div key={k}><label className="text-xs font-medium mb-1 block text-[#8b93a1]">{l}</label><input data-testid={`supplier-form-${k}`} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
              ))}
            </div>
            <div className="flex justify-end gap-2 mt-6"><button onClick={() => setModal(false)} className="px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm hover:bg-[#141a24]">Batal</button><button data-testid="supplier-save-btn" onClick={save} className="btn-primary px-5 py-2.5 rounded-lg text-sm font-semibold">Simpan</button></div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Supplier;
