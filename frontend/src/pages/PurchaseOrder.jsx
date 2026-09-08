import React, { useState } from 'react';
import { Plus, X } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatRp, formatDate, formatNum } from '../mock';
import { toast } from 'sonner';

const STATUS = { 'Draft': '#8b93a1', 'Menunggu': '#eab308', 'Dikirim': '#3b82f6', 'Diterima': '#22c55e' };

const PurchaseOrder = () => {
  const { purchaseOrders, suppliers, products, addPO } = useData();
  const [modal, setModal] = useState(false);
  const [form, setForm] = useState({ supplier: '', productId: '', qty: 1 });

  const save = async () => {
    const prod = products.find((p) => p.id === form.productId);
    if (!form.supplier || !prod) { toast.error('Lengkapi supplier & produk'); return; }
    try {
      await addPO({ supplier: form.supplier, date: new Date().toISOString(), status: 'Draft', items: [{ name: prod.name, qty: Number(form.qty), cost: prod.cost }], total: prod.cost * Number(form.qty) });
      toast.success('Purchase Order dibuat'); setModal(false); setForm({ supplier: '', productId: '', qty: 1 });
    } catch { toast.error('Gagal membuat PO'); }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Pengadaan</div>
          <h1 className="font-display text-4xl font-bold">Purchase Order</h1>
          <p className="text-[#8b93a1] mt-2">{purchaseOrders.length} PO tercatat</p>
        </div>
        <button data-testid="create-po-btn" onClick={() => setModal(true)} className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg"><Plus size={15} /> Buat PO Baru</button>
      </div>

      <div className="card-surface p-6">
        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['No. PO', 'Tanggal', 'Supplier', 'Barang', 'Total Nilai', 'Status'].map((h) => <th key={h} className="py-2.5 pr-4 font-semibold whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {purchaseOrders.length === 0 ? <tr><td colSpan={6} className="py-8 text-center text-[#6b7688]">Belum ada PO. Buat PO baru.</td></tr> : purchaseOrders.map((po) => (
                <tr key={po.id} className="tbl-row border-b border-[#131a24]">
                  <td className="py-3 pr-4 font-mono text-xs">{po.no}</td>
                  <td className="py-3 pr-4 whitespace-nowrap text-[#8b93a1]">{formatDate(po.date)}</td>
                  <td className="py-3 pr-4 text-[#c7d0dc]">{po.supplier}</td>
                  <td className="py-3 pr-4 text-xs">{po.items.map((it, i) => <div key={i}>{it.name} × {formatNum(it.qty)}</div>)}</td>
                  <td className="py-3 pr-4 font-mono">{formatRp(po.total)}</td>
                  <td className="py-3 pr-4"><span className="text-xs px-2.5 py-1 rounded-full font-medium" style={{ background: `${STATUS[po.status]}22`, color: STATUS[po.status] }}>{po.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={() => setModal(false)}>
          <div className="card-surface w-full max-w-md p-6 fade-up" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5"><h2 className="font-display text-xl font-bold">Buat Purchase Order</h2><button onClick={() => setModal(false)} className="text-[#8b93a1] hover:text-white"><X size={20} /></button></div>
            <div className="space-y-4">
              <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Supplier</label><select data-testid="po-supplier-select" value={form.supplier} onChange={(e) => setForm({ ...form, supplier: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]"><option value="">Pilih supplier...</option>{suppliers.map((s) => <option key={s.id}>{s.name}</option>)}</select></div>
              <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Produk</label><select data-testid="po-product-select" value={form.productId} onChange={(e) => setForm({ ...form, productId: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]"><option value="">Pilih produk...</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
              <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Jumlah Pesan</label><input data-testid="po-qty-input" type="number" min="1" value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
            </div>
            <div className="flex justify-end gap-2 mt-6"><button onClick={() => setModal(false)} className="px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm hover:bg-[#141a24]">Batal</button><button data-testid="po-save-btn" onClick={save} className="btn-primary px-5 py-2.5 rounded-lg text-sm font-semibold">Simpan PO</button></div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PurchaseOrder;
