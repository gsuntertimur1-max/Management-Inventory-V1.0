import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Printer, MonitorSmartphone, Play, CheckCircle2, RotateCcw, Link2, Search } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatNum, formatDate } from '../mock';
import { toast } from 'sonner';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '../components/ui/dialog';
import api, { apiError, downloadApiFile } from '../lib/api';
import { stackCodes } from '../lib/warehouses';
import { hasPermission } from '../lib/permissions';


const STATUS = {
  'Menunggu': { c: '#eab308', bg: 'rgba(234,179,8,.15)' },
  'Sedang Dimuat': { c: '#3b82f6', bg: 'rgba(59,130,246,.15)' },
  'Selesai': { c: '#22c55e', bg: 'rgba(34,197,94,.15)' },
  'Dibatalkan': { c: '#ef4444', bg: 'rgba(239,68,68,.14)' },
};
const escapeHtml = (value) => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

const measureSummary = (items = []) => {
  const totals = {};
  items.forEach((item) => { const unit = item.measureUnit || 'kg'; totals[unit] = (totals[unit] || 0) + Number(item.berat || 0); });
  return Object.entries(totals).filter(([, value]) => Math.abs(value) > 1e-9).map(([unit, value]) => `${formatNum(value)} ${unit}`).join(' + ') || '—';
};

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

const wibParts = (value = new Date()) => {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Jakarta',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(new Date(value));
  const map = Object.fromEntries(parts.filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]));
  return {
    date: `${map.year}-${map.month}-${map.day}`,
    minutes: Number(map.hour) * 60 + Number(map.minute),
  };
};

const loadingCutoffStatus = (startedAt) => {
  if (!startedAt) return 'NORMAL';
  const started = wibParts(startedAt);
  const current = wibParts();
  if (started.minutes >= 16 * 60) return 'LEMBUR_PENUH';
  if (started.date !== current.date || current.minutes >= 16 * 60) return 'LEMBUR_PARSIAL';
  return 'NORMAL';
};

