import React, { useState } from 'react';
import { ArrowLeftRight, Building2, ShoppingBag, Store } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import TumpukanWithLotStatus from './TumpukanWithLotStatus';
import ConsignmentLocationMap from './ConsignmentLocationMap';
import { useData } from '../context/DataContext';

const LOCATIONS = [
  { key: 'MAIN', label: 'Gudang Utama', icon: Building2 },
  { key: 'BAZAR', label: 'Bazar', icon: Store },
  { key: 'ECOM', label: 'E-commerce', icon: ShoppingBag },
];

const TumpukanUnified = () => {
  const [location, setLocation] = useState('MAIN');
  const navigate = useNavigate();
  const { canWrite } = useData();

  return <div className="space-y-5">
    <section className="card-surface p-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="label-mono mr-2">Lokasi Persediaan</div>
        {LOCATIONS.map((item) => <button key={item.key} type="button" onClick={() => setLocation(item.key)} className={`inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors ${location === item.key ? 'bg-[#2563eb] text-white' : 'bg-[#1e293b] text-[#94a3b8] hover:text-white'}`}><item.icon size={16} />{item.label}</button>)}
        {canWrite && <button type="button" onClick={() => navigate('/mutasi-tumpukan')} className="ml-auto inline-flex items-center gap-2 rounded-lg border border-[#3b82f6] px-4 py-2.5 text-sm font-semibold text-[#93c5fd] hover:bg-[#2563eb]/10"><ArrowLeftRight size={16} />Mutasi Tumpukan</button>}
      </div>
      <p className="text-[11px] text-[#8b93a1] mt-2">Perpindahan ke Bazar/E-commerce hanya mengubah lokasi/sub-ledger. Mutasi antar tumpukan Gudang Utama juga tidak mengubah total stok fisik.</p>
    </section>

    {location === 'MAIN' && <TumpukanWithLotStatus />}
    {location === 'BAZAR' && <ConsignmentLocationMap destination="Gudang Bazar" />}
    {location === 'ECOM' && <ConsignmentLocationMap destination="Gudang E-commerce" />}
  </div>;
};

export default TumpukanUnified;
