import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Printer, MonitorSmartphone, Play, CheckCircle2 } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatNum, formatDate } from '../mock';
import { toast } from 'sonner';

const STATUS = {
  'Menunggu': { c: '#eab308', bg: 'rgba(234,179,8,.15)' },
  'Sedang Dimuat': { c: '#3b82f6', bg: 'rgba(59,130,246,.15)' },
  'Selesai': { c: '#22c55e', bg: 'rgba(34,197,94,.15)' },
};

const escapeHtml = (value) => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

const Pengeluaran = () => {
  const { outboundLoads, suratJalan, startOutboundLoad, completeOutboundLoad } = useData();
  const navigate = useNavigate();
  const [filter, setFilter] = useState('Semua Status');
  const [busyId, setBusyId] = useState('');

  const list = outboundLoads.filter((load) => filter === 'Semua Status' || load.status === filter);

  const findFinalSJ = (load) => suratJalan.find((sj) => sj.id === load.surat_jalan_id || sj.load_id === load.id);

  const printBonMuat = (load) => {
    const rows = (load.items || []).map((item) => `
      <div class="item">
        <div class="name">${escapeHtml(item.name)}</div>
        <div class="line"><span>${escapeHtml(formatNum(item.qty))} ${escapeHtml(item.unit || '')}</span><span>${escapeHtml(formatNum(item.berat || 0))} kg</span></div>
      </div>
    `).join('');

    const w = window.open('', '_blank', 'width=420,height=760');
    if (!w) {
      toast.error('Popup diblokir browser. Izinkan popup untuk mencetak Bon Muat.');
      return;
    }
    w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>Bon Muat ${escapeHtml(load.antrian)}</title><style>
      @page { size: 80mm auto; margin: 3mm; }
      * { box-sizing: border-box; }
      body { width: 74mm; margin: 0 auto; color: #000; font-family: Arial, sans-serif; font-size: 11px; }
      .center { text-align: center; }
      .title { font-size: 16px; font-weight: 800; margin-top: 2mm; }
      .queue-label { font-size: 11px; margin-top: 3mm; }
      .queue { font-size: 36px; line-height: 1; font-weight: 900; letter-spacing: 1px; margin: 1mm 0 3mm; }
      .sep { border-top: 1px dashed #000; margin: 2.5mm 0; }
      .meta { display: grid; grid-template-columns: 20mm 1fr; gap: 1mm 1.5mm; }
      .meta b { word-break: break-word; }
      .item { margin: 2mm 0; }
      .name { font-weight: 700; }
      .line { display: flex; justify-content: space-between; gap: 3mm; margin-top: .5mm; }
      .totals { font-weight: 700; }
      .warning { text-align: center; font-size: 10px; font-weight: 800; border: 1px solid #000; padding: 2mm; margin-top: 3mm; }
      .small { font-size: 9px; }
    </style></head><body>
      <div class="center"><div><b>PERUM BULOG</b></div><div>Gudang Sunter Timur I & II</div><div class="title">BON MUAT</div><div class="queue-label">NOMOR ANTRIAN</div><div class="queue">${escapeHtml(load.antrian)}</div></div>
      <div class="sep"></div>
      <div class="meta">
        <span>Tanggal</span><b>${escapeHtml(formatDate(load.started_at || load.created_at))}</b>
        <span>Tujuan</span><b>${escapeHtml(load.party || '-')}</b>
        <span>No. Polisi</span><b>${escapeHtml(load.polisi || '-')}</b>
        <span>Referensi</span><b>${escapeHtml(load.ref || '-')}</b>
        <span>Kondisi</span><b>${escapeHtml(load.kondisi || 'BAIK')}</b>
      </div>
      <div class="sep"></div>
      <b>BARANG</b>${rows}
      <div class="sep"></div>
      <div class="line totals"><span>Total Jenis</span><span>${escapeHtml((load.items || []).length)}</span></div>
      <div class="line totals"><span>Total Unit</span><span>${escapeHtml(formatNum(load.total_unit || 0))}</span></div>
      <div class="line totals"><span>Total Berat</span><span>${escapeHtml(formatNum(load.total_berat || 0))} kg</span></div>
      <div class="sep"></div>
      <div class="small">Petugas: ${escapeHtml(load.started_by || load.created_by || '-')}</div>
      ${load.keterangan ? `<div class="small">Ket: ${escapeHtml(load.keterangan)}</div>` : ''}
      <div class="warning">BON MUAT — BUKAN SURAT JALAN</div>
    </body></html>`);
    w.document.close();
    w.focus();
    setTimeout(() => w.print(), 250);
  };

  const printSuratJalan = (sj) => {
    if (!sj) {
      toast.error('Surat Jalan belum tersedia');
      return;
    }
    const rows = (sj.items || []).map((item, index) => `<tr><td>${index + 1}</td><td>${escapeHtml(item.name)}</td><td class="right">${escapeHtml(formatNum(item.qty))}</td><td>${escapeHtml(item.unit || '')}</td><td class="right">${escapeHtml(formatNum(item.berat || 0))}</td></tr>`).join('');
    const w = window.open('', '_blank', 'width=1000,height=760');
    if (!w) {
      toast.error('Popup diblokir browser. Izinkan popup untuk mencetak Surat Jalan.');
      return;
    }
    w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(sj.no)}</title><style>
      @page { size: A4; margin: 14mm; } * { box-sizing: border-box; } body { font-family: Arial, sans-serif; color:#111; margin:0; }
      .header { display:flex; justify-content:space-between; border-bottom:2px solid #111; padding-bottom:10px; margin-bottom:14px; }
      .company { font-size:20px; font-weight:800; } .warehouse { font-size:11px; margin-top:3px; } .title { font-size:24px; font-weight:800; }
      .meta { display:grid; grid-template-columns:1fr 1fr; gap:7px 24px; margin-bottom:16px; } .meta div { display:grid; grid-template-columns:115px 1fr; font-size:12px; } .meta span { color:#555; }
      table { width:100%; border-collapse:collapse; font-size:12px; } th,td { border:1px solid #333; padding:7px; } th { background:#f0f0f0; text-align:left; } .right{text-align:right;}
      .signatures { display:grid; grid-template-columns:1fr 1fr; gap:80px; margin-top:36px; text-align:center; font-size:12px; } .space { height:70px; }
    </style></head><body>
      <div class="header"><div><div class="company">PERUM BULOG</div><div class="warehouse">Gudang Sunter Timur I & II</div></div><div class="title">SURAT JALAN</div></div>
      <div class="meta"><div><span>No. Surat Jalan</span><b>${escapeHtml(sj.no)}</b></div><div><span>Antrian</span><b>${escapeHtml(sj.antrian || '-')}</b></div><div><span>Waktu Terbit</span><b>${escapeHtml(formatDate(sj.time))}</b></div><div><span>Penerima</span><b>${escapeHtml(sj.penerima || '-')}</b></div><div><span>No. Polisi</span><b>${escapeHtml(sj.polisi || '-')}</b></div><div><span>Referensi</span><b>${escapeHtml(sj.ref || '-')}</b></div></div>
      <table><thead><tr><th>No</th><th>Nama Barang</th><th>Jumlah</th><th>Satuan</th><th>Berat (kg)</th></tr></thead><tbody>${rows}</tbody><tfoot><tr><td colspan="2"><b>Total</b></td><td class="right"><b>${escapeHtml(formatNum(sj.unit || 0))}</b></td><td></td><td class="right"><b>${escapeHtml(formatNum(sj.berat || 0))}</b></td></tr></tfoot></table>
      <div class="signatures"><div><p>Petugas Gudang</p><div class="space"></div><b>${escapeHtml(sj.operator || '')}</b></div><div><p>Penerima</p><div class="space"></div><b>${escapeHtml(sj.penerima || '')}</b></div></div>
    </body></html>`);
    w.document.close();
    w.focus();
    setTimeout(() => w.print(), 250);
  };

  const startAndPrint = async (load) => {
    if (busyId) return;
    setBusyId(load.id);
    try {
      const updated = await startOutboundLoad(load.id);
      printBonMuat(updated);
      toast.success(`Pemuatan ${updated.antrian} dimulai · Bon Muat siap dicetak`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Gagal memulai pemuatan');
    } finally {
      setBusyId('');
    }
  };

  const finishLoading = async (load) => {
    if (busyId) return;
    if (!window.confirm(`Selesaikan pemuatan ${load.antrian}? Setelah ini stok akan dikurangi dan Surat Jalan diterbitkan.`)) return;
    setBusyId(load.id);
    try {
      const result = await completeOutboundLoad(load.id);
      toast.success(`Pemuatan selesai · Surat Jalan ${result?.suratJalan?.no || ''} diterbitkan`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Gagal menyelesaikan pemuatan');
    } finally {
      setBusyId('');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Pengiriman Barang</div>
          <h1 className="font-display text-4xl font-bold">Proses Pengeluaran</h1>
          <p className="text-[#8b93a1] mt-2">Bon Muat digunakan saat proses loading. Surat Jalan baru terbit setelah pemuatan selesai.</p>
        </div>
        <button onClick={() => navigate('/antrian')} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24]"><MonitorSmartphone size={15} /> Layar Antrian</button>
      </div>

      <div className="card-surface p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <select value={filter} onChange={(e) => setFilter(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none"><option>Semua Status</option><option>Menunggu</option><option>Sedang Dimuat</option><option>Selesai</option></select>
          <div className="text-xs text-[#6b7688]">Nomor antrian A-001, A-002, ... otomatis reset setiap hari.</div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['Antrian', 'Waktu', 'Tujuan', 'No. Polisi', 'Referensi', 'Barang', 'Total Berat', 'Status', 'Surat Jalan', 'Aksi'].map((h) => <th key={h} className="py-2.5 pr-4 font-semibold whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {list.length === 0 ? <tr><td colSpan={10} className="py-8 text-center text-[#6b7688]">Belum ada antrian pengeluaran.</td></tr> : list.map((load) => {
                const sj = findFinalSJ(load);
                const st = STATUS[load.status] || STATUS.Menunggu;
                return (
                  <tr key={load.id} className="tbl-row border-b border-[#131a24] align-top">
                    <td className="py-3 pr-4 font-display text-xl font-bold text-[#60a5fa] whitespace-nowrap">{load.antrian}</td>
                    <td className="py-3 pr-4 whitespace-nowrap text-[#8b93a1]">{formatDate(load.started_at || load.created_at)}</td>
                    <td className="py-3 pr-4 text-[#c7d0dc]">{load.party}</td>
                    <td className="py-3 pr-4 font-mono text-xs whitespace-nowrap">{load.polisi || '—'}</td>
                    <td className="py-3 pr-4 font-mono text-xs">{load.ref || '—'}</td>
                    <td className="py-3 pr-4 text-xs min-w-[260px]">{(load.items || []).map((item, i) => <div key={i} className="text-[#aab4c4]">{item.name} · {formatNum(item.qty)} {item.unit} <span className="text-[#6b7688]">({formatNum(item.berat || 0)} kg)</span></div>)}</td>
                    <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(load.total_berat || 0)} kg</td>
                    <td className="py-3 pr-4"><span className="text-xs px-2.5 py-1 rounded-full font-medium whitespace-nowrap" style={{ background: st.bg, color: st.c }}>{load.status}</span></td>
                    <td className="py-3 pr-4 font-mono text-xs whitespace-nowrap">{load.surat_jalan_no || 'Belum terbit'}</td>
                    <td className="py-3 pr-4"><div className="flex flex-wrap gap-2 min-w-[260px]">
                      {load.status === 'Menunggu' && <button disabled={busyId === load.id} onClick={() => startAndPrint(load)} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#2563eb] text-[#60a5fa] hover:bg-[#2563eb]/10 disabled:opacity-50"><Play size={13} /> Mulai Muat & Cetak Bon</button>}
                      {load.status === 'Sedang Dimuat' && <><button onClick={() => printBonMuat(load)} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#242f3d] hover:bg-[#141a24]"><Printer size={13} /> Cetak Ulang Bon</button><button disabled={busyId === load.id} onClick={() => finishLoading(load)} className="btn-primary inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg disabled:opacity-50"><CheckCircle2 size={13} /> Selesai Muat</button></>}
                      {load.status === 'Selesai' && <button onClick={() => printSuratJalan(sj)} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#22c55e] text-[#4ade80] hover:bg-[#22c55e]/10"><Printer size={13} /> Cetak Surat Jalan</button>}
                    </div></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default Pengeluaran;
