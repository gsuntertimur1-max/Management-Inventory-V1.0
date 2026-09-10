import React, { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { Plus, X, Phone, Mail, MapPin, User } from 'lucide-react';
import { useData } from '../context/DataContext';
import { catColor, formatNum } from '../mock';
import { toast } from 'sonner';

const Supplier = () => {
  const { suppliers, products, addSupplier } = useData();
  const [modal, setModal] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ name: '', pic: '', phone: '', email: '', address: '', category: 'Beras' });

  const productCountBySupplier = useMemo(() => {
    const counts = new Map();
    products.forEach((product) => {
      if (!product.supplier) return;
      counts.set(product.supplier, (counts.get(product.supplier) || 0) + 1);
    });
    return counts;
  }, [products]);

  const closeModal = () => {
    if (!saving) setModal(false);
  };

  const save = async () => {
    if (!form.name.trim()) {
      toast.error('Nama supplier wajib diisi');
      return;
    }
    if (saving) return;

    setSaving(true);
    try {
      await addSupplier({ ...form, name: form.name.trim() });
      toast.success('Supplier ditambahkan');
      setModal(false);
      setForm({ name: '', pic: '', phone: '', email: '', address: '', category: 'Beras' });
    } catch {
      toast.error('Gagal menambah supplier');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Mitra Gudang</div>
          <h1 className="font-display text-4xl font-bold">Supplier</h1>
          <p className="text-[#8b93a1] mt-2">{suppliers.length} supplier terdaftar</p>
        </div>
        <button
          data-testid="add-supplier-btn"
          onClick={() => setModal(true)}
          className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg"
        >
          <Plus size={15} /> Tambah Supplier
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {suppliers.map((supplier) => {
          const count = productCountBySupplier.get(supplier.name) || 0;
          return (
            <div key={supplier.id} className="card-surface stat-card p-5">
              <div className="flex items-start justify-between mb-3">
                <div className="font-display font-bold text-lg pr-2">{supplier.name}</div>
                <span
                  className="text-[10px] px-2 py-0.5 rounded-full whitespace-nowrap"
                  style={{ background: `${catColor(supplier.category)}1f`, color: catColor(supplier.category) }}
                >
                  {supplier.category}
                </span>
              </div>
              <div className="space-y-2 text-sm text-[#aab4c4]">
                <div className="flex items-center gap-2"><User size={14} className="text-[#6b7688]" /> {supplier.pic}</div>
                <div className="flex items-center gap-2"><Phone size={14} className="text-[#6b7688]" /> {supplier.phone}</div>
                <div className="flex items-center gap-2"><Mail size={14} className="text-[#6b7688]" /> {supplier.email}</div>
                <div className="flex items-start gap-2"><MapPin size={14} className="text-[#6b7688] mt-0.5" /> {supplier.address}</div>
              </div>
              <div className="mt-4 pt-4 border-t border-[#151d28] flex justify-between text-xs">
                <span className="text-[#8b93a1]">Produk disuplai</span>
                <span className="font-mono font-semibold text-[#60a5fa]">{formatNum(count)} SKU</span>
              </div>
            </div>
          );
        })}
      </div>

      {modal && createPortal(
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-4 sm:p-6 overflow-y-auto">
          <div
            className="card-surface w-full max-w-md p-6 fade-up max-h-[calc(100dvh-3rem)] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
              <div className="flex items-center justify-between mb-5">
                <h2 className="font-display text-xl font-bold">Tambah Supplier</h2>
                <button onClick={closeModal} disabled={saving} className="text-[#8b93a1] hover:text-white disabled:opacity-50">
                  <X size={20} />
                </button>
              </div>

              <div className="space-y-4">
                {[
                  ['name', 'Nama Supplier'],
                  ['pic', 'PIC / Narahubung'],
                  ['phone', 'Telepon'],
                  ['email', 'Email'],
                  ['address', 'Alamat'],
                ].map(([key, label]) => (
                  <div key={key}>
                    <label className="text-xs font-medium mb-1 block text-[#8b93a1]">{label}</label>
                    <input
                      data-testid={`supplier-form-${key}`}
                      value={form[key]}
                      onChange={(e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))}
                      className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]"
                    />
                  </div>
                ))}
              </div>

              <div className="flex justify-end gap-2 mt-6">
                <button
                  onClick={closeModal}
                  disabled={saving}
                  className="px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm hover:bg-[#141a24] disabled:opacity-50"
                >
                  Batal
                </button>
                <button
                  data-testid="supplier-save-btn"
                  onClick={save}
                  disabled={saving}
                  className="btn-primary px-5 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-60 disabled:cursor-wait"
                >
                  {saving ? 'Menyimpan…' : 'Simpan'}
                </button>
              </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};

export default Supplier;
