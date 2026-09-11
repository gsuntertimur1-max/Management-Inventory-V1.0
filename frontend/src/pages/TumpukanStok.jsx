import React, { useMemo, useState } from 'react';
import { DoorOpen, Download, Edit3, Minus, PackagePlus, Plus, Trash2, Warehouse } from 'lucide-react';
import { toast } from 'sonner';
import { useData } from '../context/DataContext';
import { apiError } from '../lib/api';
import { downloadApiFile } from '../lib/api';
import { formatNum } from '../mock';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '../components/ui/dialog';

const WAREHOUSES = [...Array.from({ length: 8 }, (_, i) => String(i + 17)), 'MP1'];
const codesFor = (wh) => (wh === 'MP1' ? ['A', 'B'] : ['A', 'B', 'C'])
  .flatMap((zone) => Array.from({ length: wh === 'MP1' ? 8 : 4 }, (_, i) => `${wh}/${zone}${String(i + 1).padStart(2, '0')}`));
const blank = (stackCode) => ({ productId: '', stackCode, length: 1, width: 1, height: 1, arrangements: [{ hamparan: 1, kaki: 1, height: 1 }], extraSecondary: 0, extraPrimary: 0, note: '' });

const TumpukanStok = () => {
  const { products, stackAllocations, canWrite, addStackAllocation, updateStackAllocation, deleteStackAllocation } = useData();
  const [warehouse, setWarehouse] = useState('17');
  const [selected, setSelected] = useState('17/A01');
  const [modal, setModal] = useState(null);
  const [busy, setBusy] = useState(false);
  const grouped = useMemo(() => stackAllocations.reduce((map, item) => ({ ...map, [item.stackCode]: [...(map[item.stackCode] || []), item] }), {}), [stackAllocations]);
  const allocated = useMemo(() => stackAllocations.reduce((map, item) => ({ ...map, [item.productId]: (map[item.productId] || 0) + Number(item.primaryQty || 0) }), {}), [stackAllocations]);
  const product = products.find((item) => item.id === modal?.data.productId);
  const secCount = modal ? (modal.data.arrangements || []).reduce((sum, row) => sum + Number(row.hamparan || 0) * Number(row.kaki || 0) * Number(row.height || 0), 0) + Number(modal.data.extraSecondary || 0) : 0;
  const packCount = secCount * Number(product?.secondaryQty || 0) + Number(modal?.data.extraPrimary || 0);
  const prior = modal?.mode === 'edit' ? Number(modal.data.originalPrimaryQty || 0) : 0;
  const available = product ? Math.max(Number(product.stock || 0) - Number(allocated[product.id] || 0) + prior, 0) : 0;
  const eligible = products.filter((item) => item.secondary && Number(item.secondaryQty || 0) > 0);

  const chooseWarehouse = (value) => { setWarehouse(value); setSelected(codesFor(value)[0]); };
  const openEdit = (item) => setModal({ mode: 'edit', id: item.id, data: { productId: item.productId, stackCode: item.stackCode, length: item.length || 1, width: item.width || 1, height: item.height || 1, arrangements: item.arrangements?.length ? item.arrangements : [{ hamparan: item.length || 1, kaki: item.width || 1, height: item.height || 1 }], extraSecondary: item.extraSecondary || 0, extraPrimary: item.extraPrimary || item.primaryRemainder || 0, note: item.note || '', originalPrimaryQty: item.primaryQty } });
  const save = async () => {
    if (!modal?.data.productId) return toast.error('Pilih produk terlebih dahulu');
    if ((modal.data.arrangements || []).some((row) => [row.hamparan, row.kaki, row.height].some((v) => Number(v) < 1 || !Number.isInteger(Number(v))))) return toast.error('Hamparan, kaki, dan tinggi harus berupa angka bulat minimal 1');
    setBusy(true);
    const first = modal.data.arrangements[0];
    const payload = { ...modal.data, length: Number(first.hamparan), width: Number(first.kaki), height: Number(first.height), extraSecondary: Number(modal.data.extraSecondary || 0), extraPrimary: Number(modal.data.extraPrimary || 0) };
    delete payload.originalPrimaryQty;
    try {
      if (modal.mode === 'edit') await updateStackAllocation(modal.id, payload); else await addStackAllocation(payload);
      toast.success('Alokasi tumpukan berhasil disimpan'); setModal(null);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const remove = async (item) => {
    if (!window.confirm(`Hapus alokasi ${item.productName} dari ${item.stackCode}? Stok produk tidak ikut dihapus.`)) return;
    try { await deleteStackAllocation(item.id); toast.success('Alokasi tumpukan dihapus'); } catch (e) { toast.error(apiError(e)); }
  };
  const occupied = new Set(stackAllocations.map((item) => item.stackCode)).size;
  const totalAllocated = stackAllocations.reduce((n, item) => n + Number(item.primaryQty || 0), 0);
  const unallocated = products.reduce((n, item) => n + Math.max(Number(item.stock || 0) - Number(allocated[item.id] || 0), 0), 0);
  const zones = warehouse === 'MP1' ? ['B', 'A'] : ['C', 'B', 'A'];

  return <div className="space-y-5" data-testid="stack-map-page">
    <div className="flex flex-col xl:flex-row xl:items-end xl:justify-between gap-4">
      <div><div className="label-mono mb-2">Gudang Sunter Timur I & II</div><h1 className="font-display text-3xl md:text-4xl font-bold">Peta Tumpukan Stok</h1><p className="text-sm text-[#8b93a1] mt-2">Susunan komoditas berdasarkan kemasan sekunder.</p></div>
      <div className="grid grid-cols-3 gap-2">
        {[['Terisi', `${occupied}/112`, 'text-white'], ['Ditempatkan', formatNum(totalAllocated), 'text-[#60a5fa]'], ['Belum ditempatkan', formatNum(unallocated), unallocated ? 'text-[#f59e0b]' : 'text-[#22c55e]']].map(([label, value, color]) => <div key={label} className="card-surface p-3"><div className="text-xs text-[#6b7688]">{label}</div><div className={`font-display text-lg md:text-xl font-bold mt-1 ${color}`}>{value}</div></div>)}
      </div>
    </div>

    <div className="card-surface p-3 overflow-x-auto"><div className="flex gap-2 min-w-max">{WAREHOUSES.map((wh) => <button key={wh} onClick={() => chooseWarehouse(wh)} className={`px-4 py-2.5 rounded-lg text-sm font-semibold flex items-center gap-2 ${warehouse === wh ? 'bg-[#2563eb] text-white' : 'bg-[#101722] text-[#8b93a1]'}`}><Warehouse size={16} />{wh === 'MP1' ? 'MP1' : `GBB ${wh}`}</button>)}</div></div>

    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_390px] gap-5">
      <section className="card-surface p-4 md:p-5">
        <div className="flex justify-between mb-4"><div><h2 className="font-display text-xl font-bold">{warehouse === 'MP1' ? 'MP1' : `GBB ${warehouse}`}</h2><p className="text-xs text-[#6b7688] mt-1">{warehouse === 'MP1' ? '230 × 30 meter · membentang di antara GBB 17–20 dan GBB 21–24' : '50 × 30 meter · dua posisi pintu'} · Klik tumpukan untuk melihat isinya.</p></div><span className="hidden sm:flex items-center gap-2 text-xs text-[#6b7688]"><DoorOpen size={16} />Pintu depan</span></div>
        <div className={`grid ${warehouse === 'MP1' ? 'grid-cols-2' : 'grid-cols-3'} gap-2 md:gap-3`}>{zones.map((zone) => <div key={zone} className="space-y-2 min-w-0"><div className="text-center text-sm font-bold text-[#93c5fd] py-2 rounded-lg bg-[#0d1728]">Tumpukan {zone}</div>{codesFor(warehouse).filter((code) => code.includes(`/${zone}`)).map((code) => {
          const items = grouped[code] || [];
          return <button key={code} onClick={() => setSelected(code)} className={`w-full min-h-[100px] p-2.5 rounded-xl border text-left ${selected === code ? 'border-[#3b82f6] bg-[#102044]' : items.length ? 'border-[#214a3a] bg-[#0d1c19]' : 'border-[#202a38] bg-[#0b0f17]'}`}><div className="flex justify-between"><span className="font-mono text-xs md:text-sm font-bold">{code}</span><span className={`w-2 h-2 rounded-full ${items.length ? 'bg-[#22c55e]' : 'bg-[#374151]'}`} /></div><div className="mt-3 text-xs text-[#8b93a1]">{items.length ? `${items.length} komoditas` : 'Kosong'}</div>{items.length > 0 && <div className="mt-1 text-xs truncate">{formatNum(items.reduce((n, x) => n + Number(x.secondaryCount || 0), 0))} kemasan</div>}</button>;
        })}</div>)}</div>
        <div className="mt-4 flex justify-center gap-2 border border-dashed border-[#29364a] rounded-lg py-2.5 text-xs text-[#6b7688]"><DoorOpen size={15} />{warehouse === 'MP1' ? 'Pintu utama depan dan belakang · lebar 30 meter' : 'Pintu belakang terhubung menuju MP1'}</div>
      </section>

      <aside className="card-surface p-5 h-fit xl:sticky xl:top-24">
        <div className="flex justify-between"><div><div className="label-mono text-[10px]">Tumpukan dipilih</div><h2 className="font-display text-2xl font-bold mt-1">{selected}</h2></div><div className="flex gap-2"><button title="Download kartu tumpukan" onClick={() => downloadApiFile(`/export/stack-card.xlsx?stackCode=${encodeURIComponent(selected)}`, `kartu_tumpukan_${selected.replace('/', '-')}.xlsx`).catch((e) => toast.error(apiError(e)))} className="h-fit p-2 rounded-lg border border-[#242f3d] text-[#60a5fa]"><Download size={17} /></button>{canWrite && <button onClick={() => setModal({ mode: 'add', data: blank(selected) })} className="btn-primary h-fit px-3 py-2 rounded-lg text-sm flex gap-2"><PackagePlus size={16} />Tambah</button>}</div></div>
        <div className="mt-5 space-y-3">{(grouped[selected] || []).length === 0 ? <div className="border border-dashed border-[#29364a] rounded-xl p-8 text-center text-sm text-[#8b93a1]">Belum ada komoditas.</div> : (grouped[selected] || []).map((item) => <div key={item.id} className="rounded-xl border border-[#1d2a3a] bg-[#0b0f17] p-4">
          <div className="flex justify-between gap-2"><div><div className="font-semibold">{item.productName}</div><div className="label-mono text-[10px] mt-1">{item.sku}</div></div>{canWrite && <div className="flex"><button title="Ubah" onClick={() => openEdit(item)} className="p-2 text-[#60a5fa]"><Edit3 size={15} /></button><button title="Hapus" onClick={() => remove(item)} className="p-2 text-[#ef4444]"><Trash2 size={15} /></button></div>}</div>
          {item.arrangementAdjusted ? <div className="mt-3 rounded-lg bg-[#3b2a0b] p-2 text-xs text-[#fbbf24]">Stok berkurang karena pengeluaran. Perbarui susunan fisik.</div> : <div className="mt-3 space-y-1 font-mono text-sm">{(item.arrangements?.length ? item.arrangements : [{ hamparan: item.length, kaki: item.width, height: item.height }]).map((row, index) => <div key={index}>{row.hamparan} × {row.kaki} × {row.height} = {formatNum(row.hamparan * row.kaki * row.height)}</div>)}{Number(item.extraSecondary || 0) > 0 && <div>+ {formatNum(item.extraSecondary)} {item.secondary} tambahan</div>}<div className="pt-1 text-[#93c5fd]">Total {formatNum(item.secondaryCount)} {item.secondary}</div></div>}
          {Number(item.extraPrimary || 0) > 0 && <div className="mt-1 text-sm text-[#fbbf24]">+ {formatNum(item.extraPrimary)} {item.unit} lepas tanpa {item.secondary}</div>}<div className="mt-2 text-sm text-[#60a5fa]">{formatNum(item.primaryQty)} {item.unit}{Number(item.weight || 0) > 0 ? ` · ${formatNum(Number(item.primaryQty) * Number(item.weight))} kg` : ''}</div>{item.note && <div className="mt-2 text-xs text-[#8b93a1]">{item.note}</div>}
        </div>)}</div>
      </aside>
    </div>

    <Dialog open={Boolean(modal)} onOpenChange={(open) => { if (!open && !busy) setModal(null); }}><DialogContent className="max-w-2xl border-[#242f3d] bg-[#0d121b] text-[#e7ebf2]"><DialogHeader><DialogTitle>{modal?.mode === 'edit' ? 'Ubah Susunan' : 'Tempatkan Komoditas'}</DialogTitle><DialogDescription className="text-[#8b93a1]">Tumpukan {modal?.data.stackCode}; perhitungan memakai kemasan sekunder.</DialogDescription></DialogHeader>{modal && <div className="space-y-4">
      <div><label className="text-sm block mb-1">Produk</label><select disabled={modal.mode === 'edit'} value={modal.data.productId} onChange={(e) => setModal({ ...modal, data: { ...modal.data, productId: e.target.value } })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5"><option value="">Pilih produk...</option>{eligible.map((p) => <option key={p.id} value={p.id}>{p.name} — belum ditempatkan {formatNum(Math.max(Number(p.stock || 0) - Number(allocated[p.id] || 0), 0))} {p.unit}</option>)}</select><p className="text-xs text-[#6b7688] mt-1">Atur kemasan sekunder di Master Produk jika produk belum muncul.</p></div>
      <div className="space-y-2"><div className="flex justify-between"><label className="text-sm font-medium">Blok perkalian <span className="text-[#6b7688]">(maks. 10)</span></label>{modal.data.arrangements.length < 10 && <button onClick={() => setModal({ ...modal, data: { ...modal.data, arrangements: [...modal.data.arrangements, { hamparan: 1, kaki: 1, height: 1 }] } })} className="text-xs text-[#60a5fa] flex items-center gap-1"><Plus size={14} />Tambah perkalian</button>}</div>{modal.data.arrangements.map((row, index) => <div key={index} className="grid grid-cols-[1fr_1fr_1fr_34px] gap-2 items-end rounded-lg bg-[#0b0f17] p-2">{[['hamparan', 'Hamparan'], ['kaki', 'Kaki'], ['height', 'Tinggi']].map(([key, label]) => <div key={key}><label className="text-xs text-[#8b93a1] block mb-1">{label}</label><input type="number" min="1" step="1" value={row[key]} onChange={(e) => { const arrangements = modal.data.arrangements.map((x, i) => i === index ? { ...x, [key]: Number(e.target.value) } : x); setModal({ ...modal, data: { ...modal.data, arrangements } }); }} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2 font-mono" /></div>)}<button disabled={modal.data.arrangements.length === 1} onClick={() => setModal({ ...modal, data: { ...modal.data, arrangements: modal.data.arrangements.filter((_, i) => i !== index) } })} className="h-10 text-[#ef4444] disabled:opacity-30"><Minus size={16} /></button></div>)}</div>
      <div><label className="text-sm block mb-1">Kemasan tambahan / numpang</label><input type="number" min="0" step="1" value={modal.data.extraSecondary || 0} onChange={(e) => setModal({ ...modal, data: { ...modal.data, extraSecondary: Number(e.target.value) } })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 font-mono" /></div>
      <div><label className="text-sm block mb-1">{product?.unit || 'Pack/pouch'} lepas tanpa {product?.secondary || 'kemasan sekunder'}</label><input type="number" min="0" step="1" value={modal.data.extraPrimary || 0} onChange={(e) => setModal({ ...modal, data: { ...modal.data, extraPrimary: Number(e.target.value) } })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 font-mono" /></div>
      <input placeholder="Catatan (opsional)" value={modal.data.note} onChange={(e) => setModal({ ...modal, data: { ...modal.data, note: e.target.value } })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" />
      <div className="rounded-xl border border-[#1f3657] bg-[#0d1728] p-4">{product ? <><div className="font-mono text-lg">Total = {formatNum(secCount)} {product.secondary} + {formatNum(modal.data.extraPrimary || 0)} {product.unit} lepas</div><div className="text-[#93c5fd] mt-2">({formatNum(secCount)} × {formatNum(product.secondaryQty)}) + {formatNum(modal.data.extraPrimary || 0)} = <strong>{formatNum(packCount)} {product.unit}</strong></div><div className={`text-xs mt-2 ${packCount <= available ? 'text-[#22c55e]' : 'text-[#ef4444]'}`}>Tersedia untuk ditempatkan: {formatNum(available)} {product.unit}</div></> : <span className="text-sm text-[#6b7688]">Pilih produk untuk menghitung susunan.</span>}</div>
    </div>}<DialogFooter><button disabled={busy} onClick={() => setModal(null)} className="px-4 py-2 border border-[#242f3d] rounded-lg">Batal</button><button disabled={busy || !product || packCount > available} onClick={save} className="btn-primary px-4 py-2 rounded-lg disabled:opacity-50">{busy ? 'Menyimpan...' : 'Simpan'}</button></DialogFooter></DialogContent></Dialog>
  </div>;
};

export default TumpukanStok;
