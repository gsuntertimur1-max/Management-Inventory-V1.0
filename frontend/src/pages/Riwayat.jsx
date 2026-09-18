import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { Search, Download, DollarSign, Printer, X, CheckCircle2, AlertTriangle, CreditCard } from 'lucide-react';
import { useData } from '../context/DataContext';
import api, { apiError, downloadApiFile } from '../lib/api';
import { formatNum, formatDate, formatRp } from '../mock';
import { toast } from 'sonner';
import { packagingText, totalWeight } from '../lib/packaging';

const typeBadge = (type) => {
  if (type === 'MASUK') return { background: 'rgba(34,197,94,.15)', color: '#22c55e' };
  if (type === 'KELUAR') return { background: 'rgba(239,68,68,.15)', color: '#ef4444' };
  if (type === 'KOREKSI') return { background: 'rgba(245,158,11,.15)', color: '#f59e0b' };
  if (type === 'PENYESUAIAN') return { background: 'rgba(59,130,246,.15)', color: '#60a5fa' };
  return { background: 'rgba(148,163,184,.15)', color: '#94a3b8' };
};

const transactionChannel = (transaction) => {
  if (transaction.channel) return transaction.channel;
  return transaction.type === 'KOREKSI' ? '' : 'KOM';
};

const normalizeUnloadingGroup = (value) => {
  const text = String(value || '').toUpperCase();
  if (!text || text.includes('RTR')) return '';
  if (text.includes('GRUP 2') || text.includes('MANDOR 2') || text.includes('MP1') || /21-24/.test(text)) {
    return 'MANDOR 2 - MP1/GBB 21-24';
  }
  return 'MANDOR 1 - GBB 17-20';
};

const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;',
}[char]));

