import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileDown, History, Link2, Plus, RefreshCcw, Truck } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError, downloadApiFile } from '../lib/api';
import { useData } from '../context/DataContext';
import SearchableProductSelect from '../components/SearchableProductSelect';
import { formatNum } from '../mock';

const inputCls = 'w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';
const today = () => new Date().toISOString().slice(0, 10);
const newItem = () => ({ productId: '', qty: '' });

const sumPlanned = (plotting) => (plotting.items || []).reduce((sum, item) => sum + Number(item.qty || 0), 0);
const sumReceived = (plotting) => (plotting.items || []).reduce((sum, item) => sum + Number(item.receivedQty || 0), 0);
const sumDoc = (plotting, type) => (plotting.documentAllocations || []).filter((row) => row.documentType === type).reduce((sum, row) => sum + Number(row.qty || 0), 0);

const MoveIn = () => {
  const { products, suppliers, refreshPurchaseOrders } = useData();
  const navigate = useNavigate();
  const [plottings, setPlottings] = useState([]);
  const [legacy, setLegacy] = useState([]);
  const [query, setQuery] = useState('');
  const [legacyQuery, setLegacyQuery] = useState('');
  const [saving, setSaving] = useState(false);
  const [downloadingId, setDownloadingId] = useState('');
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
      await refreshPurchaseOrders();
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

  const openInbound = async (plotting) => {
    if (!plotting.poId) return toast.error('Induk penerimaan plotting belum tersedia');
    try {
      await refreshPurchaseOrders();
      navigate(`/catat?mode=masuk&poId=${encodeURIComponent(plotting.poId)}`);
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  const downloadRecap = async (plotting) => {
    if (!plotting?.poId || downloadingId) return;
    setDownloadingId(plotting.id);
    try {
      const safeNo = String(plotting.plotNo || 'MOVE-IN').replace(/[^a-zA-Z0-9_-]+/g, '-');
      await downloadApiFile(`/export/purchase-order/${plotting.poId}/receiving-recap.pdf`, `rekap_move_in_${safeNo}.pdf`);
      toast.success(`Rekap penerimaan ${plotting.plotNo} berhasil diunduh`);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setDownloadingId('');
    }
  };
  const openDocument = (plotting) => {
    const processScope = plotting.scope === 'REBAGGING' || plotting.scope === 'REPROSES';
    const docs = plotting.documentAllocations || [];
    const hasMo = docs.some((x) => x.documentType === 'MO');
    const hasTm = docs.some((x) => x.documentType === 'TM');
    const type = processScope ? (hasMo && !hasTm ? 'TM' : 'MO') : 'TM';
    setActiveDocument({
      plotting,
      documentType: type,
      documentNo: '',
      documentDate: today(),
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
        documentDate: activeDocument.documentDate,
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
      <p className="text-sm text-[#8b93a1] mt-2 max-w-4xl">Plotting menjadi induk penerimaan seperti PO. Kendaraan, bongkar, biaya bongkar, baik/rusak, dan tumpukan tujuan memakai proses Penerimaan yang sudah berjalan. Khusus Rebagging/Reproses berlaku pasangan dokumen 1 MO = 1 TM; keduanya dapat menyusul tanpa menambah stok dua kali.</p>
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
        <div><div className="font-semibold flex items-center gap-2"><Truck size={17}/> Plotting Aktif & Riwayat</div><div className="text-xs text-[#8b93a1] mt-1">Klik Tambah Kendaraan untuk memakai alur penerimaan yang sama dengan PO: pilih tumpukan, mulai/selesai bongkar, baik/rusak, lembur, dan biaya bongkar.</div></div>
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
            <div className="mt-3 text-xs space-y-1">{(row.items || []).map((item) => <div key={item.productId}><b>{item.name}</b> · plotting {formatNum(item.qty)} {item.unit} · diterima {formatNum(item.receivedQty || 0)} {item.unit}</div>)}</div>
            {(row.inboundLoads || []).length > 0 && <div className="mt-3 rounded-lg border border-[#243044] bg-[#0b0f17] p-3 text-xs">
              <div className="font-semibold mb-2">Realisasi Penerimaan</div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                <div><span className="text-[#6b7688]">Kendaraan</span><div className="font-mono mt-1">{(row.inboundLoads || []).filter((x) => x.status === 'Selesai').length} selesai</div></div>
                <div><span className="text-[#6b7688]">Tumpukan tujuan</span><div className="font-mono mt-1">{(row.completedStacks || []).join(', ') || 'Belum ada'}</div></div>
                <div><span className="text-[#6b7688]">Biaya bongkar tercatat</span><div className="font-mono mt-1">Rp {formatNum(row.unloadingCostTotal || 0)}</div></div>
              </div>
              <div className="mt-2 space-y-2">{(row.inboundLoads || []).slice(0, 12).map((load) => {
  const plan = (load.items || []).reduce((s, x) => s + Number(x.qty || 0), 0);
  const actual = (load.actualItems || []).reduce((s, x) => s + Number(x.documentActualQty ?? x.actualQty ?? 0), 0);
  const variance = actual - plan;
  const actualRows = load.actualItems || [];
  const stacks = actualRows.map((x) => x.stackCode).filter(Boolean);
  const expiries = actualRows.map((x) => x.exp).filter(Boolean);
  const varianceLabel = variance < 0 ? `Kurang ${formatNum(Math.abs(variance))}` : variance > 0 ? `Lebih ${formatNum(variance)}` : "Sesuai";
  return <div key={load.id} className="rounded-lg border border-[#1f2937] px-3 py-2">
    <div className="flex flex-wrap gap-x-2 gap-y-1 text-[#8b93a1]">
      <span className="font-mono text-[#cbd5e1]">{load.loadNo}</span><span>{load.polisi || "—"}</span><span>{load.status}</span>
      {load.status === "Selesai" && <><span>Rencana {formatNum(plan)}</span><span>Aktual {formatNum(actual)}</span><span className={variance < 0 ? "text-[#fbbf24]" : variance > 0 ? "text-[#93c5fd]" : "text-[#86efac]"}>{varianceLabel}</span></>}
    </div>
    {load.status === "Selesai" && <div className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-[#6b7688]"><span>Tumpukan: {stacks.join(", ") || "—"}</span><span>Expired: {expiries.join(", ") || "—"}</span><span>Biaya bongkar: Rp {formatNum(load.unloadingCost?.chargeable || 0)}</span>{actualRows.some((x) => x.discrepancyReason) && <span>Alasan: {actualRows.map((x) => x.discrepancyReason).filter(Boolean).join("; ")}</span>}</div>}
  </div>;
})}</div>
            </div>}
            {(row.documentAllocations || []).length > 0 && <div className="mt-3 flex flex-wrap gap-2">{row.documentAllocations.map((doc) => <span key={doc.id} className="text-[11px] px-2 py-1 rounded-lg border border-[#334155]"><b>{doc.documentType}</b> {doc.documentNo}{doc.documentDate ? ` · ${doc.documentDate}` : ""} · {formatNum(doc.qty)}</span>)}</div>}
            <div className="flex flex-wrap gap-2 mt-4">
              <button onClick={() => openInbound(row)} disabled={received >= planned - 1e-9} className="text-xs px-3 py-2 rounded-lg border border-[#2563eb] text-[#93c5fd] disabled:opacity-40"><Truck size={13} className="inline mr-1"/>Tambah Kendaraan / Proses Penerimaan</button>
              <button onClick={() => openDocument(row)} className="text-xs px-3 py-2 rounded-lg border border-[#334155] text-[#cbd5e1]"><Link2 size={13} className="inline mr-1"/>Tautkan MO/TM</button>
              {received > 0 && <button onClick={() => downloadRecap(row)} disabled={downloadingId === row.id} className="text-xs px-3 py-2 rounded-lg border border-[#22c55e]/60 text-[#4ade80] disabled:opacity-40"><FileDown size={13} className="inline mr-1"/>{downloadingId === row.id ? "Menyiapkan…" : "Rekap Penerimaan PDF"}</button>}
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

    {activeDocument && <div className="fixed inset-0 z-[100] bg-black/75 flex items-center justify-center p-4"><div className="card-surface w-full max-w-xl p-6">
      <h2 className="font-display text-xl font-bold">Tautkan Dokumen</h2>
      <p className="text-xs text-[#8b93a1] mt-1 mb-4">{activeDocument.plotting.plotNo} · Tulis nomor persis seperti dokumen resmi. Khusus Rebagging/Reproses berlaku <b>1 MO = 1 TM</b>; sistem akan menolak bila satu MO dicoba dipasangkan ke TM berbeda atau sebaliknya. Penautan dokumen tidak mengubah stok, tumpukan, maupun biaya bongkar.</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <select className={inputCls} value={activeDocument.documentType} onChange={(e) => setActiveDocument({ ...activeDocument, documentType: e.target.value })}>
          <option value="TM">TM</option>
          {(activeDocument.plotting.scope === 'REBAGGING' || activeDocument.plotting.scope === 'REPROSES') && <option value="MO">MO</option>}
        </select>
        <input className={inputCls} value={activeDocument.documentNo} onChange={(e) => setActiveDocument({ ...activeDocument, documentNo: e.target.value.toUpperCase() })} placeholder={activeDocument.documentType === 'MO' ? 'Nomor MO' : 'Nomor TM'}/>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2"><input type="date" className={inputCls} value={activeDocument.documentDate || ""} onChange={(e) => setActiveDocument({ ...activeDocument, documentDate: e.target.value })}/><div className="rounded-lg border border-[#334155] px-3 py-2 text-xs text-[#8b93a1] flex items-center">Tanggal dokumen resmi</div></div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2"><select className={inputCls} value={activeDocument.productId} onChange={(e) => setActiveDocument({ ...activeDocument, productId: e.target.value })}>{(activeDocument.plotting.items || []).map((item) => <option key={item.productId} value={item.productId}>{item.name}</option>)}</select><input type="number" min="0" className={inputCls} value={activeDocument.qty} onChange={(e) => setActiveDocument({ ...activeDocument, qty: e.target.value })} placeholder="Kuantum dokumen"/></div>
      <textarea className={`${inputCls} mt-2`} rows={2} value={activeDocument.note} onChange={(e) => setActiveDocument({ ...activeDocument, note: e.target.value })} placeholder="Catatan (opsional)"/>
      <div className="flex justify-end gap-2 mt-5"><button onClick={() => setActiveDocument(null)} className="px-4 py-2 rounded-lg border border-[#334155]">Batal</button><button onClick={saveDocument} className="btn-primary px-5 py-2 rounded-lg">Tautkan Dokumen</button></div>
    </div></div>}
  </div>;
};

export default MoveIn;
