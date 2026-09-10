import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Printer, Plus, MonitorSmartphone } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatNum, formatDate } from '../mock';
import { toast } from 'sonner';

const STATUS = { 'Menunggu': { c: '#eab308', bg: 'rgba(234,179,8,.15)' }, 'Sedang Dimuat': { c: '#3b82f6', bg: 'rgba(59,130,246,.15)' }, 'Selesai': { c: '#22c55e', bg: 'rgba(34,197,94,.15)' } };

const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[ch]));

const openPrintWindow = (html, width = 420, height = 760) => {
  const w = window.open('', '_blank', `width=${width},height=${height}`);
  if (!w) { toast.error('Popup cetak diblokir browser'); return; }
  w.document.open();
  w.document.write(html);
  w.document.close();
  setTimeout(() => { w.focus(); w.print(); }, 350);
};

const printBonMuat = (sj) => {
  const items = (sj.items || []).map((it) => `<div class="item"><b>${esc(it.name)}</b><br>${esc(formatNum(it.qty))} ${esc(it.unit)} · ${esc(formatNum(it.berat))} Kg</div>`).join('');
  const dt = new Date(sj.loading_started_at || sj.time || Date.now()).toLocaleString('id-ID', { timeZone: 'Asia/Jakarta' });
  openPrintWindow(`<!doctype html><html><head><title>Bon Muat ${esc(sj.bon_no || '')}</title><style>
    @page{size:80mm auto;margin:3mm}*{box-sizing:border-box}body{width:74mm;margin:0 auto;font-family:Arial,sans-serif;color:#000;font-size:10px;line-height:1.3}.logo{text-align:center;margin-bottom:4px}.logo img{width:48mm;max-height:24mm;object-fit:contain}.title{text-align:center;font-weight:800;font-size:13px;margin:3px 0 7px;border-top:1px solid #000;border-bottom:1px solid #000;padding:5px 0}.label{font-size:8px;text-transform:uppercase;margin-top:5px}.value{font-size:12px;font-weight:700;word-break:break-word}.queue{text-align:center;font-size:27px;font-weight:900;letter-spacing:1px;margin:2px 0 6px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:4px 7px}.item{border-top:1px dashed #555;padding:4px 0}.foot{text-align:center;border-top:1px solid #000;margin-top:8px;padding-top:6px;font-size:9px}.muted{font-size:9px}</style></head><body>
    <div class="logo"><img src="${window.location.origin}/bulog-sunter.png" alt="BULOG"></div>
    <div class="title">BON MUAT GBB SUNTER TIMUR I</div>
    <div class="label">Nomor Bon Muat</div><div class="value">${esc(sj.bon_no || '-')}</div>
    <div class="label" style="text-align:center">Nomor Antrian</div><div class="queue">${esc(sj.antrian || '-')}</div>
    <div class="grid"><div><div class="label">Tanggal Cetak</div><div class="value" style="font-size:10px">${esc(dt)}</div></div><div><div class="label">Pemuatan</div><div class="value">${esc(sj.unit_loading || '-')}</div></div></div>
    <div class="label">Nama Barang</div>${items || '<div class="value">-</div>'}
    <div class="grid"><div><div class="label">Colly</div><div class="value">${esc(formatNum(sj.unit || 0))}</div></div><div><div class="label">Tonase</div><div class="value">${esc(formatNum(sj.berat || 0))} Kg</div></div></div>
    <div class="label">Nomor SO</div><div class="value">${esc(sj.ref || '-')}</div>
    <div class="label">Tujuan / A.N</div><div class="value">${esc(sj.penerima || '-')}</div>
    <div class="grid"><div><div class="label">No. Plat</div><div class="value">${esc(sj.polisi || '-')}</div></div><div><div class="label">Pengambil</div><div class="value">${esc(sj.pengambil || '-')}</div></div></div>
    <div class="foot"><b>Serahkan bon ini ke petugas pemuatan</b><br>Terima Kasih - GBB Sunter Timur I</div>
  </body></html>`);
};

