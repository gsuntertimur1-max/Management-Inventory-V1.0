import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, ClipboardList, RefreshCcw, Search, TimerReset } from 'lucide-react';
import api, { apiError } from '../lib/api';
import { formatNum } from '../mock';
import { toast } from 'sonner';

const statusMeta = {
  SELESAI: ['Selesai', 'bg-[#14532d]/25 text-[#86efac] border-[#14532d]'],
  SEBAGIAN: ['Sebagian', 'bg-[#78350f]/30 text-[#fcd34d] border-[#78350f]'],
  DALAM_ANTREAN: ['Dalam Antrean', 'bg-[#1e3a8a]/30 text-[#93c5fd] border-[#1e3a8a]'],
  BELUM_DIAMBIL: ['Belum Diambil', 'bg-[#334155]/30 text-[#cbd5e1] border-[#475569]'],
  BERMASALAH: ['Bermasalah', 'bg-[#7f1d1d]/35 text-[#fca5a5] border-[#7f1d1d]'],
  PERLU_KUANTUM_SO: ['Perlu Kuantum SO', 'bg-[#7c2d12]/35 text-[#fdba74] border-[#9a3412]'],
  ARSIP_LEGACY: ['Arsip Legacy', 'bg-[#27272a]/45 text-[#a1a1aa] border-[#3f3f46]'],
};

const loadStatusClass = (status) => status === 'Selesai'
  ? 'text-[#86efac]'
  : status === 'Dibatalkan'
    ? 'text-[#fca5a5]'
    : status === 'Sedang Dimuat'
      ? 'text-[#fbbf24]'
      : 'text-[#93c5fd]';

const fmtDate = (value) => {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('id-ID');
};

