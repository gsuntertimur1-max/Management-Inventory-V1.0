import React, { useMemo, useState } from 'react';
import { Boxes, Download, FileText, MapPin, PackageSearch, Pencil, Plus, Save, Trash2, Warehouse, X } from 'lucide-react';
import { toast } from 'sonner';
import { useData } from '../context/DataContext';
import { formatNum } from '../mock';
import { apiError, downloadApiFile } from '../lib/api';
import { hasPermission } from '../lib/permissions';

const inputCls = 'w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';

const primaryFromLayout = (layout) => {
  if (!layout) return 0;
  if (layout.primaryQty !== undefined && layout.primaryQty !== null) return Number(layout.primaryQty || 0);
  const secondaryCount = (layout.arrangements || []).reduce(
    (sum, row) => sum + Number(row.hamparan || 0) * Number(row.kaki || 0) * Number(row.height || 0),
    0,
  ) + Number(layout.extraSecondary || 0);
  return secondaryCount * Number(layout.secondaryQty || 0) + Number(layout.extraPrimary || 0);
};

const arrangementText = (layout, secondary, secondaryQty) => {
  if (!layout) return 'Perkalian belum dicatat';
  if (layout.arrangementAdjusted) return `Perlu dihitung ulang · saldo tumpukan ${formatNum(primaryFromLayout(layout))} primer`;
  const rows = layout.arrangements || [];
  const secondaryCount = rows.reduce((sum, row) => sum + Number(row.hamparan || 0) * Number(row.kaki || 0) * Number(row.height || 0), 0) + Number(layout.extraSecondary || 0);
  const primary = secondaryCount * Number(layout.secondaryQty ?? secondaryQty ?? 0) + Number(layout.extraPrimary || 0);
  const detail = rows.map((row) => `${row.hamparan}×${row.kaki}×${row.height}`).join(' + ');
  return `${detail || '0'}${Number(layout.extraSecondary || 0) ? ` + ${formatNum(layout.extraSecondary)} ${layout.secondary || secondary || 'sekunder'}` : ''}${Number(layout.extraPrimary || 0) ? ` + ${formatNum(layout.extraPrimary)} primer` : ''} = ${formatNum(primary)} primer`;
};

const emptyForm = (prefix) => ({
  productId: '',
  stackSuffix: 'A01',
  arrangements: [{ hamparan: '', kaki: '', height: '' }],
  extraSecondary: '',
  extraPrimary: '',
  note: '',
  editingId: '',
  prefix,
});

