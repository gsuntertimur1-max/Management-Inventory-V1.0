import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Download, Filter, History, RefreshCcw, Search } from 'lucide-react';
import api, { apiError } from '../lib/api';
import { toast } from 'sonner';
import { useData } from '../context/DataContext';
import { roleDestination } from '../lib/permissions';
import PaginationControls from '../components/PaginationControls';

const inputCls = 'w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';

const EVENT_LABELS = {
  BAZAR_MUAT: 'Bazar - Muat Kendaraan',
  BAZAR_SELESAI: 'Bazar - Selesai/Rekonsiliasi',
  PAKET_MASTER_DIBUAT: 'Paket - Master Dibuat',
  PAKET_DIRAKIT: 'Paket - Dirakit',
  PAKET_DIBONGKAR: 'Paket - Dibongkar',
  PAKET_DIMUAT: 'Paket - Dimuat',
  PAKET_SELESAI: 'Paket - Selesai/Rekonsiliasi',
  ECOM_RESERVED: 'E-commerce - Reserved',
  ECOM_PACKING: 'E-commerce - Packing',
  ECOM_SHIPPED: 'E-commerce - Dikirim',
  ECOM_CANCELLED: 'E-commerce - Dibatalkan',
  ECOM_RETUR: 'E-commerce - Retur',
};

const monthStart = () => {
  const d = new Date();
  d.setDate(1);
  return d.toISOString().slice(0, 10);
};

const today = () => new Date().toISOString().slice(0, 10);

const qtyText = (item) => {
  const parts = [];
  const unit = item.unit || 'unit';
  if (item.loadedQty !== undefined) parts.push('Muat ' + item.loadedQty + ' ' + unit);
  if (item.qty !== undefined) parts.push('Qty ' + item.qty + ' ' + unit);
  if (item.requiredQty !== undefined) parts.push('Kebutuhan ' + item.requiredQty + ' ' + unit);
  if (item.soldQty !== undefined) parts.push('Terjual ' + item.soldQty + ' ' + unit);
  if (item.deliveredQty !== undefined) parts.push('Disalurkan ' + item.deliveredQty + ' ' + unit);
  if (item.returnedGoodQty !== undefined) parts.push('Retur baik ' + item.returnedGoodQty + ' ' + unit);
  if (item.returnedDamagedQty !== undefined) parts.push('Retur rusak ' + item.returnedDamagedQty + ' ' + unit);
  if (item.goodQty !== undefined) parts.push('Baik ' + item.goodQty + ' ' + unit);
  if (item.damagedQty !== undefined) parts.push('Rusak ' + item.damagedQty + ' ' + unit);
  if (item.packageQty !== undefined) parts.push('Paket ' + item.packageQty);
  return parts.join(' · ') || '—';
};

