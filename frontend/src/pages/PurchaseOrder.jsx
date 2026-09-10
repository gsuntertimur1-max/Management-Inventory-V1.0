import React, { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { Plus, X, Trash2, PackageCheck } from 'lucide-react';
import { useData } from '../context/DataContext';
import { apiError } from '../lib/api';
import { formatRp, formatDate, formatNum } from '../mock';
import { toast } from 'sonner';

const STATUS = {
  'Belum Diterima': '#eab308',
  'Sebagian': '#3b82f6',
  'Selesai': '#22c55e',
  'Draft': '#8b93a1',
  'Menunggu': '#eab308',
  'Dikirim': '#3b82f6',
  'Diterima': '#22c55e',
};

const newRow = () => ({ productId: '', qty: 1 });

const PurchaseOrder = () => {
  const { purchaseOrders, suppliers, products, addPO } = useData();
  const [modal, setModal] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ supplier: '', items: [newRow()] });

  const setItem = (index, patch) => {
    setForm((prev) => ({
      ...prev,
      items: prev.items.map((item, i) => i === index ? { ...item, ...patch } : item),
    }));
  };

  const addItem = () => setForm((prev) => ({ ...prev, items: [...prev.items, newRow()] }));
  const removeItem = (index) => setForm((prev) => ({
    ...prev,
    items: prev.items.length === 1 ? prev.items : prev.items.filter((_, i) => i !== index),
  }));

  const selectedItems = useMemo(() => form.items.map((item) => ({
    ...item,
    product: products.find((p) => p.id === item.productId),
  })), [form.items, products]);

  const total = selectedItems.reduce((sum, item) => sum + (item.product?.cost || 0) * Number(item.qty || 0), 0);

  const save = async () => {
    if (!form.supplier) {
      toast.error('Pilih supplier');
      return;
    }
    if (selectedItems.some((item) => !item.product || Number(item.qty) <= 0)) {
      toast.error('Lengkapi produk dan jumlah pesanan');
      return;
    }
    const ids = selectedItems.map((item) => item.productId);
    if (new Set(ids).size !== ids.length) {
      toast.error('Produk yang sama tidak boleh ditambahkan dua kali');
      return;
    }
    if (saving) return;

    setSaving(true);
    try {
      await addPO({
        supplier: form.supplier,
        date: new Date().toISOString(),
        items: selectedItems.map((item) => ({ productId: item.productId, qty: Number(item.qty) })),
      });
      toast.success('Purchase Order dibuat. Stok belum berubah sampai barang diterima.');
      setModal(false);
      setForm({ supplier: '', items: [newRow()] });
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Pengadaan</div>
          <h1 className="font-display text-4xl font-bold">Purchase Order</h1>
          <p className="text-[#8b93a1] mt-2">{purchaseOrders.length} PO tercatat · PO adalah pesanan, bukan stok fisik</p>
        </div>
        <button data-testid="create-po-btn" onClick={() => setModal(true)} className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg"><Plus size={15} /> Buat PO Baru</button>
      </div>

      <div className="card-surface p-6">
        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['No. PO', 'Tanggal', 'Supplier', 'Barang Dipesan', 'Progres Penerimaan', 'Total Nilai', 'Status'].map((h) => <th key={h} className="py-2.5 pr-4 font-semibold whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {purchaseOrders.length === 0 ? <tr><td colSpan={7} className="py-8 text-center text-[#6b7688]">Belum ada PO. Buat PO baru untuk mencatat rencana pengadaan.</td></tr> : purchaseOrders.map((po) => {
                const ordered = (po.items || []).reduce((a, it) => a + Number(it.qty || 0), 0);
                const received = (po.items || []).reduce((a, it) => a + Number(it.receivedQty || 0), 0);
                const pct = ordered > 0 ? Math.min((received / ordered) * 100, 100) : 0;
                const color = STATUS[po.status] || '#8b93a1';
                return (
                  <tr key={po.id} className="tbl-row border-b border-[#131a24] align-top">
                    <td className="py-3 pr-4 font-mono text-xs">{po.no}</td>
                    <td className="py-3 pr-4 whitespace-nowrap text-[#8b93a1]">{formatDate(po.date)}</td>
                    <td className="py-3 pr-4 text-[#c7d0dc]">{po.supplier}</td>
                    <td className="py-3 pr-4 text-xs min-w-[260px]">
                      {(po.items || []).map((it, i) => (
                        <div key={i} className="mb-1.5 last:mb-0">
                          <div>{it.name} × <span className="font-mono">{formatNum(it.qty)} {it.unit || ''}</span></div>
                          <div className="text-[#6b7688]">Diterima {formatNum(it.receivedQty || 0)} · Sisa {formatNum(Math.max(Number(it.qty || 0) - Number(it.receivedQty || 0), 0))} {it.unit || ''}</div>
                        </div>
                      ))}
                    </td>
                    <td className="py-3 pr-4 min-w-[170px]">
                      <div className="flex justify-between text-xs mb-1.5"><span>{formatNum(received)}</span><span>{formatNum(ordered)}</span></div>
                      <div className="h-2 rounded-full bg-[#151d28] overflow-hidden"><div className="h-full rounded-full bg-[#2563eb]" style={{ width: `${pct}%` }} /></div>
                      <div className="text-[10px] text-[#6b7688] mt-1">{pct.toFixed(0)}% diterima</div>
                    </td>
                    <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatRp(po.total)}</td>
                    <td className="py-3 pr-4"><span className="text-xs px-2.5 py-1 rounded-full font-medium whitespace-nowrap" style={{ background: `${color}22`, color }}>{po.status}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {modal && createPortal(
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-4 sm:p-6 overflow-y-auto">
          <div className="card-surface w-full max-w-2xl p-6 fade-up max-h-[calc(100dvh-3rem)] overflow-y-auto">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="font-display text-xl font-bold">Buat Purchase Order</h2>
                <p className="text-xs text-[#6b7688] mt-1">Jumlah di PO adalah jumlah yang dipesan dan tidak menambah stok.</p>
              </div>
              <button onClick={() => !saving && setModal(false)} disabled={saving} className="text-[#8b93a1] hover:text-white disabled:opacity-50"><X size={20} /></button>
            </div>

            <div className="space-y-5">
              <div>
                <label className="text-xs font-medium mb-1 block text-[#8b93a1]">Supplier</label>
                <select data-testid="po-supplier-select" value={form.supplier} onChange={(e) => setForm((prev) => ({ ...prev, supplier: e.target.value }))} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]">
                  <option value="">Pilih supplier...</option>
                  {suppliers.map((supplier) => <option key={supplier.id}>{supplier.name}</option>)}
                </select>
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs font-medium text-[#8b93a1]">Daftar Barang</label>
                  <button type="button" onClick={addItem} className="inline-flex items-center gap-1.5 text-xs text-[#60a5fa] hover:text-[#93c5fd]"><Plus size={13} /> Tambah Barang</button>
                </div>
                <div className="space-y-3">
                  {selectedItems.map((item, index) => (
                    <div key={index} className="grid grid-cols-1 sm:grid-cols-[1fr_150px_90px_40px] gap-2 items-end p-3 rounded-lg bg-[#0b0f17] border border-[#1a222e]">
                      <div>
                        <label className="text-[10px] text-[#6b7688] mb-1 block">Produk</label>
                        <select data-testid={`po-product-select-${index}`} value={item.productId} onChange={(e) => setItem(index, { productId: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]">
                          <option value="">Pilih produk...</option>
                          {products.map((product) => <option key={product.id} value={product.id}>{product.name} ({product.sku})</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="text-[10px] text-[#6b7688] mb-1 block">Jumlah Pesan</label>
                        <input data-testid={`po-qty-input-${index}`} type="number" min="0.01" step="any" value={item.qty} onChange={(e) => setItem(index, { qty: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" />
                      </div>
                      <div>
                        <label className="text-[10px] text-[#6b7688] mb-1 block">Satuan</label>
                        <div className="h-[42px] px-3 flex items-center rounded-lg border border-[#1a222e] text-xs text-[#aab4c4]">{item.product?.unit || '—'}</div>
                      </div>
                      <button type="button" title="Hapus barang" onClick={() => removeItem(index)} className="w-10 h-[42px] rounded-lg border border-[#242f3d] flex items-center justify-center text-[#ef4444] hover:bg-[#ef4444]/10"><Trash2 size={15} /></button>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-lg border border-[#1a222e] bg-[#0b0f17] p-4 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-sm text-[#aab4c4]"><PackageCheck size={16} className="text-[#60a5fa]" /> Estimasi nilai PO</div>
                <div className="font-mono font-semibold">{formatRp(total)}</div>
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-6">
              <button onClick={() => setModal(false)} disabled={saving} className="px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm hover:bg-[#141a24] disabled:opacity-50">Batal</button>
              <button data-testid="po-save-btn" onClick={save} disabled={saving} className="btn-primary px-5 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-60 disabled:cursor-wait">{saving ? 'Menyimpan…' : 'Simpan PO'}</button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};

export default PurchaseOrder;
