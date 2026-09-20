import React, { useEffect, useState } from 'react';
import { Archive, CheckCircle2, Download, RefreshCcw, ShieldAlert, Wrench } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError, downloadApiFile } from '../lib/api';

const ProductionSafetyPanel = () => {
  const [maintenance, setMaintenance] = useState(null);
  const [recovery, setRecovery] = useState(null);
  const [busy, setBusy] = useState('');

  const refresh = async () => {
    setBusy('refresh');
    try {
      const [m, r] = await Promise.all([
        api.get('/admin/maintenance'),
        api.get('/admin/recovery-status'),
      ]);
      setMaintenance(m.data);
      setRecovery(r.data);
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setBusy('');
    }
  };

  useEffect(() => { refresh(); }, []);

  const backup = async () => {
    setBusy('backup');
    try {
      const filename = 'pepeg_backup_' + new Date().toISOString().slice(0,10) + '.zip';
      await downloadApiFile('/admin/backups/export', filename);
      toast.success('Backup logis PEPEG berhasil dibuat. Simpan file di lokasi terpisah.');
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setBusy('');
    }
  };

  const toggleMaintenance = async () => {
    const next = !maintenance?.enabled;
    const message = next
      ? 'Aktifkan Maintenance Mode? Semua transaksi tulis akan ditolak sampai mode ini dimatikan.'
      : 'Buka kembali PEPEG untuk transaksi operasional?';
    if (!window.confirm(message)) return;
    setBusy('maintenance');
    try {
      const { data } = await api.post('/admin/maintenance', {
        enabled: next,
        note: next ? 'Maintenance operasional oleh Superadmin' : 'Operasional dibuka kembali',
      });
      setMaintenance(data);
      toast.success(next ? 'Maintenance Mode aktif' : 'PEPEG dibuka kembali');
      await refresh();
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setBusy('');
    }
  };

  return <div className="card-surface p-6 lg:col-span-2 border border-[#28415e]">
    <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
      <div>
        <div className="flex items-center gap-2"><ShieldAlert size={18} className="text-[#60a5fa]"/><h2 className="font-display text-lg font-bold">Production Safety & Recovery</h2></div>
        <p className="text-xs text-[#8b93a1] mt-2">Backup logis ditandatangani sistem. Restore hanya dapat dilakukan Superadmin saat Maintenance Mode aktif dan tidak ada pemuatan aktif.</p>
      </div>
      <button type="button" onClick={refresh} disabled={Boolean(busy)} className="inline-flex items-center gap-1.5 rounded-lg border border-[#243044] px-3 py-2 text-xs text-[#93c5fd] disabled:opacity-50"><RefreshCcw size={13} className={busy === 'refresh' ? 'animate-spin' : ''}/> Periksa</button>
    </div>

    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
      <div className="rounded-lg bg-[#0b0f17] border border-[#1b2635] p-3"><div className="label-mono text-[9px]">Maintenance</div><div className={"font-mono font-bold mt-1 " + (maintenance?.enabled ? 'text-[#fbbf24]' : 'text-[#4ade80]')}>{maintenance?.enabled ? 'AKTIF' : 'NONAKTIF'}</div></div>
      <div className="rounded-lg bg-[#0b0f17] border border-[#1b2635] p-3"><div className="label-mono text-[9px]">Pemuatan Aktif</div><div className="font-mono text-xl font-bold mt-1">{recovery?.activeLoads ?? '—'}</div></div>
      <div className="rounded-lg bg-[#0b0f17] border border-[#1b2635] p-3"><div className="label-mono text-[9px]">Retry Tersangkut</div><div className={"font-mono text-xl font-bold mt-1 " + (Number(recovery?.staleProcessingRequests || 0) ? 'text-[#f87171]' : 'text-[#4ade80]')}>{recovery?.staleProcessingRequests ?? '—'}</div></div>
      <div className="rounded-lg bg-[#0b0f17] border border-[#1b2635] p-3"><div className="label-mono text-[9px]">Post-commit Open</div><div className={"font-mono text-xl font-bold mt-1 " + (Number(recovery?.openPostCommitIssues || 0) ? 'text-[#f87171]' : 'text-[#4ade80]')}>{recovery?.openPostCommitIssues ?? '—'}</div></div>
    </div>

    <div className="flex flex-col sm:flex-row gap-2">
      <button type="button" onClick={backup} disabled={Boolean(busy)} className="btn-primary inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50"><Download size={15}/>{busy === 'backup' ? 'Membuat backup…' : 'Unduh Backup PEPEG'}</button>
      <button type="button" onClick={toggleMaintenance} disabled={Boolean(busy)} className={"inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold border disabled:opacity-50 " + (maintenance?.enabled ? 'border-[#22c55e]/50 text-[#4ade80]' : 'border-[#f59e0b]/50 text-[#fbbf24]')}><Wrench size={15}/>{maintenance?.enabled ? 'Buka Operasional' : 'Aktifkan Maintenance'}</button>
    </div>

    <div className="mt-4 rounded-lg border border-[#1f3a2c] bg-[#052e16]/10 p-3 text-xs text-[#86efac] flex items-start gap-2">
      <CheckCircle2 size={15} className="mt-0.5 shrink-0"/>
      <div><b>Prosedur Senin:</b> sebelum input stok besar, unduh satu backup. Simpan file ZIP di luar aplikasi. Maintenance Mode tidak perlu dinyalakan saat operasional normal.</div>
    </div>
    <div className="mt-2 text-[10px] text-[#6b7688] flex items-center gap-1.5"><Archive size={12}/> Backup berisi data sensitif termasuk akun ter-hash; jangan kirim file backup melalui grup umum.</div>
  </div>;
};

export default ProductionSafetyPanel;
