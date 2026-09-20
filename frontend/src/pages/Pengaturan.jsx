import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Save, Building2, Bell, Palette, Database, Plus, Trash2, Warehouse, Link2, MapPin, CalendarDays } from 'lucide-react';
import { DEFAULT_CATEGORIES } from '../mock';
import { useData } from '../context/DataContext';
import api, { apiError } from '../lib/api';
import { toast } from 'sonner';
import { DEFAULT_WAREHOUSES, warehousesFromSettings } from '../lib/warehouses';
import ProductionSafetyPanel from '../components/ProductionSafetyPanel';
import { canonicalRole } from '../lib/permissions';

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


const DEFAULT_LOCATIONS = [
  ...[17, 18, 19, 20].map((unit) => ({ code: String(unit), name: `GBB ${unit}`, type: 'GBB', loadingGroup: 'GRUP 1 - GBB 17-20', unloadingGroup: 'MANDOR 1 - GBB 17-20', allowInbound: true, allowOutbound: true, loadingCostEnabled: true, unloadingCostEnabled: true, active: true })),
  { code: 'MP1', name: 'Multi Purpose 1', type: 'MP', loadingGroup: 'GRUP 2 - MP1/21-24', unloadingGroup: 'MANDOR 2 - MP1/GBB 21-24', allowInbound: true, allowOutbound: true, loadingCostEnabled: true, unloadingCostEnabled: true, active: true },
  ...[21, 22, 23, 24].map((unit) => ({ code: String(unit), name: `GBB ${unit}`, type: 'GBB', loadingGroup: 'GRUP 2 - MP1/21-24', unloadingGroup: 'MANDOR 2 - MP1/GBB 21-24', allowInbound: true, allowOutbound: true, loadingCostEnabled: true, unloadingCostEnabled: true, active: true })),
  { code: 'RTR', name: 'RTR', type: 'RTR', loadingGroup: 'GRUP 3 - RTR', unloadingGroup: '', allowInbound: true, allowOutbound: true, loadingCostEnabled: true, unloadingCostEnabled: false, active: true },
  { code: 'BAZAR', name: 'Gudang Bazar', type: 'KONSINYASI', loadingGroup: '', unloadingGroup: '', allowInbound: true, allowOutbound: true, loadingCostEnabled: false, unloadingCostEnabled: false, active: true },
  { code: 'ECOM', name: 'Gudang E-commerce', type: 'KONSINYASI', loadingGroup: '', unloadingGroup: '', allowInbound: true, allowOutbound: true, loadingCostEnabled: false, unloadingCostEnabled: false, active: true },
  { code: 'RUSAK', name: 'AREA BARANG RUSAK', type: 'RUSAK', loadingGroup: '', unloadingGroup: '', allowInbound: true, allowOutbound: true, loadingCostEnabled: false, unloadingCostEnabled: false, active: true },
];

