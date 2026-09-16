import React, { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, ClipboardCheck, RefreshCcw, Save, Send, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError } from '../lib/api';
import { useData } from '../context/DataContext';
import { canonicalRole, hasPermission } from '../lib/permissions';
import { formatNum } from '../mock';

const statusClass = (status) => ({
  DRAFT: 'bg-[#1e3a5f]/40 text-[#93c5fd] border-[#1e3a5f]',
  SUBMITTED: 'bg-[#78350f]/30 text-[#fcd34d] border-[#78350f]',
  APPROVED: 'bg-[#14532d]/25 text-[#86efac] border-[#14532d]',
  REJECTED: 'bg-[#7f1d1d]/30 text-[#fca5a5] border-[#7f1d1d]',
}[status] || 'bg-[#1a222e] text-[#aab4c4] border-[#242f3d]');

const OpnameGudang = () => {
  const { user, settings } = useData();
  const [opnames, setOpnames] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [warehouse, setWarehouse] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const canEdit = hasPermission(user?.role, 'operations');
  const canApprove = canonicalRole(user?.role) === 'Administrator' || hasPermission(user?.role, 'warehouseApprove');
  const warehouseCodes = useMemo(() => {
    const configured = settings?.warehouses || [];
    if (configured.length) return configured.map((item) => String(item.code || '').toUpperCase()).filter(Boolean);
    return ['17', '18', '19', '20', '21', '22', '23', '24', 'MP1'];
  }, [settings?.warehouses]);

  const selected = opnames.find((item) => item.id === selectedId) || null;

  const load = async (preserveId = selectedId) => {
    setLoading(true);
    try {
      const response = await api.get('/stock-opnames');
      setOpnames(response.data || []);
      if (preserveId && (response.data || []).some((item) => item.id === preserveId)) setSelectedId(preserveId);
      else if ((response.data || []).length) setSelectedId(response.data[0].id);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(''); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!warehouse && warehouseCodes.length) setWarehouse(warehouseCodes[0]); }, [warehouse, warehouseCodes]);

  const createOpname = async () => {
    if (!warehouse || saving) return;
    setSaving(true);
    try {
      const response = await api.post('/stock-opnames', { warehouse, note: '' });
      toast.success(`Stock opname ${response.data.no} dibuat dari snapshot stok saat ini.`);
      await load(response.data.id);
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const patchLine = (allocationId, patch) => {
    setOpnames((prev) => prev.map((opname) => opname.id !== selectedId ? opname : {
      ...opname,
      lines: (opname.lines || []).map((line) => line.allocationId === allocationId ? {
        ...line,
        ...patch,
        difference: Number(patch.physicalQty ?? line.physicalQty ?? 0) - Number(line.systemQty || 0),
      } : line),
    }));
  };

  const saveDraft = async () => {
    if (!selected || selected.status !== 'DRAFT' || saving) return;
    setSaving(true);
    try {
      const response = await api.put(`/stock-opnames/${selected.id}`, {
        note: selected.note || '',
        lines: (selected.lines || []).map((line) => ({
          allocationId: line.allocationId,
          physicalQty: Number(line.physicalQty || 0),
          channel: line.channel || 'KOM',
          note: line.note || '',
        })),
      });
      setOpnames((prev) => prev.map((item) => item.id === selected.id ? response.data : item));
      toast.success('Draft stock opname disimpan.');
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const submitOpname = async () => {
    if (!selected || selected.status !== 'DRAFT' || saving) return;
    if (!window.confirm(`Ajukan ${selected.no} untuk persetujuan? Setelah diajukan, angka fisik tidak dapat diedit.`)) return;
    setSaving(true);
    try {
      await saveDraft();
      const response = await api.post(`/stock-opnames/${selected.id}/submit`, { note: '' });
      setOpnames((prev) => prev.map((item) => item.id === selected.id ? response.data : item));
      toast.success('Stock opname diajukan untuk persetujuan.');
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const approve = async () => {
    if (!selected || selected.status !== 'SUBMITTED' || saving) return;
    const differences = (selected.lines || []).filter((line) => Math.abs(Number(line.difference || 0)) > 0.000001).length;
    if (!window.confirm(`Setujui ${selected.no}? ${differences} baris berselisih akan membuat transaksi PENYESUAIAN dan mengubah stok/tumpukan.`)) return;
    setSaving(true);
    try {
      const response = await api.post(`/stock-opnames/${selected.id}/approve`, { note: 'Disetujui melalui aplikasi' });
      setOpnames((prev) => prev.map((item) => item.id === selected.id ? response.data : item));
      toast.success('Stock opname disetujui dan adjustment audit telah dicatat.');
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const reject = async () => {
    if (!selected || selected.status !== 'SUBMITTED' || saving) return;
    const note = window.prompt('Alasan penolakan stock opname:');
    if (!note?.trim()) return;
    setSaving(true);
    try {
      const response = await api.post(`/stock-opnames/${selected.id}/reject`, { note: note.trim() });
      setOpnames((prev) => prev.map((item) => item.id === selected.id ? response.data : item));
      toast.success('Stock opname ditolak tanpa mengubah stok.');
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const differenceCount = (selected?.lines || []).filter((line) => Math.abs(Number(line.difference || 0)) > 0.000001).length;
  const totalDifference = (selected?.lines || []).reduce((sum, line) => sum + Number(line.difference || 0), 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><div className="label-mono mb-2">Physical Stock Check</div><h1 className="font-display text-4xl font-bold">Stock Opname GBB / MP1</h1><p className="text-[#8b93a1] mt-2 max-w-3xl">Snapshot sistem dibandingkan dengan fisik per tumpukan. Selisih tidak mengubah stok sampai disetujui Superadmin/Kepala Gudang.</p></div>
        <button onClick={() => load()} className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm"><RefreshCcw size={16} /> Muat Ulang</button>
      </div>

      {canEdit && <div className="card-surface p-5 flex flex-wrap items-end gap-3"><div><label className="text-xs text-[#8b93a1] block mb-1">GBB / Warehouse</label><select value={warehouse} onChange={(e) => setWarehouse(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 min-w-[150px]">{warehouseCodes.map((code) => <option key={code}>{code}</option>)}</select></div><button disabled={saving} onClick={createOpname} className="btn-primary px-4 py-2.5 rounded-lg text-sm font-semibold inline-flex items-center gap-2"><ClipboardCheck size={16} /> Buat Snapshot Opname</button><p className="text-xs text-[#6b7688] flex-1">Satu GBB hanya boleh memiliki satu opname DRAFT/SUBMITTED aktif.</p></div>}

      <div className="grid grid-cols-1 xl:grid-cols-[310px_1fr] gap-5">
        <div className="card-surface p-3 max-h-[720px] overflow-y-auto">
          {loading ? <div className="p-6 text-center text-[#8b93a1]">Memuat...</div> : opnames.length === 0 ? <div className="p-6 text-center text-[#8b93a1]">Belum ada stock opname.</div> : <div className="space-y-2">{opnames.map((item) => <button key={item.id} onClick={() => setSelectedId(item.id)} className={`w-full text-left rounded-xl border p-3 ${selectedId === item.id ? 'border-[#2563eb] bg-[#2563eb]/10' : 'border-[#1a222e] bg-[#0b0f17]'}`}><div className="flex justify-between gap-2"><span className="font-mono text-xs font-semibold">{item.no}</span><span className={`text-[9px] border rounded-full px-2 py-0.5 ${statusClass(item.status)}`}>{item.status}</span></div><div className="text-sm font-semibold mt-2">GBB {item.warehouse}</div><div className="text-[10px] text-[#6b7688] mt-1">{(item.lines || []).length} tumpukan/produk · {item.createdBy}</div></button>)}</div>}
        </div>

        <div className="card-surface p-5 min-w-0">
          {!selected ? <div className="py-16 text-center text-[#8b93a1]">Pilih stock opname di sebelah kiri.</div> : <>
            <div className="flex flex-wrap items-start justify-between gap-3 mb-4"><div><div className="flex items-center gap-2"><h2 className="font-display text-xl font-bold">{selected.no}</h2><span className={`text-[10px] border rounded-full px-2 py-1 ${statusClass(selected.status)}`}>{selected.status}</span></div><p className="text-xs text-[#8b93a1] mt-1">GBB {selected.warehouse} · dibuat {selected.createdBy}</p></div><div className="flex gap-2"><div className="rounded-lg bg-[#0b0f17] px-3 py-2 text-xs"><span className="text-[#8b93a1]">Baris selisih</span><div className="font-mono text-lg font-bold">{differenceCount}</div></div><div className="rounded-lg bg-[#0b0f17] px-3 py-2 text-xs"><span className="text-[#8b93a1]">Net selisih</span><div className={`font-mono text-lg font-bold ${totalDifference === 0 ? 'text-[#4ade80]' : 'text-[#fbbf24]'}`}>{totalDifference > 0 ? '+' : ''}{formatNum(totalDifference)}</div></div></div></div>

            <div className="overflow-x-auto max-h-[560px]">
              <table className="w-full text-sm tbl"><thead className="sticky top-0 bg-[#0d121b]"><tr className="text-left border-b border-[#1a222e]">{['Tumpukan', 'Produk', 'Sistem', 'Fisik', 'Selisih', 'Saluran', 'Catatan'].map((h) => <th key={h} className="py-2.5 pr-3 whitespace-nowrap">{h}</th>)}</tr></thead><tbody>{(selected.lines || []).map((line) => {
                const diff = Number(line.physicalQty || 0) - Number(line.systemQty || 0);
                const editable = selected.status === 'DRAFT' && canEdit;
                return <tr key={line.allocationId} className="border-b border-[#131a24]"><td className="py-2.5 pr-3 font-mono text-xs">{line.stackCode}</td><td className="py-2.5 pr-3"><div>{line.product}</div><div className="label-mono text-[9px]">{line.sku}</div></td><td className="py-2.5 pr-3 font-mono whitespace-nowrap">{formatNum(line.systemQty)} {line.unit}</td><td className="py-2.5 pr-3"><input disabled={!editable} type="number" min="0" step="any" value={line.physicalQty} onChange={(e) => patchLine(line.allocationId, { physicalQty: e.target.value })} className="w-28 bg-[#0b0f17] border border-[#242f3d] rounded px-2 py-1.5 font-mono disabled:opacity-70" /></td><td className={`py-2.5 pr-3 font-mono ${Math.abs(diff) > 0.000001 ? 'text-[#fbbf24]' : 'text-[#4ade80]'}`}>{diff > 0 ? '+' : ''}{formatNum(diff)}</td><td className="py-2.5 pr-3"><select disabled={!editable || Math.abs(diff) <= 0.000001} value={line.channel || 'KOM'} onChange={(e) => patchLine(line.allocationId, { channel: e.target.value })} className="bg-[#0b0f17] border border-[#242f3d] rounded px-2 py-1.5 text-xs disabled:opacity-60"><option value="PSO">PSO</option><option value="KOM">KOM</option></select></td><td className="py-2.5 pr-3"><input disabled={!editable} value={line.note || ''} onChange={(e) => patchLine(line.allocationId, { note: e.target.value })} className="min-w-[160px] bg-[#0b0f17] border border-[#242f3d] rounded px-2 py-1.5 text-xs disabled:opacity-60" placeholder="Opsional" /></td></tr>;
              })}</tbody></table>
            </div>

            <div className="flex flex-wrap justify-end gap-2 pt-4 border-t border-[#1a222e] mt-4">
              {selected.status === 'DRAFT' && canEdit && <><button disabled={saving} onClick={saveDraft} className="px-4 py-2 rounded-lg border border-[#2a3443] text-sm inline-flex items-center gap-2"><Save size={15} /> Simpan Draft</button><button disabled={saving} onClick={submitOpname} className="px-4 py-2 rounded-lg bg-[#2563eb] text-white text-sm font-semibold inline-flex items-center gap-2"><Send size={15} /> Ajukan</button></>}
              {selected.status === 'SUBMITTED' && canApprove && <><button disabled={saving} onClick={reject} className="px-4 py-2 rounded-lg border border-[#7f1d1d] text-[#fca5a5] text-sm inline-flex items-center gap-2"><XCircle size={15} /> Tolak</button><button disabled={saving} onClick={approve} className="px-4 py-2 rounded-lg bg-[#15803d] text-white text-sm font-semibold inline-flex items-center gap-2"><CheckCircle2 size={15} /> Setujui & Adjustment</button></>}
              {selected.status === 'APPROVED' && <div className="text-xs text-[#86efac]">Disetujui oleh {selected.approvedBy} · adjustment operation {selected.adjustmentOperationId || '—'}</div>}
              {selected.status === 'REJECTED' && <div className="text-xs text-[#fca5a5]">Ditolak oleh {selected.rejectedBy}: {selected.rejectionNote || '—'}</div>}
            </div>
          </>}
        </div>
      </div>
    </div>
  );
};

export default OpnameGudang;
