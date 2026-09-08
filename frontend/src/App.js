import React from 'react';
import './App.css';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'sonner';
import { DataProvider, useData } from './context/DataContext';
import Layout from './components/Layout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import DaftarProduk from './pages/DaftarProduk';
import CatatStok from './pages/CatatStok';
import Riwayat from './pages/Riwayat';
import Pengeluaran from './pages/Pengeluaran';
import PurchaseOrder from './pages/PurchaseOrder';
import Supplier from './pages/Supplier';
import LayarAntrian from './pages/LayarAntrian';
import Pengguna from './pages/Pengguna';
import Pengaturan from './pages/Pengaturan';
import ImportData from './pages/ImportData';
import TumpukanStok from './pages/TumpukanStok';

const Loading = () => (
  <div className="app-bg flex items-center justify-center min-h-screen">
    <div className="text-[#8b93a1] text-sm animate-pulse">Memuat...</div>
  </div>
);

const Protected = ({ children }) => {
  const { user, checking } = useData();
  if (checking) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
};

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Protected><Dashboard /></Protected>} />
      <Route path="/produk" element={<Protected><DaftarProduk /></Protected>} />
      <Route path="/import" element={<Protected><ImportData /></Protected>} />
      <Route path="/tumpukan" element={<Protected><TumpukanStok /></Protected>} />
      <Route path="/catat" element={<Protected><CatatStok /></Protected>} />
      <Route path="/pengeluaran" element={<Protected><Pengeluaran /></Protected>} />
      <Route path="/riwayat" element={<Protected><Riwayat /></Protected>} />
      <Route path="/po" element={<Protected><PurchaseOrder /></Protected>} />
      <Route path="/supplier" element={<Protected><Supplier /></Protected>} />
      <Route path="/antrian" element={<Protected><LayarAntrian /></Protected>} />
      <Route path="/pengguna" element={<Protected><Pengguna /></Protected>} />
      <Route path="/pengaturan" element={<Protected><Pengaturan /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <DataProvider>
      <Toaster theme="dark" position="bottom-right" richColors />
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </DataProvider>
  );
}

export default App;
