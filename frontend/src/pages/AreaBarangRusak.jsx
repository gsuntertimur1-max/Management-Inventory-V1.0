import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, PackageX, RefreshCcw, Search } from 'lucide-react';
import { toast } from 'sonner';
import api, { apiError } from '../lib/api';
import { formatNum } from '../mock';

const displayTime = (value) => value
  ? new Date(value).toLocaleString('id-ID', { timeZone: 'Asia/Jakarta', dateStyle: 'medium', timeStyle: 'short' })
  : '—';

const AreaBarangRusak = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get('/damaged-stock-area');
      setData(response.data);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const query = q.trim().toLowerCase();
  const poGroups = useMemo(() => (data?.poDamageGroups || []).filter((group) => {
    if (!query) return true;
    return [
      group.poNo,
      group.supplier,
      ...(group.items || []).flatMap((item) => [item.product, item.sku]),
    ].some((value) => String(value || '').toLowerCase().includes(query));
  }), [data, query]);

  const discoveryGroups = useMemo(() => (data?.discoveryDamageGroups || []).filter((row) => {
    if (!query) return true;
    return [row.referenceNo, row.product, row.sku, row.stackCode, row.cause]
      .some((value) => String(value || '').toLowerCase().includes(query));
  }), [data, query]);

  const summary = data?.summary || {};

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Damaged Stock Subledger</div>
          <h1 className="font-display text-4xl font-bold">Area Barang Rusak</h1>
          <p className="text-sm text-[#8b93a1] mt-2">Rusak saat penerimaan dikelompokkan per nomor PO. Temuan kerusakan setelah barang tersimpan tetap dipisahkan.</p>
        </div>
        <button type="button" onClick={load} disabled={loading} className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border border-[#242f3d] text-sm disabled:opacity-50">
          <RefreshCcw size={16} className={loading ? 'animate-spin' : ''} /> Periksa Ulang
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
        <div className="card-surface p-4">
          <div className="label-mono text-[9px]">PO dengan Barang Rusak</div>
          <div className="font-mono text-2xl font-bold mt-1">{summary.poGroups ?? '—'}</div>
        </div>
        <div className="card-surface p-4">
          <div className="label-mono text-[9px]">Temuan Kerusakan Aktif</div>
          <div className="font-mono text-2xl font-bold mt-1">{summary.discoveryOpen ?? '—'}</div>
        </div>
        <div className="card-surface p-4 border border-[#78350f]">
          <div className="label-mono text-[9px] text-[#fcd34d]">Retur Pemasok Terbuka</div>
          <div className="font-mono text-2xl font-bold text-[#fbbf24] mt-1">{summary.openSupplierClaims ?? '—'}</div>
        </div>
        <div className="card-surface p-4 border border-[#7f1d1d]">
          <div className="label-mono text-[9px] text-[#fca5a5]">Mismatch PSO/KOM</div>
          <div className="font-mono text-2xl font-bold text-[#ef4444] mt-1">{summary.productsWithChannelMismatch ?? '—'}</div>
        </div>
      </div>

      {(data?.summaryByUnit || []).length > 0 && (
        <div className="card-surface p-4 flex flex-wrap gap-3 items-center">
          <div className="text-xs text-[#8b93a1] mr-1">Saldo fisik Area Barang Rusak:</div>
          {data.summaryByUnit.map((item) => (
            <div key={item.unit} className="rounded-lg bg-[#0b0f17] border border-[#242f3d] px-3 py-2">
              <span className="font-mono font-semibold">{formatNum(item.qty)}</span>{' '}
              <span className="text-xs text-[#8b93a1]">{item.unit}</span>
            </div>
          ))}
        </div>
      )}

      <div className="relative max-w-xl">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7688]" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Cari nomor PO, supplier, SKU, produk atau temuan..."
          className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg pl-9 pr-3 py-2.5 text-sm"
        />
      </div>

      <div className="card-surface p-5">
        <div className="flex items-center gap-2 mb-1">
          <PackageX size={18} className="text-[#f59e0b]" />
          <h2 className="font-display text-xl font-bold">Rusak Saat Penerimaan PO</h2>
        </div>
        <p className="text-xs text-[#8b93a1] mb-4">Satu baris = satu nomor PO. Kendaraan hanya menjadi rincian audit, bukan dasar penggantian pemasok.</p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead>
              <tr className="text-left border-b border-[#1a222e]">
                {['Nomor PO', 'Supplier', 'Produk & rincian penerimaan', 'Retur / Penggantian'].map((h) => (
                  <th key={h} className="py-2.5 pr-4 whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={4} className="py-10 text-center text-[#8b93a1]">Memuat barang rusak penerimaan...</td></tr>
              ) : poGroups.length === 0 ? (
                <tr><td colSpan={4} className="py-10 text-center text-[#8b93a1]">Belum ada barang rusak dari penerimaan PO yang sesuai.</td></tr>
              ) : poGroups.map((group) => (
                <tr key={group.poNo} className="border-b border-[#131a24] align-top">
                  <td className="py-3 pr-4 font-mono font-semibold whitespace-nowrap">{group.poNo}</td>
                  <td className="py-3 pr-4">{group.supplier || '—'}</td>
                  <td className="py-3 pr-4 min-w-[420px]">
                    <div className="space-y-3">
                      {(group.items || []).map((item) => (
                        <div key={item.productId || item.sku} className="rounded-lg border border-[#242f3d] bg-[#0b0f17] p-3">
                          <div className="flex flex-wrap justify-between gap-2">
                            <div>
                              <div className="font-semibold">{item.product}</div>
                              <div className="label-mono text-[10px]">{item.sku}</div>
                            </div>
                            <div className="font-mono text-[#fca5a5]">Rusak {formatNum(item.totalDamaged)} {item.unit}</div>
                          </div>
                          {(item.details || []).length > 0 && (
                            <div className="mt-2 space-y-1 text-[11px] text-[#8b93a1]">
                              {item.details.map((detail) => (
                                <div key={detail.operationId || `${detail.time}-${detail.polisi}`}>
                                  {detail.loadNo || 'Penerimaan'}{detail.polisi ? ` · ${detail.polisi}` : ''} · {formatNum(detail.qty)} {detail.unit} · {displayTime(detail.time)}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </td>
                  <td className="py-3 pr-4 min-w-[260px]">
                    <div className="space-y-2">
                      {(group.items || []).map((item) => (
                        <div key={item.productId || item.sku} className="text-xs">
                          <div className="font-medium">{item.product}</div>
                          <div className="text-[#8b93a1] mt-1">
                            Belum diretur <span className="font-mono text-[#fbbf24]">{formatNum(item.availableForReturn)}</span> ·
                            Menunggu pengganti <span className="font-mono text-[#93c5fd]">{formatNum(item.pendingReplacement)}</span> {item.unit}
                          </div>
                          <div className="text-[#6b7688]">
                            Retur {formatNum(item.returnedQty)} · Diganti {formatNum(item.replacementQty)}
                          </div>
                        </div>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card-surface p-5 border border-[#7f1d1d]/60">
        <div className="flex items-center gap-2 mb-1">
          <AlertTriangle size={18} className="text-[#f87171]" />
          <h2 className="font-display text-xl font-bold">Temuan Kerusakan</h2>
        </div>
        <p className="text-xs text-[#8b93a1] mb-4">Kerusakan yang ditemukan setelah barang sudah tersimpan. Tidak digabung ke saldo rusak penerimaan PO.</p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead>
              <tr className="text-left border-b border-[#1a222e]">
                {['Waktu', 'Referensi', 'Produk', 'Tumpukan', 'Rusak', 'Belum Diretur', 'Menunggu Pengganti', 'Penyebab'].map((h) => (
                  <th key={h} className="py-2.5 pr-4 whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="py-10 text-center text-[#8b93a1]">Memuat temuan kerusakan...</td></tr>
              ) : discoveryGroups.length === 0 ? (
                <tr><td colSpan={8} className="py-10 text-center text-[#8b93a1]">Belum ada Temuan Kerusakan yang sesuai.</td></tr>
              ) : discoveryGroups.map((row) => (
                <tr key={row.operationId} className="border-b border-[#131a24]">
                  <td className="py-3 pr-4 text-xs whitespace-nowrap">{displayTime(row.time)}</td>
                  <td className="py-3 pr-4 font-mono text-xs">{row.referenceNo || '—'}</td>
                  <td className="py-3 pr-4"><div className="font-medium">{row.product}</div><div className="label-mono text-[10px]">{row.sku}</div></td>
                  <td className="py-3 pr-4 font-mono">{row.stackCode || '—'}</td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(row.totalDamaged)} {row.unit}</td>
                  <td className="py-3 pr-4 font-mono text-[#fbbf24]">{formatNum(row.availableForReturn)}</td>
                  <td className="py-3 pr-4 font-mono text-[#93c5fd]">{formatNum(row.pendingReplacement)}</td>
                  <td className="py-3 pr-4 text-xs">{row.cause || row.note || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card-surface p-5">
        <h2 className="font-display text-lg font-bold mb-4">Pergerakan Barang Rusak Terbaru</h2>
        <div className="overflow-x-auto max-h-[420px]">
          <table className="w-full text-sm tbl">
            <thead className="sticky top-0 bg-[#0d121b]">
              <tr className="text-left border-b border-[#1a222e]">
                {['Waktu', 'Produk', 'Dokumen', 'Perubahan', 'Asal/Lokasi', 'Operator'].map((h) => (
                  <th key={h} className="py-2.5 pr-4 whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data?.recentMovements || []).length === 0 ? (
                <tr><td colSpan={6} className="py-8 text-center text-[#8b93a1]">Belum ada riwayat pergerakan rusak.</td></tr>
              ) : data.recentMovements.map((move) => (
                <tr key={move.id} className="border-b border-[#131a24]">
                  <td className="py-2.5 pr-4 text-xs whitespace-nowrap">{displayTime(move.time)}</td>
                  <td className="py-2.5 pr-4"><div>{move.product}</div><div className="label-mono text-[9px]">{move.sku}</div></td>
                  <td className="py-2.5 pr-4">
                    <div className="font-mono text-xs">{move.poNo || move.ref || '—'}</div>
                    <div className="text-[10px] text-[#6b7688]">{move.documentType || move.type}</div>
                  </td>
                  <td className={`py-2.5 pr-4 font-mono ${Number(move.qty) < 0 ? 'text-[#fca5a5]' : 'text-[#86efac]'}`}>
                    {Number(move.qty) > 0 ? '+' : ''}{formatNum(move.qty)} {move.unit}
                  </td>
                  <td className="py-2.5 pr-4 text-xs">{move.sourceStackCode || move.location || 'AREA BARANG RUSAK'}</td>
                  <td className="py-2.5 pr-4 text-xs">{move.operator || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default AreaBarangRusak;
