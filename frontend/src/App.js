import React from 'react';
import './App.css';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'sonner';
import { DataProvider, useData } from './context/DataContext';
import Layout from './components/Layout';
import PengeluaranReservationPanel from './components/PengeluaranReservationPanel';
import OutboundDocumentIntegrityPanel from './components/OutboundDocumentIntegrityPanel';
import Login from './pages/Login';
import DashboardUnified from './pages/DashboardUnified';
import DaftarProduk from './pages/DaftarProduk';
import CatatStok from './pages/CatatStok';
import Riwayat from './pages/Riwayat';
import Pengeluaran from './pages/Pengeluaran';
import PurchaseOrder from './pages/PurchaseOrder';
import Supplier from './pages/Supplier';
import LayarAntrianEnhanced from './pages/LayarAntrianEnhanced';
import Pengguna from './pages/Pengguna';
import Pengaturan from './pages/Pengaturan';
import ImportData from './pages/ImportData';
import TumpukanUnified from './pages/TumpukanUnified';
import MutasiTumpukan from './pages/MutasiTumpukan';
import OpnameKonsinyasi from './pages/OpnameKonsinyasi';
import BazarOperasional from './pages/BazarOperasional';
import BazarPaket from './pages/BazarPaket';
import EcomOperasional from './pages/EcomOperasional';
import MarketplaceIntegration from './pages/MarketplaceIntegration';
import KoreksiOperasional from './pages/KoreksiOperasional';
import KontrolIntegritas from './pages/KontrolIntegritas';
import OpnameGudang from './pages/OpnameGudang';
import FefoLot from './pages/FefoLot';
import AreaBarangRusak from './pages/AreaBarangRusak';
import { hasPermission, roleLabel } from './lib/permissions';

const Loading = () => (
  <div className="app-bg flex items-center justify-center min-h-screen">
    <div className="text-[#8b93a1] text-sm animate-pulse">Memuat...</div>
  </div>
);

const AccessDenied = ({ userRole }) => (
  <div className="card-surface p-8 text-center max-w-xl mx-auto">
    <div className="label-mono mb-2">Akses Terbatas</div>
    <h1 className="font-display text-2xl font-bold">Menu tidak tersedia untuk peran ini</h1>
    <p className="text-[#8b93a1] mt-2">Peran Anda ({roleLabel(userRole)}) tidak memiliki hak untuk membuka proses ini.</p>
  </div>
);

const Protected = ({ children, permission }) => {
  const { user, checking } = useData();
  if (checking) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  if (permission && !hasPermission(user.role, permission)) {
    return <Layout><AccessDenied userRole={user.role} /></Layout>;
  }
  return <Layout>{children}</Layout>;
};

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Protected><DashboardUnified /></Protected>} />
      <Route path="/produk" element={<Protected permission="mainInventory"><DaftarProduk /></Protected>} />
      <Route path="/import" element={<Protected permission="masterWrite"><ImportData /></Protected>} />
      <Route path="/tumpukan" element={<Protected><TumpukanUnified /></Protected>} />
      <Route path="/fefo" element={<Protected permission="mainInventory"><FefoLot /></Protected>} />
      <Route path="/area-barang-rusak" element={<Protected permission="mainInventory"><AreaBarangRusak /></Protected>} />
      <Route path="/opname-gudang" element={<Protected permission="mainInventory"><OpnameGudang /></Protected>} />
      <Route path="/opname-konsinyasi" element={<Protected permission="consignmentView"><OpnameKonsinyasi /></Protected>} />
      <Route path="/bazar-operasional" element={<Protected permission="bazarOps"><BazarOperasional /></Protected>} />
      <Route path="/bazar-paket" element={<Protected permission="bazarOps"><BazarPaket /></Protected>} />
      <Route path="/ecom-operasional" element={<Protected permission="ecomOps"><EcomOperasional /></Protected>} />
      <Route path="/pengaturan/marketplace" element={<Protected permission="settings"><MarketplaceIntegration /></Protected>} />
      <Route path="/marketplace" element={<Protected permission="settings"><Navigate to="/pengaturan/marketplace" replace /></Protected>} />
      <Route path="/catat" element={<Protected permission="operations"><CatatStok /></Protected>} />
      <Route path="/mutasi-tumpukan" element={<Protected permission="operations"><MutasiTumpukan /></Protected>} />
      <Route path="/temuan-kerusakan" element={<Protected permission="operations"><CatatStok panel="damage" /></Protected>} />
      <Route path="/retur-pemasok" element={<Protected permission="operations"><CatatStok panel="supplier-return" /></Protected>} />
      <Route path="/pengeluaran" element={<Protected permission="outboundPage"><><PengeluaranReservationPanel /><Pengeluaran /></></Protected>} />
      <Route path="/koreksi-operasional" element={<Protected permission="corrections"><KoreksiOperasional /></Protected>} />
      <Route path="/kontrol-integritas" element={<Protected permission="masterWrite"><><OutboundDocumentIntegrityPanel /><KontrolIntegritas /></></Protected>} />
      <Route path="/riwayat" element={<Protected permission="mainInventory"><Riwayat /></Protected>} />
      <Route path="/po" element={<Protected permission="mainInventory"><PurchaseOrder /></Protected>} />
      <Route path="/supplier" element={<Protected permission="mainInventory"><Supplier /></Protected>} />
      <Route path="/antrian" element={<Protected permission="mainInventory"><LayarAntrianEnhanced /></Protected>} />
      <Route path="/pengguna" element={<Protected permission="users"><Pengguna /></Protected>} />
      <Route path="/pengaturan" element={<Protected permission="settings"><Pengaturan /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function AppShell() {
  const { theme } = useData();
  return <><Toaster theme={theme} position="bottom-right" richColors /><BrowserRouter><AppRoutes /></BrowserRouter></>;
}

function App() {
  return <DataProvider><AppShell /></DataProvider>;
}

export default App;
