import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Printer, Plus, MonitorSmartphone, Truck } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatNum, formatDate } from '../mock';
import { toast } from 'sonner';

const STATUS = { 'Menunggu': { c: '#eab308', bg: 'rgba(234,179,8,.15)' }, 'Sedang Dimuat': { c: '#3b82f6', bg: 'rgba(59,130,246,.15)' }, 'Selesai': { c: '#22c55e', bg: 'rgba(34,197,94,.15)' } };

const Pengeluaran = () => {
  const { suratJalan, updateSJStatus } = useData();
  const navigate = useNavigate();
  const [filter, setFilter] = useState('Semua Status');
  const [selected, setSelected] = useState([]);

  const list = suratJalan.filter((sj) => filter === 'Semua Status' || sj.status === filter);
  const toggle = (id) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label-mono mb-2">Pengiriman Barang</div>
          <h1 className="font-display text-4xl font-bold">Pengeluaran &amp; Surat Jalan</h1>
          <p className="text-[#8b93a1] mt-2">{suratJalan.length} surat jalan · setiap dokumen bisa memuat beberapa jenis barang</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => navigate('/antrian')} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24]"><MonitorSmartphone size={15} /> Layar Antrian</button>
          <button onClick={() => navigate('/catat')} className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg"><Plus size={15} /> Pengeluaran Baru</button>
        </div>
      </div>

      <div className="card-surface p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <select data-testid="sj-status-filter" value={filter} onChange={(e) => setFilter(e.target.value)} className="bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none"><option>Semua Status</option><option>Menunggu</option><option>Sedang Dimuat</option><option>Selesai</option></select>
          <button onClick={() => { toast.success(`Mencetak ${selected.length} surat jalan (mock)`); }} className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24]"><Printer size={15} /> Cetak Surat Jalan ({selected.length}) — A4</button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]">{['', 'No. Surat Jalan', 'Antrian', 'Waktu', 'Penerima', 'Barang', 'Total Berat', 'Total Unit', 'Status', 'Aksi'].map((h, i) => <th key={i} className="py-2.5 pr-4 font-semibold whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {list.length === 0 ? <tr><td colSpan={10} className="py-8 text-center text-[#6b7688]">Belum ada surat jalan. Buat pengeluaran baru.</td></tr> : list.map((sj) => (
                <tr key={sj.id} className="tbl-row border-b border-[#131a24] align-top">
                  <td className="py-3 pr-4"><input type="checkbox" checked={selected.includes(sj.id)} onChange={() => toggle(sj.id)} className="accent-[#2563eb] w-4 h-4" /></td>
                  <td className="py-3 pr-4 font-mono text-xs">{sj.no}</td>
                  <td className="py-3 pr-4 font-mono text-xs">{sj.antrian}</td>
                  <td className="py-3 pr-4 whitespace-nowrap text-[#8b93a1]">{formatDate(sj.time)}</td>
                  <td className="py-3 pr-4 text-[#c7d0dc]">{sj.penerima}</td>
                  <td className="py-3 pr-4 text-xs max-w-xs">{sj.items.map((it, i) => <div key={i} className="text-[#aab4c4]">{it.name} × {it.berat} Kg <span className="text-[#6b7688]">({formatNum(it.qty)} {it.unit})</span></div>)}</td>
                  <td className="py-3 pr-4 font-mono whitespace-nowrap">{formatNum(sj.berat)} kg</td>
                  <td className="py-3 pr-4 font-mono">{formatNum(sj.unit)}</td>
                  <td className="py-3 pr-4"><span className="text-xs px-2.5 py-1 rounded-full font-medium whitespace-nowrap" style={{ background: STATUS[sj.status]?.bg, color: STATUS[sj.status]?.c }}>{sj.status}</span></td>
                  <td className="py-3 pr-4">
                    {sj.status === 'Menunggu' && <button data-testid={`sj-mulai-muat-btn-${sj.no}`} onClick={() => { updateSJStatus(sj.id, 'Sedang Dimuat'); toast.success('Mulai memuat'); }} className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-[#2563eb] text-[#60a5fa] hover:bg-[#2563eb]/10 whitespace-nowrap">Mulai Muat</button>}
                    {sj.status === 'Sedang Dimuat' && <button data-testid={`sj-selesai-btn-${sj.no}`} onClick={() => { updateSJStatus(sj.id, 'Selesai'); toast.success('Pemuatan selesai'); }} className="btn-primary text-xs font-semibold px-3 py-1.5 rounded-lg whitespace-nowrap">Selesai</button>}
                    {sj.status === 'Selesai' && <span className="text-xs text-[#6b7688]">—</span>}
                  </td>
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
