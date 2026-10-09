import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, History, PackageCheck, RefreshCcw, Scale, Truck, X } from 'lucide-react';
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
  const [groups, setGroups] = useState([]);
  const [stackCodes, setStackCodes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCompleted, setShowCompleted] = useState(false);
  const [expanded, setExpanded] = useState({});
  const [modal, setModal] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [groupsRes, optionsRes] = await Promise.all([
        api.get('/inbound-shortage-claim-groups'),
        api.get('/inbound-shortage-claim-options'),
      ]);
      setGroups(Array.isArray(groupsRes.data) ? groupsRes.data : []);
      setStackCodes(optionsRes.data?.stackCodes || []);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const openGroups = useMemo(() => groups.filter((x) => Number(x.remainingWeightKg || 0) > 1e-9), [groups]);
  const completedGroups = useMemo(() => groups.filter((x) => Number(x.remainingWeightKg || 0) <= 1e-9), [groups]);
  const totalOutstanding = useMemo(() => groups.reduce((sum, x) => sum + Number(x.remainingWeightKg || 0), 0), [groups]);
  const totalClaim = useMemo(() => groups.reduce((sum, x) => sum + Number(x.shortageWeightKg || 0), 0), [groups]);
  const totalSettled = useMemo(() => groups.reduce((sum, x) => sum + Number(x.settledWeightKg || 0), 0), [groups]);

  const openSettlement = (group, item) => {
    setModal({
      group,
      item,
      method: 'TAMBAHAN_FISIK',
      fulfilledWeightKg: String(Number(item.remainingWeightKg || 0)),
      stackCode: item.sourceStackCode || '',
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
      fulfilledWeightKg: method === 'GANTI_KARUNG' ? '' : String(Number(modal.item.remainingWeightKg || 0)),
      stackCode: modal.item.sourceStackCode || modal.stackCode || '',
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
    if (!modal.group.poId) return toast.error('TM/PO sumber belum memiliki ID pengadaan yang valid');
    const remaining = Number(modal.item.remainingWeightKg || 0);
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
      const key = `pemenuhan-tm-${modal.group.poId}-${modal.item.productId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const { data } = await api.post(
        `/inbound-shortage-claim-groups/${modal.group.poId}/${modal.item.productId}/settle`,
        payload,
        { headers: { 'X-Idempotency-Key': key } },
      );
      toast.success(data.message || 'Pemenuhan klaim TM berhasil disimpan');
      setModal(null);
      await load();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  const ItemBlock = ({ group, item }) => {
    const remaining = Number(item.remainingWeightKg || 0);
    const histories = item.settlementHistory || [];
    return <div className="rounded-xl border border-[#243044] bg-[#0b0f17]/60 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="font-semibold">{item.product}</div>
          <div className="font-mono text-[10px] text-[#8b93a1] mt-1">{item.sku} · {item.unit}</div>
        </div>
        {remaining > 1e-9 && <button onClick={() => openSettlement(group, item)} className="btn-primary inline-flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold">
          <PackageCheck size={15}/> Proses Pemenuhan
        </button>}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 mt-3">
        <div className="rounded-lg border border-[#243044] p-3"><div className="text-[10px] text-[#8b93a1]">Klaim TM</div><div className="font-mono font-bold mt-1">{fmt(item.shortageWeightKg)} kg</div></div>
        <div className="rounded-lg border border-[#243044] p-3"><div className="text-[10px] text-[#8b93a1]">Sudah Dipenuhi</div><div className="font-mono font-bold text-[#86efac] mt-1">{fmt(item.settledWeightKg)} kg</div></div>
        <div className="rounded-lg border border-[#243044] p-3"><div className="text-[10px] text-[#8b93a1]">Sisa Klaim</div><div className="font-mono font-bold text-[#fbbf24] mt-1">{fmt(item.remainingWeightKg)} kg</div></div>
        <div className="rounded-lg border border-[#243044] p-3"><div className="text-[10px] text-[#8b93a1]">Karung Tidak Utuh</div><div className="font-mono font-bold mt-1">{Number(item.shortBagCount || 0)} karung</div></div>
      </div>

      <div className="mt-4">
        <div className="text-xs font-semibold flex items-center gap-2 mb-2"><Truck size={14}/> Rincian Kendaraan</div>
        <div className="overflow-x-auto rounded-lg border border-[#1f2937]">
          <table className="w-full min-w-[820px] text-xs">
            <thead className="text-[#8b93a1] bg-[#0a0f17]"><tr>
              <th className="text-left p-2.5">Tanggal</th><th className="text-left p-2.5">No. Polisi</th><th className="text-left p-2.5">Klaim Detail</th><th className="text-left p-2.5">Tumpukan</th>
              <th className="text-right p-2.5">Karung</th><th className="text-right p-2.5">Seharusnya</th><th className="text-right p-2.5">Aktual</th><th className="text-right p-2.5">Kurang</th><th className="text-right p-2.5">Sisa</th>
            </tr></thead>
            <tbody>{(item.details || []).map((detail) => <tr key={detail.claimId} className="border-t border-[#1f2937]">
              <td className="p-2.5">{detail.operationalDate || '-'}</td>
              <td className="p-2.5 font-medium">{detail.polisi || '-'}</td>
              <td className="p-2.5 font-mono text-[10px]">{detail.claimNo || '-'}</td>
              <td className="p-2.5 font-mono">{detail.sourceStackCode || '-'}</td>
              <td className="p-2.5 text-right font-mono">{detail.shortBagCount || 0}</td>
              <td className="p-2.5 text-right font-mono">{fmt(detail.expectedWeightKg)} kg</td>
              <td className="p-2.5 text-right font-mono">{fmt(detail.actualWeightKg)} kg</td>
              <td className="p-2.5 text-right font-mono text-[#fca5a5]">{fmt(detail.shortageWeightKg)} kg</td>
              <td className="p-2.5 text-right font-mono text-[#fbbf24]">{fmt(detail.remainingWeightKg)} kg</td>
            </tr>)}</tbody>
          </table>
        </div>
        <div className="text-[10px] text-[#64748b] mt-2">Pemenuhan TM dialokasikan otomatis ke rincian kendaraan yang paling lama dan masih memiliki sisa klaim.</div>
      </div>

      {histories.length > 0 && <div className="mt-4 border-t border-[#1f2937] pt-3">
        <div className="text-xs font-semibold flex items-center gap-2 mb-2"><History size={14}/> Riwayat Pemenuhan TM</div>
        <div className="space-y-2">
          {histories.map((row) => <div key={row.id || row.settlementNo} className="rounded-lg bg-[#080c13] border border-[#1f2937] px-3 py-2 text-xs">
            <div className="flex flex-wrap justify-between gap-2">
              <span className="font-medium">{row.settlementNo || row.referenceNo || '-'} · {methodLabel(row.method)}</span>
              <span className="font-mono text-[#86efac]">{fmt(row.fulfilledWeightKg)} kg</span>
            </div>
            <div className="text-[#8b93a1] mt-1">
              {row.time ? new Date(row.time).toLocaleString('id-ID') : '-'} · {row.operator || '-'}{row.stackCode ? ` · ${row.stackCode}` : ''}
            </div>
            {(row.allocations || []).length > 0 && <div className="text-[#8b93a1] mt-1">
              Alokasi: {row.allocations.map((x) => `${x.polisi || x.claimNo}: ${fmt(x.allocatedWeightKg)} kg`).join(' · ')}
            </div>}
            {row.note && <div className="text-[#cbd5e1] mt-1">{row.note}</div>}
          </div>)}
        </div>
      </div>}
    </div>;
  };

  const GroupCard = ({ group }) => {
    const key = group.groupId || group.poId || group.poNo;
    const isOpen = Boolean(expanded[key]);
    return <div className="card-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono font-bold text-[#93c5fd]">{group.poNo}</span>
            <span className={`rounded-full border px-2 py-1 text-[10px] font-semibold ${statusBadge(group.status)}`}>{String(group.status || '').replaceAll('_', ' ')}</span>
          </div>
          <div className="text-sm font-semibold mt-2">{group.supplier || '-'}</div>
          <div className="text-xs text-[#8b93a1] mt-1">{(group.items || []).length} komoditi · {(group.items || []).reduce((n, x) => n + (x.details || []).length, 0)} kendaraan dengan kekurangan</div>
        </div>
        <button onClick={() => setExpanded((prev) => ({ ...prev, [key]: !isOpen }))} className="inline-flex items-center gap-2 rounded-lg border border-[#294263] px-3 py-2 text-xs text-[#93c5fd]">
          {isOpen ? <ChevronUp size={14}/> : <ChevronDown size={14}/>} {isOpen ? 'Tutup Rincian' : 'Lihat Rincian'}
        </button>
      </div>

      <div className="grid grid-cols-3 gap-2 mt-4">
        <div className="rounded-lg border border-[#243044] p-3"><div className="text-[10px] text-[#8b93a1]">Total Kekurangan</div><div className="font-mono font-bold mt-1">{fmt(group.shortageWeightKg)} kg</div></div>
        <div className="rounded-lg border border-[#243044] p-3"><div className="text-[10px] text-[#8b93a1]">Sudah Dipenuhi</div><div className="font-mono font-bold text-[#86efac] mt-1">{fmt(group.settledWeightKg)} kg</div></div>
        <div className="rounded-lg border border-[#243044] p-3"><div className="text-[10px] text-[#8b93a1]">Sisa TM</div><div className="font-mono font-bold text-[#fbbf24] mt-1">{fmt(group.remainingWeightKg)} kg</div></div>
      </div>

      {isOpen && <div className="space-y-3 mt-4">{(group.items || []).map((item) => <ItemBlock key={item.productId} group={group} item={item}/>)}</div>}
    </div>;
  };

  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <div className="label-mono mb-2">Operasional Penerimaan</div>
        <h1 className="font-display text-3xl sm:text-4xl font-bold">Pemenuhan Klaim Kekurangan</h1>
        <p className="text-sm text-[#8b93a1] mt-2">Klaim dikelompokkan per TM/PO. Detail kendaraan tetap tersimpan dan pemenuhan dapat dilakukan bertahap.</p>
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
      <div>Satu TM tampil sebagai satu kelompok seperti kerusakan PO. Jika beberapa mobil kekurangan, seluruh rincian tetap terlihat. Pemenuhan sebagian akan mengurangi sisa TM dan dialokasikan ke rincian kendaraan secara otomatis.</div>
    </div>

    <section>
      <div className="flex items-center gap-2 mb-3"><Scale size={18}/><h2 className="font-display text-xl font-bold">TM dengan Klaim Aktif</h2><span className="text-xs text-[#8b93a1]">({openGroups.length})</span></div>
      {loading ? <div className="card-surface p-10 text-center text-[#8b93a1]">Memuat klaim...</div> :
        <div className="space-y-3">{openGroups.length ? openGroups.map((group) => <GroupCard key={group.groupId || group.poNo} group={group}/>) : <div className="card-surface p-8 text-center text-[#86efac]"><CheckCircle2 className="mx-auto mb-2" size={24}/>Tidak ada TM dengan klaim kekurangan aktif.</div>}</div>}
    </section>

    {completedGroups.length > 0 && <section>
      <button onClick={() => setShowCompleted((v) => !v)} className="flex items-center gap-2 text-sm font-semibold text-[#93c5fd]">
        <History size={16}/>{showCompleted ? 'Sembunyikan' : 'Tampilkan'} TM Selesai ({completedGroups.length})
      </button>
      {showCompleted && <div className="space-y-3 mt-3">{completedGroups.map((group) => <GroupCard key={group.groupId || group.poNo} group={group}/>)}</div>}
    </section>}

    {modal && <div className="fixed inset-0 z-[100] bg-black/75 overflow-y-auto flex items-start justify-center p-4 sm:py-6">
      <div className="card-surface w-full max-w-2xl p-6">
        <div className="flex justify-between gap-3">
          <div>
            <h2 className="font-display text-xl font-bold">Pemenuhan {modal.group.poNo}</h2>
            <p className="text-xs text-[#8b93a1] mt-1">{modal.group.supplier || '-'} · {modal.item.product}</p>
            <p className="text-xs text-[#fbbf24] mt-1">Sisa klaim produk pada TM: <b>{fmt(modal.item.remainingWeightKg)} kg</b></p>
          </div>
          <button onClick={() => setModal(null)} className="p-2 rounded-lg border border-[#242f3d] h-fit"><X size={16}/></button>
        </div>

        <div className="mt-4 rounded-lg border border-[#243044] bg-[#0b0f17] px-3 py-2 text-xs text-[#8b93a1]">
          {(modal.item.details || []).filter((x) => Number(x.remainingWeightKg || 0) > 1e-9).length} rincian kendaraan masih memiliki sisa klaim. Pemenuhan akan dialokasikan ke rincian tertua terlebih dahulu.
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-4">
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
          <div className="rounded-lg border border-[#1d4ed8]/50 bg-[#1e3a8a]/10 px-3 py-2 text-xs text-[#bfdbfe]">Jumlah boleh lebih kecil dari sisa klaim. Contoh sisa 35 kg, hari ini datang 10 kg: status TM menjadi Dipenuhi Sebagian dan sisa 25 kg.</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div><label className="text-xs text-[#8b93a1] block mb-1.5">Berat pemenuhan (kg)</label><input type="number" min="0.01" step="0.01" className={inputCls} value={modal.fulfilledWeightKg} onChange={(e) => setModal({...modal, fulfilledWeightKg:e.target.value})}/></div>
            <div><label className="text-xs text-[#8b93a1] block mb-1.5">Tumpukan tujuan</label><input list="claim-stack-codes" className={inputCls} value={modal.stackCode} onChange={(e) => setModal({...modal,stackCode:e.target.value.toUpperCase()})} placeholder="Contoh 22/A03"/></div>
          </div>
          <div className="text-xs text-[#8b93a1]">Setara penambahan stok: <b className="text-[#e5e7eb]">{fmt(Number(modal.fulfilledWeightKg || 0) / 50, 4)} {modal.item.unit}</b>.</div>
        </div>}

        {modal.method === 'GANTI_KARUNG' && <div className="space-y-3 mt-4">
          <div className="rounded-lg border border-[#854d0e] bg-[#451a03]/20 px-3 py-2 text-xs text-[#fbbf24]">Gunakan bila karung kurang timbang ditarik lalu diganti karung utuh. Sistem menambah selisih bersih dan tetap mengalokasikan pemenuhan ke rincian kendaraan.</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div><label className="text-xs text-[#8b93a1] block mb-1.5">Jumlah karung pengganti 50 kg</label><input type="number" min="1" step="1" className={inputCls} value={modal.replacementBagCount} onChange={(e) => setModal({...modal,replacementBagCount:e.target.value})}/></div>
            <div><label className="text-xs text-[#8b93a1] block mb-1.5">Total berat karung lama yang ditarik (kg)</label><input type="number" min="0.01" step="0.01" className={inputCls} value={modal.withdrawnOldWeightKg} onChange={(e) => setModal({...modal,withdrawnOldWeightKg:e.target.value})}/></div>
          </div>
          <div className="rounded-lg border border-[#243044] p-3 text-sm">
            Perhitungan: <b>{Number(modal.replacementBagCount || 0)} × 50 kg</b> − <b>{fmt(modal.withdrawnOldWeightKg)} kg</b> = <b className="text-[#86efac]">{fmt(replacementFulfilled)} kg pemenuhan</b>
          </div>
          <div><label className="text-xs text-[#8b93a1] block mb-1.5">Tumpukan tempat penggantian diterima</label><input list="claim-stack-codes" className={inputCls} value={modal.stackCode} onChange={(e) => setModal({...modal,stackCode:e.target.value.toUpperCase()})} placeholder="Pilih GBB/MP1"/></div>
        </div>}

        {modal.method === 'ADMINISTRATIF' && <div className="space-y-3 mt-4">
          <div className="rounded-lg border border-[#7f1d1d] bg-[#450a0a]/20 px-3 py-2 text-xs text-[#fca5a5]"><b>Tidak menambah stok fisik.</b> Gunakan hanya jika kekurangan diselesaikan secara administratif/kompensasi.</div>
          <div><label className="text-xs text-[#8b93a1] block mb-1.5">Berat klaim yang diselesaikan (kg)</label><input type="number" min="0.01" step="0.01" className={inputCls} value={modal.fulfilledWeightKg} onChange={(e) => setModal({...modal,fulfilledWeightKg:e.target.value})}/></div>
        </div>}

        <datalist id="claim-stack-codes">{stackCodes.map((code) => <option key={code} value={code}/>)}</datalist>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
          <div><label className="text-xs text-[#8b93a1] block mb-1.5">No. referensi pemenuhan (opsional)</label><input className={inputCls} value={modal.referenceNo} onChange={(e) => setModal({...modal,referenceNo:e.target.value})} placeholder="Kosong = nomor otomatis"/></div>
          <div><label className="text-xs text-[#8b93a1] block mb-1.5">Catatan {modal.method === 'ADMINISTRATIF' ? '(wajib)' : '(opsional)'}</label><input className={inputCls} value={modal.note} onChange={(e) => setModal({...modal,note:e.target.value})} placeholder="Keterangan pemenuhan"/></div>
        </div>

        <div className="flex justify-end gap-2 mt-5">
          <button disabled={saving} onClick={() => setModal(null)} className="px-4 py-2 rounded-lg border border-[#242f3d] disabled:opacity-50">Batal</button>
          <button disabled={saving} onClick={submit} className="btn-primary px-5 py-2 rounded-lg font-semibold disabled:opacity-50">{saving ? 'Menyimpan...' : 'Simpan Pemenuhan TM'}</button>
        </div>
      </div>
    </div>}
  </div>;
};

export default PemenuhanKlaim;
