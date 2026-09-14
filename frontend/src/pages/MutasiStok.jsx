import React, { useState } from 'react';
import { ArrowRightLeft } from 'lucide-react';
import { toast } from 'sonner';
import { useData } from '../context/DataContext';
import { apiError } from '../lib/api';
import { stackCodes } from '../lib/warehouses';

const MutasiStok = () => {
  const { products, settings, addStockMutation } = useData();
  const [form, setForm] = useState({ productId: '', qty: '', fromCondition: 'BAIK', toCondition: 'BAIK', fromStackCode: '', toStackCode: '', reason: '' });
  const [busy, setBusy] = useState(false);
  const selected = products.find((item) => item.id === form.productId);
  const stacks = stackCodes(settings?.warehouses);
  const change = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const submit = async () => {
    if (!form.productId || Number(form.qty) <= 0 || !form.reason.trim()) return toast.error('Produk, jumlah, dan alasan mutasi wajib diisi');
    setBusy(true);
    try {
      await addStockMutation({ ...form, qty: Number(form.qty) });
      toast.success('Mutasi stok tersimpan dan masuk audit');
      setForm({ productId: '', qty: '', fromCondition: 'BAIK', toCondition: 'BAIK', fromStackCode: '', toStackCode: '', reason: '' });
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div><div className="label-mono mb-2">Pergerakan Internal</div><h1 className="font-display text-3xl md:text-4xl font-bold">Mutasi Stok</h1><p className="text-[#8b93a1] mt-2 max-w-3xl">Pindah kondisi atau lokasi tanpa menghapus transaksi lama. Sistem menolak saldo negatif dan wajib mencatat alasan.</p></div>
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_380px] gap-6">
        <div className="card-surface p-6">
          <h2 className="font-display text-xl font-bold mb-4 flex items-center gap-2"><ArrowRightLeft size={20} /> Form Mutasi</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="md:col-span-2"><label className="text-sm block mb-1">Produk</label><select value={form.productId} onChange={(e) => change('productId', e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5"><option value="">Pilih produk...</option>{products.map((p) => <option key={p.id} value={p.id}>{p.sku} · {p.name}</option>)}</select></div>
            <div><label className="text-sm block mb-1">Jumlah</label><input type="number" min="0" value={form.qty} onChange={(e) => change('qty', e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /></div>
            <div><label className="text-sm block mb-1">Lokasi tujuan</label><select value={form.toStackCode} onChange={(e) => change('toStackCode', e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5"><option value="">Tidak ubah lokasi</option>{stacks.map((s) => <option key={s}>{s}</option>)}</select></div>
            <div><label className="text-sm block mb-1">Kondisi asal</label><select value={form.fromCondition} onChange={(e) => change('fromCondition', e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5"><option>BAIK</option><option>RUSAK</option><option>ON_PROSES</option></select></div>
            <div><label className="text-sm block mb-1">Kondisi tujuan</label><select value={form.toCondition} onChange={(e) => change('toCondition', e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5"><option>BAIK</option><option>RUSAK</option><option>ON_PROSES</option></select></div>
            <div className="md:col-span-2"><label className="text-sm block mb-1">Alasan</label><textarea value={form.reason} onChange={(e) => change('reason', e.target.value)} rows="3" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" placeholder="Contoh: hasil sortasi, relokasi tumpukan, koreksi setelah opname..." /></div>
          </div>
          <button disabled={busy} onClick={submit} className="btn-primary mt-5 px-5 py-2.5 rounded-xl disabled:opacity-50">{busy ? 'Menyimpan...' : 'Simpan Mutasi'}</button>
        </div>
        <div className="card-surface p-6">
          <h2 className="font-display text-xl font-bold mb-4">Saldo Produk</h2>
          {selected ? <div className="space-y-3 text-sm"><div className="font-semibold">{selected.name}</div><div className="label-mono">{selected.sku}</div><div className="grid grid-cols-3 gap-2"><div className="rounded-lg bg-[#0b0f17] p-3"><div className="text-[#6b7688] text-xs">BAIK</div><div className="font-mono text-lg">{selected.stock}</div></div><div className="rounded-lg bg-[#0b0f17] p-3"><div className="text-[#6b7688] text-xs">RUSAK</div><div className="font-mono text-lg">{selected.damaged || 0}</div></div><div className="rounded-lg bg-[#0b0f17] p-3"><div className="text-[#6b7688] text-xs">PROSES</div><div className="font-mono text-lg">{selected.process || 0}</div></div></div><p className="text-[#8b93a1]">Lokasi saat ini: {selected.location || 'Belum dicatat'}</p></div> : <p className="text-sm text-[#8b93a1]">Pilih produk untuk melihat saldo.</p>}
        </div>
      </div>
    </div>
  );
};

export default MutasiStok;
