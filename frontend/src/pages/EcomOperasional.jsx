import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, History, PackageCheck, PackagePlus, Plus, RefreshCcw, RotateCcw, ShoppingCart, Truck } from 'lucide-react';
import api, { apiError } from '../lib/api';
import { toast } from 'sonner';
import { useData } from '../context/DataContext';

const inputCls = 'w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';

const EcomOperasional = () => {
  const { refreshConsignmentFlow, consignmentLayouts } = useData();
  const [availability, setAvailability] = useState([]);
  const [orders, setOrders] = useState([]);
  const [history, setHistory] = useState([]);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ marketplace: 'Manual', orderNo: '', buyer: '', productId: '', qty: '', note: '' });
  const [orderItems, setOrderItems] = useState([]);
  const [returnOrder, setReturnOrder] = useState(null);
  const [returnRows, setReturnRows] = useState({});
  const [damagedStock, setDamagedStock] = useState([]);
  const [damageDiscovery, setDamageDiscovery] = useState({ productId: '', channel: '', stackCode: '', qty: '', cause: '', note: '' });
  const [damagedSale, setDamagedSale] = useState({ productId: '', channel: '', qty: '', recipient: '', referenceNo: '', note: '' });

  const load = async () => {
    const [a, o, h, d] = await Promise.all([
      api.get('/ecom/availability'),
      api.get('/ecom/orders'),
      api.get('/consignment-operation-history?destination=Gudang%20E-commerce'),
      api.get('/consignment-damaged-stock?destination=Gudang%20E-commerce'),
    ]);
    setAvailability(a.data);
    setOrders(o.data);
    setHistory(h.data);
    setDamagedStock(d.data);
  };

  useEffect(() => { load().catch(() => {}); }, []);

  useEffect(() => {
    const ECOM_AUTO_REFRESH_INTERVAL = 15000;
    const sync = () => {
      if (document.visibilityState === 'visible' && navigator.onLine) load().catch(() => {});
    };
    const intervalId = window.setInterval(sync, ECOM_AUTO_REFRESH_INTERVAL);
    const handleVisibility = () => { if (document.visibilityState === 'visible') sync(); };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, []);
  const selected = useMemo(() => availability.find((x) => x.productId === form.productId), [availability, form.productId]);
  const damageStackOptions = useMemo(
    () => (consignmentLayouts || []).filter((row) => row.destination === 'Gudang E-commerce' && row.productId === damageDiscovery.productId),
    [consignmentLayouts, damageDiscovery.productId],
  );

  const chooseDamageProduct = (value) => {
    const [productId, channel = 'KOM'] = value.split('|');
    const first = (consignmentLayouts || []).find((row) => row.destination === 'Gudang E-commerce' && row.productId === productId);
    setDamageDiscovery((prev) => ({ ...prev, productId, channel, stackCode: first?.stackCode || '', qty: '' }));
  };

  const recordDamageDiscovery = async () => {
    const qty = Number(damageDiscovery.qty || 0);
    if (!damageDiscovery.productId || !damageDiscovery.stackCode || qty <= 0 || !damageDiscovery.cause.trim()) {
      return toast.error('Pilih produk, lokasi, jumlah, dan penyebab kerusakan');
    }
    try {
      await api.post('/consignment-damaged/discoveries', {
        destination: 'Gudang E-commerce',
        productId: damageDiscovery.productId,
        channel: damageDiscovery.channel,
        stackCode: damageDiscovery.stackCode,
        qty,
        cause: damageDiscovery.cause.trim(),
        note: damageDiscovery.note.trim(),
      });
      toast.success('Temuan rusak dipindahkan ke Area Barang Rusak E-commerce');
      setDamageDiscovery({ productId: '', channel: '', stackCode: '', qty: '', cause: '', note: '' });
      await Promise.all([load(), refreshConsignmentFlow()]);
    } catch (e) { toast.error(apiError(e)); }
  };

  const addOrderItem = () => {
    if (!form.productId || Number(form.qty) <= 0) return toast.error('Pilih produk dan isi jumlah');
    const row = availability.find((x) => x.productId === form.productId);
    if (!row) return;
    setOrderItems((prev) => {
      const found = prev.find((x) => x.productId === row.productId);
      if (found) return prev.map((x) => x.productId === row.productId ? { ...x, qty: Number(x.qty) + Number(form.qty) } : x);
      return [...prev, { productId: row.productId, name: row.name, unit: row.unit, qty: Number(form.qty) }];
    });
    setForm((p) => ({ ...p, productId: '', qty: '' }));
  };

  const createOrder = async () => {
    if (!form.orderNo.trim() || orderItems.length === 0) return toast.error('Nomor pesanan dan minimal satu produk wajib diisi');
    setSaving(true);
    try {
      await api.post('/ecom/orders', { marketplace: form.marketplace, orderNo: form.orderNo, buyer: form.buyer, note: form.note, items: orderItems.map((x) => ({ productId: x.productId, qty: Number(x.qty) })) });
      toast.success('Pesanan dibuat dan stok E-commerce telah direservasi');
      setForm((p) => ({ ...p, orderNo: '', buyer: '', productId: '', qty: '', note: '' }));
      setOrderItems([]);
      await load();
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const setStatus = async (order, status) => {
    try {
      let trackingNo = order.trackingNo || '';
      if (status === 'SHIPPED' && !trackingNo) trackingNo = window.prompt('Nomor resi (boleh dikosongkan):', '') || '';
      await api.post(`/ecom/orders/${order.id}/status`, { status, trackingNo, note: '' });
      toast.success(`Status pesanan menjadi ${status}`); await Promise.all([load(), refreshConsignmentFlow()]);
    } catch (e) { toast.error(apiError(e)); }
  };

  const openReturn = (order) => {
    const rows = {}; (order.items || []).forEach((item) => { rows[item.productId] = { goodQty: '', damagedQty: '' }; });
    setReturnRows(rows); setReturnOrder(order);
  };

  const sellDamaged = async () => {
    const row = damagedStock.find((item) => item.productId === damagedSale.productId && item.channel === damagedSale.channel);
    const qty = Number(damagedSale.qty || 0);
    if (!row || qty <= 0) return toast.error('Pilih barang rusak dan isi jumlah yang dijual');
    if (qty > Number(row.qty || 0)) return toast.error(`Saldo rusak ${row.name} hanya ${row.qty} ${row.unit}`);
    try {
      await api.post('/consignment-damaged/sales', {
        destination: 'Gudang E-commerce',
        productId: row.productId,
        channel: row.channel,
        qty,
        recipient: damagedSale.recipient.trim(),
        referenceNo: damagedSale.referenceNo.trim(),
        note: damagedSale.note.trim(),
      });
      toast.success('Penjualan barang rusak E-commerce tersimpan');
      setDamagedSale({ productId: '', channel: '', qty: '', recipient: '', referenceNo: '', note: '' });
      await Promise.all([load(), refreshConsignmentFlow()]);
    } catch (e) { toast.error(apiError(e)); }
  };

  const submitReturn = async () => {
    try {
      const items = (returnOrder.items || []).map((item) => ({ productId: item.productId, goodQty: Number(returnRows[item.productId]?.goodQty || 0), damagedQty: Number(returnRows[item.productId]?.damagedQty || 0) }));
      await api.post(`/ecom/orders/${returnOrder.id}/return`, { items, note: 'Retur E-commerce diterima' });
      toast.success('Retur E-commerce diterima · barang rusak masuk Area Barang Rusak E-commerce'); setReturnOrder(null); await Promise.all([load(), refreshConsignmentFlow()]);
    } catch (e) { toast.error(apiError(e)); }
  };

  return <div className="space-y-6">
    <div><div className="label-mono mb-2">Operasional E-commerce</div><h1 className="font-display text-3xl sm:text-4xl font-bold">Pesanan & Fulfillment E-commerce</h1></div>

    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
      <div className="card-surface p-5 space-y-3">
        <div className="font-semibold flex items-center gap-2"><PackagePlus size={17}/> Input Pesanan</div>
        <select className={inputCls} value={form.marketplace} onChange={(e) => setForm({ ...form, marketplace: e.target.value })}><option>Manual</option><option>Shopee</option><option>Tokopedia</option><option>TikTok Shop</option><option>Lainnya</option></select>
        <input className={inputCls} placeholder="Nomor pesanan" value={form.orderNo} onChange={(e) => setForm({ ...form, orderNo: e.target.value })}/>
        <input className={inputCls} placeholder="Pembeli (opsional)" value={form.buyer} onChange={(e) => setForm({ ...form, buyer: e.target.value })}/>
        <div className="grid grid-cols-[1fr_120px_auto] gap-2">
          <select className={inputCls} value={form.productId} onChange={(e) => setForm({ ...form, productId: e.target.value })}><option value="">Pilih komoditi</option>{availability.map((x) => <option key={x.productId} value={x.productId}>{x.name} · tersedia {x.availableQty} {x.unit}</option>)}</select>
          <input type="number" min="0" className={inputCls} placeholder="Jumlah" value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })}/>
          <button type="button" onClick={addOrderItem} className="px-3 rounded-lg border border-[#3b82f6]/50 text-[#93c5fd]"><Plus size={17}/></button>
        </div>
        {selected && <div className="text-xs text-[#94a3b8]">Fisik {selected.physicalQty} · Reserved {selected.reservedQty} · Tersedia {selected.availableQty} {selected.unit}</div>}
        <div className="space-y-2">{orderItems.map((x) => <div key={x.productId} className="flex justify-between border border-[#243044] rounded-lg px-3 py-2 text-xs"><span>{x.name}</span><span className="font-mono">{x.qty} {x.unit}</span></div>)}</div>
        <textarea className={inputCls} placeholder="Catatan" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })}/>
        <button disabled={saving} onClick={createOrder} className="btn-primary w-full py-2.5 rounded-lg font-semibold">{saving ? 'Menyimpan…' : 'Buat & Reservasi Order'}</button>
      </div>

      <div className="card-surface p-5 xl:col-span-2">
        <div className="flex items-center justify-between mb-4"><div className="font-semibold flex items-center gap-2"><PackageCheck size={17}/> Daftar Pesanan</div><button onClick={() => load()} className="text-xs inline-flex items-center gap-1 text-[#93c5fd]"><RefreshCcw size={13}/> Refresh</button></div>
        <div className="space-y-3">
          {orders.length === 0 && <div className="text-sm text-[#8b93a1]">Belum ada pesanan E-commerce.</div>}
          {orders.map((order) => <div key={order.id} className="border border-[#243044] rounded-xl p-4">
            <div className="flex flex-wrap justify-between gap-2"><div><div className="font-semibold">{order.marketplace} · {order.orderNo}</div><div className="text-xs text-[#8b93a1] mt-1">{order.buyer || 'Pembeli tidak dicatat'} {order.trackingNo ? `· Resi ${order.trackingNo}` : ''}</div></div><span className="text-xs px-2.5 py-1 rounded-full bg-[#2563eb]/15 text-[#93c5fd]">{order.status}</span></div>
            <div className="mt-3 text-xs space-y-1">{(order.items || []).map((item) => <div key={item.productId} className="flex justify-between gap-3"><span>{item.name}</span><span className="font-mono">{item.qty} {item.unit}</span></div>)}</div>
            <div className="flex flex-wrap gap-2 mt-3">
              {order.status === 'RESERVED' && <button onClick={() => setStatus(order, 'PACKING')} className="px-3 py-2 rounded-lg border border-[#f59e0b]/40 text-[#fbbf24] text-xs font-semibold">Packing</button>}
              {['RESERVED','PACKING'].includes(order.status) && <button onClick={() => setStatus(order, 'SHIPPED')} className="px-3 py-2 rounded-lg border border-[#22c55e]/40 text-[#86efac] text-xs font-semibold inline-flex items-center gap-1"><Truck size={13}/> Dikirim</button>}
              {['RESERVED','PACKING'].includes(order.status) && <button onClick={() => setStatus(order, 'CANCELLED')} className="px-3 py-2 rounded-lg border border-[#ef4444]/40 text-[#fca5a5] text-xs font-semibold">Batal</button>}
              {['SHIPPED','PARTIAL_RETURN'].includes(order.status) && <button onClick={() => openReturn(order)} className="px-3 py-2 rounded-lg border border-[#60a5fa]/40 text-[#93c5fd] text-xs font-semibold inline-flex items-center gap-1"><RotateCcw size={13}/> Terima Retur</button>}
            </div>
          </div>)}
        </div>
      </div>
    </div>


    <div className="card-surface p-5">
      <div className="flex items-center gap-2 mb-4"><AlertTriangle size={17} className="text-[#f59e0b]"/><div className="font-semibold">Area Barang Rusak E-commerce</div></div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div>
          {damagedStock.length === 0 ? <div className="text-sm text-[#8b93a1]">Belum ada saldo barang rusak E-commerce.</div> : <div className="space-y-2">
            {damagedStock.map((row) => <div key={`${row.productId}-${row.channel}`} className="rounded-lg border border-[#7c5a1f] bg-[#191307] px-3 py-2.5 flex items-center justify-between gap-3 text-sm">
              <div><div className="font-semibold">{row.name}</div><div className="text-[10px] text-[#c9b783]">{row.sku || 'Tanpa SKU'} · {row.location || 'Area Barang Rusak E-commerce'}</div></div>
              <div className="font-mono font-bold text-[#fbbf24]">{row.qty} {row.unit}</div>
            </div>)}
          </div>}
        </div>
        <div className="rounded-xl border border-[#7c5a1f] p-4 space-y-2">
          <div className="font-semibold text-sm flex items-center gap-2"><AlertTriangle size={15}/> Temuan Kerusakan Stok</div>
          <select className={inputCls} value={damageDiscovery.productId ? `${damageDiscovery.productId}|${damageDiscovery.channel}` : ''} onChange={(e) => chooseDamageProduct(e.target.value)}>
            <option value="">Pilih stok baik</option>
            {availability.map((row) => <option key={`${row.productId}-${row.channel || 'KOM'}`} value={`${row.productId}|${row.channel || 'KOM'}`}>{row.name} · {row.channel || 'KOM'} · tersedia {row.availableQty} {row.unit}</option>)}
          </select>
          <select className={inputCls} value={damageDiscovery.stackCode} onChange={(e) => setDamageDiscovery((p) => ({ ...p, stackCode: e.target.value }))}>
            <option value="">Pilih lokasi fisik</option>
            {damageStackOptions.map((row) => <option key={row.id} value={row.stackCode}>{row.stackCode} · {row.primaryQty} {row.unit}</option>)}
          </select>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <input type="number" min="0" className={inputCls} placeholder="Jumlah rusak" value={damageDiscovery.qty} onChange={(e) => setDamageDiscovery((p) => ({ ...p, qty: e.target.value }))}/>
            <input className={inputCls} placeholder="Penyebab kerusakan" value={damageDiscovery.cause} onChange={(e) => setDamageDiscovery((p) => ({ ...p, cause: e.target.value }))}/>
          </div>
          <textarea className={inputCls} placeholder="Catatan (opsional)" value={damageDiscovery.note} onChange={(e) => setDamageDiscovery((p) => ({ ...p, note: e.target.value }))}/>
          <button onClick={recordDamageDiscovery} className="w-full py-2.5 rounded-lg border border-[#f59e0b]/50 text-[#fbbf24] font-semibold">Pindahkan ke Area Barang Rusak E-commerce</button>
        </div>
        <div className="rounded-xl border border-[#243044] p-4 space-y-2">
          <div className="font-semibold text-sm flex items-center gap-2"><ShoppingCart size={15}/> Penjualan Barang Rusak</div>
          <select className={inputCls} value={damagedSale.productId ? `${damagedSale.productId}|${damagedSale.channel}` : ''} onChange={(e) => { const [productId, channel = ''] = e.target.value.split('|'); setDamagedSale((p) => ({ ...p, productId, channel, qty: '' })); }}>
            <option value="">Pilih barang rusak</option>
            {damagedStock.map((row) => <option key={`${row.productId}-${row.channel}`} value={`${row.productId}|${row.channel}`}>{row.name} · {row.channel} · saldo {row.qty} {row.unit}</option>)}
          </select>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <input type="number" min="0" className={inputCls} placeholder="Jumlah dijual" value={damagedSale.qty} onChange={(e) => setDamagedSale((p) => ({ ...p, qty: e.target.value }))}/>
            <input className={inputCls} placeholder="Pembeli / penerima" value={damagedSale.recipient} onChange={(e) => setDamagedSale((p) => ({ ...p, recipient: e.target.value }))}/>
          </div>
          <input className={inputCls} placeholder="No. referensi (opsional)" value={damagedSale.referenceNo} onChange={(e) => setDamagedSale((p) => ({ ...p, referenceNo: e.target.value }))}/>
          <textarea className={inputCls} placeholder="Catatan penjualan (opsional)" value={damagedSale.note} onChange={(e) => setDamagedSale((p) => ({ ...p, note: e.target.value }))}/>
          <button onClick={sellDamaged} disabled={!damagedStock.length} className="w-full py-2.5 rounded-lg border border-[#f59e0b]/50 text-[#fbbf24] font-semibold disabled:opacity-40">Jual Barang Rusak E-commerce</button>
        </div>
      </div>
    </div>

    <div className="card-surface p-5"><div className="font-semibold flex items-center gap-2 mb-4"><History size={17}/> History E-commerce</div><div className="space-y-2 max-h-[420px] overflow-auto">{history.map((row) => <div key={row.id} className="border-b border-[#1f2937] pb-2 text-xs"><div className="font-medium">{row.eventType} · {row.referenceNo}</div><div className="text-[#8b93a1]">{new Date(row.time).toLocaleString('id-ID')} · {row.operator}</div></div>)}</div></div>

    {returnOrder && <div className="fixed inset-0 z-[90] bg-black/75 flex items-center justify-center p-4"><div className="card-surface w-full max-w-2xl p-6"><h2 className="font-display text-xl font-bold">Retur {returnOrder.orderNo}</h2><p className="text-xs text-[#8b93a1] mt-1 mb-4">Retur baik kembali ke stok jual E-commerce. Retur rusak otomatis masuk Area Barang Rusak E-commerce dan tidak menambah stok jual.</p>{(returnOrder.items || []).map((item) => <div key={item.productId} className="border border-[#243044] rounded-xl p-4 mb-3"><div className="font-semibold text-sm">{item.name} · Dikirim {item.qty} {item.unit}</div><div className="grid grid-cols-2 gap-2 mt-3"><input type="number" min="0" className={inputCls} placeholder="Retur baik" value={returnRows[item.productId]?.goodQty || ''} onChange={(e) => setReturnRows((p) => ({ ...p, [item.productId]: { ...p[item.productId], goodQty: e.target.value } }))}/><input type="number" min="0" className={inputCls} placeholder="Retur rusak" value={returnRows[item.productId]?.damagedQty || ''} onChange={(e) => setReturnRows((p) => ({ ...p, [item.productId]: { ...p[item.productId], damagedQty: e.target.value } }))}/></div></div>)}<div className="flex justify-end gap-2 mt-5"><button onClick={() => setReturnOrder(null)} className="px-4 py-2 rounded-lg border border-[#243044]">Batal</button><button onClick={submitReturn} className="btn-primary px-5 py-2 rounded-lg font-semibold">Simpan Retur</button></div></div></div>}
  </div>;
};

export default EcomOperasional;
