import React, { useEffect, useMemo, useState } from 'react';
import { ArrowDownToLine, RefreshCcw } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError } from '../lib/api';
import SearchableProductSelect from './SearchableProductSelect';

const inputCls = 'w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';
const formatNum = (value) => Number(value || 0).toLocaleString('id-ID', { maximumFractionDigits: 4 });

const ConsignmentReturnToMainCard = ({ destination, onChanged }) => {
  const [options, setOptions] = useState({ sources: [], mainStackCodes: [] });
  const [productId, setProductId] = useState('');
  const [sourceStackCode, setSourceStackCode] = useState('');
  const [destinationStackCode, setDestinationStackCode] = useState('');
  const [qty, setQty] = useState('');
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/consignment-return-main/options', { params: { destination } });
      setOptions(data || { sources: [], mainStackCodes: [] });
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [destination]);

  const products = useMemo(() => {
    const map = new Map();
    (options.sources || []).forEach((row) => {
      if (!map.has(row.productId)) {
        map.set(row.productId, { id: row.productId, name: row.name || row.sku || 'Komoditi', sku: row.sku || '', unit: row.unit || '' });
      }
    });
    return [...map.values()].sort((a, b) => a.name.localeCompare(b.name, 'id'));
  }, [options.sources]);

  const sources = useMemo(
    () => (options.sources || []).filter((row) => row.productId === productId)
      .sort((a, b) => String(a.sourceStackCode || '').localeCompare(String(b.sourceStackCode || ''), 'id', { numeric: true })),
    [options.sources, productId],
  );
  const source = sources.find((row) => row.sourceStackCode === sourceStackCode);
  const product = products.find((row) => row.id === productId);

  const chooseProduct = (value) => {
    setProductId(value);
    setSourceStackCode('');
    setQty('');
  };

  const chooseSource = (value) => {
    setSourceStackCode(value);
    const row = sources.find((item) => item.sourceStackCode === value);
    setQty(row ? String(row.availableQty || '') : '');
  };

  const submit = async () => {
    const numericQty = Number(qty || 0);
    if (!productId || !sourceStackCode || !destinationStackCode || numericQty <= 0) {
      return toast.error('Lengkapi komoditi, lokasi asal, tumpukan Gudang Induk, dan jumlah');
    }
    if (numericQty > Number(source?.availableQty || 0) + 1e-9) {
      return toast.error(`Maksimal yang dapat dikembalikan dari ${sourceStackCode} adalah ${formatNum(source?.availableQty)} ${product?.unit || ''}`);
    }
    setSaving(true);
    try {
      const key = `kembali-induk-${destination === 'Gudang Bazar' ? 'bazar' : 'ecom'}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
      const { data } = await api.post('/consignment-return-main', {
        destination,
        productId,
        sourceStackCode,
        destinationStackCode: destinationStackCode.trim().toUpperCase(),
        qty: numericQty,
        note: note.trim(),
      }, { headers: { 'X-Idempotency-Key': key } });
      toast.success(`${formatNum(data.qty)} ${data.unit} dikembalikan ke ${data.destinationStackCode} · ${data.referenceNo}`);
      setProductId('');
      setSourceStackCode('');
      setDestinationStackCode('');
      setQty('');
      setNote('');
      await load();
      await onChanged?.();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  const areaLabel = destination === 'Gudang Bazar' ? 'Bazar' : 'E-commerce';

  return <div className="card-surface p-5 border border-[#1d4ed8]/40">
    <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
      <div>
        <div className="font-semibold flex items-center gap-2"><ArrowDownToLine size={17} className="text-[#60a5fa]"/> Kembalikan ke Gudang Induk</div>
        <p className="text-xs text-[#8b93a1] mt-1">Pindahkan stok baik {areaLabel} ke GBB/MP1. Bisa sebagian atau seluruh saldo tersedia; total stok perusahaan tidak berubah.</p>
      </div>
      <button type="button" onClick={load} disabled={loading} className="p-2 rounded-lg border border-[#242f3d] text-[#93c5fd] disabled:opacity-50" title="Perbarui saldo">
        <RefreshCcw size={15} className={loading ? 'animate-spin' : ''}/>
      </button>
    </div>

    {products.length === 0 ? <div className="text-sm text-[#8b93a1]">Belum ada stok {areaLabel} yang tersedia untuk dikembalikan.</div> : <>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2">
        <SearchableProductSelect
          products={products}
          value={productId}
          onChange={chooseProduct}
          placeholder="Cari komoditi..."
          getDescription={(row) => `${row.sku || ''} · ${row.unit || ''}`}
        />
        <select className={inputCls} value={sourceStackCode} onChange={(e) => chooseSource(e.target.value)} disabled={!productId}>
          <option value="">Lokasi asal {areaLabel}...</option>
          {sources.map((row) => <option key={`${row.productId}-${row.sourceStackCode}`} value={row.sourceStackCode}>
            {row.sourceStackCode} · tersedia {formatNum(row.availableQty)} {row.unit}
          </option>)}
        </select>
        <div>
          <input
            list={`main-stack-options-${destination.replaceAll(' ', '-')}`}
            className={inputCls}
            value={destinationStackCode}
            onChange={(e) => setDestinationStackCode(e.target.value.toUpperCase())}
            disabled={!sourceStackCode}
            placeholder="Tumpukan tujuan, contoh 18/C01"
          />
          <datalist id={`main-stack-options-${destination.replaceAll(' ', '-')}`}>
            {(options.mainStackCodes || []).map((code) => <option key={code} value={code}/>)}
          </datalist>
        </div>
        <div>
          <input type="number" min="0.01" step="any" className={inputCls} value={qty} onChange={(e) => setQty(e.target.value)} disabled={!sourceStackCode} placeholder={product?.unit ? `Jumlah (${product.unit})` : 'Jumlah'} />
          {source && <button type="button" onClick={() => setQty(String(source.availableQty || ''))} className="mt-1.5 text-[11px] text-[#93c5fd] hover:underline">
            Ambil semua tersedia: {formatNum(source.availableQty)} {source.unit}
          </button>}
        </div>
      </div>

      {source && <div className="mt-3 rounded-lg border border-[#243044] bg-[#0b0f17] px-3 py-2 text-xs text-[#8b93a1]">
        Fisik di {source.sourceStackCode}: <b className="text-[#e5e7eb]">{formatNum(source.physicalQty)} {source.unit}</b>
        {Number(source.reservedQty || 0) > 0 && <> · Terikat kegiatan: <b className="text-[#fbbf24]">{formatNum(source.reservedQty)} {source.unit}</b></>}
        {' '}· Dapat dikembalikan: <b className="text-[#86efac]">{formatNum(source.availableQty)} {source.unit}</b>
      </div>}

      <textarea rows={2} className={`${inputCls} mt-3`} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Catatan pengembalian (opsional)" />
      <button type="button" onClick={submit} disabled={saving || loading || !sourceStackCode} className="btn-primary mt-3 inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50">
        <ArrowDownToLine size={16}/>{saving ? 'Mengembalikan…' : 'Kembalikan ke Gudang Induk'}
      </button>
    </>}
  </div>;
};

export default ConsignmentReturnToMainCard;
