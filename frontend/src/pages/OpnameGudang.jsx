import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, ClipboardCheck, RefreshCcw, Save, Send, XCircle } from 'lucide-react';
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
  CANCELLED: 'bg-[#374151]/30 text-[#cbd5e1] border-[#4b5563]',
}[status] || 'bg-[#1a222e] text-[#aab4c4] border-[#242f3d]');

const lotStatusClass = (status) => ({
  SYNCED: 'bg-[#14532d]/25 text-[#86efac] border-[#14532d]',
  RECONCILIATION_REQUIRED: 'bg-[#78350f]/30 text-[#fcd34d] border-[#78350f]',
  ERROR: 'bg-[#7f1d1d]/30 text-[#fca5a5] border-[#7f1d1d]',
}[status] || 'bg-[#1a222e] text-[#aab4c4] border-[#242f3d]');

const OpnameGudang = () => {
  const { user, settings } = useData();
  const [opnames, setOpnames] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [warehouse, setWarehouse] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [lotLoading, setLotLoading] = useState(false);
  const [lotReconcile, setLotReconcile] = useState(null);

  const canEdit = hasPermission(user?.role, 'operations');
  const canApprove = canonicalRole(user?.role) === 'Administrator' || hasPermission(user?.role, 'warehouseApprove');
  const warehouseCodes = useMemo(() => {
    const configured = settings?.warehouses || [];
    if (configured.length) return configured.map((item) => String(item.code || '').toUpperCase()).filter(Boolean);
    return ['17', '18', '19', '20', '21', '22', '23', '24', 'MP1'];
  }, [settings?.warehouses]);

  const selected = opnames.find((item) => item.id === selectedId) || null;

  const replaceOpname = (document) => {
    if (!document?.id) return;
    setOpnames((prev) => prev.map((item) => item.id === document.id ? document : item));
  };

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
  useEffect(() => { setLotReconcile(null); }, [selectedId]);

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

  const draftPayload = (opname) => ({
    note: opname.note || '',
    lines: (opname.lines || []).map((line) => ({
      allocationId: line.allocationId,
      physicalQty: Number(line.physicalQty || 0),
      channel: line.channel || 'KOM',
      note: line.note || '',
    })),
  });

  const persistDraft = async (opname) => api.put(`/stock-opnames/${opname.id}`, draftPayload(opname));

  const saveDraft = async () => {
    if (!selected || selected.status !== 'DRAFT' || saving) return;
    setSaving(true);
    try {
      const response = await persistDraft(selected);
      replaceOpname(response.data);
      toast.success('Draft stock opname disimpan.');
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const submitOpname = async () => {
    if (!selected || selected.status !== 'DRAFT' || saving) return;
    if (!window.confirm(`Ajukan ${selected.no} untuk persetujuan? Setelah diajukan, angka fisik tidak dapat diedit.`)) return;
    setSaving(true);
    try {
      const saved = await persistDraft(selected);
      const response = await api.post(`/stock-opnames/${selected.id}/submit`, { note: '' });
      replaceOpname(response.data);
      if (saved.data?.updatedAt) toast.success('Draft terbaru tersimpan dan stock opname diajukan untuk persetujuan.');
      else toast.success('Stock opname diajukan untuk persetujuan.');
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const approve = async () => {
    if (!selected || selected.status !== 'SUBMITTED' || saving) return;
    const differences = (selected.lines || []).filter((line) => Math.abs(Number(line.difference || 0)) > 0.000001).length;
    if (!window.confirm(`Setujui ${selected.no}? ${differences} baris berselisih akan membuat transaksi PENYESUAIAN dan mengubah stok/tumpukan.`)) return;
    setSaving(true);
    try {
      const response = await api.post(`/stock-opnames/${selected.id}/approve`, { note: 'Disetujui melalui aplikasi' });
      replaceOpname(response.data);
      if (response.data?.lotSyncStatus === 'RECONCILIATION_REQUIRED') {
        toast.warning('Stock opname disetujui. Ada tumpukan multi-lot yang perlu rekonsiliasi batch sebelum subledger lot dinyatakan sinkron.');
      } else {
        toast.success('Stock opname disetujui dan adjustment audit telah dicatat.');
      }
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const cancelDraft = async () => {
    if (!selected || selected.status !== 'DRAFT' || saving) return;
    const defaultNote = selected.snapshotStale ? 'Snapshot kedaluwarsa karena stok berubah setelah opname dibuat' : 'Draft dibatalkan';
    const note = window.prompt('Alasan pembatalan draft opname:', defaultNote);
    if (!note?.trim()) return;
    if (!window.confirm(`Batalkan ${selected.no}? Tidak ada stok yang akan berubah.`)) return;
    setSaving(true);
    try {
      const response = await api.post(`/stock-opnames/${selected.id}/cancel`, { note: note.trim() });
      replaceOpname(response.data);
      toast.success('Draft stock opname dibatalkan tanpa mengubah stok.');
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const reject = async () => {
    if (!selected || selected.status !== 'SUBMITTED' || saving) return;
    const note = window.prompt('Alasan penolakan stock opname:');
    if (!note?.trim()) return;
    setSaving(true);
    try {
      const response = await api.post(`/stock-opnames/${selected.id}/reject`, { note: note.trim() });
      replaceOpname(response.data);
      toast.success('Stock opname ditolak tanpa mengubah stok.');
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const syncLots = async () => {
    if (!selected || selected.status !== 'APPROVED' || saving || !canApprove) return;
    setSaving(true);
    try {
      const response = await api.post(`/stock-opnames/${selected.id}/sync-lots`);
      replaceOpname(response.data);
      toast.success(response.data?.lotSyncStatus === 'SYNCED' ? 'Subledger lot sudah sinkron.' : 'Sinkronisasi lot diperiksa ulang.');
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const openLotReconcile = async (row) => {
    if (!selected || !canApprove || lotLoading) return;
    setLotLoading(true);
    try {
      const response = await api.get('/stack-lots', { params: { productId: row.productId, stackCode: row.stackCode } });
      const lots = response.data || [];
      if (!lots.length) {
        toast.error('Tidak ada lot aktif pada tumpukan ini. Jalankan sinkronisasi ulang untuk mencatat bagian legacy/untracked.');
        return;
      }
      setLotReconcile({ row, lots, quantities: {}, note: '' });
    } catch (e) { toast.error(apiError(e)); } finally { setLotLoading(false); }
  };

  const patchLotQty = (lotId, value) => {
    setLotReconcile((prev) => prev ? { ...prev, quantities: { ...prev.quantities, [lotId]: value } } : prev);
  };

  const submitLotReconcile = async () => {
    if (!selected || !lotReconcile || saving) return;
    const items = (lotReconcile.lots || []).map((lot) => ({
      productId: lotReconcile.row.productId,
      stackCode: lotReconcile.row.stackCode,
      lotId: lot.id,
      qty: Number(lotReconcile.quantities?.[lot.id] || 0),
    })).filter((item) => item.qty > 0);
    if (!items.length) return toast.error('Isi jumlah koreksi pada minimal satu lot.');
    const total = items.reduce((sum, item) => sum + item.qty, 0);
    const required = Number(lotReconcile.row.qty || 0);
    if (total > required + 0.000001) return toast.error(`Total koreksi ${formatNum(total)} melebihi selisih yang perlu direkonsiliasi (${formatNum(required)} ${lotReconcile.row.unit}).`);
    if (!window.confirm(`Kurangi ${formatNum(total)} ${lotReconcile.row.unit} dari lot terpilih pada ${lotReconcile.row.stackCode}? Stok master tidak akan berubah lagi.`)) return;
    setSaving(true);
    try {
      const response = await api.post(`/stock-opnames/${selected.id}/reconcile-lots`, { items, note: lotReconcile.note || '' });
      replaceOpname(response.data);
      setLotReconcile(null);
      if (response.data?.lotSyncStatus === 'SYNCED') toast.success('Rekonsiliasi lot selesai. Subledger lot sekarang sinkron dengan hasil stock opname.');
      else toast.success('Koreksi lot tersimpan. Masih ada selisih multi-lot yang perlu ditentukan.');
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const differenceCount = (selected?.lines || []).filter((line) => Math.abs(Number(line.difference || 0)) > 0.000001).length;
  const reconcileTotal = lotReconcile ? Object.values(lotReconcile.quantities || {}).reduce((sum, value) => sum + Number(value || 0), 0) : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><div className="label-mono mb-2">Physical Stock Check</div><h1 className="font-display text-4xl font-bold">Stock Opname GBB / MP1</h1></div>
        <button onClick={() => load()} className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm"><RefreshCcw size={16} /> Muat Ulang</button>
      </div>

      {canEdit && <div className="card-surface p-5 flex flex-wrap items-end gap-3"><div><label className="text-xs text-[#8b93a1] block mb-1">GBB / Warehouse</label><select value={warehouse} onChange={(e) => setWarehouse(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 min-w-[150px]">{warehouseCodes.map((code) => <option key={code}>{code}</option>)}</select></div><button disabled={saving} onClick={createOpname} className="btn-primary px-4 py-2.5 rounded-lg text-sm font-semibold inline-flex items-center gap-2"><ClipboardCheck size={16} /> Buat Snapshot Opname</button></div>}

      <div className="grid grid-cols-1 xl:grid-cols-[310px_1fr] gap-5">
        <div className="card-surface p-3 max-h-[720px] overflow-y-auto">
          {loading ? <div className="p-6 text-center text-[#8b93a1]">Memuat...</div> : opnames.length === 0 ? <div className="p-6 text-center text-[#8b93a1]">Belum ada stock opname.</div> : <div className="space-y-2">{opnames.map((item) => <button key={item.id} onClick={() => setSelectedId(item.id)} className={`w-full text-left rounded-xl border p-3 ${selectedId === item.id ? 'border-[#2563eb] bg-[#2563eb]/10' : 'border-[#1a222e] bg-[#0b0f17]'}`}><div className="flex justify-between gap-2"><span className="font-mono text-xs font-semibold">{item.no}</span><span className={`text-[9px] border rounded-full px-2 py-0.5 ${statusClass(item.status)}`}>{item.status}</span></div><div className="text-sm font-semibold mt-2">GBB {item.warehouse}</div><div className="text-[10px] text-[#6b7688] mt-1">{(item.lines || []).length} tumpukan/produk · {item.createdBy}</div>{item.snapshotStale && <div className="mt-2 text-[9px] text-[#f87171]">Snapshot kedaluwarsa · batalkan & buat ulang</div>}{item.lotSyncStatus === 'RECONCILIATION_REQUIRED' && <div className="mt-2 text-[9px] text-[#fbbf24]">Lot perlu rekonsiliasi</div>}</button>)}</div>}
        </div>

        <div className="card-surface p-5 min-w-0">
          {!selected ? <div className="py-16 text-center text-[#8b93a1]">Pilih stock opname di sebelah kiri.</div> : <>
            <div className="flex flex-wrap items-start justify-between gap-3 mb-4"><div><div className="flex flex-wrap items-center gap-2"><h2 className="font-display text-xl font-bold">{selected.no}</h2><span className={`text-[10px] border rounded-full px-2 py-1 ${statusClass(selected.status)}`}>{selected.status}</span>{selected.status === 'APPROVED' && selected.lotSyncStatus && <span className={`text-[10px] border rounded-full px-2 py-1 ${lotStatusClass(selected.lotSyncStatus)}`}>LOT: {selected.lotSyncStatus}</span>}</div><p className="text-xs text-[#8b93a1] mt-1">GBB {selected.warehouse} · dibuat {selected.createdBy}</p></div><div className="flex gap-2"><div className="rounded-lg bg-[#0b0f17] px-3 py-2 text-xs"><span className="text-[#8b93a1]">Baris diperiksa</span><div className="font-mono text-lg font-bold">{(selected.lines || []).length}</div></div><div className="rounded-lg bg-[#0b0f17] px-3 py-2 text-xs"><span className="text-[#8b93a1]">Baris selisih</span><div className={`font-mono text-lg font-bold ${differenceCount ? 'text-[#fbbf24]' : 'text-[#4ade80]'}`}>{differenceCount}</div></div></div></div>

            {selected.snapshotStale && <div className="mb-4 rounded-xl border border-[#7f1d1d] bg-[#2a0f14] p-4 flex items-start gap-3"><AlertTriangle size={18} className="text-[#f87171] shrink-0 mt-0.5" /><div><div className="font-semibold text-[#fecaca]">Snapshot opname sudah kedaluwarsa</div><p className="text-xs text-[#fca5a5] mt-1">Saldo sistem berubah setelah snapshot dibuat. Jangan ajukan opname ini. Batalkan draft lalu buat snapshot baru agar transaksi terbaru tidak tertimpa.</p></div></div>}

            <div className="overflow-x-auto max-h-[560px]">
              <table className="w-full text-sm tbl"><thead className="sticky top-0 bg-[#0d121b]"><tr className="text-left border-b border-[#1a222e]">{['Tumpukan', 'Produk', 'Sistem', 'Fisik', 'Selisih', 'Saluran', 'Catatan'].map((h) => <th key={h} className="py-2.5 pr-3 whitespace-nowrap">{h}</th>)}</tr></thead><tbody>{(selected.lines || []).map((line) => {
                const diff = Number(line.physicalQty || 0) - Number(line.systemQty || 0);
                const editable = selected.status === 'DRAFT' && canEdit;
                return <tr key={line.allocationId} className="border-b border-[#131a24]"><td className="py-2.5 pr-3 font-mono text-xs">{line.stackCode}</td><td className="py-2.5 pr-3"><div>{line.product}</div><div className="label-mono text-[9px]">{line.sku}</div></td><td className="py-2.5 pr-3 font-mono whitespace-nowrap">{formatNum(line.systemQty)} {line.unit}</td><td className="py-2.5 pr-3"><input disabled={!editable} type="number" min="0" step="any" value={line.physicalQty} onChange={(e) => patchLine(line.allocationId, { physicalQty: e.target.value })} className="w-28 bg-[#0b0f17] border border-[#242f3d] rounded px-2 py-1.5 font-mono disabled:opacity-70" /></td><td className={`py-2.5 pr-3 font-mono ${Math.abs(diff) > 0.000001 ? 'text-[#fbbf24]' : 'text-[#4ade80]'}`}>{diff > 0 ? '+' : ''}{formatNum(diff)} {line.unit}</td><td className="py-2.5 pr-3"><select disabled={!editable || Math.abs(diff) <= 0.000001} value={line.channel || 'KOM'} onChange={(e) => patchLine(line.allocationId, { channel: e.target.value })} className="bg-[#0b0f17] border border-[#242f3d] rounded px-2 py-1.5 text-xs disabled:opacity-60"><option value="PSO">PSO</option><option value="KOM">KOM</option></select></td><td className="py-2.5 pr-3"><input disabled={!editable} value={line.note || ''} onChange={(e) => patchLine(line.allocationId, { note: e.target.value })} className="min-w-[160px] bg-[#0b0f17] border border-[#242f3d] rounded px-2 py-1.5 text-xs disabled:opacity-60" placeholder="Opsional" /></td></tr>;
              })}</tbody></table>
            </div>

            {selected.status === 'APPROVED' && selected.lotSyncStatus === 'RECONCILIATION_REQUIRED' && <div className="mt-5 rounded-xl border border-[#78350f] bg-[#1d1308] p-4"><div className="flex items-start gap-3"><AlertTriangle size={18} className="text-[#fbbf24] shrink-0 mt-0.5" /><div className="flex-1"><div className="font-semibold text-[#fde68a]">Rekonsiliasi lot diperlukan</div><p className="text-xs text-[#d6b873] mt-1">Stok master dan tumpukan sudah mengikuti hasil opname. Tentukan batch/lot mana yang berkurang agar histori FEFO tidak salah. Sistem tidak akan mengurangi stok master untuk kedua kalinya.</p></div></div><div className="mt-3 space-y-2">{(selected.lotReconciliation || []).map((row) => <div key={`${row.productId}-${row.stackCode}`} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[#513716] bg-[#0b0f17] p-3"><div><div className="text-sm font-semibold">{row.product}</div><div className="text-[10px] text-[#d6b873] font-mono">{row.stackCode} · {row.activeLots} lot aktif</div></div><div className="text-right"><div className="text-xs text-[#d6b873]">Belum dialokasikan ke lot</div><div className="font-mono font-semibold text-[#fbbf24]">{formatNum(row.qty)} {row.unit}</div></div>{canApprove && <button disabled={saving || lotLoading} onClick={() => openLotReconcile(row)} className="px-3 py-2 rounded-lg border border-[#d97706] text-[#fbbf24] text-xs font-semibold">Pilih Lot</button>}</div>)}</div></div>}

            {selected.status === 'APPROVED' && selected.lotSyncStatus === 'ERROR' && <div className="mt-5 rounded-xl border border-[#7f1d1d] bg-[#2a0f14] p-4 flex flex-wrap items-center justify-between gap-3"><div><div className="font-semibold text-[#fecaca]">Sinkronisasi lot bermasalah</div><div className="text-xs text-[#fca5a5] mt-1">{selected.lotSyncNote || 'Periksa kembali subledger lot.'}</div></div>{canApprove && <button disabled={saving} onClick={syncLots} className="px-3 py-2 rounded-lg border border-[#ef4444] text-[#fca5a5] text-xs inline-flex items-center gap-2"><RefreshCcw size={14} /> Sinkronkan Ulang</button>}</div>}

            {selected.status === 'APPROVED' && selected.lotSyncStatus === 'SYNCED' && <div className="mt-5 rounded-xl border border-[#14532d] bg-[#0b1c13] p-3 text-xs text-[#86efac]">Subledger lot sinkron dengan hasil opname. {selected.lotReconciledBy ? `Rekonsiliasi terakhir oleh ${selected.lotReconciledBy}.` : ''}</div>}

            {lotReconcile && <div className="mt-5 rounded-xl border border-[#2563eb] bg-[#0d1728] p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="label-mono text-[9px]">Manual Lot Reconciliation</div><h3 className="font-display text-lg font-bold mt-1">{lotReconcile.row.product} · {lotReconcile.row.stackCode}</h3><p className="text-xs text-[#8fb8ef] mt-1">Selisih yang perlu dialokasikan: <b>{formatNum(lotReconcile.row.qty)} {lotReconcile.row.unit}</b>. Isi hanya lot yang secara fisik terbukti berkurang.</p></div><button type="button" onClick={() => setLotReconcile(null)} className="text-[#93c5fd]">×</button></div><div className="overflow-x-auto mt-4"><table className="w-full text-sm tbl"><thead><tr className="text-left border-b border-[#1f3657]">{['Lot', 'Expired', 'Sisa lot', 'Kurangi karena opname'].map((h) => <th key={h} className="py-2 pr-3 whitespace-nowrap">{h}</th>)}</tr></thead><tbody>{(lotReconcile.lots || []).map((lot) => <tr key={lot.id} className="border-b border-[#15243a]"><td className="py-2.5 pr-3"><div className="font-mono text-xs">{lot.lotCode}</div><div className="text-[9px] text-[#6b7688]">{lot.sourceRef || '—'}</div></td><td className="py-2.5 pr-3 font-mono text-xs">{lot.exp || 'Tanpa expired'}</td><td className="py-2.5 pr-3 font-mono">{formatNum(lot.remainingQty)} {lot.unit}</td><td className="py-2.5 pr-3"><input type="number" min="0" max={Number(lot.remainingQty || 0)} step="any" value={lotReconcile.quantities?.[lot.id] ?? ''} onChange={(e) => patchLotQty(lot.id, e.target.value)} className="w-36 bg-[#0b0f17] border border-[#2b3b52] rounded px-2 py-1.5 font-mono" /></td></tr>)}</tbody></table></div><div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3 items-end mt-4"><div><label className="text-xs text-[#8fb8ef] block mb-1">Catatan / dasar pemeriksaan batch</label><input value={lotReconcile.note || ''} onChange={(e) => setLotReconcile((prev) => ({ ...prev, note: e.target.value }))} placeholder="Contoh: hasil hitung batch fisik / kartu tumpukan" className="w-full bg-[#0b0f17] border border-[#2b3b52] rounded-lg px-3 py-2 text-sm" /></div><div className="text-right"><div className={`font-mono text-sm ${reconcileTotal > Number(lotReconcile.row.qty || 0) ? 'text-[#ef4444]' : 'text-[#60a5fa]'}`}>{formatNum(reconcileTotal)} / {formatNum(lotReconcile.row.qty)} {lotReconcile.row.unit}</div><button disabled={saving || reconcileTotal <= 0 || reconcileTotal > Number(lotReconcile.row.qty || 0) + 0.000001} onClick={submitLotReconcile} className="mt-2 px-4 py-2.5 rounded-lg bg-[#2563eb] text-white text-sm font-semibold disabled:opacity-50">Simpan Rekonsiliasi Lot</button></div></div></div>}

            <div className="flex flex-wrap justify-end gap-2 pt-4 border-t border-[#1a222e] mt-4">
              {selected.status === 'DRAFT' && canEdit && <><button disabled={saving} onClick={cancelDraft} className="px-4 py-2 rounded-lg border border-[#7f1d1d] text-[#fca5a5] text-sm inline-flex items-center gap-2"><XCircle size={15} /> Batalkan Draft</button><button disabled={saving || selected.snapshotStale} onClick={saveDraft} className="px-4 py-2 rounded-lg border border-[#2a3443] text-sm inline-flex items-center gap-2 disabled:opacity-50"><Save size={15} /> Simpan Draft</button><button disabled={saving || selected.snapshotStale} onClick={submitOpname} className="px-4 py-2 rounded-lg bg-[#2563eb] text-white text-sm font-semibold inline-flex items-center gap-2 disabled:opacity-50"><Send size={15} /> Ajukan</button></>}
              {selected.status === 'SUBMITTED' && canApprove && <><button disabled={saving} onClick={reject} className="px-4 py-2 rounded-lg border border-[#7f1d1d] text-[#fca5a5] text-sm inline-flex items-center gap-2"><XCircle size={15} /> Tolak</button><button disabled={saving} onClick={approve} className="px-4 py-2 rounded-lg bg-[#15803d] text-white text-sm font-semibold inline-flex items-center gap-2"><CheckCircle2 size={15} /> Setujui & Adjustment</button></>}
              {selected.status === 'APPROVED' && <div className="text-xs text-[#86efac]">Disetujui oleh {selected.approvedBy} · adjustment operation {selected.adjustmentOperationId || '—'}</div>}
              {selected.status === 'REJECTED' && <div className="text-xs text-[#fca5a5]">Ditolak oleh {selected.rejectedBy}: {selected.rejectionNote || '—'}</div>}
              {selected.status === 'CANCELLED' && <div className="text-xs text-[#cbd5e1]">Dibatalkan oleh {selected.cancelledBy}: {selected.cancellationNote || '—'}</div>}
            </div>
          </>}
        </div>
      </div>
    </div>
  );
};

export default OpnameGudang;
