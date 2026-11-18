import React, { useEffect, useMemo, useState } from 'react';
import { FileClock, FileText, History, Link2, Plus, RefreshCcw, Truck } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError } from '../lib/api';
import { useData } from '../context/DataContext';
import SearchableProductSelect from '../components/SearchableProductSelect';
import { formatNum } from '../mock';

const inputCls = 'w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';
const today = () => new Date().toISOString().slice(0, 10);
const newItem = () => ({ productId: '', qty: '' });

const sumPlanned = (plotting) => (plotting.items || []).reduce((sum, item) => sum + Number(item.qty || 0), 0);
const sumReceived = (plotting) => (plotting.receipts || []).reduce((sum, receipt) => sum + (receipt.items || []).reduce((s, item) => s + Number(item.qty || 0), 0), 0);
const sumDoc = (plotting, type) => (plotting.documentAllocations || []).filter((row) => row.documentType === type).reduce((sum, row) => sum + Number(row.qty || 0), 0);

const MoveIn = () => {
  const { products, suppliers } = useData();
  const [plottings, setPlottings] = useState([]);
  const [legacy, setLegacy] = useState([]);
  const [query, setQuery] = useState('');
  const [legacyQuery, setLegacyQuery] = useState('');
  const [saving, setSaving] = useState(false);
  const [activeReceipt, setActiveReceipt] = useState(null);
  const [activeDocument, setActiveDocument] = useState(null);
  const [form, setForm] = useState({
    plottingDate: today(),
    scope: 'REGIONAL',
    senderType: 'GUDANG',
    senderName: '',
    items: [newItem()],
    note: '',
  });

  const load = async () => {
    const [plotRes, legacyRes] = await Promise.all([
      api.get('/move-in-plottings'),
      api.get('/move-in-legacy-references'),
    ]);
    setPlottings(plotRes.data || []);
    setLegacy(legacyRes.data || []);
  };

  useEffect(() => { load().catch((e) => toast.error(apiError(e))); }, []);

  const senderSuggestions = useMemo(() => {
    const values = new Set();
    (suppliers || []).forEach((s) => { if (s?.name) values.add(s.name); });
    (legacy || []).forEach((row) => { if (row?.supplier) values.add(row.supplier); });
    return [...values].sort((a, b) => a.localeCompare(b, 'id'));
  }, [suppliers, legacy]);

  const addItem = () => setForm((prev) => ({ ...prev, items: [...prev.items, newItem()] }));
  const setItem = (index, patch) => setForm((prev) => ({
    ...prev,
    items: prev.items.map((row, i) => i === index ? { ...row, ...patch } : row),
  }));
  const removeItem = (index) => setForm((prev) => ({
    ...prev,
    items: prev.items.length === 1 ? prev.items : prev.items.filter((_, i) => i !== index),
  }));

  const createPlotting = async () => {
    const cleanItems = form.items.filter((row) => row.productId && Number(row.qty || 0) > 0);
    if (!form.senderName.trim() || cleanItems.length === 0) return toast.error('Nama pengirim dan minimal satu komoditi wajib diisi');
    if (new Set(cleanItems.map((row) => row.productId)).size !== cleanItems.length) return toast.error('Produk yang sama tidak boleh muncul dua kali');
    setSaving(true);
    try {
      const { data } = await api.post('/move-in-plottings', {
        ...form,
        senderName: form.senderName.trim(),
        items: cleanItems.map((row) => ({ productId: row.productId, qty: Number(row.qty) })),
      });
      toast.success(`Plotting ${data.plotNo} dibuat`);
      setForm({ plottingDate: today(), scope: 'REGIONAL', senderType: 'GUDANG', senderName: '', items: [newItem()], note: '' });
      await load();
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return plottings;
    return plottings.filter((row) => [
      row.plotNo, row.plottingDate, row.scope, row.senderName, row.status,
      ...(row.items || []).flatMap((item) => [item.name, item.sku]),
      ...(row.documentAllocations || []).map((x) => x.documentNo),
    ].filter(Boolean).join(' ').toLowerCase().includes(q));
  }, [plottings, query]);

  const filteredLegacy = useMemo(() => {
    const q = legacyQuery.trim().toLowerCase();
    if (!q) return legacy.slice(0, 50);
    return legacy.filter((row) => [
      row.no, row.supplier, row.status, ...(row.items || []).flatMap((item) => [item.name, item.sku]),
    ].filter(Boolean).join(' ').toLowerCase().includes(q)).slice(0, 100);
  }, [legacy, legacyQuery]);

  const receiptTotals = (plotting) => {
    const totals = {};
    (plotting.receipts || []).forEach((rec) => (rec.items || []).forEach((item) => {
      totals[item.productId] = Number(totals[item.productId] || 0) + Number(item.qty || 0);
    }));
    return totals;
  };

  const openReceipt = (plotting) => {
    const totals = receiptTotals(plotting);
    setActiveReceipt({
      plotting,
      receiptDate: today(),
      vehicleNo: '',
      note: '',
      items: (plotting.items || []).map((item) => ({
        productId: item.productId,
        name: item.name,
        unit: item.unit,
        remaining: Math.max(Number(item.qty || 0) - Number(totals[item.productId] || 0), 0),
        qty: '',
      })),
    });
  };

  const saveReceipt = async () => {
    const rows = (activeReceipt?.items || []).filter((row) => Number(row.qty || 0) > 0);
    if (!rows.length) return toast.error('Isi jumlah fisik yang diterima');
    try {
      await api.post(`/move-in-plottings/${activeReceipt.plotting.id}/receipts`, {
        receiptDate: activeReceipt.receiptDate,
        vehicleNo: activeReceipt.vehicleNo,
        note: activeReceipt.note,
        items: rows.map((row) => ({ productId: row.productId, qty: Number(row.qty) })),
      });
      toast.success('Progres fisik plotting dicatat. Catatan ini tidak menambah stok dua kali.');
      setActiveReceipt(null);
      await load();
    } catch (e) { toast.error(apiError(e)); }
  };

  const openDocument = (plotting) => {
    const type = plotting.scope === 'REBAGGING' || plotting.scope === 'REPROSES' ? 'MO' : 'TM';
    setActiveDocument({
      plotting,
      documentType: type,
      documentNo: '',
      productId: plotting.items?.[0]?.productId || '',
      qty: '',
      note: '',
    });
  };

  const saveDocument = async () => {
    if (!activeDocument?.documentNo.trim() || !activeDocument.productId || Number(activeDocument.qty || 0) <= 0) {
      return toast.error('Nomor dokumen, produk dan kuantum wajib diisi');
    }
    try {
      await api.post(`/move-in-plottings/${activeDocument.plotting.id}/document-allocations`, {
        documentType: activeDocument.documentType,
        documentNo: activeDocument.documentNo,
        productId: activeDocument.productId,
        qty: Number(activeDocument.qty),
        note: activeDocument.note,
      });
      toast.success(`${activeDocument.documentType} berhasil ditautkan ke plotting`);
      setActiveDocument(null);
      await load();
    } catch (e) { toast.error(apiError(e)); }
  };

  return <div className="space-y-6">
    <div>
      <div className="label-mono mb-2">Pengadaan</div>
      <h1 className="font-display text-4xl font-bold">Move In / TM In</h1>
      <p className="text-sm text-[#8b93a1] mt-2 max-w-4xl">Plotting operasional berdiri sendiri dari MO/TM. MO hanya tersedia untuk Rebagging/Reproses dan dapat ditautkan belakangan. Nomor TM juga dapat menyusul, digabung ke beberapa plotting, atau satu plotting dipecah ke beberapa TM.</p>
    </div>

    <section className="card-surface p-5">
      <div className="flex items-center gap-2 mb-4"><Plus size={17} className="text-[#60a5fa]"/><div className="font-semibold">Buat Plotting Penerimaan</div></div>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3">
        <div><label className="text-xs text-[#8b93a1] block mb-1">Tanggal plotting</label><input type="date" className={inputCls} value={form.plottingDate} onChange={(e) => setForm({ ...form, plottingDate: e.target.value })}/></div>
        <div><label className="text-xs text-[#8b93a1] block mb-1">Cakupan</label><select className={inputCls} value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })}><option value="LOKAL">Lokal</option><option value="REGIONAL">Regional</option><option value="NASIONAL">Nasional</option><option value="REBAGGING">Rebagging</option><option value="REPROSES">Reproses</option></select></div>
        <div><label className="text-xs text-[#8b93a1] block mb-1">Jenis pengirim</label><select className={inputCls} value={form.senderType} onChange={(e) => setForm({ ...form, senderType: e.target.value })}><option value="GUDANG">Gudang Pengirim</option><option value="MITRA">Mitra Pengirim</option></select></div>
        <div className="xl:col-span-2"><label className="text-xs text-[#8b93a1] block mb-1">Nama Gudang / Mitra</label><input list="move-in-senders" className={inputCls} value={form.senderName} onChange={(e) => setForm({ ...form, senderName: e.target.value })} placeholder="Contoh: CV Mizan Amanah"/><datalist id="move-in-senders">{senderSuggestions.map((name) => <option key={name} value={name}/>)}</datalist></div>
      </div>

      <div className="mt-4 space-y-2">
        {(form.items || []).map((row, index) => {
          const product = products.find((p) => p.id === row.productId);
          return <div key={index} className="grid grid-cols-1 md:grid-cols-[1fr_220px_auto] gap-2">
            <SearchableProductSelect products={products} value={row.productId} onChange={(productId) => setItem(index, { productId })} placeholder="Cari komoditi..." getDescription={(p) => `${p.sku || ''} · ${p.unit || ''}`}/>
            <input type="number" min="0" step="any" className={inputCls} value={row.qty} onChange={(e) => setItem(index, { qty: e.target.value })} placeholder={product ? `Jumlah (${product.unit})` : 'Jumlah plotting'}/>
            <button type="button" onClick={() => removeItem(index)} className="px-3 py-2 rounded-lg border border-[#7f1d1d] text-[#fca5a5] disabled:opacity-30" disabled={form.items.length === 1}>Hapus</button>
          </div>;
        })}
        <button type="button" onClick={addItem} className="text-xs px-3 py-2 rounded-lg border border-[#334155] text-[#93c5fd]">+ Tambah komoditi</button>
      </div>

      <textarea rows={2} className={`${inputCls} mt-3`} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="Catatan plotting (opsional)"/>
      <button onClick={createPlotting} disabled={saving} className="btn-primary mt-3 px-5 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50">{saving ? 'Menyimpan…' : 'Buat Plotting'}</button>
    </section>

    <section className="card-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div><div className="font-semibold flex items-center gap-2"><Truck size={17}/> Plotting Aktif & Riwayat</div><div className="text-xs text-[#8b93a1] mt-1">Progres fisik di sini adalah catatan plotting. Mutasi stok tetap mengikuti proses Penerimaan yang sudah berjalan.</div></div>
        <div className="flex gap-2"><input className={inputCls} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari plotting / pengirim / TM / MO..."/><button onClick={() => load().catch(() => {})} className="px-3 rounded-lg border border-[#334155] text-[#93c5fd]"><RefreshCcw size={15}/></button></div>
      </div>
      <div className="space-y-3">
        {filtered.length === 0 ? <div className="text-sm text-[#8b93a1] py-6 text-center">Belum ada plotting Move In.</div> : filtered.map((row) => {
          const planned = sumPlanned(row);
          const received = sumReceived(row);
          const tm = sumDoc(row, 'TM');
          const mo = sumDoc(row, 'MO');
          return <div key={row.id} className="rounded-xl border border-[#243044] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="font-mono text-xs text-[#93c5fd]">{row.plotNo}</div>
                <div className="font-semibold mt-1">{row.senderName}</div>
                <div className="text-xs text-[#8b93a1] mt-1">{row.plottingDate} · {row.senderType} · {row.scope}</div>
              </div>
              <span className="text-xs px-2.5 py-1 rounded-full bg-[#2563eb]/15 text-[#93c5fd]">{row.status}</span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mt-4 text-xs">
              <div className="rounded-lg bg-[#0b0f17] p-3"><div className="text-[#6b7688]">Plotting</div><div className="font-mono font-bold mt-1">{formatNum(planned)}</div></div>
              <div className="rounded-lg bg-[#0b0f17] p-3"><div className="text-[#6b7688]">Fisik tercatat</div><div className="font-mono font-bold mt-1">{formatNum(received)}</div></div>
              <div className="rounded-lg bg-[#0b0f17] p-3"><div className="text-[#6b7688]">Sisa plotting</div><div className="font-mono font-bold mt-1 text-[#fbbf24]">{formatNum(Math.max(planned - received, 0))}</div></div>
              <div className="rounded-lg bg-[#0b0f17] p-3"><div className="text-[#6b7688]">Tertaut TM</div><div className="font-mono font-bold mt-1">{formatNum(tm)}</div></div>
              <div className="rounded-lg bg-[#0b0f17] p-3"><div className="text-[#6b7688]">{row.scope === 'REBAGGING' || row.scope === 'REPROSES' ? 'Tertaut MO' : 'MO'}</div><div className="font-mono font-bold mt-1">{row.scope === 'REBAGGING' || row.scope === 'REPROSES' ? formatNum(mo) : 'Tidak berlaku'}</div></div>
            </div>
            <div className="mt-3 text-xs space-y-1">{(row.items || []).map((item) => <div key={item.productId}><b>{item.name}</b> · {formatNum(item.qty)} {item.unit}</div>)}</div>
            {(row.documentAllocations || []).length > 0 && <div className="mt-3 flex flex-wrap gap-2">{row.documentAllocations.map((doc) => <span key={doc.id} className="text-[11px] px-2 py-1 rounded-lg border border-[#334155]"><b>{doc.documentType}</b> {doc.documentNo} · {formatNum(doc.qty)}</span>)}</div>}
            <div className="flex flex-wrap gap-2 mt-4">
              <button onClick={() => openReceipt(row)} disabled={received >= planned - 1e-9} className="text-xs px-3 py-2 rounded-lg border border-[#2563eb] text-[#93c5fd] disabled:opacity-40"><Truck size={13} className="inline mr-1"/>Catat Progres Fisik</button>
              <button onClick={() => openDocument(row)} disabled={received <= 0} className="text-xs px-3 py-2 rounded-lg border border-[#334155] text-[#cbd5e1] disabled:opacity-40"><Link2 size={13} className="inline mr-1"/>Tautkan MO/TM</button>
            </div>
          </div>;
        })}
      </div>
    </section>

    <section className="card-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4"><div><div className="font-semibold flex items-center gap-2"><History size={17}/> Referensi PO/TM Lama</div><div className="text-xs text-[#8b93a1] mt-1">Data lama seperti Gudang Lamajakka dan CV Mizan Amanah tetap utuh. Bagian ini hanya membantu pencarian histori.</div></div><input className={inputCls} value={legacyQuery} onChange={(e) => setLegacyQuery(e.target.value)} placeholder="Cari Gudang Lamajakka, Mizan, nomor TM..."/></div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[850px] text-sm">
          <thead><tr className="text-left border-b border-[#1a222e] text-xs text-[#8b93a1]"><th className="py-2 pr-3">Nomor</th><th className="py-2 pr-3">Pengirim</th><th className="py-2 pr-3">Tanggal</th><th className="py-2 pr-3">Komoditi</th><th className="py-2 pr-3">Status</th></tr></thead>
          <tbody>{filteredLegacy.map((row) => <tr key={row.id} className="border-b border-[#131a24]"><td className="py-3 pr-3 font-mono text-xs">{row.no}</td><td className="py-3 pr-3">{row.supplier}</td><td className="py-3 pr-3 text-xs text-[#8b93a1]">{String(row.date || '').slice(0,10)}</td><td className="py-3 pr-3 text-xs">{(row.items || []).map((item) => <div key={item.productId || item.sku}>{item.name} · {formatNum(item.receivedQty || 0)}/{formatNum(item.qty || 0)} {item.unit}</div>)}</td><td className="py-3 pr-3">{row.status}</td></tr>)}</tbody>
        </table>
      </div>
    </section>

    {activeReceipt && <div className="fixed inset-0 z-[100] bg-black/75 flex items-center justify-center p-4"><div className="card-surface w-full max-w-2xl p-6">
      <h2 className="font-display text-xl font-bold">Catat Progres Fisik</h2>
      <p className="text-xs text-[#8b93a1] mt-1 mb-4">{activeReceipt.plotting.plotNo} · {activeReceipt.plotting.senderName}. Catatan ini untuk tracking plotting dan tidak melakukan mutasi stok.</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2"><input type="date" className={inputCls} value={activeReceipt.receiptDate} onChange={(e) => setActiveReceipt({ ...activeReceipt, receiptDate: e.target.value })}/><input className={inputCls} value={activeReceipt.vehicleNo} onChange={(e) => setActiveReceipt({ ...activeReceipt, vehicleNo: e.target.value.toUpperCase() })} placeholder="Nomor polisi / kendaraan (opsional)"/></div>
      <div className="space-y-2 mt-3">{activeReceipt.items.map((row, index) => <div key={row.productId} className="grid grid-cols-[1fr_180px] gap-2 items-center"><div className="text-sm"><div className="font-medium">{row.name}</div><div className="text-xs text-[#8b93a1]">Sisa plotting {formatNum(row.remaining)} {row.unit}</div></div><input type="number" min="0" max={row.remaining} className={inputCls} value={row.qty} onChange={(e) => setActiveReceipt({ ...activeReceipt, items: activeReceipt.items.map((x, i) => i === index ? { ...x, qty: e.target.value } : x) })} placeholder={row.unit}/></div>)}</div>
      <textarea className={`${inputCls} mt-3`} rows={2} value={activeReceipt.note} onChange={(e) => setActiveReceipt({ ...activeReceipt, note: e.target.value })} placeholder="Catatan bongkar / surat jalan bila ada"/>
      <div className="flex justify-end gap-2 mt-5"><button onClick={() => setActiveReceipt(null)} className="px-4 py-2 rounded-lg border border-[#334155]">Batal</button><button onClick={saveReceipt} className="btn-primary px-5 py-2 rounded-lg">Simpan Progres</button></div>
    </div></div>}

    {activeDocument && <div className="fixed inset-0 z-[100] bg-black/75 flex items-center justify-center p-4"><div className="card-surface w-full max-w-xl p-6">
      <h2 className="font-display text-xl font-bold">Tautkan Dokumen</h2>
      <p className="text-xs text-[#8b93a1] mt-1 mb-4">{activeDocument.plotting.plotNo} · Dokumen hanya menyelesaikan administrasi, tidak mengubah stok.</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <select className={inputCls} value={activeDocument.documentType} onChange={(e) => setActiveDocument({ ...activeDocument, documentType: e.target.value })}>
          <option value="TM">TM</option>
          {(activeDocument.plotting.scope === 'REBAGGING' || activeDocument.plotting.scope === 'REPROSES') && <option value="MO">MO</option>}
        </select>
        <input className={inputCls} value={activeDocument.documentNo} onChange={(e) => setActiveDocument({ ...activeDocument, documentNo: e.target.value.toUpperCase() })} placeholder={activeDocument.documentType === 'MO' ? 'Nomor MO' : 'Nomor TM'}/>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2"><select className={inputCls} value={activeDocument.productId} onChange={(e) => setActiveDocument({ ...activeDocument, productId: e.target.value })}>{(activeDocument.plotting.items || []).map((item) => <option key={item.productId} value={item.productId}>{item.name}</option>)}</select><input type="number" min="0" className={inputCls} value={activeDocument.qty} onChange={(e) => setActiveDocument({ ...activeDocument, qty: e.target.value })} placeholder="Kuantum dokumen"/></div>
      <textarea className={`${inputCls} mt-2`} rows={2} value={activeDocument.note} onChange={(e) => setActiveDocument({ ...activeDocument, note: e.target.value })} placeholder="Catatan (opsional)"/>
      <div className="flex justify-end gap-2 mt-5"><button onClick={() => setActiveDocument(null)} className="px-4 py-2 rounded-lg border border-[#334155]">Batal</button><button onClick={saveDocument} className="btn-primary px-5 py-2 rounded-lg">Tautkan Dokumen</button></div>
    </div></div>}
  </div>;
};

export default MoveIn;