const RiwayatConsignment = () => {
  const { user } = useData();
  const scopedDestination = roleDestination(user?.role);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({
    destination: scopedDestination || '',
    startDate: monthStart(),
    endDate: today(),
    eventType: '',
    search: '',
  });

  useEffect(() => {
    if (scopedDestination) setFilters((prev) => ({ ...prev, destination: scopedDestination }));
  }, [scopedDestination]);

  const params = useMemo(() => {
    const result = {};
    Object.entries(filters).forEach(([key, value]) => {
      if (String(value || '').trim()) result[key] = String(value).trim();
    });
    if (scopedDestination) result.destination = scopedDestination;
    return result;
  }, [filters, scopedDestination]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/consignment-operation-history', { params });
      setRows(data);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLoading(false);
    }
  }, [params]);

  useEffect(() => { load(); }, [load]);

  const downloadExcel = async () => {
    setDownloading(true);
    try {
      const res = await api.get('/export/consignment-operation-history.xlsx', { params, responseType: 'blob' });
      const blob = new Blob([res.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const disposition = String(res.headers?.['content-disposition'] || '');
      const match = disposition.match(/filename="?([^"]+)"?/i);
      a.href = url;
      a.download = match?.[1] || ('riwayat_bazar_ecom_' + today() + '.xlsx');
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success('Riwayat berhasil diunduh ke Excel');
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setDownloading(false);
    }
  };

  const totalItems = rows.reduce((sum, row) => sum + Math.max((row.items || []).length, 1), 0);
  const pageSize = 10;
  const paginatedRows = rows.slice((page - 1) * pageSize, page * pageSize);

  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(rows.length / pageSize));
    if (page > maxPage) setPage(maxPage);
  }, [rows.length, page]);

  useEffect(() => {
    setPage(1);
  }, [filters.destination, filters.startDate, filters.endDate, filters.eventType, filters.search]);

  return <div className="space-y-6">
    <div>
      <div className="label-mono mb-2">Riwayat Operasional</div>
      <h1 className="font-display text-3xl sm:text-4xl font-bold">Riwayat Bazar & E-commerce</h1>
    </div>

    <section className="card-surface p-5">
      <div className="font-semibold flex items-center gap-2 mb-4"><Filter size={17}/> Filter Data</div>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-3">
        {!scopedDestination && <select className={inputCls} value={filters.destination} onChange={(e) => setFilters({ ...filters, destination: e.target.value })}>
          <option value="">Semua Area</option>
          <option value="Gudang Bazar">Gudang Bazar</option>
          <option value="Gudang E-commerce">Gudang E-commerce</option>
        </select>}
        <input type="date" className={inputCls} value={filters.startDate} onChange={(e) => setFilters({ ...filters, startDate: e.target.value })}/>
        <input type="date" className={inputCls} value={filters.endDate} onChange={(e) => setFilters({ ...filters, endDate: e.target.value })}/>
        <select className={inputCls} value={filters.eventType} onChange={(e) => setFilters({ ...filters, eventType: e.target.value })}>
          <option value="">Semua Jenis Transaksi</option>
          {Object.entries(EVENT_LABELS)
            .filter(([key]) => !scopedDestination || (scopedDestination === 'Gudang Bazar' ? !key.startsWith('ECOM_') : key.startsWith('ECOM_')))
            .map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <div className="relative">
          <Search size={15} className="absolute left-3 top-3 text-[#64748b]"/>
          <input className={inputCls + ' pl-9'} placeholder="No. referensi, SKU, produk, petugas…" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })}/>
        </div>
      </div>
      <div className="flex flex-wrap gap-2 mt-4">
        <button onClick={load} disabled={loading} className="btn-primary inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold">
          <RefreshCcw size={15}/>{loading ? 'Menarik Data…' : 'Tarik Data'}
        </button>
        <button onClick={downloadExcel} disabled={downloading} className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border border-[#22c55e]/40 text-[#86efac] text-sm font-semibold">
          <Download size={15}/>{downloading ? 'Menyiapkan…' : 'Download Excel'}
        </button>
      </div>
    </section>

    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      <div className="card-surface p-4"><div className="label-mono">Transaksi</div><div className="font-display text-2xl font-bold mt-1">{rows.length}</div></div>
      <div className="card-surface p-4"><div className="label-mono">Baris Komoditi</div><div className="font-display text-2xl font-bold mt-1">{totalItems}</div></div>
      <div className="card-surface p-4"><div className="label-mono">Area</div><div className="font-display text-lg font-bold mt-1">{scopedDestination || filters.destination || 'Bazar + E-commerce'}</div></div>
    </div>

    <section className="card-surface overflow-hidden">
      <div className="p-5 border-b border-[#1f2937] flex items-center gap-2"><History size={17}/><div className="font-semibold">Data History</div></div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1050px] text-sm">
          <thead><tr className="text-left text-[#8b93a1] border-b border-[#243044]">
            <th className="px-4 py-3">Tanggal</th><th className="px-4 py-3">Area</th><th className="px-4 py-3">Jenis</th>
            <th className="px-4 py-3">Referensi</th><th className="px-4 py-3">Komoditi / Kuantum</th>
            <th className="px-4 py-3">Petugas</th><th className="px-4 py-3">Keterangan</th>
          </tr></thead>
          <tbody>
            {paginatedRows.map((row) => <tr key={row.id} className="border-b border-[#171f2b] align-top">
              <td className="px-4 py-3 whitespace-nowrap">{row.time ? new Date(row.time).toLocaleString('id-ID') : '—'}</td>
              <td className="px-4 py-3">{row.destination === 'Gudang Bazar' ? 'Bazar' : 'E-commerce'}</td>
              <td className="px-4 py-3"><span className="text-xs px-2 py-1 rounded-md bg-[#2563eb]/10 text-[#93c5fd]">{EVENT_LABELS[row.eventType] || row.eventType}</span></td>
              <td className="px-4 py-3 font-mono text-xs">{row.referenceNo || '—'}</td>
              <td className="px-4 py-3">
                <div className="space-y-2">{(row.items || []).length ? row.items.map((item, index) => <div key={row.id + '-' + index}>
                  <div className="font-medium">{item.sku ? (item.sku + ' · ') : ''}{item.name || item.packageName || 'Item'}</div>
                  <div className="text-xs text-[#8b93a1] mt-0.5">{qtyText(item)}</div>
                </div>) : <span className="text-[#8b93a1]">—</span>}</div>
              </td>
              <td className="px-4 py-3">{row.operator || '—'}</td>
              <td className="px-4 py-3 text-[#94a3b8]">{row.note || row.location || row.marketplace || '—'}</td>
            </tr>)}
          </tbody>
        </table>
        {!loading && rows.length === 0 && <div className="py-10 text-center text-sm text-[#8b93a1]">Tidak ada history pada filter yang dipilih.</div>}
      </div>
      <div className="px-5 pb-5">
        <PaginationControls page={page} totalItems={rows.length} pageSize={pageSize} onChange={setPage} label="transaksi" />
      </div>
    </section>
  </div>;
};

export default RiwayatConsignment;
