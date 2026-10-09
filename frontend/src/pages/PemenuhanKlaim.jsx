import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, History, PackageCheck, RefreshCcw, Scale, X } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError } from '../lib/api';

const inputCls = 'w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';
const fmt = (value, digits = 2) => Number(value || 0).toLocaleString('id-ID', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const methodLabel = (value) => ({
  TAMBAHAN_FISIK: 'Tambahan Fisik',
  GANTI_KARUNG: 'Ganti Karung',
  ADMINISTRATIF: 'Administratif',
}[value] || value || '-');

const statusBadge = (status) => {
  if (status === 'SELESAI') return 'border-[#166534] bg-[#14532d]/20 text-[#86efac]';
  if (status === 'DIPENUHI_SEBAGIAN') return 'border-[#92400e] bg-[#78350f]/20 text-[#fbbf24]';
  return 'border-[#7f1d1d] bg-[#450a0a]/20 text-[#fca5a5]';
};

const PemenuhanKlaim = () => {
  const [claims, setClaims] = useState([]);
  const [stackCodes, setStackCodes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCompleted, setShowCompleted] = useState(false);
  const [modal, setModal] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [claimsRes, optionsRes] = await Promise.all([
        api.get('/inbound-shortage-claims'),
        api.get('/inbound-shortage-claim-options'),
      ]);
      setClaims(claimsRes.data || []);
      setStackCodes(optionsRes.data?.stackCodes || []);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const openClaims = useMemo(() => claims.filter((x) => Number(x.remainingWeightKg || 0) > 1e-9), [claims]);
  const completedClaims = useMemo(() => claims.filter((x) => Number(x.remainingWeightKg || 0) <= 1e-9), [claims]);
  const totalOutstanding = useMemo(() => openClaims.reduce((sum, x) => sum + Number(x.remainingWeightKg || 0), 0), [openClaims]);
  const totalClaim = useMemo(() => claims.reduce((sum, x) => sum + Number(x.shortageWeightKg || 0), 0), [claims]);
  const totalSettled = useMemo(() => claims.reduce((sum, x) => sum + Number(x.settledWeightKg || 0), 0), [claims]);

  const openSettlement = (claim) => {
    setModal({
      claim,
      method: 'TAMBAHAN_FISIK',
      fulfilledWeightKg: String(Number(claim.remainingWeightKg || 0)),
      stackCode: claim.sourceStackCode || '',
      replacementBagCount: '',
      withdrawnOldWeightKg: '',
      referenceNo: '',
      note: '',
    });
  };

  const setMethod = (method) => {
    if (!modal) return;
    setModal({
      ...modal,
      method,
      fulfilledWeightKg: method === 'GANTI_KARUNG' ? '' : String(Number(modal.claim.remainingWeightKg || 0)),
      stackCode: modal.claim.sourceStackCode || modal.stackCode || '',
      replacementBagCount: '',
      withdrawnOldWeightKg: '',
      note: '',
    });
  };

  const replacementFulfilled = modal?.method === 'GANTI_KARUNG'
    ? Math.max(Number(modal.replacementBagCount || 0) * 50 - Number(modal.withdrawnOldWeightKg || 0), 0)
    : 0;

  const submit = async () => {
    if (!modal) return;
    const remaining = Number(modal.claim.remainingWeightKg || 0);
    const payload = {
      method: modal.method,
      fulfilledWeightKg: Number(modal.fulfilledWeightKg || 0),
      stackCode: modal.stackCode || '',
      replacementBagCount: Number(modal.replacementBagCount || 0),
      withdrawnOldWeightKg: Number(modal.withdrawnOldWeightKg || 0),
      referenceNo: modal.referenceNo.trim(),
      note: modal.note.trim(),
    };

    const amount = modal.method === 'GANTI_KARUNG' ? replacementFulfilled : payload.fulfilledWeightKg;
    if (amount <= 0) return toast.error('Jumlah pemenuhan harus lebih dari 0 kg');
    if (amount > remaining + 1e-9) return toast.error(`Pemenuhan melebihi sisa klaim ${fmt(remaining)} kg`);
    if (modal.method !== 'ADMINISTRATIF' && !payload.stackCode) return toast.error('Pilih tumpukan tujuan');
    if (modal.method === 'GANTI_KARUNG' && (!payload.replacementBagCount || !payload.withdrawnOldWeightKg)) {
      return toast.error('Isi jumlah karung pengganti dan berat karung lama yang ditarik');
    }
    if (modal.method === 'ADMINISTRATIF' && payload.note.length < 3) {
      return toast.error('Catatan penyelesaian administratif wajib diisi');
    }

    setSaving(true);
    try {
      const key = `pemenuhan-klaim-${modal.claim.id}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const { data } = await api.post(
        `/inbound-shortage-claims/${modal.claim.id}/settle`,
        payload,
        { headers: { 'X-Idempotency-Key': key } },
      );
      toast.success(data.message || 'Pemenuhan klaim berhasil disimpan');
      setModal(null);
      await load();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  const ClaimCard = ({ claim }) => {
    const remaining = Number(claim.remainingWeightKg || 0);
    const history = claim.settlementHistory || [];
    return <div className="card-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-bold text-[#93c5fd]">{claim.claimNo}</span>
            <span className={`rounded-full border px-2 py-1 text-[10px] font-semibold ${statusBadge(claim.status)}`}>
              {String(claim.status || '').replaceAll('_', ' ')}
            </span>
          </div>
          <div className="text-sm font-semibold mt-2">{claim.product}</div>
          <div className="text-xs text-[#8b93a1] mt-1">
            {claim.poNo || 'Tanpa TM/PO'} · {claim.supplier || '-'}{claim.polisi ? ` · ${claim.polisi}` : ''}
          </div>
          <div className="text-xs text-[#64748b] mt-1">
            {claim.sourceStackCode ? `Tumpukan asal ${claim.sourceStackCode} · ` : ''}{claim.operationalDate || ''}
          </div>
        </div>
        {remaining > 1e-9 && <button onClick={() => openSettlement(claim)} className="btn-primary inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold">
          <PackageCheck size={15}/> Proses Pemenuhan
        </button>}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-4">
        <div className="rounded-lg border border-[#243044] p-3"><div className="text-[10px] text-[#8b93a1]">Klaim Awal</div><div className="font-mono font-bold mt-1">{fmt(claim.shortageWeightKg)} kg</div></div>
        <div className="rounded-lg border border-[#243044] p-3"><div className="text-[10px] text-[#8b93a1]">Sudah Dipenuhi</div><div className="font-mono font-bold text-[#86efac] mt-1">{fmt(claim.settledWeightKg)} kg</div></div>
        <div className="rounded-lg border border-[#243044] p-3"><div className="text-[10px] text-[#8b93a1]">Sisa Klaim</div><div className="font-mono font-bold text-[#fbbf24] mt-1">{fmt(remaining)} kg</div></div>
        <div className="rounded-lg border border-[#243044] p-3"><div className="text-[10px] text-[#8b93a1]">Karung Tidak Utuh</div><div className="font-mono font-bold mt-1">{Number(claim.shortBagCount || 0)} karung</div></div>
      </div>

      {history.length > 0 && <div className="mt-4 border-t border-[#1f2937] pt-3">
        <div className="text-xs font-semibold flex items-center gap-2 mb-2"><History size={14}/> Riwayat Pemenuhan</div>
        <div className="space-y-2">
          {[...history].reverse().map((row) => <div key={row.id || row.settlementNo} className="rounded-lg bg-[#0b0f17] border border-[#1f2937] px-3 py-2 text-xs">
            <div className="flex flex-wrap justify-between gap-2">
              <span className="font-medium">{row.settlementNo || row.referenceNo || '-'} · {methodLabel(row.method)}</span>
              <span className="font-mono text-[#86efac]">{fmt(row.fulfilledWeightKg)} kg</span>
            </div>
            <div className="text-[#8b93a1] mt-1">
              {row.time ? new Date(row.time).toLocaleString('id-ID') : '-'} · {row.operator || '-'}
              {row.stackCode ? ` · ${row.stackCode}` : ''}
            </div>
            {row.method === 'GANTI_KARUNG' && <div className="text-[#8b93a1] mt-1">
              {row.replacementBagCount || 0} karung × 50 kg, berat lama ditarik {fmt(row.withdrawnOldWeightKg)} kg
            </div>}
            {row.note && <div className="text-[#cbd5e1] mt-1">{row.note}</div>}
          </div>)}
        </div>
      </div>}
    </div>;
  };

  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <div className="label-mono mb-2">Operasional Penerimaan</div>
        <h1 className="font-display text-3xl sm:text-4xl font-bold">Pemenuhan Klaim Kekurangan</h1>
        <p className="text-sm text-[#8b93a1] mt-2">Penyelesaian kekurangan timbang beras 50 kg setelah TM/PO penerimaan selesai. TM/PO asal tidak diubah.</p>
      </div>
      <button onClick={load} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-[#294263] px-3 py-2 text-xs text-[#93c5fd] disabled:opacity-50">
        <RefreshCcw size={14} className={loading ? 'animate-spin' : ''}/> Refresh
      </button>
    </div>

    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      <div className="card-surface p-4"><div className="text-xs text-[#8b93a1]">Total Klaim</div><div className="font-display text-2xl font-bold mt-1">{fmt(totalClaim)} kg</div></div>
      <div className="card-surface p-4"><div className="text-xs text-[#8b93a1]">Sudah Dipenuhi</div><div className="font-display text-2xl font-bold mt-1 text-[#22c55e]">{fmt(totalSettled)} kg</div></div>
      <div className="card-surface p-4"><div className="text-xs text-[#8b93a1]">Belum Dipenuhi</div><div className="font-display text-2xl font-bold mt-1 text-[#f59e0b]">{fmt(totalOutstanding)} kg</div></div>
    </div>

    <div className="rounded-xl border border-[#854d0e] bg-[#451a03]/20 px-4 py-3 text-xs text-[#fbbf24] flex gap-2">
      <AlertTriangle size={16} className="shrink-0 mt-0.5"/>
      <div><b>Tambahan Fisik</b> menambah stok sebesar kg yang diterima. <b>Ganti Karung</b> menambah hanya selisih antara karung 50 kg pengganti dan berat karung lama yang ditarik. <b>Administratif</b> menyelesaikan klaim tanpa menambah stok.</div>
    </div>

    <section>
      <div className="flex items-center gap-2 mb-3"><Scale size={18}/><h2 className="font-display text-xl font-bold">Klaim Aktif</h2><span className="text-xs text-[#8b93a1]">({openClaims.length})</span></div>
      {loading ? <div className="card-surface p-10 text-center text-[#8b93a1]">Memuat klaim...</div> :
        <div className="space-y-3">{openClaims.length ? openClaims.map((claim) => <ClaimCard key={claim.id} claim={claim}/>) : <div className="card-surface p-8 text-center text-[#86efac]"><CheckCircle2 className="mx-auto mb-2" size={24}/>Tidak ada klaim kekurangan yang belum diselesaikan.</div>}</div>}
    </section>

    {completedClaims.length > 0 && <section>
      <button onClick={() => setShowCompleted((v) => !v)} className="flex items-center gap-2 text-sm font-semibold text-[#93c5fd]">
        <History size={16}/>{showCompleted ? 'Sembunyikan' : 'Tampilkan'} Klaim Selesai ({completedClaims.length})
      </button>
      {showCompleted && <div className="space-y-3 mt-3">{completedClaims.map((claim) => <ClaimCard key={claim.id} claim={claim}/>)}</div>}
    </section>}

    {modal && <div className="fixed inset-0 z-[100] bg-black/75 overflow-y-auto flex items-start justify-center p-4 sm:py-6">
      <div className="card-surface w-full max-w-2xl p-6">
        <div className="flex justify-between gap-3">
          <div>
            <h2 className="font-display text-xl font-bold">Pemenuhan {modal.claim.claimNo}</h2>
            <p className="text-xs text-[#8b93a1] mt-1">{modal.claim.poNo} · {modal.claim.product}</p>
            <p className="text-xs text-[#fbbf24] mt-1">Sisa klaim: <b>{fmt(modal.claim.remainingWeightKg)} kg</b></p>
          </div>
          <button onClick={() => setModal(null)} className="p-2 rounded-lg border border-[#242f3d] h-fit"><X size={16}/></button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-5">
          {[
            ['TAMBAHAN_FISIK','Tambahan Fisik'],
            ['GANTI_KARUNG','Ganti Karung'],
            ['ADMINISTRATIF','Administratif'],
          ].map(([value,label]) => <button key={value} type="button" onClick={() => setMethod(value)}
            className={`rounded-lg border px-3 py-2.5 text-xs font-semibold ${modal.method === value ? 'border-[#2563eb] bg-[#2563eb]/15 text-[#93c5fd]' : 'border-[#374151] text-[#cbd5e1]'}`}>
            {label}
          </button>)}
        </div>

        {modal.method === 'TAMBAHAN_FISIK' && <div className="space-y-3 mt-4">
          <div className="rounded-lg border border-[#1d4ed8]/50 bg-[#1e3a8a]/10 px-3 py-2 text-xs text-[#bfdbfe]">Gunakan bila pengirim mengirim tambahan beras untuk menutup kekurangan. Stok bertambah tepat sebesar berat yang diterima.</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div><label className="text-xs text-[#8b93a1] block mb-1.5">Berat pemenuhan (kg)</label><input type="number" min="0.01" step="0.01" className={inputCls} value={modal.fulfilledWeightKg} onChange={(e) => setModal({...modal, fulfilledWeightKg:e.target.value})}/></div>
            <div><label className="text-xs text-[#8b93a1] block mb-1.5">Tumpukan tujuan</label><input list="claim-stack-codes" className={inputCls} value={modal.stackCode} onChange={(e) => setModal({...modal,stackCode:e.target.value.toUpperCase()})} placeholder="Contoh 22/A03"/></div>
          </div>
          <div className="text-xs text-[#8b93a1]">Setara penambahan stok: <b className="text-[#e5e7eb]">{fmt(Number(modal.fulfilledWeightKg || 0) / 50, 4)} {modal.claim.unit}</b>.</div>
        </div>}

        {modal.method === 'GANTI_KARUNG' && <div className="space-y-3 mt-4">
          <div className="rounded-lg border border-[#854d0e] bg-[#451a03]/20 px-3 py-2 text-xs text-[#fbbf24]">Gunakan bila karung kurang timbang ditarik pengirim lalu diganti karung utuh 50 kg. Sistem hanya menambah selisih bersih agar stok tidak dihitung ganda.</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div><label className="text-xs text-[#8b93a1] block mb-1.5">Jumlah karung pengganti 50 kg</label><input type="number" min="1" step="1" className={inputCls} value={modal.replacementBagCount} onChange={(e) => setModal({...modal,replacementBagCount:e.target.value})}/></div>
            <div><label className="text-xs text-[#8b93a1] block mb-1.5">Total berat karung lama yang ditarik (kg)</label><input type="number" min="0.01" step="0.01" className={inputCls} value={modal.withdrawnOldWeightKg} onChange={(e) => setModal({...modal,withdrawnOldWeightKg:e.target.value})}/></div>
          </div>
          <div className="rounded-lg border border-[#243044] p-3 text-sm">
            Perhitungan: <b>{Number(modal.replacementBagCount || 0)} × 50 kg</b> − <b>{fmt(modal.withdrawnOldWeightKg)} kg</b> = <b className="text-[#86efac]">{fmt(replacementFulfilled)} kg pemenuhan</b>
          </div>
          <div><label className="text-xs text-[#8b93a1] block mb-1.5">Tumpukan asal/penggantian</label><input list="claim-stack-codes" className={inputCls} value={modal.stackCode} onChange={(e) => setModal({...modal,stackCode:e.target.value.toUpperCase()})} placeholder="Tumpukan asal"/></div>
          {modal.claim.sourceStackCode && <div className="text-xs text-[#8b93a1]">Untuk menjaga saldo benar, penggantian karung diselesaikan pada tumpukan asal <b className="text-[#e5e7eb]">{modal.claim.sourceStackCode}</b>.</div>}
        </div>}

        {modal.method === 'ADMINISTRATIF' && <div className="space-y-3 mt-4">
          <div className="rounded-lg border border-[#7f1d1d] bg-[#450a0a]/20 px-3 py-2 text-xs text-[#fca5a5]"><b>Tidak menambah stok fisik.</b> Gunakan hanya jika klaim diselesaikan secara administratif/kompensasi dan barang tidak diterima kembali.</div>
          <div><label className="text-xs text-[#8b93a1] block mb-1.5">Berat klaim yang diselesaikan (kg)</label><input type="number" min="0.01" step="0.01" className={inputCls} value={modal.fulfilledWeightKg} onChange={(e) => setModal({...modal,fulfilledWeightKg:e.target.value})}/></div>
        </div>}

        <datalist id="claim-stack-codes">{stackCodes.map((code) => <option key={code} value={code}/>)}</datalist>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
          <div><label className="text-xs text-[#8b93a1] block mb-1.5">No. referensi pemenuhan (opsional)</label><input className={inputCls} value={modal.referenceNo} onChange={(e) => setModal({...modal,referenceNo:e.target.value})} placeholder="Kosong = nomor otomatis"/></div>
          <div><label className="text-xs text-[#8b93a1] block mb-1.5">Catatan {modal.method === 'ADMINISTRATIF' ? '(wajib)' : '(opsional)'}</label><input className={inputCls} value={modal.note} onChange={(e) => setModal({...modal,note:e.target.value})} placeholder="Keterangan pemenuhan"/></div>
        </div>

        <div className="flex justify-end gap-2 mt-5">
          <button disabled={saving} onClick={() => setModal(null)} className="px-4 py-2 rounded-lg border border-[#242f3d] disabled:opacity-50">Batal</button>
          <button disabled={saving} onClick={submit} className="btn-primary px-5 py-2 rounded-lg font-semibold disabled:opacity-50">{saving ? 'Menyimpan...' : 'Simpan Pemenuhan'}</button>
        </div>
      </div>
    </div>}
  </div>;
};

export default PemenuhanKlaim;
