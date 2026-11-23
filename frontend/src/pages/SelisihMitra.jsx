import React, { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ArrowDownCircle,
  ArrowUpCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Handshake,
  History,
  RefreshCcw,
  Scale,
  Truck,
  X,
} from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError } from '../lib/api';

const EPS = 1e-9;

const fmt = (value, digits = 0) => Number(value || 0).toLocaleString('id-ID', {
  maximumFractionDigits: digits,
  minimumFractionDigits: 0,
});

const kindLabel = (kind) => kind === 'EXCESS' ? 'Kelebihan' : 'Kekurangan';

const statusClass = (status) => {
  if (status === 'SELESAI') return 'border-[#166534] bg-[#14532d]/20 text-[#86efac]';
  if (status === 'SEBAGIAN') return 'border-[#92400e] bg-[#78350f]/20 text-[#fbbf24]';
  return 'border-[#1d4ed8] bg-[#1e3a8a]/20 text-[#93c5fd]';
};

const methodLabel = (method) => ({
  PENGAMBILAN_KELEBIHAN: 'Diambil Kembali Mitra',
  PEMENUHAN_KEKURANGAN: 'Kiriman Susulan',
  KOMPENSASI: 'Kompensasi Saldo',
}[method] || method || '-');

const inputCls = 'w-full rounded-lg border border-[#374151] bg-[#0b0f17] px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';