const printSuratJalan = (sj) => {
  if (!sj.no) { toast.error('Surat Jalan belum diterbitkan'); return; }
  const rows = (sj.items || []).map((it, i) => `<tr><td>${i + 1}</td><td>${esc(it.name)}</td><td>${esc(formatNum(it.qty))}</td><td>${esc(it.unit)}</td><td>${esc(formatNum(it.berat))} Kg</td></tr>`).join('');
  const dt = new Date(sj.completed_at || sj.time || Date.now()).toLocaleString('id-ID', { timeZone: 'Asia/Jakarta' });
  openPrintWindow(`<!doctype html><html><head><title>${esc(sj.no)}</title><style>@page{size:A4;margin:16mm}body{font-family:Arial,sans-serif;color:#111;font-size:12px}.head{display:flex;align-items:center;justify-content:space-between;border-bottom:2px solid #1d4f91;padding-bottom:10px}.head img{width:180px}.title{text-align:right}.title h1{margin:0;font-size:22px}.meta{margin:18px 0;display:grid;grid-template-columns:1fr 1fr;gap:8px 30px}.meta b{display:inline-block;min-width:110px}table{width:100%;border-collapse:collapse;margin-top:10px}th,td{border:1px solid #777;padding:7px;text-align:left}th{background:#eee}.sign{display:grid;grid-template-columns:1fr 1fr;margin-top:55px;text-align:center;gap:80px}.line{margin-top:55px;border-top:1px solid #222;padding-top:5px}</style></head><body>
  <div class="head"><img src="${window.location.origin}/bulog-sunter.png"><div class="title"><h1>SURAT JALAN</h1><div>${esc(sj.no)}</div></div></div>
  <div class="meta"><div><b>Tanggal</b>${esc(dt)}</div><div><b>No. Bon Muat</b>${esc(sj.bon_no || '-')}</div><div><b>Tujuan / A.N</b>${esc(sj.penerima || '-')}</div><div><b>Nomor SO</b>${esc(sj.ref || '-')}</div><div><b>No. Plat</b>${esc(sj.polisi || '-')}</div><div><b>Pengambil</b>${esc(sj.pengambil || '-')}</div></div>
  <table><thead><tr><th>No</th><th>Nama Barang</th><th>Jumlah</th><th>Satuan</th><th>Berat</th></tr></thead><tbody>${rows}</tbody></table>
  <div class="sign"><div>Petugas Gudang<div class="line">${esc(sj.operator || '')}</div></div><div>Penerima / Pengambil<div class="line">${esc(sj.pengambil || sj.penerima || '')}</div></div></div>
  </body></html>`, 900, 800);
};

