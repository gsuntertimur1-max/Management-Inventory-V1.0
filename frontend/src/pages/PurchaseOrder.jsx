import React, { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { Plus, X, Trash2, PackageCheck, Printer, DollarSign } from 'lucide-react';
import { useData } from '../context/DataContext';
import { apiError } from '../lib/api';
import { formatRp, formatDate, formatNum } from '../mock';
import { toast } from 'sonner';
import { packagingText, quantityFromInput, quantityIsValid, totalWeight } from '../lib/packaging';

const STATUS = {
  'Belum Diterima': '#eab308',
  'Sebagian': '#3b82f6',
  'Selesai': '#22c55e',
  'Draft': '#8b93a1',
  'Menunggu': '#eab308',
  'Dikirim': '#3b82f6',
  'Diterima': '#22c55e',
  'Dibatalkan': '#ef4444',
  'Diterima Sebagian · Sisa Dibatalkan': '#f97316',
};

const newRow = () => ({ productId: '', inputMode: 'QTY', inputValue: 1, qty: 1 });

const PurchaseOrder = () => {
  const { purchaseOrders, suppliers, products, addPO, cancelPurchaseOrder, canManageMasterData } = useData();
  const [modal, setModal] = useState(false);
  const [unloadingPo, setUnloadingPo] = useState(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ supplier: '', no: '', items: [newRow()] });

  const setItem = (index, patch) => {
    setForm((prev) => ({
      ...prev,
      items: prev.items.map((item, i) => {
        if (i !== index) return item;
        const next = { ...item, ...patch };
        const product = products.find((candidate) => candidate.id === next.productId);
        return { ...next, qty: quantityFromInput(next.inputValue, next.inputMode, product) };
      }),
    }));
  };

  const addItem = () => setForm((prev) => ({ ...prev, items: [...prev.items, newRow()] }));
  const removeItem = (index) => setForm((prev) => ({
    ...prev,
    items: prev.items.length === 1 ? prev.items : prev.items.filter((_, i) => i !== index),
  }));

  const selectedItems = useMemo(() => form.items.map((item) => ({
    ...item,
    product: products.find((p) => p.id === item.productId),
  })), [form.items, products]);

  const total = selectedItems.reduce((sum, item) => sum + (item.product?.cost || 0) * Number(item.qty || 0), 0);

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));

  const printUnloadingDay = (po, day, recipient) => {
    const key = recipient === 'BURUH' ? 'labor' : 'daily';
    const title = recipient === 'BURUH' ? 'REKAP UPAH BURUH BONGKAR' : 'REKAP UH GUDANG BONGKAR';
    const items = (day.items || []).filter((item) => Number(item.cost?.[key] || 0) > 0);
    const rows = items.map((item, index) => `<tr><td>${index + 1}</td><td><b>${escapeHtml(item.product)}</b><br/><small>${escapeHtml(item.group)} · ${escapeHtml(formatNum(item.qty))} ${escapeHtml(item.unit)}${item.cost?.overtime ? ' · Lembur' : ''}${item.cost?.holiday ? ' · Hari Libur' : ''}</small></td><td class="r">Rp ${escapeHtml(formatNum(item.cost?.[key] || 0))}</td></tr>`).join('');
    const totalAmount = items.reduce((sum, item) => sum + Number(item.cost?.[key] || 0), 0);
    const w = window.open('', '_blank', 'width=460,height=720');
    if (!w) return toast.error('Izinkan popup untuk mencetak rekap thermal.');
    w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${title}</title><style>@page{size:80mm auto;margin:3mm}*{box-sizing:border-box}body{width:74mm;margin:0 auto;color:#000;font:12px/1.35 Arial,sans-serif}.center{text-align:center}.title{font-size:15px;font-weight:900;margin:6px 0}.sub{font-size:11px;margin-bottom:8px}table{width:100%;border-collapse:collapse;font-size:11px}th,td{border-bottom:1px dashed #000;padding:6px 2px;text-align:left;vertical-align:top}.r{text-align:right;font-weight:700}.total{font-size:17px;font-weight:900;margin:12px 0}.line{border-top:1px solid #000;margin-top:38px;padding-top:5px;text-align:center;font-size:11px;font-weight:700}small{font-size:9px}</style></head><body><div class="center"><b>PERUM BULOG</b><div>Gudang Sunter Timur I & II</div><div class="title">${title}</div><div class="sub">PO: ${escapeHtml(po.no)}<br/>Supplier: ${escapeHtml(po.supplier)}<br/>Tanggal: ${escapeHtml(day.date)}</div></div><table><thead><tr><th>No</th><th>Komoditi</th><th class="r">Biaya</th></tr></thead><tbody>${rows || '<tr><td colspan="3">Tidak ada biaya</td></tr>'}</tbody></table><div class="total">TOTAL: Rp ${escapeHtml(formatNum(totalAmount))}</div><div class="line">Petugas Gudang</div><div class="line">Penerima ${recipient === 'BURUH' ? 'Buruh' : 'UH Gudang'}</div><script>window.onload=()=>window.print()</script></body></html>`);
    w.document.close();
  };

  const cancelRemaining = async (po) => {
    const reason = window.prompt(`Alasan pembatalan sisa PO ${po.no}:`);
    if (reason === null) return;
    if (reason.trim().length < 3) return toast.error('Alasan pembatalan minimal 3 karakter');
    try {
      await cancelPurchaseOrder(po.id, { reason: reason.trim() });
      toast.success(`Sisa PO ${po.no} dibatalkan dan riwayat tersimpan`);
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  const save = async () => {
    if (!form.supplier) {
      toast.error('Pilih supplier');
      return;
    }
    if (selectedItems.some((item) => !item.product || Number(item.qty) <= 0)) {
      toast.error('Lengkapi produk dan jumlah pesanan');
      return;
    }
    if (selectedItems.some((item) => !quantityIsValid(item.qty, item.product))) {
      toast.error('Berat harus menghasilkan jumlah kemasan primer/pack yang utuh');
      return;
    }
    const ids = selectedItems.map((item) => item.productId);
    if (new Set(ids).size !== ids.length) {
      toast.error('Produk yang sama tidak boleh ditambahkan dua kali');
      return;
    }
    if (saving) return;

    setSaving(true);
    try {
      await addPO({
        supplier: form.supplier,
        no: form.no.trim(),
        date: new Date().toISOString(),
        items: selectedItems.map((item) => ({ productId: item.productId, qty: Number(item.qty) })),
      });
      toast.success('Purchase Order dibuat. Stok belum berubah sampai barang diterima.');
      setModal(false);
      setForm({ supplier: '', no: '', items: [newRow()] });
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Pengadaan</div>
          <h1 className="font-display text-4xl font-bold">Purchase Order</h1>
          <p className="text-[#8b93a1] mt-2">{purchaseOrders.length} PO tercatat · PO adalah pesanan, bukan stok fisik</p>
        </div>
        {canManageMasterData && <button data-testid="create-po-btn" onClick={() => setModal(true)} className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg"><Plus size={15} /> Buat PO Baru</button>}
      </div>

      <div className="card-surface p-6">
        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['No. PO', 'Tanggal', 'Supplier', 'Barang Dipesan', 'Progres Penerimaan', 'Total Nilai', 'Biaya Bongkar', 'Status', ...(canManageMasterData ? ['Aksi'] : [])].map((h) => <th key={h} className="py-2.5 pr-4 font-semibold whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {purchaseOrders.length === 0 ? <tr><td colSpan={canManageMasterData ? 9 : 8} className="py-8 text-center text-[#6b7688]">Belum ada PO. Buat PO baru untuk mencatat rencana pengadaan.</td></tr> : purchaseOrders.map((po) => {
                const ordered = (po.items || []).reduce((a, it) => a + Number(it.qty || 0), 0);
                const received = (po.items || []).reduce((a, it) => a + Number(it.receivedQty || 0), 0);
                const pct = ordered > 0 ? Math.min((received / ordered) * 100, 100) : 0;
                const color = STATUS[po.status] || '#8b93a1';
                return (
                  <tr key={po.id} className="tbl-row border-b border-[#131a24] align-top">
                    <td className="py-3 pr-4 font-mono text-xs">{po.no}</td>
                    <td className="py-3 pr-4 whitespace-nowrap text-[#8b93a1]">{formatDate(po.date)}</td>
                    <td className="py-3 pr-4 text-[#c7d0dc]">{po.supplier}</td>
                    <td className="py-3 pr-4 text-xs min-w-[260px]">
                      {(po.items || []).map((it, i) => (
                        <div key={i} className="mb-1.5 last:mb-0">
                          <div>{it.name} × <span className="font-mono">{formatNum(it.qty)} {it.unit || ''}</span></div>
                          {(packagingText(it.qty, it, formatNum) || Number(it.weight || 0) > 0) && <div className="text-[#7892b5]">{packagingText(it.qty, it, formatNum)}{packagingText(it.qty, it, formatNum) && Number(it.weight || 0) > 0 ? ' · ' : ''}{Number(it.weight || 0) > 0 ? `${formatNum(totalWeight(it.qty, it))} kg` : ''}</div>}
                          <div className="text-[#6b7688]">Diterima {formatNum(it.receivedQty || 0)} · Sisa {formatNum(Math.max(Number(it.qty || 0) - Number(it.receivedQty || 0) - Number(it.cancelledQty || 0), 0))} {it.unit || ''}{Number(it.cancelledQty || 0) > 0 ? ` · Dibatalkan ${formatNum(it.cancelledQty)}` : ''}</div>
                        </div>
                      ))}
                    </td>
                    <td className="py-3 pr-4 min-w-[170px]">
                      <div className="flex justify-between text-xs mb-1.5"><span>{formatNum(received)}</span><span>{formatNum(ordered)}</span></div>
                      <div className="h-2 rounded-full bg-[#151d28] overflow-hidden"><div className="h-full rounded-full bg-[#2563eb]" style={{ width: `${pct}%` }} /></div>
                      <div className="text-[10px] text-[#6b7688] mt-1">{pct.toFixed(0)}% diterima</div>
                    </td>
                    <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatRp(po.total)}</td>
                    <td className="py-3 pr-4 min-w-[180px]">
                      {Number(po.unloadingSummary?.totals?.total || 0) > 0 ? <div>
                        <div className="font-mono font-semibold text-[#fbbf24]">{formatRp(po.unloadingSummary.totals.total)}</div>
                        <div className="text-[10px] text-[#6b7688] mt-1">Buruh {formatRp(po.unloadingSummary.totals.labor)} · UH {formatRp(po.unloadingSummary.totals.daily)} · Gudang {formatRp(po.unloadingSummary.totals.warehouse)}</div>
                        <button onClick={() => setUnloadingPo(po)} className="mt-2 inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border border-[#8a5a16] text-[#fbbf24] hover:bg-[#f59e0b]/10"><DollarSign size={12} /> Lihat Rekap</button>
                      </div> : <span className="text-xs text-[#6b7688]">Belum ada biaya bongkar</span>}
                    </td>
                    <td className="py-3 pr-4"><span className="text-xs px-2.5 py-1 rounded-full font-medium whitespace-nowrap" style={{ background: `${color}22`, color }}>{po.status}</span></td>
                    {canManageMasterData && <td className="py-3 pr-4">{!['Selesai', 'Dibatalkan', 'Diterima Sebagian · Sisa Dibatalkan'].includes(po.status) && <button onClick={() => cancelRemaining(po)} className="text-xs px-3 py-2 rounded-lg border border-[#ef4444] text-[#f87171] hover:bg-[#ef4444]/10">Batalkan Sisa</button>}</td>}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {unloadingPo && createPortal(
        <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/75 p-4 sm:p-6 overflow-y-auto">
          <div className="card-surface w-full max-w-3xl p-6 fade-up max-h-[calc(100dvh-3rem)] overflow-y-auto">
            <div className="flex items-start justify-between gap-3 mb-5">
              <div>
                <div className="label-mono text-[10px] text-[#fbbf24]">Rekap PO</div>
                <h2 className="font-display text-xl font-bold mt-1">Biaya Bongkar · {unloadingPo.no}</h2>
                <p className="text-xs text-[#8b93a1] mt-1">{unloadingPo.supplier} · rekap mengikuti tanggal penerimaan barang.</p>
              </div>
              <button onClick={() => setUnloadingPo(null)} className="text-[#8b93a1] hover:text-white"><X size={20} /></button>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mb-5">
              {[['Buruh', 'labor'], ['UH Gudang', 'daily'], ['Dana Gudang', 'warehouse'], ['Total', 'total'], ['Tagihan Pengirim', 'chargeable']].map(([label, key]) => <div key={key} className="rounded-lg border border-[#2b3545] bg-[#0b0f17] p-3"><div className="text-[10px] text-[#8b93a1]">{label}</div><div className="font-mono text-sm font-bold mt-1 text-[#fbbf24]">{formatRp(unloadingPo.unloadingSummary?.totals?.[key] || 0)}</div></div>)}
            </div>

            <div className="space-y-4">
              {(unloadingPo.unloadingSummary?.days || []).length === 0 ? <div className="rounded-lg border border-[#242f3d] p-5 text-center text-sm text-[#6b7688]">Belum ada penerimaan dengan biaya bongkar untuk PO ini.</div> : (unloadingPo.unloadingSummary?.days || []).map((day) => (
                <div key={day.date} className="rounded-xl border border-[#2b3545] bg-[#0b0f17] p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold">{day.date}</div>
                      <div className="text-xs text-[#8b93a1] mt-1">Total {formatRp(day.totals?.total || 0)} · Tagihan pengirim {formatRp(day.totals?.chargeable || 0)}</div>
                    </div>
                    <div className="flex gap-2">
                      <button onClick={() => printUnloadingDay(unloadingPo, day, 'BURUH')} className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-[#294263] text-[#93c5fd]"><Printer size={12} /> Buruh 80mm</button>
                      <button onClick={() => printUnloadingDay(unloadingPo, day, 'HARIAN')} className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-[#294263] text-[#93c5fd]"><Printer size={12} /> UH 80mm</button>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mt-3">
                    {Object.entries(day.groups || {}).map(([group, values]) => <div key={group} className="rounded-lg border border-[#202a38] p-3"><div className="text-[10px] text-[#8b93a1]">{group}</div><div className="mt-1 text-xs">Buruh <b className="font-mono">{formatRp(values.labor || 0)}</b></div><div className="text-xs">UH <b className="font-mono">{formatRp(values.daily || 0)}</b></div><div className="text-xs">Gudang <b className="font-mono">{formatRp(values.warehouse || 0)}</b></div></div>)}
                  </div>

                  <div className="overflow-x-auto mt-3">
                    <table className="w-full text-xs">
                      <thead><tr className="text-left border-b border-[#242f3d]"><th className="py-2 pr-3">Komoditi</th><th className="py-2 pr-3">Kuantitas</th><th className="py-2 pr-3">Grup</th><th className="py-2 text-right">Biaya</th></tr></thead>
                      <tbody>{(day.items || []).map((item, index) => <tr key={`${day.date}-${index}`} className="border-b border-[#171e29]"><td className="py-2 pr-3"><div className="font-medium">{item.product}</div><div className="text-[10px] text-[#6b7688]">{item.ref}{item.cost?.overtime ? ' · Lembur' : ''}{item.cost?.holiday ? ' · Hari Libur' : ''}</div></td><td className="py-2 pr-3 font-mono">{formatNum(item.qty)} {item.unit}</td><td className="py-2 pr-3">{item.group}</td><td className="py-2 text-right font-mono">{formatRp(item.cost?.total || 0)}</td></tr>)}</tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>,
        document.body
      )}

      {modal && createPortal(
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-4 sm:p-6 overflow-y-auto">
          <div className="card-surface w-full max-w-2xl p-6 fade-up max-h-[calc(100dvh-3rem)] overflow-y-auto">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="font-display text-xl font-bold">Buat Purchase Order</h2>
                <p className="text-xs text-[#6b7688] mt-1">Jumlah di PO adalah jumlah yang dipesan dan tidak menambah stok.</p>
              </div>
              <button onClick={() => !saving && setModal(false)} disabled={saving} className="text-[#8b93a1] hover:text-white disabled:opacity-50"><X size={20} /></button>
            </div>

            <div className="space-y-5">
              <div>
                <label className="text-xs font-medium mb-1 block text-[#8b93a1]">Nomor PO</label>
                <input value={form.no || ''} onChange={(e) => setForm((prev) => ({ ...prev, no: e.target.value }))} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" placeholder="Tulis nomor PO manual (opsional)" />
                <p className="mt-1 text-xs text-[#6b7688]">Kosongkan bila ingin nomor dibuat otomatis.</p>
              </div>
              <div>
                <label className="text-xs font-medium mb-1 block text-[#8b93a1]">Supplier</label>
                <select data-testid="po-supplier-select" value={form.supplier} onChange={(e) => setForm((prev) => ({ ...prev, supplier: e.target.value }))} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]">
                  <option value="">Pilih supplier...</option>
                  {suppliers.map((supplier) => <option key={supplier.id}>{supplier.name}</option>)}
                </select>
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs font-medium text-[#8b93a1]">Daftar Barang</label>
                  <button type="button" onClick={addItem} className="inline-flex items-center gap-1.5 text-xs text-[#60a5fa] hover:text-[#93c5fd]"><Plus size={13} /> Tambah Barang</button>
                </div>
                <div className="space-y-3">
                  {selectedItems.map((item, index) => (
                    <div key={index} className="grid grid-cols-1 sm:grid-cols-[minmax(180px,1fr)_105px_145px_40px] gap-2 items-end p-3 rounded-lg bg-[#0b0f17] border border-[#1a222e]">
                      <div>
                        <label className="text-[10px] text-[#6b7688] mb-1 block">Produk</label>
                        <select data-testid={`po-product-select-${index}`} value={item.productId} onChange={(e) => setItem(index, { productId: e.target.value, inputMode: 'QTY', inputValue: 1 })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]">
                          <option value="">Pilih produk...</option>
                          {products.map((product) => <option key={product.id} value={product.id}>{product.name} ({product.sku})</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="text-[10px] text-[#6b7688] mb-1 block">Input Berdasarkan</label>
                        <select value={item.inputMode || 'QTY'} onChange={(e) => setItem(index, { inputMode: e.target.value, inputValue: e.target.value === 'WEIGHT' ? totalWeight(item.qty, item.product) : item.qty })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2.5 text-xs outline-none focus:border-[#2563eb]">
                          <option value="QTY">Jumlah</option>
                          <option value="WEIGHT" disabled={!Number(item.product?.weight || 0)}>Berat</option>
                        </select>
                      </div>
                      <div>
                        <label className="text-[10px] text-[#6b7688] mb-1 block">{item.inputMode === 'WEIGHT' ? 'Berat Pesanan (kg)' : `Jumlah (${item.product?.unit || 'unit'})`}</label>
                        <input data-testid={`po-qty-input-${index}`} type="number" min="0.01" step="any" value={item.inputValue} onChange={(e) => setItem(index, { inputValue: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" />
                      </div>
                      <button type="button" title="Hapus barang" onClick={() => removeItem(index)} className="w-10 h-[42px] rounded-lg border border-[#242f3d] flex items-center justify-center text-[#ef4444] hover:bg-[#ef4444]/10"><Trash2 size={15} /></button>
                      {item.product && Number(item.qty || 0) > 0 && <div className="sm:col-span-4 text-[10px] text-[#60a5fa]">{formatNum(item.qty)} {item.product.unit} · {formatNum(totalWeight(item.qty, item.product))} kg{packagingText(item.qty, item.product, formatNum) ? ` · ${packagingText(item.qty, item.product, formatNum)}` : ''}</div>}
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-lg border border-[#1a222e] bg-[#0b0f17] p-4 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-sm text-[#aab4c4]"><PackageCheck size={16} className="text-[#60a5fa]" /> Estimasi nilai PO</div>
                <div className="font-mono font-semibold">{formatRp(total)}</div>
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-6">
              <button onClick={() => setModal(false)} disabled={saving} className="px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm hover:bg-[#141a24] disabled:opacity-50">Batal</button>
              <button data-testid="po-save-btn" onClick={save} disabled={saving} className="btn-primary px-5 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-60 disabled:cursor-wait">{saving ? 'Menyimpan…' : 'Simpan PO'}</button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};

export default PurchaseOrder;
