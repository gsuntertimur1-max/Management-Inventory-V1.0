import React from 'react';
import { Clock, Loader } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatNum } from '../mock';

const LayarAntrian = () => {
  const { suratJalan } = useData();
  const active = suratJalan.filter((sj) => sj.status !== 'Selesai').sort((a, b) => String(a.antrian || '').localeCompare(String(b.antrian || '')));
  const loading = suratJalan.find((sj) => sj.status === 'Sedang Dimuat');

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="label-mono mb-2">Monitor Pemuatan</div>
          <h1 className="font-display text-4xl font-bold">Layar Antrian Pemuatan</h1>
          <p className="text-[#8b93a1] mt-2">Nomor antrian aktif untuk area loading dock</p>
        </div>
        <div className="text-right"><div className="label-mono">Sedang Dilayani</div><div className="font-display text-5xl font-bold text-[#60a5fa]">{loading ? loading.antrian : '—'}</div></div>
      </div>

      {loading && (
        <div className="card-surface p-8 relative overflow-hidden" style={{ background: 'linear-gradient(135deg, rgba(37,99,235,0.15), rgba(20,26,37,0.9))' }}>
          <div className="flex items-center gap-3 mb-2"><Loader size={20} className="text-[#3b82f6] animate-spin" /><span className="label-mono text-[#60a5fa]">Sedang Dimuat</span></div>
          <div className="font-display text-7xl font-bold mb-2">{loading.antrian}</div>
          <div className="text-xl font-semibold">{loading.penerima}</div>
          <div className="text-[#aab4c4] mt-1">Bon {loading.bon_no || '-'} · {formatNum(loading.unit)} unit · {formatNum(loading.berat)} kg</div>
          <div className="text-[#6b7688] mt-1 text-sm">{loading.polisi || '-'} · {loading.unit_loading || '-'}</div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {active.length === 0 ? <div className="card-surface p-8 text-center text-[#6b7688] col-span-full">Tidak ada antrian aktif.</div> : active.map((sj) => (
          <div key={sj.id} className="card-surface stat-card p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="font-display text-4xl font-bold">{sj.antrian}</div>
              {sj.status === 'Menunggu' ? <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full" style={{ background: 'rgba(234,179,8,.15)', color: '#eab308' }}><Clock size={12} /> Menunggu</span> : <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full" style={{ background: 'rgba(59,130,246,.15)', color: '#3b82f6' }}><Loader size={12} className="animate-spin" /> Dimuat</span>}
            </div>
            <div className="font-semibold">{sj.penerima}</div>
            <div className="label-mono text-[10px] mt-1">Bon {sj.bon_no || '-'}</div>
            <div className="text-xs text-[#6b7688] mt-1">{sj.polisi || '-'} · {sj.unit_loading || '-'}</div>
            <div className="mt-4 pt-4 border-t border-[#151d28] flex justify-between text-xs"><span className="text-[#8b93a1]">{formatNum((sj.items || []).length)} jenis barang</span><span className="font-mono">{formatNum(sj.unit)} unit</span></div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default LayarAntrian;