const Pengaturan = () => {
  const { user, settings, updateSettings, canManageSettings, theme, setTheme } = useData();
  const isAdmin = canManageSettings;
  const isSuperadmin = canonicalRole(user?.role) === 'Administrator';
  const [warehouse, setWarehouse] = useState(settings?.warehouse || 'Gudang Sunter Timur I & II');
  const [address, setAddress] = useState(settings?.address || 'Jl. Sunter Agung, Jakarta Utara');
  const [warehouseHead, setWarehouseHead] = useState(settings?.warehouseHead || 'Irsa Maulian Nugraha');
  const [categories, setCategories] = useState(settings?.categories || DEFAULT_CATEGORIES);
  const [warehouses, setWarehouses] = useState(warehousesFromSettings(settings?.warehouses));
  const [locations, setLocations] = useState(settings?.locations || DEFAULT_LOCATIONS);
  const [holidays, setHolidays] = useState(settings?.holidays || []);
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingCategories, setSavingCategories] = useState(false);
  const [savingToggle, setSavingToggle] = useState('');
  const [savingWarehouses, setSavingWarehouses] = useState(false);
  const [savingLocations, setSavingLocations] = useState(false);
  const [savingHolidays, setSavingHolidays] = useState(false);
  const [resettingOperational, setResettingOperational] = useState(false);

  useEffect(() => {
    setWarehouse(settings?.warehouse || 'Gudang Sunter Timur I & II');
    setAddress(settings?.address || 'Jl. Sunter Agung, Jakarta Utara');
    setWarehouseHead(settings?.warehouseHead || 'Irsa Maulian Nugraha');
    setCategories(settings?.categories || DEFAULT_CATEGORIES);
    setWarehouses(warehousesFromSettings(settings?.warehouses));
    setLocations(settings?.locations || DEFAULT_LOCATIONS);
    setHolidays(settings?.holidays || []);
  }, [settings?.warehouse, settings?.address, settings?.warehouseHead, settings?.categories, settings?.warehouses, settings?.locations, settings?.holidays]);

  const payload = (override = {}) => ({
    warehouse: settings?.warehouse || 'Gudang Sunter Timur I & II',
    address: settings?.address || 'Jl. Sunter Agung, Jakarta Utara',
    warehouseHead: settings?.warehouseHead || 'Irsa Maulian Nugraha',
    categories: settings?.categories || DEFAULT_CATEGORIES,
    lowAlert: settings?.lowAlert ?? true,
    expAlert: settings?.expAlert ?? true,
    autoQueue: settings?.autoQueue ?? true,
    holidays: settings?.holidays || [],
    warehouses: settings?.warehouses || DEFAULT_WAREHOUSES,
    locations: settings?.locations || DEFAULT_LOCATIONS,
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

  const resetOperationalData = async () => {
    if (!isSuperadmin || resettingOperational) return;

    if (!window.confirm('Reset Operasional akan menghapus seluruh stok, transaksi, dokumen, tumpukan, lot/FEFO, Bazar/Ecom, biaya, opname, dan nomor urut. Master SKU, supplier, user, gudang/lokasi, template Paket, serta konfigurasi marketplace tetap dipertahankan. Pastikan Backup PEPEG sudah diunduh. Lanjutkan pemeriksaan?')) return;

    setResettingOperational(true);
    try {
      const { data: preview } = await api.get('/admin/reset-operational/preview');
      if (!preview?.maintenanceMode) {
        toast.error('Aktifkan Maintenance Mode pada Production Safety & Recovery terlebih dahulu.');
        return;
      }
      if (Number(preview?.activeLoads || 0) > 0 || Number(preview?.processingRequests || 0) > 0 || Number(preview?.activeLocks || 0) > 0) {
        toast.error(`Reset belum aman: ${preview?.activeLoads || 0} pemuatan aktif, ${preview?.processingRequests || 0} request diproses, ${preview?.activeLocks || 0} lock aktif.`);
        return;
      }

      const keyCounts = preview?.keyCounts || {};
      const confirmation = window.prompt(
        'PEMERIKSAAN RESET OPERASIONAL\n\n' +
        `Master SKU dipertahankan: ${preview?.productsPreserved ?? 0}\n` +
        `Supplier dipertahankan: ${preview?.suppliersPreserved ?? 0}\n` +
        `Transaksi akan dihapus: ${keyCounts.transactions ?? 0}\n` +
        `Pemuatan akan dihapus: ${keyCounts.outbound_loads ?? 0}\n` +
        `Surat Jalan akan dihapus: ${keyCounts.surat_jalan ?? 0}\n` +
        `Tumpukan aktif akan dikosongkan: ${keyCounts.stack_allocations ?? 0}\n\n` +
        'Ketik RESET OPERASIONAL untuk melanjutkan.'
      );
      if (confirmation !== 'RESET OPERASIONAL') {
        toast.info('Reset Operasional dibatalkan.');
        return;
      }

      if (!window.confirm('KONFIRMASI TERAKHIR: seluruh saldo stok akan menjadi 0 dan data operasional tidak dapat dikembalikan kecuali dari backup. Lanjutkan?')) return;

      const { data } = await api.post('/admin/reset-operational', {}, {
        headers: {
          'X-PEPEG-RESET-CONFIRM': 'RESET_OPERASIONAL_PEPEG',
          'X-PEPEG-BACKUP-CONFIRM': 'BACKUP_TERSIMPAN',
        },
      });
      toast.success(`Reset Operasional selesai. ${data?.productsPreserved ?? 0} master SKU tetap dipertahankan. Maintenance Mode tetap aktif.`);
      window.setTimeout(() => window.location.reload(), 900);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setResettingOperational(false);
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

  const updateWarehouse = (index, patch) => setWarehouses((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
  const updateZone = (warehouseIndex, zoneIndex, patch) => setWarehouses((items) => items.map((item, itemIndex) => itemIndex === warehouseIndex ? { ...item, zones: item.zones.map((zone, currentZone) => currentZone === zoneIndex ? { ...zone, ...patch } : zone) } : item));
  const addWarehouse = (type = 'GBB') => setWarehouses((items) => [...items, type === 'MP'
    ? { code: '', name: '', type: 'MP', length: 230, width: 30, zones: [{ code: 'A', count: 8 }, { code: 'B', count: 8 }], active: true }
    : { code: '', name: '', type: 'GBB', length: 50, width: 30, zones: [{ code: 'A', count: 4 }, { code: 'B', count: 4 }, { code: 'C', count: 4 }], active: true }]);
  const removeWarehouse = (index) => setWarehouses((items) => items.filter((_, itemIndex) => itemIndex !== index));
  const saveWarehouses = async () => {
    const cleaned = warehouses.map((item) => ({ ...item, code: item.code.trim().toUpperCase(), name: item.name.trim(), zones: item.zones.map((zone) => ({ code: zone.code.trim().toUpperCase(), count: Number(zone.count) })) }));
    if (cleaned.some((item) => !item.code || !item.name || item.zones.some((zone) => !zone.code || zone.count < 1))) return toast.error('Kode, nama gudang, dan jumlah tumpukan wajib diisi');
    setSavingWarehouses(true);
    try { await updateSettings(payload({ warehouses: cleaned })); toast.success('Master gudang dan tumpukan tersimpan'); }
    catch (e) { toast.error(apiError(e)); }
    finally { setSavingWarehouses(false); }
  };


  const addHoliday = () => setHolidays((items) => [...items, { date: '', name: '', active: true }]);
  const updateHoliday = (index, patch) => setHolidays((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
  const removeHoliday = (index) => setHolidays((items) => items.filter((_, itemIndex) => itemIndex !== index));
  const saveHolidays = async () => {
    const cleaned = holidays.map((item) => ({ date: String(item.date || '').trim(), name: String(item.name || '').trim(), active: item.active !== false }));
    if (cleaned.some((item) => !item.date)) return toast.error('Tanggal hari libur wajib diisi');
    setSavingHolidays(true);
    try {
      await updateSettings(payload({ holidays: cleaned }));
      toast.success('Master hari libur tersimpan');
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSavingHolidays(false);
    }
  };

  const updateLocation = (index, patch) => setLocations((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
  const addLocation = () => setLocations((items) => [...items, { code: '', name: '', type: 'LAINNYA', loadingGroup: '', unloadingGroup: '', allowInbound: true, allowOutbound: true, loadingCostEnabled: false, unloadingCostEnabled: false, active: true }]);
  const removeLocation = (index) => setLocations((items) => items.filter((_, itemIndex) => itemIndex !== index));
  const saveLocations = async () => {
    const cleaned = locations.map((item) => ({ ...item, code: String(item.code || '').trim().toUpperCase(), name: String(item.name || '').trim() }));
    if (!cleaned.length || cleaned.some((item) => !item.code || !item.name)) return toast.error('Kode dan nama lokasi wajib diisi');
    if (cleaned.some((item) => item.loadingCostEnabled && !item.loadingGroup)) return toast.error('Pilih Grup Muat untuk lokasi dengan biaya muat aktif');
    if (cleaned.some((item) => item.unloadingCostEnabled && !item.unloadingGroup)) return toast.error('Pilih Mandor Bongkar untuk lokasi dengan biaya bongkar aktif');
    setSavingLocations(true);
    try {
      await updateSettings(payload({ locations: cleaned }));
      toast.success('Master lokasi operasional tersimpan');
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSavingLocations(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <div className="label-mono mb-2">Konfigurasi Sistem</div>
        <h1 className="font-display text-4xl font-bold">Pengaturan</h1>
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

        <div className="card-surface p-6 lg:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
            <div><div className="flex items-center gap-2"><Warehouse size={18} className="text-[#60a5fa]" /><h2 className="font-display text-lg font-bold">Master Gudang & Tumpukan</h2></div><p className="text-xs text-[#6b7688] mt-1">GBB dapat memakai zona A/B/C, sedangkan MP memakai A/B. Tumpukan yang telah dipakai stok tidak dapat dihapus atau dikurangi.</p></div>
            {isAdmin && <div className="flex gap-2"><button onClick={() => addWarehouse('GBB')} className="px-3 py-2 rounded-lg border border-[#2563eb] text-xs text-[#60a5fa]"><Plus size={14} className="inline mr-1" />GBB</button><button onClick={() => addWarehouse('MP')} className="px-3 py-2 rounded-lg border border-[#2563eb] text-xs text-[#60a5fa]"><Plus size={14} className="inline mr-1" />MP</button></div>}
          </div>
          <div className="space-y-3">
            {warehouses.map((item, index) => <div key={`${item.code}-${index}`} className="rounded-xl border border-[#151d28] bg-[#0b0f17] p-3">
              <div className="grid grid-cols-1 sm:grid-cols-6 gap-2 items-end"><div><label className="text-[10px] text-[#8b93a1]">Kode</label><input disabled={!isAdmin} value={item.code} onChange={(e) => updateWarehouse(index, { code: e.target.value })} placeholder="25 / MP2" className="w-full bg-transparent border-b border-[#242f3d] py-1.5 text-sm outline-none" /></div><div className="sm:col-span-2"><label className="text-[10px] text-[#8b93a1]">Nama</label><input disabled={!isAdmin} value={item.name} onChange={(e) => updateWarehouse(index, { name: e.target.value })} placeholder="GBB 25" className="w-full bg-transparent border-b border-[#242f3d] py-1.5 text-sm outline-none" /></div><div><label className="text-[10px] text-[#8b93a1]">Tipe</label><div className="py-1.5 text-sm">{item.type}</div></div><div><label className="text-[10px] text-[#8b93a1]">P × L (m)</label><div className="flex gap-1"><input disabled={!isAdmin} type="number" value={item.length} onChange={(e) => updateWarehouse(index, { length: Number(e.target.value) })} className="w-1/2 bg-transparent border-b border-[#242f3d] py-1.5 text-sm outline-none" /><input disabled={!isAdmin} type="number" value={item.width} onChange={(e) => updateWarehouse(index, { width: Number(e.target.value) })} className="w-1/2 bg-transparent border-b border-[#242f3d] py-1.5 text-sm outline-none" /></div></div><div className="flex justify-end gap-2"><button type="button" disabled={!isAdmin} onClick={() => updateWarehouse(index, { active: item.active === false })} className={`text-xs px-2.5 py-1.5 rounded-md border ${item.active === false ? 'border-[#4b5563] text-[#9ca3af]' : 'border-[#22c55e]/50 text-[#4ade80]'}`}>{item.active === false ? 'Nonaktif' : 'Aktif'}</button>{isAdmin && <button type="button" onClick={() => removeWarehouse(index)} className="p-1.5 text-[#f87171]" title="Hapus gudang"><Trash2 size={15} /></button>}</div></div>
              <div className="mt-3 flex flex-wrap gap-2">{item.zones.map((zone, zoneIndex) => <div key={`${zone.code}-${zoneIndex}`} className="flex items-center gap-2 rounded-lg border border-[#242f3d] px-2 py-1"><span className="text-xs text-[#8b93a1]">Zona</span><input disabled={!isAdmin} value={zone.code} onChange={(e) => updateZone(index, zoneIndex, { code: e.target.value })} className="w-8 bg-transparent text-center text-sm outline-none" /><span className="text-xs text-[#8b93a1]">Tumpukan</span><input disabled={!isAdmin} type="number" min="1" value={zone.count} onChange={(e) => updateZone(index, zoneIndex, { count: Number(e.target.value) })} className="w-12 bg-transparent text-center text-sm outline-none" /></div>)}</div>
            </div>)}
          </div>
          {isAdmin && <button onClick={saveWarehouses} disabled={savingWarehouses} className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg mt-4 disabled:opacity-60"><Save size={15} /> {savingWarehouses ? 'Menyimpan…' : 'Simpan Master Gudang'}</button>}
        </div>


        <div className="card-surface p-6 lg:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
            <div>
              <div className="flex items-center gap-2"><MapPin size={18} className="text-[#f59e0b]" /><h2 className="font-display text-lg font-bold">Master Lokasi Operasional</h2></div>
              <p className="text-xs text-[#6b7688] mt-1">Sumber resmi lokasi untuk penerimaan, pengeluaran, Grup Muat, dan Mandor Bongkar. Sistem tidak lagi menebak grup dari tulisan lokasi.</p>
            </div>
            {isAdmin && <button onClick={addLocation} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#2563eb] text-[#60a5fa]"><Plus size={14} /> Tambah Lokasi</button>}
          </div>
          <div className="space-y-3">
            {locations.map((item, index) => (
              <div key={`${item.code}-${index}`} className="rounded-xl border border-[#202a38] bg-[#0b0f17] p-3">
                <div className="grid grid-cols-1 md:grid-cols-12 gap-2 items-end">
                  <div className="md:col-span-1"><label className="text-[10px] text-[#8b93a1]">Kode</label><input disabled={!isAdmin} value={item.code} onChange={(e) => updateLocation(index, { code: e.target.value })} className="w-full bg-transparent border-b border-[#242f3d] py-1.5 text-sm outline-none" placeholder="25" /></div>
                  <div className="md:col-span-2"><label className="text-[10px] text-[#8b93a1]">Nama Lokasi</label><input disabled={!isAdmin} value={item.name} onChange={(e) => updateLocation(index, { name: e.target.value })} className="w-full bg-transparent border-b border-[#242f3d] py-1.5 text-sm outline-none" placeholder="GBB 25" /></div>
                  <div className="md:col-span-2"><label className="text-[10px] text-[#8b93a1]">Jenis</label><select disabled={!isAdmin} value={item.type || 'LAINNYA'} onChange={(e) => updateLocation(index, { type: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2 text-xs"><option>GBB</option><option>MP</option><option>RTR</option><option>KONSINYASI</option><option>RUSAK</option><option>LAINNYA</option></select></div>
                  <div className="md:col-span-3"><label className="text-[10px] text-[#8b93a1]">Grup Muat</label><select disabled={!isAdmin || !item.loadingCostEnabled} value={item.loadingGroup || ''} onChange={(e) => updateLocation(index, { loadingGroup: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2 text-xs disabled:opacity-50"><option value="">Tidak Ada</option><option>GRUP 1 - GBB 17-20</option><option>GRUP 2 - MP1/21-24</option><option>GRUP 3 - RTR</option></select></div>
                  <div className="md:col-span-3"><label className="text-[10px] text-[#8b93a1]">Mandor Bongkar</label><select disabled={!isAdmin || !item.unloadingCostEnabled} value={item.unloadingGroup || ''} onChange={(e) => updateLocation(index, { unloadingGroup: e.target.value })} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-2 py-2 text-xs disabled:opacity-50"><option value="">Tidak Ada</option><option>MANDOR 1 - GBB 17-20</option><option>MANDOR 2 - MP1/GBB 21-24</option></select></div>
                  <div className="md:col-span-1 flex justify-end">{isAdmin && <button type="button" onClick={() => removeLocation(index)} className="p-2 text-[#f87171]" title="Hapus lokasi"><Trash2 size={15} /></button>}</div>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {[
                    ['allowInbound', 'Penerimaan'],
                    ['allowOutbound', 'Pengeluaran'],
                    ['loadingCostEnabled', 'Biaya Muat'],
                    ['unloadingCostEnabled', 'Biaya Bongkar'],
                    ['active', 'Aktif'],
                  ].map(([key, label]) => (
                    <button key={key} type="button" disabled={!isAdmin} onClick={() => updateLocation(index, { [key]: !item[key] })} className={`text-xs px-2.5 py-1.5 rounded-md border disabled:opacity-60 ${item[key] ? 'border-[#22c55e]/50 text-[#4ade80]' : 'border-[#4b5563] text-[#9ca3af]'}`}>{label}: {item[key] ? 'Ya' : 'Tidak'}</button>
                  ))}
                </div>
              </div>
            ))}
          </div>
          {isAdmin && <button onClick={saveLocations} disabled={savingLocations} className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg mt-4 disabled:opacity-60"><Save size={15} /> {savingLocations ? 'Menyimpan…' : 'Simpan Master Lokasi'}</button>}
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

        <div className="card-surface p-6 lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
            <div className="flex items-center gap-2"><CalendarDays size={18} className="text-[#f59e0b]" /><h2 className="font-display text-lg font-bold">Master Hari Libur / Tanggal Merah</h2></div>
            {isAdmin && <button onClick={addHoliday} className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-[#2563eb] text-[#60a5fa]"><Plus size={14} /> Tambah Hari Libur</button>}
          </div>
          <div className="space-y-2">
            {holidays.length === 0 ? <div className="text-sm text-[#8b93a1] py-2">Sabtu dan Minggu dihitung otomatis. Tambahkan tanggal merah hari kerja bila diperlukan.</div> : holidays.map((item, index) => (
              <div key={`${item.date}-${index}`} className="grid grid-cols-1 sm:grid-cols-[180px_1fr_auto_auto] gap-2 items-center rounded-lg bg-[#0b0f17] border border-[#151d28] p-2.5">
                <input type="date" disabled={!isAdmin} value={item.date || ''} onChange={(e) => updateHoliday(index, { date: e.target.value })} className="bg-transparent border border-[#242f3d] rounded-lg px-3 py-2 text-sm" />
                <input disabled={!isAdmin} value={item.name || ''} onChange={(e) => updateHoliday(index, { name: e.target.value })} placeholder="Nama hari libur / tanggal merah" className="bg-transparent border border-[#242f3d] rounded-lg px-3 py-2 text-sm" />
                <button type="button" disabled={!isAdmin} onClick={() => updateHoliday(index, { active: item.active === false })} className={`text-xs px-2.5 py-1.5 rounded-md border ${item.active === false ? 'border-[#4b5563] text-[#9ca3af]' : 'border-[#22c55e]/50 text-[#4ade80]'}`}>{item.active === false ? 'Nonaktif' : 'Aktif'}</button>
                {isAdmin && <button type="button" onClick={() => removeHoliday(index)} className="p-2 text-[#f87171]" title="Hapus hari libur"><Trash2 size={15} /></button>}
              </div>
            ))}
          </div>
          {isAdmin && <button onClick={saveHolidays} disabled={savingHolidays} className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg mt-4 disabled:opacity-60"><Save size={15} /> {savingHolidays ? 'Menyimpan…' : 'Simpan Hari Libur'}</button>}
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
          <div className="flex items-center justify-between gap-4 p-3 rounded-lg bg-[#0b0f17] border border-[#151d28]">
            <div>
              <div className="text-sm font-medium">Mode terang</div>
              <div className="text-xs text-[#6b7688]">{theme === 'light' ? 'Tampilan terang sedang digunakan' : 'Gunakan latar terang untuk kenyamanan membaca'}</div>
            </div>
            <Toggle
              on={theme === 'light'}
              onClick={() => {
                const next = theme === 'light' ? 'dark' : 'light';
                setTheme(next);
                toast.success(`Mode ${next === 'light' ? 'terang' : 'gelap'} diaktifkan`);
              }}
            />
          </div>
          <p className="text-xs text-[#6b7688] mt-4">Pilihan ini disimpan di browser ini dan tidak mengubah tampilan pengguna lain.</p>
        </div>


        <div className="card-surface p-6">
          <div className="flex items-center gap-2 mb-4">
            <Link2 size={18} className="text-[#60a5fa]" />
            <h2 className="font-display text-lg font-bold">Integrasi Marketplace</h2>
          </div>
          <p className="text-sm text-[#8b93a1]">
            Kelola akun Shopee, Tokopedia & Shop, TikTok Shop, mapping SKU, status koneksi, preview stok, serta log webhook dari halaman pengaturan khusus.
          </p>
          <p className="text-xs text-[#6b7688] mt-2">
            App ID, secret, partner key, access token, dan webhook key tetap disimpan aman di Railway Variables dan tidak ditulis ke source code.
          </p>
          <Link
            to="/pengaturan/marketplace"
            className="btn-primary inline-flex items-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-lg mt-4"
          >
            <Link2 size={15} /> Buka Pengaturan Marketplace
          </Link>
        </div>

        {isAdmin && <ProductionSafetyPanel />}

        <div className="card-surface p-6">
          <div className="flex items-center gap-2 mb-5">
            <Database size={18} className="text-[#22c55e]" />
            <h2 className="font-display text-lg font-bold">Data</h2>
          </div>
          <div className="space-y-3">
            {isSuperadmin ? (
              <>
                <button
                  type="button"
                  data-testid="reset-operational-btn"
                  onClick={resetOperationalData}
                  disabled={resettingOperational}
                  className="w-full text-left p-3 rounded-lg bg-[#2a1408]/30 border border-[#92400e] hover:border-[#f59e0b] transition-colors text-sm disabled:opacity-50"
                >
                  <div className="font-semibold text-[#fbbf24]">{resettingOperational ? 'Memproses Reset Operasional…' : 'Reset Data Operasional — Pertahankan Master SKU'}</div>
                  <p className="text-xs text-[#d6b873] mt-1">Mengosongkan seluruh saldo stok dan data transaksi. Master SKU/produk, supplier, user, gudang/lokasi, template Paket, dan konfigurasi marketplace tetap ada.</p>
                  <p className="text-[10px] text-[#8b93a1] mt-2">Wajib: unduh Backup PEPEG dan aktifkan Maintenance Mode terlebih dahulu.</p>
                </button>
                <div data-testid="reset-data-locked" className="w-full p-3 rounded-lg bg-[#0b0f17] border border-[#243044] text-sm">
                  <div className="font-semibold text-[#f87171]">Reset Total termasuk Master SKU tetap dikunci</div>
                  <p className="text-xs text-[#8b93a1] mt-1">Fitur di atas hanya Reset Operasional. SKU dan master tidak ikut dihapus.</p>
                </div>
              </>
            ) : isAdmin ? (
              <div className="w-full p-3 rounded-lg bg-[#0b0f17] border border-[#243044] text-sm text-[#8b93a1]">Reset Operasional hanya dapat dilakukan oleh Superadmin.</div>
            ) : (
              <p className="text-sm text-[#6b7688] p-3">Reset produksi dikunci.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Pengaturan;
