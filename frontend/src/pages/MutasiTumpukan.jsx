import React, { useEffect, useMemo, useState } from 'react';
import { ArrowRight, RefreshCcw, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError } from '../lib/api';
import { useData } from '../context/DataContext';
import { formatNum } from '../mock';
import { stackCodes } from '../lib/warehouses';

const MutasiTumpukan = () => {
  const { products, stackAllocations, settings, fetchAll } = useData();
  const [productId, setProductId] = useState('');
  const [sourceStackCode, setSourceStackCode] = useState('');
  const [destinationStackCode, setDestinationStackCode] = useState('');
  const [qty, setQty] = useState('');
  const [lotId, setLotId] = useState('');
  const [note, setNote] = useState('');
  const [availability, setAvailability] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const stacks = stackCodes(settings?.warehouses);
  const sourceAllocations = useMemo(() => (stackAllocations || []).filter((row) => Number(row.primaryQty || 0) > 0), [stackAllocations]);
  const productOptions = useMemo(() => {
    const ids = new Set(sourceAllocations.map((row) => row.productId));
    return (products || []).filter((row) => ids.has(row.id)).sort((a, b) => a.name.localeCompare(b.name, 'id'));
  }, [products, sourceAllocations]);
  const sourceOptions = sourceAllocations.filter((row) => row.productId === productId).sort((a, b) => String(a.stackCode).localeCompare(String(b.stackCode), 'id', { numeric: true }));
  const product = products.find((row) => row.id === productId);
  const selectedSource = sourceOptions.find((row) => row.stackCode === sourceStackCode);
  const scope = sourceStackCode && destinationStackCode && sourceStackCode.split('/')[0] === destinationStackCode.split('/')[0] ? 'Dalam GBB' : 'Antar GBB / MP1';

  const loadHistory = async () => {
    try { const { data } = await api.get('/stock-transfers?limit=20'); setHistory(data || []); }
    catch { setHistory([]); }
  };

  useEffect(() => { loadHistory(); }, []);
  useEffect(() => {
    setAvailability(null);
    setLotId('');
    if (!productId || !sourceStackCode) return;
    let cancelled = false;
    setLoading(true);
    api.get(`/stock-transfers/availability?productId=${encodeURIComponent(productId)}&stackCode=${encodeURIComponent(sourceStackCode)}`)
      .then(({ data }) => { if (!cancelled) setAvailability(data); })
      .catch((e) => { if (!cancelled) toast.error(apiError(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [productId, sourceStackCode]);

  const chooseProduct = (value) => {
    setProductId(value);
    setSourceStackCode('');
    setDestinationStackCode('');
    setQty('');
    setLotId('');
  };

  const submit = async () => {
    const numericQty = Number(qty || 0);
    if (!productId || !sourceStackCode || !destinationStackCode || numericQty <= 0) return toast.error('Lengkapi produk, tumpukan asal, tujuan, dan jumlah mutasi');
    if (sourceStackCode === destinationStackCode) return toast.error('Tumpukan asal dan tujuan harus berbeda');
    if (availability && numericQty > Number(availability.availableQty || 0)) return toast.error(`Stok tersedia hanya ${formatNum(availability.availableQty || 0)} ${product?.unit || ''}`);
    if (lotId) {
      const lot = (availability?.lots || []).find((row) => row.id === lotId);
      if (lot && numericQty > Number(lot.remainingQty || 0)) return toast.error('Jumlah mutasi melebihi saldo lot yang dipilih');
    }
    setSaving(true);
    try {
      const idempotencyKey = `mutasi-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      const { data } = await api.post('/stock-transfers', {
        productId, sourceStackCode, destinationStackCode, qty: numericQty, lotId, note,
      }, { headers: { 'X-Idempotency-Key': idempotencyKey } });
      toast.success(`Mutasi ${data.sourceStackCode} → ${data.destinationStackCode} berhasil. Total stok produk tidak berubah.`);
      setQty(''); setLotId(''); setNote(''); setAvailability(null);
      await fetchAll();
      await loadHistory();
    } catch (e) { toast.error(apiError(e)); }
    finally { setSaving(false); }
  };

  return <div className="space-y-6">
    <div>
      <div className="label-mono mb-2">Operasional Gudang</div>
      <h1 className="font-display text-4xl font-bold">Mutasi Tumpukan</h1>
    </div>

    <div className="card-surface p-5 md:p-6">
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div><label className="text-xs text-[#8b93a1] block mb-1">Komoditi</label><select value={productId} onChange={(e) => chooseProduct(e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5"><option value="">Pilih komoditi...</option>{productOptions.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.sku}</option>)}</select></div>
        <div><label className="text-xs text-[#8b93a1] block mb-1">Tumpukan asal</label><select value={sourceStackCode} onChange={(e) => { setSourceStackCode(e.target.value); setDestinationStackCode(''); setQty(''); }} disabled={!productId} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 disabled:opacity-50"><option value="">Pilih asal...</option>{sourceOptions.map((row) => <option key={row.id} value={row.stackCode}>{row.stackCode} · fisik {formatNum(row.primaryQty)} {row.unit}</option>)}</select></div>
        <div><label className="text-xs text-[#8b93a1] block mb-1">Tumpukan tujuan</label><select value={destinationStackCode} onChange={(e) => setDestinationStackCode(e.target.value)} disabled={!sourceStackCode} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 disabled:opacity-50"><option value="">Pilih tujuan...</option>{stacks.filter((code) => code !== sourceStackCode).map((code) => <option key={code} value={code}>{code}</option>)}</select></div>
        <div><label className="text-xs text-[#8b93a1] block mb-1">Jumlah dipindahkan</label><input type="number" min="0.01" step="any" value={qty} onChange={(e) => setQty(e.target.value)} disabled={!sourceStackCode} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 disabled:opacity-50" placeholder={product?.unit ? `Dalam ${product.unit}` : 'Jumlah'} /></div>
      </div>

      {sourceStackCode && <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
        <div className="rounded-lg border border-[#242f3d] p-3"><div className="text-[#8b93a1]">Fisik asal</div><div className="font-mono font-bold mt-1">{loading ? '…' : `${formatNum(availability?.physicalQty || selectedSource?.primaryQty || 0)} ${product?.unit || ''}`}</div></div>
        <div className="rounded-lg border border-[#7c2d12] p-3"><div className="text-[#fca5a5]">Direservasi outbound</div><div className="font-mono font-bold mt-1 text-[#fca5a5]">{loading ? '…' : `${formatNum(availability?.reservedQty || 0)} ${product?.unit || ''}`}</div></div>
        <div className="rounded-lg border border-[#14532d] p-3"><div className="text-[#86efac]">Tersedia dimutasi</div><div className="font-mono font-bold mt-1 text-[#86efac]">{loading ? '…' : `${formatNum(availability?.availableQty || 0)} ${product?.unit || ''}`}</div></div>
        <div className="rounded-lg border border-[#294263] p-3"><div className="text-[#93c5fd]">Jenis mutasi</div><div className="font-medium mt-1">{destinationStackCode ? scope : '—'}</div></div>
      </div>}

      {(availability?.lots || []).length > 0 && <div className="mt-4"><label className="text-xs text-[#8b93a1] block mb-1">Lot yang dipindahkan <span className="text-[#6b7688]">(opsional)</span></label><select value={lotId} onChange={(e) => setLotId(e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5"><option value="">Otomatis: legacy/untracked dulu, lalu FEFO</option>{availability.lots.map((lot) => <option key={lot.id} value={lot.id}>{lot.lotCode || lot.id} · exp {lot.exp || 'tanpa expired'} · saldo {formatNum(lot.remainingQty)} {lot.unit}</option>)}</select><p className="text-[11px] text-[#6b7688] mt-1">Pilih lot bila secara fisik lot tertentu yang dipindahkan. Jika kosong, sistem menjaga kebijakan legacy-first lalu FEFO.</p></div>}

      <div className="mt-4"><label className="text-xs text-[#8b93a1] block mb-1">Catatan mutasi</label><textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" placeholder="Contoh: perapihan ruang, konsolidasi tumpukan, pindah antar GBB..." /></div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button disabled={saving || loading} onClick={submit} className="btn-primary inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50"><ArrowRight size={16} />{saving ? 'Memindahkan...' : 'Proses Mutasi'}</button>
        <div className="text-xs text-[#8b93a1] inline-flex items-center gap-1.5"><ShieldCheck size={14} />Reservasi outbound dilindungi; stok induk tidak bertambah/berkurang.</div>
      </div>
    </div>

    <div className="card-surface p-5 md:p-6">
      <div className="flex items-center justify-between gap-3 mb-4"><div><h2 className="font-display text-xl font-bold">Riwayat Mutasi Terakhir</h2></div><button onClick={loadHistory} className="p-2 rounded-lg border border-[#242f3d] text-[#93c5fd]" title="Perbarui"><RefreshCcw size={16} /></button></div>
      {history.length === 0 ? <p className="text-sm text-[#8b93a1]">Belum ada mutasi tumpukan.</p> : <div className="overflow-x-auto"><table className="w-full text-sm tbl"><thead><tr className="text-left border-b border-[#1a222e]"><th className="py-2.5 pr-4">Waktu</th><th className="py-2.5 pr-4">Komoditi</th><th className="py-2.5 pr-4">Asal → Tujuan</th><th className="py-2.5 pr-4">Jumlah</th><th className="py-2.5">Lot</th></tr></thead><tbody>{history.map((row) => <tr key={row.id} className="border-b border-[#131a24]"><td className="py-3 pr-4 text-xs text-[#8b93a1]">{new Date(row.time).toLocaleString('id-ID')}</td><td className="py-3 pr-4"><div className="font-medium">{row.product}</div><div className="font-mono text-[10px] text-[#6b7688]">{row.sku}</div></td><td className="py-3 pr-4 font-mono text-xs">{row.sourceStackCode} → {row.destinationStackCode}</td><td className="py-3 pr-4 font-mono font-semibold">{formatNum(row.qty)} {row.unit}</td><td className="py-3 text-xs text-[#8b93a1]">{row.lots?.length ? row.lots.map((lot) => lot.lotCode || lot.lotId).join(', ') : row.untrackedQty ? `Legacy ${formatNum(row.untrackedQty)}` : '—'}</td></tr>)}</tbody></table></div>}
    </div>
  </div>;
};

export default MutasiTumpukan;