const SelisihMitra = () => {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState({});
  const [stackCodes, setStackCodes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [filter, setFilter] = useState('AKTIF');
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState({});
  const [modal, setModal] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const [varianceRes, stacksRes] = await Promise.all([
        api.get('/partner-variances'),
        api.get('/stack-allocations'),
      ]);
      setRows(varianceRes.data?.items || []);
      setSummary(varianceRes.data?.summary || {});
      const codes = Array.from(new Set((stacksRes.data || [])
        .map((row) => String(row.stackCode || '').trim().toUpperCase())
        .filter(Boolean))).sort();
      setStackCodes(codes);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const activeRows = useMemo(() => rows.filter((row) => Number(row.remainingQty || 0) > EPS), [rows]);

  const filteredRows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (filter === 'AKTIF' && Number(row.remainingQty || 0) <= EPS) return false;
      if (filter === 'EXCESS' && row.kind !== 'EXCESS') return false;
      if (filter === 'SHORTAGE' && row.kind !== 'SHORTAGE') return false;
      if (filter === 'SELESAI' && row.status !== 'SELESAI') return false;
      if (!needle) return true;
      return [
        row.supplier,
        row.documentNo,
        row.poNo,
        row.loadNo,
        row.polisi,
        row.sku,
        row.product,
        row.stackCode,
      ].some((value) => String(value || '').toLowerCase().includes(needle));
    });
  }, [rows, filter, query]);

  const compensationCandidates = (row) => activeRows.filter((other) =>
    other.key !== row.key &&
    other.kind !== row.kind &&
    other.supplierKey === row.supplierKey &&
    other.productId === row.productId &&
    other.channel === row.channel
  );

  const openPhysical = (row) => {
    const method = row.kind === 'EXCESS' ? 'PENGAMBILAN_KELEBIHAN' : 'PEMENUHAN_KEKURANGAN';
    setModal({
      mode: 'PHYSICAL',
      row,
      method,
      qty: String(row.remainingQty || ''),
      stackCode: row.stackCode || '',
      referenceNo: '',
      note: '',
    });
  };

  const openCompensation = (row) => {
    const candidates = compensationCandidates(row);
    if (!candidates.length) {
      toast.error('Belum ada saldo lawan yang cocok untuk mitra, komoditi, dan saluran yang sama');
      return;
    }
    const counterpart = candidates[0];
    const excess = row.kind === 'EXCESS' ? row : counterpart;
    const shortage = row.kind === 'SHORTAGE' ? row : counterpart;
    setModal({
      mode: 'COMPENSATE',
      row,
      counterpartKey: counterpart.key,
      qty: String(Math.min(Number(excess.remainingQty || 0), Number(shortage.remainingQty || 0))),
      referenceNo: '',
      note: '',
    });
  };

  const submit = async () => {
    if (!modal) return;
    const qty = Number(modal.qty || 0);
    if (!(qty > 0)) return toast.error('Jumlah penyelesaian wajib lebih dari 0');

    setSaving(true);
    try {
      let response;
      if (modal.mode === 'COMPENSATE') {
        const counterpart = rows.find((row) => row.key === modal.counterpartKey);
        if (!counterpart) throw new Error('Saldo pasangan tidak ditemukan');
        const excess = modal.row.kind === 'EXCESS' ? modal.row : counterpart;
        const shortage = modal.row.kind === 'SHORTAGE' ? modal.row : counterpart;
        response = await api.post('/partner-variances/compensate', {
          excessKey: excess.key,
          shortageKey: shortage.key,
          qty,
          referenceNo: modal.referenceNo.trim(),
          note: modal.note.trim(),
        });
      } else {
        if (!modal.stackCode.trim()) return toast.error('Tumpukan penyelesaian wajib dipilih');
        response = await api.post('/partner-variances/' + encodeURIComponent(modal.row.key) + '/settle', {
          method: modal.method,
          qty,
          stackCode: modal.stackCode.trim().toUpperCase(),
          referenceNo: modal.referenceNo.trim(),
          note: modal.note.trim(),
        });
      }
      toast.success('Selisih mitra berhasil diselesaikan: ' + (response.data?.settlementNo || 'tersimpan'));
      setModal(null);
      await load();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  const modalCandidates = modal?.mode === 'COMPENSATE' ? compensationCandidates(modal.row) : [];
  const selectedCounterpart = modalCandidates.find((row) => row.key === modal?.counterpartKey);
  const modalMax = modal?.mode === 'COMPENSATE' && selectedCounterpart
    ? Math.min(Number(modal.row.remainingQty || 0), Number(selectedCounterpart.remainingQty || 0))
    : Number(modal?.row?.remainingQty || 0);

  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <div className="label-mono mb-2">Operasional Penerimaan</div>
        <h1 className="font-display text-3xl sm:text-4xl font-bold">Selisih Mitra</h1>
        <p className="text-sm text-[#8b93a1] mt-2">
          Kelebihan dan kekurangan kirim dicatat terpisah. Saldo tidak pernah dijaring otomatis dan setiap penyelesaian memiliki riwayat audit.
        </p>
      </div>
      <button onClick={load} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-[#294263] px-3 py-2 text-xs text-[#93c5fd] disabled:opacity-50">
        <RefreshCcw size={14} className={loading ? 'animate-spin' : ''}/> Refresh
      </button>
    </div>

    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      <div className="card-surface p-4">
        <div className="flex items-center gap-2 text-xs text-[#8b93a1]"><ArrowUpCircle size={15}/> Saldo Kelebihan Aktif</div>
        <div className="font-display text-2xl font-bold mt-1 text-[#60a5fa]">{fmt(summary.activeExcessWeightKg, 2)} kg</div>
        <div className="text-[10px] text-[#64748b] mt-1">{summary.activeExcessCount || 0} catatan</div>
      </div>
      <div className="card-surface p-4">
        <div className="flex items-center gap-2 text-xs text-[#8b93a1]"><ArrowDownCircle size={15}/> Saldo Kekurangan Aktif</div>
        <div className="font-display text-2xl font-bold mt-1 text-[#f59e0b]">{fmt(summary.activeShortageWeightKg, 2)} kg</div>
        <div className="text-[10px] text-[#64748b] mt-1">{summary.activeShortageCount || 0} catatan</div>
      </div>
      <div className="card-surface p-4">
        <div className="flex items-center gap-2 text-xs text-[#8b93a1]"><CheckCircle2 size={15}/> Selisih Selesai</div>
        <div className="font-display text-2xl font-bold mt-1 text-[#86efac]">{summary.completedCount || 0}</div>
        <div className="text-[10px] text-[#64748b] mt-1">catatan selesai</div>
      </div>
    </div>

    <div className="rounded-xl border border-[#1d4ed8]/50 bg-[#1e3a8a]/10 px-4 py-3 text-xs text-[#bfdbfe] flex gap-2">
      <AlertTriangle size={16} className="shrink-0 mt-0.5"/>
      <div>
        Saldo kelebihan tetap tercatat sebagai barang fisik di gudang tetapi dikunci dari pengeluaran normal sampai diselesaikan.
        Pilih <b>Diambil Mitra</b> untuk mengeluarkan fisiknya atau <b>Kompensasikan</b> untuk menutup kekurangan yang cocok.
      </div>
    </div>

    <div className="card-surface p-4">
      <div className="flex flex-col lg:flex-row gap-3 lg:items-center lg:justify-between">
        <div className="flex flex-wrap gap-2">
          {[
            ['AKTIF','Aktif'],
            ['EXCESS','Kelebihan'],
            ['SHORTAGE','Kekurangan'],
            ['SELESAI','Selesai'],
            ['SEMUA','Semua'],
          ].map(([value, label]) =>
            <button key={value} onClick={() => setFilter(value)}
              className={'rounded-lg border px-3 py-2 text-xs font-semibold ' + (filter === value ? 'border-[#2563eb] bg-[#2563eb]/15 text-[#93c5fd]' : 'border-[#374151] text-[#cbd5e1]')}>
              {label}
            </button>
          )}
        </div>
        <input value={query} onChange={(e) => setQuery(e.target.value)}
          className="w-full lg:w-80 rounded-lg border border-[#374151] bg-[#0b0f17] px-3 py-2 text-sm outline-none focus:border-[#2563eb]"
          placeholder="Cari mitra, TM, nopol, SKU..." />
      </div>
    </div>

    {loading ? <div className="card-surface p-10 text-center text-[#8b93a1]">Memuat saldo selisih mitra...</div> :
      filteredRows.length === 0 ? <div className="card-surface p-10 text-center text-[#86efac]">
        <CheckCircle2 className="mx-auto mb-2" size={24}/>Tidak ada data sesuai filter.
      </div> :
      <div className="card-surface overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1180px] text-xs">
            <thead className="bg-[#111827] text-[#9ca3af]">
              <tr>
                <th className="text-left p-3">Tanggal / Mitra</th>
                <th className="text-left p-3">TM / Kendaraan</th>
                <th className="text-left p-3">Komoditi</th>
                <th className="text-left p-3">Jenis</th>
                <th className="text-right p-3">Awal</th>
                <th className="text-right p-3">Diselesaikan</th>
                <th className="text-right p-3">Sisa</th>
                <th className="text-left p-3">Tumpukan</th>
                <th className="text-left p-3">Status</th>
                <th className="text-right p-3">Tindakan</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((row) => {
                const isOpen = Boolean(expanded[row.key]);
                const candidates = compensationCandidates(row);
                return <React.Fragment key={row.key}>
                  <tr className="border-t border-[#1f2937] align-top">
                    <td className="p-3">
                      <div>{row.operationalDate || '-'}</div>
                      <div className="font-semibold mt-1">{row.supplier || '-'}</div>
                    </td>
                    <td className="p-3">
                      <div className="font-mono text-[#93c5fd]">{row.documentNo || row.poNo || '-'}</div>
                      <div className="mt-1">{row.polisi || '-'}</div>
                      <div className="text-[10px] text-[#64748b] mt-1">{row.loadNo || '-'}</div>
                    </td>
                    <td className="p-3">
                      <div className="font-semibold">{row.product || '-'}</div>
                      <div className="font-mono text-[10px] text-[#8b93a1] mt-1">{row.sku || '-'} · {row.channel}</div>
                    </td>
                    <td className="p-3">
                      <span className={'inline-flex items-center gap-1 rounded-full border px-2 py-1 font-semibold ' + (row.kind === 'EXCESS' ? 'border-[#1d4ed8] text-[#93c5fd]' : 'border-[#92400e] text-[#fbbf24]')}>
                        {row.kind === 'EXCESS' ? <ArrowUpCircle size={12}/> : <ArrowDownCircle size={12}/>}
                        {kindLabel(row.kind)}
                      </span>
                    </td>
                    <td className="p-3 text-right font-mono">
                      <div>{fmt(row.originalQty, 4)} {row.unit}</div>
                      <div className="text-[10px] text-[#8b93a1] mt-1">{fmt(row.originalWeightKg, 2)} kg</div>
                    </td>
                    <td className="p-3 text-right font-mono">{fmt(row.settledQty, 4)} {row.unit}</td>
                    <td className="p-3 text-right font-mono font-bold">
                      <div className={row.kind === 'EXCESS' ? 'text-[#60a5fa]' : 'text-[#f59e0b]'}>{fmt(row.remainingQty, 4)} {row.unit}</div>
                      <div className="text-[10px] text-[#8b93a1] mt-1">{fmt(row.remainingWeightKg, 2)} kg</div>
                    </td>
                    <td className="p-3 font-mono">{row.stackCode || '-'}</td>
                    <td className="p-3">
                      <span className={'rounded-full border px-2 py-1 text-[10px] font-semibold ' + statusClass(row.status)}>{row.status}</span>
                      {row.reason && <div className="text-[10px] text-[#8b93a1] mt-2 max-w-48">{row.reason}</div>}
                    </td>
                    <td className="p-3">
                      <div className="flex flex-col items-end gap-1.5">
                        {Number(row.remainingQty || 0) > EPS && <>
                          <button onClick={() => openPhysical(row)} className="inline-flex items-center gap-1.5 rounded-lg border border-[#166534] px-2.5 py-1.5 text-[10px] font-semibold text-[#86efac]">
                            <Truck size={12}/>{row.kind === 'EXCESS' ? 'Diambil Mitra' : 'Kiriman Susulan'}
                          </button>
                          <button onClick={() => openCompensation(row)} disabled={!candidates.length}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-[#1d4ed8] px-2.5 py-1.5 text-[10px] font-semibold text-[#93c5fd] disabled:opacity-30">
                            <Handshake size={12}/>Kompensasikan
                          </button>
                        </>}
                        <button onClick={() => setExpanded((prev) => ({ ...prev, [row.key]: !isOpen }))}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-[#374151] px-2.5 py-1.5 text-[10px] text-[#cbd5e1]">
                          <History size={12}/>{isOpen ? <ChevronUp size={11}/> : <ChevronDown size={11}/>} Riwayat
                        </button>
                      </div>
                    </td>
                  </tr>
                  {isOpen && <tr className="border-t border-[#1f2937] bg-[#080c13]">
                    <td colSpan={10} className="p-4">
                      <div className="text-xs font-semibold mb-2">Riwayat Penyelesaian</div>
                      {(row.history || []).length === 0 ? <div className="text-xs text-[#64748b]">Belum ada penyelesaian.</div> :
                        <div className="space-y-2">
                          {(row.history || []).map((event) =>
                            <div key={event.id} className="rounded-lg border border-[#243044] px-3 py-2 flex flex-wrap justify-between gap-2">
                              <div>
                                <span className="font-mono text-[#93c5fd]">{event.settlementNo || '-'}</span>
                                <span className="ml-2">{methodLabel(event.method)}</span>
                                <div className="text-[10px] text-[#8b93a1] mt-1">
                                  {event.time ? new Date(event.time).toLocaleString('id-ID') : '-'} · {event.operator || '-'}
                                  {event.note ? ' · ' + event.note : ''}
                                </div>
                              </div>
                              <div className="font-mono font-semibold">{fmt(event.qty, 4)} {row.unit}</div>
                            </div>
                          )}
                        </div>}
                    </td>
                  </tr>}
                </React.Fragment>;
              })}
            </tbody>
          </table>
        </div>
      </div>}

    {modal && <div className="fixed inset-0 z-[100] bg-black/75 overflow-y-auto flex items-start justify-center p-4 sm:py-8">
      <div className="card-surface w-full max-w-2xl p-6">
        <div className="flex justify-between gap-3">
          <div>
            <div className="label-mono mb-1">Penyelesaian Selisih Mitra</div>
            <h2 className="font-display text-xl font-bold">
              {modal.mode === 'COMPENSATE' ? 'Kompensasi Saldo' : methodLabel(modal.method)}
            </h2>
            <p className="text-xs text-[#8b93a1] mt-1">{modal.row.supplier} · {modal.row.product}</p>
          </div>
          <button onClick={() => setModal(null)} className="p-2 rounded-lg border border-[#242f3d] h-fit"><X size={16}/></button>
        </div>

        <div className="grid grid-cols-2 gap-2 mt-4">
          <div className="rounded-lg border border-[#243044] p-3">
            <div className="text-[10px] text-[#8b93a1]">Sumber</div>
            <div className="font-mono text-xs mt-1">{modal.row.documentNo || modal.row.poNo || '-'}</div>
            <div className="font-semibold mt-1">{kindLabel(modal.row.kind)} · sisa {fmt(modal.row.remainingQty, 4)} {modal.row.unit}</div>
          </div>
          <div className="rounded-lg border border-[#243044] p-3">
            <div className="text-[10px] text-[#8b93a1]">Kendaraan sumber</div>
            <div className="font-medium mt-1">{modal.row.polisi || '-'}</div>
            <div className="font-mono text-[10px] text-[#8b93a1] mt-1">{modal.row.stackCode || 'Tumpukan belum tercatat'}</div>
          </div>
        </div>

        {modal.mode === 'COMPENSATE' && <div className="mt-4">
          <label className="text-xs text-[#8b93a1] block mb-1.5">Saldo pasangan</label>
          <select className={inputCls} value={modal.counterpartKey}
            onChange={(e) => {
              const counterpart = rows.find((row) => row.key === e.target.value);
              const maxQty = counterpart ? Math.min(Number(modal.row.remainingQty || 0), Number(counterpart.remainingQty || 0)) : 0;
              setModal({ ...modal, counterpartKey: e.target.value, qty: String(maxQty) });
            }}>
            {modalCandidates.map((candidate) =>
              <option key={candidate.key} value={candidate.key}>
                {kindLabel(candidate.kind) + ' · ' + (candidate.documentNo || candidate.poNo || '-') + ' · sisa ' + fmt(candidate.remainingQty, 4) + ' ' + candidate.unit}
              </option>
            )}
          </select>
          <div className="rounded-lg border border-[#1d4ed8]/50 bg-[#1e3a8a]/10 px-3 py-2 text-xs text-[#bfdbfe] mt-3">
            Kompensasi hanya mengubah saldo administratif. Tidak ada stok fisik yang bertambah atau berkurang karena barang kelebihan sudah berada di gudang.
          </div>
        </div>}

        {modal.mode === 'PHYSICAL' && <div className="mt-4">
          <label className="text-xs text-[#8b93a1] block mb-1.5">Tumpukan {modal.method === 'PENGAMBILAN_KELEBIHAN' ? 'asal' : 'tujuan'}</label>
          <input list="partner-variance-stack-codes" className={inputCls} value={modal.stackCode}
            readOnly={modal.method === 'PENGAMBILAN_KELEBIHAN' && Boolean(modal.row.stackCode)}
            onChange={(e) => setModal({ ...modal, stackCode: e.target.value.toUpperCase() })}
            placeholder="Contoh 23/B04" />
          <datalist id="partner-variance-stack-codes">{stackCodes.map((code) => <option key={code} value={code}/>)}</datalist>
          <div className="text-[10px] text-[#64748b] mt-1">
            {modal.method === 'PENGAMBILAN_KELEBIHAN'
              ? 'Pengambilan mengurangi stok fisik dan tumpukan sumber.'
              : 'Kiriman susulan menambah stok baik ke tumpukan tujuan.'}
          </div>
        </div>}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
          <div>
            <label className="text-xs text-[#8b93a1] block mb-1.5">Jumlah ({modal.row.unit})</label>
            <input type="number" min="0.0001" max={modalMax || undefined} step="0.0001" className={inputCls}
              value={modal.qty} onChange={(e) => setModal({ ...modal, qty: e.target.value })}/>
            <div className="text-[10px] text-[#64748b] mt-1">Maksimal {fmt(modalMax, 4)} {modal.row.unit}</div>
          </div>
          <div>
            <label className="text-xs text-[#8b93a1] block mb-1.5">No. referensi (opsional)</label>
            <input className={inputCls} value={modal.referenceNo}
              onChange={(e) => setModal({ ...modal, referenceNo: e.target.value })}
              placeholder="Kosong = SM otomatis"/>
          </div>
        </div>

        <div className="mt-4">
          <label className="text-xs text-[#8b93a1] block mb-1.5">Catatan (opsional)</label>
          <textarea rows={3} className={inputCls} value={modal.note}
            onChange={(e) => setModal({ ...modal, note: e.target.value })}
            placeholder="Contoh: diambil kembali oleh mitra / disepakati untuk menutup TM berikutnya"/>
        </div>

        <div className="flex justify-end gap-2 mt-5">
          <button disabled={saving} onClick={() => setModal(null)} className="px-4 py-2 rounded-lg border border-[#242f3d] disabled:opacity-50">Batal</button>
          <button disabled={saving} onClick={submit} className="btn-primary px-5 py-2 rounded-lg font-semibold disabled:opacity-50">
            {saving ? 'Menyimpan...' : 'Simpan Penyelesaian'}
          </button>
        </div>
      </div>
    </div>}
  </div>;
};

export default SelisihMitra;