const MonitorSO = () => {
  const [data, setData] = useState({ summary: {}, records: [] });
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('OUTSTANDING');

  const load = async () => {
    setLoading(true);
    try {
      const response = await api.get('/so-monitoring');
      setData(response.data || { summary: {}, records: [] });
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const outstanding = new Set(['BELUM_DIAMBIL', 'DALAM_ANTREAN', 'SEBAGIAN', 'BERMASALAH', 'PERLU_KUANTUM_SO']);
    return (data.records || []).filter((row) => {
      if (status === 'OUTSTANDING' && !outstanding.has(row.status)) return false;
      if (status !== 'ALL' && status !== 'OUTSTANDING' && row.status !== status) return false;
      if (!q) return true;
      const haystack = [
        row.documentNo,
        row.party,
        ...(row.items || []).flatMap((item) => [item.sku, item.name]),
        ...(row.loads || []).flatMap((item) => [item.bonNo, item.queue, item.vehicleNo, ...(item.suratJalan || []).map((sj) => sj.no)]),
      ].join(' ').toLowerCase();
      return haystack.includes(q);
    });
  }, [data.records, query, status]);

  const summary = data.summary || {};
  const cards = [
    ['Outstanding', summary.outstanding || 0, 'text-[#fbbf24]'],
    ['Sebagian', summary.partial || 0, 'text-[#fbbf24]'],
    ['Dalam Antrean', summary.queued || 0, 'text-[#93c5fd]'],
    ['Belum Diambil', summary.notStarted || 0, 'text-[#cbd5e1]'],
    ['Selesai', summary.completed || 0, 'text-[#86efac]'],
    ['Bermasalah', summary.problem || 0, 'text-[#fca5a5]'],
    ['Arsip Legacy', summary.legacy || 0, 'text-[#a1a1aa]'],
  ];

  return <div className="space-y-6">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div className="label-mono mb-2">Operasional · Dokumen Pengeluaran</div>
        <h1 className="font-display text-3xl sm:text-4xl font-bold">Monitoring SO Bertahap</h1>
        
      </div>
      <button onClick={load} disabled={loading} className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border border-[#243044] text-sm text-[#93c5fd] disabled:opacity-50"><RefreshCcw size={15} className={loading ? 'animate-spin' : ''}/> Periksa Ulang</button>
    </div>

    <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
      {cards.map(([label, value, tone]) => <div key={label} className="card-surface p-4">
        <div className="label-mono text-[9px]">{label}</div>
        <div className={`font-mono text-2xl font-bold mt-1 ${tone}`}>{value}</div>
      </div>)}
    </div>

    {(summary.errors > 0 || summary.warnings > 0) && <div className="rounded-xl border border-[#7f1d1d]/60 bg-[#450a0a]/15 px-4 py-3 text-sm flex items-start gap-3">
      <AlertTriangle size={18} className="text-[#fca5a5] mt-0.5"/>
      <div><b>Kontrol SO menemukan {summary.errors || 0} error dan {summary.warnings || 0} peringatan.</b><div className="text-xs text-[#c7a3a3] mt-1">Detail ditampilkan pada SO terkait dan ikut masuk ke Kontrol Integritas.</div></div>
    </div>}

    <div className="card-surface p-4">
      <div className="grid grid-cols-1 md:grid-cols-[1fr_220px] gap-3">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-3 text-[#64748b]"/>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cari nomor SO, penerima, SKU, komoditi, Bon Muat, SJ, kendaraan..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm outline-none focus:border-[#2563eb]"/>
        </div>
        <select value={status} onChange={(event) => setStatus(event.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm">
          <option value="OUTSTANDING">Outstanding saja</option>
          <option value="ALL">Semua SO</option>
          <option value="BELUM_DIAMBIL">Belum Diambil</option>
          <option value="DALAM_ANTREAN">Dalam Antrean</option>
          <option value="SEBAGIAN">Sebagian</option>
          <option value="SELESAI">Selesai</option>
          <option value="BERMASALAH">Bermasalah</option>
          <option value="PERLU_KUANTUM_SO">Perlu Kuantum SO</option>
          <option value="ARSIP_LEGACY">Arsip Legacy</option>
        </select>
      </div>
    </div>

    <div className="space-y-3">
      {loading && <div className="card-surface p-10 text-center text-[#8b93a1]">Memuat monitoring SO...</div>}
      {!loading && filtered.length === 0 && <div className="card-surface p-10 text-center text-[#8b93a1]">Tidak ada SO yang sesuai filter.</div>}
      {!loading && filtered.map((record) => {
        const meta = statusMeta[record.status] || [record.status, 'bg-[#334155]/30 text-[#cbd5e1] border-[#475569]'];
        return <details key={record.documentNo} className="card-surface overflow-hidden">
          <summary className="cursor-pointer list-none px-5 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono font-bold text-[#93c5fd]">{record.documentNo}</span>
                  <span className={`border rounded-full px-2 py-1 text-[10px] font-semibold ${meta[1]}`}>{meta[0]}</span>
                  {(record.issues || []).length > 0 && <span className="text-[10px] text-[#fca5a5]">{record.issues.length} temuan</span>}
                </div>
                <div className="text-sm mt-1">{record.party || 'Penerima belum tercatat'}</div>
                <div className="text-[11px] text-[#8b93a1] mt-1">{record.loadCount} pemuatan · {record.completedLoadCount} selesai · {record.activeLoadCount} aktif · aktivitas terakhir {fmtDate(record.lastActivity)}</div>
              </div>
              <div className="flex items-center gap-2 text-xs text-[#8b93a1]"><ClipboardList size={15}/> Lihat rincian</div>
            </div>

            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-[#8b93a1]"><tr><th className="text-left py-1 pr-3">Komoditi</th><th>SO Total</th><th>Selesai</th><th>Dalam Antrean</th><th>Sisa Dijadwalkan</th><th>Outstanding Fisik</th></tr></thead>
                <tbody>{(record.items || []).map((item) => <tr key={item.productId} className="border-t border-[#1f2937]">
                  <td className="py-2 pr-3"><div className="font-medium min-w-[220px]">{item.name || item.sku}</div><div className="font-mono text-[10px] text-[#64748b]">{item.sku}</div></td>
                  <td className="text-center font-mono">{item.orderedQty === null ? '—' : `${formatNum(item.orderedQty)} ${item.unit}`}</td>
                  <td className="text-center font-mono text-[#86efac]">{formatNum(item.completedQty)} {item.unit}</td>
                  <td className="text-center font-mono text-[#93c5fd]">{formatNum(item.reservedQty)} {item.unit}</td>
                  <td className="text-center font-mono font-bold text-[#fbbf24]">{item.remainingQty === null ? '—' : `${formatNum(item.remainingQty)} ${item.unit}`}</td>
                  <td className="text-center font-mono">{item.outstandingQty === null ? '—' : `${formatNum(item.outstandingQty)} ${item.unit}`}</td>
                </tr>)}</tbody>
              </table>
            </div>
          </summary>

          <div className="border-t border-[#1a222e] px-5 py-4 space-y-5">
            {(record.issues || []).length > 0 && <div>
              <div className="font-semibold text-sm mb-2 flex items-center gap-2"><AlertTriangle size={16} className="text-[#fca5a5]"/> Temuan</div>
              <div className="space-y-2">{record.issues.map((issue, index) => <div key={`${issue.code}-${index}`} className={`rounded-lg border px-3 py-2 text-xs ${issue.severity === 'ERROR' ? 'border-[#7f1d1d] bg-[#450a0a]/20 text-[#fca5a5]' : 'border-[#78350f] bg-[#451a03]/15 text-[#fcd34d]'}`}><b>{issue.code}</b> · {issue.issue}</div>)}</div>
            </div>}

            <div>
              <div className="font-semibold text-sm mb-2 flex items-center gap-2"><TimerReset size={16} className="text-[#93c5fd]"/> Riwayat Pemuatan</div>
              {(record.loads || []).length === 0 ? <div className="text-xs text-[#8b93a1]">Belum ada pemuatan untuk SO ini.</div> : <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-[#8b93a1]"><tr><th className="text-left py-2">Tanggal</th><th>Bon Muat</th><th>Antrian</th><th>Status</th><th>Kendaraan</th><th>Komoditi</th><th>Surat Jalan</th></tr></thead>
                  <tbody>{record.loads.map((load) => <tr key={`${load.loadId}-${load.status}`} className="border-t border-[#1f2937]">
                    <td className="py-2 whitespace-nowrap">{load.operationalDate || '—'}</td>
                    <td className="text-center font-mono whitespace-nowrap">{load.bonNo || '—'}</td>
                    <td className="text-center font-mono">{load.queue || '—'}</td>
                    <td className={`text-center font-semibold whitespace-nowrap ${loadStatusClass(load.status)}`}>{load.status}</td>
                    <td className="text-center whitespace-nowrap">{load.vehicleNo || '—'}</td>
                    <td className="py-2 min-w-[240px]">{(load.items || []).map((item) => `${item.name}: ${formatNum(item.qty)} ${item.unit}`).join(' · ') || '—'}</td>
                    <td className="text-center font-mono min-w-[180px]">{(load.suratJalan || []).map((sj) => sj.no).join(' · ') || '—'}</td>
                  </tr>)}</tbody>
                </table>
              </div>}
            </div>

            {record.status === 'ARSIP_LEGACY' && <div className="rounded-lg border border-[#3f3f46] bg-[#18181b]/50 px-3 py-2 text-xs text-[#a1a1aa]">SO ini selesai sebelum fitur master kuantum SO bertahap diterapkan. Histori Bon Muat/SJ tetap ditampilkan, tetapi Total SO dan Sisa tidak direkonstruksi agar sistem tidak menebak kuantum dokumen asli.</div>}
            {record.status === 'SELESAI' && <div className="text-xs text-[#86efac] inline-flex items-center gap-1"><CheckCircle2 size={14}/> Seluruh kuantum master SO sudah selesai dimuat.</div>}
          </div>
        </details>;
      })}
    </div>
  </div>;
};

export default MonitorSO;
