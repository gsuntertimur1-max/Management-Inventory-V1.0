import React, { useEffect, useMemo, useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, Plus, Trash2, Save, ClipboardList, CalendarDays, Truck } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatRp, formatNum } from '../mock';
import { toast } from 'sonner';
import { useNavigate } from 'react-router-dom';
import { packagingText, quantityFromInput, quantityIsValid, totalWeight } from '../lib/packaging';
import { downloadApiFile } from '../lib/api';
import { stackCodes } from '../lib/warehouses';

const CONSIGNMENT_DESTINATIONS = ['Gudang E-commerce', 'Gudang Bazar'];
const CONSIGNMENT_ZONES = ['18/A01', '18/A02', '18/A03', '18/A04', '18/B01 (½)', '18/B02 (½)', '18/B03 (½)', '18/B04 (½)'];
const DAMAGED_AREA = 'AREA BARANG RUSAK';
const emptyRow = () => ({ productId: '', inputMode: 'QTY', inputValue: 1, qty: 1, goodQty: 1, damagedQty: 0, exp: '', stackCode: '', documentNo: '', channel: '' });

const CatatStok = ({ panel = '' }) => {
  const { products, suppliers, purchaseOrders, settings, stackAllocations, transactions, supplierReturns, addReceipt, createOutboundLoad, recordStockDamage, createSupplierReturn, receiveSupplierReplacement, canInbound, canOutbound } = useData();
  const STACKS = stackCodes(settings?.warehouses);
  const navigate = useNavigate();
  const activePanel = panel;
  const [type, setType] = useState(canOutbound ? 'KELUAR' : 'MASUK');
  const [rows, setRows] = useState([emptyRow()]);
  const [poId, setPoId] = useState('');
  const [party, setParty] = useState('');
  const [ref, setRef] = useState('');
  const [polisi, setPolisi] = useState('');
  const [pengambil, setPengambil] = useState('');
  const [kondisi, setKondisi] = useState('BAIK');
  const [ket, setKet] = useState('');
  const [documentType, setDocumentType] = useState('SO');
  const [transferScope, setTransferScope] = useState('');
  const [documentRefs, setDocumentRefs] = useState(['']);
  const [dispatchPurpose, setDispatchPurpose] = useState('LAINNYA');
  const [consignmentDestination, setConsignmentDestination] = useState('');
  const [consignmentZone, setConsignmentZone] = useState('');
  const [saving, setSaving] = useState(false);
  const [weighingForm, setWeighingForm] = useState(false);
  const [grossWeight, setGrossWeight] = useState('');
  const [grossMin, setGrossMin] = useState('');
  const [grossMax, setGrossMax] = useState('');
  const [damageForm, setDamageForm] = useState(null);
  const [supplierClaimForm, setSupplierClaimForm] = useState(null);
  const [feeChargeMode, setFeeChargeMode] = useState('PENGAMBIL');

  useEffect(() => {
    if (activePanel === 'damage' && !damageForm) setDamageForm({ productId: '', stackCode: '', qty: '', channel: 'KOM', cause: '', note: '', referenceNo: '' });
    if (activePanel === 'supplier-return' && !supplierClaimForm) setSupplierClaimForm({ productId: '', qty: '', channel: 'KOM', supplier: '', sourceDamageOperationId: '', sourceStackCode: '', poNo: '', returnNo: '', note: '' });
  }, [activePanel, damageForm, supplierClaimForm]);

  const activePOs = useMemo(
    () => purchaseOrders.filter((po) => !['Selesai', 'Diterima', 'Dibatalkan', 'Diterima Sebagian · Sisa Dibatalkan'].includes(po.status)),
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
    setDocumentType('SO');
    setTransferScope('');
    setDocumentRefs(['']);
    setDispatchPurpose('LAINNYA');
    setConsignmentDestination('');
    setConsignmentZone('');
    setWeighingForm(false);
    setGrossWeight('');
    setGrossMin('');
    setGrossMax('');
    setFeeChargeMode(nextType === 'MASUK' ? 'PENGIRIM' : 'PENGAMBIL');
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
        goodQty: Math.max(Number(item.qty || 0) - Number(item.receivedQty || 0), 0),
        damagedQty: 0,
        exp: '',
        channel: item.channel || products.find((product) => product.id === item.productId)?.channel || 'KOM',
      }))
      .filter((item) => item.productId && item.qty > 0);
    setParty(po.supplier || '');
    setRef(po.no || '');
    setRows(remainingItems.length ? remainingItems : [emptyRow()]);
  };

  const receiptQty = (row) => Number(row.goodQty || 0) + Number(row.damagedQty || 0);
  const chosen = rows
    .map((row) => ({ ...row, qty: type === 'MASUK' ? receiptQty(row) : row.qty, product: products.find((product) => product.id === row.productId) }))
    .filter((row) => row.product);

  const totalUnit = chosen.reduce((a, row) => a + Number(row.qty || 0), 0);
  const totalBerat = chosen.reduce((a, row) => a + (row.product.weight || 0) * Number(row.qty || 0), 0);
  const totalNilai = chosen.reduce((a, row) => a + (row.product.cost || 0) * Number(row.qty || 0), 0);
  const outboundDocumentRefs = documentRefs.map((item) => item.trim()).filter(Boolean);
  const isMultiDocumentOutbound = type === 'KELUAR' && outboundDocumentRefs.length > 1;
  const productOptions = type === 'KELUAR' && kondisi === 'RUSAK'
    ? products.filter((item) => Number(item.damaged || 0) > 0)
    : products;
  const availableStacksFor = (productId) => (stackAllocations || [])
    .filter((allocation) => allocation.productId === productId && Number(allocation.primaryQty || 0) > 0)
    .sort((a, b) => String(a.stackCode || '').localeCompare(String(b.stackCode || '')));

  const remainingFor = (productId) => {
    if (!selectedPO) return null;
    const item = (selectedPO.items || []).find((poItem) => poItem.productId === productId);
    if (!item) return 0;
    return Math.max(Number(item.qty || 0) - Number(item.receivedQty || 0), 0);
  };
  const damageStacks = (stackAllocations || []).filter((allocation) => allocation.productId === damageForm?.productId && Number(allocation.primaryQty || 0) > 0);
  const saveDamageDiscovery = async () => {
    if (!damageForm?.productId || !damageForm?.stackCode || Number(damageForm.qty) <= 0 || !damageForm.cause?.trim()) return toast.error('Pilih produk, tumpukan, jumlah, dan penyebab kerusakan');
    setSaving(true);
    try {
      await recordStockDamage({ ...damageForm, qty: Number(damageForm.qty), cause: damageForm.cause.trim(), note: damageForm.note || '', referenceNo: damageForm.referenceNo || '' });
      toast.success('Temuan kerusakan tercatat. Barang dipindahkan ke stok rusak.');
      setDamageForm(null);
      navigate('/catat');
    } catch (e) { toast.error(e?.response?.data?.detail || 'Gagal mencatat kerusakan'); } finally { setSaving(false); }
  };
  const damageSources = (transactions || []).filter((tx) => tx.kondisi === 'RUSAK' && (tx.document_type === 'TEMUAN_RUSAK' || tx.type === 'MASUK') && Number(tx.damaged_change ?? tx.change ?? 0) > 0);
  const claimProduct = products.find((p) => p.id === supplierClaimForm?.productId);
  const claimSources = damageSources.filter((tx) => tx.product === claimProduct?.name);
  const claimSource = claimSources.find((tx) => tx.operation_id === supplierClaimForm?.sourceDamageOperationId);
  const openClaims = (supplierReturns || []).filter((claim) => claim.status !== 'SELESAI_DIGANTI');
  const saveSupplierReturn = async () => {
    if (!supplierClaimForm?.productId || Number(supplierClaimForm.qty) <= 0) return toast.error('Pilih produk dan jumlah yang diretur');
    setSaving(true);
    try { await createSupplierReturn({ ...supplierClaimForm, qty: Number(supplierClaimForm.qty), sourceStackCode: claimSource?.stackCode || supplierClaimForm.sourceStackCode || '' }); toast.success('Retur rusak ke pemasok dicatat. Menunggu barang pengganti.'); setSupplierClaimForm(null); navigate('/catat'); } catch (e) { toast.error(e?.response?.data?.detail || 'Gagal menyimpan retur pemasok'); } finally { setSaving(false); }
  };
  const saveReplacement = async (claim) => {
    const qty = window.prompt(`Jumlah barang baik pengganti untuk ${claim.return_no} (sisa ${formatNum(Number(claim.qty) - Number(claim.replacement_qty || 0))} ${claim.unit})`);
    if (!qty || Number(qty) <= 0) return;
    const stackCode = window.prompt('Tumpukan tujuan barang pengganti, contoh 19/A02');
    if (!stackCode) return;
    setSaving(true);
    try { await receiveSupplierReplacement(claim.id, { qty: Number(qty), stackCode, referenceNo: '', note: '' }); toast.success('Barang pengganti masuk sebagai stok baik.'); } catch (e) { toast.error(e?.response?.data?.detail || 'Gagal mencatat barang pengganti'); } finally { setSaving(false); }
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
    if (weighingForm && (Number(grossWeight) <= 0 || Number(grossMin) <= 0 || Number(grossMax) <= 0)) {
      toast.error('Isi rata-rata bruto serta rentang timbang');
      return;
    }
    if (weighingForm && (Number(grossWeight) < Number(grossMin) || Number(grossWeight) > Number(grossMax))) {
      toast.error('Rata-rata bruto harus berada di dalam rentang timbang');
      return;
    }
    if (!party.trim()) {
      toast.error(type === 'MASUK' ? 'Pilih supplier pengirim' : 'Isi penerima barang');
      return;
    }
    if (type === 'KELUAR' && (documentRefs.some((item) => !item.trim()) || outboundDocumentRefs.length !== documentRefs.length)) {
      toast.error('Lengkapi semua nomor SO/CT/TM/Memo');
      return;
    }
    if (type === 'KELUAR' && new Set(outboundDocumentRefs).size !== outboundDocumentRefs.length) {
      toast.error('Nomor dokumen tidak boleh sama');
      return;
    }
    if (type === 'KELUAR' && (isMultiDocumentOutbound
      ? chosen.some((row) => !row.documentNo || !outboundDocumentRefs.includes(row.documentNo))
      : chosen.some((row) => row.documentNo && !outboundDocumentRefs.includes(row.documentNo)))) {
      toast.error('Pilih dokumen sumber pada setiap komoditas');
      return;
    }
    if (type === 'KELUAR' && isMultiDocumentOutbound) {
      const withoutItems = outboundDocumentRefs.filter((doc) => !chosen.some((row) => row.documentNo === doc));
      if (withoutItems.length) {
        toast.error(`Dokumen belum memiliki komoditas: ${withoutItems.join(', ')}`);
        return;
      }
    }
    if (type === 'KELUAR' && kondisi === 'BAIK' && (chosen.length > 1 || isMultiDocumentOutbound) && chosen.some((row) => !row.stackCode)) {
      toast.error('Pilih tumpukan asal pada setiap barang untuk pemuatan multi-SO/multi-produk');
      return;
    }
    if (type === 'KELUAR' && ['MEMO', 'ND'].includes(documentType) && consignmentDestination && !consignmentZone) {
      toast.error('Pilih zona konsinyasi Unit 18 untuk Gudang E-commerce/Bazar');
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
          items: chosen.map((row) => ({ productId: row.productId, qty: Number(row.qty), goodQty: Number(row.goodQty || 0), damagedQty: Number(row.damagedQty || 0), exp: row.exp || '', stackCode: row.stackCode || row.product.location || '', channel: row.channel || row.product.channel || 'KOM' })),
          party,
          ref,
          polisi,
          keterangan: ket,
          weighingForm,
          grossWeight: Number(grossWeight || 0),
          grossMin: Number(grossMin || 0),
          grossMax: Number(grossMax || 0),
          unloadingFeeChargeMode: feeChargeMode,
        });
        const poStatus = result?.purchaseOrder?.status;
        toast.success(poStatus ? `Penerimaan tersimpan · Status PO: ${poStatus}` : 'Stok masuk tersimpan');
        if (weighingForm && result?.operationId) await downloadApiFile(`/export/weighing-form/inbound/${result.operationId}.pdf`, `form_timbangan_masuk_${result.operationId}.pdf`);
        navigate('/riwayat');
      } else {
        const load = await createOutboundLoad({
          items: chosen.map((row) => ({ productId: row.productId, qty: Number(row.qty), documentNo: row.documentNo || documentRefs[0], stackCode: kondisi === 'RUSAK' ? '' : (row.stackCode || ''), channel: row.channel || row.product.channel || 'KOM' })),
          party: party.trim(),
          ref: documentRefs[0],
          polisi,
          pengambil,
          kondisi,
          keterangan: ket,
          documentType,
          transferScope,
          documents: documentRefs.filter(Boolean),
          dispatchPurpose,
          consignmentDestination,
          consignmentZone,
          weighingForm,
          grossWeight: Number(grossWeight || 0),
          grossMin: Number(grossMin || 0),
          grossMax: Number(grossMax || 0),
          loadingFeeChargeMode: feeChargeMode,
        });
        toast.success(`Antrian ${load.antrian} dibuat${kondisi === 'RUSAK' ? ` dari ${DAMAGED_AREA}` : ''}. Stok belum berkurang sampai pemuatan selesai.`);
        if (weighingForm) await downloadApiFile(`/export/weighing-form/outbound/${load.id}.pdf`, `form_timbangan_keluar_${load.antrian}.pdf`);
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
        <h1 className="font-display text-4xl font-bold">{activePanel === 'damage' ? 'Temuan Kerusakan' : activePanel === 'supplier-return' ? 'Retur / Ganti Pemasok' : 'Pencatatan Stok Keluar / Masuk'}</h1>
        {!activePanel && <p className="text-[#8b93a1] mt-2 max-w-3xl">Penerimaan langsung menambah stok. Pengeluaran membuat antrian pemuatan terlebih dahulu; stok baru berkurang setelah proses muat selesai.</p>}
      </div>

      {activePanel === 'damage' && damageForm && <div className="card-surface p-5 border border-[#7f1d1d]"><div className="flex items-start justify-between gap-3"><div><h2 className="font-display text-xl font-bold text-[#fecaca]">Temuan Kerusakan Stok</h2><p className="text-xs text-[#fca5a5] mt-1">Stok baik pada tumpukan akan dipindahkan ke saldo stok rusak dan tetap dapat dikeluarkan lewat SO kondisi rusak.</p></div><button onClick={() => { setDamageForm(null); navigate('/catat'); }} className="text-[#fca5a5]">×</button></div><div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4"><div><label className="text-xs text-[#fca5a5] block mb-1">Produk</label><select value={damageForm.productId} onChange={(e) => setDamageForm({ ...damageForm, productId: e.target.value, stackCode: '', channel: products.find((p) => p.id === e.target.value)?.channel || 'KOM' })} className="w-full bg-[#0b0f17] border border-[#5b2430] rounded-lg px-3 py-2.5"><option value="">Pilih produk...</option>{products.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}</select></div><div><label className="text-xs text-[#fca5a5] block mb-1">Tumpukan asal</label><select value={damageForm.stackCode} onChange={(e) => setDamageForm({ ...damageForm, stackCode: e.target.value })} className="w-full bg-[#0b0f17] border border-[#5b2430] rounded-lg px-3 py-2.5"><option value="">Pilih tumpukan...</option>{damageStacks.map((allocation) => <option key={allocation.id} value={allocation.stackCode}>{allocation.stackCode} — tersedia {formatNum(allocation.primaryQty)} {allocation.unit}</option>)}</select></div><div><label className="text-xs text-[#fca5a5] block mb-1">Jumlah rusak</label><input type="number" min="0.01" step="any" value={damageForm.qty} onChange={(e) => setDamageForm({ ...damageForm, qty: e.target.value })} className="w-full bg-[#0b0f17] border border-[#5b2430] rounded-lg px-3 py-2.5" /></div><div><label className="text-xs text-[#fca5a5] block mb-1">Penyebab</label><input value={damageForm.cause} onChange={(e) => setDamageForm({ ...damageForm, cause: e.target.value })} placeholder="Bocor, basah, hama, kemasan robek..." className="w-full bg-[#0b0f17] border border-[#5b2430] rounded-lg px-3 py-2.5" /></div><div><label className="text-xs text-[#fca5a5] block mb-1">Saluran</label><select value={damageForm.channel} onChange={(e) => setDamageForm({ ...damageForm, channel: e.target.value })} className="w-full bg-[#0b0f17] border border-[#5b2430] rounded-lg px-3 py-2.5"><option value="PSO">PSO</option><option value="KOM">KOM</option></select></div><div><label className="text-xs text-[#fca5a5] block mb-1">No. BA / Referensi</label><input value={damageForm.referenceNo} onChange={(e) => setDamageForm({ ...damageForm, referenceNo: e.target.value })} placeholder="Opsional" className="w-full bg-[#0b0f17] border border-[#5b2430] rounded-lg px-3 py-2.5" /></div></div><textarea rows={2} value={damageForm.note} onChange={(e) => setDamageForm({ ...damageForm, note: e.target.value })} placeholder="Keterangan tambahan (opsional)" className="w-full mt-3 bg-[#0b0f17] border border-[#5b2430] rounded-lg px-3 py-2.5" /><button disabled={saving} onClick={saveDamageDiscovery} className="mt-3 px-4 py-2.5 rounded-lg bg-[#dc2626] text-white font-semibold text-sm disabled:opacity-50">{saving ? 'Menyimpan...' : 'Simpan Temuan Kerusakan'}</button></div>}

      {activePanel === 'supplier-return' && supplierClaimForm && <div className="card-surface p-5 border border-[#92400e]"><div className="flex items-start justify-between gap-3"><div><h2 className="font-display text-xl font-bold text-[#fde68a]">Retur & Penggantian Pemasok</h2><p className="text-xs text-[#fcd34d] mt-1">Pilih sumber penerimaan rusak atau temuan kerusakan. Retur mengurangi stok rusak; penggantian masuk sebagai stok baik tanpa menambah jumlah PO.</p></div><button onClick={() => navigate('/catat')} className="text-[#fde68a]">×</button></div><div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4"><div><label className="text-xs text-[#fcd34d] block mb-1">Produk rusak</label><select value={supplierClaimForm.productId} onChange={(e) => setSupplierClaimForm({ ...supplierClaimForm, productId: e.target.value, sourceDamageOperationId: '', channel: products.find((p) => p.id === e.target.value)?.channel || 'KOM' })} className="w-full bg-[#0b0f17] border border-[#6b4b1c] rounded-lg px-3 py-2.5"><option value="">Pilih produk...</option>{products.filter((p) => Number(p.damaged || 0) > 0).map((p) => <option key={p.id} value={p.id}>{p.name} — rusak {formatNum(p.damaged)} {p.unit}</option>)}</select></div><div><label className="text-xs text-[#fcd34d] block mb-1">Sumber barang rusak</label><select value={supplierClaimForm.sourceDamageOperationId} onChange={(e) => setSupplierClaimForm({ ...supplierClaimForm, sourceDamageOperationId: e.target.value })} className="w-full bg-[#0b0f17] border border-[#6b4b1c] rounded-lg px-3 py-2.5"><option value="">Saldo rusak umum / tanpa tautan</option>{claimSources.map((tx) => <option key={`${tx.operation_id}-${tx.id}`} value={tx.operation_id}>{tx.document_type === 'TEMUAN_RUSAK' ? 'Temuan Rusak' : 'Penerimaan Rusak'} · {tx.ref} · {formatNum(Number(tx.damaged_change ?? tx.change))} {tx.unit}</option>)}</select></div><div><label className="text-xs text-[#fcd34d] block mb-1">Jumlah diretur</label><input type="number" min="0.01" step="any" value={supplierClaimForm.qty} onChange={(e) => setSupplierClaimForm({ ...supplierClaimForm, qty: e.target.value })} className="w-full bg-[#0b0f17] border border-[#6b4b1c] rounded-lg px-3 py-2.5" /></div><div><label className="text-xs text-[#fcd34d] block mb-1">Supplier / pabrik</label><input value={supplierClaimForm.supplier} onChange={(e) => setSupplierClaimForm({ ...supplierClaimForm, supplier: e.target.value })} placeholder="Nama pemasok" className="w-full bg-[#0b0f17] border border-[#6b4b1c] rounded-lg px-3 py-2.5" /></div><div><label className="text-xs text-[#fcd34d] block mb-1">No. PO</label><input value={supplierClaimForm.poNo} onChange={(e) => setSupplierClaimForm({ ...supplierClaimForm, poNo: e.target.value })} placeholder="PO/... (opsional)" className="w-full bg-[#0b0f17] border border-[#6b4b1c] rounded-lg px-3 py-2.5" /></div><div><label className="text-xs text-[#fcd34d] block mb-1">No. Retur Pemasok</label><input value={supplierClaimForm.returnNo} onChange={(e) => setSupplierClaimForm({ ...supplierClaimForm, returnNo: e.target.value })} placeholder="Otomatis bila kosong" className="w-full bg-[#0b0f17] border border-[#6b4b1c] rounded-lg px-3 py-2.5" /></div></div><textarea rows={2} value={supplierClaimForm.note} onChange={(e) => setSupplierClaimForm({ ...supplierClaimForm, note: e.target.value })} placeholder="Catatan retur (opsional)" className="w-full mt-3 bg-[#0b0f17] border border-[#6b4b1c] rounded-lg px-3 py-2.5" /><button disabled={saving} onClick={saveSupplierReturn} className="mt-3 px-4 py-2.5 rounded-lg bg-[#d97706] text-white font-semibold text-sm disabled:opacity-50">{saving ? 'Menyimpan...' : 'Simpan Retur ke Pemasok'}</button><div className="mt-5 border-t border-[#6b4b1c] pt-4"><div className="text-sm font-semibold">Menunggu barang pengganti</div>{openClaims.length === 0 ? <p className="text-xs text-[#a99675] mt-2">Belum ada retur pemasok terbuka.</p> : <div className="space-y-2 mt-2">{openClaims.map((claim) => <div key={claim.id} className="flex flex-wrap justify-between gap-2 rounded-lg bg-[#0b0f17] p-3 text-xs"><div><b>{claim.return_no}</b> · {claim.product}<br/><span className="text-[#a99675]">Retur {formatNum(claim.qty)} {claim.unit} · sudah diganti {formatNum(claim.replacement_qty || 0)} · {claim.status}</span></div><button disabled={saving} onClick={() => saveReplacement(claim)} className="px-3 py-1.5 rounded border border-[#22c55e] text-[#4ade80]">Catat Barang Pengganti</button></div>)}</div>}</div></div>}

      <div className={`grid grid-cols-1 lg:grid-cols-3 gap-6 ${activePanel ? 'hidden' : ''}`}>
        <div className="card-surface p-6 lg:col-span-2">
          <h2 className="font-display text-lg font-bold mb-4">Formulir Transaksi</h2>
          <div className={`grid ${canInbound && canOutbound ? 'grid-cols-2' : 'grid-cols-1'} gap-2 mb-5 p-1 bg-[#0b0f17] rounded-xl border border-[#1a222e]`}>
            {canOutbound && <button onClick={() => chooseType('KELUAR')} className={`flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold ${type === 'KELUAR' ? 'bg-[#ef4444]/15 text-[#ef4444]' : 'text-[#8b93a1]'}`}><ArrowUpRight size={16} /> Stok Keluar</button>}
            {canInbound && <button onClick={() => chooseType('MASUK')} className={`flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold ${type === 'MASUK' ? 'bg-[#22c55e]/15 text-[#22c55e]' : 'text-[#8b93a1]'}`}><ArrowDownLeft size={16} /> Stok Masuk</button>}
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
            <div className="mb-5 p-4 rounded-xl border border-[#5a3b15] bg-[#1a1208]">
              <div className="flex gap-3"><Truck size={18} className="text-[#f59e0b] shrink-0 mt-0.5" /><div><div className="text-sm font-semibold text-[#fbbf24]">Tahap Persiapan Pemuatan</div><p className="text-xs text-[#a99675] mt-1">ND dan Memo adalah jalur dokumen yang terpisah. Keduanya dapat digunakan untuk Bazar, E-commerce, peminjaman, atau keperluan lain.</p></div></div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4"><div><label className="text-xs text-[#a99675] block mb-1">Jenis Dokumen</label><select value={documentType} onChange={(e) => { const next = e.target.value; setDocumentType(next); if (next !== 'TM') setTransferScope(''); if (!['MEMO', 'ND'].includes(next)) { setConsignmentDestination(''); setConsignmentZone(''); setDispatchPurpose('LAINNYA'); } }} className="w-full bg-[#0b0f17] border border-[#59431f] rounded-lg px-3 py-2.5 text-sm"><option value="SO">SO — Penjualan</option><option value="TM">TM — Transfer Move</option><option value="CT">CT — Konsinyasi</option><option value="ND">ND — Nota Dinas</option><option value="MEMO">Memo — Pengeluaran Memo</option></select></div>{documentType === 'TM' && <div><label className="text-xs text-[#a99675] block mb-1">Cakupan Transfer</label><select value={transferScope} onChange={(e) => setTransferScope(e.target.value)} className="w-full bg-[#0b0f17] border border-[#59431f] rounded-lg px-3 py-2.5 text-sm"><option value="">Pilih cakupan...</option><option value="LOKAL">Antar Gudang Lokal</option><option value="REGIONAL">Regional</option><option value="NASIONAL">Nasional</option></select></div>}</div>
              <div className="mt-3"><div className="flex items-center justify-between mb-1"><label className="text-xs text-[#a99675]">Nomor Dokumen (satu kendaraan dapat membawa beberapa dokumen)</label><button type="button" onClick={() => setDocumentRefs((prev) => [...prev, ''])} className="text-xs text-[#60a5fa]">+ Tambah dokumen</button></div>{documentRefs.map((doc, index) => <div key={index} className="flex gap-2 mt-2"><input value={doc} onChange={(e) => { const next = [...documentRefs]; next[index] = e.target.value; setDocumentRefs(next); }} placeholder={documentType === 'SO' ? 'SO/xxxx/mm/09001' : `${documentType}/...`} className="flex-1 bg-[#0b0f17] border border-[#59431f] rounded-lg px-3 py-2.5 text-sm" />{documentRefs.length > 1 && <button type="button" onClick={() => { const removed = doc.trim(); setDocumentRefs((prev) => prev.filter((_, i) => i !== index)); if (removed) setRows((prev) => prev.map((row) => row.documentNo === removed ? { ...row, documentNo: '' } : row)); }} className="px-3 rounded-lg border border-[#59431f] text-[#f59e0b]">×</button>}</div>)}<p className="text-[11px] text-[#a99675] mt-2">Bila ada lebih dari satu nomor dokumen, pilih dokumen sumber pada setiap baris komoditas. Setiap dokumen harus memiliki minimal satu komoditas.</p></div>
          {['MEMO', 'ND'].includes(documentType) && <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3 rounded-lg border border-[#1f3657] bg-[#0d1728] p-3"><div><label className="text-xs text-[#93c5fd] block mb-1">Keperluan {documentType}</label><select value={dispatchPurpose} onChange={(e) => { const purpose = e.target.value; const destination = purpose === 'BAZAR' ? 'Gudang Bazar' : purpose === 'ECOMMERCE' ? 'Gudang E-commerce' : ''; setDispatchPurpose(purpose); setConsignmentDestination(destination); setConsignmentZone(''); if (destination) setParty(destination); }} className="w-full bg-[#0b0f17] border border-[#2b3b52] rounded-lg px-3 py-2.5 text-sm"><option value="BAZAR">Gudang Bazar</option><option value="ECOMMERCE">Gudang E-commerce</option><option value="PEMINJAMAN">Peminjaman</option><option value="LAINNYA">Keperluan lain</option></select></div><div><label className="text-xs text-[#93c5fd] block mb-1">Zona Unit 18</label><select value={consignmentZone} onChange={(e) => setConsignmentZone(e.target.value)} disabled={!consignmentDestination} className="w-full bg-[#0b0f17] border border-[#2b3b52] rounded-lg px-3 py-2.5 text-sm disabled:opacity-50"><option value="">{consignmentDestination ? 'Pilih zona...' : 'Tidak diperlukan'}</option>{CONSIGNMENT_ZONES.map((zone) => <option key={zone}>{zone}</option>)}</select></div><p className="sm:col-span-2 text-[11px] text-[#8fb8ef]">{documentType} berdiri sendiri. Bila tujuannya Bazar/E-commerce, saldo dipisahkan sebagai stok Unit 18 dan kemudian dapat ditautkan ke SO atau Retur.</p></div>}
            </div>
          )}

          <div className="mb-5 rounded-xl border border-[#294263] bg-[#0d1728] p-4">
            <div className="text-sm font-semibold">Penagihan biaya {type === 'MASUK' ? 'bongkar' : 'muat'}</div>
            <p className="text-xs text-[#8fb8ef] mt-1">Pilih apakah biaya operasional ditagihkan terpisah, atau sudah termasuk pada harga/dokumen.</p>
            <select value={feeChargeMode} onChange={(e) => setFeeChargeMode(e.target.value)} className="w-full mt-3 bg-[#0b0f17] border border-[#2b3b52] rounded-lg px-3 py-2.5 text-sm">
              {type === 'MASUK' ? <><option value="PENGIRIM">Ditagihkan kepada pengirim</option><option value="TERMASUK">Tidak ditagihkan — sudah termasuk biaya dokumen</option></> : <><option value="PENGAMBIL">Ditagihkan kepada pengambil</option><option value="TERMASUK">Tidak ditagihkan — sudah termasuk biaya SO</option></>}
            </select>
          </div>

          <div className="mb-5 rounded-xl border border-[#294263] bg-[#0d1728] p-4">
            <label className="flex items-center gap-3 cursor-pointer"><input type="checkbox" checked={weighingForm} onChange={(e) => setWeighingForm(e.target.checked)} className="h-4 w-4 accent-[#2563eb]" /><span><span className="text-sm font-semibold">Buat form timbangan</span><span className="block text-xs text-[#8fb8ef] mt-0.5">Opsional. Sistem mengisi 20 baris bruto dari satu nilai awal.</span></span></label>
            {weighingForm && <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3"><div><label className="text-xs text-[#93c5fd] block mb-1">Rata-rata bruto (kg)</label><input type="number" min="0.01" step="0.01" value={grossWeight} onChange={(e) => setGrossWeight(e.target.value)} placeholder="40.22" className="w-full bg-[#0b0f17] border border-[#2b3b52] rounded-lg px-3 py-2.5 text-sm font-mono" /></div><div><label className="text-xs text-[#93c5fd] block mb-1">Bruto minimum (kg)</label><input type="number" min="0.01" step="0.01" value={grossMin} onChange={(e) => setGrossMin(e.target.value)} placeholder="40.20" className="w-full bg-[#0b0f17] border border-[#2b3b52] rounded-lg px-3 py-2.5 text-sm font-mono" /></div><div><label className="text-xs text-[#93c5fd] block mb-1">Bruto maksimum (kg)</label><input type="number" min="0.01" step="0.01" value={grossMax} onChange={(e) => setGrossMax(e.target.value)} placeholder="40.32" className="w-full bg-[#0b0f17] border border-[#2b3b52] rounded-lg px-3 py-2.5 text-sm font-mono" /></div><p className="sm:col-span-3 text-[11px] text-[#8fb8ef]">20 bruto dibuat bervariasi di dalam rentang. Rata-ratanya tetap tepat sesuai nilai target.</p></div>}
          </div>

          <label className="text-sm font-medium mb-2 block">Daftar Barang</label>
          <div className="space-y-3 mb-3">
            {rows.map((row, index) => {
              const product = products.find((item) => item.id === row.productId);
              const remaining = remainingFor(row.productId);
              const availableStacks = type === 'KELUAR' && kondisi === 'BAIK' ? availableStacksFor(row.productId) : [];
              return (
                <div key={index} className={`grid gap-2 items-end p-3 rounded-lg border border-[#1a222e] bg-[#0b0f17] ${type === 'MASUK' ? 'grid-cols-1 md:grid-cols-[minmax(190px,1fr)_125px_125px_175px_52px]' : 'grid-cols-1 md:grid-cols-[minmax(170px,1fr)_100px_135px_150px_140px_52px]'}`}>
                  <div>
                    <label className="text-[10px] text-[#6b7688] mb-1 block">Produk</label>
                    <select value={row.productId} disabled={Boolean(selectedPO)} onChange={(e) => { const chosenProduct = products.find((item) => item.id === e.target.value); setTransactionInput(index, { productId: e.target.value, inputMode: 'QTY', inputValue: 1, stackCode: '', channel: chosenProduct?.channel || 'KOM' }); }} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb] disabled:opacity-70">
                      <option value="">Pilih produk...</option>
                      {productOptions.map((item) => <option key={item.id} value={item.id}>{item.name} ({kondisi === 'RUSAK' && type === 'KELUAR' ? `Rusak ${formatNum(item.damaged || 0)}` : formatNum(item.stock || 0)} {item.unit})</option>)}
                    </select>
                    {type === 'KELUAR' && kondisi === 'RUSAK' && product && <div className="text-[10px] text-[#fca5a5] mt-1">Saldo Area Barang Rusak: {formatNum(product.damaged || 0)} {product.unit}</div>}
                    {selectedPO && product && <div className="text-[10px] text-[#60a5fa] mt-1">Sisa PO: {formatNum(remaining)} {product.unit}</div>}<label className="text-[10px] text-[#6b7688] mt-2 mb-1 block">Saluran</label><select value={row.channel || product?.channel || 'KOM'} onChange={(e) => setRow(index, { channel: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2 text-xs"><option value="PSO">PSO</option><option value="KOM">KOM</option></select>
                  </div>
                  {type === 'KELUAR' && <div>
                    <label className="text-[10px] text-[#6b7688] mb-1 block">Input Berdasarkan</label>
                    <select value={row.inputMode || 'QTY'} onChange={(e) => setTransactionInput(index, { inputMode: e.target.value, inputValue: e.target.value === 'WEIGHT' ? totalWeight(row.qty, product) : row.qty })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2.5 text-xs outline-none focus:border-[#2563eb]">
                      <option value="QTY">Jumlah</option>
                      <option value="WEIGHT" disabled={!Number(product?.weight || 0)}>Berat</option>
                    </select>
                  </div>}
                  {type === 'MASUK' && <><div><label className="text-[10px] text-[#22c55e] mb-1 block">Baik ({product?.unit || 'unit'})</label><input type="number" min="0" step="any" value={row.goodQty ?? 0} onChange={(e) => setRow(index, { goodQty: e.target.value })} className="w-full bg-[#0b0f17] border border-[#1f6f45] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#22c55e]" /></div><div><label className="text-[10px] text-[#f59e0b] mb-1 block">Rusak ({product?.unit || 'unit'})</label><input type="number" min="0" step="any" value={row.damagedQty ?? 0} onChange={(e) => setRow(index, { damagedQty: e.target.value })} className="w-full bg-[#0b0f17] border border-[#794b1c] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#f59e0b]" />{product && receiptQty(row) > 0 && <div className="text-[9px] text-[#60a5fa] mt-1">Total {formatNum(receiptQty(row))} {product.unit} · {formatNum(totalWeight(receiptQty(row), product))} kg</div>}</div></>}
                  {type === 'KELUAR' && <div>
                    <label className="text-[10px] text-[#6b7688] mb-1 block">{row.inputMode === 'WEIGHT' ? 'Berat (kg)' : `Jumlah (${product?.unit || 'unit'})`}</label>
                    <input type="number" min="0.01" step="any" value={row.inputValue} onChange={(e) => setTransactionInput(index, { inputValue: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" />
                    {product && Number(row.qty || 0) > 0 && <div className="text-[9px] text-[#60a5fa] mt-1">{formatNum(row.qty)} {product.unit} · {formatNum(totalWeight(row.qty, product))} kg{packagingText(row.qty, product, formatNum) ? ` · ${packagingText(row.qty, product, formatNum)}` : ''}</div>}
                  </div>}
                  {type === 'MASUK' && (
                    <div><label className="text-[10px] text-[#6b7688] mb-1 flex items-center gap-1"><CalendarDays size={11} /> Kedaluwarsa / Lokasi</label><input type="date" value={row.exp || ''} onChange={(e) => setRow(index, { exp: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-sm" /><select value={row.stackCode || product?.location || ''} onChange={(e) => setRow(index, { stackCode: e.target.value })} className="w-full mt-1 bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2 text-xs"><option value="">Pilih lokasi...</option>{STACKS.map((code) => <option key={code}>{code}</option>)}</select></div>
                  )}
                  {type === 'KELUAR' && <><div><label className="text-[10px] text-[#6b7688] mb-1 block">Dokumen sumber</label><select value={isMultiDocumentOutbound ? row.documentNo : (row.documentNo || outboundDocumentRefs[0] || '')} disabled={!isMultiDocumentOutbound && outboundDocumentRefs.length === 1} onChange={(e) => setRow(index, { documentNo: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2.5 text-xs disabled:opacity-70"><option value="">{isMultiDocumentOutbound ? 'Pilih dokumen...' : 'Isi nomor dokumen dulu'}</option>{outboundDocumentRefs.map((doc) => <option key={doc}>{doc}</option>)}</select></div><div><label className="text-[10px] text-[#6b7688] mb-1 block">{kondisi === 'RUSAK' ? 'Lokasi sumber' : 'Tumpukan asal · stok tersedia'}</label>{kondisi === 'RUSAK' ? <div className="w-full rounded-lg border border-[#7f1d1d] bg-[#2a0f14] px-3 py-2.5 text-xs text-[#fecaca]"><div className="font-semibold">{DAMAGED_AREA}</div><div className="text-[9px] text-[#fca5a5] mt-1">Tidak memakai tumpukan stok Baik · antrean otomatis seri R-xxx</div></div> : <><select value={row.stackCode || ''} onChange={(e) => setRow(index, { stackCode: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2.5 text-xs"><option value="">{isMultiDocumentOutbound || rows.length > 1 ? "Pilih tumpukan asal (wajib)" : "Otomatis (pilih dari stok tersedia)"}</option>{availableStacks.map((allocation) => { const secondaryQty = Number(allocation.secondaryQty || 0); const qty = Number(allocation.primaryQty || 0); const secondary = secondaryQty > 0 ? Math.floor(qty / secondaryQty) : 0; const remainder = secondaryQty > 0 ? qty - (secondary * secondaryQty) : 0; const packaging = secondaryQty > 0 ? ` · ${formatNum(secondary)} ${allocation.secondary || 'sekunder'}${remainder > 0 ? ` + ${formatNum(remainder)} ${allocation.unit || 'pcs'}` : ''}` : ''; return <option key={allocation.id} value={allocation.stackCode}>{allocation.stackCode} — sisa {formatNum(qty)} {allocation.unit || 'pcs'}{packaging}</option>; })}</select>{row.productId && availableStacks.length === 0 && <p className="text-[9px] text-[#fbbf24] mt-1">Belum ada alokasi tumpukan untuk produk ini; sistem akan menentukan otomatis.</p>}</>}</div></>}
                  <button type="button" onClick={() => delRow(index)} disabled={rows.length === 1} className="w-10 h-[42px] rounded-lg border border-[#242f3d] flex items-center justify-center text-[#ef4444] disabled:opacity-30"><Trash2 size={15} /></button>
                </div>
              );
            })}
          </div>
          {!selectedPO && <button onClick={addRow} className="inline-flex items-center gap-2 text-sm text-[#60a5fa] mb-5"><Plus size={15} /> Tambah Barang</button>}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div><label className="text-sm font-medium mb-1.5 block">{type === 'MASUK' ? 'Supplier Pengirim' : 'Penerima / Tujuan'}</label>{type === 'MASUK' ? <select value={party} disabled={Boolean(selectedPO)} onChange={(e) => setParty(e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm"><option value="">Pilih supplier...</option>{suppliers.map((supplier) => <option key={supplier.id}>{supplier.name}</option>)}</select> : <input value={party} onChange={(e) => setParty(e.target.value)} placeholder="Nama penerima / tujuan" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm" />}</div>
            <div><label className="text-sm font-medium mb-1.5 block">{type === 'MASUK' ? 'No. Referensi' : 'Dokumen Utama'}</label><input value={type === 'KELUAR' ? (documentRefs.filter(Boolean).join(', ') || 'Diisi pada daftar dokumen di atas') : ref} readOnly={type === 'KELUAR' || Boolean(selectedPO)} onChange={(e) => setRef(e.target.value)} placeholder="DO / BAST / referensi lain" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm read-only:opacity-70" /></div>
            <div><label className="text-sm font-medium mb-1.5 block">Nomor Plat Kendaraan</label><input value={polisi} onChange={(e) => setPolisi(e.target.value)} placeholder="B 1441 PQF" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm" /></div>
            {type === 'KELUAR' ? (
              <div><label className="text-sm font-medium mb-1.5 block">Nama Pengambil / Sopir</label><input value={pengambil} onChange={(e) => setPengambil(e.target.value)} placeholder="Contoh: KOYUM" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm" /></div>
            ) : <div className="rounded-lg border border-[#1f3657] bg-[#0d1728] px-3 py-2.5 text-xs text-[#8fb8ef]">Isi kuantum <b>Baik</b> dan <b>Rusak</b> pada setiap komoditas.</div>}
            {type === 'KELUAR' && <div><label className="text-sm font-medium mb-1.5 block">Kondisi Barang</label><select value={kondisi} onChange={(e) => { const next = e.target.value; setKondisi(next); if (next === 'RUSAK') setRows((prev) => prev.map((row) => ({ ...row, stackCode: '' }))); }} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm"><option value="BAIK">Baik (Good)</option><option value="RUSAK">Rusak (Damage)</option></select>{kondisi === 'RUSAK' && <p className="text-[10px] text-[#fca5a5] mt-1">Sumber fisik otomatis: {DAMAGED_AREA} · antrean R-xxx.</p>}</div>}
          </div>
          <div className="mt-4"><label className="text-sm font-medium mb-1.5 block">Keterangan</label><textarea value={ket} onChange={(e) => setKet(e.target.value)} rows={2} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm resize-none" /></div>
          <button onClick={submit} disabled={saving} className="btn-primary w-full mt-5 flex items-center justify-center gap-2 py-3 rounded-lg font-semibold text-sm disabled:opacity-60"><Save size={16} /> {saving ? 'Menyimpan…' : type === 'MASUK' ? 'Simpan Stok Masuk' : 'Buat Antrian Pemuatan'}</button>
        </div>

        <div className="card-surface p-6 h-fit">
          <h2 className="font-display text-lg font-bold mb-4">Ringkasan</h2>
          <span className="text-xs px-2.5 py-1 rounded-full font-semibold" style={{ background: type === 'MASUK' ? 'rgba(34,197,94,.15)' : 'rgba(239,68,68,.15)', color: type === 'MASUK' ? '#22c55e' : '#ef4444' }}>{type}</span>
          <div className="mt-5 space-y-3 text-sm">{[['Jenis barang', chosen.length], ['Total unit', formatNum(totalUnit)], ['Total berat', `${totalBerat.toFixed(2)} kg`], ['Estimasi nilai', formatRp(totalNilai)]].map(([label, value]) => <div key={label} className="flex justify-between border-b border-[#151d28] pb-3"><span className="text-[#8b93a1]">{label}</span><span className="font-mono font-semibold">{value}</span></div>)}</div>
          {type === 'KELUAR' && kondisi === 'RUSAK' && <div className="mt-4 rounded-lg border border-[#7f1d1d] bg-[#2a0f14] p-3 text-xs text-[#fecaca]"><div className="flex justify-between gap-3"><span>Lokasi sumber</span><strong>{DAMAGED_AREA}</strong></div><div className="mt-1 text-[#fca5a5]">Nomor antrean akan memakai seri R-xxx.</div></div>}
          {type === 'KELUAR' && <div className="mt-4 p-3 rounded-lg bg-[#0d1728] border border-[#1f3657] text-xs text-[#8fb8ef]">Setelah antrian dibuat, stok fisik tetap sama sampai pemuatan dinyatakan selesai.</div>}
        </div>
      </div>
    </div>
  );
};

export default CatatStok;