const Pengeluaran = () => {
  const { suratJalan, updateSJStatus, canWrite } = useData();
  const navigate = useNavigate();
  const [filter, setFilter] = useState('Semua Status');
  const [busy, setBusy] = useState('');

  const list = suratJalan.filter((sj) => filter === 'Semua Status' || sj.status === filter);

  const mulaiMuat = async (sj) => {
    try {
      setBusy(sj.id);
      const updated = await updateSJStatus(sj.id, 'Sedang Dimuat');
      toast.success('Pemuatan dimulai. Bon Muat siap dicetak.');
      printBonMuat(updated || sj);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Gagal memulai pemuatan');
    } finally { setBusy(''); }
  };

  const selesaiMuat = async (sj) => {
    try {
      setBusy(sj.id);
      const updated = await updateSJStatus(sj.id, 'Selesai');
      toast.success(`Pemuatan selesai. Stok dikurangi dan Surat Jalan ${updated?.no || ''} diterbitkan.`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Gagal menyelesaikan pemuatan');
    } finally { setBusy(''); }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Pengiriman Barang</div>
          <h1 className="font-display text-4xl font-bold">Antrian Pemuatan &amp; Surat Jalan</h1>
          <p className="text-[#8b93a1] mt-2">Bon Muat dicetak saat Mulai Muat. Stok dan Surat Jalan diproses saat Selesai Muat.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => navigate('/antrian')} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24]"><MonitorSmartphone size={15} /> Layar Antrian</button>
          {canWrite && <button onClick={() => navigate('/catat')} className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg"><Plus size={15} /> Pengeluaran Baru</button>}
        </div>
      </div>

      <div className="card-surface p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <select data-testid="sj-status-filter" value={filter} onChange={(e) => setFilter(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none"><option>Semua Status</option><option>Menunggu</option><option>Sedang Dimuat</option><option>Selesai</option></select>
          <div className="text-xs text-[#8b93a1]">Antrian aktif: {suratJalan.filter((sj) => sj.status !== 'Selesai').length}</div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['Dokumen', 'Antrian', 'Waktu', 'Tujuan / A.N', 'Barang', 'Total Berat', 'Status', 'Aksi'].map((h) => <th key={h} className="py-2.5 pr-4 font-semibold whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {list.length === 0 ? <tr><td colSpan={8} className="py-8 text-center text-[#6b7688]">Belum ada antrian pengeluaran.</td></tr> : list.map((sj) => (
                <tr key={sj.id} className="tbl-row border-b border-[#131a24] align-top">
                  <td className="py-3 pr-4"><div className="font-mono text-xs">{sj.no || 'SJ belum terbit'}</div><div className="text-[10px] text-[#6b7688] mt-1">Bon: {sj.bon_no || '-'}</div></td>
                  <td className="py-3 pr-4 font-mono text-xs font-bold">{sj.antrian}</td>
                  <td className="py-3 pr-4 whitespace-nowrap text-[#8b93a1]">{formatDate(sj.time)}</td>
                  <td className="py-3 pr-4 text-[#c7d0dc]"><div>{sj.penerima}</div><div className="text-[10px] text-[#6b7688]">{sj.polisi || '-'} · {sj.pengambil || '-'}</div></td>
                  <td className="py-3 pr-4 text-xs max-w-xs">{sj.items.map((it, i) => <div key={i} className="text-[#aab4c4]">{it.name} <span className="text-[#6b7688]">({formatNum(it.qty)} {it.unit})</span></div>)}</td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(sj.berat)} kg</td>
                  <td className="py-3 pr-4"><span className="text-xs px-2.5 py-1 rounded-full font-medium whitespace-nowrap" style={{ background: STATUS[sj.status]?.bg, color: STATUS[sj.status]?.c }}>{sj.status}</span></td>
                  <td className="py-3 pr-4"><div className="flex flex-wrap gap-2">
                    {sj.status === 'Menunggu' && canWrite && <button disabled={busy === sj.id} onClick={() => mulaiMuat(sj)} className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-[#2563eb] text-[#60a5fa] hover:bg-[#2563eb]/10 whitespace-nowrap">Mulai Muat &amp; Cetak Bon</button>}
                    {sj.status === 'Sedang Dimuat' && <button onClick={() => printBonMuat(sj)} className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24] whitespace-nowrap"><Printer size={12} className="inline mr-1" />Bon Muat</button>}
                    {sj.status === 'Sedang Dimuat' && canWrite && <button disabled={busy === sj.id} onClick={() => selesaiMuat(sj)} className="btn-primary text-xs font-semibold px-3 py-1.5 rounded-lg whitespace-nowrap">Selesai Muat</button>}
                    {sj.status === 'Selesai' && <button onClick={() => printSuratJalan(sj)} className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-[#22c55e] text-[#4ade80] hover:bg-[#22c55e]/10 whitespace-nowrap"><Printer size={12} className="inline mr-1" />Cetak Surat Jalan</button>}
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default Pengeluaran;