const Riwayat = () => {
  const { transactions, outboundLoads, fetchAll, canWrite } = useData();
  const [q, setQ] = useState('');
  const [type, setType] = useState('SEMUA');
  const [kondisi, setKondisi] = useState('SEMUA');
  const [channel, setChannel] = useState('SEMUA');
  const [exporting, setExporting] = useState(false);
  const [unloadingOpen, setUnloadingOpen] = useState(false);
  const [loadingOpen, setLoadingOpen] = useState(false);
  const [costSettlements, setCostSettlements] = useState({ loading: [], unloading: [] });
  const [feePayment, setFeePayment] = useState(null);
  const [settlementModal, setSettlementModal] = useState(null);
  const [savingPayment, setSavingPayment] = useState(false);

  const loadCostSettlements = useCallback(async () => {
    try {
      const { data } = await api.get('/cost-settlements');
      setCostSettlements({ loading: data.loading || [], unloading: data.unloading || [] });
    } catch (error) {
      console.error('cost settlements failed', error);
    }
  }, []);

  useEffect(() => {
    loadCostSettlements();
  }, [loadCostSettlements]);

  const filtered = transactions.filter((t) => {
    const query = q.toLowerCase();
    const auditChannel = transactionChannel(t);
    return (type === 'SEMUA' || t.type === type)
      && (kondisi === 'SEMUA' || t.kondisi === kondisi)
      && (channel === 'SEMUA' || auditChannel === channel)
      && (
        (t.ref || '').toLowerCase().includes(query)
        || (t.po_no || '').toLowerCase().includes(query)
        || (t.product || '').toLowerCase().includes(query)
        || (t.sku || '').toLowerCase().includes(query)
        || (t.penerima || '').toLowerCase().includes(query)
        || (t.correction_reason || '').toLowerCase().includes(query)
      );
  });
  const totalIn = transactions.filter((t) => t.type === 'MASUK' && !t.voided).reduce((a, t) => a + Number(t.change || 0), 0);
  const totalOut = transactions.filter((t) => t.type === 'KELUAR' && !t.voided).reduce((a, t) => a + Number(t.change || 0), 0);
  const totalCorrections = transactions.filter((t) => t.type === 'KOREKSI').length;

  const unloadingDays = useMemo(() => {
    const days = {};
    transactions
      .filter((t) => t.type === 'MASUK' && !t.voided && Number(t.unloading_cost?.total || 0) > 0)
      .forEach((t) => {
        const group = normalizeUnloadingGroup(t.unloading_group);
        if (!group) return;
        const date = t.operational_date || String(t.time || '').slice(0, 10) || '-';
        const day = days[date] || {
          date,
          totals: { labor: 0, daily: 0, warehouse: 0, total: 0, chargeable: 0 },
          groups: {},
          items: [],
        };
        const groupTotals = day.groups[group] || { labor: 0, daily: 0, warehouse: 0, total: 0, chargeable: 0 };
        ['labor', 'daily', 'warehouse', 'total', 'chargeable'].forEach((key) => {
          const value = Number(t.unloading_cost?.[key] || 0);
          day.totals[key] += value;
          groupTotals[key] += value;
        });
        day.groups[group] = groupTotals;
        day.items.push({ ...t, unloading_group: group });
        days[date] = day;
      });
    return Object.values(days).sort((a, b) => String(b.date).localeCompare(String(a.date)));
  }, [transactions]);

  const unloadingGrandTotal = unloadingDays.reduce((sum, day) => sum + Number(day.totals.total || 0), 0);

  const loadingDays = useMemo(() => {
    const days = {};
    (outboundLoads || [])
      .filter((load) => load.status === 'Selesai' && Number(load.loading_cost?.total || 0) > 0)
      .forEach((load) => {
        const date = load.operational_date || String(load.completed_at || load.created_at || '').slice(0, 10) || '-';
        const day = days[date] || {
          date,
          totals: { labor: 0, daily: 0, warehouse: 0, total: 0, chargeable: 0, collected: 0, outstanding: 0 },
          groups: {},
          items: [],
          loads: [],
        };

        ['labor', 'daily', 'warehouse', 'total', 'chargeable'].forEach((key) => {
          day.totals[key] += Number(load.loading_cost?.[key] || 0);
        });
        day.totals.collected += Number(load.loading_fee_payment_total || 0);
        day.totals.outstanding += Math.max(Number(load.loading_cost?.chargeable || 0) - Number(load.loading_fee_payment_total || 0), 0);

        (load.items || []).forEach((item, index) => {
          const group = item.crewGroup || 'TANPA GRUP BIAYA';
          const fee = item.loadingFee || {};
          const groupTotals = day.groups[group] || { labor: 0, daily: 0, warehouse: 0, total: 0, chargeable: 0 };
          ['labor', 'daily', 'warehouse', 'total', 'chargeable'].forEach((key) => {
            groupTotals[key] += Number(fee[key] || 0);
          });
          day.groups[group] = groupTotals;
          day.items.push({
            id: `${load.id}-${index}`,
            loadId: load.id,
            antrian: load.antrian || '',
            bonNo: load.bon_no || '',
            suratJalanNo: load.surat_jalan_no || '',
            documentNo: item.documentNo || load.ref || '',
            product: item.name || '',
            sku: item.sku || '',
            qty: Number(item.qty || 0),
            unit: item.unit || '',
            stackCode: item.stackCode || item.location || '',
            crewGroup: group,
            fee,
            pengambil: load.pengambil || load.party || '',
            paymentStatus: load.loading_fee_payment_status || (Number(load.loading_cost?.chargeable || 0) > 0 ? 'BELUM_DIBAYAR' : 'TIDAK_DITAGIH'),
            outstanding: Math.max(Number(load.loading_cost?.chargeable || 0) - Number(load.loading_fee_payment_total || 0), 0),
            payments: load.loading_fee_payments || [],
            isFirstLoadItem: index === 0,
          });
        });

        day.loads.push(load);
        days[date] = day;
      });
    return Object.values(days).sort((a, b) => String(b.date).localeCompare(String(a.date)));
  }, [outboundLoads]);

  const loadingGrandTotal = loadingDays.reduce((sum, day) => sum + Number(day.totals.total || 0), 0);

  const settlementIndex = useMemo(() => {
    const index = { loading: {}, unloading: {} };
    ['loading', 'unloading'].forEach((kind) => {
      (costSettlements[kind] || []).forEach((row) => {
        index[kind][`${row.date}:${row.recipient}`] = row;
      });
    });
    return index;
  }, [costSettlements]);

  const getSettlementInfo = (kind, date, recipient, total) => {
    const row = settlementIndex[kind]?.[`${date}:${recipient}`] || null;
    const paid = Math.min(Number(row?.amount || 0), Number(total || 0));
    const outstanding = Math.max(Number(total || 0) - paid, 0);
    return { row, paid, outstanding, settled: Number(total || 0) > 0 && outstanding <= 1e-9 };
  };

  const accumulatedUnpaid = (kind, days, recipient, key) => days.reduce(
    (sum, day) => sum + getSettlementInfo(kind, day.date, recipient, day.totals[key]).outstanding,
    0,
  );

  const loadingLaborUnpaid = accumulatedUnpaid('loading', loadingDays, 'BURUH', 'labor');
  const loadingDailyUnpaid = accumulatedUnpaid('loading', loadingDays, 'HARIAN', 'daily');
  const unloadingLaborUnpaid = accumulatedUnpaid('unloading', unloadingDays, 'BURUH', 'labor');
  const unloadingDailyUnpaid = accumulatedUnpaid('unloading', unloadingDays, 'HARIAN', 'daily');

  const renderSettlementCard = (kind, day, recipient, amount) => {
    const label = recipient === 'BURUH' ? 'Buruh' : 'Harian / UH';
    const info = getSettlementInfo(kind, day.date, recipient, amount);
    if (Number(amount || 0) <= 0) return null;
    return (
      <div className={`rounded-lg border px-3 py-2 text-xs ${info.settled ? 'border-[#166534] bg-[#14532d]/10' : 'border-[#7f1d1d] bg-[#7f1d1d]/10'}`}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="font-semibold flex items-center gap-1.5">{info.settled ? <CheckCircle2 size={13} className="text-[#4ade80]" /> : <AlertTriangle size={13} className="text-[#f87171]" />} {label}</div>
            <div className={info.settled ? 'text-[#4ade80] mt-1' : 'text-[#f87171] mt-1'}>{info.settled ? 'Sudah dibayar' : `Belum dibayar ${formatRp(info.outstanding)}`}</div>
            {info.row && <div className="text-[10px] text-[#8b93a1] mt-1">{formatDate(info.row.settledAt)} · {info.row.settledBy || '—'}{info.row.note ? ` · ${info.row.note}` : ''}</div>}
          </div>
          {canWrite && info.outstanding > 0 && (
            <button
              type="button"
              onClick={() => setSettlementModal({ kind, date: day.date, recipient, label, total: Number(amount || 0), outstanding: info.outstanding, note: '' })}
              className="px-2.5 py-1.5 rounded-lg border border-[#2563eb] text-[#93c5fd] hover:bg-[#2563eb]/10"
            >
              Tandai dibayar
            </button>
          )}
        </div>
      </div>
    );
  };

  const saveFeePayment = async () => {
    if (!feePayment || savingPayment) return;
    const amount = Number(feePayment.amount || 0);
    if (!(amount > 0) || amount > Number(feePayment.max || 0) + 1e-9) {
      toast.error('Nominal pembayaran harus lebih dari 0 dan tidak boleh melebihi sisa tagihan.');
      return;
    }
    setSavingPayment(true);
    try {
      await api.post(`/outbound-loads/${feePayment.loadId}/loading-fee-payment`, {
        amount,
        method: feePayment.method,
        payer: feePayment.payer,
        note: feePayment.note,
      });
      await fetchAll();
      toast.success('Pembayaran biaya muat berhasil dicatat');
      setFeePayment(null);
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setSavingPayment(false);
    }
  };

  const saveSettlement = async () => {
    if (!settlementModal || savingPayment) return;
    setSavingPayment(true);
    try {
      const prefix = settlementModal.kind === 'loading' ? 'loading-costs' : 'unloading-costs';
      await api.post(`/${prefix}/${settlementModal.date}/settle`, {
        recipient: settlementModal.recipient,
        note: settlementModal.note || '',
      });
      await loadCostSettlements();
      toast.success(`Pembayaran ${settlementModal.label} tanggal ${settlementModal.date} ditandai sudah dibayar`);
      setSettlementModal(null);
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setSavingPayment(false);
    }
  };

  const printLoadingDay = (day, group, recipient) => {
    const key = recipient === 'BURUH' ? 'labor' : 'daily';
    const title = recipient === 'BURUH' ? 'REKAP UPAH BURUH PEMUATAN' : 'REKAP UH GUDANG PEMUATAN';
    const items = (day.items || []).filter((item) => item.crewGroup === group && Number(item.fee?.[key] || 0) > 0);
    const rows = items.map((item, index) => `<tr><td>${index + 1}</td><td><b>${escapeHtml(item.product)}</b><br/><small>${escapeHtml(item.documentNo || item.bonNo || '—')} · ${escapeHtml(formatNum(item.qty))} ${escapeHtml(item.unit)} · ${escapeHtml(item.stackCode || '—')}${item.fee?.overtime ? ' · Lembur' : ''}${item.fee?.holiday ? ' · Hari Libur' : ''}</small></td><td class="r">Rp ${escapeHtml(formatNum(item.fee?.[key] || 0))}</td></tr>`).join('');
    const totalAmount = items.reduce((sum, item) => sum + Number(item.fee?.[key] || 0), 0);
    const w = window.open('', '_blank', 'width=460,height=720');
    if (!w) return toast.error('Izinkan popup untuk mencetak rekap thermal.');
    w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${title}</title><style>@page{size:80mm auto;margin:3mm}*{box-sizing:border-box}body{width:74mm;margin:0 auto;color:#000;font:12px/1.35 Arial,sans-serif}.center{text-align:center}.title{font-size:15px;font-weight:900;margin:6px 0}.sub{font-size:10px;margin-bottom:8px}table{width:100%;border-collapse:collapse;font-size:11px}th,td{border-bottom:1px dashed #000;padding:6px 2px;text-align:left;vertical-align:top}.r{text-align:right;font-weight:700}.total{font-size:17px;font-weight:900;margin:12px 0}.line{border-top:1px solid #000;margin-top:38px;padding-top:5px;text-align:center;font-size:11px;font-weight:700}small{font-size:9px}</style></head><body><div class="center"><b>PERUM BULOG</b><div>Gudang Sunter Timur I & II</div><div class="title">${title}</div><div class="sub">${escapeHtml(group)}<br/>Tanggal: ${escapeHtml(day.date)}</div></div><table><thead><tr><th>No</th><th>Pemuatan</th><th class="r">Biaya</th></tr></thead><tbody>${rows || '<tr><td colspan="3">Tidak ada biaya</td></tr>'}</tbody></table><div class="total">TOTAL: Rp ${escapeHtml(formatNum(totalAmount))}</div><div class="line">Petugas Gudang</div><div class="line">Penerima ${recipient === 'BURUH' ? 'Buruh' : 'UH Gudang'}</div><script>window.onload=()=>window.print()</script></body></html>`);
    w.document.close();
  };

  const printUnloadingDay = (day, group, recipient) => {
    const key = recipient === 'BURUH' ? 'labor' : 'daily';
    const title = recipient === 'BURUH' ? 'REKAP UPAH BURUH BONGKAR' : 'REKAP UH GUDANG BONGKAR';
    const items = (day.items || []).filter((item) => item.unloading_group === group && Number(item.unloading_cost?.[key] || 0) > 0);
    const rows = items.map((item, index) => `<tr><td>${index + 1}</td><td><b>${escapeHtml(item.product)}</b><br/><small>${escapeHtml(item.ref || item.po_no || '—')} · ${escapeHtml(formatNum(Math.abs(Number(item.change || 0))))} ${escapeHtml(item.unit || '')}${item.unloading_cost?.overtime ? ' · Lembur' : ''}${item.unloading_cost?.holiday ? ' · Hari Libur' : ''}</small></td><td class="r">Rp ${escapeHtml(formatNum(item.unloading_cost?.[key] || 0))}</td></tr>`).join('');
    const totalAmount = items.reduce((sum, item) => sum + Number(item.unloading_cost?.[key] || 0), 0);
    const w = window.open('', '_blank', 'width=460,height=720');
    if (!w) return toast.error('Izinkan popup untuk mencetak rekap thermal.');
    w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${title}</title><style>@page{size:80mm auto;margin:3mm}*{box-sizing:border-box}body{width:74mm;margin:0 auto;color:#000;font:12px/1.35 Arial,sans-serif}.center{text-align:center}.title{font-size:15px;font-weight:900;margin:6px 0}.sub{font-size:10px;margin-bottom:8px}table{width:100%;border-collapse:collapse;font-size:11px}th,td{border-bottom:1px dashed #000;padding:6px 2px;text-align:left;vertical-align:top}.r{text-align:right;font-weight:700}.total{font-size:17px;font-weight:900;margin:12px 0}.line{border-top:1px solid #000;margin-top:38px;padding-top:5px;text-align:center;font-size:11px;font-weight:700}small{font-size:9px}</style></head><body><div class="center"><b>PERUM BULOG</b><div>Gudang Sunter Timur I & II</div><div class="title">${title}</div><div class="sub">${escapeHtml(group)}<br/>Tanggal: ${escapeHtml(day.date)}</div></div><table><thead><tr><th>No</th><th>Penerimaan</th><th class="r">Biaya</th></tr></thead><tbody>${rows || '<tr><td colspan="3">Tidak ada biaya</td></tr>'}</tbody></table><div class="total">TOTAL: Rp ${escapeHtml(formatNum(totalAmount))}</div><div class="line">Petugas Gudang</div><div class="line">Penerima ${recipient === 'BURUH' ? 'Buruh' : 'UH Gudang'}</div><script>window.onload=()=>window.print()</script></body></html>`);
    w.document.close();
  };

  const exportCurrentMonth = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      await downloadApiFile('/export/transactions-v2.xlsx', 'riwayat_transaksi.xlsx');
      toast.success('File Excel riwayat bulan ini berhasil diunduh');
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Audit Trail</div>
          <h1 className="font-display text-4xl font-bold">Riwayat Transaksi Stok</h1>
          <p className="text-[#8b93a1] mt-2">{filtered.length} transaksi ditampilkan</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <div className="card-surface px-5 py-3"><div className="label-mono text-[9px] mb-1">Masuk Aktif</div><div className="font-mono text-2xl font-bold text-[#22c55e]">+{formatNum(totalIn)}</div></div>
          <div className="card-surface px-5 py-3"><div className="label-mono text-[9px] mb-1">Total Keluar</div><div className="font-mono text-2xl font-bold text-[#ef4444]">{formatNum(totalOut)}</div></div>
          <div className="card-surface px-5 py-3"><div className="label-mono text-[9px] mb-1">Koreksi Audit</div><div className="font-mono text-2xl font-bold text-[#f59e0b]">{formatNum(totalCorrections)}</div></div>
        </div>
      </div>

      <div className="card-surface p-6">
        <div className="flex flex-wrap gap-3 mb-4">
          <div className="relative flex-1 min-w-[240px]"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" /><input data-testid="riwayat-search-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari No. Ref/PO, produk, SKU, pihak terkait, alasan koreksi..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
          <select data-testid="riwayat-type-filter" value={type} onChange={(e) => setType(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none"><option value="SEMUA">SEMUA TIPE</option><option value="MASUK">PENERIMAAN (MASUK)</option><option value="KELUAR">PENGELUARAN (KELUAR)</option><option value="PENYESUAIAN">PENYESUAIAN</option><option value="KOREKSI">KOREKSI</option></select>
          <select value={channel} onChange={(e) => setChannel(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none"><option value="SEMUA">Semua Saluran</option><option value="PSO">PSO</option><option value="KOM">KOM</option></select>
          <select data-testid="riwayat-kondisi-filter" value={kondisi} onChange={(e) => setKondisi(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none"><option value="SEMUA">SEMUA KONDISI</option><option value="BAIK">BAIK</option><option value="RUSAK">RUSAK</option><option value="DOKUMEN">DOKUMEN</option></select>
          <button onClick={() => { setType('MASUK'); setUnloadingOpen(true); }} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#8a5a16] text-[#fbbf24] hover:bg-[#f59e0b]/10"><DollarSign size={15} /> Rekap Biaya Bongkar</button>
          <button onClick={() => { setType('KELUAR'); setLoadingOpen(true); }} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#2563eb] text-[#93c5fd] hover:bg-[#2563eb]/10"><DollarSign size={15} /> Rekap Biaya Muat</button>
          <button onClick={exportCurrentMonth} disabled={exporting} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24] disabled:opacity-60 disabled:cursor-wait"><Download size={15} /> {exporting ? 'Menyiapkan…' : 'Unduh Excel Bulan Ini'}</button>
        </div>
        <p className="text-xs text-[#6b7688] mb-4">Transaksi yang dibatalkan tetap tampil sebagai audit trail dan tidak dihitung pada Masuk Aktif. Koreksi tidak pernah menghapus riwayat transaksi asli.</p>

        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['Waktu', 'No. Referensi', 'Saluran', 'Rangkaian Dokumen', 'No. PO', 'Antrian', 'Tipe', 'Kondisi', 'Produk', 'Perubahan', 'Kadaluarsa', 'Pihak Terkait', 'Dicatat Oleh'].map((h) => <th key={h} className="py-2.5 pr-4 font-semibold whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {filtered.length === 0 ? <tr><td colSpan={13} className="py-8 text-center text-[#6b7688]">Belum ada transaksi yang sesuai filter.</td></tr> : filtered.map((t) => {
                const auditChannel = transactionChannel(t);
                const badge = typeBadge(t.type);
                return (
                  <tr key={t.id} className={`tbl-row border-b border-[#131a24] ${t.voided ? 'opacity-55' : ''}`}>
                    <td className="py-3 pr-4 whitespace-nowrap text-[#8b93a1]">{formatDate(t.time)}</td>
                    <td className="py-3 pr-4 font-mono text-xs"><div>{t.ref || '—'}</div>{t.voided && <span className="inline-block mt-1 text-[9px] px-1.5 py-0.5 rounded bg-[#7f1d1d]/30 text-[#fca5a5]">DIBATALKAN</span>}</td>
                    <td className="py-3 pr-4">{auditChannel ? <span className={`text-[10px] font-mono px-2 py-0.5 rounded ${auditChannel === 'PSO' ? 'bg-[#2563eb]/15 text-[#60a5fa]' : 'bg-[#a855f7]/15 text-[#c084fc]'}`}>{auditChannel}</span> : <span className="text-[#6b7688]">—</span>}</td>
                    <td className="py-3 pr-4 font-mono text-xs whitespace-nowrap"><span className="text-[#93c5fd]">{t.document_type || '—'}</span>{t.parent_document && <span className="text-[#6b7688]"> ← {t.parent_document}</span>}</td>
                    <td className="py-3 pr-4 font-mono text-xs text-[#60a5fa]">{t.po_no || '—'}</td>
                    <td className="py-3 pr-4 font-mono text-xs">{t.antrian || '—'}</td>
                    <td className="py-3 pr-4"><span className="text-[10px] font-mono px-2 py-0.5 rounded" style={badge}>{t.type}</span></td>
                    <td className="py-3 pr-4"><span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#1a222e] text-[#8b93a1]">{t.kondisi || '—'}</span></td>
                    <td className="py-3 pr-4"><div className="font-medium">{t.product}</div><div className="label-mono text-[10px]">{t.sku}</div>{t.correction_reason && <div className="mt-1 text-[10px] text-[#f59e0b] max-w-[240px]">Alasan: {t.correction_reason}</div>}</td>
                    <td className={`py-3 pr-4 font-mono font-semibold ${Number(t.change || 0) > 0 ? 'text-[#22c55e]' : Number(t.change || 0) < 0 ? 'text-[#ef4444]' : 'text-[#8b93a1]'}`}><div>{Number(t.change || 0) > 0 ? '+' : ''}{formatNum(Number(t.change || 0))} {t.unit || ''}</div>{(packagingText(Math.abs(Number(t.change || 0)), t, formatNum) || Number(t.weight || 0) > 0) && <div className="mt-1 text-[10px] font-sans font-normal text-[#8b93a1]">{packagingText(Math.abs(Number(t.change || 0)), t, formatNum)}{packagingText(Math.abs(Number(t.change || 0)), t, formatNum) && Number(t.weight || 0) > 0 ? ' · ' : ''}{Number(t.weight || 0) > 0 ? `${formatNum(Math.abs(Number(t.total_weight || totalWeight(Math.abs(Number(t.change || 0)), t))))} kg` : ''}</div>}</td>
                    <td className="py-3 pr-4 font-mono text-xs whitespace-nowrap">{t.exp || '—'}</td>
                    <td className="py-3 pr-4 text-[#c7d0dc]">{t.penerima || '—'}</td>
                    <td className="py-3 pr-4 text-[#8b93a1] text-xs">{t.operator || '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {loadingOpen && createPortal(
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/75 p-4 sm:p-6 overflow-y-auto">
          <div className="card-surface w-full max-w-6xl p-6 fade-up max-h-[calc(100dvh-3rem)] overflow-y-auto">
            <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
              <div>
                <div className="label-mono text-[10px] text-[#93c5fd]">History Pengeluaran</div>
                <h2 className="font-display text-xl font-bold mt-1">Rekap Biaya Muat</h2>
                <p className="text-xs text-[#8b93a1] mt-1">3 mandor pemuatan: GBB 17–20, MP1/GBB 21–24, dan RTR.</p>
              </div>
              <div className="flex items-start gap-3">
                <div className="text-right"><div className="text-[10px] text-[#8b93a1]">Total tercatat</div><div className="font-mono font-bold text-[#93c5fd]">{formatRp(loadingGrandTotal)}</div></div>
                <button onClick={() => setLoadingOpen(false)} className="text-[#8b93a1] hover:text-white"><X size={20} /></button>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
              <div className={`rounded-lg border p-3 ${loadingLaborUnpaid > 0 ? 'border-[#7f1d1d] bg-[#7f1d1d]/10' : 'border-[#166534] bg-[#14532d]/10'}`}>
                <div className="text-[10px] text-[#8b93a1]">Akumulasi Buruh belum dibayar</div>
                <div className={`font-mono font-bold mt-1 ${loadingLaborUnpaid > 0 ? 'text-[#f87171]' : 'text-[#4ade80]'}`}>{formatRp(loadingLaborUnpaid)}</div>
              </div>
              <div className={`rounded-lg border p-3 ${loadingDailyUnpaid > 0 ? 'border-[#7f1d1d] bg-[#7f1d1d]/10' : 'border-[#166534] bg-[#14532d]/10'}`}>
                <div className="text-[10px] text-[#8b93a1]">Akumulasi Harian / UH belum dibayar</div>
                <div className={`font-mono font-bold mt-1 ${loadingDailyUnpaid > 0 ? 'text-[#f87171]' : 'text-[#4ade80]'}`}>{formatRp(loadingDailyUnpaid)}</div>
              </div>
            </div>

            <div className="space-y-4">
              {loadingDays.length === 0 ? <div className="rounded-lg border border-[#242f3d] p-6 text-center text-sm text-[#6b7688]">Belum ada pemuatan selesai dengan biaya muat.</div> : loadingDays.map((day) => (
                <div key={day.date} className="rounded-xl border border-[#2b3545] bg-[#0b0f17] p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
                    <div>
                      <div className="font-semibold">{day.date}</div>
                      <div className="text-xs text-[#8b93a1] mt-1">Buruh {formatRp(day.totals.labor)} · UH {formatRp(day.totals.daily)} · Gudang {formatRp(day.totals.warehouse)} · Total <b className="text-[#93c5fd]">{formatRp(day.totals.total)}</b></div>
                    </div>
                    <div className="text-xs text-right">
                      <div>Tagihan pengambil <b className="text-[#fbbf24]">{formatRp(day.totals.chargeable)}</b></div>
                      <div className="mt-1">Diterima <b className="text-[#4ade80]">{formatRp(day.totals.collected)}</b> · Belum dibayar <b className="text-[#f87171]">{formatRp(day.totals.outstanding)}</b></div>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
                    {renderSettlementCard('loading', day, 'BURUH', day.totals.labor)}
                    {renderSettlementCard('loading', day, 'HARIAN', day.totals.daily)}
                  </div>

                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                    {['GRUP 1 - GBB 17-20', 'GRUP 2 - MP1/21-24', 'GRUP 3 - RTR'].map((group) => {
                      const values = day.groups[group];
                      if (!values) return null;
                      return (
                        <div key={group} className="rounded-lg border border-[#202a38] p-3">
                          <div className="font-semibold text-sm">{group}</div>
                          <div className="grid grid-cols-2 gap-2 mt-2 text-xs">
                            <div><span className="text-[#8b93a1]">Buruh</span><div className="font-mono">{formatRp(values.labor)}</div></div>
                            <div><span className="text-[#8b93a1]">UH</span><div className="font-mono">{formatRp(values.daily)}</div></div>
                            <div><span className="text-[#8b93a1]">Gudang</span><div className="font-mono">{formatRp(values.warehouse)}</div></div>
                            <div><span className="text-[#8b93a1]">Total</span><div className="font-mono font-bold text-[#93c5fd]">{formatRp(values.total)}</div></div>
                          </div>
                          <div className="flex flex-wrap gap-2 mt-3">
                            <button onClick={() => printLoadingDay(day, group, 'BURUH')} className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-[#294263] text-[#93c5fd]"><Printer size={12} /> Buruh 80mm</button>
                            <button onClick={() => printLoadingDay(day, group, 'HARIAN')} className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-[#294263] text-[#93c5fd]"><Printer size={12} /> UH 80mm</button>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="overflow-x-auto mt-4">
                    <table className="w-full text-xs">
                      <thead><tr className="text-left border-b border-[#242f3d]"><th className="py-2 pr-3">Dokumen / Bon</th><th className="py-2 pr-3">Produk</th><th className="py-2 pr-3">Tumpukan</th><th className="py-2 pr-3">Mandor</th><th className="py-2 pr-3">Pengambil</th><th className="py-2 pr-3">Status Tagihan</th><th className="py-2 text-right">Biaya</th></tr></thead>
                      <tbody>{day.items.map((item) => {
                        const latestPayment = item.payments?.length ? item.payments[item.payments.length - 1] : null;
                        return <tr key={item.id} className="border-b border-[#171e29]"><td className="py-2 pr-3 font-mono"><div>{item.documentNo || '—'}</div><div className="text-[10px] text-[#6b7688]">{item.bonNo || item.antrian || '—'}{item.suratJalanNo ? ` · ${item.suratJalanNo}` : ''}</div></td><td className="py-2 pr-3"><div className="font-medium">{item.product}</div><div className="text-[10px] text-[#6b7688]">{formatNum(item.qty)} {item.unit}{item.fee?.overtime ? ' · Lembur' : ''}{item.fee?.holiday ? ' · Hari Libur' : ''}</div></td><td className="py-2 pr-3 font-mono">{item.stackCode || '—'}</td><td className="py-2 pr-3">{item.crewGroup}</td><td className="py-2 pr-3">{item.pengambil || '—'}</td><td className="py-2 pr-3"><span className={item.paymentStatus === 'LUNAS' ? 'text-[#4ade80]' : item.paymentStatus === 'SEBAGIAN' ? 'text-[#fbbf24]' : item.paymentStatus === 'TIDAK_DITAGIH' ? 'text-[#8b93a1]' : 'text-[#f87171]'}>{item.paymentStatus === 'LUNAS' ? 'Sudah dibayar' : item.paymentStatus === 'SEBAGIAN' ? 'Dibayar sebagian' : item.paymentStatus === 'TIDAK_DITAGIH' ? 'Tidak ditagihkan' : 'Belum dibayar'}</span>{item.outstanding > 0 && <div className="font-mono text-[10px] mt-1">{formatRp(item.outstanding)}</div>}{item.isFirstLoadItem && latestPayment && <div className="text-[10px] text-[#8b93a1] mt-1">Terakhir {formatDate(latestPayment.time)} · {latestPayment.method}{latestPayment.payer ? ` · ${latestPayment.payer}` : ''}</div>}{canWrite && item.isFirstLoadItem && item.outstanding > 0 && item.paymentStatus !== 'TIDAK_DITAGIH' && <button type="button" onClick={() => setFeePayment({ loadId: item.loadId, max: item.outstanding, amount: String(item.outstanding), method: 'TUNAI', payer: item.pengambil || '', note: '' })} className="mt-2 inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-[#2563eb] text-[#93c5fd] hover:bg-[#2563eb]/10"><CreditCard size={12} /> Catat pembayaran</button>}</td><td className="py-2 text-right font-mono">{formatRp(item.fee?.total || 0)}</td></tr>;
                      })}</tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>,
        document.body
      )}

      {unloadingOpen && createPortal(
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/75 p-4 sm:p-6 overflow-y-auto">
          <div className="card-surface w-full max-w-5xl p-6 fade-up max-h-[calc(100dvh-3rem)] overflow-y-auto">
            <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
              <div>
                <div className="label-mono text-[10px] text-[#fbbf24]">History Penerimaan</div>
                <h2 className="font-display text-xl font-bold mt-1">Rekap Biaya Bongkar</h2>
                <p className="text-xs text-[#8b93a1] mt-1">Hanya 2 mandor bongkar: GBB 17–20 dan MP1/GBB 21–24. RTR tidak masuk rekap bongkar.</p>
              </div>
              <div className="flex items-start gap-3">
                <div className="text-right"><div className="text-[10px] text-[#8b93a1]">Total tercatat</div><div className="font-mono font-bold text-[#fbbf24]">{formatRp(unloadingGrandTotal)}</div></div>
                <button onClick={() => setUnloadingOpen(false)} className="text-[#8b93a1] hover:text-white"><X size={20} /></button>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
              <div className={`rounded-lg border p-3 ${unloadingLaborUnpaid > 0 ? 'border-[#7f1d1d] bg-[#7f1d1d]/10' : 'border-[#166534] bg-[#14532d]/10'}`}>
                <div className="text-[10px] text-[#8b93a1]">Akumulasi Buruh belum dibayar</div>
                <div className={`font-mono font-bold mt-1 ${unloadingLaborUnpaid > 0 ? 'text-[#f87171]' : 'text-[#4ade80]'}`}>{formatRp(unloadingLaborUnpaid)}</div>
              </div>
              <div className={`rounded-lg border p-3 ${unloadingDailyUnpaid > 0 ? 'border-[#7f1d1d] bg-[#7f1d1d]/10' : 'border-[#166534] bg-[#14532d]/10'}`}>
                <div className="text-[10px] text-[#8b93a1]">Akumulasi Harian / UH belum dibayar</div>
                <div className={`font-mono font-bold mt-1 ${unloadingDailyUnpaid > 0 ? 'text-[#f87171]' : 'text-[#4ade80]'}`}>{formatRp(unloadingDailyUnpaid)}</div>
              </div>
            </div>

            <div className="space-y-4">
              {unloadingDays.length === 0 ? <div className="rounded-lg border border-[#242f3d] p-6 text-center text-sm text-[#6b7688]">Belum ada penerimaan dengan biaya bongkar.</div> : unloadingDays.map((day) => (
                <div key={day.date} className="rounded-xl border border-[#2b3545] bg-[#0b0f17] p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
                    <div>
                      <div className="font-semibold">{day.date}</div>
                      <div className="text-xs text-[#8b93a1] mt-1">Buruh {formatRp(day.totals.labor)} · UH {formatRp(day.totals.daily)} · Gudang {formatRp(day.totals.warehouse)} · Total <b className="text-[#fbbf24]">{formatRp(day.totals.total)}</b></div>
                    </div>
                    {Number(day.totals.chargeable || 0) > 0 && <div className="text-xs rounded-lg border border-[#8a5a16] px-3 py-2 text-[#fbbf24]">Tagihan Pengirim {formatRp(day.totals.chargeable)}</div>}
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
                    {renderSettlementCard('unloading', day, 'BURUH', day.totals.labor)}
                    {renderSettlementCard('unloading', day, 'HARIAN', day.totals.daily)}
                  </div>

                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                    {['MANDOR 1 - GBB 17-20', 'MANDOR 2 - MP1/GBB 21-24'].map((group) => {
                      const values = day.groups[group];
                      if (!values) return null;
                      return (
                        <div key={group} className="rounded-lg border border-[#202a38] p-3">
                          <div className="font-semibold text-sm">{group}</div>
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-2 text-xs">
                            <div><span className="text-[#8b93a1]">Buruh</span><div className="font-mono">{formatRp(values.labor)}</div></div>
                            <div><span className="text-[#8b93a1]">UH</span><div className="font-mono">{formatRp(values.daily)}</div></div>
                            <div><span className="text-[#8b93a1]">Gudang</span><div className="font-mono">{formatRp(values.warehouse)}</div></div>
                            <div><span className="text-[#8b93a1]">Total</span><div className="font-mono font-bold text-[#fbbf24]">{formatRp(values.total)}</div></div>
                          </div>
                          <div className="flex flex-wrap gap-2 mt-3">
                            <button onClick={() => printUnloadingDay(day, group, 'BURUH')} className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-[#294263] text-[#93c5fd]"><Printer size={12} /> Buruh 80mm</button>
                            <button onClick={() => printUnloadingDay(day, group, 'HARIAN')} className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-[#294263] text-[#93c5fd]"><Printer size={12} /> UH 80mm</button>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="overflow-x-auto mt-4">
                    <table className="w-full text-xs">
                      <thead><tr className="text-left border-b border-[#242f3d]"><th className="py-2 pr-3">No. Ref / PO</th><th className="py-2 pr-3">Produk</th><th className="py-2 pr-3">Mandor</th><th className="py-2 pr-3">Kuantitas</th><th className="py-2 text-right">Biaya</th></tr></thead>
                      <tbody>{day.items.map((item) => <tr key={item.id} className="border-b border-[#171e29]"><td className="py-2 pr-3 font-mono">{item.po_no || item.ref || '—'}</td><td className="py-2 pr-3"><div className="font-medium">{item.product}</div><div className="text-[10px] text-[#6b7688]">{item.unloading_cost?.overtime ? 'Lembur ' : ''}{item.unloading_cost?.holiday ? 'Hari Libur' : ''}</div></td><td className="py-2 pr-3">{item.unloading_group}</td><td className="py-2 pr-3 font-mono">{formatNum(Math.abs(Number(item.change || 0)))} {item.unit || ''}</td><td className="py-2 text-right font-mono">{formatRp(item.unloading_cost?.total || 0)}</td></tr>)}</tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>,
        document.body
      )}

      {feePayment && createPortal(
        <div className="fixed inset-0 z-[150] flex items-center justify-center bg-black/80 p-4">
          <div className="card-surface w-full max-w-md p-5">
            <div className="flex items-center justify-between mb-4"><h3 className="font-display text-lg font-bold">Catat Pembayaran Biaya Muat</h3><button onClick={() => setFeePayment(null)} disabled={savingPayment} className="text-[#8b93a1] hover:text-white"><X size={18} /></button></div>
            <div className="rounded-lg border border-[#242f3d] p-3 mb-4 text-xs"><span className="text-[#8b93a1]">Sisa tagihan:</span> <b className="font-mono text-[#fbbf24]">{formatRp(feePayment.max)}</b></div>
            <div className="space-y-3">
              <div><label className="text-xs text-[#8b93a1] block mb-1">Nominal pembayaran</label><input type="number" min="0" max={feePayment.max} value={feePayment.amount} onChange={(e) => setFeePayment((prev) => ({ ...prev, amount: e.target.value }))} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
              <div><label className="text-xs text-[#8b93a1] block mb-1">Metode</label><select value={feePayment.method} onChange={(e) => setFeePayment((prev) => ({ ...prev, method: e.target.value }))} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none"><option value="TUNAI">Tunai</option><option value="TRANSFER">Transfer</option><option value="PIUTANG">Piutang</option></select></div>
              <div><label className="text-xs text-[#8b93a1] block mb-1">Pembayar</label><input value={feePayment.payer} onChange={(e) => setFeePayment((prev) => ({ ...prev, payer: e.target.value }))} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
              <div><label className="text-xs text-[#8b93a1] block mb-1">Catatan</label><textarea rows={2} value={feePayment.note} onChange={(e) => setFeePayment((prev) => ({ ...prev, note: e.target.value }))} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
            </div>
            <div className="flex justify-end gap-2 mt-5"><button onClick={() => setFeePayment(null)} disabled={savingPayment} className="px-4 py-2 rounded-lg border border-[#242f3d] text-sm">Batal</button><button onClick={saveFeePayment} disabled={savingPayment} className="btn-primary px-4 py-2 rounded-lg text-sm font-semibold">{savingPayment ? 'Menyimpan…' : 'Simpan pembayaran'}</button></div>
          </div>
        </div>,
        document.body
      )}

      {settlementModal && createPortal(
        <div className="fixed inset-0 z-[150] flex items-center justify-center bg-black/80 p-4">
          <div className="card-surface w-full max-w-md p-5">
            <div className="flex items-center justify-between mb-4"><h3 className="font-display text-lg font-bold">Tandai Pembayaran {settlementModal.label}</h3><button onClick={() => setSettlementModal(null)} disabled={savingPayment} className="text-[#8b93a1] hover:text-white"><X size={18} /></button></div>
            <div className="rounded-lg border border-[#242f3d] p-3 mb-4 text-xs"><div>Tanggal <b>{settlementModal.date}</b></div><div className="mt-1">Sisa belum dibayar <b className="font-mono text-[#f87171]">{formatRp(settlementModal.outstanding)}</b></div><div className="mt-1 text-[#8b93a1]">Setelah disimpan, status tanggal ini tercatat sebagai sudah dibayar. Jika kemudian ada biaya tambahan pada tanggal yang sama, sisa tambahan akan muncul lagi sebagai tunggakan.</div></div>
            <div><label className="text-xs text-[#8b93a1] block mb-1">Catatan pembayaran (opsional)</label><textarea rows={3} value={settlementModal.note} onChange={(e) => setSettlementModal((prev) => ({ ...prev, note: e.target.value }))} placeholder="Contoh: Dibayar transfer / diterima koordinator buruh" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
            <div className="flex justify-end gap-2 mt-5"><button onClick={() => setSettlementModal(null)} disabled={savingPayment} className="px-4 py-2 rounded-lg border border-[#242f3d] text-sm">Batal</button><button onClick={saveSettlement} disabled={savingPayment} className="btn-primary px-4 py-2 rounded-lg text-sm font-semibold">{savingPayment ? 'Menyimpan…' : 'Tandai sudah dibayar'}</button></div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};

export default Riwayat;
