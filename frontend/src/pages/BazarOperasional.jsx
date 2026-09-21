import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Car, CheckCircle2, FileText, History, Plus, Printer, RefreshCcw, ShoppingCart, Trash2 } from 'lucide-react';
import api, { apiError, downloadApiFile } from '../lib/api';
import { toast } from 'sonner';
import { useData } from '../context/DataContext';
import { defaultConsignmentStack, consignmentStackCodes } from '../lib/consignmentLocations';
import SearchableProductSelect from '../components/SearchableProductSelect';

const inputCls = 'w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';

const ConsignmentTransferCard = ({ destination, layouts = [], onChanged }) => {
  const [productId, setProductId] = useState('');
  const [sourceStackCode, setSourceStackCode] = useState('');
  const [destinationStackCode, setDestinationStackCode] = useState('');
  const [qty, setQty] = useState('');
  const [note, setNote] = useState('');
  const [savingTransfer, setSavingTransfer] = useState(false);

  const active = useMemo(
    () => (layouts || []).filter((row) => row.destination === destination && Number(row.primaryQty || 0) > 0),
    [layouts, destination],
  );
  const products = useMemo(() => {
    const byId = new Map();
    active.forEach((row) => {
      if (!byId.has(row.productId)) byId.set(row.productId, {
        id: row.productId,
        name: row.productName || row.sku || 'Komoditi',
        sku: row.sku || '',
        unit: row.unit || '',
      });
    });
    return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name, 'id'));
  }, [active]);
  const sources = active.filter((row) => row.productId === productId)
    .sort((a, b) => String(a.stackCode || '').localeCompare(String(b.stackCode || ''), 'id', { numeric: true }));
  const source = sources.find((row) => row.stackCode === sourceStackCode);
  const product = products.find((row) => row.id === productId);
  const targets = consignmentStackCodes(destination).filter((code) => code !== sourceStackCode);

  const chooseProduct = (value) => {
    setProductId(value);
    setSourceStackCode('');
    setDestinationStackCode('');
    setQty('');
  };

  const chooseSource = (value) => {
    setSourceStackCode(value);
    setDestinationStackCode(consignmentStackCodes(destination).find((code) => code !== value) || '');
    setQty('');
  };

  const submitTransfer = async () => {
    const numericQty = Number(qty || 0);
    if (!productId || !sourceStackCode || !destinationStackCode || numericQty <= 0) {
      return toast.error('Lengkapi komoditi, tumpukan asal, tujuan, dan jumlah mutasi');
    }
    if (numericQty > Number(source?.primaryQty || 0)) {
      return toast.error(`Saldo tumpukan asal hanya ${Number(source?.primaryQty || 0).toLocaleString('id-ID')} ${product?.unit || ''}`);
    }
    setSavingTransfer(true);
    try {
      const idempotencyKey = `mutasi-bazar-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
      const { data } = await api.post('/consignment-transfers', {
        destination, productId, sourceStackCode, destinationStackCode, qty: numericQty, note,
      }, { headers: { 'X-Idempotency-Key': idempotencyKey } });
      toast.success(`${data.sourceStackCode} → ${data.destinationStackCode} berhasil. Total stok Bazar tidak berubah.`);
      setQty('');
      setNote('');
      await onChanged?.();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSavingTransfer(false);
    }
  };

  return <div className="card-surface p-5">
    <div className="mb-4">
      <div className="font-semibold">Mutasi Tumpukan Bazar</div>
      
    </div>
    {products.length === 0 ? <div className="text-sm text-[#8b93a1]">Belum ada stok Bazar yang dapat dimutasi.</div> : <>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2">
        <SearchableProductSelect
          products={products}
          value={productId}
          onChange={chooseProduct}
          placeholder="Cari komoditi..."
          getDescription={(row) => `${row.sku || ''} · ${row.unit || ''}`}
        />
        <select className={inputCls} value={sourceStackCode} onChange={(e) => chooseSource(e.target.value)} disabled={!productId}>
          <option value="">Tumpukan asal...</option>
          {sources.map((row) => <option key={row.id} value={row.stackCode}>{row.stackCode} · {Number(row.primaryQty || 0).toLocaleString('id-ID')} {row.unit}</option>)}
        </select>
        <select className={inputCls} value={destinationStackCode} onChange={(e) => setDestinationStackCode(e.target.value)} disabled={!sourceStackCode}>
          <option value="">Tumpukan tujuan...</option>
          {targets.map((code) => <option key={code} value={code}>{code}</option>)}
        </select>
        <input type="number" min="0.01" step="any" className={inputCls} value={qty} onChange={(e) => setQty(e.target.value)} disabled={!sourceStackCode} placeholder={product?.unit ? `Jumlah (${product.unit})` : 'Jumlah'} />
      </div>
      <textarea rows={2} className={`${inputCls} mt-2`} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Catatan mutasi (opsional)" />
      <button onClick={submitTransfer} disabled={savingTransfer || !sourceStackCode} className="btn-primary mt-3 px-4 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50">
        {savingTransfer ? 'Memindahkan…' : 'Proses Mutasi'}
      </button>
    </>}
  </div>;
};

const BazarOperasional = () => {
  const { refreshConsignmentFlow, consignmentLayouts } = useData();
  const [availability, setAvailability] = useState([]);
  const [trips, setTrips] = useState([]);
  const [history, setHistory] = useState([]);
  const [saving, setSaving] = useState(false);
  const [downloading, setDownloading] = useState('');
  const [form, setForm] = useState({ eventDate: new Date().toISOString().slice(0, 10), location: '', vehicleNo: '', driver: '', note: '' });
  const [draft, setDraft] = useState({ productId: '', qty: '', stackCode: defaultConsignmentStack('Gudang Bazar') });
  const [items, setItems] = useState([]);
  const [closing, setClosing] = useState(null);
  const [closeRows, setCloseRows] = useState({});
  const [damagedStock, setDamagedStock] = useState([]);
  const [damageDiscovery, setDamageDiscovery] = useState({ productId: '', channel: '', stackCode: '', qty: '', cause: '', note: '' });
  const [damagedSale, setDamagedSale] = useState({ productId: '', channel: '', qty: '', recipient: '', referenceNo: '', note: '' });

  const load = async () => {
    const [a, t, h, d] = await Promise.all([
      api.get('/bazar/availability'),
      api.get('/bazar/trips'),
      api.get('/consignment-operation-history?destination=Gudang%20Bazar'),
      api.get('/consignment-damaged-stock?destination=Gudang%20Bazar'),
    ]);
    setAvailability(a.data);
    setTrips(t.data);
    setHistory(h.data.filter((x) => String(x.eventType || '').startsWith('BAZAR_')));
    setDamagedStock(d.data);
  };

  useEffect(() => { load().catch(() => {}); }, []);

  const stackOptions = useMemo(
    () => (consignmentLayouts || []).filter((row) => row.destination === 'Gudang Bazar' && row.productId === draft.productId),
    [consignmentLayouts, draft.productId],
  );

  const damageStackOptions = useMemo(
    () => (consignmentLayouts || []).filter((row) => row.destination === 'Gudang Bazar' && row.productId === damageDiscovery.productId),
    [consignmentLayouts, damageDiscovery.productId],
  );

  const chooseDamageProduct = (value) => {
    const [productId, channel = 'KOM'] = value.split('|');
    const first = (consignmentLayouts || []).find((row) => row.destination === 'Gudang Bazar' && row.productId === productId);
    setDamageDiscovery((prev) => ({ ...prev, productId, channel, stackCode: first?.stackCode || '', qty: '' }));
  };

  const recordDamageDiscovery = async () => {
    const qty = Number(damageDiscovery.qty || 0);
    if (!damageDiscovery.productId || !damageDiscovery.stackCode || qty <= 0 || !damageDiscovery.cause.trim()) {
      return toast.error('Pilih produk, lokasi, jumlah, dan penyebab kerusakan');
    }
    try {
      await api.post('/consignment-damaged/discoveries', {
        destination: 'Gudang Bazar',
        productId: damageDiscovery.productId,
        channel: damageDiscovery.channel,
        stackCode: damageDiscovery.stackCode,
        qty,
        cause: damageDiscovery.cause.trim(),
        note: damageDiscovery.note.trim(),
      });
      toast.success('Temuan rusak dipindahkan ke Area Barang Rusak Bazar');
      setDamageDiscovery({ productId: '', channel: '', stackCode: '', qty: '', cause: '', note: '' });
      await Promise.all([load(), refreshConsignmentFlow()]);
    } catch (e) { toast.error(apiError(e)); }
  };

  const chooseProduct = (productId) => {
    const first = (consignmentLayouts || []).find((row) => row.destination === 'Gudang Bazar' && row.productId === productId);
    setDraft((prev) => ({ ...prev, productId, stackCode: first?.stackCode || defaultConsignmentStack('Gudang Bazar') }));
  };

  const addItem = () => {
    const product = availability.find((x) => x.productId === draft.productId);
    const qty = Number(draft.qty || 0);
    if (!product || qty <= 0) return toast.error('Pilih komoditi dan isi jumlah muat');
    const existingQty = items.filter((x) => x.productId === product.productId).reduce((sum, x) => sum + Number(x.qty || 0), 0);
    if (existingQty + qty > Number(product.availableQty || 0)) return toast.error(`Stok tersedia ${product.name} hanya ${product.availableQty} ${product.unit}`);
    const stackCode = String(draft.stackCode || defaultConsignmentStack('Gudang Bazar')).toUpperCase();
    setItems((prev) => {
      const key = `${product.productId}|${stackCode}`;
      const existing = prev.find((x) => x.key === key);
      if (existing) return prev.map((x) => x.key === key ? { ...x, qty: Number(x.qty) + qty } : x);
      return [...prev, { key, productId: product.productId, name: product.name, unit: product.unit, qty, stackCode }];
    });
    setDraft({ productId: '', qty: '', stackCode: defaultConsignmentStack('Gudang Bazar') });
  };

  const createTrip = async () => {
    if (!form.location.trim() || !form.vehicleNo.trim() || items.length === 0) return toast.error('Lokasi bazar, kendaraan dan minimal satu komoditi wajib diisi');
    setSaving(true);
    try {
      const { data } = await api.post('/bazar/trips', { ...form, items: items.map(({ productId, qty, stackCode }) => ({ productId, qty: Number(qty), stackCode })) });
      toast.success(`Perjalanan Bazar dibuat · SJ ${data.suratJalanNo} · BM ${data.bonNo}`);
      setItems([]); setForm((p) => ({ ...p, note: '' }));
      await load();
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const downloadDoc = async (trip, type) => {
    const key = `${trip.id}-${type}`;
    setDownloading(key);
    try {
      await api.post(`/bazar/trips/${trip.id}/documents`);
      await downloadApiFile(
        `/export/bazar/trips/${trip.id}/${type}.pdf`,
        type === 'surat-jalan' ? `surat_jalan_${trip.tripNo}.pdf` : `bon_muat_${trip.tripNo}.pdf`,
      );
      await load();
    } catch (e) { toast.error(apiError(e)); } finally { setDownloading(''); }
  };

  const openClose = (trip) => {
    const rows = {};
    (trip.items || []).forEach((item) => { rows[`${item.productId}|${item.stackCode || ''}`] = { soldQty: '', returnedDamagedQty: '' }; });
    setCloseRows(rows); setClosing(trip);
  };

  const sellDamaged = async () => {
    const row = damagedStock.find((item) => item.productId === damagedSale.productId && item.channel === damagedSale.channel);
    const qty = Number(damagedSale.qty || 0);
    if (!row || qty <= 0) return toast.error('Pilih barang rusak dan isi jumlah yang dijual');
    if (qty > Number(row.qty || 0)) return toast.error(`Saldo rusak ${row.name} hanya ${row.qty} ${row.unit}`);
    try {
      await api.post('/consignment-damaged/sales', {
        destination: 'Gudang Bazar',
        productId: row.productId,
        channel: row.channel,
        qty,
        recipient: damagedSale.recipient.trim(),
        referenceNo: damagedSale.referenceNo.trim(),
        note: damagedSale.note.trim(),
      });
      toast.success('Penjualan barang rusak Bazar tersimpan');
      setDamagedSale({ productId: '', channel: '', qty: '', recipient: '', referenceNo: '', note: '' });
      await Promise.all([load(), refreshConsignmentFlow()]);
    } catch (e) { toast.error(apiError(e)); }
  };

  const closeTrip = async () => {
    try {
      const resultItems = (closing.items || []).map((item) => {
        const rowKey = `${item.productId}|${item.stackCode || ''}`;
        const sold = Number(closeRows[rowKey]?.soldQty || 0);
        const damaged = Number(closeRows[rowKey]?.returnedDamagedQty || 0);
        const returnedGood = Number(item.loadedQty || 0) - sold - damaged;
        if (returnedGood < 0) throw new Error(`${item.name}: terjual + retur rusak melebihi jumlah muat`);
        return { productId: item.productId, stackCode: item.stackCode || '', soldQty: sold, returnedDamagedQty: damaged, returnedGoodQty: returnedGood };
      });
      await api.post(`/bazar/trips/${closing.id}/close`, { items: resultItems, note: 'Rekonsiliasi penutupan bazar' });
      toast.success('Perjalanan Bazar selesai · retur rusak masuk Area Barang Rusak Bazar');
      setClosing(null); await Promise.all([load(), refreshConsignmentFlow()]);
    } catch (e) { toast.error(e?.response ? apiError(e) : e.message); }
  };

  return <div className="space-y-6">
    <div><div className="label-mono mb-2">Operasional Bazar</div><h1 className="font-display text-3xl sm:text-4xl font-bold">Perjalanan & Penjualan Bazar</h1></div>

    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
      <div className="card-surface p-5 xl:col-span-1 space-y-3">
        <div className="font-semibold flex items-center gap-2"><Plus size={17}/> Buat Perjalanan Bazar</div>
        <input type="date" className={inputCls} value={form.eventDate} onChange={(e) => setForm({ ...form, eventDate: e.target.value })} />
        <input className={inputCls} placeholder="Lokasi bazar / penerima" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} />
        <input className={inputCls} placeholder="No. kendaraan" value={form.vehicleNo} onChange={(e) => setForm({ ...form, vehicleNo: e.target.value })} />
        <input className={inputCls} placeholder="Pengemudi (opsional)" value={form.driver} onChange={(e) => setForm({ ...form, driver: e.target.value })} />
        <div className="rounded-xl border border-[#243044] p-3 space-y-2">
          <div className="text-xs font-semibold">Tambah Komoditi Muatan</div>
          <SearchableProductSelect
            products={availability.map((x) => ({ ...x, id: x.productId }))}
            value={draft.productId}
            onChange={chooseProduct}
            placeholder="Ketik nama / SKU komoditi..."
            getDescription={(x) => `${x.channel || 'KOM'} · tersedia ${x.availableQty} ${x.unit}`}
          />
          <select className={inputCls} value={draft.stackCode} onChange={(e) => setDraft({ ...draft, stackCode: e.target.value })}>
            {stackOptions.length === 0 && <option value={defaultConsignmentStack('Gudang Bazar')}>{defaultConsignmentStack('Gudang Bazar')} · belum dipetakan khusus</option>}
            {stackOptions.map((row) => <option key={row.id || row.stackCode} value={row.stackCode}>{row.stackCode} · {row.arrangementAdjusted ? 'perlu hitung ulang' : 'perkalian aktif'}</option>)}
          </select>
          <div className="flex gap-2"><input type="number" min="0" className={inputCls} placeholder="Jumlah muat" value={draft.qty} onChange={(e) => setDraft({ ...draft, qty: e.target.value })} /><button type="button" onClick={addItem} className="px-4 rounded-lg border border-[#3b82f6] text-[#93c5fd]">Tambah</button></div>
          <div className="space-y-1">{items.map((item) => <div key={item.key} className="flex items-center justify-between gap-2 text-xs bg-[#111827] rounded-lg px-3 py-2"><span>{item.name}<span className="text-[#8b93a1]"> · {item.stackCode}</span></span><span className="flex items-center gap-2"><b>{item.qty} {item.unit}</b><button onClick={() => setItems((p) => p.filter((x) => x.key !== item.key))} className="text-[#f87171]"><Trash2 size={13}/></button></span></div>)}</div>
        </div>
        <textarea className={inputCls} placeholder="Catatan" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
        <button disabled={saving} onClick={createTrip} className="btn-primary w-full py-2.5 rounded-lg font-semibold">{saving ? 'Menyimpan…' : `Muat ${items.length || ''} Komoditi ke Mobil`}</button>
      </div>

      <div className="card-surface p-5 xl:col-span-2">
        <div className="flex items-center justify-between mb-4"><div className="font-semibold flex items-center gap-2"><Car size={17}/> Perjalanan Bazar</div><button onClick={() => load()} className="text-xs inline-flex items-center gap-1 text-[#93c5fd]"><RefreshCcw size={13}/> Refresh</button></div>
        <div className="space-y-3">
          {trips.length === 0 && <div className="text-sm text-[#8b93a1]">Belum ada perjalanan Bazar.</div>}
          {trips.map((trip) => <div key={trip.id} className="border border-[#243044] rounded-xl p-4">
            <div className="flex flex-wrap items-start justify-between gap-2"><div><div className="font-semibold">{trip.tripNo} · {trip.location}</div><div className="text-xs text-[#8b93a1] mt-1">{trip.eventDate} · {trip.vehicleNo} · {trip.driver || 'Pengemudi belum diisi'}</div><div className="font-mono text-[10px] text-[#93c5fd] mt-1">SJ: {trip.suratJalanNo || 'belum dibuat'} · BM: {trip.bonNo || 'belum dibuat'}</div></div><span className={`text-xs px-2.5 py-1 rounded-full ${trip.status === 'SELESAI' ? 'bg-[#22c55e]/15 text-[#22c55e]' : 'bg-[#f59e0b]/15 text-[#f59e0b]'}`}>{trip.status}</span></div>
            <div className="mt-3 text-xs space-y-1">{(trip.items || []).map((item, index) => <div key={`${item.productId}-${item.stackCode}-${index}`} className="flex justify-between gap-3"><span>{item.name} · <span className="text-[#8b93a1]">{item.stackCode || defaultConsignmentStack('Gudang Bazar')}</span></span><span className="font-mono">Muat {item.loadedQty} {item.unit}</span></div>)}</div>
            <div className="flex flex-wrap gap-2 mt-3">
              <button disabled={downloading === `${trip.id}-surat-jalan`} onClick={() => downloadDoc(trip, 'surat-jalan')} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-[#2563eb]/50 text-[#93c5fd] text-xs font-semibold"><FileText size={13}/>{downloading === `${trip.id}-surat-jalan` ? 'Menyiapkan…' : 'Surat Jalan'}</button>
              <button disabled={downloading === `${trip.id}-bon-muat`} onClick={() => downloadDoc(trip, 'bon-muat')} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-[#64748b]/50 text-[#cbd5e1] text-xs font-semibold"><Printer size={13}/>{downloading === `${trip.id}-bon-muat` ? 'Menyiapkan…' : 'Bon Muat'}</button>
              {trip.status === 'BERJALAN' && <button onClick={() => openClose(trip)} className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-[#22c55e]/40 text-[#86efac] text-xs font-semibold"><CheckCircle2 size={14}/> Tutup & Rekonsiliasi</button>}
            </div>
            {trip.status === 'SELESAI' && <div className="mt-3 pt-3 border-t border-[#243044] text-xs space-y-1">{(trip.resultItems || []).map((item, index) => <div key={`${item.productId}-${index}`}>{item.name}: <b>{item.soldQty}</b> terjual · <b>{item.returnedGoodQty}</b> retur baik · <b>{item.returnedDamagedQty}</b> retur rusak</div>)}</div>}
          </div>)}
        </div>
      </div>
    </div>


    <div className="card-surface p-5">
      <div className="flex items-center gap-2 mb-4"><AlertTriangle size={17} className="text-[#f59e0b]"/><div className="font-semibold">Area Barang Rusak Bazar</div></div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div>
          {damagedStock.length === 0 ? <div className="text-sm text-[#8b93a1]">Belum ada saldo barang rusak Bazar.</div> : <div className="space-y-2">
            {damagedStock.map((row) => <div key={`${row.productId}-${row.channel}`} className="rounded-lg border border-[#7c5a1f] bg-[#191307] px-3 py-2.5 flex items-center justify-between gap-3 text-sm">
              <div><div className="font-semibold">{row.name}</div><div className="text-[10px] text-[#c9b783]">{row.sku || 'Tanpa SKU'} · {row.location || 'Area Barang Rusak Bazar'}</div></div>
              <div className="font-mono font-bold text-[#fbbf24]">{row.qty} {row.unit}</div>
            </div>)}
          </div>}
        </div>
        <div className="rounded-xl border border-[#7c5a1f] p-4 space-y-2">
          <div className="font-semibold text-sm flex items-center gap-2"><AlertTriangle size={15}/> Temuan Kerusakan Stok</div>
          <SearchableProductSelect
            products={availability.map((row) => ({ ...row, id: `${row.productId}|${row.channel || 'KOM'}` }))}
            value={damageDiscovery.productId ? `${damageDiscovery.productId}|${damageDiscovery.channel}` : ''}
            onChange={chooseDamageProduct}
            placeholder="Cari stok baik..."
            getDescription={(row) => `${row.channel || 'KOM'} · tersedia ${row.availableQty} ${row.unit}`}
          />
          <select className={inputCls} value={damageDiscovery.stackCode} onChange={(e) => setDamageDiscovery((p) => ({ ...p, stackCode: e.target.value }))}>
            <option value="">Pilih lokasi fisik</option>
            {damageStackOptions.map((row) => <option key={row.id} value={row.stackCode}>{row.stackCode} · {row.primaryQty} {row.unit}</option>)}
          </select>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <input type="number" min="0" className={inputCls} placeholder="Jumlah rusak" value={damageDiscovery.qty} onChange={(e) => setDamageDiscovery((p) => ({ ...p, qty: e.target.value }))}/>
            <input className={inputCls} placeholder="Penyebab kerusakan" value={damageDiscovery.cause} onChange={(e) => setDamageDiscovery((p) => ({ ...p, cause: e.target.value }))}/>
          </div>
          <textarea className={inputCls} placeholder="Catatan (opsional)" value={damageDiscovery.note} onChange={(e) => setDamageDiscovery((p) => ({ ...p, note: e.target.value }))}/>
          <button onClick={recordDamageDiscovery} className="w-full py-2.5 rounded-lg border border-[#f59e0b]/50 text-[#fbbf24] font-semibold">Pindahkan ke Area Barang Rusak Bazar</button>
        </div>
        <div className="rounded-xl border border-[#243044] p-4 space-y-2">
          <div className="font-semibold text-sm flex items-center gap-2"><ShoppingCart size={15}/> Penjualan Barang Rusak</div>
          <SearchableProductSelect
            products={damagedStock.map((row) => ({ ...row, id: `${row.productId}|${row.channel}` }))}
            value={damagedSale.productId ? `${damagedSale.productId}|${damagedSale.channel}` : ''}
            onChange={(value) => { const [productId, channel = ''] = value.split('|'); setDamagedSale((p) => ({ ...p, productId, channel, qty: '' })); }}
            placeholder="Cari barang rusak..."
            getDescription={(row) => `${row.channel} · saldo ${row.qty} ${row.unit}`}
          />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <input type="number" min="0" className={inputCls} placeholder="Jumlah dijual" value={damagedSale.qty} onChange={(e) => setDamagedSale((p) => ({ ...p, qty: e.target.value }))}/>
            <input className={inputCls} placeholder="Pembeli / penerima" value={damagedSale.recipient} onChange={(e) => setDamagedSale((p) => ({ ...p, recipient: e.target.value }))}/>
          </div>
          <input className={inputCls} placeholder="No. referensi (opsional)" value={damagedSale.referenceNo} onChange={(e) => setDamagedSale((p) => ({ ...p, referenceNo: e.target.value }))}/>
          <textarea className={inputCls} placeholder="Catatan penjualan (opsional)" value={damagedSale.note} onChange={(e) => setDamagedSale((p) => ({ ...p, note: e.target.value }))}/>
          <button onClick={sellDamaged} disabled={!damagedStock.length} className="w-full py-2.5 rounded-lg border border-[#f59e0b]/50 text-[#fbbf24] font-semibold disabled:opacity-40">Jual Barang Rusak Bazar</button>
        </div>
      </div>
    </div>

    <ConsignmentTransferCard destination="Gudang Bazar" layouts={consignmentLayouts} onChanged={async () => { await Promise.all([load(), refreshConsignmentFlow()]); }} />\n\n    <div className="card-surface p-5"><div className="font-semibold flex items-center gap-2 mb-4"><History size={17}/> History Bazar</div><div className="space-y-2 max-h-[420px] overflow-auto">{history.map((row) => <div key={row.id} className="border-b border-[#1f2937] pb-2 text-xs"><div className="font-medium">{row.eventType} · {row.referenceNo}</div><div className="text-[#8b93a1]">{new Date(row.time).toLocaleString('id-ID')} · {row.operator}</div></div>)}</div></div>

    {closing && <div className="fixed inset-0 z-[90] bg-black/75 flex items-center justify-center p-4"><div className="card-surface w-full max-w-2xl p-6 max-h-[90vh] overflow-y-auto"><h2 className="font-display text-xl font-bold">Rekonsiliasi {closing.tripNo}</h2><p className="text-xs text-[#8b93a1] mt-1 mb-4">Isi terjual dan retur rusak. Retur baik dihitung otomatis = Muat − Terjual − Retur Rusak. Retur rusak otomatis masuk Area Barang Rusak Bazar.</p>{(closing.items || []).map((item, index) => { const rowKey = `${item.productId}|${item.stackCode || ''}`; const sold = Number(closeRows[rowKey]?.soldQty || 0); const damaged = Number(closeRows[rowKey]?.returnedDamagedQty || 0); const good = Number(item.loadedQty || 0) - sold - damaged; return <div key={`${rowKey}-${index}`} className="border border-[#243044] rounded-xl p-4 mb-3"><div className="font-semibold text-sm">{item.name} · {item.stackCode || defaultConsignmentStack('Gudang Bazar')} · Muat {item.loadedQty} {item.unit}</div><div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-3"><input type="number" min="0" className={inputCls} placeholder="Terjual" value={closeRows[rowKey]?.soldQty || ''} onChange={(e) => setCloseRows((p) => ({ ...p, [rowKey]: { ...p[rowKey], soldQty: e.target.value } }))}/><input type="number" min="0" className={inputCls} placeholder="Retur rusak" value={closeRows[rowKey]?.returnedDamagedQty || ''} onChange={(e) => setCloseRows((p) => ({ ...p, [rowKey]: { ...p[rowKey], returnedDamagedQty: e.target.value } }))}/><div className="rounded-lg border border-[#243044] px-3 py-2.5 text-sm">Retur baik: <b>{good}</b></div></div></div>; })}<div className="flex justify-end gap-2 mt-5"><button onClick={() => setClosing(null)} className="px-4 py-2 rounded-lg border border-[#243044]">Batal</button><button onClick={closeTrip} className="btn-primary px-5 py-2 rounded-lg font-semibold">Selesaikan Bazar</button></div></div></div>}
  </div>;
};

export default BazarOperasional;
