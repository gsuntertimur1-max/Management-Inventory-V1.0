import React from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { LayoutGrid, Boxes, Layers, ArrowLeftRight, Send, History, ClipboardList, Truck, MonitorSmartphone, Users, Settings, PlusCircle, LogOut } from 'lucide-react';
import { useData } from '../context/DataContext';
import { hasPermission, roleLabel } from '../lib/permissions';

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutGrid },
  { to: '/produk', label: 'Daftar Produk', icon: Boxes },
  { to: '/tumpukan', label: 'Tumpukan Stok', icon: Layers },
  { to: '/catat', label: 'Catat Stok', icon: ArrowLeftRight, permission: 'operations' },
  { to: '/pengeluaran', label: 'Pengeluaran', icon: Send, permission: 'outbound' },
  { to: '/riwayat', label: 'Riwayat', icon: History },
  { to: '/po', label: 'Purchase Order', icon: ClipboardList },
  { to: '/supplier', label: 'Supplier', icon: Truck },
  { to: '/antrian', label: 'Layar Antrian', icon: MonitorSmartphone },
  { to: '/pengguna', label: 'Pengguna', icon: Users, permission: 'users' },
  { to: '/pengaturan', label: 'Pengaturan', icon: Settings, permission: 'settings' },
];

const Layout = ({ children }) => {
  const { user, logout, canWrite, settings } = useData();
  const navigate = useNavigate();

  return (
    <div className="app-bg">
      <header className="sticky top-0 z-40 backdrop-blur-xl bg-[#070a10]/80 border-b border-[#161d29]">
        <div className="max-w-[1440px] mx-auto px-6 py-3 flex items-center gap-4">
          <div className="flex items-center gap-3 shrink-0">
            <div className="w-14 h-11 rounded-xl bg-white px-1.5 py-1 flex items-center justify-center shadow-lg overflow-hidden">
              <img src="/bulog-sunter.png" alt="BULOG Sunter Timur I & II" className="w-full h-full object-contain" />
            </div>
            <div className="leading-tight">
              <div className="font-display font-bold text-[15px] tracking-tight">BULOG</div>
              <div className="label-mono text-[9px]">{settings?.warehouse || 'Gudang Sunter Timur I & II'}</div>
            </div>
          </div>

          <nav className="flex-1 flex flex-wrap items-center justify-center gap-1 px-2">
            {NAV.filter((n) => !n.permission || hasPermission(user?.role, n.permission)).map((n) => (
              <NavLink key={n.to} to={n.to} end={n.to === '/'} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
                <n.icon size={15} />
                <span>{n.label}</span>
              </NavLink>
            ))}
          </nav>

          <div className="flex items-center gap-2 shrink-0">
            {canWrite && <button data-testid="header-catat-btn" onClick={() => navigate('/catat')} className="btn-primary inline-flex items-center gap-1.5 text-xs font-semibold px-3.5 py-2 rounded-lg">
              <PlusCircle size={15} /> Catat Transaksi
            </button>}
            <div className="flex items-center gap-2 pl-2">
              <div className="text-right leading-tight hidden md:block">
                <div className="text-[13px] font-semibold">{user?.name}</div>
                <div className="label-mono text-[9px]">{roleLabel(user?.role)}</div>
              </div>
              <button data-testid="logout-btn" onClick={logout} title="Keluar" className="w-9 h-9 rounded-lg border border-[#242f3d] flex items-center justify-center text-[#8b93a1] hover:text-white hover:bg-[#141a24] transition-colors">
                <LogOut size={16} />
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-[1440px] mx-auto px-6 py-8 fade-up">{children}</main>
    </div>
  );
};

export default Layout;
