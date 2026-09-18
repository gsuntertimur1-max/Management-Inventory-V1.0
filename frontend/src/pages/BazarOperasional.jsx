import React, { useEffect, useState } from 'react';
import { Car, CheckCircle2, History, Plus, RefreshCcw, Trash2 } from 'lucide-react';
import api, { apiError } from '../lib/api';
import { toast } from 'sonner';

const inputCls = 'w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';

const BazarOperasional = () => {
  const [availability, setAvailability] = useState([]);
  const [trips, setTrips] = useState([]);
  const [history, setHistory] = useState([]);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ eventDate: new Date().toISOString().slice(0, 10), location: '', vehicleNo: '', driver: '', note: '' });
  const [draft, setDraft] = useState({ productId: '', qty: '' });
  const [items, setItems] = useState([]);
  const [closing, setClosing] = useState(null);
  const [closeRows, setCloseRows] = useState({});

  const load = async () => {
    const [a, t, h] = await Promise.all([
      api.get('/bazar/availability'), api.get('/bazar/trips'), api.get('/consignment-operation-history?destination=Gudang%20Bazar'),
    ]);
    setAvailability(a.data); setTrips(t.data); setHistory(h.data.filter((x) => String(x.eventType || '').startsWith('BAZAR_')));
  };

  useEffect(() => { load().catch(() => {}); }, []);

  const addItem = () => {
    const product = availability.find((x) => x.productId === draft.productId);
    const qty = Number(draft.qty || 0);
    if (!product || qty <= 0) return toast.error('Pilih komoditi dan isi jumlah muat');
    const existingQty = items.filter((x) => x.productId === product.productId).reduce((sum, x) => sum + Number(x.qty || 0), 0);
    if (existingQty + qty > Number(product.availableQty || 0)) return toast.error(`Stok tersedia ${product.name} hanya ${product.availableQty} ${product.unit}`);
    setItems((prev) => {
      const existing = prev.find((x) => x.productId === product.productId);
      if (existing) return prev.map((x) => x.productId === product.productId ? { ...x, qty: Number(x.qty) + qty } : x);
      return [...prev, { productId: product.productId, name: product.name, unit: product.unit, qty }];
    });
    setDraft({ productId: '', qty: '' });
  };

  const createTrip = async () => {
    if (!form.location.trim() || !form.vehicleNo.trim() || items.length === 0) return toast.error('Lokasi bazar, kendaraan dan minimal satu komoditi wajib diisi');
    setSaving(true);
    try {
      await api.post('/bazar/trips', { ...form, items: items.map(({ productId, qty }) => ({ productId, qty: Number(qty) })) });
      toast.success('Perjalanan Bazar dibuat dan seluruh muatan direservasi');
      setItems([]); setForm((p) => ({ ...p, note: '' }));
      await load();
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const openClose = (trip) => {
    const rows = {};
    (trip.items || []).forEach((item) => { rows[item.productId] = { soldQty: '', returnedDamagedQty: '' }; });
    setCloseRows(rows); setClosing(trip);
  };

  const closeTrip = async () => {
    try {
      const resultItems = (closing.items || []).map((item) => {
        const sold = Number(closeRows[item.productId]?.soldQty || 0);
        const damaged = Number(closeRows[item.productId]?.returnedDamagedQty || 0);
        const returnedGood = Number(item.loadedQty || 0) - sold - damaged;
        if (returnedGood < 0) throw new Error(`${item.name}: terjual + retur rusak melebihi jumlah muat`);
        return { productId: item.productId, soldQty: sold, returnedDamagedQty: damaged, returnedGoodQty: returnedGood };
      });
      await api.post(`/bazar/trips/${closing.id}/close`, { items: resultItems, note: 'Rekonsiliasi penutupan bazar' });
      toast.success('Perjalanan Bazar selesai dan stok direkonsiliasi');
      setClosing(null); await load();
    } catch (e) { toast.error(e?.response ? apiError(e) : e.message); }
  };

  return <div className="space-y-6">
    <div><div className="label-mono mb-2">Operasional Bazar</div><h1 className="font-display text-3xl sm:text-4xl font-bold">Perjalanan & Penjualan Bazar</h1><p className="text-[#8b93a1] mt-2 text-sm">Satu mobil dapat membawa beberapa komoditi. Muatan menjadi reservasi Bazar sampai perjalanan ditutup dan direkonsiliasi.</p></div>

    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
      <div className="card-surface p-5 xl:col-span-1 space-y-3">
        <div className="font-semibold flex items-center gap-2"><Plus size={17}/> Buat Perjalanan Bazar</div>
        <input type="date" className={inputCls} value={form.eventDate} onChange={(e) => setForm({ ...form, eventDate: e.target.value })} />
        <input className={inputCls} placeholder="Lokasi bazar" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} />
        <input className={inputCls} placeholder="No. kendaraan" value={form.vehicleNo} onChange={(e) => setForm({ ...form, vehicleNo: e.target.value })} />
        <input className={inputCls} placeholder="Pengemudi (opsional)" value={form.driver} onChange={(e) => setForm({ ...form, driver: e.target.value })} />
        <div className="rounded-xl border border-[#243044] p-3 space-y-2">
          <div className="text-xs font-semibold">Tambah Komoditi Muatan</div>
          <select className={inputCls} value={draft.productId} onChange={(e) => setDraft({ ...draft, productId: e.target.value })}><option value="">Pilih komoditi</option>{availability.map((x) => <option key={x.productId} value={x.productId}>{x.name} · tersedia {x.availableQty} {x.unit}</option>)}</select>
          <div className="flex gap-2"><input type="number" min="0" className={inputCls} placeholder="Jumlah muat" value={draft.qty} onChange={(e) => setDraft({ ...draft, qty: e.target.value })} /><button type="button" onClick={addItem} className="px-4 rounded-lg border border-[#3b82f6] text-[#93c5fd]">Tambah</button></div>
          <div className="space-y-1">{items.map((item) => <div key={item.productId} className="flex items-center justify-between gap-2 text-xs bg-[#111827] rounded-lg px-3 py-2"><span>{item.name}</span><span className="flex items-center gap-2"><b>{item.qty} {item.unit}</b><button onClick={() => setItems((p) => p.filter((x) => x.productId !== item.productId))} className="text-[#f87171]"><Trash2 size={13}/></button></span></div>)}</div>
        </div>
        <textarea className={inputCls} placeholder="Catatan" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
        <button disabled={saving} onClick={createTrip} className="btn-primary w-full py-2.5 rounded-lg font-semibold">{saving ? 'Menyimpan…' : `Muat ${items.length || ''} Komoditi ke Mobil`}</button>
      </div>

      <div className="card-surface p-5 xl:col-span-2">
        <div className="flex items-center justify-between mb-4"><div className="font-semibold flex items-center gap-2"><Car size={17}/> Perjalanan Bazar</div><button onClick={() => load()} className="text-xs inline-flex items-center gap-1 text-[#93c5fd]"><RefreshCcw size={13}/> Refresh</button></div>
        <div className="space-y-3">
          {trips.length === 0 && <div className="text-sm text-[#8b93a1]">Belum ada perjalanan Bazar.</div>}
          {trips.map((trip) => <div key={trip.id} className="border border-[#243044] rounded-xl p-4">
            <div className="flex flex-wrap items-start justify-between gap-2"><div><div className="font-semibold">{trip.tripNo} · {trip.location}</div><div className="text-xs text-[#8b93a1] mt-1">{trip.eventDate} · {trip.vehicleNo} · {trip.driver || 'Pengemudi belum diisi'}</div></div><span className={`text-xs px-2.5 py-1 rounded-full ${trip.status === 'SELESAI' ? 'bg-[#22c55e]/15 text-[#22c55e]' : 'bg-[#f59e0b]/15 text-[#f59e0b]'}`}>{trip.status}</span></div>
            <div className="mt-3 text-xs space-y-1">{(trip.items || []).map((item) => <div key={item.productId} className="flex justify-between gap-3"><span>{item.name}</span><span className="font-mono">Muat {item.loadedQty} {item.unit}</span></div>)}</div>
            {trip.status === 'SELESAI' && <div className="mt-3 pt-3 border-t border-[#243044] text-xs space-y-1">{(trip.resultItems || []).map((item) => <div key={item.productId}>{item.name}: <b>{item.soldQty}</b> terjual · <b>{item.returnedGoodQty}</b> retur baik · <b>{item.returnedDamagedQty}</b> retur rusak</div>)}</div>}
            {trip.status === 'BERJALAN' && <button onClick={() => openClose(trip)} className="mt-3 inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-[#22c55e]/40 text-[#86efac] text-xs font-semibold"><CheckCircle2 size={14}/> Tutup & Rekonsiliasi</button>}
          </div>)}
        </div>
      </div>
    </div>

    <div className="card-surface p-5"><div className="font-semibold flex items-center gap-2 mb-4"><History size={17}/> History Bazar</div><div className="space-y-2 max-h-[420px] overflow-auto">{history.map((row) => <div key={row.id} className="border-b border-[#1f2937] pb-2 text-xs"><div className="font-medium">{row.eventType} · {row.referenceNo}</div><div className="text-[#8b93a1]">{new Date(row.time).toLocaleString('id-ID')} · {row.operator}</div></div>)}</div></div>

    {closing && <div className="fixed inset-0 z-[90] bg-black/75 flex items-center justify-center p-4"><div className="card-surface w-full max-w-2xl p-6 max-h-[90vh] overflow-y-auto"><h2 className="font-display text-xl font-bold">Rekonsiliasi {closing.tripNo}</h2><p className="text-xs text-[#8b93a1] mt-1 mb-4">Isi terjual dan retur rusak. Retur baik dihitung otomatis = Muat − Terjual − Retur Rusak.</p>{(closing.items || []).map((item) => { const sold = Number(closeRows[item.productId]?.soldQty || 0); const damaged = Number(closeRows[item.productId]?.returnedDamagedQty || 0); const good = Number(item.loadedQty || 0) - sold - damaged; return <div key={item.productId} className="border border-[#243044] rounded-xl p-4 mb-3"><div className="font-semibold text-sm">{item.name} · Muat {item.loadedQty} {item.unit}</div><div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-3"><input type="number" min="0" className={inputCls} placeholder="Terjual" value={closeRows[item.productId]?.soldQty || ''} onChange={(e) => setCloseRows((p) => ({ ...p, [item.productId]: { ...p[item.productId], soldQty: e.target.value } }))}/><input type="number" min="0" className={inputCls} placeholder="Retur rusak" value={closeRows[item.productId]?.returnedDamagedQty || ''} onChange={(e) => setCloseRows((p) => ({ ...p, [item.productId]: { ...p[item.productId], returnedDamagedQty: e.target.value } }))}/><div className="rounded-lg border border-[#243044] px-3 py-2.5 text-sm">Retur baik: <b>{good}</b></div></div></div>; })}<div className="flex justify-end gap-2 mt-5"><button onClick={() => setClosing(null)} className="px-4 py-2 rounded-lg border border-[#243044]">Batal</button><button onClick={closeTrip} className="btn-primary px-5 py-2 rounded-lg font-semibold">Selesaikan Bazar</button></div></div></div>}
  </div>;
};

export default BazarOperasional;
