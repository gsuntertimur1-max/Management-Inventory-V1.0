import React, { useEffect, useMemo, useState } from 'react';
import { ArrowDownToLine, BadgeCheck, FileCheck2, FilePlus2, RefreshCcw, RotateCcw, Warehouse } from 'lucide-react';
import api, { apiError } from '../lib/api';
import { toast } from 'sonner';
import { useData } from '../context/DataContext';
import SearchableProductSelect from '../components/SearchableProductSelect';
import { consignmentStackCodes } from '../lib/consignmentLocations';

const inputCls = 'w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';
const today = () => new Date().toISOString().slice(0, 10);

const statusLabel = (status) => ({
  ND_TERDAFTAR: 'ND Terdaftar', DITERIMA_SEBAGIAN: 'Diterima Sebagian', DITERIMA: 'Menunggu Rekonsiliasi',
  ADA_RETUR: 'Ada Retur', DIREALISASIKAN_SEBAGIAN: 'Direalisasikan Sebagian', SO_TERBIT_SEBAGIAN: 'SO Terbit Sebagian', SELESAI: 'Selesai', DIBATALKAN: 'Dibatalkan',
}[status] || status);

const BazarNDExternal = () => {
  const { products, refreshConsignmentFlow } = useData();
  const [documents, setDocuments] = useState([]);
  const [bazarTrips, setBazarTrips] = useState([]);
  const [packageLoads, setPackageLoads] = useState([]);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ ndNo: '', ndDate: today(), originWarehouse: '', activityType: 'BAZAR', note: '' });
  const [draft, setDraft] = useState({ productId: '', qty: '' });
  const [items, setItems] = useState([]);
  const [action, setAction] = useState(null);
  const [actionRows, setActionRows] = useState({});
  const [actionMeta, setActionMeta] = useState({ date: today(), vehicleNo: '', soNo: '', activityType: 'BAZAR', note: '' });

  const load = async () => {
    const [nd, trips, packages] = await Promise.all([
      api.get('/bazar/external-nds'),
      api.get('/bazar/trips'),
      api.get('/bazar/package-loads'),
    ]);
    setDocuments(nd.data);
    setBazarTrips(trips.data);
    setPackageLoads(packages.data);
  };
  useEffect(() => { load().catch(() => {}); }, []);

  const activeProducts = useMemo(() => (products || []).filter((row) => row.active !== false), [products]);

  const addItem = () => {
    const product = activeProducts.find((row) => row.id === draft.productId);
    const qty = Number(draft.qty || 0);
    if (!product || qty <= 0) return toast.error('Pilih produk dan isi kuantum ND');
    setItems((prev) => {
      const found = prev.find((row) => row.productId === product.id);
      if (found) return prev.map((row) => row.productId === product.id ? { ...row, qty: Number(row.qty) + qty } : row);
      return [...prev, { productId: product.id, name: product.name, unit: product.unit, qty }];
    });
    setDraft({ productId: '', qty: '' });
  };

  const createDocument = async () => {
    if (!form.ndNo.trim() || !form.originWarehouse.trim() || !form.ndDate || !items.length) return toast.error('Nomor ND, tanggal, gudang asal, dan komoditi wajib diisi');
    setSaving(true);
    try {
      await api.post('/bazar/external-nds', { ...form, items: items.map(({ productId, qty }) => ({ productId, qty: Number(qty) })) });
      toast.success('ND gudang lain berhasil diregister');
      setForm({ ndNo: '', ndDate: today(), originWarehouse: '', activityType: 'BAZAR', note: '' });
      setItems([]); await load();
    } catch (error) { toast.error(apiError(error)); } finally { setSaving(false); }
  };

  const openAction = (type, document) => {
    const rows = {};
    const defaultStack = consignmentStackCodes('Gudang Bazar')[0] || '18/A01-BAZAR';
    (document.summaryItems || []).forEach((row) => {
      rows[row.productId] = { goodQty: '', damagedQty: '', qty: '', stackCode: defaultStack };
    });
    const realizationType = document.activityType === 'PAKET' ? 'PAKET' : 'BAZAR';
    setActionRows(rows); setAction({ type, document });
    setActionMeta({ date: today(), vehicleNo: '', soNo: '', activityType: realizationType, note: '' });
  };

  const realizationReferences = useMemo(() => {
    if (!action || action.type !== 'realize') return [];
    if (actionMeta.activityType === 'PAKET') {
      return (packageLoads || []).filter((row) => row.status === 'SELESAI').map((row) => ({
        value: row.loadNo,
        label: `${row.loadNo} · ${row.destination || 'Paket'}`,
      }));
    }
    return (bazarTrips || []).filter((row) => row.status === 'SELESAI').map((row) => ({
      value: row.tripNo,
      label: `${row.tripNo} · ${row.location || 'Bazar'}`,
    }));
  }, [action, actionMeta.activityType, bazarTrips, packageLoads]);

  const cancelDocument = async (document) => {
    const note = window.prompt('Alasan pembatalan ND:', '') ?? '';
    if (!note.trim()) return;
    try {
      await api.post(`/bazar/external-nds/${document.id}/cancel`, { note: note.trim() });
      toast.success('ND dibatalkan');
      await load();
    } catch (error) { toast.error(apiError(error)); }
  };

  const submitAction = async () => {
    const { type, document } = action;
    let path = '';
    let payload = {};
    if (type === 'receive') {
      path = 'receipts';
      payload = {
        receiptDate: actionMeta.date, vehicleNo: actionMeta.vehicleNo, note: actionMeta.note,
        items: document.summaryItems.map((row) => ({
          productId: row.productId,
          goodQty: Number(actionRows[row.productId]?.goodQty || 0),
          damagedQty: Number(actionRows[row.productId]?.damagedQty || 0),
          stackCode: actionRows[row.productId]?.stackCode || '',
        })),
      };
    } else if (type === 'return') {
      path = 'returns';
      payload = {
        returnDate: actionMeta.date,
        note: actionMeta.note,
        items: document.summaryItems
          .filter((row) => Number(actionRows[row.productId]?.qty || 0) > 0)
          .map((row) => ({
            productId: row.productId,
            qty: Number(actionRows[row.productId].qty),
            stackCode: actionRows[row.productId]?.stackCode || '',
          })),
      };
    } else if (type === 'realize') {
      path = 'realizations';
      payload = {
        realizationDate: actionMeta.date,
        activityType: actionMeta.activityType,
        referenceNo: actionMeta.soNo,
        note: actionMeta.note,
        items: document.summaryItems.filter((row) => Number(actionRows[row.productId]?.qty || 0) > 0).map((row) => ({ productId: row.productId, qty: Number(actionRows[row.productId].qty) })),
      };
    } else {
      path = 'so-documents';
      payload = { soNo: actionMeta.soNo, soDate: actionMeta.date, note: actionMeta.note, items: document.summaryItems.filter((row) => Number(actionRows[row.productId]?.qty || 0) > 0).map((row) => ({ productId: row.productId, qty: Number(actionRows[row.productId].qty) })) };
    }
    if (!payload.items.length) return toast.error('Isi minimal satu kuantum');
    setSaving(true);
    try {
      await api.post(`/bazar/external-nds/${document.id}/${path}`, payload);
      toast.success(type === 'receive' ? 'Penerimaan fisik tersimpan' : type === 'return' ? 'Retur ke gudang asal tersimpan' : type === 'realize' ? 'Realisasi penjualan/distribusi terikat ke ND' : 'SO akhir tersimpan tanpa mutasi stok ganda');
      setAction(null); await Promise.all([load(), refreshConsignmentFlow()]);
    } catch (error) { toast.error(apiError(error)); } finally { setSaving(false); }
  };

  return <div className="space-y-6">
    <div><div className="label-mono mb-2">Operasional Bazar · Gudang Lain</div><h1 className="font-display text-3xl sm:text-4xl font-bold">Register ND & Rekonsiliasi SO</h1></div>
    <div className="rounded-xl border border-[#2563eb]/30 bg-[#0d1726] px-4 py-3 text-sm text-[#bfdbfe]">Khusus barang dari gudang di luar GST I & II. Setiap penerimaan Baik membentuk lot sumber ND; retur, realisasi, dan SO dapat ditelusuri kembali ke lot tersebut. SO tetap administratif dan tidak mengurangi stok untuk kedua kali.</div>

    <section className="card-surface p-5 space-y-3">
      <div className="font-semibold flex items-center gap-2"><FilePlus2 size={17}/> Register ND dari Gudang Lain</div>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
        <input className={inputCls} placeholder="Nomor ND" value={form.ndNo} onChange={(e) => setForm({ ...form, ndNo: e.target.value })}/>
        <input type="date" className={inputCls} value={form.ndDate} onChange={(e) => setForm({ ...form, ndDate: e.target.value })}/>
        <input className={inputCls} placeholder="Gudang asal, mis. Sunter III" value={form.originWarehouse} onChange={(e) => setForm({ ...form, originWarehouse: e.target.value })}/>
        <select className={inputCls} value={form.activityType} onChange={(e) => setForm({ ...form, activityType: e.target.value })}><option value="BAZAR">Bazar</option><option value="PAKET">Paket</option><option value="BAZAR_DAN_PAKET">Bazar & Paket</option></select>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-[1fr_160px_auto] gap-2">
        <SearchableProductSelect
          products={activeProducts}
          value={draft.productId}
          onChange={(productId) => setDraft({ ...draft, productId })}
          placeholder="Ketik nama / SKU komoditi..."
          getDescription={(row) => `${row.channel || 'KOM'} · ${row.unit || ''}`}
        />
        <input type="number" min="0" className={inputCls} placeholder="Kuantum ND" value={draft.qty} onChange={(e) => setDraft({ ...draft, qty: e.target.value })}/>
        <button onClick={addItem} className="px-4 rounded-lg border border-[#3b82f6]/50 text-[#93c5fd]">Tambah</button>
      </div>
      <div className="flex flex-wrap gap-2">{items.map((row) => <button key={row.productId} onClick={() => setItems((prev) => prev.filter((x) => x.productId !== row.productId))} className="text-xs px-3 py-2 rounded-lg bg-[#1e293b]">{row.name} · {row.qty} {row.unit} ×</button>)}</div>
      <textarea className={inputCls} placeholder="Catatan ND" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })}/>
      <button disabled={saving} onClick={createDocument} className="btn-primary px-5 py-2.5 rounded-lg font-semibold">Simpan Register ND</button>
    </section>

    <section className="card-surface p-5">
      <div className="flex items-center justify-between mb-4"><div className="font-semibold flex items-center gap-2"><Warehouse size={17}/> Perjalanan Dokumen ND</div><button onClick={load} className="text-xs inline-flex items-center gap-1 text-[#93c5fd]"><RefreshCcw size={13}/> Refresh</button></div>
      <div className="space-y-3">
        {!documents.length && <div className="text-sm text-[#8b93a1]">Belum ada ND dari gudang lain.</div>}
        {documents.map((doc) => <div key={doc.id} className="border border-[#243044] rounded-xl p-4">
          <div className="flex flex-wrap justify-between gap-2"><div><b>{doc.ndNo}</b> · {doc.originWarehouse}<div className="text-xs text-[#8b93a1] mt-1">{doc.ndDate} · Tujuan {doc.activityType.replaceAll('_', ' ')}</div></div><span className="text-xs px-2.5 py-1 rounded-full bg-[#2563eb]/15 text-[#93c5fd]">{statusLabel(doc.status)}</span></div>
          <div className="mt-3 overflow-x-auto"><table className="w-full text-xs"><thead className="text-[#8b93a1]"><tr><th className="text-left py-1">Komoditi</th><th>ND</th><th>Diterima Baik</th><th>Rusak</th><th>Retur Asal</th><th>Realisasi</th><th>SO</th><th>Saldo Fisik</th><th>Siap SO</th><th>Lot Aktif</th></tr></thead><tbody>{(doc.summaryItems || []).map((row) => <tr key={row.productId} className="border-t border-[#1f2937]"><td className="py-2">{row.name}</td><td className="text-center">{row.ordered}</td><td className="text-center">{row.good}</td><td className="text-center">{row.damaged}</td><td className="text-center">{row.returned}</td><td className="text-center">{row.realized}</td><td className="text-center">{row.settled}</td><td className="text-center font-bold text-[#fbbf24]">{row.physicalBalance}</td><td className="text-center font-bold text-[#86efac]">{row.eligibleSoQty}</td><td className="text-center text-[#93c5fd]">{row.sourceLotCount || 0} · sisa {row.sourceLotRemaining || 0}</td></tr>)}</tbody></table></div>
          {(doc.sourceLots || []).length > 0 && <details className="mt-3 rounded-lg border border-[#243044] bg-[#0b0f17]">
            <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-[#93c5fd]">Trace Lot Sumber ND ({doc.sourceLots.length})</summary>
            <div className="overflow-x-auto px-3 pb-3">
              <table className="w-full text-[11px]">
                <thead className="text-[#8b93a1]"><tr><th className="text-left py-2">Lot</th><th className="text-left">Komoditi</th><th>Tgl Terima</th><th>Lokasi Awal</th><th>Diterima</th><th>Retur</th><th>Realisasi</th><th>Sisa</th></tr></thead>
                <tbody>{doc.sourceLots.map((lot) => <tr key={lot.id} className="border-t border-[#1f2937]">
                  <td className="py-2 font-mono text-[#93c5fd] whitespace-nowrap">{lot.lotNo}</td>
                  <td className="pr-3 min-w-[220px]">{lot.name}</td>
                  <td className="text-center whitespace-nowrap">{lot.receiptDate}</td>
                  <td className="text-center font-mono whitespace-nowrap">{lot.stackCode || '—'}</td>
                  <td className="text-center">{lot.receivedQty}</td>
                  <td className="text-center">{lot.returnedQty}</td>
                  <td className="text-center">{lot.realizedQty}</td>
                  <td className="text-center font-bold text-[#fbbf24]">{lot.remainingQty}</td>
                </tr>)}</tbody>
              </table>
            </div>
          </details>}
          <div className="flex flex-wrap gap-2 mt-3">
            {!['SELESAI','DIBATALKAN'].includes(doc.status) && (doc.summaryItems || []).some((row) => row.remainingToReceive > 0) && <button onClick={() => openAction('receive', doc)} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-[#2563eb]/50 text-[#93c5fd] text-xs"><ArrowDownToLine size={13}/> Terima Fisik</button>}
            {!['SELESAI','DIBATALKAN'].includes(doc.status) && (doc.summaryItems || []).some((row) => row.physicalBalance > 0) && <button onClick={() => openAction('return', doc)} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-[#f59e0b]/50 text-[#fbbf24] text-xs"><RotateCcw size={13}/> Retur ke Gudang Asal</button>}
            {!['SELESAI','DIBATALKAN'].includes(doc.status) && (doc.summaryItems || []).some((row) => row.physicalBalance > 0) && <button onClick={() => openAction('realize', doc)} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-[#a855f7]/50 text-[#d8b4fe] text-xs"><BadgeCheck size={13}/> Catat Realisasi</button>}
            {!['SELESAI','DIBATALKAN'].includes(doc.status) && (doc.summaryItems || []).some((row) => row.eligibleSoQty > 0) && <button onClick={() => openAction('so', doc)} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-[#22c55e]/50 text-[#86efac] text-xs"><FileCheck2 size={13}/> Catat SO Terbit</button>}
            {doc.status === 'ND_TERDAFTAR' && <button onClick={() => cancelDocument(doc)} className="px-3 py-2 rounded-lg border border-[#ef4444]/40 text-[#fca5a5] text-xs font-semibold">Batalkan ND</button>}
          </div>
        </div>)}
      </div>
    </section>

    {action && <div className="fixed inset-0 z-[90] bg-black/75 flex items-center justify-center p-4"><div className="card-surface w-full max-w-3xl p-6 max-h-[90vh] overflow-y-auto">
      <h2 className="font-display text-xl font-bold">{action.type === 'receive' ? 'Penerimaan Fisik' : action.type === 'return' ? 'Retur ke Gudang Asal' : action.type === 'realize' ? 'Rekonsiliasi Realisasi' : 'Pencatatan SO Akhir'} · {action.document.ndNo}</h2>
      <div className="text-xs text-[#8b93a1] mt-1 mb-2">Asal {action.document.originWarehouse}</div>
      {['return', 'realize'].includes(action.type) && <div className="mb-4 rounded-lg border border-[#2563eb]/30 bg-[#0d1726] px-3 py-2 text-xs text-[#bfdbfe]">Trace sumber dialokasikan otomatis FIFO dari lot penerimaan ND ini. Sistem tidak dapat mengambil saldo dari ND lain.</div>}
      {action.type === 'so' && <div className="mb-4 rounded-lg border border-[#22c55e]/30 bg-[#052e16]/20 px-3 py-2 text-xs text-[#bbf7d0]">SO akan ditautkan ke realisasi Bazar/Paket yang belum terselesaikan, termasuk lot sumber asalnya.</div>}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-3">
        <input type="date" className={inputCls} value={actionMeta.date} onChange={(e) => setActionMeta({ ...actionMeta, date: e.target.value })}/>
        {action.type === 'receive' && <input className={inputCls} placeholder="No. kendaraan" value={actionMeta.vehicleNo} onChange={(e) => setActionMeta({ ...actionMeta, vehicleNo: e.target.value })}/>}
        {action.type === 'so' && <input className={inputCls} placeholder="Nomor SO" value={actionMeta.soNo} onChange={(e) => setActionMeta({ ...actionMeta, soNo: e.target.value })}/>}
        {action.type === 'realize' && action.document.activityType === 'BAZAR_DAN_PAKET' && <select className={inputCls} value={actionMeta.activityType} onChange={(e) => setActionMeta({ ...actionMeta, activityType: e.target.value, soNo: '' })}><option value="BAZAR">Bazar</option><option value="PAKET">Paket</option></select>}
        {action.type === 'realize' && <select className={inputCls} value={actionMeta.soNo} onChange={(e) => setActionMeta({ ...actionMeta, soNo: e.target.value })}><option value="">Pilih kegiatan selesai</option>{realizationReferences.map((row) => <option key={row.value} value={row.value}>{row.label}</option>)}</select>}
      </div>
      <div className="space-y-3">{action.document.summaryItems.map((row) => <div key={row.productId} className="border border-[#243044] rounded-xl p-3"><div className="text-sm font-semibold mb-2">{row.name} · {action.type === 'receive' ? `sisa ND ${row.remainingToReceive}` : action.type === 'so' ? `siap SO ${row.eligibleSoQty}` : `saldo fisik ${row.physicalBalance}`} {row.unit}</div>{action.type === 'receive' ? <div className="grid grid-cols-1 sm:grid-cols-3 gap-2"><input type="number" min="0" className={inputCls} placeholder="Diterima baik" value={actionRows[row.productId]?.goodQty || ''} onChange={(e) => setActionRows((p) => ({ ...p, [row.productId]: { ...p[row.productId], goodQty: e.target.value } }))}/><input type="number" min="0" className={inputCls} placeholder="Diterima rusak" value={actionRows[row.productId]?.damagedQty || ''} onChange={(e) => setActionRows((p) => ({ ...p, [row.productId]: { ...p[row.productId], damagedQty: e.target.value } }))}/><select className={inputCls} value={actionRows[row.productId]?.stackCode || ''} onChange={(e) => setActionRows((p) => ({ ...p, [row.productId]: { ...p[row.productId], stackCode: e.target.value } }))}><option value="">Lokasi barang baik</option>{consignmentStackCodes('Gudang Bazar').map((code) => <option key={code} value={code}>{code}</option>)}</select></div> : action.type === 'return' ? <div className="grid grid-cols-1 sm:grid-cols-2 gap-2"><input type="number" min="0" max={row.physicalBalance} className={inputCls} placeholder="Jumlah kembali ke gudang asal" value={actionRows[row.productId]?.qty || ''} onChange={(e) => setActionRows((p) => ({ ...p, [row.productId]: { ...p[row.productId], qty: e.target.value } }))}/><select className={inputCls} value={actionRows[row.productId]?.stackCode || ''} onChange={(e) => setActionRows((p) => ({ ...p, [row.productId]: { ...p[row.productId], stackCode: e.target.value } }))}>{consignmentStackCodes('Gudang Bazar').map((code) => <option key={code} value={code}>{code}</option>)}</select></div> : <input type="number" min="0" max={action.type === 'so' ? row.eligibleSoQty : row.physicalBalance} className={inputCls} placeholder={action.type === 'realize' ? 'Jumlah terjual/disalurkan' : 'Kuantum dalam SO'} value={actionRows[row.productId]?.qty || ''} onChange={(e) => setActionRows((p) => ({ ...p, [row.productId]: { ...p[row.productId], qty: e.target.value } }))}/>}</div>)}</div>
      <textarea className={`${inputCls} mt-3`} placeholder="Catatan" value={actionMeta.note} onChange={(e) => setActionMeta({ ...actionMeta, note: e.target.value })}/>
      <div className="flex justify-end gap-2 mt-5"><button onClick={() => setAction(null)} className="px-4 py-2 rounded-lg border border-[#243044]">Batal</button><button disabled={saving} onClick={submitAction} className="btn-primary px-5 py-2 rounded-lg font-semibold">Simpan</button></div>
    </div></div>}
  </div>;
};

export default BazarNDExternal;
