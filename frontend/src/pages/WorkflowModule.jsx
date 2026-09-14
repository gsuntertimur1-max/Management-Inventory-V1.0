import React, { useMemo, useState } from 'react';
import { BadgeCheck, ClipboardCheck, Factory, Save, Search } from 'lucide-react';
import { toast } from 'sonner';
import { useData } from '../context/DataContext';
import { apiError } from '../lib/api';
import { formatDate, formatNum } from '../mock';

const initialRepacking = { tmHasil: '', sourceProductId: '', sourceQty: '', resultProductId: '', resultQty: '', batch: '', expired: '', operator: '', note: '' };
const statusClass = {
  LULUS: 'bg-[#123520] text-[#4ade80] border-[#245b36]',
  TIDAK_LULUS: 'bg-[#3a1515] text-[#f87171] border-[#7f1d1d]',
  PENDING: 'bg-[#32260b] text-[#fbbf24] border-[#59431f]',
};

const WorkflowModule = ({ type }) => {
  const { products, repackingJobs, addRepackingJob, addQCInspection, user } = useData();
  const [form, setForm] = useState(initialRepacking);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [qcDraft, setQcDraft] = useState({});
  const sourceProduct = products.find((item) => item.id === form.sourceProductId);
  const resultProduct = products.find((item) => item.id === form.resultProductId);
  const shrinkage = Number(form.sourceQty || 0) - Number(form.resultQty || 0);
  const filteredJobs = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return repackingJobs;
    return repackingJobs.filter((job) => [job.tmHasil, job.sourceProductName, job.resultProductName, job.batch, job.qcStatus].filter(Boolean).join(' ').toLowerCase().includes(needle));
  }, [query, repackingJobs]);

  const saveRepacking = async () => {
    if (!form.tmHasil.trim() || !form.sourceProductId || !form.resultProductId) return toast.error('TM hasil, produk asal, dan produk hasil wajib diisi');
    if (Number(form.sourceQty) <= 0 || Number(form.resultQty) <= 0) return toast.error('Jumlah bahan dan hasil harus lebih dari nol');
    if (sourceProduct && Number(sourceProduct.stock || 0) < Number(form.sourceQty)) return toast.error('Stok bahan baku tidak cukup');
    setBusy(true);
    try {
      await addRepackingJob({ ...form, sourceQty: Number(form.sourceQty), resultQty: Number(form.resultQty), operator: form.operator || user?.name || '' });
      toast.success('Repacking tersimpan dan masuk antrean QC');
      setForm(initialRepacking);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const saveQC = async (job, status) => {
    const draft = qcDraft[job.id] || {};
    setBusy(true);
    try {
      await addQCInspection({ repackingId: job.id, status, inspector: draft.inspector || user?.name || '', reason: draft.reason || '' });
      toast.success(`QC ${status.replace('_', ' ')} tersimpan`);
      setQcDraft((prev) => ({ ...prev, [job.id]: {} }));
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const updateQCDraft = (id, patch) => setQcDraft((prev) => ({ ...prev, [id]: { ...(prev[id] || {}), ...patch } }));

  if (type === 'qc') {
    const pending = filteredJobs.filter((job) => job.qcStatus === 'PENDING');
    return (
      <div className="space-y-6">
        <div className="flex flex-col xl:flex-row xl:items-end xl:justify-between gap-4">
          <div><div className="label-mono mb-2">Quality Control</div><h1 className="font-display text-3xl md:text-4xl font-bold">QC Repacking</h1><p className="text-[#8b93a1] mt-2 max-w-3xl">Review hasil produksi ON_PROSES, putuskan lulus/reject/pending, dan saldo otomatis dipindahkan ke stok baik atau rusak.</p></div>
          <div className="grid grid-cols-3 gap-2 min-w-[320px]">{['PENDING', 'LULUS', 'TIDAK_LULUS'].map((status) => <div key={status} className="card-surface p-3"><div className="text-xs text-[#6b7688]">{status.replace('_', ' ')}</div><div className="font-display text-xl font-bold mt-1">{formatNum(repackingJobs.filter((job) => job.qcStatus === status).length)}</div></div>)}</div>
        </div>
        <div className="card-surface p-5">
          <div className="relative mb-4"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari TM, batch, produk, status..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm tbl">
              <thead><tr className="text-left border-b border-[#1a222e]"><th className="py-2.5 pr-4">TM / Batch</th><th className="py-2.5 pr-4">Produk Hasil</th><th className="py-2.5 pr-4">Qty</th><th className="py-2.5 pr-4">Status</th><th className="py-2.5 pr-4">Catatan QC</th><th className="py-2.5">Aksi</th></tr></thead>
              <tbody>
                {filteredJobs.map((job) => {
                  const draft = qcDraft[job.id] || {};
                  return <tr key={job.id} className="tbl-row border-b border-[#131a24] align-top">
                    <td className="py-3 pr-4"><div className="font-mono text-[#93c5fd]">{job.tmHasil || '-'}</div><div className="text-xs text-[#8b93a1] mt-1">{job.batch || 'Batch belum dicatat'} · {formatDate(job.created_at)}</div></td>
                    <td className="py-3 pr-4">{job.resultProductName}<div className="text-xs text-[#6b7688] mt-1">Dari {job.sourceProductName}</div></td>
                    <td className="py-3 pr-4 font-mono">{formatNum(job.resultQty)}<div className="text-xs text-[#fbbf24] mt-1">Susut {formatNum(job.shrinkage || 0)}</div></td>
                    <td className="py-3 pr-4"><span className={`text-xs px-2.5 py-1 rounded-full border ${statusClass[job.qcStatus] || statusClass.PENDING}`}>{(job.qcStatus || 'PENDING').replace('_', ' ')}</span></td>
                    <td className="py-3 pr-4 min-w-[240px]"><input value={draft.inspector || ''} onChange={(e) => updateQCDraft(job.id, { inspector: e.target.value })} placeholder={(user && user.name) || 'Pemeriksa'} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-xs mb-2" /><input value={draft.reason || ''} onChange={(e) => updateQCDraft(job.id, { reason: e.target.value })} placeholder="Catatan / alasan reject" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2 text-xs" /></td>
                    <td className="py-3"><div className="flex flex-wrap gap-2 min-w-[230px]"><button disabled={busy || job.qcStatus !== 'PENDING'} onClick={() => saveQC(job, 'LULUS')} className="px-3 py-2 rounded-lg border border-[#245b36] text-xs text-[#4ade80] disabled:opacity-40">Lulus</button><button disabled={busy || job.qcStatus !== 'PENDING'} onClick={() => saveQC(job, 'TIDAK_LULUS')} className="px-3 py-2 rounded-lg border border-[#7f1d1d] text-xs text-[#f87171] disabled:opacity-40">Reject</button><button disabled={busy || job.qcStatus !== 'PENDING'} onClick={() => saveQC(job, 'PENDING')} className="px-3 py-2 rounded-lg border border-[#59431f] text-xs text-[#fbbf24] disabled:opacity-40">Pending</button></div></td>
                  </tr>;
                })}
                {filteredJobs.length === 0 && <tr><td colSpan={6} className="py-8 text-center text-[#8b93a1]">Belum ada antrean QC. Input Repacking terlebih dahulu.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
        {pending.length > 0 && <div className="rounded-xl border border-[#59431f] bg-[#2a220f] p-4 text-sm text-[#fbbf24]"><BadgeCheck size={17} className="inline mr-2" />Ada {pending.length} hasil repacking yang masih menunggu keputusan QC.</div>}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div><div className="label-mono mb-2">Produksi / Rebagging</div><h1 className="font-display text-3xl md:text-4xl font-bold">Repacking</h1><p className="text-[#8b93a1] mt-2 max-w-3xl">Catat TM hasil, bahan baku, output produksi, batch, expired, susut, operator, lalu kirim otomatis ke QC.</p></div>
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_380px] gap-6">
        <div className="card-surface p-6">
          <h2 className="font-display text-xl font-bold mb-4 flex items-center gap-2"><Factory size={20} /> Form Repacking</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div><label className="text-sm block mb-1">TM Hasil</label><input value={form.tmHasil} onChange={(e) => setForm({ ...form, tmHasil: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" placeholder="TM-HASIL/..." /></div>
            <div><label className="text-sm block mb-1">Operator</label><input value={form.operator} onChange={(e) => setForm({ ...form, operator: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" placeholder={user?.name || 'Nama operator'} /></div>
            <div><label className="text-sm block mb-1">Produk Asal</label><select value={form.sourceProductId} onChange={(e) => setForm({ ...form, sourceProductId: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5"><option value="">Pilih bahan baku...</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name} · stok {formatNum(p.stock)} {p.unit}</option>)}</select></div>
            <div><label className="text-sm block mb-1">Jumlah Bahan</label><input type="number" min="0" value={form.sourceQty} onChange={(e) => setForm({ ...form, sourceQty: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 font-mono" /></div>
            <div><label className="text-sm block mb-1">Produk Hasil</label><select value={form.resultProductId} onChange={(e) => setForm({ ...form, resultProductId: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5"><option value="">Pilih hasil...</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
            <div><label className="text-sm block mb-1">Jumlah Hasil</label><input type="number" min="0" value={form.resultQty} onChange={(e) => setForm({ ...form, resultQty: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 font-mono" /></div>
            <div><label className="text-sm block mb-1">Batch Hasil</label><input value={form.batch} onChange={(e) => setForm({ ...form, batch: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /></div>
            <div><label className="text-sm block mb-1">Expired</label><input type="date" value={form.expired} onChange={(e) => setForm({ ...form, expired: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /></div>
          </div>
          <textarea value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} rows={2} placeholder="Catatan produksi, mesin kemas, atau kendala" className="w-full mt-4 bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" />
          <button disabled={busy} className="btn-primary mt-5 px-5 py-2.5 rounded-xl inline-flex items-center gap-2 disabled:opacity-50" onClick={saveRepacking}><Save size={16} />{busy ? 'Menyimpan...' : 'Simpan & Kirim QC'}</button>
        </div>
        <div className="card-surface p-6">
          <h2 className="font-display text-xl font-bold mb-4 flex items-center gap-2"><ClipboardCheck size={20} /> Ringkasan</h2>
          <div className="space-y-3 text-sm">
            <div className="rounded-lg bg-[#0b0f17] border border-[#1a222e] p-3"><div className="text-[#6b7688]">Stok bahan tersedia</div><div className="font-mono text-lg mt-1">{sourceProduct ? `${formatNum(sourceProduct.stock)} ${sourceProduct.unit}` : '-'}</div></div>
            <div className="rounded-lg bg-[#0b0f17] border border-[#1a222e] p-3"><div className="text-[#6b7688]">Hasil masuk status</div><div className="font-mono text-lg mt-1 text-[#fbbf24]">ON_PROSES</div></div>
            <div className={`rounded-lg border p-3 ${shrinkage >= 0 ? 'bg-[#0d1728] border-[#1f3657] text-[#93c5fd]' : 'bg-[#3a1515] border-[#7f1d1d] text-[#f87171]'}`}><div className="text-xs opacity-80">Susut / selisih</div><div className="font-mono text-lg mt-1">{formatNum(shrinkage)}</div></div>
            <div className="rounded-lg bg-[#0b0f17] border border-[#1a222e] p-3 text-xs text-[#8b93a1]">Produk hasil {resultProduct ? resultProduct.name : 'belum dipilih'} baru menjadi stok baik setelah QC lulus.</div>
          </div>
        </div>
      </div>
      <div className="card-surface p-6">
        <h2 className="font-display text-xl font-bold mb-4">Riwayat Repacking</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]"><th className="py-2.5 pr-4">Tanggal</th><th className="py-2.5 pr-4">TM / Batch</th><th className="py-2.5 pr-4">Bahan</th><th className="py-2.5 pr-4">Hasil</th><th className="py-2.5 pr-4">Susut</th><th className="py-2.5">QC</th></tr></thead>
            <tbody>
              {repackingJobs.slice(0, 12).map((job) => <tr key={job.id} className="tbl-row border-b border-[#131a24]"><td className="py-3 pr-4 whitespace-nowrap">{formatDate(job.created_at)}</td><td className="py-3 pr-4"><div className="font-mono text-[#93c5fd]">{job.tmHasil || '-'}</div><div className="text-xs text-[#8b93a1]">{job.batch || '-'}</div></td><td className="py-3 pr-4">{job.sourceProductName}<div className="font-mono text-xs text-[#6b7688]">{formatNum(job.sourceQty)}</div></td><td className="py-3 pr-4">{job.resultProductName}<div className="font-mono text-xs text-[#6b7688]">{formatNum(job.resultQty)}</div></td><td className="py-3 pr-4 font-mono">{formatNum(job.shrinkage || 0)}</td><td className="py-3"><span className={`text-xs px-2.5 py-1 rounded-full border ${statusClass[job.qcStatus] || statusClass.PENDING}`}>{(job.qcStatus || 'PENDING').replace('_', ' ')}</span></td></tr>)}
              {repackingJobs.length === 0 && <tr><td colSpan={6} className="py-8 text-center text-[#8b93a1]">Belum ada riwayat repacking.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default WorkflowModule;