const Pengeluaran = () => {
  const { user, outboundLoads, suratJalan, settings, startOutboundLoad, completeOutboundLoad, createConsignmentReturn, createSalesReturn, settleOutboundDocument, cancelOutboundLoad, editOutboundLoad, refreshOutboundLoads } = useData();
  const STACKS = stackCodes(settings?.warehouses);
  const navigate = useNavigate();
  const [filter, setFilter] = useState('Semua Status');
  const [query, setQuery] = useState('');
  const [busyId, setBusyId] = useState('');
  const [documentModal, setDocumentModal] = useState(null);
  const [costBusy, setCostBusy] = useState(false);
  const [paymentModal, setPaymentModal] = useState(null);
  const [cancelModal, setCancelModal] = useState(null);
  const [editModal, setEditModal] = useState(null);
  const [loadingCompletionModal, setLoadingCompletionModal] = useState(null);
  const isSuperadmin = user?.role === 'Administrator' || user?.role === 'Superadmin';
  const canOperateOutbound = hasPermission(user?.role, 'outbound');

  const list = outboundLoads.filter((load) => {
    const needle = query.trim().toLowerCase();
    const searchable = [load.ref, ...(load.documents || []), load.document_type, load.party, ...(load.document_links || []).flatMap((link) => [link.no, link.type]), ...(load.items || []).flatMap((item) => [item.name, item.sku, item.documentNo])].filter(Boolean).join(' ').toLowerCase();
    return (filter === 'Semua Status' || load.status === filter) && (!needle || searchable.includes(needle));
  });
  const findFinalSJ = (load) => suratJalan.find((sj) => sj.id === load.surat_jalan_id || sj.load_id === load.id);
  const downloadBon = (load) => downloadApiFile(`/export/bon-muat-v2/${load.id}.pdf`, `bon_pemuatan_${load.bon_no || load.id}_72mm.pdf`).catch((e) => toast.error(apiError(e)));
  const downloadSuratJalan = (sj) => sj ? downloadApiFile(`/export/surat-jalan/${sj.id}.pdf`, `surat_jalan_${(sj.no || sj.ref || sj.id).replaceAll('/', '-')}.pdf`).catch((e) => toast.error(apiError(e))) : toast.error('Surat Jalan belum tersedia');
  const downloadWeighingForm = (load) => downloadApiFile(`/export/weighing-form/outbound/${load.id}.pdf`, `form_timbangan_keluar_${load.antrian || load.id}.pdf`).catch((e) => toast.error(apiError(e)));
  const sourceDocumentFor = (load, item) => item.documentNo || load.ref || '';
  const linkedUsageFor = (load, sourceDocumentNo, productId) => (load.document_links || []).reduce((total, link) => {
    const linkSource = link.sourceDocumentNo || load.ref || '';
    if (linkSource !== sourceDocumentNo) return total;
    return total + (link.items || []).filter((item) => item.productId === productId).reduce((sum, item) => sum + (['CR', 'RETUR'].includes(link.type) ? Number(item.goodQty || 0) + Number(item.damagedQty || 0) : Number(item.qty || 0)), 0);
  }, 0);
  const sourceItemsFor = (load, sourceDocumentNo) => {
    const grouped = {};
    (load.items || []).filter((item) => sourceDocumentFor(load, item) === sourceDocumentNo).forEach((item) => { grouped[item.productId] = grouped[item.productId] || { ...item, qty: 0, documentNo: sourceDocumentNo }; grouped[item.productId].qty += Number(item.qty || 0); });
    return Object.values(grouped);
  };
  const remainingQty = (load, source, sourceDocumentNo = sourceDocumentFor(load, source)) => Math.max(Number(source.qty || 0) - linkedUsageFor(load, sourceDocumentNo, source.productId), 0);
  const consignmentSummary = Object.values(outboundLoads.filter((load) => ['MEMO', 'ND'].includes(load.document_type) && load.consignment_destination && load.status === 'Selesai').reduce((result, load) => {
    (load.documents || [load.ref]).forEach((sourceDocumentNo) => sourceItemsFor(load, sourceDocumentNo).forEach((item) => {
      const qty = remainingQty(load, item, sourceDocumentNo);
      if (qty <= 0) return;
      const key = `${load.consignment_destination}|${load.consignment_zone || 'Unit 18'}|${item.productId}|${item.channel || ''}`;
      result[key] = result[key] || { destination: load.consignment_destination, zone: load.consignment_zone || 'Unit 18', name: item.name, unit: item.unit, qty: 0 };
      result[key].qty += qty;
    }));
    return result;
  }, {}));
  const isReturnMode = (mode) => ['CR', 'RETUR', 'SO_RETUR'].includes(mode);
  const salesReturnRemaining = (load, item, sourceDocumentNo) => {
    const returned = (load.document_links || []).filter((link) => link.type === 'SO_RETUR' && link.sourceDocumentNo === sourceDocumentNo).reduce((total, link) => total + (link.items || []).filter((entry) => entry.productId === item.productId).reduce((sum, entry) => sum + Number(entry.goodQty || 0) + Number(entry.damagedQty || 0), 0), 0);
    return Math.max(Number(item.qty || 0) - returned, 0);
  };
  const returnItemsFor = (load, mode, sourceDocumentNo) => sourceItemsFor(load, sourceDocumentNo).map((item) => {
    const remaining = mode === 'SO_RETUR' ? salesReturnRemaining(load, item, sourceDocumentNo) : remainingQty(load, item, sourceDocumentNo);
    return { productId: item.productId, name: item.name, unit: item.unit, goodQty: 0, stackCode: item.location || '', placements: [{ goodQty: 0, stackCode: item.location || '' }], damagedQty: 0, remaining };
  });
  const openLinkedDocument = (load, mode) => {
    const documents = load.documents || [load.ref];
    const sourceDocumentNo = documents[0] || '';
    const sourceItems = sourceItemsFor(load, sourceDocumentNo);
    setDocumentModal({ load, mode, documentNo: '', note: '', sourceDocumentNo, items: isReturnMode(mode) ? returnItemsFor(load, mode, sourceDocumentNo) : sourceItems.map((item) => ({ productId: item.productId, name: item.name, unit: item.unit, qty: remainingQty(load, item, sourceDocumentNo), remaining: remainingQty(load, item, sourceDocumentNo) })) });
  };
  const updateDocumentItem = (index, patch) => setDocumentModal((prev) => ({ ...prev, items: prev.items.map((item, i) => i === index ? { ...item, ...patch } : item) }));
  const updateReturnPlacement = (itemIndex, placementIndex, patch) => updateDocumentItem(itemIndex, { placements: documentModal.items[itemIndex].placements.map((placement, index) => index === placementIndex ? { ...placement, ...patch } : placement) });
  const saveLinkedDocument = async () => {
    if (!documentModal?.documentNo.trim()) return toast.error(`Isi nomor dokumen ${documentModal?.mode}`);
    setBusyId(documentModal.load.id);
    try {
      const payload = { documentNo: documentModal.documentNo, sourceDocumentNo: documentModal.sourceDocumentNo, note: documentModal.note, returnType: documentModal.mode, items: documentModal.items.map((item) => isReturnMode(documentModal.mode) ? { productId: item.productId, goodQty: Number(item.goodQty || 0), damagedQty: Number(item.damagedQty || 0), stackCode: item.stackCode || '', placements: (item.placements || []).map((placement) => ({ goodQty: Number(placement.goodQty || 0), stackCode: placement.stackCode || '' })).filter((placement) => placement.goodQty > 0) } : { productId: item.productId, qty: Number(item.qty || 0) }).filter((item) => isReturnMode(documentModal.mode) ? item.placements.reduce((total, placement) => total + placement.goodQty, 0) + item.goodQty + item.damagedQty > 0 : item.qty > 0) };
      if (documentModal.mode === 'SO_RETUR') await createSalesReturn(documentModal.load.id, { ...payload, sourceDocumentNo: documentModal.sourceDocumentNo });
      else if (isReturnMode(documentModal.mode)) await createConsignmentReturn(documentModal.load.id, payload);
      else await settleOutboundDocument(documentModal.load.id, payload);
      toast.success(`Dokumen ${documentModal.mode === 'SO_RETUR' ? 'Retur SO' : documentModal.mode} berhasil ditautkan`); setDocumentModal(null);
    } catch (e) { toast.error(e?.response?.data?.detail || 'Gagal menyimpan dokumen'); } finally { setBusyId(''); }
  };

  const writeBonMuat = (load, targetWindow) => {
    const w = targetWindow || window.open('', '_blank', 'width=420,height=760');
    if (!w) {
      toast.error('Popup diblokir browser. Izinkan popup untuk mencetak Bon Muat.');
      return false;
    }

    const logoUrl = `${window.location.origin}/bulog-sunter.png`;
    const itemNames = (load.items || []).map((item) => `<div class="product-name">${escapeHtml(item.name)}</div><div class="field-value">${escapeHtml(item.documentNo || load.ref || '-')} · Tumpukan: ${escapeHtml(item.stackCode || item.location || '-')}</div>`).join('');
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
      <div class="grid"><div class="k">Kuantum Fisik:</div><div class="v">${escapeHtml(measureSummary(load.items || []))}</div></div>
      <div class="grid"><div class="k">Lokasi muat:</div><div class="v">${escapeHtml(load.unit_loading || '-')}</div></div>

      <div class="rule"></div>
      <div class="grid"><div class="k">Dokumen ${escapeHtml(load.document_type || 'SO')}:</div><div class="v">${escapeHtml((load.documents || [load.ref]).join(', ') || '-')}</div></div>
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
    const rows = (sj.items || []).map((item, index) => `<tr><td>${index + 1}</td><td>${escapeHtml(item.name)}</td><td class="right">${escapeHtml(formatNum(item.qty))}</td><td>${escapeHtml(item.unit || '')}</td><td class="right">${escapeHtml(formatNum(item.berat || 0))} ${escapeHtml(item.measureUnit || 'kg')}</td></tr>`).join('');
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
      <table><thead><tr><th>No</th><th>Nama Barang</th><th>Jumlah</th><th>Satuan</th><th>Kuantum Fisik</th></tr></thead><tbody>${rows}</tbody><tfoot><tr><td colspan="2"><b>Total</b></td><td class="right"><b>${escapeHtml(formatNum(sj.unit || 0))}</b></td><td></td><td class="right"><b>${escapeHtml(measureSummary(sj.items || []))}</b></td></tr></tfoot></table>
      <div class="signatures"><div><p>Petugas Gudang</p><div class="space"></div><b>${escapeHtml(sj.operator || '')}</b></div><div><p>Penerima</p><div class="space"></div><b>${escapeHtml(sj.penerima || '')}</b></div></div>
    </body></html>`);
    w.document.close();
    w.focus();
    setTimeout(() => w.print(), 450);
  };

  const saveLoadingPayment = async () => {
    if (!paymentModal) return;
    const amount = Number(paymentModal.amount || 0);
    if (amount <= 0) return toast.error('Nominal pembayaran harus diisi');
    setCostBusy(true);
    try { await api.post(`/outbound-loads/${paymentModal.load.id}/loading-fee-payment`, { amount, method: paymentModal.method, payer: paymentModal.payer, note: paymentModal.note }); toast.success('Pembayaran biaya muat dicatat'); setPaymentModal(null); await refreshOutboundLoads(); } catch (e) { toast.error(apiError(e)); } finally { setCostBusy(false); }
  };

  const openEdit = (load) => setEditModal({
    load,
    documents: [...(load.documents || [load.ref])],
    polisi: load.polisi || '',
    pengambil: load.pengambil || '',
    items: (load.items || []).map((item) => ({ productId: item.productId, name: item.name, unit: item.unit, qty: item.qty, documentNo: item.documentNo || load.ref || '', documentQty: item.documentQty || 0, stackCode: item.stackCode || '', channel: item.channel || '' })),
  });
  const updateEditItem = (index, patch) => setEditModal((prev) => ({ ...prev, items: prev.items.map((item, i) => i === index ? { ...item, ...patch } : item) }));
  const saveEdit = async () => {
    if (!editModal) return;
    const documents = editModal.documents.map((doc) => doc.trim()).filter(Boolean);
    if (!documents.length || documents.length !== editModal.documents.length) return toast.error('Lengkapi nomor dokumen');
    if (new Set(documents).size !== documents.length) return toast.error('Nomor dokumen tidak boleh sama');
    if (documents.length > 1 && editModal.items.some((item) => !item.documentNo || !documents.includes(item.documentNo))) return toast.error('Pilih dokumen sumber pada semua komoditas');
    if (documents.some((doc) => !editModal.items.some((item) => (item.documentNo || documents[0]) === doc))) return toast.error('Setiap dokumen wajib memiliki komoditas');
    if (editModal.items.some((item) => Number(item.qty) <= 0)) return toast.error('Kuantum harus lebih dari 0');
    setBusyId(editModal.load.id);
    try {
      await editOutboundLoad(editModal.load.id, { documents, polisi: editModal.polisi, pengambil: editModal.pengambil, items: editModal.items.map((item) => ({ productId: item.productId, qty: Number(item.qty), documentNo: item.documentNo || documents[0], documentQty: Number(item.documentQty || 0), stackCode: item.stackCode || '', channel: item.channel || '' })) });
      toast.success('Pengeluaran berhasil dikoreksi');
      setEditModal(null);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusyId('');
    }
  };

  const saveCancellation = async () => {
    if (!cancelModal?.reason?.trim() || cancelModal.reason.trim().length < 3) return toast.error('Isi alasan pembatalan minimal 3 karakter');
    setBusyId(cancelModal.load.id);
    try {
      await cancelOutboundLoad(cancelModal.load.id, { documentNo: cancelModal.documentNo || '', reason: cancelModal.reason.trim() });
      toast.success(cancelModal.documentNo ? `Dokumen ${cancelModal.documentNo} dibatalkan` : 'Antrian pemuatan dibatalkan');
      setCancelModal(null);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusyId('');
    }
  };

  const startAndPrint = async (load) => {
    if (busyId) return;
    setBusyId(load.id);
    try {
      const updated = await startOutboundLoad(load.id);
      await downloadApiFile(`/export/bon-muat-v2/${updated.id}.pdf`, `bon_pemuatan_${updated.bon_no || updated.id}_72mm.pdf`);
      toast.success(`Pemuatan ${updated.antrian} dimulai · Bon Pemuatan PDF diunduh`);
    } catch (e) {
      toast.error(apiError(e) || 'Gagal memulai pemuatan');
    } finally {
      setBusyId('');
    }
  };

  const finalizeLoading = async (load, payload = {}) => {
    if (busyId) return;
    setBusyId(load.id);
    try {
      const result = await completeOutboundLoad(load.id, payload);
      toast.success(`Pemuatan selesai · Surat Jalan ${result?.suratJalan?.no || ''} diterbitkan`);
      setLoadingCompletionModal(null);
    } catch (e) {
      const detail = e?.response?.data?.detail || 'Gagal menyelesaikan pemuatan';
      toast.error(detail);
      if (String(detail).includes('pukul 16.00') && !loadingCompletionModal) {
        setLoadingCompletionModal({
          load,
          items: (load.items || []).map((item, index) => ({
            index,
            name: item.name,
            unit: item.unit,
            qty: Number(item.qty || 0),
            normalQtyBefore1600: '',
          })),
        });
      }
    } finally {
      setBusyId('');
    }
  };

  const finishLoading = async (load) => {
    if (busyId) return;
    const cutoffStatus = loadingCutoffStatus(load.started_at);
    if (cutoffStatus === 'LEMBUR_PARSIAL') {
      setLoadingCompletionModal({
        load,
        items: (load.items || []).map((item, index) => ({
          index,
          name: item.name,
          unit: item.unit,
          qty: Number(item.qty || 0),
          normalQtyBefore1600: '',
        })),
      });
      return;
    }
    const label = cutoffStatus === 'LEMBUR_PENUH'
      ? 'Pemuatan dimulai setelah 16.00 sehingga seluruh kuantitas dihitung lembur. Lanjutkan?'
      : `Selesaikan pemuatan ${load.antrian}? Setelah ini stok akan dikurangi dan Surat Jalan diterbitkan.`;
    if (!window.confirm(label)) return;
    await finalizeLoading(load);
  };

  const saveLoadingCompletion = async () => {
    if (!loadingCompletionModal || busyId) return;
    const invalid = loadingCompletionModal.items.some((item) => (
      item.normalQtyBefore1600 === ''
      || Number(item.normalQtyBefore1600) < 0
      || Number(item.normalQtyBefore1600) > Number(item.qty)
    ));
    if (invalid) {
      toast.error('Isi kuantitas selesai sampai 16.00 untuk setiap komoditas, antara 0 dan total pemuatan.');
      return;
    }
    await finalizeLoading(loadingCompletionModal.load, {
      items: loadingCompletionModal.items.map((item) => ({
        index: item.index,
        normalQtyBefore1600: Number(item.normalQtyBefore1600),
      })),
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Pengiriman Barang</div>
          <h1 className="font-display text-4xl font-bold">Proses Pengeluaran</h1>
        </div>
        <button onClick={() => navigate('/antrian')} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24]"><MonitorSmartphone size={15} /> Layar Antrian</button>
      </div>

      {consignmentSummary.length > 0 && <div className="card-surface p-5 border border-[#1f3657]">
        <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3"><div><div className="label-mono text-[10px] text-[#93c5fd]">Persediaan di luar stok gudang utama</div><h2 className="font-display text-lg font-bold mt-1">Stok Konsinyasi Unit 18</h2></div></div>
        <div className="overflow-x-auto"><table className="w-full text-xs tbl"><thead><tr className="text-left border-b border-[#1a222e]"><th className="py-2 pr-4">Tujuan</th><th className="py-2 pr-4">Zona</th><th className="py-2 pr-4">Komoditas</th><th className="py-2 text-right">Sisa Konsinyasi</th></tr></thead><tbody>{consignmentSummary.map((item) => <tr key={`${item.destination}-${item.zone}-${item.name}`} className="border-b border-[#131a24]"><td className="py-2.5 pr-4">{item.destination}</td><td className="py-2.5 pr-4 font-mono text-[#93c5fd]">{item.zone}</td><td className="py-2.5 pr-4">{item.name}</td><td className="py-2.5 text-right font-mono font-semibold">{formatNum(item.qty)} {item.unit}</td></tr>)}</tbody></table></div>
      </div>}

      <div className="card-surface p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="relative min-w-[280px] flex-1"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari SO / CT / TM / Memo / produk..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
          <select value={filter} onChange={(e) => setFilter(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none"><option>Semua Status</option><option>Menunggu</option><option>Sedang Dimuat</option><option>Selesai</option></select>
          
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
                    <td className="py-3 pr-4 text-xs min-w-[250px]">{(load.items || []).map((item, i) => <div key={i} className="text-[#aab4c4]">{item.name} · {formatNum(item.qty)} {item.unit} <span className="text-[#6b7688]">({formatNum(item.berat || 0)} {item.measureUnit || 'kg'})</span></div>)}</td>
                    <td className="py-3 pr-4 whitespace-nowrap">{load.unit_loading || '—'}</td>
                    <td className="py-3 pr-4"><span className="text-xs px-2.5 py-1 rounded-full font-medium whitespace-nowrap" style={{ background: st.bg, color: st.c }}>{load.status}</span></td>
                    <td className="py-3 pr-4 text-xs min-w-[220px]"><div className="font-mono font-semibold text-[#93c5fd]">{load.document_type || 'SO'} · {load.ref || '—'}</div>{load.request_document && <div className="font-mono mt-1 text-[#fbbf24]">↳ Dasar: {load.request_document}</div>}{(load.document_links || []).map((link) => <div key={link.id} className="font-mono mt-1 text-[#4ade80]">↳ {link.type} · {link.no}</div>)}<div className="mt-1 text-[#6b7688]">{load.document_status || (load.status === 'Selesai' ? 'Selesai' : 'Menunggu pemuatan')} · SJ {load.surat_jalan_no || 'belum terbit'}</div>{Number(load.loading_cost?.chargeable || 0) > 0 && <div className={`mt-2 font-semibold ${load.loading_fee_payment_status === 'LUNAS' ? 'text-[#4ade80]' : load.loading_fee_payment_status === 'SEBAGIAN' ? 'text-[#fbbf24]' : 'text-[#ef4444]'}`}>Biaya muat {load.loading_fee_payment_status === 'LUNAS' ? 'sudah dibayar' : load.loading_fee_payment_status === 'SEBAGIAN' ? 'dibayar sebagian' : 'belum dibayar'} · Rp {formatNum(Math.max(Number(load.loading_cost?.chargeable || 0) - Number(load.loading_fee_payment_total || 0), 0))}</div>}{load.loading_cost?.total > 0 && load.loading_cost?.chargeable <= 0 && <div className="mt-2 text-[#8b93a1]">Biaya muat {load.items?.some((item) => item.loadingFee?.mode === 'TERMASUK') ? 'termasuk harga SO' : 'tidak ditagihkan'}</div>}</td>
                    <td className="py-3 pr-4"><div className="flex flex-wrap gap-2 min-w-[270px]">
                      {load.status === 'Menunggu' && canOperateOutbound && <>{isSuperadmin && <button disabled={busyId === load.id} onClick={() => openEdit(load)} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#f59e0b] text-[#fbbf24] hover:bg-[#f59e0b]/10 disabled:opacity-50">Edit</button>}<button disabled={busyId === load.id} onClick={() => startAndPrint(load)} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#2563eb] text-[#60a5fa] hover:bg-[#2563eb]/10 disabled:opacity-50"><Play size={13} /> Mulai Muat & Download Bon</button><button disabled={busyId === load.id} onClick={() => setCancelModal({ load, documentNo: '', reason: '' })} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#ef4444] text-[#f87171] hover:bg-[#ef4444]/10 disabled:opacity-50">Batalkan</button></>}
                      {load.status === 'Sedang Dimuat' && <><button onClick={() => downloadBon(load)} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#242f3d] hover:bg-[#141a24]"><Printer size={13} /> Download Bon PDF</button>{canOperateOutbound && <button disabled={busyId === load.id} onClick={() => finishLoading(load)} className="btn-primary inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg disabled:opacity-50"><CheckCircle2 size={13} /> Selesai Muat</button>}</>}
                      {load.status === 'Selesai' && <>{canOperateOutbound && <>{Number(load.loading_cost?.chargeable || 0) > Number(load.loading_fee_payment_total || 0) && <button onClick={() => setPaymentModal({ load, amount: Math.max(Number(load.loading_cost?.chargeable || 0) - Number(load.loading_fee_payment_total || 0), 0), method: 'TUNAI', payer: load.pengambil || load.party || '', note: '' })} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#f59e0b] text-[#fbbf24]"><CheckCircle2 size={13} /> Catat Bayar Muat</button>}{load.document_type === 'SO' && <button onClick={() => openLinkedDocument(load, 'SO_RETUR')} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#f59e0b] text-[#fbbf24]"><RotateCcw size={13} /> Catat Retur SO</button>}{load.document_type === 'CT' && <button onClick={() => openLinkedDocument(load, 'CR')} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#f59e0b] text-[#fbbf24]"><RotateCcw size={13} /> Catat CR</button>}{['MEMO', 'ND'].includes(load.document_type) && <button onClick={() => openLinkedDocument(load, 'RETUR')} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#f59e0b] text-[#fbbf24]"><RotateCcw size={13} /> Catat Retur</button>}{['CT', 'MEMO', 'ND'].includes(load.document_type) && <button onClick={() => openLinkedDocument(load, 'SO')} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#2563eb] text-[#60a5fa]"><Link2 size={13} /> Tautkan SO</button>}</>}<button onClick={() => downloadBon(load)} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#242f3d] hover:bg-[#141a24]"><Printer size={13} /> Download Bon</button><button onClick={() => downloadSuratJalan(sj)} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#22c55e] text-[#4ade80] hover:bg-[#22c55e]/10"><Printer size={13} /> Download Surat Jalan</button>{load.weighing_form && <button onClick={() => downloadWeighingForm(load)} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#294263] text-[#93c5fd]"><Printer size={13} /> Form Timbangan</button>}</>}
                    </div></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <Dialog open={Boolean(loadingCompletionModal)} onOpenChange={(open) => { if (!open && !busyId) setLoadingCompletionModal(null); }}>
        <DialogContent className="max-w-xl border-[#242f3d] bg-[#0d121b] text-[#e7ebf2]">
          <DialogHeader>
            <DialogTitle>Selesaikan Pemuatan · Lembur Parsial</DialogTitle>
            <DialogDescription className="text-[#8b93a1]">
              Mulai {printDateWib(loadingCompletionModal?.load?.started_at)} · batas lembur 16.00 WIB. Isi jumlah yang sudah selesai dimuat sampai pukul 16.00; sisanya otomatis menjadi kuantitas lembur.
            </DialogDescription>
          </DialogHeader>
          {loadingCompletionModal && <div className="space-y-3">
            {loadingCompletionModal.items.map((item, index) => {
              const normal = Number(item.normalQtyBefore1600 || 0);
              const overtime = item.normalQtyBefore1600 === '' ? null : Math.max(Number(item.qty || 0) - normal, 0);
              return <div key={item.index} className="rounded-lg border border-[#263244] bg-[#0b0f17] p-3">
                <div className="flex justify-between gap-3"><div><div className="font-semibold text-sm">{item.name}</div><div className="text-xs text-[#8b93a1]">Total {formatNum(item.qty)} {item.unit}</div></div>{overtime !== null && <div className="text-right text-xs"><div className="text-[#8b93a1]">Lembur</div><div className="font-mono font-bold text-[#fbbf24]">{formatNum(overtime)} {item.unit}</div></div>}</div>
                <label className="text-xs text-[#93c5fd] block mt-3 mb-1">Sudah selesai sampai 16.00</label>
                <input type="number" min="0" max={item.qty} step="any" value={item.normalQtyBefore1600} onChange={(e) => setLoadingCompletionModal((prev) => ({ ...prev, items: prev.items.map((row, rowIndex) => rowIndex === index ? { ...row, normalQtyBefore1600: e.target.value } : row) }))} className="w-full bg-[#0d121b] border border-[#294263] rounded-lg px-3 py-2.5 font-mono" placeholder={`0 – ${item.qty}`} />
              </div>;
            })}
            <div className="rounded-lg border border-[#78350f] bg-[#1c1408] p-3 text-xs text-[#fcd34d]">Biaya dasar tetap dihitung untuk seluruh kuantitas. Tambahan lembur hanya dikenakan pada sisa setelah kuantitas di atas.</div>
          </div>}
          <DialogFooter><button disabled={Boolean(busyId)} onClick={() => setLoadingCompletionModal(null)} className="px-4 py-2 border border-[#242f3d] rounded-lg">Batal</button><button disabled={Boolean(busyId)} onClick={saveLoadingCompletion} className="btn-primary px-4 py-2 rounded-lg disabled:opacity-50">{busyId ? 'Menyimpan...' : 'Simpan & Selesaikan Muat'}</button></DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={Boolean(editModal)} onOpenChange={(open) => { if (!open && !busyId) setEditModal(null); }}><DialogContent className="max-w-2xl border-[#242f3d] bg-[#0d121b] text-[#e7ebf2]"><DialogHeader><DialogTitle>Koreksi Pengeluaran</DialogTitle><DialogDescription className="text-[#8b93a1]">Khusus Superadmin · hanya tersedia sebelum pemuatan dimulai. Riwayat koreksi tetap disimpan.</DialogDescription></DialogHeader>{editModal && <div className="space-y-4"><div className="grid grid-cols-1 sm:grid-cols-2 gap-3"><div><label className="text-sm block mb-1">Nomor Polisi</label><input value={editModal.polisi} onChange={(e) => setEditModal({ ...editModal, polisi: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /></div><div><label className="text-sm block mb-1">Nama Sopir / Pengambil</label><input value={editModal.pengambil} onChange={(e) => setEditModal({ ...editModal, pengambil: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /></div></div><div><label className="text-sm block mb-1">Nomor Dokumen</label>{editModal.documents.map((doc, index) => <input key={index} value={doc} onChange={(e) => { const documents = [...editModal.documents]; documents[index] = e.target.value; setEditModal({ ...editModal, documents }); }} className="w-full mb-2 bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 font-mono text-sm" />)}</div><div className="space-y-2">{editModal.items.map((item, index) => <div key={index} className="grid grid-cols-1 sm:grid-cols-[1fr_110px_190px] gap-2 rounded-lg border border-[#202a38] bg-[#0b0f17] p-3"><div><div className="text-sm font-semibold">{item.name}</div><div className="text-xs text-[#8b93a1]">{item.unit}</div></div><div><label className="text-xs text-[#8b93a1]">Kuantum</label><input type="number" min="0.01" step="any" value={item.qty} onChange={(e) => updateEditItem(index, { qty: e.target.value })} className="w-full mt-1 bg-[#0d121b] border border-[#242f3d] rounded-lg px-3 py-2" /></div><div><label className="text-xs text-[#8b93a1]">Dokumen sumber</label><select value={item.documentNo || editModal.documents[0] || ''} onChange={(e) => updateEditItem(index, { documentNo: e.target.value })} className="w-full mt-1 bg-[#0d121b] border border-[#242f3d] rounded-lg px-2 py-2 text-xs">{editModal.documents.map((doc) => <option key={doc} value={doc}>{doc || 'Isi dokumen...'}</option>)}</select></div></div>)}</div></div>}<DialogFooter><button disabled={Boolean(busyId)} onClick={() => setEditModal(null)} className="px-4 py-2 border border-[#242f3d] rounded-lg">Batal</button><button disabled={Boolean(busyId)} onClick={saveEdit} className="btn-primary px-4 py-2 rounded-lg disabled:opacity-50">{busyId ? 'Menyimpan...' : 'Simpan Koreksi'}</button></DialogFooter></DialogContent></Dialog>
      <Dialog open={Boolean(cancelModal)} onOpenChange={(open) => { if (!open && !busyId) setCancelModal(null); }}><DialogContent className="max-w-md border-[#242f3d] bg-[#0d121b] text-[#e7ebf2]"><DialogHeader><DialogTitle>Batalkan Dokumen Pengeluaran</DialogTitle><DialogDescription className="text-[#8b93a1]">Pembatalan tidak menghapus riwayat. Dokumen yang selesai harus dikoreksi melalui retur atau dokumen balik.</DialogDescription></DialogHeader>{cancelModal && <div className="space-y-3"><div><label className="text-sm block mb-1">Dokumen yang dibatalkan</label><select value={cancelModal.documentNo} onChange={(e) => setCancelModal({ ...cancelModal, documentNo: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5"><option value="">Semua dokumen pada antrian</option>{(cancelModal.load.documents || [cancelModal.load.ref]).map((doc) => <option key={doc} value={doc}>{doc}</option>)}</select><p className="text-xs text-[#8b93a1] mt-1">Pilih satu dokumen untuk pembatalan sebagian pada pemuatan multi-SO.</p></div><div><label className="text-sm block mb-1">Alasan pembatalan</label><textarea rows="3" value={cancelModal.reason} onChange={(e) => setCancelModal({ ...cancelModal, reason: e.target.value })} placeholder="Contoh: permintaan dibatalkan oleh penerima" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /></div></div>}<DialogFooter><button disabled={Boolean(busyId)} onClick={() => setCancelModal(null)} className="px-4 py-2 border border-[#242f3d] rounded-lg">Kembali</button><button disabled={Boolean(busyId)} onClick={saveCancellation} className="px-4 py-2 rounded-lg bg-[#dc2626] text-white disabled:opacity-50">{busyId ? 'Membatalkan...' : 'Simpan Pembatalan'}</button></DialogFooter></DialogContent></Dialog>
      <Dialog open={Boolean(paymentModal)} onOpenChange={(open) => { if (!open && !costBusy) setPaymentModal(null); }}><DialogContent className="max-w-md border-[#242f3d] bg-[#0d121b] text-[#e7ebf2]"><DialogHeader><DialogTitle>Pembayaran Biaya Pemuatan</DialogTitle><DialogDescription className="text-[#8b93a1]">Dokumen {paymentModal?.load?.ref} · biaya ini hanya catatan internal.</DialogDescription></DialogHeader>{paymentModal && <div className="space-y-3"><div><label className="text-sm block mb-1">Nominal diterima</label><input type="number" min="1" value={paymentModal.amount} onChange={(e) => setPaymentModal({ ...paymentModal, amount: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 font-mono" /></div><div><label className="text-sm block mb-1">Metode</label><select value={paymentModal.method} onChange={(e) => setPaymentModal({ ...paymentModal, method: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5"><option value="TUNAI">Tunai</option><option value="TRANSFER">Transfer</option><option value="PIUTANG">Piutang / Disetujui</option></select></div><div><label className="text-sm block mb-1">Nama pembayar</label><input value={paymentModal.payer} onChange={(e) => setPaymentModal({ ...paymentModal, payer: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /></div><textarea rows="2" value={paymentModal.note} onChange={(e) => setPaymentModal({ ...paymentModal, note: e.target.value })} placeholder="Catatan (opsional)" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /></div>}<DialogFooter><button onClick={() => setPaymentModal(null)} className="px-4 py-2 border border-[#242f3d] rounded-lg">Batal</button><button disabled={costBusy} onClick={saveLoadingPayment} className="btn-primary px-4 py-2 rounded-lg">{costBusy ? 'Menyimpan...' : 'Simpan Pembayaran'}</button></DialogFooter></DialogContent></Dialog>
      <Dialog open={Boolean(documentModal)} onOpenChange={(open) => { if (!open && !busyId) setDocumentModal(null); }}><DialogContent className="max-w-2xl border-[#242f3d] bg-[#0d121b] text-[#e7ebf2]"><DialogHeader><DialogTitle>{documentModal?.mode === 'SO_RETUR' ? 'Retur Barang dari SO' : documentModal?.mode === 'CR' ? 'Pengembalian Barang Konsinyasi (CR)' : documentModal?.mode === 'RETUR' ? 'Retur Barang Memo' : 'Tautkan Dokumen Penjualan (SO)'}</DialogTitle><DialogDescription className="text-[#8b93a1]">Dokumen induk: {documentModal?.load?.document_type} · {documentModal?.load?.ref}. Riwayat dokumen lama tidak akan ditimpa.</DialogDescription></DialogHeader>{documentModal && <div className="space-y-4">{(documentModal.load.documents || [documentModal.load.ref]).length > 1 && <div><label className="text-sm block mb-1">Dokumen sumber</label><select value={documentModal.sourceDocumentNo} onChange={(e) => { const sourceDocumentNo = e.target.value; setDocumentModal({ ...documentModal, sourceDocumentNo, items: returnItemsFor(documentModal.load, documentModal.mode, sourceDocumentNo) }); }} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5">{(documentModal.load.documents || [documentModal.load.ref]).map((doc) => <option key={doc} value={doc}>{doc}</option>)}</select></div>}<div><label className="text-sm block mb-1">Nomor Dokumen {documentModal.mode === 'SO_RETUR' ? 'Retur' : documentModal.mode}</label><input value={documentModal.documentNo} onChange={(e) => setDocumentModal({ ...documentModal, documentNo: e.target.value })} placeholder={documentModal.mode === 'CR' ? 'CR/...' : isReturnMode(documentModal.mode) ? 'RT/... atau RM/...' : 'SO/xxxx/mm/09001'} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /></div><div className="space-y-3">{documentModal.items.map((item, index) => <div key={item.productId} className="rounded-lg border border-[#202a38] bg-[#0b0f17] p-3"><div className="flex justify-between gap-3 mb-2"><span className="text-sm font-semibold">{item.name}</span><span className="text-xs text-[#8b93a1]">Sisa {formatNum(item.remaining)} {item.unit}</span></div>{isReturnMode(documentModal.mode) ? <div className="grid grid-cols-1 sm:grid-cols-3 gap-2"><div><label className="text-xs text-[#8b93a1]">Kembali Good</label><input type="number" min="0" max={item.remaining} value={item.goodQty} onChange={(e) => updateDocumentItem(index, { goodQty: e.target.value })} className="w-full mt-1 bg-[#0d121b] border border-[#242f3d] rounded-lg px-3 py-2" /></div><div><label className="text-xs text-[#8b93a1]">Kembali Damage</label><input type="number" min="0" max={item.remaining} value={item.damagedQty} onChange={(e) => updateDocumentItem(index, { damagedQty: e.target.value })} className="w-full mt-1 bg-[#0d121b] border border-[#242f3d] rounded-lg px-3 py-2" /></div><div><label className="text-xs text-[#8b93a1]">Tumpukan barang Good</label><select value={item.stackCode} onChange={(e) => updateDocumentItem(index, { stackCode: e.target.value })} className="w-full mt-1 bg-[#0d121b] border border-[#242f3d] rounded-lg px-2 py-2"><option value="">Pilih lokasi...</option>{STACKS.map((code) => <option key={code}>{code}</option>)}</select></div></div> : <div><label className="text-xs text-[#8b93a1]">Jumlah terjual</label><input type="number" min="0" max={item.remaining} value={item.qty} onChange={(e) => updateDocumentItem(index, { qty: e.target.value })} className="w-full mt-1 bg-[#0d121b] border border-[#242f3d] rounded-lg px-3 py-2" /></div>}</div>)}</div><textarea rows="2" value={documentModal.note} onChange={(e) => setDocumentModal({ ...documentModal, note: e.target.value })} placeholder="Catatan (opsional)" className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /></div>}<DialogFooter><button disabled={Boolean(busyId)} onClick={() => setDocumentModal(null)} className="px-4 py-2 border border-[#242f3d] rounded-lg">Batal</button><button disabled={Boolean(busyId)} onClick={saveLinkedDocument} className="btn-primary px-4 py-2 rounded-lg disabled:opacity-50">{busyId ? 'Menyimpan...' : 'Simpan Dokumen'}</button></DialogFooter></DialogContent></Dialog>
    </div>
  );
};

export default Pengeluaran;
