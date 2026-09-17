import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { MapPin, Route } from 'lucide-react';
import api from '../lib/api';
import LayarAntrian from './LayarAntrian';

const LayarAntrianEnhanced = () => {
  const [rows, setRows] = useState([]);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get('/outbound-queue');
      setRows(Array.isArray(data) ? data : []);
    } catch (error) {
      // LayarAntrian utama tetap menangani error/refresh sendiri.
    }
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
  }, [load]);

  const multi = useMemo(() => rows.filter((row) => row.multiLocation), [rows]);

  return (
    <div className="space-y-5">
      <div className="card-surface p-4 border border-[#24364d]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="label-mono text-[10px] text-[#93c5fd]">Aturan Nomor Antrian</div>
            <div className="text-sm mt-1"><span className="font-mono font-bold">17-xxx s.d. 24-xxx / MP1-xxx</span> = satu unit pemuatan · <span className="font-mono font-bold text-[#fbbf24]">M-xxx</span> = satu kendaraan memuat dari lebih dari satu unit.</div>
            <div className="text-xs text-[#8b93a1] mt-1">Nomor Bon Muat tetap nomor dokumen global dan tidak memakai kode lokasi. Lokasi fisik ditampilkan terpisah sebagai rute muat.</div>
          </div>
          <div className="inline-flex items-center gap-2 rounded-lg border border-[#334155] px-3 py-2 text-xs"><Route size={15} /> {multi.length} multi-lokasi aktif</div>
        </div>
      </div>

      {multi.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
          {multi.map((load) => (
            <div key={load.id} className="card-surface p-4 border border-[#78350f]">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="label-mono text-[10px] text-[#fbbf24]">MULTI LOKASI · {load.antrian}</div>
                  <div className="font-semibold mt-1">{load.party || '-'}</div>
                  <div className="text-xs text-[#8b93a1] mt-1">{(load.documents || [load.ref]).filter(Boolean).join(', ') || 'Tanpa dokumen'}</div>
                </div>
                <MapPin size={18} className="text-[#fbbf24] shrink-0" />
              </div>
              <div className="mt-3 rounded-lg bg-[#0b0f17] border border-[#242f3d] px-3 py-2 text-sm font-medium">{load.loadingRoute || load.unit_loading || '-'}</div>
              <div className="mt-3 space-y-2">
                {(load.loadingPlan || []).map((step, index) => (
                  <div key={`${load.id}-${step.unit}`} className="flex gap-3 text-xs">
                    <div className="font-mono text-[#93c5fd] shrink-0">{index + 1}.</div>
                    <div><span className="font-semibold">{step.unit === 'MP1' ? 'MP1' : `Unit ${step.unit}`}</span> · {(step.stacks || []).join(', ') || '-'}<div className="text-[#8b93a1]">Dokumen: {(step.documents || []).join(', ') || '-'} · Produk: {(step.products || []).join(', ') || '-'}</div></div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <LayarAntrian />
    </div>
  );
};

export default LayarAntrianEnhanced;
