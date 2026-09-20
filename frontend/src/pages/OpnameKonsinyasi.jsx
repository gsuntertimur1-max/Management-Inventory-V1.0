import React, { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, ClipboardCheck, RefreshCcw, Save, Send, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import { useData } from '../context/DataContext';
import { formatNum } from '../mock';
import api, { apiError } from '../lib/api';
import { hasPermission, roleDestination } from '../lib/permissions';

const inputCls = 'w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';
const rowKey = (row) => `${row.productId}|${row.channel || 'KOM'}`;

const statusMeta = {
  DRAFT: ['Draft', 'bg-[#64748b]/15 text-[#cbd5e1]'],
  SUBMITTED: ['Menunggu Persetujuan', 'bg-[#f59e0b]/15 text-[#fbbf24]'],
  APPROVED: ['Disetujui', 'bg-[#22c55e]/15 text-[#86efac]'],
  REJECTED: ['Ditolak', 'bg-[#ef4444]/15 text-[#fca5a5]'],
};

const OpnameKonsinyasi = () => {
  const { consignmentStock, refreshConsignmentFlow, user } = useData();
  const scopedDestination = roleDestination(user?.role);
  const [destination, setDestination] = useState(scopedDestination || 'Gudang Bazar');
  const [opnames, setOpnames] = useState([]);
  const [actual, setActual] = useState({});
  const [lineNotes, setLineNotes] = useState({});
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (scopedDestination) setDestination(scopedDestination);
  }, [scopedDestination]);

  const canOperate = hasPermission(user?.role, destination === 'Gudang Bazar' ? 'bazarOps' : 'ecomOps');
  const canApprove = hasPermission(user?.role, 'warehouseApprove');

  const liveRows = useMemo(() => {
    const grouped = new Map();
    (consignmentStock || []).filter((item) => item.destination === destination).forEach((item) => {
      const key = rowKey(item);
      const current = grouped.get(key) || {
        productId: item.productId,
        channel: item.channel || 'KOM',
        sku: item.sku || '',
        name: item.name || '',
        unit: item.unit || '',
        systemQty: 0,
      };
      current.systemQty += Number(item.qty || 0);
      grouped.set(key, current);
    });
    return Array.from(grouped.values()).sort((a, b) => String(a.name).localeCompare(String(b.name), 'id'));
  }, [consignmentStock, destination]);

  const loadOpnames = async () => {
    const { data } = await api.get('/consignment-opnames', { params: { destination } });
    setOpnames(data || []);
  };

  useEffect(() => {
    loadOpnames().catch(() => {});
  }, [destination]);

  const active = useMemo(
    () => opnames.find((row) => ['DRAFT', 'SUBMITTED'].includes(row.status)),
    [opnames],
  );

  const displayedRows = active?.items || liveRows;

  useEffect(() => {
    const nextActual = {};
    const nextNotes = {};
    (displayedRows || []).forEach((row) => {
      nextActual[rowKey(row)] = Number(row.actualQty ?? row.systemQty ?? 0);
      nextNotes[rowKey(row)] = row.note || '';
    });
    setActual(nextActual);
    setLineNotes(nextNotes);
    setNote(active?.note || '');
  }, [active?.id, destination, liveRows.length]);

  const payloadItems = () => (displayedRows || []).map((row) => ({
    productId: row.productId,
    channel: row.channel || 'KOM',
    actualQty: Number(actual[rowKey(row)] ?? row.actualQty ?? row.systemQty ?? 0),
    note: lineNotes[rowKey(row)] || '',
  }));

  const createDraft = async () => {
    if (!liveRows.length) return toast.error('Belum ada saldo Bazar/E-commerce yang dapat diopname');
    setSaving(true);
    try {
      await api.post('/consignment-opnames', { destination, items: payloadItems(), note });
      toast.success('Draft stock opname tersimpan');
      await loadOpnames();
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setSaving(false);
    }
  };

  const saveDraft = async () => {
    if (!active || active.status !== 'DRAFT') return;
    await api.put(`/consignment-opnames/${active.id}`, { items: payloadItems(), note });
    await loadOpnames();
  };

  const saveDraftButton = async () => {
    setSaving(true);
    try {
      await saveDraft();
      toast.success('Draft opname diperbarui');
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setSaving(false);
    }
  };

  const submit = async () => {
    if (!active || active.status !== 'DRAFT') return;
    setSaving(true);
    try {
      await api.put(`/consignment-opnames/${active.id}`, { items: payloadItems(), note });
      await api.post(`/consignment-opnames/${active.id}/submit`, { note });
      toast.success('Stock opname diajukan untuk persetujuan Kepala Gudang');
      await loadOpnames();
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setSaving(false);
    }
  };

  const approve = async () => {
    if (!active || active.status !== 'SUBMITTED') return;
    const approvalNote = window.prompt('Catatan persetujuan (opsional):', '') ?? '';
    setSaving(true);
    try {
      await api.post(`/consignment-opnames/${active.id}/approve`, { note: approvalNote });
      toast.success('Opname disetujui · saldo dan lokasi Bazar/E-commerce telah disesuaikan');
      await Promise.all([loadOpnames(), refreshConsignmentFlow()]);
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setSaving(false);
    }
  };

  const reject = async () => {
    if (!active || active.status !== 'SUBMITTED') return;
    const rejectionNote = window.prompt('Alasan penolakan:', '') ?? '';
    if (!rejectionNote.trim()) return;
    setSaving(true);
    try {
      await api.post(`/consignment-opnames/${active.id}/reject`, { note: rejectionNote.trim() });
      toast.success('Stock opname ditolak tanpa mengubah saldo');
      await loadOpnames();
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setSaving(false);
    }
  };

  const history = opnames.filter((row) => !['DRAFT', 'SUBMITTED'].includes(row.status)).slice(0, 10);
  const editable = !active || active.status === 'DRAFT';

  return <div className="space-y-6">
    <div>
      <div className="label-mono mb-2">Kontrol Konsinyasi Unit 18</div>
      <h1 className="font-display text-4xl font-bold">Stock Opname Bazar / E-commerce</h1>
      <p className="text-sm text-[#8b93a1] mt-2">Selisih hanya mengubah saldo setelah disetujui Superadmin/Kepala Gudang. Adjustment otomatis disinkronkan ke lokasi/perkalian konsinyasi.</p>
    </div>

    <div className="card-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div className="flex gap-2">
          {['Gudang Bazar', 'Gudang E-commerce']
            .filter((location) => !scopedDestination || location === scopedDestination)
            .map((location) => <button
              key={location}
              disabled={Boolean(active)}
              onClick={() => setDestination(location)}
              className={`px-4 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50 ${destination === location ? 'bg-[#2563eb] text-white' : 'bg-[#101722] text-[#8b93a1]'}`}
            >{location === 'Gudang Bazar' ? 'Bazar' : 'E-commerce'}</button>)}
        </div>
        <button onClick={() => Promise.all([loadOpnames(), refreshConsignmentFlow()])} className="text-xs inline-flex items-center gap-1 text-[#93c5fd]"><RefreshCcw size={13}/> Refresh</button>
      </div>

      {active && <div className="rounded-xl border border-[#243044] bg-[#0b0f17] px-4 py-3 mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="font-mono text-sm text-[#93c5fd]">{active.no}</div>
          <div className="text-xs text-[#8b93a1] mt-1">Dibuat {new Date(active.createdAt || active.time).toLocaleString('id-ID')} · {active.createdBy || active.operator}</div>
        </div>
        <span className={`text-xs px-2.5 py-1 rounded-full ${statusMeta[active.status]?.[1] || ''}`}>{statusMeta[active.status]?.[0] || active.status}</span>
      </div>}

      {!displayedRows.length ? <p className="text-sm text-[#8b93a1]">Tidak ada saldo aktif untuk diopname.</p> : <div className="overflow-x-auto">
        <table className="w-full text-sm tbl">
          <thead><tr className="text-left border-b border-[#1a222e]">
            <th className="py-2.5 pr-4">SKU</th><th className="py-2.5 pr-4">Komoditi</th><th className="py-2.5 pr-4">Saluran</th>
            <th className="py-2.5 pr-4">Snapshot Sistem</th><th className="py-2.5 pr-4">Fisik Opname</th><th className="py-2.5 pr-4">Selisih</th><th className="py-2.5">Catatan</th>
          </tr></thead>
          <tbody>{displayedRows.map((item) => {
            const key = rowKey(item);
            const system = Number(item.systemQty ?? 0);
            const physical = Number(actual[key] ?? item.actualQty ?? system);
            const diff = physical - system;
            return <tr key={key} className="border-b border-[#131a24]">
              <td className="py-3 pr-4 font-mono text-xs text-[#93c5fd]">{item.sku || '—'}</td>
              <td className="py-3 pr-4 font-medium min-w-[260px]">{item.name}</td>
              <td className="py-3 pr-4">{item.channel || 'KOM'}</td>
              <td className="py-3 pr-4 font-mono">{formatNum(system)} {item.unit}</td>
              <td className="py-3 pr-4"><input type="number" min="0" disabled={!editable} value={actual[key] ?? physical} onChange={(event) => setActual((prev) => ({ ...prev, [key]: event.target.value }))} className="w-32 bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2 font-mono disabled:opacity-60" /></td>
              <td className={`py-3 pr-4 font-mono ${diff === 0 ? 'text-[#22c55e]' : diff < 0 ? 'text-[#ef4444]' : 'text-[#f59e0b]'}`}>{diff > 0 ? '+' : ''}{formatNum(diff)} {item.unit}</td>
              <td className="py-3"><input disabled={!editable} value={lineNotes[key] || ''} onChange={(event) => setLineNotes((prev) => ({ ...prev, [key]: event.target.value }))} placeholder="Keterangan selisih" className="min-w-[180px] bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2 text-xs disabled:opacity-60" /></td>
            </tr>;
          })}</tbody>
        </table>
      </div>}

      <textarea disabled={!editable} value={note} onChange={(event) => setNote(event.target.value)} rows={2} placeholder="Catatan opname (opsional)" className={`${inputCls} mt-4 disabled:opacity-60`} />

      <div className="flex flex-wrap gap-2 mt-3">
        {!active && canOperate && <button disabled={saving || !liveRows.length} onClick={createDraft} className="btn-primary px-4 py-2.5 rounded-lg inline-flex items-center gap-2 disabled:opacity-50"><Save size={16}/>{saving ? 'Menyimpan...' : 'Simpan Draft Opname'}</button>}
        {active?.status === 'DRAFT' && canOperate && <>
          <button disabled={saving} onClick={saveDraftButton} className="px-4 py-2.5 rounded-lg border border-[#64748b]/50 text-[#cbd5e1] inline-flex items-center gap-2"><Save size={16}/> Simpan Draft</button>
          <button disabled={saving} onClick={submit} className="btn-primary px-4 py-2.5 rounded-lg inline-flex items-center gap-2"><Send size={16}/> Ajukan Persetujuan</button>
        </>}
        {active?.status === 'SUBMITTED' && canApprove && <>
          <button disabled={saving} onClick={approve} className="px-4 py-2.5 rounded-lg border border-[#22c55e]/50 text-[#86efac] inline-flex items-center gap-2"><CheckCircle2 size={16}/> Setujui & Adjustment</button>
          <button disabled={saving} onClick={reject} className="px-4 py-2.5 rounded-lg border border-[#ef4444]/50 text-[#fca5a5] inline-flex items-center gap-2"><XCircle size={16}/> Tolak</button>
        </>}
        {active?.status === 'SUBMITTED' && !canApprove && <div className="text-xs text-[#fbbf24] py-2">Menunggu persetujuan Superadmin/Kepala Gudang. Saldo belum berubah.</div>}
      </div>
    </div>

    <div className="card-surface p-5">
      <div className="flex items-center gap-2 mb-4"><ClipboardCheck size={18} className="text-[#60a5fa]"/><h2 className="font-display text-xl font-bold">Riwayat Opname {destination === 'Gudang Bazar' ? 'Bazar' : 'E-commerce'}</h2></div>
      {history.length === 0 ? <p className="text-sm text-[#8b93a1]">Belum ada opname yang selesai diproses.</p> : <div className="space-y-3">{history.map((opname) => <div key={opname.id} className="rounded-lg bg-[#0b0f17] border border-[#1a222e] p-3 text-sm">
        <div className="flex flex-wrap justify-between gap-2"><div className="font-mono text-xs text-[#93c5fd]">{opname.no} · {new Date(opname.createdAt || opname.time).toLocaleString('id-ID')}</div><span className={`text-[10px] px-2 py-1 rounded-full ${statusMeta[opname.status]?.[1] || ''}`}>{statusMeta[opname.status]?.[0] || opname.status}</span></div>
        <div className="mt-2">{(opname.items || []).filter((item) => Number(item.difference) !== 0).map((item) => `${item.name}: ${Number(item.difference) > 0 ? '+' : ''}${formatNum(item.difference)} ${item.unit}`).join(' · ') || 'Tidak ada selisih'}</div>
        {opname.status === 'APPROVED' && <div className="text-xs text-[#86efac] mt-1">Disetujui {opname.approvedBy || '—'} · saldo dan lokasi telah disesuaikan.</div>}
        {opname.status === 'REJECTED' && <div className="text-xs text-[#fca5a5] mt-1">Ditolak {opname.rejectedBy || '—'} · {opname.rejectionNote || 'tanpa catatan'}</div>}
        {opname.note && <div className="text-xs text-[#8b93a1] mt-1">{opname.note}</div>}
      </div>)}</div>}
    </div>
  </div>;
};

export default OpnameKonsinyasi;
