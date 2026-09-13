import React, { useMemo, useState } from 'react';
import { ClipboardCheck, Save } from 'lucide-react';
import { toast } from 'sonner';
import { useData } from '../context/DataContext';
import { formatNum } from '../mock';
import { apiError } from '../lib/api';

const OpnameKonsinyasi = () => {
  const { consignmentStock, consignmentOpnames, addConsignmentOpname, canWrite } = useData();
  const [destination, setDestination] = useState('Gudang Bazar');
  const rows = useMemo(() => consignmentStock.filter((item) => item.destination === destination), [consignmentStock, destination]);
  const [actual, setActual] = useState({});
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const history = consignmentOpnames.filter((item) => item.destination === destination).slice(0, 5);
  const actualFor = (item) => actual[item.productId] ?? item.qty;
  const save = async () => {
    if (!rows.length) return toast.error('Belum ada saldo Memo/ND aktif untuk diopname');
    setSaving(true);
    try {
      await addConsignmentOpname({ destination, note, items: rows.map((item) => ({ productId: item.productId, actualQty: Number(actualFor(item)), note: '' })) });
      toast.success('Catatan opname tersimpan. Saldo sistem tidak diubah otomatis.'); setActual({}); setNote('');
    } catch (error) { toast.error(apiError(error)); } finally { setSaving(false); }
  };
  return <div className="space-y-6">
    <div><div className="label-mono mb-2">Kontrol Konsinyasi Unit 18</div><h1 className="font-display text-4xl font-bold">Opname Bazar / E-commerce</h1><p className="text-[#8b93a1] mt-2">Bandingkan saldo Memo/ND dengan fisik. Selisih dicatat untuk evaluasi dan tidak mengubah saldo tanpa dokumen penyesuaian.</p></div>
    <div className="card-surface p-5"><div className="flex gap-2 mb-5">{['Gudang Bazar', 'Gudang E-commerce'].map((location) => <button key={location} onClick={() => { setDestination(location); setActual({}); }} className={`px-4 py-2.5 rounded-lg text-sm font-semibold ${destination === location ? 'bg-[#2563eb] text-white' : 'bg-[#101722] text-[#8b93a1]'}`}>{location === 'Gudang Bazar' ? 'Bazar' : 'E-commerce'}</button>)}</div>{rows.length === 0 ? <p className="text-sm text-[#8b93a1]">Tidak ada saldo Memo/ND aktif.</p> : <div className="overflow-x-auto"><table className="w-full text-sm tbl"><thead><tr className="text-left border-b border-[#1a222e]"><th className="py-2.5 pr-4">SKU</th><th className="py-2.5 pr-4">Komoditi</th><th className="py-2.5 pr-4">Saldo Sistem</th><th className="py-2.5 pr-4">Fisik Opname</th><th className="py-2.5">Selisih</th></tr></thead><tbody>{rows.map((item) => { const physical = Number(actualFor(item)); const diff = physical - Number(item.qty); return <tr key={item.productId} className="border-b border-[#131a24]"><td className="py-3 pr-4 font-mono text-xs text-[#93c5fd]">{item.sku || '—'}</td><td className="py-3 pr-4 font-medium">{item.name}</td><td className="py-3 pr-4 font-mono">{formatNum(item.qty)} {item.unit}</td><td className="py-3 pr-4"><input type="number" min="0" value={actualFor(item)} onChange={(event) => setActual({ ...actual, [item.productId]: event.target.value })} className="w-32 bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2 font-mono" /></td><td className={`py-3 font-mono ${diff === 0 ? 'text-[#22c55e]' : diff < 0 ? 'text-[#ef4444]' : 'text-[#f59e0b]'}`}>{diff > 0 ? '+' : ''}{formatNum(diff)} {item.unit}</td></tr>; })}</tbody></table></div>}<textarea value={note} onChange={(event) => setNote(event.target.value)} rows={2} placeholder="Catatan opname (opsional)" className="w-full mt-4 bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm" />{canWrite && <button disabled={saving || !rows.length} onClick={save} className="btn-primary mt-3 px-4 py-2.5 rounded-lg inline-flex items-center gap-2 disabled:opacity-50"><Save size={16} />{saving ? 'Menyimpan...' : 'Simpan Opname'}</button>}</div>
    <div className="card-surface p-5"><div className="flex items-center gap-2 mb-4"><ClipboardCheck size={18} className="text-[#60a5fa]" /><h2 className="font-display text-xl font-bold">Riwayat Opname {destination === 'Gudang Bazar' ? 'Bazar' : 'E-commerce'}</h2></div>{history.length === 0 ? <p className="text-sm text-[#8b93a1]">Belum ada catatan opname.</p> : <div className="space-y-2">{history.map((opname) => <div key={opname.id} className="rounded-lg bg-[#0b0f17] border border-[#1a222e] p-3 text-sm"><div className="font-mono text-xs text-[#93c5fd]">{new Date(opname.time).toLocaleString('id-ID')} · {opname.operator}</div><div className="mt-1">{(opname.items || []).filter((item) => Number(item.difference) !== 0).map((item) => `${item.name}: ${Number(item.difference) > 0 ? '+' : ''}${formatNum(item.difference)} ${item.unit}`).join(' · ') || 'Tidak ada selisih'}</div>{opname.note && <div className="text-xs text-[#8b93a1] mt-1">{opname.note}</div>}</div>)}</div>}</div>
  </div>;
};

export default OpnameKonsinyasi;