const ConsignmentLocationMap = ({ destination }) => {
  const {
    user,
    consignmentStock,
    consignmentLayouts,
    outboundLoads,
    saveConsignmentLayout,
    deleteConsignmentLayout,
  } = useData();
  const prefix = destination === 'Gudang Bazar' ? 'BZR' : 'ECOM';
  const permission = destination === 'Gudang Bazar' ? 'bazarOps' : 'ecomOps';
  const canEdit = hasPermission(user?.role, permission);
  const [form, setForm] = useState(() => emptyForm(prefix));
  const [saving, setSaving] = useState(false);
  const [printing, setPrinting] = useState('');

  const rows = useMemo(
    () => (consignmentStock || []).filter((item) => item.destination === destination).sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'id')),
    [consignmentStock, destination],
  );
  const layouts = useMemo(
    () => (consignmentLayouts || [])
      .filter((item) => item.destination === destination)
      .map((item) => ({ ...item, stackCode: item.stackCode || `${prefix}/A01` }))
      .sort((a, b) => String(a.stackCode).localeCompare(String(b.stackCode)) || String(a.productName || '').localeCompare(String(b.productName || ''), 'id')),
    [consignmentLayouts, destination, prefix],
  );

  const sourceStacks = useMemo(() => {
    const result = {};
    (outboundLoads || [])
      .filter((load) => load.status === 'Selesai' && load.consignment_destination === destination)
      .forEach((load) => (load.items || []).forEach((item) => {
        if (!item.productId) return;
        const stack = item.stackCode || item.location;
        if (!stack) return;
        result[item.productId] = result[item.productId] || [];
        if (!result[item.productId].includes(stack)) result[item.productId].push(stack);
      }));
    return result;
  }, [outboundLoads, destination]);

  const stockByProduct = useMemo(() => Object.fromEntries(rows.map((row) => [row.productId, row])), [rows]);
  const allocatedByProduct = useMemo(() => {
    const result = {};
    layouts.forEach((layout) => {
      result[layout.productId] = Number(result[layout.productId] || 0) + primaryFromLayout(layout);
    });
    return result;
  }, [layouts]);

  const stacks = useMemo(() => {
    const grouped = {};
    layouts.forEach((layout) => {
      grouped[layout.stackCode] = grouped[layout.stackCode] || [];
      grouped[layout.stackCode].push(layout);
    });
    return Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b));
  }, [layouts]);

  const totalPrimary = rows.reduce((sum, row) => sum + Number(row.qty || 0), 0);
  const totalWeight = rows.reduce((sum, row) => sum + Number(row.totalWeight || 0), 0);
  const totalAllocated = layouts.reduce((sum, row) => sum + primaryFromLayout(row), 0);
  const label = destination === 'Gudang Bazar' ? 'BAZAR' : 'E-COMMERCE';

  const resetForm = () => setForm(emptyForm(prefix));

  const editLayout = (layout) => {
    setForm({
      productId: layout.productId || '',
      stackSuffix: String(layout.stackCode || `${prefix}/A01`).split('/')[1] || 'A01',
      arrangements: (layout.arrangements || []).length
        ? layout.arrangements.map((row) => ({ hamparan: row.hamparan, kaki: row.kaki, height: row.height }))
        : [{ hamparan: '', kaki: '', height: '' }],
      extraSecondary: layout.extraSecondary || '',
      extraPrimary: layout.extraPrimary || '',
      note: layout.note || '',
      editingId: layout.id || '',
      prefix,
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const updateArrangement = (index, key, value) => {
    setForm((prev) => ({
      ...prev,
      arrangements: prev.arrangements.map((row, rowIndex) => rowIndex === index ? { ...row, [key]: value } : row),
    }));
  };

  const save = async () => {
    if (!form.productId) return toast.error('Pilih komoditi yang akan dihitung');
    const suffix = String(form.stackSuffix || '').trim().toUpperCase();
    if (!suffix) return toast.error('Isi kode tumpukan, contoh A01');
    const arrangements = form.arrangements
      .map((row) => ({ hamparan: Number(row.hamparan || 0), kaki: Number(row.kaki || 0), height: Number(row.height || 0) }))
      .filter((row) => row.hamparan > 0 && row.kaki > 0 && row.height > 0);
    if (!arrangements.length && Number(form.extraSecondary || 0) <= 0 && Number(form.extraPrimary || 0) <= 0) {
      return toast.error('Isi perkalian Hamparan × Kaki × Tinggi atau jumlah tambahan');
    }
    setSaving(true);
    try {
      if (form.editingId) {
        const current = layouts.find((layout) => layout.id === form.editingId);
        const nextCode = `${prefix}/${suffix}`;
        if (current && current.stackCode !== nextCode) {
          await deleteConsignmentLayout(current.id);
        }
      }
      await saveConsignmentLayout({
        destination,
        productId: form.productId,
        stackCode: `${prefix}/${suffix}`,
        arrangements,
        extraSecondary: Number(form.extraSecondary || 0),
        extraPrimary: Number(form.extraPrimary || 0),
        note: form.note || '',
      });
      toast.success(`Perkalian tumpukan ${prefix}/${suffix} tersimpan`);
      resetForm();
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setSaving(false);
    }
  };

  const removeLayout = async (layout) => {
    if (!window.confirm(`Hapus perkalian ${layout.stackCode} untuk ${layout.productName || 'komoditi ini'}?`)) return;
    try {
      await deleteConsignmentLayout(layout.id);
      toast.success('Perkalian tumpukan dihapus');
      if (form.editingId === layout.id) resetForm();
    } catch (error) {
      toast.error(apiError(error));
    }
  };

  const printStack = async (stackCode) => {
    setPrinting(stackCode);
    try {
      await downloadApiFile(
        `/export/consignment-stack-card.pdf?stackCode=${encodeURIComponent(stackCode)}`,
        `kartu_tumpukan_${stackCode.replace('/', '-')}.pdf`,
      );
      toast.success(`Kartu tumpukan ${stackCode} berhasil dibuat`);
    } catch (error) {
      toast.error(apiError(error));
    } finally {
      setPrinting('');
    }
  };

  return <div className="space-y-5" data-testid={`consignment-map-${label.toLowerCase()}`}>
    <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
      <div className="card-surface p-4"><div className="label-mono">Lokasi</div><div className="font-display text-xl font-bold mt-2 flex items-center gap-2"><MapPin size={18} className="text-[#60a5fa]" />{destination}</div></div>
      <div className="card-surface p-4"><div className="label-mono">Produk Aktif</div><div className="font-display text-2xl font-bold mt-2">{rows.length}</div><div className="text-xs text-[#8b93a1] mt-1">SKU dengan saldo sub-ledger</div></div>
      <div className="card-surface p-4"><div className="label-mono">Saldo Primer</div><div className="font-display text-2xl font-bold mt-2">{formatNum(totalPrimary)}</div><div className="text-xs text-[#8b93a1] mt-1">Fisik {formatNum(totalWeight)}</div></div>
      <div className="card-surface p-4"><div className="label-mono">Terpetakan di Tumpukan</div><div className="font-display text-2xl font-bold mt-2">{formatNum(totalAllocated)}</div><div className="text-xs text-[#8b93a1] mt-1">{stacks.length} kode tumpukan</div></div>
    </div>

    {canEdit && <section className="card-surface p-4 md:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div><h2 className="font-display text-xl font-bold">{form.editingId ? 'Ubah Perkalian Tumpukan' : 'Input Perkalian Tumpukan'}</h2><p className="text-xs text-[#8b93a1] mt-1">Kode lokasi terpisah dari gudang induk. Gunakan {prefix}/A01, {prefix}/A02, dan seterusnya.</p></div>
        {form.editingId && <button onClick={resetForm} className="inline-flex items-center gap-1 text-xs px-3 py-2 rounded-lg border border-[#334155] text-[#cbd5e1]"><X size={13}/> Batal Edit</button>}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-[180px_1fr] gap-3">
        <div>
          <label className="text-xs text-[#8b93a1] block mb-1">Kode Tumpukan</label>
          <div className="flex"><div className="rounded-l-lg border border-r-0 border-[#242f3d] bg-[#111827] px-3 py-2.5 text-sm font-mono text-[#93c5fd]">{prefix}/</div><input className={inputCls + ' rounded-l-none font-mono'} value={form.stackSuffix} onChange={(e) => setForm({ ...form, stackSuffix: e.target.value.toUpperCase() })} placeholder="A01"/></div>
        </div>
        <div>
          <label className="text-xs text-[#8b93a1] block mb-1">Komoditi</label>
          <select className={inputCls} value={form.productId} onChange={(e) => setForm({ ...form, productId: e.target.value })}>
            <option value="">Pilih komoditi</option>
            {rows.map((item) => <option key={item.productId} value={item.productId}>{item.name} · saldo {formatNum(item.qty)} {item.unit} · belum terpetakan {formatNum(Math.max(Number(item.qty || 0) - Number(allocatedByProduct[item.productId] || 0), 0))}</option>)}
          </select>
        </div>
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between gap-3 mb-2"><div className="text-xs font-semibold">Susunan Hamparan × Kaki × Tinggi</div><button type="button" onClick={() => setForm((prev) => ({ ...prev, arrangements: [...prev.arrangements, { hamparan: '', kaki: '', height: '' }] }))} disabled={form.arrangements.length >= 10} className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-[#2563eb] text-[#93c5fd] disabled:opacity-40"><Plus size={12}/> Tambah Susunan</button></div>
        <div className="space-y-2">{form.arrangements.map((row, index) => <div key={index} className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2">
          <input type="number" min="1" className={inputCls} placeholder="Hamparan" value={row.hamparan} onChange={(e) => updateArrangement(index, 'hamparan', e.target.value)}/>
          <input type="number" min="1" className={inputCls} placeholder="Kaki" value={row.kaki} onChange={(e) => updateArrangement(index, 'kaki', e.target.value)}/>
          <input type="number" min="1" className={inputCls} placeholder="Tinggi" value={row.height} onChange={(e) => updateArrangement(index, 'height', e.target.value)}/>
          <button type="button" onClick={() => setForm((prev) => ({ ...prev, arrangements: prev.arrangements.length === 1 ? [{ hamparan: '', kaki: '', height: '' }] : prev.arrangements.filter((_, i) => i !== index) }))} className="px-3 rounded-lg border border-[#7f1d1d] text-[#fca5a5]"><Trash2 size={15}/></button>
        </div>)}</div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-3">
        <div><label className="text-xs text-[#8b93a1] block mb-1">Tambahan kemasan sekunder</label><input type="number" min="0" className={inputCls} value={form.extraSecondary} onChange={(e) => setForm({ ...form, extraSecondary: e.target.value })} placeholder="0"/></div>
        <div><label className="text-xs text-[#8b93a1] block mb-1">Primer lepas</label><input type="number" min="0" className={inputCls} value={form.extraPrimary} onChange={(e) => setForm({ ...form, extraPrimary: e.target.value })} placeholder="0"/></div>
        <div><label className="text-xs text-[#8b93a1] block mb-1">Catatan</label><input className={inputCls} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="Opsional"/></div>
      </div>
      <button disabled={saving} onClick={save} className="btn-primary mt-4 inline-flex items-center gap-2 px-5 py-2.5 rounded-lg font-semibold disabled:opacity-50"><Save size={16}/>{saving ? 'Menyimpan…' : 'Simpan Perkalian'}</button>
    </section>}

    <section className="card-surface p-4 md:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div><h2 className="font-display text-xl font-bold">Tumpukan Persediaan {label}</h2><p className="text-xs text-[#8b93a1] mt-1">Saldo dan perkalian ini hanya milik {destination}; tidak menambah atau mengurangi alokasi tumpukan GBB/MP1 gudang induk.</p></div>
        <div className="inline-flex items-center gap-2 rounded-lg border border-[#334155] px-3 py-2 text-xs text-[#93c5fd]"><Warehouse size={15} />Sub-ledger mandiri {label}</div>
      </div>

      {rows.length === 0 ? <div className="rounded-xl border border-dashed border-[#334155] p-10 text-center text-sm text-[#8b93a1]"><PackageSearch size={28} className="mx-auto mb-3 opacity-60" />Belum ada stok aktif di {destination}.</div> : <>
        {stacks.length === 0 && <div className="rounded-xl border border-dashed border-[#334155] p-6 text-center text-sm text-[#8b93a1]">Belum ada perkalian tumpukan. {canEdit ? `Mulai dari ${prefix}/A01 di formulir di atas.` : 'Petugas operasional belum mencatat perkalian.'}</div>}
        <div className="space-y-4">
          {stacks.map(([stackCode, stackLayouts]) => <div key={stackCode} className="rounded-xl border border-[#334155] bg-[#111827]/40 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
              <div><div className="font-display font-bold text-lg">{stackCode}</div><div className="text-xs text-[#8b93a1]">{stackLayouts.length} komoditi</div></div>
              <button disabled={printing === stackCode} onClick={() => printStack(stackCode)} className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-[#2563eb] text-[#93c5fd] text-xs font-semibold disabled:opacity-50"><Download size={14}/>{printing === stackCode ? 'Menyiapkan…' : 'Cetak Kartu Tumpukan'}</button>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {stackLayouts.map((layout) => {
                const item = stockByProduct[layout.productId] || {};
                const origins = sourceStacks[layout.productId] || [];
                return <div key={layout.id || `${stackCode}-${layout.productId}`} className="rounded-lg border border-[#243044] p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div><div className="font-semibold">{layout.productName || item.name || 'Komoditi'}</div><div className="font-mono text-[10px] text-[#93c5fd] mt-1">{layout.sku || item.sku || '—'} · {item.channel || 'KOM'}</div></div>
                    <Boxes size={17} className="text-[#60a5fa]"/>
                  </div>
                  <div className="grid grid-cols-2 gap-2 mt-3 text-xs"><div className="rounded-lg bg-[#0f172a] p-2"><span className="text-[#8b93a1]">Dalam tumpukan</span><div className="font-mono font-bold mt-1">{formatNum(primaryFromLayout(layout))} {layout.unit || item.unit || ''}</div></div><div className="rounded-lg bg-[#0f172a] p-2"><span className="text-[#8b93a1]">Saldo area</span><div className="font-mono font-bold mt-1">{formatNum(item.qty || 0)} {item.unit || ''}</div></div></div>
                  <div className="mt-3 text-xs"><div className="text-[#8b93a1]">Perkalian</div><div className={`font-mono text-[11px] mt-1 ${layout.arrangementAdjusted ? 'text-[#fbbf24]' : 'text-[#d9e3ef]'}`}>{arrangementText(layout, item.secondary, item.secondaryQty)}</div></div>
                  <div className="mt-3 pt-3 border-t border-[#243044] text-[11px] text-[#8b93a1]"><div className="flex gap-2"><MapPin size={12} className="mt-0.5 shrink-0"/><span>Asal gudang induk: {origins.length ? origins.join(', ') : 'data lama / tidak tercatat'}</span></div><div className="flex gap-2 mt-1"><FileText size={12} className="mt-0.5 shrink-0"/><span>Dokumen: {(item.documents || []).join(', ') || '—'}</span></div></div>
                  {canEdit && <div className="flex gap-2 mt-3"><button onClick={() => editLayout(layout)} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-[#334155] text-[#cbd5e1] text-xs"><Pencil size={12}/> Edit</button><button onClick={() => removeLayout(layout)} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-[#7f1d1d] text-[#fca5a5] text-xs"><Trash2 size={12}/> Hapus</button></div>}
                </div>;
              })}
            </div>
          </div>)}
        </div>

        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {rows.filter((item) => Math.max(Number(item.qty || 0) - Number(allocatedByProduct[item.productId] || 0), 0) > 1e-9).map((item) => <div key={item.productId} className="rounded-lg border border-[#8a5a16] bg-[#f59e0b]/5 p-3 text-xs"><div className="font-semibold">{item.name}</div><div className="text-[#fbbf24] mt-1">Belum terpetakan: {formatNum(Math.max(Number(item.qty || 0) - Number(allocatedByProduct[item.productId] || 0), 0))} {item.unit}</div></div>)}
        </div>
      </>}
    </section>
  </div>;
};

export default ConsignmentLocationMap;
