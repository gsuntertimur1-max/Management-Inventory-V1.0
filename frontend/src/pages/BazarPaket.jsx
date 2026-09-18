import React, { useEffect, useMemo, useState } from 'react';
import { Boxes, CheckCircle2, FileText, History, PackagePlus, Plus, Printer, RefreshCcw, Truck, Undo2 } from 'lucide-react';
import api, { apiError, downloadApiFile } from '../lib/api';
import { toast } from 'sonner';
import { useData } from '../context/DataContext';

const inputCls = 'w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';

const BazarPaket = () => {
  const { refreshConsignmentFlow } = useData();
  const [availability, setAvailability] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [packageStock, setPackageStock] = useState([]);
  const [batches, setBatches] = useState([]);
  const [loads, setLoads] = useState([]);
  const [history, setHistory] = useState([]);
  const [saving, setSaving] = useState(false);
  const [downloading, setDownloading] = useState('');

  const [master, setMaster] = useState({ code: '', name: '', note: '', productId: '', qty: '' });
  const [components, setComponents] = useState([]);
  const [assemble, setAssemble] = useState({ templateId: '', qty: '', note: '' });
  const [loadForm, setLoadForm] = useState({ date: new Date().toISOString().slice(0, 10), destination: '', vehicleNo: '', driver: '', templateId: '', qty: '', note: '' });
  const [loadItems, setLoadItems] = useState([]);
  const [closing, setClosing] = useState(null);
  const [closeRows, setCloseRows] = useState({});

  const loadAll = async () => {
    const [a, t, s, b, l, h] = await Promise.all([
      api.get('/bazar/availability'),
      api.get('/bazar/package-templates'),
      api.get('/bazar/package-stock'),
      api.get('/bazar/package-batches'),
      api.get('/bazar/package-loads'),
      api.get('/consignment-operation-history?destination=Gudang%20Bazar'),
    ]);
    setAvailability(a.data);
    setTemplates(t.data);
    setPackageStock(s.data);
    setBatches(b.data);
    setLoads(l.data);
    setHistory(h.data.filter((x) => String(x.eventType || '').startsWith('PAKET_')));
  };

  useEffect(() => { loadAll().catch(() => {}); }, []);

  const selectedProduct = useMemo(() => availability.find((x) => x.productId === master.productId), [availability, master.productId]);
  const selectedTemplateStock = useMemo(() => packageStock.find((x) => x.id === loadForm.templateId), [packageStock, loadForm.templateId]);

  const addComponent = () => {
    if (!master.productId || Number(master.qty) <= 0) return toast.error('Pilih komoditi dan isi jumlah per paket');
    const product = availability.find((x) => x.productId === master.productId);
    if (!product) return;
    setComponents((prev) => {
      const found = prev.find((x) => x.productId === master.productId);
      if (found) return prev.map((x) => x.productId === master.productId ? { ...x, qty: Number(x.qty) + Number(master.qty) } : x);
      return [...prev, { productId: master.productId, name: product.name, unit: product.unit, qty: Number(master.qty) }];
    });
    setMaster((p) => ({ ...p, productId: '', qty: '' }));
  };

  const createTemplate = async () => {
    if (!master.code.trim() || !master.name.trim() || components.length === 0) return toast.error('Kode, nama, dan komposisi paket wajib diisi');
    setSaving(true);
    try {
      await api.post('/bazar/package-templates', {
        code: master.code, name: master.name, note: master.note,
        components: components.map((x) => ({ productId: x.productId, qty: Number(x.qty) })),
      });
      toast.success('Master paket berhasil dibuat');
      setMaster({ code: '', name: '', note: '', productId: '', qty: '' });
      setComponents([]);
      await loadAll();
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const assemblePackage = async () => {
    if (!assemble.templateId || Number(assemble.qty) <= 0) return toast.error('Pilih paket dan isi jumlah yang dirakit');
    setSaving(true);
    try {
      await api.post('/bazar/packages/assemble', { templateId: assemble.templateId, qty: Number(assemble.qty), note: assemble.note });
      toast.success('Paket selesai dirakit dan masuk Stok Paket Jadi');
      setAssemble({ templateId: '', qty: '', note: '' });
      await loadAll();
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const unpackBatch = async (batch) => {
    const raw = window.prompt(`Jumlah paket yang akan dibongkar dari ${batch.batchNo} (maks. ${batch.remainingQty}):`, '');
    const qty = Number(raw || 0);
    if (qty <= 0) return;
    try {
      await api.post(`/bazar/package-batches/${batch.id}/unpack`, { qty, note: 'Pembongkaran Paket Jadi' });
      toast.success('Paket dibongkar; komponen kembali tersedia sebagai stok loose');
      await loadAll();
    } catch (e) { toast.error(apiError(e)); }
  };

  const addLoadItem = () => {
    if (!loadForm.templateId || Number(loadForm.qty) <= 0) return toast.error('Pilih Paket Jadi dan jumlah muat');
    const row = packageStock.find((x) => x.id === loadForm.templateId);
    if (!row) return;
    setLoadItems((prev) => {
      const found = prev.find((x) => x.templateId === row.id);
      if (found) return prev.map((x) => x.templateId === row.id ? { ...x, qty: Number(x.qty) + Number(loadForm.qty) } : x);
      return [...prev, { templateId: row.id, packageName: row.name, code: row.code, qty: Number(loadForm.qty) }];
    });
    setLoadForm((p) => ({ ...p, templateId: '', qty: '' }));
  };

  const createLoad = async () => {
    if (!loadForm.destination.trim() || !loadForm.vehicleNo.trim() || loadItems.length === 0) return toast.error('Tujuan, kendaraan, dan paket yang dimuat wajib diisi');
    setSaving(true);
    try {
      await api.post('/bazar/package-loads', {
        date: loadForm.date, destination: loadForm.destination, vehicleNo: loadForm.vehicleNo,
        driver: loadForm.driver, note: loadForm.note,
        items: loadItems.map((x) => ({ templateId: x.templateId, qty: Number(x.qty) })),
      });
      toast.success('Paket berhasil dimuat dan masuk status perjalanan');
      setLoadItems([]);
      setLoadForm({ date: new Date().toISOString().slice(0, 10), destination: '', vehicleNo: '', driver: '', templateId: '', qty: '', note: '' });
      await loadAll();
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const openClose = (load) => {
    const rows = {};
    (load.items || []).forEach((item) => { rows[item.templateId] = { deliveredQty: '', returnedDamagedQty: '' }; });
    setCloseRows(rows); setClosing(load);
  };

  const closeLoad = async () => {
    try {
      const items = (closing.items || []).map((item) => {
        const delivered = Number(closeRows[item.templateId]?.deliveredQty || 0);
        const damaged = Number(closeRows[item.templateId]?.returnedDamagedQty || 0);
        const returnedGood = Number(item.loadedQty || 0) - delivered - damaged;
        if (returnedGood < 0) throw new Error(`${item.packageName}: disalurkan + retur rusak melebihi jumlah muat`);
        return { templateId: item.templateId, deliveredQty: delivered, returnedGoodQty: returnedGood, returnedDamagedQty: damaged };
      });
      await api.post(`/bazar/package-loads/${closing.id}/close`, { items, note: 'Rekonsiliasi distribusi paket' });
      toast.success('Distribusi paket selesai dan stok telah direkonsiliasi');
      setClosing(null); await Promise.all([loadAll(), refreshConsignmentFlow()]);
    } catch (e) { toast.error(e?.response ? apiError(e) : e.message); }
  };

  const downloadDocument = async (load, type) => {
    const key = `${load.id}-${type}`;
    setDownloading(key);
    try {
      await api.post(`/bazar/package-loads/${load.id}/documents`);
      await downloadApiFile(
        `/export/bazar/package-loads/${load.id}/${type}.pdf`,
        type === 'surat-jalan' ? `surat_jalan_${load.loadNo}.pdf` : `bon_muat_${load.loadNo}.pdf`,
      );
      await loadAll();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setDownloading('');
    }
  };

  return <div className="space-y-6">
    <div>
      <div className="label-mono mb-2">Operasional Bazar · Paket</div>
      <h1 className="font-display text-3xl sm:text-4xl font-bold">Pembuatan & Distribusi Paket</h1>
    </div>

    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <section className="card-surface p-5 space-y-3">
        <div className="font-semibold flex items-center gap-2"><PackagePlus size={17}/> Master Komposisi Paket</div>
        <div className="grid grid-cols-2 gap-2">
          <input className={inputCls} placeholder="Kode paket, mis. PKT-01" value={master.code} onChange={(e) => setMaster({ ...master, code: e.target.value })}/>
          <input className={inputCls} placeholder="Nama paket" value={master.name} onChange={(e) => setMaster({ ...master, name: e.target.value })}/>
        </div>
        <div className="grid grid-cols-[1fr_120px_auto] gap-2">
          <select className={inputCls} value={master.productId} onChange={(e) => setMaster({ ...master, productId: e.target.value })}>
            <option value="">Pilih komoditi</option>
            {availability.map((x) => <option key={x.productId} value={x.productId}>{x.name} · loose {x.availableQty} {x.unit}</option>)}
          </select>
          <input type="number" min="0" className={inputCls} placeholder="Isi/paket" value={master.qty} onChange={(e) => setMaster({ ...master, qty: e.target.value })}/>
          <button onClick={addComponent} className="px-3 rounded-lg border border-[#3b82f6]/50 text-[#93c5fd]"><Plus size={17}/></button>
        </div>
        {selectedProduct && <div className="text-xs text-[#94a3b8]">Stok loose tersedia: {selectedProduct.availableQty} {selectedProduct.unit}</div>}
        <div className="space-y-2">
          {components.map((x) => <div key={x.productId} className="flex items-center justify-between border border-[#243044] rounded-lg px-3 py-2 text-sm">
            <span>{x.name}</span><span className="font-mono">{x.qty} {x.unit}/paket</span>
          </div>)}
        </div>
        <textarea className={inputCls} placeholder="Catatan master paket" value={master.note} onChange={(e) => setMaster({ ...master, note: e.target.value })}/>
        <button disabled={saving} onClick={createTemplate} className="btn-primary w-full py-2.5 rounded-lg font-semibold">Simpan Komposisi Paket</button>
      </section>

      <section className="card-surface p-5 space-y-3">
        <div className="font-semibold flex items-center gap-2"><Boxes size={17}/> Rakit Paket Jadi</div>
        <select className={inputCls} value={assemble.templateId} onChange={(e) => setAssemble({ ...assemble, templateId: e.target.value })}>
          <option value="">Pilih jenis paket</option>
          {templates.map((x) => <option key={x.id} value={x.id}>{x.code} · {x.name}</option>)}
        </select>
        <input type="number" min="0" className={inputCls} placeholder="Jumlah paket yang dirakit" value={assemble.qty} onChange={(e) => setAssemble({ ...assemble, qty: e.target.value })}/>
        <textarea className={inputCls} placeholder="Catatan perakitan" value={assemble.note} onChange={(e) => setAssemble({ ...assemble, note: e.target.value })}/>
        <button disabled={saving} onClick={assemblePackage} className="btn-primary w-full py-2.5 rounded-lg font-semibold">Selesai Rakit → Paket Jadi</button>
        <div className="pt-2 space-y-2">
          {packageStock.map((x) => <div key={x.id} className="border border-[#243044] rounded-xl p-3 text-sm">
            <div className="flex justify-between gap-3"><div><b>{x.code}</b> · {x.name}</div><div className="font-mono">{x.availableQty} tersedia</div></div>
            <div className="text-xs text-[#8b93a1] mt-1">Paket jadi {x.assembledQty} · dimuat/reserved {x.reservedQty}</div>
            <div className="text-xs text-[#8b93a1] mt-1">{(x.components || []).map((c) => `${c.name} ${c.qty} ${c.unit}`).join(' + ')}</div>
          </div>)}
        </div>
      </section>
    </div>

    <section className="card-surface p-5">
      <div className="font-semibold mb-4 flex items-center gap-2"><Truck size={17}/> Muat Paket Jadi</div>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
        <input type="date" className={inputCls} value={loadForm.date} onChange={(e) => setLoadForm({ ...loadForm, date: e.target.value })}/>
        <input className={inputCls} placeholder="Tujuan / penerima" value={loadForm.destination} onChange={(e) => setLoadForm({ ...loadForm, destination: e.target.value })}/>
        <input className={inputCls} placeholder="No. kendaraan" value={loadForm.vehicleNo} onChange={(e) => setLoadForm({ ...loadForm, vehicleNo: e.target.value })}/>
        <input className={inputCls} placeholder="Pengemudi" value={loadForm.driver} onChange={(e) => setLoadForm({ ...loadForm, driver: e.target.value })}/>
      </div>
      <div className="grid grid-cols-[1fr_140px_auto] gap-2 mt-2">
        <select className={inputCls} value={loadForm.templateId} onChange={(e) => setLoadForm({ ...loadForm, templateId: e.target.value })}>
          <option value="">Pilih Paket Jadi</option>
          {packageStock.filter((x) => Number(x.availableQty) > 0).map((x) => <option key={x.id} value={x.id}>{x.code} · {x.name} · tersedia {x.availableQty}</option>)}
        </select>
        <input type="number" min="0" className={inputCls} placeholder="Jumlah muat" value={loadForm.qty} onChange={(e) => setLoadForm({ ...loadForm, qty: e.target.value })}/>
        <button onClick={addLoadItem} className="px-3 rounded-lg border border-[#3b82f6]/50 text-[#93c5fd]"><Plus size={17}/></button>
      </div>
      {selectedTemplateStock && <div className="text-xs text-[#94a3b8] mt-1">Tersedia {selectedTemplateStock.availableQty} paket · reserved {selectedTemplateStock.reservedQty}</div>}
      <div className="flex flex-wrap gap-2 mt-3">{loadItems.map((x) => <span key={x.templateId} className="text-xs px-3 py-2 rounded-lg bg-[#1e293b]">{x.code} · {x.qty} paket</span>)}</div>
      <textarea className={`${inputCls} mt-2`} placeholder="Catatan pemuatan" value={loadForm.note} onChange={(e) => setLoadForm({ ...loadForm, note: e.target.value })}/>
      <button disabled={saving} onClick={createLoad} className="btn-primary mt-3 px-5 py-2.5 rounded-lg font-semibold">Muat Paket ke Kendaraan</button>
    </section>

    <section className="card-surface p-5">
      <div className="flex items-center justify-between mb-4"><div className="font-semibold">Distribusi Paket</div><button onClick={loadAll} className="text-xs inline-flex items-center gap-1 text-[#93c5fd]"><RefreshCcw size={13}/> Refresh</button></div>
      <div className="space-y-3">
        {loads.length === 0 && <div className="text-sm text-[#8b93a1]">Belum ada pemuatan paket.</div>}
        {loads.map((load) => <div key={load.id} className="border border-[#243044] rounded-xl p-4">
          <div className="flex flex-wrap justify-between gap-2"><div><b>{load.loadNo}</b> · {load.destination}<div className="text-xs text-[#8b93a1] mt-1">{load.date} · {load.vehicleNo} · {load.driver || 'Pengemudi belum diisi'}</div><div className="font-mono text-[10px] text-[#93c5fd] mt-1">SJ: {load.suratJalanNo || 'belum dibuat'} · BM: {load.bonNo || 'belum dibuat'}</div></div><span className="text-xs px-2.5 py-1 rounded-full bg-[#2563eb]/15 text-[#93c5fd]">{load.status}</span></div>
          <div className="text-xs mt-3 space-y-1">{(load.items || []).map((x) => <div key={x.templateId}>{x.packageCode} · {x.packageName}: <b>{x.loadedQty}</b> paket</div>)}</div>
          {load.status === 'SELESAI' && <div className="mt-3 pt-3 border-t border-[#243044] text-xs space-y-1">{(load.resultItems || []).map((x) => <div key={x.templateId}>{x.packageName}: <b>{x.deliveredQty}</b> disalurkan · <b>{x.returnedGoodQty}</b> retur baik · <b>{x.returnedDamagedQty}</b> retur rusak</div>)}</div>}
          <div className="flex flex-wrap gap-2 mt-3">
            <button disabled={downloading === `${load.id}-surat-jalan`} onClick={() => downloadDocument(load, 'surat-jalan')} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-[#2563eb]/50 text-[#93c5fd] text-xs font-semibold"><FileText size={13}/>{downloading === `${load.id}-surat-jalan` ? 'Menyiapkan…' : 'Surat Jalan'}</button>
            <button disabled={downloading === `${load.id}-bon-muat`} onClick={() => downloadDocument(load, 'bon-muat')} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-[#64748b]/50 text-[#cbd5e1] text-xs font-semibold"><Printer size={13}/>{downloading === `${load.id}-bon-muat` ? 'Menyiapkan…' : 'Bon Muat'}</button>
            {load.status === 'BERJALAN' && <button onClick={() => openClose(load)} className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-[#22c55e]/40 text-[#86efac] text-xs font-semibold"><CheckCircle2 size={14}/> Selesaikan & Rekonsiliasi</button>}
          </div>
        </div>)}
      </div>
    </section>

    <section className="card-surface p-5">
      <div className="font-semibold flex items-center gap-2 mb-4"><Undo2 size={17}/> Batch Paket Jadi</div>
      <div className="space-y-2 max-h-[300px] overflow-auto">{batches.filter((x) => Number(x.remainingQty) > 0).map((x) => <div key={x.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-[#1f2937] pb-2 text-xs"><div><b>{x.batchNo}</b> · {x.packageName}<div className="text-[#8b93a1]">Dirakit {x.assembledQty} · sisa {x.remainingQty}</div></div><button onClick={() => unpackBatch(x)} className="px-3 py-1.5 rounded-lg border border-[#64748b]/40 text-[#cbd5e1]">Bongkar Paket</button></div>)}</div>
    </section>

    <section className="card-surface p-5">
      <div className="font-semibold flex items-center gap-2 mb-4"><History size={17}/> History Paket</div>
      <div className="space-y-2 max-h-[420px] overflow-auto">{history.map((row) => <div key={row.id} className="border-b border-[#1f2937] pb-2 text-xs"><div className="font-medium">{row.eventType} · {row.referenceNo}</div><div className="text-[#8b93a1]">{new Date(row.time).toLocaleString('id-ID')} · {row.operator}</div></div>)}</div>
    </section>

    {closing && <div className="fixed inset-0 z-[90] bg-black/75 flex items-center justify-center p-4"><div className="card-surface w-full max-w-2xl p-6 max-h-[90vh] overflow-y-auto">
      <h2 className="font-display text-xl font-bold">Rekonsiliasi {closing.loadNo}</h2>
      <p className="text-xs text-[#8b93a1] mt-1 mb-4">Isi jumlah disalurkan dan retur rusak. Retur baik dihitung otomatis.</p>
      {(closing.items || []).map((item) => {
        const delivered = Number(closeRows[item.templateId]?.deliveredQty || 0);
        const damaged = Number(closeRows[item.templateId]?.returnedDamagedQty || 0);
        const good = Number(item.loadedQty || 0) - delivered - damaged;
        return <div key={item.templateId} className="border border-[#243044] rounded-xl p-4 mb-3">
          <div className="font-semibold text-sm">{item.packageName} · Muat {item.loadedQty} paket</div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-3">
            <input type="number" min="0" className={inputCls} placeholder="Disalurkan" value={closeRows[item.templateId]?.deliveredQty || ''} onChange={(e) => setCloseRows((p) => ({ ...p, [item.templateId]: { ...p[item.templateId], deliveredQty: e.target.value } }))}/>
            <input type="number" min="0" className={inputCls} placeholder="Retur rusak" value={closeRows[item.templateId]?.returnedDamagedQty || ''} onChange={(e) => setCloseRows((p) => ({ ...p, [item.templateId]: { ...p[item.templateId], returnedDamagedQty: e.target.value } }))}/>
            <div className="rounded-lg border border-[#243044] px-3 py-2.5 text-sm">Retur baik: <b>{good}</b></div>
          </div>
        </div>;
      })}
      <div className="flex justify-end gap-2 mt-5"><button onClick={() => setClosing(null)} className="px-4 py-2 rounded-lg border border-[#243044]">Batal</button><button onClick={closeLoad} className="btn-primary px-5 py-2 rounded-lg font-semibold">Selesaikan Distribusi</button></div>
    </div></div>}
  </div>;
};

export default BazarPaket;
