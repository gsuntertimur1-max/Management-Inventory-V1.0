import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, Clock3, Play, Printer, RefreshCcw, RotateCcw, Truck, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError, printApiFile } from '../lib/api';
import { useData } from '../context/DataContext';
import { formatNum, formatRp } from '../mock';
import { stackCodes } from '../lib/warehouses';
import PaginationControls from '../components/PaginationControls';

const displayTime = (value) => value
  ? new Date(value).toLocaleString('id-ID', { timeZone: 'Asia/Jakarta', dateStyle: 'medium', timeStyle: 'short' })
  : '—';

const minutesWib = (value) => {
  if (!value) return null;
  const date = new Date(value);
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(date);
  const map = Object.fromEntries(parts.filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]));
  return Number(map.hour) * 60 + Number(map.minute);
};

const nowMinutesWib = () => {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(new Date());
  const map = Object.fromEntries(parts.filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]));
  return Number(map.hour) * 60 + Number(map.minute);
};

const statusClass = (status) => ({
  'Menunggu Bongkar': 'border-[#92400e] bg-[#78350f]/15 text-[#fbbf24]',
  'Sedang Bongkar': 'border-[#1d4ed8] bg-[#1d4ed8]/15 text-[#93c5fd]',
  Selesai: 'border-[#166534] bg-[#14532d]/15 text-[#86efac]',
  Dibatalkan: 'border-[#7f1d1d] bg-[#7f1d1d]/15 text-[#fca5a5]',
}[status] || 'border-[#334155] text-[#94a3b8]');

