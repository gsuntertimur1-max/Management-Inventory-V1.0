import React, { useEffect, useMemo, useState } from 'react';
import { ClipboardList, FileText, Plus, RefreshCcw, Send } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import api, { apiError } from '../lib/api';
import { useData } from '../context/DataContext';
import SearchableProductSelect from '../components/SearchableProductSelect';
import { formatNum } from '../mock';
import { packagingText, quantityFromInput, quantityIsValid, totalWeight } from '../lib/packaging';

const inputCls = 'w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';
const today = () => new Date().toISOString().slice(0, 10);
const newItem = () => ({ productId: '', inputMode: 'WEIGHT', inputValue: '', orderedQty: 0 });

const statusLabel = (status) => ({
  BELUM_DIAMBIL: 'Belum Diambil',
  SEBAGIAN: 'Sebagian',
  SELESAI: 'Selesai',
}[status] || status || 'Belum Diambil');

const DokumenPengeluaran = () => {
  const navigate = useNavigate();
  const { products } = useData();
  const [documents, setDocuments] = useState([]);
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('SEMUA');
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    documentType: 'SO',
    documentNo: '',
    documentDate: today(),
    party: '',
    transferScope: '',
    processMoNo: '',
    note: '',
    items: [newItem()],
  });

  const load = async () => {
    const { data } = await api.get('/outbound-document-masters');
    setDocuments(data || []);
  };

  useEffect(() => { load().catch((e) => toast.error(apiError(e))); }, []);

  const setItem = (index, patch) => setForm((prev) => ({
    ...prev,
    items: prev.items.map((row, i) => i === index ? { ...row, ...patch } : row),
  }));

  const addItem = () => setForm((prev) => ({ ...prev, items: [...prev.items, newItem()] }));
  const removeItem = (index) => setForm((prev) => ({
    ...prev,
    items: prev.items.length === 1 ? prev.items : prev.items.filter((_, i) => i !== index),
  }));

  const updateInput = (index, inputValue, inputMode) => {
    const row = form.items[index];
    const product = products.find((p) => p.id === row.productId);
    const mode = inputMode || row.inputMode;
    const qty = quantityFromInput(inputValue, mode, product);
    setItem(index, { inputValue, inputMode: mode, orderedQty: qty });
  };

  const createDocument = async () => {
    const cleanItems = form.items.filter((row) => row.productId && Number(row.orderedQty || 0) > 0);
    if (!form.documentNo.trim()) return toast.error('Nomor dokumen wajib diisi');
    if (!form.party.trim()) return toast.error('Penerima/Tujuan wajib diisi');
    if (!cleanItems.length) return toast.error('Minimal satu komoditi wajib diisi');
    if (new Set(cleanItems.map((x) => x.productId)).size !== cleanItems.length) return toast.error('Produk yang sama tidak boleh muncul dua kali');
    for (const row of cleanItems) {
      const product = products.find((p) => p.id === row.productId);
      if (!quantityIsValid(row.orderedQty, product)) return toast.error(`Kuantum ${product?.name || 'produk'} tidak valid terhadap kemasan master`);
    }
    if (form.documentType === 'TM' && !form.transferScope) return toast.error('Pilih cakupan TM');
    if (form.documentType === 'TM' && ['REBAGGING', 'REPROSES'].includes(form.transferScope) && !form.processMoNo.trim()) return toast.error('Nomor MO wajib diisi untuk TM Rebagging/Reproses');

    setSaving(true);
    try {
      const payload = {
        ...form,
        documentNo: form.documentNo.trim().toUpperCase(),
        party: form.party.trim(),
        processMoNo: form.processMoNo.trim().toUpperCase(),
        items: cleanItems.map((row) => ({
          productId: row.productId,
          orderedQty: Number(row.orderedQty),
          inputMode: row.inputMode,
          inputValue: Number(row.inputValue),
        })),
      };
      const { data } = await api.post('/outbound-document-masters', payload);
      toast.success(`${data.documentType} ${data.documentNo} terdaftar sebagai outstanding pengeluaran`);
      setForm({
        documentType: 'SO', documentNo: '', documentDate: today(), party: '',
        transferScope: '', processMoNo: '', note: '', items: [newItem()],
      });
      await load();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return documents.filter((doc) => {
      if (typeFilter !== 'SEMUA' && doc.documentType !== typeFilter) return false;
      if (!q) return true;
      return [
        doc.documentNo, doc.documentType, doc.party, doc.status, doc.transferScope, doc.processMoNo,
        ...(doc.items || []).flatMap((item) => [item.name, item.sku]),
      ].filter(Boolean).join(' ').toLowerCase().includes(q);
    });
  }, [documents, query, typeFilter]);

  const processDocument = (doc) => {
    const params = new URLSearchParams({
      mode: 'keluar',
      documentNo: doc.documentNo,
      documentType: doc.documentType,
    });
    navigate(`/catat?${params.toString()}`);
  };

  return <div className="space-y-6">
    <div>
      <div className="label-mono mb-2">Operasional</div>
      <h1 className="font-display text-4xl font-bold">Dokumen Pengeluaran</h1>
      <p className="text-sm text-[#8b93a1] mt-2 max-w-4xl">Daftarkan SO, TM Out, CT, ND, atau Memo sebelum kendaraan dibuat. Dokumen ini membentuk outstanding administratif saja; stok baru terreservasi saat kendaraan/pemuatan dijadwalkan.</p>
    </div>

    <section className="card-surface p-5">
      <div className="flex items-center gap-2 mb-4"><Plus size={17} className="text-[#60a5fa]"/><div className="font-semibold">Daftarkan Dokumen Induk</div></div>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3">
        <div><label className="text-xs text-[#8b93a1] block mb-1">Jenis dokumen</label><select className={inputCls} value={form.documentType} onChange={(e) => setForm({ ...form, documentType: e.target.value, transferScope: e.target.value === 'TM' ? form.transferScope : '', processMoNo: e.target.value === 'TM' ? form.processMoNo : '' })}><option value="SO">SO</option><option value="TM">TM Out</option><option value="CT">CT</option><option value="ND">ND</option><option value="MEMO">Memo</option></select></div>
        <div><label className="text-xs text-[#8b93a1] block mb-1">Tanggal dokumen</label><input type="date" className={inputCls} value={form.documentDate} onChange={(e) => setForm({ ...form, documentDate: e.target.value })}/></div>
        <div className="xl:col-span-2"><label className="text-xs text-[#8b93a1] block mb-1">Nomor dokumen</label><input className={inputCls} value={form.documentNo} onChange={(e) => setForm({ ...form, documentNo: e.target.value.toUpperCase() })} placeholder={form.documentType === 'SO' ? 'SO/...' : form.documentType === 'MEMO' ? 'MEMO...' : `${form.documentType}...`}/></div>
        <div><label className="text-xs text-[#8b93a1] block mb-1">Penerima / Tujuan</label><input className={inputCls} value={form.party} onChange={(e) => setForm({ ...form, party: e.target.value })} placeholder="Nama penerima/tujuan"/></div>
      </div>

      {form.documentType === 'TM' && <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
        <div><label className="text-xs text-[#8b93a1] block mb-1">Cakupan TM</label><select className={inputCls} value={form.transferScope} onChange={(e) => setForm({ ...form, transferScope: e.target.value, processMoNo: ['REBAGGING','REPROSES'].includes(e.target.value) ? form.processMoNo : '' })}><option value="">Pilih...</option><option value="LOKAL">Lokal</option><option value="REGIONAL">Regional</option><option value="NASIONAL">Nasional</option><option value="REBAGGING">Rebagging</option><option value="REPROSES">Reproses</option></select></div>
        {['REBAGGING','REPROSES'].includes(form.transferScope) && <div><label className="text-xs text-[#8b93a1] block mb-1">Nomor MO</label><input className={inputCls} value={form.processMoNo} onChange={(e) => setForm({ ...form, processMoNo: e.target.value.toUpperCase() })} placeholder="MO/..."/></div>}
      </div>}

      <div className="mt-4 space-y-3">
        {form.items.map((row, index) => {
          const product = products.find((p) => p.id === row.productId);
          const convertedWeight = totalWeight(row.orderedQty, product);
          return <div key={index} className="rounded-xl border border-[#243044] p-3">
            <div className="grid grid-cols-1 md:grid-cols-[1fr_150px_220px_auto] gap-2">
              <SearchableProductSelect products={products} value={row.productId} onChange={(productId) => {
                const selected = products.find((p) => p.id === productId);
                const mode = Number(selected?.weight || 0) > 0 ? 'WEIGHT' : 'QTY';
                setItem(index, { productId, inputMode: mode, inputValue: '', orderedQty: 0 });
              }} placeholder="Cari komoditi..." getDescription={(p) => `${p.sku || ''} · ${p.unit || ''}`}/>
              <select className={inputCls} value={row.inputMode} onChange={(e) => updateInput(index, row.inputValue, e.target.value)}><option value="QTY">Pack/Pcs</option><option value="WEIGHT">Kg/Liter</option></select>
              <input type="number" min="0" step="any" className={inputCls} value={row.inputValue} onChange={(e) => updateInput(index, e.target.value, row.inputMode)} placeholder={row.inputMode === 'WEIGHT' ? 'Kuantum kg/liter' : `Kuantum ${product?.unit || 'unit'}`}/>
              <button type="button" onClick={() => removeItem(index)} disabled={form.items.length === 1} className="px-3 py-2 rounded-lg border border-[#7f1d1d] text-[#fca5a5] disabled:opacity-30">Hapus</button>
            </div>
            {product && Number(row.orderedQty || 0) > 0 && <div className="mt-2 text-[11px] text-[#8b93a1] flex flex-wrap gap-x-4 gap-y-1">
              <span>Disimpan: <b className="text-[#cbd5e1]">{formatNum(row.orderedQty)} {product.unit}</b></span>
              <span>Kg/Liter master: <b className="text-[#cbd5e1]">{formatNum(convertedWeight)}</b></span>
              {packagingText(row.orderedQty, product, formatNum) && <span>{packagingText(row.orderedQty, product, formatNum)}</span>}
            </div>}
          </div>;
        })}
        <button type="button" onClick={addItem} className="text-xs px-3 py-2 rounded-lg border border-[#334155] text-[#93c5fd]">+ Tambah komoditi</button>
      </div>

      <textarea rows={2} className={`${inputCls} mt-3`} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="Catatan dokumen (opsional)"/>
      <button onClick={createDocument} disabled={saving} className="btn-primary mt-3 px-5 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50">{saving ? 'Menyimpan…' : 'Simpan Dokumen Outstanding'}</button>
    </section>

    <section className="card-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div><div className="font-semibold flex items-center gap-2"><ClipboardList size={17}/> Outstanding Dokumen</div><div className="text-xs text-[#8b93a1] mt-1">Selesai = kendaraan yang sudah selesai dimuat. Reservasi = kendaraan Menunggu/Sedang Dimuat. Sisa tersedia = kuantum dokumen yang masih dapat dijadwalkan.</div></div>
        <div className="flex flex-wrap gap-2">
          <select className={inputCls} value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}><option value="SEMUA">Semua</option><option value="SO">SO</option><option value="TM">TM Out</option><option value="CT">CT</option><option value="ND">ND</option><option value="MEMO">Memo</option></select>
          <input className={inputCls} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari nomor / penerima / produk..."/>
          <button onClick={() => load().catch((e) => toast.error(apiError(e)))} className="px-3 rounded-lg border border-[#334155] text-[#93c5fd]"><RefreshCcw size={15}/></button>
        </div>
      </div>

      <div className="space-y-3">
        {filtered.length === 0 ? <div className="py-8 text-center text-sm text-[#8b93a1]">Belum ada dokumen pengeluaran.</div> : filtered.map((doc) => <div key={doc.id || `${doc.documentType}-${doc.documentNo}`} className="rounded-xl border border-[#243044] p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2"><FileText size={15} className="text-[#60a5fa]"/><span className="font-mono text-xs text-[#93c5fd]">{doc.documentType} · {doc.documentNo}</span></div>
              <div className="font-semibold mt-1">{doc.party || '—'}</div>
              <div className="text-xs text-[#8b93a1] mt-1">{doc.documentDate || 'Tanggal belum dicatat'}{doc.documentType === 'TM' && doc.transferScope ? ` · ${doc.transferScope}` : ''}{doc.processMoNo ? ` · MO ${doc.processMoNo}` : ''}</div>
            </div>
            <span className="text-xs px-2.5 py-1 rounded-full bg-[#2563eb]/15 text-[#93c5fd]">{statusLabel(doc.status)}</span>
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[760px] text-xs">
              <thead><tr className="text-left text-[#6b7688] border-b border-[#1a222e]"><th className="py-2">Komoditi</th><th className="py-2 text-right">Dokumen</th><th className="py-2 text-right">Selesai</th><th className="py-2 text-right">Reservasi</th><th className="py-2 text-right">Sisa Tersedia</th></tr></thead>
              <tbody>{(doc.items || []).map((item) => {
                const product = products.find((p) => p.id === item.productId);
                return <tr key={item.productId} className="border-b border-[#131a24]"><td className="py-2"><div className="font-medium">{item.name}</div><div className="text-[10px] text-[#6b7688]">{item.sku}</div></td><td className="py-2 text-right font-mono">{formatNum(item.orderedQty)} {item.unit}<div className="text-[10px] text-[#6b7688]">{formatNum(totalWeight(item.orderedQty, product))} kg/liter</div></td><td className="py-2 text-right font-mono">{formatNum(item.completedQty || 0)} {item.unit}</td><td className="py-2 text-right font-mono">{formatNum(item.reservedQty || 0)} {item.unit}</td><td className="py-2 text-right font-mono font-bold text-[#fbbf24]">{formatNum(item.remainingQty || 0)} {item.unit}</td></tr>;
              })}</tbody>
            </table>
          </div>
          <div className="flex justify-end mt-4"><button onClick={() => processDocument(doc)} disabled={doc.status === 'SELESAI'} className="btn-primary px-4 py-2 rounded-lg text-xs font-semibold disabled:opacity-40"><Send size={13} className="inline mr-1"/>Proses Pengeluaran</button></div>
        </div>)}
      </div>
    </section>
  </div>;
};

export default DokumenPengeluaran;
