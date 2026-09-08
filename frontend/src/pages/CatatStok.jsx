import React, { useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, Plus, Trash2, Save } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatRp, formatNum } from '../mock';
import { toast } from 'sonner';
import { useNavigate } from 'react-router-dom';

const CatatStok = () => {
  const { products, suppliers, addTransaction, canWrite } = useData();
  const navigate = useNavigate();
  const [type, setType] = useState('MASUK');
  const [rows, setRows] = useState([{ productId: '', qty: 1 }]);
  const [party, setParty] = useState('');
  const [ref, setRef] = useState('');
  const [polisi, setPolisi] = useState('');
  const [kondisi, setKondisi] = useState('BAIK');
  const [ket, setKet] = useState('');

  const setRow = (i, patch) => setRows(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const addRow = () => setRows([...rows, { productId: '', qty: 1 }]);
  const delRow = (i) => setRows(rows.filter((_, idx) => idx !== i));

  const chosen = rows.map((r) => ({ ...r, product: products.find((p) => p.id === r.productId) })).filter((r) => r.product);
  const totalUnit = chosen.reduce((a, r) => a + Number(r.qty), 0);
  const totalBerat = chosen.reduce((a, r) => a + (r.product.weight || 0) * Number(r.qty), 0);
  const totalNilai = chosen.reduce((a, r) => a + r.product.cost * Number(r.qty), 0);

  const submit = async () => {
    if (chosen.length === 0) { toast.error('Pilih minimal satu produk'); return; }
    if (type === 'KELUAR' && !party) { toast.error('Isi penerima barang'); return; }
    try {
      await addTransaction({ type, items: chosen.map((r) => ({ productId: r.productId, qty: Number(r.qty) })), party, ref, polisi, kondisi, keterangan: ket });
      toast.success(type === 'MASUK' ? 'Stok masuk tersimpan' : 'Surat jalan dibuat & stok keluar tersimpan');
      if (type === 'KELUAR') navigate('/pengeluaran'); else navigate('/riwayat');
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Gagal menyimpan transaksi');
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
        <p className="text-[#8b93a1] mt-2 max-w-2xl">Satu pengeluaran bisa memuat beberapa jenis barang dan menghasilkan satu surat jalan beserta nomor antrian pemuatan.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="card-surface p-6 lg:col-span-2">
          <h2 className="font-display text-lg font-bold mb-4">Formulir Transaksi</h2>
          <div className="grid grid-cols-2 gap-2 mb-5 p-1 bg-[#0b0f17] rounded-xl border border-[#1a222e]">
            <button data-testid="txn-type-masuk" onClick={() => setType('MASUK')} className={`flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold transition-colors ${type === 'MASUK' ? 'bg-[#22c55e]/15 text-[#22c55e]' : 'text-[#8b93a1]'}`}><ArrowDownLeft size={16} /> Stok Masuk</button>
            <button data-testid="txn-type-keluar" onClick={() => setType('KELUAR')} className={`flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold transition-colors ${type === 'KELUAR' ? 'bg-[#ef4444]/15 text-[#ef4444]' : 'text-[#8b93a1]'}`}><ArrowUpRight size={16} /> Stok Keluar</button>
          </div>

          <label className="text-sm font-medium mb-2 block">Daftar Barang</label>
          <div className="space-y-2 mb-3">
            {rows.map((r, i) => {
              const prod = products.find((p) => p.id === r.productId);
              return (
                <div key={i} className="flex gap-2 items-center">
                  <select data-testid={`txn-product-select-${i}`} value={r.productId} onChange={(e) => setRow(i, { productId: e.target.value })} className="flex-1 bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]">
                    <option value="">Pilih produk...</option>
                    {products.map((p) => <option key={p.id} value={p.id}>{`${p.name} (${formatNum(p.stock)} ${p.unit})`}</option>)}
                  </select>
                  <input data-testid={`txn-qty-input-${i}`} type="number" min="1" value={r.qty} onChange={(e) => setRow(i, { qty: e.target.value })} className="w-24 bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" />
                  <span className="text-xs text-[#6b7688] w-10">{prod?.unit || '—'}</span>
                  <button onClick={() => delRow(i)} className="w-9 h-9 rounded-lg border border-[#242f3d] flex items-center justify-center text-[#ef4444] hover:bg-[#ef4444]/10"><Trash2 size={15} /></button>
                </div>
              );
            })}
          </div>
          <button onClick={addRow} className="inline-flex items-center gap-2 text-sm text-[#60a5fa] hover:text-[#93c5fd] mb-5"><Plus size={15} /> Tambah Barang</button>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div><label className="text-sm font-medium mb-1.5 block">{type === 'MASUK' ? 'Supplier Pengirim' : 'Penerima Barang'}</label>{type === 'MASUK' ? (
              <select data-testid="txn-party-select" value={party} onChange={(e) => setParty(e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]"><option value="">Pilih supplier...</option>{suppliers.map((s) => <option key={s.id}>{s.name}</option>)}</select>
            ) : (<input data-testid="txn-party-input" value={party} onChange={(e) => setParty(e.target.value)} placeholder="Nama penerima / toko" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" />)}</div>
            <div><label className="text-sm font-medium mb-1.5 block">No. Referensi / PO</label><input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="PO-2026-001" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
            <div><label className="text-sm font-medium mb-1.5 block">Nomor Plat Kendaraan</label><input value={polisi} onChange={(e) => setPolisi(e.target.value)} placeholder="B 9021 XY" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
            <div><label className="text-sm font-medium mb-1.5 block">Kondisi Barang</label><select value={kondisi} onChange={(e) => setKondisi(e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]"><option value="BAIK">Baik (Good)</option><option value="RUSAK">Rusak (Damage)</option></select><p className="text-xs text-[#6b7688] mt-1">Stok rusak dicatat terpisah dari stok baik.</p></div>
          </div>
          <div className="mt-4"><label className="text-sm font-medium mb-1.5 block">Keterangan</label><textarea value={ket} onChange={(e) => setKet(e.target.value)} rows={2} placeholder="Muat pagi — truk B 9021 XX..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb] resize-none" /></div>
          <button data-testid="txn-submit-btn" onClick={submit} className="btn-primary w-full mt-5 flex items-center justify-center gap-2 py-3 rounded-lg font-semibold text-sm"><Save size={16} /> Simpan Stok {type === 'MASUK' ? 'Masuk' : 'Keluar'}</button>
        </div>

        <div className="card-surface p-6 h-fit">
          <h2 className="font-display text-lg font-bold mb-4">Ringkasan Transaksi</h2>
          <span className="text-xs px-2.5 py-1 rounded-full font-semibold" style={{ background: type === 'MASUK' ? 'rgba(34,197,94,.15)' : 'rgba(239,68,68,.15)', color: type === 'MASUK' ? '#22c55e' : '#ef4444' }}>{type}</span>
          <div className="mt-5 space-y-3 text-sm">
            {[['Jenis barang', chosen.length], ['Total unit', formatNum(totalUnit)], ['Total berat', totalBerat.toFixed(2) + ' kg'], ['Estimasi nilai', formatRp(totalNilai)]].map(([l, v]) => (
              <div key={l} className="flex justify-between items-center border-b border-[#151d28] pb-3"><span className="text-[#8b93a1]">{l}</span><span className="font-mono font-semibold">{v}</span></div>
            ))}
          </div>
          {chosen.length === 0 ? <p className="text-xs text-[#6b7688] mt-4">Pilih barang untuk melihat perkiraan stok setelah transaksi.</p> : (
            <div className="mt-4 space-y-2">{chosen.map((r) => (<div key={r.productId} className="text-xs p-2.5 rounded-lg bg-[#0b0f17] border border-[#151d28]"><div className="font-medium">{r.product.name}</div><div className="text-[#8b93a1] font-mono">{formatNum(r.product.stock)} → {formatNum(type === 'MASUK' ? r.product.stock + Number(r.qty) : r.product.stock - Number(r.qty))} {r.product.unit}</div></div>))}</div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CatatStok;
