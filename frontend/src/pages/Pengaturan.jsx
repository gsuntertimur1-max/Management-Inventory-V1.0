import React, { useEffect, useState } from 'react';
import { Save, Building2, Bell, Palette, Database, Plus, Trash2 } from 'lucide-react';
import { DEFAULT_CATEGORIES } from '../mock';
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
  const { user, settings, updateSettings, resetData, canManageSettings } = useData();
  const isAdmin = canManageSettings;
  const [warehouse, setWarehouse] = useState(settings?.warehouse || 'Gudang Sunter Timur I & II');
  const [address, setAddress] = useState(settings?.address || 'Jl. Sunter Agung, Jakarta Utara');
  const [warehouseHead, setWarehouseHead] = useState(settings?.warehouseHead || 'Irsa Maulian Nugraha');
  const [categories, setCategories] = useState(settings?.categories || DEFAULT_CATEGORIES);
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingCategories, setSavingCategories] = useState(false);
  const [savingToggle, setSavingToggle] = useState('');

  useEffect(() => {
    setWarehouse(settings?.warehouse || 'Gudang Sunter Timur I & II');
    setAddress(settings?.address || 'Jl. Sunter Agung, Jakarta Utara');
    setWarehouseHead(settings?.warehouseHead || 'Irsa Maulian Nugraha');
    setCategories(settings?.categories || DEFAULT_CATEGORIES);
  }, [settings?.warehouse, settings?.address, settings?.warehouseHead, settings?.categories]);

  const payload = (override = {}) => ({
    warehouse: settings?.warehouse || 'Gudang Sunter Timur I & II',
    address: settings?.address || 'Jl. Sunter Agung, Jakarta Utara',
    warehouseHead: settings?.warehouseHead || 'Irsa Maulian Nugraha',
    categories: settings?.categories || DEFAULT_CATEGORIES,
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
      await updateSettings(payload({ warehouse: warehouse.trim(), address: address.trim(), warehouseHead: warehouseHead.trim() }));
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

  const updateCategory = (index, patch) => setCategories((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
  const addCategory = () => setCategories((items) => [...items, { name: '', color: '#64748b', active: true }]);
  const removeCategory = (index) => setCategories((items) => items.filter((_, itemIndex) => itemIndex !== index));
  const saveCategories = async () => {
    const cleaned = categories.map((item) => ({ ...item, name: item.name.trim() }));
    if (!cleaned.length || cleaned.some((item) => !item.name)) return toast.error('Nama kategori wajib diisi');
    setSavingCategories(true);
    try {
      await updateSettings(payload({ categories: cleaned }));
      toast.success('Master kategori tersimpan');
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSavingCategories(false);
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
            <div>
              <label className="text-xs font-medium mb-1 block text-[#8b93a1]">Nama Kepala Gudang</label>
              <input
                value={warehouseHead}
                onChange={(e) => setWarehouseHead(e.target.value)}
                disabled={!isAdmin}
                placeholder="Nama kepala gudang"
                className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb] disabled:opacity-60"
              />
              <p className="text-[11px] text-[#6b7688] mt-1">Nama ini digunakan pada tanda tangan kartu tumpukan dan surat jalan.</p>
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
          <div className="flex items-center justify-between gap-3 mb-5">
            <div>
              <h2 className="font-display text-lg font-bold">Master Kategori Komoditas</h2>
              <p className="text-xs text-[#6b7688] mt-1">Kategori aktif tersedia saat menambah produk. Kategori yang dipakai produk tidak dapat dihapus.</p>
            </div>
            {isAdmin && <button onClick={addCategory} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#2563eb] text-[#60a5fa]"><Plus size={14} /> Tambah</button>}
          </div>
          <div className="space-y-2">
            {categories.map((category, index) => (
              <div key={`${category.name}-${index}`} className="flex flex-wrap items-center gap-2 rounded-lg bg-[#0b0f17] border border-[#151d28] p-2.5">
                <input type="color" value={category.color || '#64748b'} disabled={!isAdmin} onChange={(e) => updateCategory(index, { color: e.target.value })} className="h-8 w-10 rounded border border-[#242f3d] bg-transparent p-0.5 disabled:opacity-60" />
                <input value={category.name} disabled={!isAdmin} onChange={(e) => updateCategory(index, { name: e.target.value })} placeholder="Nama kategori" className="min-w-[150px] flex-1 bg-transparent px-2 py-1.5 text-sm outline-none disabled:opacity-60" />
                <button type="button" disabled={!isAdmin} onClick={() => updateCategory(index, { active: category.active === false })} className={`text-xs px-2.5 py-1.5 rounded-md border disabled:opacity-60 ${category.active === false ? 'border-[#4b5563] text-[#9ca3af]' : 'border-[#22c55e]/50 text-[#4ade80]'}`}>{category.active === false ? 'Nonaktif' : 'Aktif'}</button>
                {isAdmin && <button type="button" onClick={() => removeCategory(index)} className="p-2 rounded-md text-[#f87171] hover:bg-[#ef4444]/10" title="Hapus kategori"><Trash2 size={15} /></button>}
              </div>
            ))}
          </div>
          {isAdmin && <button onClick={saveCategories} disabled={savingCategories} className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg mt-4 disabled:opacity-60"><Save size={15} /> {savingCategories ? 'Menyimpan…' : 'Simpan Kategori'}</button>}
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
                  if (!window.confirm('Reset seluruh data operasional? Semua produk, supplier, transaksi, pengeluaran, surat jalan, tumpukan, riwayat perawatan, dan nomor urut akan dihapus. Master hanya dimuat dari CSV seed bila tersedia.')) return;
                  try {
                    await resetData();
                    toast.success('Data operasional direset. Import master CSV baru bila daftar SKU belum tersedia.');
                  } catch (e) {
                    toast.error(apiError(e));
                  }
                }}
                className="w-full text-left p-3 rounded-lg bg-[#0b0f17] border border-[#151d28] hover:border-[#ef4444] transition-colors text-sm text-[#f87171]"
              >
                Reset seluruh data operasional & muat ulang master dari CSV seed
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
