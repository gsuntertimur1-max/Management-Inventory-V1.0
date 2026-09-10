import React, { useMemo, useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, Plus, Trash2, Save, ClipboardList, CalendarDays } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatRp, formatNum } from '../mock';
import { toast } from 'sonner';
import { useNavigate } from 'react-router-dom';

const emptyRow = () => ({ productId: '', qty: 1, exp: '' });

const CatatStok = () => {
  const { products, suppliers, purchaseOrders, addTransaction, addReceipt, canWrite } = useData();
  const navigate = useNavigate();
  const [type, setType] = useState('MASUK');
  const [rows, setRows] = useState([emptyRow()]);
  const [poId, setPoId] = useState('');
  const [party, setParty] = useState('');
  const [ref, setRef] = useState('');
  const [polisi, setPolisi] = useState('');
  const [kondisi, setKondisi] = useState('BAIK');
  const [ket, setKet] = useState('');
  const [saving, setSaving] = useState(false);

  const activePOs = useMemo(
    () => purchaseOrders.filter((po) => po.status !== 'Selesai' && po.status !== 'Diterima'),
    [purchaseOrders],
  );
  const selectedPO = purchaseOrders.find((po) => po.id === poId);

  const switchType = (nextType) => {
    setType(nextType);
    setRows([emptyRow()]);
    setPoId('');
    setParty('');
    setRef('');
    setKondisi('BAIK');
  };

  const setRow = (index, patch) => setRows((prev) => prev.map((row, i) => i === index ? { ...row, ...patch } : row));
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
    if (chosen.length === 0) {
      toast.error('Pilih minimal satu produk');
      return;
    }
    if (chosen.some((row) => Number(row.qty) <= 0)) {
      toast.error('Jumlah barang harus lebih dari 0');
      return;
    }
    if (!party) {
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
          items: chosen.map((row) => ({
            productId: row.productId,
            qty: Number(row.qty),
            exp: row.exp || '',
          })),
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
        await addTransaction({
          type,
          items: chosen.map((row) => ({ productId: row.productId, qty: Number(row.qty) })),
          party,
          ref,
          polisi,
          kondisi,
          keterangan: ket,
        });
        toast.success('Surat jalan dibuat & stok keluar tersimpan');
        navigate('/pengeluaran');
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Gagal menyimpan transaksi');
    } finally {
      setSaving(false);
    }
  };

  if (!canWrite) {
    return (
      <div className="space-y-6">
        <div>
          <div className="label-mono mb-2">Operasional Gudang</div>
          <h1 className="font-display text-4xl font-bold">Pencatatan Stok Masuk / Keluar</h1>
        </div>
        <div className="card-surface p-8 text-center" data-testid="readonly-notice">
          <p className="text-[#8b93a1]">Peran <span className="text-white font-semibold">Pemantau</span> hanya dapat melihat data. Hubungi Administrator untuk akses pencatatan stok.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <div className="label-mono mb-2">Operasional Gudang</div>
        <h1 className="font-display text-4xl font-bold">Pencatatan Stok Masuk / Keluar</h1>
        <p className="text-[#8b93a1] mt-2 max-w-3xl">Stok baru berubah saat transaksi fisik disimpan. Penerimaan dapat dikaitkan ke Purchase Order dan mencatat tanggal kedaluwarsa setiap barang.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="card-surface p-6 lg:col-span-2">
          <h2 className="font-display text-lg font-bold mb-4">Formulir Transaksi</h2>
          <div className="grid grid-cols-2 gap-2 mb-5 p-1 bg-[#0b0f17] rounded-xl border border-[#1a222e]">
            <button data-testid="txn-type-masuk" onClick={() => switchType('MASUK')} className={`flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold transition-colors ${type === 'MASUK' ? 'bg-[#22c55e]/15 text-[#22c55e]' : 'text-[#8b93a1]'}`}><ArrowDownLeft size={16} /> Stok Masuk</button>
            <button data-testid="txn-type-keluar" onClick={() => switchType('KELUAR')} className={`flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold transition-colors ${type === 'KELUAR' ? 'bg-[#ef4444]/15 text-[#ef4444]' : 'text-[#8b93a1]'}`}><ArrowUpRight size={16} /> Stok Keluar</button>
          </div>

          {type === 'MASUK' && (
            <div className="mb-5 p-4 rounded-xl border border-[#1f3657] bg-[#0d1728]">
              <div className="flex items-center gap-2 mb-2"><ClipboardList size={16} className="text-[#60a5fa]" /><label className="text-sm font-semibold">Purchase Order</label></div>
              <select data-testid="receipt-po-select" value={poId} onChange={(e) => choosePO(e.target.value)} className="w-full bg-[#0b0f17] border border-[#2b3b52] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]">
                <option value="">Tanpa PO / Penerimaan langsung</option>
                {activePOs.map((po) => <option key={po.id} value={po.id}>{po.no} · {po.supplier} · {po.status}</option>)}
              </select>
              <p className="text-xs text-[#6b7688] mt-2">Jika memilih PO, barang dan sisa jumlah pesanan akan terisi otomatis. Stok tidak boleh diterima melebihi sisa PO.</p>
            </div>
          )}

          <label className="text-sm font-medium mb-2 block">Daftar Barang</label>
          <div className="space-y-3 mb-3">
            {rows.map((row, index) => {
              const product = products.find((item) => item.id === row.productId);
              const remaining = remainingFor(row.productId);
              return (
                <div key={`${row.productId || 'row'}-${index}`} className={`grid gap-2 items-end p-3 rounded-lg border border-[#1a222e] bg-[#0b0f17] ${type === 'MASUK' ? 'grid-cols-1 md:grid-cols-[1fr_130px_175px_52px]' : 'grid-cols-1 md:grid-cols-[1fr_130px_52px]'}`}>
                  <div>
                    <label className="text-[10px] text-[#6b7688] mb-1 block">Produk</label>
                    <select data-testid={`txn-product-select-${index}`} value={row.productId} disabled={Boolean(selectedPO)} onChange={(e) => setRow(index, { productId: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb] disabled:opacity-70">
                      <option value="">Pilih produk...</option>
                      {products.map((item) => <option key={item.id} value={item.id}>{`${item.name} (${formatNum(item.stock || 0)} ${item.unit})`}</option>)}
                    </select>
                    {selectedPO && product && <div className="text-[10px] text-[#60a5fa] mt-1">Sisa PO: {formatNum(remaining)} {product.unit}</div>}
                  </div>
                  <div>
                    <label className="text-[10px] text-[#6b7688] mb-1 block">Jumlah</label>
                    <div className="flex items-center gap-2">
                      <input data-testid={`txn-qty-input-${index}`} type="number" min="0.01" max={selectedPO ? remaining : undefined} step="any" value={row.qty} onChange={(e) => setRow(index, { qty: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" />
                      <span className="text-xs text-[#6b7688] whitespace-nowrap">{product?.unit || '—'}</span>
                    </div>
                  </div>
                  {type === 'MASUK' && (
                    <div>
                      <label className="text-[10px] text-[#6b7688] mb-1 flex items-center gap-1"><CalendarDays size={11} /> Tanggal Kedaluwarsa</label>
                      <input data-testid={`txn-exp-input-${index}`} type="date" value={row.exp || ''} onChange={(e) => setRow(index, { exp: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" />
                      <div className="text-[9px] text-[#566173] mt-1">Kosongkan jika barang tidak memiliki expired.</div>
                    </div>
                  )}
                  <button type="button" onClick={() => delRow(index)} disabled={rows.length === 1} className="w-10 h-[42px] rounded-lg border border-[#242f3d] flex items-center justify-center text-[#ef4444] hover:bg-[#ef4444]/10 disabled:opacity-30"><Trash2 size={15} /></button>
                </div>
              );
            })}
          </div>
          {!selectedPO && <button onClick={addRow} className="inline-flex items-center gap-2 text-sm text-[#60a5fa] hover:text-[#93c5fd] mb-5"><Plus size={15} /> Tambah Barang</button>}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-1.5 block">{type === 'MASUK' ? 'Supplier Pengirim' : 'Penerima Barang'}</label>
              {type === 'MASUK' ? (
                <select data-testid="txn-party-select" value={party} disabled={Boolean(selectedPO)} onChange={(e) => setParty(e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb] disabled:opacity-70"><option value="">Pilih supplier...</option>{suppliers.map((supplier) => <option key={supplier.id}>{supplier.name}</option>)}</select>
              ) : (
                <input data-testid="txn-party-input" value={party} onChange={(e) => setParty(e.target.value)} placeholder="Nama penerima / toko" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" />
              )}
            </div>
            <div>
              <label className="text-sm font-medium mb-1.5 block">No. Referensi {selectedPO ? '/ PO' : ''}</label>
              <input value={ref} readOnly={Boolean(selectedPO)} onChange={(e) => setRef(e.target.value)} placeholder={type === 'MASUK' ? 'DO / BAST / referensi lain' : 'No. referensi pengeluaran'} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb] read-only:opacity-70" />
            </div>
            <div><label className="text-sm font-medium mb-1.5 block">Nomor Plat Kendaraan</label><input value={polisi} onChange={(e) => setPolisi(e.target.value)} placeholder="B 9021 XY" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
            <div><label className="text-sm font-medium mb-1.5 block">Kondisi Barang</label><select value={kondisi} onChange={(e) => setKondisi(e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]"><option value="BAIK">Baik (Good)</option><option value="RUSAK">Rusak (Damage)</option></select><p className="text-xs text-[#6b7688] mt-1">Stok rusak dicatat terpisah dari stok baik.</p></div>
          </div>
          <div className="mt-4"><label className="text-sm font-medium mb-1.5 block">Keterangan</label><textarea value={ket} onChange={(e) => setKet(e.target.value)} rows={2} placeholder={type === 'MASUK' ? 'Keterangan penerimaan barang...' : 'Muat pagi — truk B 9021 XX...'} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb] resize-none" /></div>
          <button data-testid="txn-submit-btn" onClick={submit} disabled={saving} className="btn-primary w-full mt-5 flex items-center justify-center gap-2 py-3 rounded-lg font-semibold text-sm disabled:opacity-60 disabled:cursor-wait"><Save size={16} /> {saving ? 'Menyimpan…' : `Simpan Stok ${type === 'MASUK' ? 'Masuk' : 'Keluar'}`}</button>
        </div>

        <div className="card-surface p-6 h-fit">
          <h2 className="font-display text-lg font-bold mb-4">Ringkasan Transaksi</h2>
          <span className="text-xs px-2.5 py-1 rounded-full font-semibold" style={{ background: type === 'MASUK' ? 'rgba(34,197,94,.15)' : 'rgba(239,68,68,.15)', color: type === 'MASUK' ? '#22c55e' : '#ef4444' }}>{type}</span>
          {selectedPO && (
            <div className="mt-4 p-3 rounded-lg border border-[#1f3657] bg-[#0d1728] text-xs">
              <div className="text-[#60a5fa] font-semibold">{selectedPO.no}</div>
              <div className="text-[#8b93a1] mt-1">{selectedPO.supplier} · {selectedPO.status}</div>
            </div>
          )}
          <div className="mt-5 space-y-3 text-sm">
            {[['Jenis barang', chosen.length], ['Total unit', formatNum(totalUnit)], ['Total berat', totalBerat.toFixed(2) + ' kg'], ['Estimasi nilai', formatRp(totalNilai)]].map(([label, value]) => (
              <div key={label} className="flex justify-between items-center border-b border-[#151d28] pb-3"><span className="text-[#8b93a1]">{label}</span><span className="font-mono font-semibold">{value}</span></div>
            ))}
          </div>
          {chosen.length === 0 ? <p className="text-xs text-[#6b7688] mt-4">Pilih barang untuk melihat perkiraan stok setelah transaksi.</p> : (
            <div className="mt-4 space-y-2">{chosen.map((row, index) => (
              <div key={`${row.productId}-${index}`} className="text-xs p-2.5 rounded-lg bg-[#0b0f17] border border-[#151d28]">
                <div className="font-medium">{row.product.name}</div>
                <div className="text-[#8b93a1] font-mono">{formatNum(row.product.stock || 0)} → {formatNum(type === 'MASUK' ? Number(row.product.stock || 0) + Number(row.qty || 0) : Number(row.product.stock || 0) - Number(row.qty || 0))} {row.product.unit}</div>
                {type === 'MASUK' && row.exp && <div className="text-[#eab308] mt-1">Exp: {row.exp}</div>}
              </div>
            ))}</div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CatatStok;
