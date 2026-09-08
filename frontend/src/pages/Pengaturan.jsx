import React, { useState } from 'react';
import { Save, Building2, Bell, Palette, Database } from 'lucide-react';
import { useData } from '../context/DataContext';
import { toast } from 'sonner';

const Toggle = ({ on, onClick }) => (
  <button onClick={onClick} className={`w-11 h-6 rounded-full transition-colors relative ${on ? 'bg-[#2563eb]' : 'bg-[#242f3d]'}`}><span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${on ? 'left-[22px]' : 'left-0.5'}`} /></button>
);

const Pengaturan = () => {
  const { user, resetData } = useData();
  const [warehouse, setWarehouse] = useState('Gudang Sunter Timur I & II');
  const [address, setAddress] = useState('Jl. Sunter Agung, Jakarta Utara');
  const [lowAlert, setLowAlert] = useState(true);
  const [expAlert, setExpAlert] = useState(true);
  const [autoQueue, setAutoQueue] = useState(true);

  return (
    <div className="space-y-6">
      <div>
        <div className="label-mono mb-2">Konfigurasi Sistem</div>
        <h1 className="font-display text-4xl font-bold">Pengaturan</h1>
        <p className="text-[#8b93a1] mt-2">Kelola profil gudang, notifikasi, dan preferensi sistem</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card-surface p-6">
          <div className="flex items-center gap-2 mb-5"><Building2 size={18} className="text-[#60a5fa]" /><h2 className="font-display text-lg font-bold">Profil Gudang</h2></div>
          <div className="space-y-4">
            <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Nama Gudang</label><input value={warehouse} onChange={(e) => setWarehouse(e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
            <div><label className="text-xs font-medium mb-1 block text-[#8b93a1]">Alamat</label><input value={address} onChange={(e) => setAddress(e.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]" /></div>
            <button onClick={() => toast.success('Profil gudang disimpan')} className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg"><Save size={15} /> Simpan Profil</button>
          </div>
        </div>

        <div className="card-surface p-6">
          <div className="flex items-center gap-2 mb-5"><Bell size={18} className="text-[#eab308]" /><h2 className="font-display text-lg font-bold">Notifikasi</h2></div>
          <div className="space-y-4">
            {[['Peringatan stok minimum', lowAlert, () => setLowAlert(!lowAlert)], ['Peringatan barang mendekati kedaluwarsa', expAlert, () => setExpAlert(!expAlert)], ['Penomoran antrian otomatis', autoQueue, () => setAutoQueue(!autoQueue)]].map(([l, v, fn]) => (
              <div key={l} className="flex items-center justify-between p-3 rounded-lg bg-[#0b0f17] border border-[#151d28]"><span className="text-sm">{l}</span><Toggle on={v} onClick={fn} /></div>
            ))}
          </div>
        </div>

        <div className="card-surface p-6">
          <div className="flex items-center gap-2 mb-5"><Palette size={18} className="text-[#a855f7]" /><h2 className="font-display text-lg font-bold">Tampilan</h2></div>
          <div className="flex items-center justify-between p-3 rounded-lg bg-[#0b0f17] border border-[#151d28]"><div><div className="text-sm font-medium">Mode Gelap</div><div className="text-xs text-[#6b7688]">Tema default untuk area gudang</div></div><Toggle on={true} onClick={() => toast.info('Mode terang segera hadir')} /></div>
        </div>

        <div className="card-surface p-6">
          <div className="flex items-center gap-2 mb-5"><Database size={18} className="text-[#22c55e]" /><h2 className="font-display text-lg font-bold">Data</h2></div>
          <div className="space-y-3">
            {user?.role === 'Administrator' ? (
              <button data-testid="reset-data-btn" onClick={async () => { if (!window.confirm('Hapus semua transaksi, surat jalan & PO, lalu muat ulang produk & supplier dari data master CSV?')) return; try { await resetData(); toast.success('Data direset — produk & supplier dimuat ulang dari CSV master'); } catch { toast.error('Gagal mereset data'); } }} className="w-full text-left p-3 rounded-lg bg-[#0b0f17] border border-[#151d28] hover:border-[#ef4444] transition-colors text-sm text-[#f87171]">Reset semua transaksi & muat ulang data master dari CSV (31 produk)</button>
            ) : (
              <p className="text-sm text-[#6b7688] p-3">Hanya Administrator yang dapat mereset data.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Pengaturan;
