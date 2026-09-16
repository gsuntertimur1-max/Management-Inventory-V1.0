import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { FilePenLine, RefreshCcw, RotateCcw, Search, ShieldAlert } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError } from '../lib/api';
import { useData } from '../context/DataContext';
import { formatNum } from '../mock';

const displayDate = (value) => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' });
};

const qtyText = (item) => {
  const parts = [];
  if (Number(item.goodQty || 0) > 0) parts.push(`Baik ${formatNum(Number(item.goodQty))}`);
  if (Number(item.damagedQty || 0) > 0) parts.push(`Rusak ${formatNum(Number(item.damagedQty))}`);
  return `${parts.join(' · ') || '0'} ${item.unit || ''}`.trim();
};

const KoreksiOperasional = () => {
  const { fetchAll } = useData();
  const [tab, setTab] = useState('receipt');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [query, setQuery] = useState('');
  const [receipts, setReceipts] = useState([]);
  const [outbound, setOutbound] = useState([]);
  const [receiptCorrection, setReceiptCorrection] = useState(null);
  const [receiptReason, setReceiptReason] = useState('');
  const [outboundCorrection, setOutboundCorrection] = useState(null);

  const loadCorrections = useCallback(async () => {
    setLoading(true);
    try {
      const [receiptRes, outboundRes] = await Promise.all([
        api.get('/operational-corrections/receipts'),
        api.get('/operational-corrections/outbound'),
      ]);
      setReceipts(receiptRes.data || []);
      setOutbound(outboundRes.data || []);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadCorrections(); }, [loadCorrections]);

  const filteredReceipts = useMemo(() => {
    const text = query.trim().toLowerCase();
    if (!text) return receipts;
    return receipts.filter((row) => [row.ref, row.poNo, row.party, ...(row.items || []).flatMap((item) => [item.product, item.sku, item.stackCode])]
      .some((value) => String(value || '').toLowerCase().includes(text)));
  }, [receipts, query]);

  const filteredOutbound = useMemo(() => {
    const text = query.trim().toLowerCase();
    if (!text) return outbound;
    return outbound.filter((row) => [row.bonNo, row.antrian, row.party, row.polisi, row.pengambil, ...(row.documents || []), ...(row.items || []).flatMap((item) => [item.name, item.sku, item.stackCode])]
      .some((value) => String(value || '').toLowerCase().includes(text)));
  }, [outbound, query]);

  const openOutboundCorrection = (row) => setOutboundCorrection({
    row,
    party: row.party || '',
    polisi: row.polisi || '',
    pengambil: row.pengambil || '',
    keterangan: row.keterangan || '',
    reason: '',
  });

  const submitReceiptCorrection = async () => {
    if (!receiptCorrection || busy) return;
    if (receiptReason.trim().length < 3) return toast.error('Alasan koreksi minimal 3 karakter');
    setBusy(`receipt:${receiptCorrection.operationId}`);
    try {
      await api.post(`/operational-corrections/receipts/${receiptCorrection.operationId}/void`, { reason: receiptReason.trim() });
      toast.success('Penerimaan dibatalkan melalui transaksi reversal. Silakan input ulang penerimaan yang benar.');
      setReceiptCorrection(null);
      setReceiptReason('');
      await Promise.all([loadCorrections(), fetchAll()]);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusy('');
    }
  };

  const submitOutboundCorrection = async () => {
    if (!outboundCorrection || busy) return;
    if (outboundCorrection.reason.trim().length < 3) return toast.error('Alasan koreksi minimal 3 karakter');
    const id = outboundCorrection.row.id;
    setBusy(`outbound:${id}`);
    try {
      await api.put(`/operational-corrections/outbound/${id}`, {
        reason: outboundCorrection.reason.trim(),
        party: outboundCorrection.party,
        polisi: outboundCorrection.polisi,
        pengambil: outboundCorrection.pengambil,
        keterangan: outboundCorrection.keterangan,
      });
      toast.success('Metadata pengeluaran, Surat Jalan, dan riwayat transaksi sudah disinkronkan');
      setOutboundCorrection(null);
      await Promise.all([loadCorrections(), fetchAll()]);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">SUPERADMIN · AUDIT CONTROL</div>
          <h1 className="font-display text-3xl sm:text-4xl font-bold">Koreksi Operasional</h1>
          <p className="text-[#8b93a1] mt-2 max-w-3xl">Koreksi tidak menghapus transaksi. Penerimaan dibalik dengan reversal, sedangkan pengeluaran selesai hanya dapat mengubah metadata dokumen. Perubahan kuantitas pengeluaran tetap melalui Retur/CR.</p>
        </div>
        <button onClick={loadCorrections} disabled={loading} className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm hover:bg-[#141a24] disabled:opacity-50">
          <RefreshCcw size={16} className={loading ? 'animate-spin' : ''} /> Muat Ulang
        </button>
      </div>

      <div className="card-surface p-4 border border-[#7c2d12]/50 bg-[#451a03]/15">
        <div className="flex gap-3 items-start">
          <ShieldAlert size={20} className="text-[#f59e0b] shrink-0 mt-0.5" />
          <div className="text-sm text-[#c7d0dc]"><span className="font-semibold text-[#fbbf24]">Aturan koreksi:</span> penerimaan lama yang tidak menyimpan tumpukan asal akan ditolak otomatis. Ini mencegah sistem mengurangi stok dari tumpukan yang salah.</div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        <button onClick={() => setTab('receipt')} className={`px-4 py-2.5 rounded-lg text-sm font-semibold border ${tab === 'receipt' ? 'bg-[#2563eb]/15 border-[#2563eb] text-[#60a5fa]' : 'border-[#242f3d] text-[#9aa6b7]'}`}><RotateCcw size={15} className="inline mr-2" />Koreksi Penerimaan</button>
        <button onClick={() => setTab('outbound')} className={`px-4 py-2.5 rounded-lg text-sm font-semibold border ${tab === 'outbound' ? 'bg-[#2563eb]/15 border-[#2563eb] text-[#60a5fa]' : 'border-[#242f3d] text-[#9aa6b7]'}`}><FilePenLine size={15} className="inline mr-2" />Koreksi Pengeluaran Selesai</button>
        <div className="relative flex-1 min-w-[240px] ml-auto">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari PO, dokumen, produk, bon muat, polisi..." className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" />
        </div>
      </div>

      {loading ? <div className="card-surface p-10 text-center text-[#8b93a1]">Memuat data koreksi...</div> : tab === 'receipt' ? (
        <div className="space-y-3">
          {filteredReceipts.length === 0 && <div className="card-surface p-10 text-center text-[#6b7688]">Tidak ada penerimaan yang cocok.</div>}
          {filteredReceipts.map((row) => (
            <div key={row.operationId} className="card-surface p-5">
              <div className="flex flex-wrap justify-between gap-4">
                <div>
                  <div className="flex flex-wrap items-center gap-2"><span className="font-mono text-sm text-[#93c5fd]">{row.ref || 'Tanpa referensi'}</span><span className={`text-[10px] font-mono px-2 py-1 rounded ${row.status === 'DIBATALKAN' ? 'bg-[#ef4444]/15 text-[#f87171]' : 'bg-[#22c55e]/15 text-[#4ade80]'}`}>{row.status}</span></div>
                  <div className="text-xs text-[#8b93a1] mt-1">{displayDate(row.time)} · PO {row.poNo || '—'} · {row.party || '—'}</div>
                </div>
                <button disabled={!row.correctable || Boolean(busy)} onClick={() => { setReceiptCorrection(row); setReceiptReason(''); }} className="px-4 py-2 rounded-lg text-sm border border-[#7f1d1d] text-[#fca5a5] hover:bg-[#7f1d1d]/20 disabled:opacity-40 disabled:cursor-not-allowed">Batalkan Penerimaan</button>
              </div>
              <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-2">
                {(row.items || []).map((item, index) => <div key={`${item.transactionId}-${index}`} className="rounded-lg border border-[#202a38] bg-[#0b0f17] p-3"><div className="font-medium text-sm">{item.product}</div><div className="text-xs text-[#8b93a1] mt-1">{item.sku || '—'} · {qtyText(item)} · Lokasi {item.receiptLocation || item.stackCode || '—'}</div></div>)}
              </div>
              {!row.correctable && <div className="mt-3 text-xs text-[#f59e0b]">Tidak dapat dikoreksi otomatis: {row.reason}</div>}
              {row.voidReason && <div className="mt-3 text-xs text-[#8b93a1]">Alasan koreksi: {row.voidReason} · {row.voidedBy || '—'} · {displayDate(row.voidedAt)}</div>}
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {filteredOutbound.length === 0 && <div className="card-surface p-10 text-center text-[#6b7688]">Tidak ada pengeluaran selesai yang cocok.</div>}
          {filteredOutbound.map((row) => (
            <div key={row.id} className="card-surface p-5">
              <div className="flex flex-wrap justify-between gap-4">
                <div><div className="flex flex-wrap gap-2 items-center"><span className="font-mono text-sm text-[#93c5fd]">{row.bonNo || 'Bon Muat —'}</span><span className="text-[10px] font-mono px-2 py-1 rounded bg-[#22c55e]/15 text-[#4ade80]">SELESAI</span></div><div className="text-xs text-[#8b93a1] mt-1">{(row.documents || []).join(' · ')} · Antrian {row.antrian || '—'} · {displayDate(row.completedAt)}</div></div>
                <button disabled={Boolean(busy)} onClick={() => openOutboundCorrection(row)} className="px-4 py-2 rounded-lg text-sm border border-[#2563eb] text-[#60a5fa] hover:bg-[#2563eb]/15 disabled:opacity-40">Koreksi Metadata</button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-4 text-sm"><div><div className="label-mono text-[9px]">Penerima</div><div>{row.party || '—'}</div></div><div><div className="label-mono text-[9px]">Kendaraan</div><div>{row.polisi || '—'} · {row.pengambil || '—'}</div></div><div><div className="label-mono text-[9px]">Surat Jalan</div><div>{row.suratJalanNo || '—'}</div></div></div>
              {(row.correctionHistory || []).length > 0 && <div className="mt-3 text-xs text-[#f59e0b]">Sudah dikoreksi {row.correctionHistory.length} kali. Riwayat lama tetap disimpan.</div>}
            </div>
          ))}
        </div>
      )}

      {receiptCorrection && <div className="card-surface p-5 border border-[#7f1d1d]">
        <h2 className="font-display text-xl font-bold">Konfirmasi Reversal Penerimaan</h2>
        <p className="text-sm text-[#8b93a1] mt-1">Seluruh penerimaan <span className="font-mono text-[#e7ebf2]">{receiptCorrection.ref}</span> pada operasi ini akan dibalik. Setelah itu input ulang penerimaan dengan data yang benar.</p>
        <textarea rows="3" value={receiptReason} onChange={(e) => setReceiptReason(e.target.value)} placeholder="Alasan wajib, contoh: salah input kuantum penerimaan" className="w-full mt-4 bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#ef4444]" />
        <div className="flex gap-2 justify-end mt-3"><button disabled={Boolean(busy)} onClick={() => setReceiptCorrection(null)} className="px-4 py-2 rounded-lg border border-[#242f3d]">Batal</button><button disabled={Boolean(busy)} onClick={submitReceiptCorrection} className="px-4 py-2 rounded-lg bg-[#b91c1c] text-white disabled:opacity-50">{busy ? 'Memproses...' : 'Buat Reversal'}</button></div>
      </div>}

      {outboundCorrection && <div className="card-surface p-5 border border-[#1d4ed8]">
        <h2 className="font-display text-xl font-bold">Koreksi Metadata Pengeluaran</h2>
        <p className="text-sm text-[#8b93a1] mt-1">Tidak mengubah kuantum, produk, tumpukan, atau dokumen sumber. Perubahan akan diterapkan ke Pengeluaran, Surat Jalan, dan transaksi keluar.</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4"><input value={outboundCorrection.party} onChange={(e) => setOutboundCorrection({ ...outboundCorrection, party: e.target.value })} placeholder="Penerima barang" className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /><input value={outboundCorrection.polisi} onChange={(e) => setOutboundCorrection({ ...outboundCorrection, polisi: e.target.value })} placeholder="Nomor polisi" className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /><input value={outboundCorrection.pengambil} onChange={(e) => setOutboundCorrection({ ...outboundCorrection, pengambil: e.target.value })} placeholder="Sopir / pengambil" className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /><input value={outboundCorrection.keterangan} onChange={(e) => setOutboundCorrection({ ...outboundCorrection, keterangan: e.target.value })} placeholder="Keterangan dokumen" className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" /></div>
        <textarea rows="3" value={outboundCorrection.reason} onChange={(e) => setOutboundCorrection({ ...outboundCorrection, reason: e.target.value })} placeholder="Alasan koreksi wajib" className="w-full mt-3 bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" />
        <div className="flex gap-2 justify-end mt-3"><button disabled={Boolean(busy)} onClick={() => setOutboundCorrection(null)} className="px-4 py-2 rounded-lg border border-[#242f3d]">Batal</button><button disabled={Boolean(busy)} onClick={submitOutboundCorrection} className="btn-primary px-4 py-2 rounded-lg disabled:opacity-50">{busy ? 'Menyimpan...' : 'Simpan Koreksi'}</button></div>
      </div>}
    </div>
  );
};

export default KoreksiOperasional;
