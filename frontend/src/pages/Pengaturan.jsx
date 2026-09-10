import React, { useEffect, useState } from 'react';
import { Save, Building2, Bell, Palette, Database } from 'lucide-react';
import { useData } from '../context/DataContext';
import { apiError } from '../lib/api';
import { toast } from 'sonner';

const Toggle = ({ on, onClick, disabled = false }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    aria-pressed={on}
    className={`w-11 h-6 rounded-full transition-colors relative disabled:opacity-50 disabled:cursor-not-allowed ${on ? 'bg-[#2563eb]' : 'bg-[#242f3d]'}`}
  >
    <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${on ? 'left-[22px]' : 'left-0.5'}`} />
  </button>
);

const Pengaturan = () => {
  const { user, settings, updateSettings, resetData } = useData();
  const isAdmin = user?.role === 'Administrator';
  const [warehouse, setWarehouse] = useState(settings?.warehouse || 'Gudang Sunter Timur I & II');
  const [address, setAddress] = useState(settings?.address || 'Jl. Sunter Agung, Jakarta Utara');
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingToggle, setSavingToggle] = useState('');

  useEffect(() => {
    setWarehouse(settings?.warehouse || 'Gudang Sunter Timur I & II');
    setAddress(settings?.address || 'Jl. Sunter Agung, Jakarta Utara');
  }, [settings?.warehouse, settings?.address]);

  const payload = (override = {}) => ({
    warehouse: settings?.warehouse || 'Gudang Sunter Timur I & II',
    address: settings?.address || 'Jl. Sunter Agung, Jakarta Utara',
    lowAlert: settings?.lowAlert ?? true,
    expAlert: settings?.expAlert ?? true,
    autoQueue: settings?.autoQueue ?? true,
    ...override,
  });

  const saveProfile = async () => {
    if (!warehouse.trim()) {
      toast.error('Nama gudang wajib diisi');
      return;
    }
    setSavingProfile(true);
    try {
      await updateSettings(payload({ warehouse: warehouse.trim(), address: address.trim() }));
      toast.success('Profil gudang tersimpan');
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSavingProfile(false);
    }
  };

  const toggleSetting = async (key, label) => {
    if (!isAdmin || savingToggle) return;
    const next = !(settings?.[key] ?? true);
    setSavingToggle(key);
    try {
      await updateSettings(payload({ [key]: next }));
      toast.success(`${label} ${next ? 'diaktifkan' : 'dinonaktifkan'}`);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSavingToggle('');
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <div className="label-mono mb-2">Konfigurasi Sistem</div>
        <h1 className="font-display text-4xl font-bold">Pengaturan</h1>
        <p className="text-[#8b93a1] mt-2">Kelola profil gudang dan preferensi sistem. Perubahan tersimpan di database.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card-surface p-6">
          <div className="flex items-center gap-2 mb-5">
            <Building2 size={18} className="text-[#60a5fa]" />
            <h2 className="font-display text-lg font-bold">Profil Gudang</h2>
          </div>
          <div className="space-y-4">
            <div>
              <label className="text-xs font-medium mb-1 block text-[#8b93a1]">Nama Gudang</label>
              <input
                value={warehouse}
                onChange={(e) => setWarehouse(e.target.value)}
                disabled={!isAdmin}
                className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb] disabled:opacity-60"
              />
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block text-[#8b93a1]">Alamat</label>
              <input
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                disabled={!isAdmin}
                className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb] disabled:opacity-60"
              />
            </div>
            {isAdmin && (
              <button
                onClick={saveProfile}
                disabled={savingProfile}
                className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg disabled:opacity-60"
              >
                <Save size={15} /> {savingProfile ? 'Menyimpan…' : 'Simpan Profil'}
              </button>
            )}
          </div>
        </div>

        <div className="card-surface p-6">
          <div className="flex items-center gap-2 mb-5">
            <Bell size={18} className="text-[#eab308]" />
            <h2 className="font-display text-lg font-bold">Preferensi Operasional</h2>
          </div>
          <div className="space-y-4">
            {[
              ['lowAlert', 'Peringatan stok minimum'],
              ['expAlert', 'Peringatan barang mendekati kedaluwarsa'],
              ['autoQueue', 'Penomoran antrian otomatis'],
            ].map(([key, label]) => (
              <div key={key} className="flex items-center justify-between gap-4 p-3 rounded-lg bg-[#0b0f17] border border-[#151d28]">
                <div>
                  <div className="text-sm">{label}</div>
                  {savingToggle === key && <div className="text-[10px] text-[#6b7688] mt-1">Menyimpan…</div>}
                </div>
                <Toggle
                  on={settings?.[key] ?? true}
                  onClick={() => toggleSetting(key, label)}
                  disabled={!isAdmin || Boolean(savingToggle)}
                />
              </div>
            ))}
          </div>
          <p className="text-xs text-[#6b7688] mt-4">Preferensi tersimpan otomatis dan tetap berlaku setelah halaman dimuat ulang.</p>
        </div>

        <div className="card-surface p-6">
          <div className="flex items-center gap-2 mb-5">
            <Palette size={18} className="text-[#a855f7]" />
            <h2 className="font-display text-lg font-bold">Tampilan</h2>
          </div>
          <div className="flex items-center justify-between p-3 rounded-lg bg-[#0b0f17] border border-[#151d28]">
            <div>
              <div className="text-sm font-medium">Mode Gelap</div>
              <div className="text-xs text-[#6b7688]">Tema aktif aplikasi saat ini</div>
            </div>
            <span className="text-xs px-2.5 py-1 rounded-full bg-[#22c55e]/15 text-[#22c55e]">Aktif</span>
          </div>
        </div>

        <div className="card-surface p-6">
          <div className="flex items-center gap-2 mb-5">
            <Database size={18} className="text-[#22c55e]" />
            <h2 className="font-display text-lg font-bold">Data</h2>
          </div>
          <div className="space-y-3">
            {isAdmin ? (
              <button
                data-testid="reset-data-btn"
                onClick={async () => {
                  if (!window.confirm('Hapus semua transaksi, surat jalan & PO, lalu muat ulang produk & supplier dari data master CSV?')) return;
                  try {
                    await resetData();
                    toast.success('Data direset — produk & supplier dimuat ulang dari CSV master');
                  } catch {
                    toast.error('Gagal mereset data');
                  }
                }}
                className="w-full text-left p-3 rounded-lg bg-[#0b0f17] border border-[#151d28] hover:border-[#ef4444] transition-colors text-sm text-[#f87171]"
              >
                Reset semua transaksi & muat ulang data master dari CSV (31 produk)
              </button>
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
