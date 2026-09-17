import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { CheckCircle2, RefreshCcw, Save, ShieldAlert } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError } from '../lib/api';
import { useData } from '../context/DataContext';
import { formatNum } from '../mock';

const ADMIN_ROLES = new Set(['Administrator', 'Supervisor', 'Superadmin', 'Admin']);

const ReturnLotReconciliationPanel = ({ onChanged }) => {
  const { user } = useData();
  const canReconcile = ADMIN_ROLES.has(user?.role);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState('');
  const [forms, setForms] = useState({});

  const load = useCallback(async () => {
    if (!canReconcile) return;
    setLoading(true);
    try {
      const { data } = await api.get('/return-lot-reconciliations/pending');
      setRows(data || []);
      setForms((current) => {
        const next = { ...current };
        (data || []).forEach((row) => {
          if (!next[row.id]) next[row.id] = { qty: Number(row.remainingQty || 0), lotCode: '', exp: '', note: '' };
        });
        return next;
      });
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLoading(false);
    }
  }, [canReconcile]);

  useEffect(() => { load(); }, [load]);

  const totalPending = useMemo(() => rows.reduce((sum, row) => sum + Number(row.remainingQty || 0), 0), [rows]);

  const patchForm = (id, patch) => setForms((current) => ({ ...current, [id]: { ...(current[id] || {}), ...patch } }));

  const submit = async (row) => {
    const form = forms[row.id] || {};
    const qty = Number(form.qty || 0);
    if (!form.lotCode?.trim()) return toast.error('Nomor batch / lot wajib diisi berdasarkan verifikasi fisik atau dokumen.');
    if (!(qty > 0)) return toast.error('Kuantum rekonsiliasi harus lebih dari 0.');
    if (qty > Number(row.remainingQty || 0) + 0.000001) return toast.error('Kuantum melebihi sisa retur yang belum direkonsiliasi.');

    setBusyId(row.id);
    try {
      const { data } = await api.post(`/return-lot-reconciliations/${row.id}`, {
        qty,
        lotCode: form.lotCode.trim(),
        exp: form.exp || '',
        note: form.note?.trim() || '',
      });
      toast.success(`Retur berhasil direkonsiliasi ke lot ${data.lotCode}. Stok fisik tidak berubah.`);
      await load();
      await onChanged?.();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusyId('');
    }
  };

  if (!canReconcile) return null;

  return (
    <section className="card-surface p-5 border border-[#6b3b16]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="label-mono text-[10px] text-[#fbbf24]">Verifikasi Retur Legacy</div>
          <h2 className="font-display text-2xl font-bold mt-1">Rekonsiliasi Batch / Expired Retur</h2>
          <p className="text-sm text-[#8b93a1] mt-1 max-w-3xl">Gunakan hanya setelah nomor batch/lot dan expired benar-benar diverifikasi dari fisik atau dokumen. Rekonsiliasi ini tidak menambah atau mengurangi stok fisik; hanya mengubah bagian untracked menjadi lot terverifikasi.</p>
        </div>
        <button type="button" onClick={load} disabled={loading} className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-[#59431f] text-sm text-[#fcd34d] disabled:opacity-50"><RefreshCcw size={15} className={loading ? 'animate-spin' : ''} /> Muat ulang</button>
      </div>

      <div className="mt-4 flex flex-wrap gap-3 text-xs">
        <div className="rounded-lg bg-[#0b0f17] border border-[#2a3442] px-3 py-2">Movement pending: <b className="font-mono">{rows.length}</b></div>
        <div className="rounded-lg bg-[#0b0f17] border border-[#6b3b16] px-3 py-2 text-[#fbbf24]">Total belum direkonsiliasi: <b className="font-mono">{formatNum(totalPending)}</b></div>
      </div>

      {loading ? <div className="py-8 text-center text-sm text-[#8b93a1]">Memuat retur pending...</div> : rows.length === 0 ? <div className="mt-4 rounded-xl border border-[#14532d] bg-[#14532d]/15 p-4 text-sm text-[#86efac] flex items-center gap-2"><CheckCircle2 size={17} />Tidak ada retur yang menunggu rekonsiliasi lot.</div> : <div className="mt-4 space-y-3">{rows.map((row) => {
        const form = forms[row.id] || {};
        const busy = busyId === row.id;
        return <div key={row.id} className="rounded-xl border border-[#342716] bg-[#0b0f17] p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><div className="font-semibold">{row.product || 'Produk'}</div><div className="font-mono text-[10px] text-[#93c5fd] mt-1">{row.sku || '—'} · {row.stackCode || '—'}</div><div className="text-xs text-[#8b93a1] mt-1">Retur: {row.returnDocument || '—'} · Sumber: {row.sourceDocument || '—'}</div></div>
            <div className="text-right"><div className="label-mono text-[9px]">Sisa Pending</div><div className="font-mono text-lg font-bold text-[#fbbf24]">{formatNum(row.remainingQty)} {row.unit}</div><div className="text-[10px] text-[#6b7688]">Asal {formatNum(row.originalQty)} · sudah {formatNum(row.reconciledQty)}</div></div>
          </div>

          <div className="mt-4 grid grid-cols-1 md:grid-cols-[.7fr_1fr_1fr] gap-3">
            <div><label className="text-xs text-[#8b93a1] block mb-1">Kuantum</label><input type="number" min="0.000001" max={Number(row.remainingQty || 0)} step="any" value={form.qty ?? ''} onChange={(e) => patchForm(row.id, { qty: e.target.value })} className="w-full bg-[#0d121b] border border-[#2a3442] rounded-lg px-3 py-2.5 font-mono" /></div>
            <div><label className="text-xs text-[#8b93a1] block mb-1">Nomor batch / lot</label><input value={form.lotCode || ''} onChange={(e) => patchForm(row.id, { lotCode: e.target.value })} placeholder="Contoh: LOT-240926-A" className="w-full bg-[#0d121b] border border-[#2a3442] rounded-lg px-3 py-2.5 font-mono" /></div>
            <div><label className="text-xs text-[#8b93a1] block mb-1">Expired <span className="text-[#6b7688]">(kosong bila memang tidak ada)</span></label><input type="date" value={form.exp || ''} onChange={(e) => patchForm(row.id, { exp: e.target.value })} className="w-full bg-[#0d121b] border border-[#2a3442] rounded-lg px-3 py-2.5" /></div>
          </div>
          <div className="mt-3 grid grid-cols-1 lg:grid-cols-[1fr_auto] gap-3 items-end">
            <div><label className="text-xs text-[#8b93a1] block mb-1">Catatan verifikasi</label><input value={form.note || ''} onChange={(e) => patchForm(row.id, { note: e.target.value })} placeholder="Sumber verifikasi batch/expired, kondisi label, atau keterangan lain" className="w-full bg-[#0d121b] border border-[#2a3442] rounded-lg px-3 py-2.5" /></div>
            <button type="button" disabled={busy || !form.lotCode?.trim() || !(Number(form.qty) > 0)} onClick={() => submit(row)} className="btn-primary px-4 py-2.5 rounded-lg inline-flex items-center justify-center gap-2 disabled:opacity-40"><Save size={15} />{busy ? 'Menyimpan...' : 'Rekonsiliasi'}</button>
          </div>
          <div className="mt-3 flex gap-2 text-[11px] text-[#fcd34d]"><ShieldAlert size={14} className="shrink-0" /><span>Jangan mengisi batch atau expired berdasarkan perkiraan. Jika belum terverifikasi, biarkan tetap legacy/untracked.</span></div>
        </div>;
      })}</div>}
    </section>
  );
};

export default ReturnLotReconciliationPanel;
