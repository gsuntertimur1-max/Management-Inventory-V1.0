import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Printer, MonitorSmartphone, Play, CheckCircle2, RotateCcw, Link2, Search } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatNum, formatDate } from '../mock';
import { toast } from 'sonner';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { apiError, downloadApiFile } from '../lib/api';

const STACKS = [...Array.from({ length: 8 }, (_, i) => String(i + 17)).flatMap((unit) => ['A', 'B', 'C'].flatMap((zone) => Array.from({ length: 4 }, (_, i) => `${unit}/${zone}${String(i + 1).padStart(2, '0')}`))), ...['A', 'B'].flatMap((zone) => Array.from({ length: 8 }, (_, i) => `MP1/${zone}${String(i + 1).padStart(2, '0')}`))];

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

const printDateWib = (value) => {
  try {
    return new Intl.DateTimeFormat('id-ID', {
      timeZone: 'Asia/Jakarta',
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: false,
    }).format(new Date(value || Date.now())).replace(',', '');
  } catch (_) {
    return String(value || '');
  }
};

const Pengeluaran = () => {
  const { outboundLoads, suratJalan, startOutboundLoad, completeOutboundLoad, createConsignmentReturn, settleOutboundDocument } = useData();
  const navigate = useNavigate();
  const [filter, setFilter] = useState('Semua Status');
  const [query, setQuery] = useState('');
  const [busyId, setBusyId] = useState('');
  const [documentModal, setDocumentModal] = useState(null);

  const list = outboundLoads.filter((load) => {
    const needle = query.trim().toLowerCase();
    const searchable = [load.ref, ...(load.documents || []), load.document_type, load.party, ...(load.document_links || []).flatMap((link) => [link.no, link.type]), ...(load.items || []).flatMap((item) => [item.name, item.sku, item.documentNo])].filter(Boolean).join(' ').toLowerCase();
    return (filter === 'Semua Status' || load.status === filter) && (!needle || searchable.includes(needle));
  });
  const findFinalSJ = (load) => suratJalan.find((sj) => sj.id === load.surat_jalan_id || sj.load_id === load.id);
  const downloadBon = (load) => downloadApiFile(`/export/bon-muat/${load.id}.pdf`, `bon_pemuatan_${load.bon_no || load.id}.pdf`).catch((e) => toast.error(apiError(e)));
  const downloadSuratJalan = (sj) => sj ? downloadApiFile(`/export/surat-jalan/${sj.id}.pdf`, `surat_jalan_${(sj.ref || sj.no || sj.id).replaceAll('/', '-')}.pdf`).catch((e) => toast.error(apiError(e))) : toast.error('Surat Jalan belum tersedia');
  const downloadWeighingForm = (load) => downloadApiFile(`/export/weighing-form/outbound/${load.id}.pdf`, `form_timbangan_keluar_${load.antrian || load.id}.pdf`).catch((e) => toast.error(apiError(e)));
  const remainingQty = (load, source) => {
    let used = 0;
    (load.document_links || []).forEach((link) => (link.items || []).forEach((item) => {
      if (item.productId !== source.productId) return;
      used += ['CR', 'RETUR'].includes(link.type) ? Number(item.goodQty || 0) + Number(item.damagedQty || 0) : Number(item.qty || 0);
    }));
    return Math.max(Number(source.qty || 0) - used, 0);
  };
  const consignmentSummary = Object.values(outboundLoads.filter((load) => ['MEMO', 'ND'].includes(load.document_type) && load.consignment_destination && load.status === 'Selesai').reduce((result, load) => {
    (load.items || []).forEach((item) => {
      const qty = remainingQty(load, item);
      if (qty <= 0) return;
      const key = `${load.consignment_destination}|${load.consignment_zone || 'Unit 18'}|${item.productId}`;
      result[key] = result[key] || { destination: load.consignment_destination, zone: load.consignment_zone || 'Unit 18', name: item.name, unit: item.unit, qty: 0 };
      result[key].qty += qty;
    });
    return result;
  }, {}));
  const isReturnMode = (mode) => ['CR', 'RETUR'].includes(mode);
  const openLinkedDocument = (load, mode) => setDocumentModal({ load, mode, documentNo: '', note: '', items: (load.items || []).map((item) => isReturnMode(mode) ? { productId: item.productId, name: item.name, unit: item.unit, goodQty: 0, stackCode: item.location || '', placements: [{ goodQty: 0, stackCode: item.location || '' }], damagedQty: 0, remaining: remainingQty(load, item) } : { productId: item.productId, name: item.name, unit: item.unit, qty: remainingQty(load, item), remaining: remainingQty(load, item) }) });
  const updateDocumentItem = (index, patch) => setDocumentModal((prev) => ({ ...prev, items: prev.items.map((item, i) => i === index ? { ...item, ...patch } : item) }));
  const updateReturnPlacement = (itemIndex, placementIndex, patch) => updateDocumentItem(itemIndex, { placements: documentModal.items[itemIndex].placements.map((placement, index) => index === placementIndex ? { ...placement, ...patch } : placement) });
  const saveLinkedDocument = async () => {
    if (!documentModal?.documentNo.trim()) return toast.error(`Isi nomor dokumen ${documentModal?.mode}`);
    setBusyId(documentModal.load.id);
    try {
      const payload = { documentNo: documentModal.documentNo, note: documentModal.note, returnType: documentModal.mode, items: documentModal.items.map((item) => isReturnMode(documentModal.mode) ? { productId: item.productId, goodQty: Number(item.goodQty || 0), damagedQty: Number(item.damagedQty || 0), stackCode: item.stackCode || '', placements: (item.placements || []).map((placement) => ({ goodQty: Number(placement.goodQty || 0), stackCode: placement.stackCode || '' })).filter((placement) => placement.goodQty > 0) } : { productId: item.productId, qty: Number(item.qty || 0) }).filter((item) => isReturnMode(documentModal.mode) ? item.placements.reduce((total, placement) => total + placement.goodQty, 0) + item.goodQty + item.damagedQty > 0 : item.qty > 0) };
      if (isReturnMode(documentModal.mode)) await createConsignmentReturn(documentModal.load.id, payload); else await settleOutboundDocument(documentModal.load.id, payload);
      toast.success(`Dokumen ${documentModal.mode} berhasil ditautkan`); setDocumentModal(null);
    } catch (e) { toast.error(e?.response?.data?.detail || 'Gagal menyimpan dokumen'); } finally { setBusyId(''); }
  };

  const writeBonMuat = (load, targetWindow) => {
    const w = targetWindow || window.open('', '_blank', 'width=420,height=760');
    if (!w) {
      toast.error('Popup diblokir browser. Izinkan popup untuk mencetak Bon Muat.');
      return false;
    }

    const logoUrl = `${window.location.origin}/bulog-sunter.png`;
    const itemNames = (load.items || []).map((item) => `<div class="product-name">${escapeHtml(item.name)}</div>`).join('');
    const colly = (load.items || []).map((item) => `${escapeHtml(formatNum(item.qty))} ${escapeHtml(item.unit || '')}`).join(' + ') || '-';

    w.document.open();
    w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>Bon Muat ${escapeHtml(load.antrian || '')}</title><style>
      @page { size: 80mm auto; margin: 2.5mm 3mm 3mm; }
      * { box-sizing: border-box; }
      html, body { margin: 0; padding: 0; }
      body { width: 74mm; margin: 0 auto; color: #000; background:#fff; font-family: Arial, Helvetica, sans-serif; font-size: 10.5px; line-height: 1.25; }
      .logo { width: 46mm; max-height: 18mm; object-fit: contain; display:block; margin:0 auto 1.5mm; }
      .center { text-align:center; }
      .title { font-size: 14px; font-weight: 900; margin: 1mm 0 3mm; }
      .label { font-size: 9px; font-weight: 700; text-transform: uppercase; }
      .bon-no { font-size: 12px; font-weight: 900; margin: .7mm 0 2.5mm; overflow-wrap:anywhere; }
      .queue { font-size: 31px; line-height: 1; font-weight: 900; letter-spacing: 1px; margin: 1mm 0 3mm; }
      .rule { border-top: 1px dashed #000; margin: 2.5mm 0; }
      .field { margin: 1.6mm 0; }
      .field-name { font-size: 9px; font-weight: 700; margin-bottom: .4mm; }
      .field-value { font-size: 10.5px; font-weight: 700; overflow-wrap:anywhere; }
      .product-name { font-size: 11px; font-weight: 900; margin: .7mm 0; }
      .grid { display:grid; grid-template-columns: 18mm 1fr; gap:1.2mm; align-items:start; margin:1mm 0; }
      .grid .k { font-size:9px; }
      .grid .v { font-size:10px; font-weight:700; overflow-wrap:anywhere; }
      .footer { text-align:center; margin-top:3mm; font-size:9.5px; }
      .footer strong { display:block; margin-bottom:1mm; }
    </style></head><body>
      <img class="logo" src="${escapeHtml(logoUrl)}" alt="BULOG" />
      <div class="center title">BON MUAT GBB SUNTER TIMUR I</div>

      <div class="center label">NOMOR BON MUAT</div>
      <div class="center bon-no">${escapeHtml(load.bon_no || '-')}</div>
      <div class="center label">NOMOR ANTRIAN</div>
      <div class="center queue">${escapeHtml(load.antrian || '-')}</div>

      <div class="rule"></div>
      <div class="field"><div class="field-name">Tanggal Cetak:</div><div class="field-value">${escapeHtml(printDateWib(Date.now()))}</div></div>
      <div class="field"><div class="field-name">Nama Barang:</div>${itemNames || '<div class="field-value">-</div>'}</div>

      <div class="grid"><div class="k">Colly:</div><div class="v">${colly}</div></div>
      <div class="grid"><div class="k">Tonase:</div><div class="v">${escapeHtml(formatNum(load.total_berat || 0))} Kg</div></div>
      <div class="grid"><div class="k">Pemuatan:</div><div class="v">${escapeHtml(load.unit_loading || '-')}</div></div>

      <div class="rule"></div>
      <div class="grid"><div class="k">Dokumen ${escapeHtml(load.document_type || 'SO')}:</div><div class="v">${escapeHtml(load.ref || '-')}</div></div>
      <div class="field"><div class="field-name">Tujuan / A.N:</div><div class="field-value">${escapeHtml(load.party || '-')}</div></div>
      <div class="grid"><div class="k">No. Plat:</div><div class="v">${escapeHtml(load.polisi || '-')}</div></div>
      <div class="grid"><div class="k">Pengambil:</div><div class="v">${escapeHtml(load.pengambil || '-')}</div></div>

      <div class="rule"></div>
      <div class="footer"><strong>Serahkan bon ini ke petugas pemuatan</strong>Terima Kasih - GBB Sunter Timur I</div>
    </body></html>`);
    w.document.close();
    w.focus();
    setTimeout(() => { try { w.print(); } catch (_) {} }, 450);
    return true;
  };

  const printSuratJalanPreview = (sj) => {
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
    const logoUrl = `${window.location.origin}/bulog-sunter.png`;
    w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(sj.no)}</title><style>
      @page { size: A4; margin: 14mm; } * { box-sizing: border-box; } body { font-family: Arial, sans-serif; color:#111; margin:0; }
      .header { display:flex; justify-content:space-between; align-items:center; border-bottom:2px solid #111; padding-bottom:10px; margin-bottom:14px; }
      .brand { display:flex; align-items:center; gap:12px; } .brand img { width:115px; max-height:58px; object-fit:contain; }
      .warehouse { font-size:11px; margin-top:3px; } .title { font-size:24px; font-weight:800; }
      .meta { display:grid; grid-template-columns:1fr 1fr; gap:7px 24px; margin-bottom:16px; } .meta div { display:grid; grid-template-columns:115px 1fr; font-size:12px; } .meta span { color:#555; }
      table { width:100%; border-collapse:collapse; font-size:12px; } th,td { border:1px solid #333; padding:7px; } th { background:#f0f0f0; text-align:left; } .right{text-align:right;}
      .signatures { display:grid; grid-template-columns:1fr 1fr; gap:80px; margin-top:36px; text-align:center; font-size:12px; } .space { height:70px; }
    </style></head><body>
      <div class="header"><div class="brand"><img src="${escapeHtml(logoUrl)}" alt="BULOG"/><div><b>PERUM BULOG</b><div class="warehouse">Gudang Sunter Timur I & II</div></div></div><div class="title">SURAT JALAN</div></div>
      <div class="meta"><div><span>No. Surat Jalan</span><b>${escapeHtml(sj.no)}</b></div><div><span>Antrian</span><b>${escapeHtml(sj.antrian || '-')}</b></div><div><span>Waktu Terbit</span><b>${escapeHtml(formatDate(sj.time))}</b></div><div><span>Penerima</span><b>${escapeHtml(sj.penerima || '-')}</b></div><div><span>No. Polisi</span><b>${escapeHtml(sj.polisi || '-')}</b></div><div><span>Pengambil</span><b>${escapeHtml(sj.pengambil || '-')}</b></div><div><span>Referensi</span><b>${escapeHtml(sj.ref || '-')}</b></div><div><span>Bon Muat</span><b>${escapeHtml(sj.bon_no || '-')}</b></div></div>
      <table><thead><tr><th>No</th><th>Nama Barang</th><th>Jumlah</th><th>Satuan</th><th>Berat (kg)</th></tr></thead><tbody>${rows}</tbody><tfoot><tr><td colspan="2"><b>Total</b></td><td class="right"><b>${escapeHtml(formatNum(sj.unit || 0))}</b></td><td></td><td class="right"><b>${escapeHtml(formatNum(sj.berat || 0))}</b></td></tr></tfoot></table>
      <div class="signatures"><div><p>Petugas Gudang</p><div class="space"></div><b>${escapeHtml(sj.operator || '')}</b></div><div><p>Penerima</p><div class="space"></div><b>${escapeHtml(sj.penerima || '')}</b></div></div>
    </body></html>`);
    w.document.close();
    w.focus();
    setTimeout(() => w.print(), 450);
  };

  const startAndPrint = async (load) => {
    if (busyId) return;
    setBusyId(load.id);
    try {
      const updated = await startOutboundLoad(load.id);
      await downloadApiFile(`/export/bon-muat/${updated.id}.pdf`, `bon_pemuatan_${updated.bon_no || updated.id}.pdf`);
      toast.success(`Pemuatan ${updated.antrian} dimulai · Bon Pemuatan PDF diunduh`);
    } catch (e) {
      toast.error(apiError(e) || 'Gagal memulai pemuatan');
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
          <p className="text-[#8b93a1] mt-2">Bon Muat diterbitkan untuk proses loading. Stok dan Surat Jalan baru diproses setelah pemuatan selesai.</p>
        </div>
        <button onClick={() => navigate('/antrian')} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24]"><MonitorSmartphone size={15} /> Layar Antrian</button>
      </div>

      {consignmentSummary.length > 0 && <div className="card-surface p-5 border border-[#1f3657]">
        <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3"><div><div className="label-mono text-[10px] text-[#93c5fd]">Persediaan di luar stok gudang utama</div><h2 className="font-display text-lg font-bold mt-1">Stok Konsinyasi Unit 18</h2></div><p className="text-xs text-[#6b7688]">Berasal dari Memo/ND dan berubah saat SO atau Retur ditautkan.</p></div>
        <div className="overflow-x-auto"><table className="w-full text-xs tbl"><thead><tr className="text-left border-b border-[#1a222e]"><th className="py-2 pr-4">Tujuan</th><th className="py-2 pr-4">Zona</th><th className="py-2 pr-4">Komoditas</th><th className="py-2 text-right">Sisa Konsinyasi</th></tr></thead><tbody>{consignmentSummary.map((item) => <tr key={`${item.destination}-${item.zone}-${item.name}`} className="border-b border-[#131a24]"><td className="py-2.5 pr-4">{item.destination}</td><td className="py-2.5 pr-4 font-mono text-[#93c5fd]">{item.zone}</td><td className="py-2.5 pr-4">{item.name}</td><td className="py-2.5 text-right font-mono font-semibold">{formatNum(item.qty)} {item.unit}</td></tr>)}</tbody></table></div>
      </div>}

      <div className="card-surface p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="relative min-w-[280px] flex-1"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari SO / CT / TM / Memo / produk..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
          <select value={filter} onChange={(e) => setFilter(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none"><option>Semua Status</option><option>Menunggu</option><option>Sedang Dimuat</option><option>Selesai</option></select>
          <div className="text-xs text-[#6b7688]">Nomor antrean mengikuti unit pemuatan, misalnya 17-001, dan reset setiap hari.</div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['Antrian', 'Bon Muat', 'Waktu', 'Tujuan', 'Pengambil', 'No. Polisi', 'Barang', 'Pemuatan', 'Status', 'Dokumen & Rangkaian', 'Aksi'].map((h) => <th key={h} className="py-2.5 pr-4 font-semibold whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {list.length === 0 ? <tr><td colSpan={11} className="py-8 text-center text-[#6b7688]">Belum ada antrian pengeluaran.</td></tr> : list.map((load) => {
                const sj = findFinalSJ(load);
                const st = STATUS[load.status] || STATUS.Menunggu;
                return (
                  <tr key={load.id} className="tbl-row border-b border-[#131a24] align-top">
                    <td className="py-3 pr-4 font-display text-xl font-bold text-[#60a5fa] whitespace-nowrap">{load.antrian}</td>
                    <td className="py-3 pr-4 font-mono text-xs whitespace-nowrap">{load.bon_no || '—'}</td>
                    <td className="py-3 pr-4 whitespace-nowrap text-[#8b93a1]">{formatDate(load.started_at || load.created_at)}</td>
                    <td className="py-3 pr-4 text-[#c7d0dc] min-w-[180px]"><div>{load.party}</div>{load.consignment_destination && <div className="text-[10px] text-[#93c5fd] mt-1">{load.consignment_destination} · {load.consignment_zone || 'Unit 18'}</div>}</td>
                    <td className="py-3 pr-4 whitespace-nowrap">{load.pengambil || '—'}</td>
                    <td className="py-3 pr-4 font-mono text-xs whitespace-nowrap">{load.polisi || '—'}</td>
                    <td className="py-3 pr-4 text-xs min-w-[250px]">{(load.items || []).map((item, i) => <div key={i} className="text-[#aab4c4]">{item.name} · {formatNum(item.qty)} {item.unit} <span className="text-[#6b7688]">({formatNum(item.berat || 0)} kg)</span></div>)}</td>
                    <td className="py-3 pr-4 whitespace-nowrap">{load.unit_loading || '—'}</td>
                    <td className="py-3 pr-4"><span className="text-xs px-2.5 py-1 rounded-full font-medium whitespace-nowrap" style={{ background: st.bg, color: st.c }}>{load.status}</span></td>
                    <td className="py-3 pr-4 text-xs min-w-[220px]"><div className="font-mono font-semibold text-[#93c5fd]">{load.document_type || 'SO'} · {load.ref || '—'}</div>{load.request_document && <div className="font-mono mt-1 text-[#fbbf24]">↳ Dasar: {load.request_document}</div>}{(load.document_links || []).map((link) => <div key={link.id} className="font-mono mt-1 text-[#4ade80]">↳ {link.type} · {link.no}</div>)}<div className="mt-1 text-[#6b7688]">{load.document_status || (load.status === 'Selesai' ? 'Selesai' : 'Menunggu pemuatan')} · SJ {load.surat_jalan_no || 'belum terbit'}</div></td>
                    <td className="py-3 pr-4"><div className="flex flex-wrap gap-2 min-w-[270px]">
                      {load.status === 'Menunggu' && <button disabled={busyId === load.id} onClick={() => startAndPrint(load)} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#2563eb] text-[#60a5fa] hover:bg-[#2563eb]/10 disabled:opacity-50"><Play size={13} /> Mulai Muat & Download Bon</button>}
                      {load.status === 'Sedang Dimuat' && <><button onClick={() => downloadBon(load)} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#242f3d] hover:bg-[#141a24]"><Printer size={13} /> Download Bon PDF</button><button disabled={busyId === load.id} onClick={() => finishLoading(load)} className="btn-primary inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg disabled:opacity-50"><CheckCircle2 size={13} /> Selesai Muat</button></>}
                      {load.status === 'Selesai' && <><button onClick={() => downloadBon(load)} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#242f3d] hover:bg-[#141a24]"><Printer size={13} /> Download Bon</button><button onClick={() => downloadSuratJalan(sj)} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#22c55e] text-[#4ade80] hover:bg-[#22c55e]/10"><Printer size={13} /> Download Surat Jalan</button>{load.weighing_form && <button onClick={() => downloadWeighingForm(load)} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#294263] text-[#93c5fd]"><Printer size={13} /> Form Timbangan</button>}{load.document_type === 'CT' && <button onClick={() => openLinkedDocument(load, 'CR')} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#f59e0b] text-[#fbbf24]"><RotateCcw size={13} /> Catat CR</button>}{['MEMO', 'ND'].includes(load.document_type) && <button onClick={() => openLinkedDocument(load, 'RETUR')} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#f59e0b] text-[#fbbf24]"><RotateCcw size={13} /> Catat Retur</button>}{['CT', 'MEMO', 'ND'].includes(load.document_type) && <button onClick={() => openLinkedDocument(load, 'SO')} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#2563eb] text-[#60a5fa]"><Link2 size={13} /> Tautkan SO</button>}</>}
                    </div></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <Dialog open={Boolean(documentModal)} onOpenChange={(open) => { if (!open && !busyId) setDocumentModal(null); }}><DialogContent className="max-w-2xl border-[#242f3d] bg-[#0d121b] text-[#e7ebf2]"><DialogHeader><DialogTitle>{documentModal?.mode === 'CR' ? 'Pengembalian Barang Konsinyasi (CR)' : documentModal?.mode === 'RETUR' ? 'Retur Barang Memo' : 'Tautkan Dokumen Penjualan (SO)'}</DialogTitle><DialogDescription className="text-[#8b93a1]">Dokumen induk: {documentModal?.load?.document_type} · {documentModal?.load?.ref}. Riwayat dokumen lama tidak akan ditimpa.</DialogDescription></DialogHeader>{documentModal && <div className="space-y-4"><div><label className="text-sm block mb-1">Nomor Dokumen {documentModal.mode}</label><input value={documentModal.documentNo} onChange={(e) => setDocumentModal({ ...documentModal, documentNo: e.target.value })} placeholder={documentModal.mode === 'CR' ? 'CR/...' : documentModal.mode === 'RETUR' ? 'RT/... atau RM/...' : 'SO/xxxx/mm/09001'} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /></div><div className="space-y-3">{documentModal.items.map((item, index) => <div key={item.productId} className="rounded-lg border border-[#202a38] bg-[#0b0f17] p-3"><div className="flex justify-between gap-3 mb-2"><span className="text-sm font-semibold">{item.name}</span><span className="text-xs text-[#8b93a1]">Sisa {formatNum(item.remaining)} {item.unit}</span></div>{isReturnMode(documentModal.mode) ? <div className="grid grid-cols-1 sm:grid-cols-3 gap-2"><div><label className="text-xs text-[#8b93a1]">Kembali Good</label><input type="number" min="0" max={item.remaining} value={item.goodQty} onChange={(e) => updateDocumentItem(index, { goodQty: e.target.value })} className="w-full mt-1 bg-[#0d121b] border border-[#242f3d] rounded-lg px-3 py-2" /></div><div><label className="text-xs text-[#8b93a1]">Kembali Damage</label><input type="number" min="0" max={item.remaining} value={item.damagedQty} onChange={(e) => updateDocumentItem(index, { damagedQty: e.target.value })} className="w-full mt-1 bg-[#0d121b] border border-[#242f3d] rounded-lg px-3 py-2" /></div><div><label className="text-xs text-[#8b93a1]">Tumpukan barang Good</label><select value={item.stackCode} onChange={(e) => updateDocumentItem(index, { stackCode: e.target.value })} className="w-full mt-1 bg-[#0d121b] border border-[#242f3d] rounded-lg px-2 py-2"><option value="">Pilih lokasi...</option>{STACKS.map((code) => <option key={code}>{code}</option>)}</select></div></div> : <div><label className="text-xs text-[#8b93a1]">Jumlah terjual</label><input type="number" min="0" max={item.remaining} value={item.qty} onChange={(e) => updateDocumentItem(index, { qty: e.target.value })} className="w-full mt-1 bg-[#0d121b] border border-[#242f3d] rounded-lg px-3 py-2" /></div>}</div>)}</div><textarea rows="2" value={documentModal.note} onChange={(e) => setDocumentModal({ ...documentModal, note: e.target.value })} placeholder="Catatan (opsional)" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /></div>}<DialogFooter><button disabled={Boolean(busyId)} onClick={() => setDocumentModal(null)} className="px-4 py-2 border border-[#242f3d] rounded-lg">Batal</button><button disabled={Boolean(busyId)} onClick={saveLinkedDocument} className="btn-primary px-4 py-2 rounded-lg disabled:opacity-50">{busyId ? 'Menyimpan...' : 'Simpan Dokumen'}</button></DialogFooter></DialogContent></Dialog>
    </div>
  );
};

export default Pengeluaran;