const Penerimaan = () => {
  const { products, settings, fetchAll } = useData();
  const navigate = useNavigate();
  const STACKS = stackCodes(settings?.warehouses);
  const [loads, setLoads] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [completion, setCompletion] = useState(null);
  const [cancelModal, setCancelModal] = useState(null);
  const [historyPage, setHistoryPage] = useState(1);

  const loadAll = useCallback(async () => {
    try {
      const { data } = await api.get('/inbound-loads');
      setLoads(Array.isArray(data) ? data : []);
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const active = useMemo(
    () => loads.filter((row) => ['Menunggu Bongkar', 'Sedang Bongkar'].includes(row.status)),
    [loads],
  );
  const history = useMemo(
    () => loads.filter((row) => ['Selesai', 'Dibatalkan'].includes(row.status)),
    [loads],
  );
  const historyPageSize = 10;
  const paginatedHistory = history.slice((historyPage - 1) * historyPageSize, historyPage * historyPageSize);

  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(history.length / historyPageSize));
    if (historyPage > maxPage) setHistoryPage(maxPage);
  }, [history.length, historyPage]);

  const startLoad = async (load) => {
    if (busy) return;
    setBusy(`start:${load.id}`);
    try {
      await api.post(`/inbound-loads/${load.id}/start`);
      toast.success(`${load.loadNo} mulai bongkar. Waktu mulai tercatat otomatis.`);
      await loadAll();
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setBusy('');
    }
  };

  const askCancel = (load) => setCancelModal({ load, reason: '' });

  const cancelLoad = async () => {
    if (!cancelModal || busy) return;
    if (cancelModal.reason.trim().length < 3) return toast.error('Alasan pembatalan minimal 3 karakter');
    setBusy(`cancel:${cancelModal.load.id}`);
    try {
      await api.post(`/inbound-loads/${cancelModal.load.id}/cancel`, { reason: cancelModal.reason.trim() });
      toast.success('Kendaraan dibatalkan. PO dan stok tidak berubah.');
      setCancelModal(null);
      await loadAll();
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setBusy('');
    }
  };

  const openComplete = (load) => {
    const started = minutesWib(load.startedAt);
    const now = nowMinutesWib();
    const fullOvertime = started !== null && started >= 16 * 60;
    const crossesCutoff = started !== null && started < 16 * 60 && now >= 16 * 60;
    const rows = (load.items || []).map((item) => {
      const product = products.find((row) => row.id === item.productId);
      return {
        productId: item.productId,
        name: item.name,
        sku: item.sku,
        unit: item.unit,
        plannedQty: Number(item.qty || 0),
        goodQty: Number(item.qty || 0),
        damagedQty: 0,
        // Untuk sesi yang mulai sebelum 16.00, biarkan kosong sampai selesai.
        // Jika modal dibuka sebelum 16.00 tetapi disimpan setelah 16.00,
        // completeLoad akan mewajibkan operator mengisi jumlah setelah 16.00.
        overtimeQty: fullOvertime ? Number(item.qty || 0) : '',
        stackCode: item.stackCode || product?.location || '',
        exp: item.exp || '',
        channel: item.channel || product?.channel || 'KOM',
      };
    });
    setCompletion({ load, rows, note: '', fullOvertime, crossesCutoff });
  };

  const setCompleteRow = (index, patch) => {
    setCompletion((prev) => ({
      ...prev,
      rows: prev.rows.map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row),
    }));
  };

  const completeLoad = async () => {
    if (!completion || busy) return;
    const started = minutesWib(completion.load.startedAt);
    const now = nowMinutesWib();
    const fullOvertimeNow = started !== null && started >= 16 * 60;
    const crossesCutoffNow = started !== null && started < 16 * 60 && now >= 16 * 60;
    if (crossesCutoffNow && !completion.crossesCutoff) {
      setCompletion((prev) => prev ? { ...prev, crossesCutoff: true } : prev);
    }
    for (const row of completion.rows) {
      const good = Number(row.goodQty || 0);
      const damaged = Number(row.damagedQty || 0);
      const total = good + damaged;
      if (total > Number(row.plannedQty || 0) + 1e-9) {
        return toast.error(`${row.name}: jumlah aktual melebihi rencana kendaraan`);
      }
      if (good > 0 && !row.stackCode) return toast.error(`Pilih tumpukan barang baik untuk ${row.name}`);
      if (total > 0 && crossesCutoffNow && row.overtimeQty === '') {
        return toast.error(`Isi jumlah yang dibongkar setelah 16.00 untuk ${row.name}; isi 0 bila tidak ada.`);
      }
      if (Number(row.overtimeQty || 0) > total + 1e-9) {
        return toast.error(`${row.name}: jumlah lembur tidak boleh melebihi total aktual`);
      }
    }
    const actualTotal = completion.rows.reduce((sum, row) => sum + Number(row.goodQty || 0) + Number(row.damagedQty || 0), 0);
    if (actualTotal <= 0) return toast.error('Tidak ada jumlah aktual. Jika kendaraan tidak jadi bongkar, gunakan Batalkan.');

    setBusy(`complete:${completion.load.id}`);
    try {
      const { data } = await api.post(`/inbound-loads/${completion.load.id}/complete`, {
        items: completion.rows.map((row) => ({
          productId: row.productId,
          goodQty: Number(row.goodQty || 0),
          damagedQty: Number(row.damagedQty || 0),
          overtimeQty: fullOvertimeNow
            ? Number(row.goodQty || 0) + Number(row.damagedQty || 0)
            : (crossesCutoffNow ? (row.overtimeQty === '' ? null : Number(row.overtimeQty)) : null),
          stackCode: row.stackCode || '',
          exp: row.exp || '',
          channel: row.channel || 'KOM',
        })),
        note: completion.note || '',
      });
      const status = data?.purchaseOrder?.status;
      toast.success(status ? `Bongkar selesai · Status PO: ${status}` : 'Bongkar selesai dan stok masuk tersimpan');
      setCompletion(null);
      await Promise.all([loadAll(), fetchAll?.()]);
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setBusy('');
    }
  };

  const printWeighing = (load) => {
    if (!load.operationId) return toast.error('Bukti timbang belum tersedia');
    return printApiFile(`/export/weighing-form/inbound/${load.operationId}.pdf`).catch((error) => toast.error(apiError(error)));
  };

  const renderLoad = (load) => (
    <div key={load.id} className="card-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono font-bold text-[#93c5fd]">{load.loadNo}</span>
            <span className={`text-[10px] border rounded-full px-2.5 py-1 font-semibold ${statusClass(load.status)}`}>{load.status}</span>
          </div>
          <div className="font-semibold mt-2">{load.poNo} · {load.party}</div>
          <div className="text-xs text-[#8b93a1] mt-1">{load.polisi || 'Tanpa nomor polisi'}{load.driver ? ` · ${load.driver}` : ''}</div>
          {load.startedAt && <div className="text-xs text-[#8b93a1] mt-1">Mulai bongkar: {displayTime(load.startedAt)}</div>}
          {load.status === 'Selesai' && Number(load.unloadingCost?.total || 0) > 0 && (
            <div className="text-xs text-[#fbbf24] mt-1">
              Biaya bongkar kendaraan: {formatRp(load.unloadingCost.total)}
              {load.unloadingCost?.groups?.length ? ` · ${load.unloadingCost.groups.join(', ')}` : ''}
            </div>
          )}
          {load.reversedAt && (
            <div className="mt-2 rounded-lg border border-[#b45309] bg-[#78350f]/10 px-2.5 py-2 text-xs text-[#fbbf24]">
              Penerimaan sudah direversal melalui Koreksi Operasional pada {displayTime(load.reversedAt)}
              {load.reversalReason ? ` · ${load.reversalReason}` : ''}.
            </div>
          )}
        </div>
        <Truck size={20} className="text-[#60a5fa]" />
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-[#8b93a1]"><tr><th className="text-left py-2">Komoditi</th><th className="text-right">Rencana</th>{load.status === 'Selesai' && <><th className="text-right">Baik</th><th className="text-right">Rusak</th><th className="text-right">Lembur</th></>}</tr></thead>
          <tbody>{(load.items || []).map((item) => {
            const actual = (load.actualItems || []).find((row) => row.productId === item.productId);
            return <tr key={item.productId} className="border-t border-[#1f2937]"><td className="py-2"><div className="font-medium">{item.name}</div><div className="font-mono text-[10px] text-[#8b93a1]">{item.sku || '—'}</div></td><td className="text-right font-mono">{formatNum(item.qty)} {item.unit}</td>{load.status === 'Selesai' && <><td className="text-right font-mono">{formatNum(actual?.goodQty || 0)}</td><td className="text-right font-mono">{formatNum(actual?.damagedQty || 0)}</td><td className="text-right font-mono">{formatNum(actual?.overtimeQty || 0)}</td></>}</tr>;
          })}</tbody>
        </table>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {load.status === 'Menunggu Bongkar' && <button disabled={Boolean(busy)} onClick={() => startLoad(load)} className="btn-primary inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold disabled:opacity-50"><Play size={13}/> Mulai Bongkar</button>}
        {load.status === 'Sedang Bongkar' && <button disabled={Boolean(busy)} onClick={() => openComplete(load)} className="inline-flex items-center gap-1.5 rounded-lg border border-[#22c55e] px-3 py-2 text-xs font-semibold text-[#86efac] disabled:opacity-50"><CheckCircle2 size={13}/> Selesai Bongkar</button>}
        {['Menunggu Bongkar','Sedang Bongkar'].includes(load.status) && <button disabled={Boolean(busy)} onClick={() => askCancel(load)} className="inline-flex items-center gap-1.5 rounded-lg border border-[#7f1d1d] px-3 py-2 text-xs font-semibold text-[#fca5a5] disabled:opacity-50"><XCircle size={13}/> Batalkan Kendaraan</button>}
        {load.status === 'Selesai' && load.weighingForm && load.operationId && <button onClick={() => printWeighing(load)} className="inline-flex items-center gap-1.5 rounded-lg border border-[#294263] px-3 py-2 text-xs font-semibold text-[#93c5fd]"><Printer size={13}/> Cetak Ulang Timbangan</button>}
      </div>
      {load.cancelReason && <div className="mt-3 text-xs text-[#fca5a5]">Alasan batal: {load.cancelReason}</div>}
    </div>
  );

  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div><div className="label-mono mb-2">Operasional Penerimaan PO</div><h1 className="font-display text-3xl sm:text-4xl font-bold">Penerimaan & Bongkar Kendaraan</h1><p className="text-sm text-[#8b93a1] mt-2">Satu kendaraan = satu sesi bongkar. PO dan stok baru berubah ketika Selesai Bongkar.</p></div>
      <div className="flex flex-wrap gap-2"><button onClick={() => navigate('/catat?mode=masuk')} className="btn-primary inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold"><Truck size={14}/> Tambah Kendaraan PO</button><button onClick={loadAll} className="inline-flex items-center gap-2 rounded-lg border border-[#294263] px-3 py-2 text-xs text-[#93c5fd]"><RefreshCcw size={14}/> Refresh</button></div>
    </div>

    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      <div className="card-surface p-4"><div className="text-xs text-[#8b93a1]">Menunggu / Bongkar</div><div className="font-display text-2xl font-bold mt-1">{active.length}</div></div>
      <div className="card-surface p-4"><div className="text-xs text-[#8b93a1]">Sedang Bongkar</div><div className="font-display text-2xl font-bold mt-1 text-[#60a5fa]">{active.filter((x) => x.status === 'Sedang Bongkar').length}</div></div>
      <div className="card-surface p-4"><div className="text-xs text-[#8b93a1]">Selesai</div><div className="font-display text-2xl font-bold mt-1 text-[#22c55e]">{history.filter((x) => x.status === 'Selesai').length}</div></div>
    </div>

    {loading ? <div className="card-surface p-10 text-center text-[#8b93a1]">Memuat kendaraan...</div> : <>
      <section><div className="flex items-center gap-2 mb-3"><Clock3 size={17}/><h2 className="font-display text-xl font-bold">Kendaraan Aktif</h2></div><div className="space-y-3">{active.length ? active.map(renderLoad) : <div className="card-surface p-8 text-center text-[#6b7688]">Tidak ada kendaraan menunggu bongkar.</div>}</div></section>
      <section>
        <div className="flex items-center gap-2 mb-3"><RotateCcw size={17}/><h2 className="font-display text-xl font-bold">Riwayat Kendaraan</h2></div>
        <div className="space-y-3">{paginatedHistory.map(renderLoad)}</div>
        <PaginationControls page={historyPage} totalItems={history.length} pageSize={historyPageSize} onChange={setHistoryPage} label="transaksi penerimaan" />
      </section>
    </>}

    {completion && <div className="fixed inset-0 z-[90] bg-black/75 flex items-center justify-center p-4"><div className="card-surface w-full max-w-4xl max-h-[92vh] overflow-y-auto p-6">
      <h2 className="font-display text-2xl font-bold">Selesaikan Bongkar · {completion.load.loadNo}</h2>
      <p className="text-xs text-[#8b93a1] mt-1">Isi jumlah aktual per kendaraan. Baik masuk tumpukan, rusak masuk Area Barang Rusak. Rencana yang tidak diterima tetap menjadi outstanding PO.</p>
      {completion.fullOvertime && <div className="mt-3 rounded-lg border border-[#b45309] bg-[#1f1408] px-3 py-2 text-xs text-[#fbbf24]">Mulai bongkar setelah 16.00 · seluruh jumlah aktual otomatis dihitung lembur.</div>}
      {completion.crossesCutoff && <div className="mt-3 rounded-lg border border-[#b45309] bg-[#1f1408] px-3 py-2 text-xs text-[#fbbf24]">Pekerjaan melewati 16.00 · isi hanya jumlah yang dibongkar setelah 16.00.</div>}
      <div className="space-y-3 mt-4">{completion.rows.map((row, index) => {
        const actual = Number(row.goodQty || 0) + Number(row.damagedQty || 0);
        const overtime = completion.fullOvertime ? actual : Number(row.overtimeQty || 0);
        const normal = Math.max(actual - overtime, 0);
        return <div key={row.productId} className="rounded-xl border border-[#243044] p-4">
          <div className="flex flex-wrap justify-between gap-2"><div><div className="font-semibold">{row.name}</div><div className="text-[10px] text-[#8b93a1]">{row.sku} · Rencana {formatNum(row.plannedQty)} {row.unit}</div></div><div className="text-xs font-mono text-[#93c5fd]">Normal {formatNum(normal)} · Lembur {formatNum(overtime)} {row.unit}</div></div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-3">
            <div><label className="text-[10px] text-[#8b93a1]">Tumpukan barang baik</label><select value={row.stackCode} onChange={(e) => setCompleteRow(index,{stackCode:e.target.value})} className="w-full mt-1 bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2"><option value="">Pilih...</option>{STACKS.map((code)=><option key={code}>{code}</option>)}</select></div>
            <div><label className="text-[10px] text-[#8b93a1]">Kedaluwarsa</label><input type="date" value={row.exp} onChange={(e) => setCompleteRow(index,{exp:e.target.value})} className="w-full mt-1 bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2"/></div>
            <div><label className="text-[10px] text-[#fbbf24]">Setelah 16.00</label><input type="number" min="0" max={actual} step="any" disabled={completion.fullOvertime || !completion.crossesCutoff} value={completion.fullOvertime ? actual : row.overtimeQty} onChange={(e) => setCompleteRow(index,{overtimeQty:e.target.value})} className="w-full mt-1 bg-[#0b0f17] border border-[#7c5a1f] rounded-lg px-3 py-2 disabled:opacity-60"/></div>
          </div>
          <div className="mt-3 rounded-lg border border-[#263244] bg-[#0a0f17] p-3">
            <div className="text-[10px] uppercase tracking-wide text-[#8b93a1] mb-2">Kuantum aktual hasil bongkar</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div><label className="text-xs font-semibold text-[#22c55e]">Baik ({row.unit})</label><input type="number" min="0" max={row.plannedQty} step="any" value={row.goodQty} onChange={(e) => setCompleteRow(index,{goodQty:e.target.value})} className="w-full mt-1 bg-[#0b0f17] border border-[#166534] rounded-lg px-3 py-2.5 font-mono"/></div>
              <div><label className="text-xs font-semibold text-[#f59e0b]">Rusak ({row.unit})</label><input type="number" min="0" max={row.plannedQty} step="any" value={row.damagedQty} onChange={(e) => setCompleteRow(index,{damagedQty:e.target.value})} className="w-full mt-1 bg-[#0b0f17] border border-[#92400e] rounded-lg px-3 py-2.5 font-mono"/></div>
            </div>
          </div>
        </div>;
      })}</div>
      <textarea rows={2} value={completion.note} onChange={(e)=>setCompletion({...completion,note:e.target.value})} placeholder="Catatan bongkar (opsional)" className="w-full mt-4 bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5"/>
      <div className="flex justify-end gap-2 mt-5"><button disabled={Boolean(busy)} onClick={()=>setCompletion(null)} className="px-4 py-2 rounded-lg border border-[#242f3d]">Batal</button><button disabled={Boolean(busy)} onClick={completeLoad} className="btn-primary px-5 py-2 rounded-lg font-semibold disabled:opacity-50">{busy ? 'Menyimpan...' : 'Selesai Bongkar & Simpan'}</button></div>
    </div></div>}

    {cancelModal && <div className="fixed inset-0 z-[90] bg-black/75 flex items-center justify-center p-4"><div className="card-surface w-full max-w-md p-6">
      <h2 className="font-display text-xl font-bold">Batalkan Kendaraan</h2>
      <p className="text-xs text-[#8b93a1] mt-1">{cancelModal.load.loadNo} · {cancelModal.load.polisi}. Pembatalan tidak mengurangi PO dan tidak mengubah stok.</p>
      <textarea rows={3} value={cancelModal.reason} onChange={(e)=>setCancelModal({...cancelModal,reason:e.target.value})} placeholder="Alasan pembatalan" className="w-full mt-4 bg-[#0b0f17] border border-[#7f1d1d] rounded-lg px-3 py-2.5"/>
      <div className="flex justify-end gap-2 mt-4"><button disabled={Boolean(busy)} onClick={()=>setCancelModal(null)} className="px-4 py-2 rounded-lg border border-[#242f3d]">Kembali</button><button disabled={Boolean(busy)} onClick={cancelLoad} className="px-4 py-2 rounded-lg bg-[#b91c1c] text-white disabled:opacity-50">{busy ? 'Membatalkan...' : 'Batalkan Kendaraan'}</button></div>
    </div></div>}
  </div>;
};

export default Penerimaan;
