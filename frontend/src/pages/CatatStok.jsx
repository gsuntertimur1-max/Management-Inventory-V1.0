import React, { useMemo, useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, Plus, Trash2, Save, ClipboardList, CalendarDays, Truck } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatRp, formatNum } from '../mock';
import { toast } from 'sonner';
import { useNavigate } from 'react-router-dom';
import { packagingText, quantityFromInput, quantityIsValid, totalWeight } from '../lib/packaging';

const STACKS = [...Array.from({ length: 8 }, (_, i) => String(i + 17)).flatMap((unit) => ['A', 'B', 'C'].flatMap((zone) => Array.from({ length: 4 }, (_, i) => `${unit}/${zone}${String(i + 1).padStart(2, '0')}`))), ...['A', 'B'].flatMap((zone) => Array.from({ length: 8 }, (_, i) => `MP1/${zone}${String(i + 1).padStart(2, '0')}`))];
const emptyRow = () => ({ productId: '', inputMode: 'QTY', inputValue: 1, qty: 1, exp: '', stackCode: '' });

const CatatStok = () => {
  const { products, suppliers, purchaseOrders, addReceipt, createOutboundLoad, canInbound, canOutbound } = useData();
  const navigate = useNavigate();
  const [type, setType] = useState(canInbound ? 'MASUK' : 'KELUAR');
  const [rows, setRows] = useState([emptyRow()]);
  const [poId, setPoId] = useState('');
  const [party, setParty] = useState('');
  const [ref, setRef] = useState('');
  const [polisi, setPolisi] = useState('');
  const [pengambil, setPengambil] = useState('');
  const [kondisi, setKondisi] = useState('BAIK');
  const [ket, setKet] = useState('');
  const [saving, setSaving] = useState(false);

  const activePOs = useMemo(
    () => purchaseOrders.filter((po) => po.status !== 'Selesai' && po.status !== 'Diterima'),
    [purchaseOrders],
  );
  const selectedPO = purchaseOrders.find((po) => po.id === poId);

  const resetForm = (nextType) => {
    setType(nextType);
    setRows([emptyRow()]);
    setPoId('');
    setParty('');
    setRef('');
    setPolisi('');
    setPengambil('');
    setKondisi('BAIK');
    setKet('');
  };

  const chooseType = (nextType) => {
    if (nextType === 'MASUK' && !canInbound) return;
    if (nextType === 'KELUAR' && !canOutbound) return;
    resetForm(nextType);
  };

  const setRow = (index, patch) => setRows((prev) => prev.map((row, i) => i === index ? { ...row, ...patch } : row));
  const setTransactionInput = (index, patch) => setRows((prev) => prev.map((row, i) => {
    if (i !== index) return row;
    const next = { ...row, ...patch };
    const product = products.find((item) => item.id === next.productId);
    return { ...next, qty: quantityFromInput(next.inputValue, next.inputMode, product) };
  }));
  const addRow = () => setRows((prev) => [...prev, emptyRow()]);
  const delRow = (index) => setRows((prev) => prev.length === 1 ? prev : prev.filter((_, i) => i !== index));

  const choosePO = (id) => {
    setPoId(id);
    if (!id) {
      setParty('');
      setRef('');
      setRows([emptyRow()]);
      return;
    }
    const po = purchaseOrders.find((item) => item.id === id);
    if (!po) return;
    const remainingItems = (po.items || [])
      .map((item) => ({
        productId: item.productId,
        inputMode: 'QTY',
        inputValue: Math.max(Number(item.qty || 0) - Number(item.receivedQty || 0), 0),
        qty: Math.max(Number(item.qty || 0) - Number(item.receivedQty || 0), 0),
        exp: '',
      }))
      .filter((item) => item.productId && item.qty > 0);
    setParty(po.supplier || '');
    setRef(po.no || '');
    setRows(remainingItems.length ? remainingItems : [emptyRow()]);
  };

  const chosen = rows
    .map((row) => ({ ...row, product: products.find((product) => product.id === row.productId) }))
    .filter((row) => row.product);

  const totalUnit = chosen.reduce((a, row) => a + Number(row.qty || 0), 0);
  const totalBerat = chosen.reduce((a, row) => a + (row.product.weight || 0) * Number(row.qty || 0), 0);
  const totalNilai = chosen.reduce((a, row) => a + (row.product.cost || 0) * Number(row.qty || 0), 0);

  const remainingFor = (productId) => {
    if (!selectedPO) return null;
    const item = (selectedPO.items || []).find((poItem) => poItem.productId === productId);
    if (!item) return 0;
    return Math.max(Number(item.qty || 0) - Number(item.receivedQty || 0), 0);
  };

  const submit = async () => {
    if (chosen.length === 0 || chosen.length !== rows.length) {
      toast.error('Lengkapi semua produk');
      return;
    }
    if (chosen.some((row) => Number(row.qty) <= 0)) {
      toast.error('Jumlah barang harus lebih dari 0');
      return;
    }
    if (chosen.some((row) => !quantityIsValid(row.qty, row.product))) {
      toast.error('Berat harus menghasilkan jumlah kemasan primer/pack yang utuh');
      return;
    }
    if (!party.trim()) {
      toast.error(type === 'MASUK' ? 'Pilih supplier pengirim' : 'Isi penerima barang');
      return;
    }

    if (type === 'MASUK' && selectedPO) {
      for (const row of chosen) {
        const remaining = remainingFor(row.productId);
        if (remaining === null || Number(row.qty) > remaining) {
          toast.error(`Jumlah ${row.product.name} melebihi sisa PO (${formatNum(remaining || 0)} ${row.product.unit})`);
          return;
        }
      }
    }

    if (saving) return;
    setSaving(true);
    try {
      if (type === 'MASUK') {
        const result = await addReceipt({
          poId,
          items: chosen.map((row) => ({ productId: row.productId, qty: Number(row.qty), exp: row.exp || '', stackCode: row.stackCode || row.product.location || '' })),
          party,
          ref,
          polisi,
          kondisi,
          keterangan: ket,
        });
        const poStatus = result?.purchaseOrder?.status;
        toast.success(poStatus ? `Penerimaan tersimpan · Status PO: ${poStatus}` : 'Stok masuk tersimpan');
        navigate('/riwayat');
      } else {
        const load = await createOutboundLoad({
          items: chosen.map((row) => ({ productId: row.productId, qty: Number(row.qty) })),
          party: party.trim(),
          ref,
          polisi,
          pengambil,
          kondisi,
          keterangan: ket,
        });
        toast.success(`Antrian ${load.antrian} dibuat. Stok belum berkurang sampai pemuatan selesai.`);
        navigate('/pengeluaran');
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Gagal menyimpan');
    } finally {
      setSaving(false);
    }
  };

  if (!canInbound && !canOutbound) {
    return (
      <div className="space-y-6">
        <div><div className="label-mono mb-2">Operasional Gudang</div><h1 className="font-display text-4xl font-bold">Pencatatan Stok Masuk / Keluar</h1></div>
        <div className="card-surface p-8 text-center"><p className="text-[#8b93a1]">Peran Anda tidak memiliki hak untuk memproses inbound atau outbound.</p></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <div className="label-mono mb-2">Operasional Gudang</div>
        <h1 className="font-display text-4xl font-bold">Pencatatan Stok Masuk / Keluar</h1>
        <p className="text-[#8b93a1] mt-2 max-w-3xl">Penerimaan langsung menambah stok. Pengeluaran membuat antrian pemuatan terlebih dahulu; stok baru berkurang setelah proses muat selesai.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="card-surface p-6 lg:col-span-2">
          <h2 className="font-display text-lg font-bold mb-4">Formulir Transaksi</h2>
          <div className={`grid ${canInbound && canOutbound ? 'grid-cols-2' : 'grid-cols-1'} gap-2 mb-5 p-1 bg-[#0b0f17] rounded-xl border border-[#1a222e]`}>
            {canInbound && <button onClick={() => chooseType('MASUK')} className={`flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold ${type === 'MASUK' ? 'bg-[#22c55e]/15 text-[#22c55e]' : 'text-[#8b93a1]'}`}><ArrowDownLeft size={16} /> Stok Masuk</button>}
            {canOutbound && <button onClick={() => chooseType('KELUAR')} className={`flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold ${type === 'KELUAR' ? 'bg-[#ef4444]/15 text-[#ef4444]' : 'text-[#8b93a1]'}`}><ArrowUpRight size={16} /> Stok Keluar</button>}
          </div>

          {type === 'MASUK' && (
            <div className="mb-5 p-4 rounded-xl border border-[#1f3657] bg-[#0d1728]">
              <div className="flex items-center gap-2 mb-2"><ClipboardList size={16} className="text-[#60a5fa]" /><label className="text-sm font-semibold">Purchase Order</label></div>
              <select value={poId} onChange={(e) => choosePO(e.target.value)} className="w-full bg-[#0b0f17] border border-[#2b3b52] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]">
                <option value="">Tanpa PO / Penerimaan langsung</option>
                {activePOs.map((po) => <option key={po.id} value={po.id}>{po.no} · {po.supplier} · {po.status}</option>)}
              </select>
              <p className="text-xs text-[#6b7688] mt-2">Jika memilih PO, barang dan sisa pesanan akan terisi otomatis.</p>
            </div>
          )}

          {type === 'KELUAR' && (
            <div className="mb-5 p-4 rounded-xl border border-[#5a3b15] bg-[#1a1208] flex gap-3">
              <Truck size={18} className="text-[#f59e0b] shrink-0 mt-0.5" />
              <div><div className="text-sm font-semibold text-[#fbbf24]">Tahap Persiapan Pemuatan</div><p className="text-xs text-[#a99675] mt-1">Simpan form untuk mendapatkan nomor antrian. Bon Muat dicetak saat Mulai Muat. Surat Jalan baru terbit setelah Selesai Muat.</p></div>
            </div>
          )}

          <label className="text-sm font-medium mb-2 block">Daftar Barang</label>
          <div className="space-y-3 mb-3">
            {rows.map((row, index) => {
              const product = products.find((item) => item.id === row.productId);
              const remaining = remainingFor(row.productId);
              return (
                <div key={index} className={`grid gap-2 items-end p-3 rounded-lg border border-[#1a222e] bg-[#0b0f17] ${type === 'MASUK' ? 'grid-cols-1 md:grid-cols-[minmax(190px,1fr)_105px_145px_175px_52px]' : 'grid-cols-1 md:grid-cols-[minmax(220px,1fr)_105px_160px_52px]'}`}>
                  <div>
                    <label className="text-[10px] text-[#6b7688] mb-1 block">Produk</label>
                    <select value={row.productId} disabled={Boolean(selectedPO)} onChange={(e) => setTransactionInput(index, { productId: e.target.value, inputMode: 'QTY', inputValue: 1 })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb] disabled:opacity-70">
                      <option value="">Pilih produk...</option>
                      {products.map((item) => <option key={item.id} value={item.id}>{item.name} ({formatNum(item.stock || 0)} {item.unit})</option>)}
                    </select>
                    {selectedPO && product && <div className="text-[10px] text-[#60a5fa] mt-1">Sisa PO: {formatNum(remaining)} {product.unit}</div>}
                  </div>
                  <div>
                    <label className="text-[10px] text-[#6b7688] mb-1 block">Input Berdasarkan</label>
                    <select value={row.inputMode || 'QTY'} onChange={(e) => setTransactionInput(index, { inputMode: e.target.value, inputValue: e.target.value === 'WEIGHT' ? totalWeight(row.qty, product) : row.qty })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2.5 text-xs outline-none focus:border-[#2563eb]">
                      <option value="QTY">Jumlah</option>
                      <option value="WEIGHT" disabled={!Number(product?.weight || 0)}>Berat</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] text-[#6b7688] mb-1 block">{row.inputMode === 'WEIGHT' ? 'Berat (kg)' : `Jumlah (${product?.unit || 'unit'})`}</label>
                    <input type="number" min="0.01" step="any" value={row.inputValue} onChange={(e) => setTransactionInput(index, { inputValue: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" />
                    {product && Number(row.qty || 0) > 0 && <div className="text-[9px] text-[#60a5fa] mt-1">{formatNum(row.qty)} {product.unit} · {formatNum(totalWeight(row.qty, product))} kg{packagingText(row.qty, product, formatNum) ? ` · ${packagingText(row.qty, product, formatNum)}` : ''}</div>}
                  </div>
                  {type === 'MASUK' && (
                    <div><label className="text-[10px] text-[#6b7688] mb-1 flex items-center gap-1"><CalendarDays size={11} /> Kedaluwarsa / Lokasi</label><input type="date" value={row.exp || ''} onChange={(e) => setRow(index, { exp: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-sm" /><select value={row.stackCode || product?.location || ''} onChange={(e) => setRow(index, { stackCode: e.target.value })} className="w-full mt-1 bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2 text-xs"><option value="">Pilih lokasi...</option>{STACKS.map((code) => <option key={code}>{code}</option>)}</select></div>
                  )}
                  <button type="button" onClick={() => delRow(index)} disabled={rows.length === 1} className="w-10 h-[42px] rounded-lg border border-[#242f3d] flex items-center justify-center text-[#ef4444] disabled:opacity-30"><Trash2 size={15} /></button>
                </div>
              );
            })}
          </div>
          {!selectedPO && <button onClick={addRow} className="inline-flex items-center gap-2 text-sm text-[#60a5fa] mb-5"><Plus size={15} /> Tambah Barang</button>}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div><label className="text-sm font-medium mb-1.5 block">{type === 'MASUK' ? 'Supplier Pengirim' : 'Penerima / Tujuan'}</label>{type === 'MASUK' ? <select value={party} disabled={Boolean(selectedPO)} onChange={(e) => setParty(e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm"><option value="">Pilih supplier...</option>{suppliers.map((supplier) => <option key={supplier.id}>{supplier.name}</option>)}</select> : <input value={party} onChange={(e) => setParty(e.target.value)} placeholder="Nama penerima / tujuan" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm" />}</div>
            <div><label className="text-sm font-medium mb-1.5 block">{type === 'MASUK' ? 'No. Referensi' : 'Nomor SO / Referensi'}</label><input value={ref} readOnly={Boolean(selectedPO)} onChange={(e) => setRef(e.target.value)} placeholder={type === 'MASUK' ? 'DO / BAST / referensi lain' : 'SO/8775/09/2026/09001'} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm read-only:opacity-70" /></div>
            <div><label className="text-sm font-medium mb-1.5 block">Nomor Plat Kendaraan</label><input value={polisi} onChange={(e) => setPolisi(e.target.value)} placeholder="B 1441 PQF" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm" /></div>
            {type === 'KELUAR' ? (
              <div><label className="text-sm font-medium mb-1.5 block">Nama Pengambil / Sopir</label><input value={pengambil} onChange={(e) => setPengambil(e.target.value)} placeholder="Contoh: KOYUM" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm" /></div>
            ) : (
              <div><label className="text-sm font-medium mb-1.5 block">Kondisi Barang</label><select value={kondisi} onChange={(e) => setKondisi(e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm"><option value="BAIK">Baik (Good)</option><option value="RUSAK">Rusak (Damage)</option></select></div>
            )}
            {type === 'KELUAR' && <div><label className="text-sm font-medium mb-1.5 block">Kondisi Barang</label><select value={kondisi} onChange={(e) => setKondisi(e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm"><option value="BAIK">Baik (Good)</option><option value="RUSAK">Rusak (Damage)</option></select></div>}
          </div>
          <div className="mt-4"><label className="text-sm font-medium mb-1.5 block">Keterangan</label><textarea value={ket} onChange={(e) => setKet(e.target.value)} rows={2} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm resize-none" /></div>
          <button onClick={submit} disabled={saving} className="btn-primary w-full mt-5 flex items-center justify-center gap-2 py-3 rounded-lg font-semibold text-sm disabled:opacity-60"><Save size={16} /> {saving ? 'Menyimpan…' : type === 'MASUK' ? 'Simpan Stok Masuk' : 'Buat Antrian Pemuatan'}</button>
        </div>

        <div className="card-surface p-6 h-fit">
          <h2 className="font-display text-lg font-bold mb-4">Ringkasan</h2>
          <span className="text-xs px-2.5 py-1 rounded-full font-semibold" style={{ background: type === 'MASUK' ? 'rgba(34,197,94,.15)' : 'rgba(239,68,68,.15)', color: type === 'MASUK' ? '#22c55e' : '#ef4444' }}>{type}</span>
          <div className="mt-5 space-y-3 text-sm">{[['Jenis barang', chosen.length], ['Total unit', formatNum(totalUnit)], ['Total berat', `${totalBerat.toFixed(2)} kg`], ['Estimasi nilai', formatRp(totalNilai)]].map(([label, value]) => <div key={label} className="flex justify-between border-b border-[#151d28] pb-3"><span className="text-[#8b93a1]">{label}</span><span className="font-mono font-semibold">{value}</span></div>)}</div>
          {type === 'KELUAR' && <div className="mt-4 p-3 rounded-lg bg-[#0d1728] border border-[#1f3657] text-xs text-[#8fb8ef]">Setelah antrian dibuat, stok fisik tetap sama sampai pemuatan dinyatakan selesai.</div>}
        </div>
      </div>
    </div>
  );
};

export default CatatStok;
