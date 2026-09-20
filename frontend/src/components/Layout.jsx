import React, { useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { LayoutGrid, Boxes, Layers, ArrowLeftRight, Send, History, ClipboardList, Truck, MonitorSmartphone, Users, Settings, PlusCircle, LogOut, Menu, ChevronDown, PackageSearch, Workflow, ShoppingCart, ShieldCheck, ClipboardCheck, TriangleAlert, RefreshCcw, Activity, CalendarClock, PackageX, Store, ShoppingBag, PackagePlus, Link2, FileInput } from 'lucide-react';
import { useData } from '../context/DataContext';
import { hasPermission, roleLabel } from '../lib/permissions';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from './ui/sheet';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from './ui/dropdown-menu';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from './ui/accordion';

const NAV_GROUPS = [
  { label: 'Dashboard', icon: LayoutGrid, to: '/' },
  {
    label: 'Inventori', icon: PackageSearch, items: [
      { to: '/produk', label: 'Daftar Produk', icon: Boxes, permission: 'mainInventory' },
      { to: '/tumpukan', label: 'Tumpukan Stok', icon: Layers, permission: 'mainInventory' },
      { to: '/fefo', label: 'Lot & FEFO', icon: CalendarClock, permission: 'mainInventory' },
      { to: '/area-barang-rusak', label: 'Area Barang Rusak', icon: PackageX, permission: 'mainInventory' },
      { to: '/opname-gudang', label: 'Stock Opname GBB', icon: ClipboardCheck, permission: 'mainInventory' },
      { to: '/opname-konsinyasi', label: 'Opname Bazar/E-commerce', icon: ClipboardCheck, permission: 'consignmentView' },
    ],
  },
  {
    label: 'Bazar & E-commerce', icon: ShoppingBag, items: [
      { to: '/bazar-operasional', label: 'Perjalanan Bazar', icon: Store, permission: 'bazarOps' },
      { to: '/bazar-paket', label: 'Paket Bazar', icon: PackagePlus, permission: 'bazarOps' },
      { to: '/bazar-nd-eksternal', label: 'ND Gudang Lain', icon: FileInput, permission: 'bazarOps' },
      { to: '/ecom-operasional', label: 'Operasional E-commerce', icon: ShoppingBag, permission: 'ecomOps' },
    ],
  },
  {
    label: 'Operasional', icon: Workflow, items: [
      { to: '/catat', label: 'Catat Stok', icon: ArrowLeftRight, permission: 'operations' },
      { to: '/temuan-kerusakan', label: 'Temuan Kerusakan', icon: TriangleAlert, permission: 'operations' },
      { to: '/retur-pemasok', label: 'Retur / Ganti Pemasok', icon: RefreshCcw, permission: 'operations' },
      { to: '/pengeluaran', label: 'Pengeluaran', icon: Send, permission: 'outboundPage' },
      { to: '/monitoring-so', label: 'Monitoring SO', icon: ClipboardList, permission: 'outboundPage' },
      { to: '/koreksi-operasional', label: 'Koreksi Operasional', icon: ShieldCheck, permission: 'corrections' },
      { to: '/antrian', label: 'Layar Antrian', icon: MonitorSmartphone, permission: 'mainInventory' },
    ],
  },
  {
    label: 'Pengadaan', icon: ShoppingCart, items: [
      { to: '/po', label: 'Purchase Order', icon: ClipboardList, permission: 'mainInventory' },
      { to: '/supplier', label: 'Supplier', icon: Truck, permission: 'mainInventory' },
    ],
  },
  {
    label: 'Riwayat', icon: History, items: [
      { to: '/riwayat', label: 'Riwayat Gudang', icon: History, permission: 'mainInventory' },
      { to: '/laporan-operasional', label: 'Laporan Operasional', icon: FileInput, permission: 'mainInventory' },
      { to: '/riwayat-bazar-ecom', label: 'Riwayat Bazar/E-commerce', icon: ShoppingBag, permission: 'consignmentHistory' },
    ],
  },
  {
    label: 'Administrasi', icon: ShieldCheck, items: [
      { to: '/kontrol-integritas', label: 'Kontrol Integritas', icon: Activity, permission: 'masterWrite' },
      { to: '/import', label: 'Import Master XLSX', icon: FileInput, permission: 'masterWrite' },
      { to: '/pengguna', label: 'Pengguna', icon: Users, permission: 'users' },
      { to: '/pengaturan', label: 'Pengaturan', icon: Settings, permission: 'settings' },
      { to: '/pengaturan/marketplace', label: 'Integrasi Marketplace', icon: Link2, permission: 'settings' },
    ],
  },
];

const Layout = ({ children }) => {
  const { user, logout, canWrite, settings } = useData();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const canSeeItem = (item) => !item.permission || hasPermission(user?.role, item.permission);
  const visibleGroups = NAV_GROUPS
    .filter((group) => !group.permission || hasPermission(user?.role, group.permission))
    .map((group) => group.items ? { ...group, items: group.items.filter(canSeeItem) } : group)
    .filter((group) => group.to || group.items.length > 0);
  const isPathActive = (to) => to === '/' ? location.pathname === '/' : location.pathname.startsWith(to);
  const isGroupActive = (group) => group.to ? isPathActive(group.to) : group.items.some((item) => isPathActive(item.to));

  const goToTransaction = () => {
    setMobileMenuOpen(false);
    navigate('/catat');
  };

  const handleLogout = () => {
    setMobileMenuOpen(false);
    logout();
  };

  return (
    <div className="app-bg">
      <header className="sticky top-0 z-40 backdrop-blur-xl bg-[#070a10]/80 border-b border-[#161d29]">
        <div className="max-w-[1440px] mx-auto px-4 sm:px-6 py-3 flex items-center gap-3 xl:gap-4">
          <div className="flex items-center gap-3 shrink-0">
            <div className="w-12 h-10 sm:w-14 sm:h-11 rounded-xl bg-white px-1.5 py-1 flex items-center justify-center shadow-lg overflow-hidden">
              <img src="/bulog-sunter.png" alt="BULOG Sunter Timur I & II" className="w-full h-full object-contain" />
            </div>
            <div className="leading-tight">
              <div className="font-display font-bold text-[15px] tracking-tight">PEPEG</div>
              <div className="text-[9px] text-[#aab4c4] max-w-[230px] truncate">Platform Elektronik Pengendalian dan Evaluasi Gudang</div>
              <div className="label-mono text-[8px] max-w-[180px] sm:max-w-none truncate">{settings?.warehouse || 'Gudang Sunter Timur I & II'}</div>
            </div>
          </div>

          <nav className="hidden xl:flex flex-1 flex-wrap items-center justify-center gap-1 px-2">
            {visibleGroups.map((group) => group.to ? (
              <NavLink key={group.to} to={group.to} end={group.to === '/'} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
                <group.icon size={15} /><span>{group.label}</span>
              </NavLink>
            ) : (
              <DropdownMenu key={group.label}>
                <DropdownMenuTrigger asChild>
                  <button type="button" className={`nav-link outline-none ${isGroupActive(group) ? 'active' : ''}`}><group.icon size={15} /><span>{group.label}</span><ChevronDown size={13} /></button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="min-w-52 border-[#242f3d] bg-[#0d121b] p-1.5 text-[#e7ebf2] shadow-xl">
                  {group.items.map((item) => (
                    <DropdownMenuItem key={item.to} asChild className="cursor-pointer rounded-lg p-0 focus:bg-[#172033] focus:text-white">
                      <NavLink to={item.to} className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-sm ${isPathActive(item.to) ? 'bg-[#2563eb]/15 text-[#60a5fa]' : 'text-[#aab4c4]'}`}><item.icon size={17} /><span>{item.label}</span></NavLink>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            ))}
          </nav>

          <div className="hidden xl:flex items-center gap-2 shrink-0">
            {canWrite && <button data-testid="header-catat-btn" onClick={() => navigate('/catat')} className="btn-primary inline-flex items-center gap-1.5 text-xs font-semibold px-3.5 py-2 rounded-lg"><PlusCircle size={15} /> Catat Transaksi</button>}
            <div className="flex items-center gap-2 pl-2">
              <div className="text-right leading-tight hidden md:block"><div className="text-[13px] font-semibold">{user?.name}</div><div className="label-mono text-[9px]">{roleLabel(user?.role)}</div></div>
              <button data-testid="logout-btn" onClick={logout} title="Keluar" className="w-9 h-9 rounded-lg border border-[#242f3d] flex items-center justify-center text-[#8b93a1] hover:text-white hover:bg-[#141a24] transition-colors"><LogOut size={16} /></button>
            </div>
          </div>

          <div className="ml-auto xl:hidden">
            <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
              <SheetTrigger asChild><button type="button" aria-label="Buka menu navigasi" className="w-11 h-11 rounded-xl border border-[#242f3d] flex items-center justify-center text-[#c7d0dc] hover:text-white hover:bg-[#141a24] transition-colors"><Menu size={21} /></button></SheetTrigger>
              <SheetContent side="right" className="w-[min(88vw,360px)] h-[100dvh] p-0 border-[#242f3d] bg-[#090d14] text-[#e7ebf2] flex flex-col">
                <SheetHeader className="text-left px-5 pt-6 pb-4 border-b border-[#1a222e]"><SheetTitle className="font-display text-lg text-white">Menu PEPEG</SheetTitle><SheetDescription className="text-[#8b93a1]">{user?.name || 'Pengguna'} · {roleLabel(user?.role)}</SheetDescription></SheetHeader>
                <nav aria-label="Navigasi mobile" className="flex-1 overflow-y-auto px-3 py-4">
                  {visibleGroups.map((group) => group.to ? (
                    <NavLink key={group.to} to={group.to} end={group.to === '/'} onClick={() => setMobileMenuOpen(false)} className={`mobile-nav-link mb-1 ${isGroupActive(group) ? 'active' : ''}`}><group.icon size={19} /><span>{group.label}</span></NavLink>
                  ) : (
                    <Accordion key={group.label} type="single" collapsible defaultValue={isGroupActive(group) ? group.label : undefined}>
                      <AccordionItem value={group.label} className="border-0">
                        <AccordionTrigger className={`mobile-nav-link mb-1 py-3 hover:no-underline [&>svg]:ml-auto ${isGroupActive(group) ? 'active' : ''}`}><span className="flex items-center gap-3"><group.icon size={19} />{group.label}</span></AccordionTrigger>
                        <AccordionContent className="pb-2 pl-4 space-y-1">{group.items.map((item) => <NavLink key={item.to} to={item.to} onClick={() => setMobileMenuOpen(false)} className={`mobile-nav-link ${isPathActive(item.to) ? 'active' : ''}`}><item.icon size={18} /><span>{item.label}</span></NavLink>)}</AccordionContent>
                      </AccordionItem>
                    </Accordion>
                  ))}
                </nav>
                <div className="p-4 border-t border-[#1a222e] space-y-2 pb-[max(1rem,env(safe-area-inset-bottom))]">
                  {canWrite && <button data-testid="mobile-catat-btn" onClick={goToTransaction} className="btn-primary w-full inline-flex items-center justify-center gap-2 text-sm font-semibold px-4 py-3 rounded-xl"><PlusCircle size={18} /> Catat Transaksi</button>}
                  <button data-testid="mobile-logout-btn" onClick={handleLogout} className="w-full inline-flex items-center justify-center gap-2 text-sm font-semibold px-4 py-3 rounded-xl border border-[#242f3d] text-[#c7d0dc] hover:text-white hover:bg-[#141a24] transition-colors"><LogOut size={18} /> Keluar</button>
                </div>
              </SheetContent>
            </Sheet>
          </div>
        </div>
      </header>
      <main className="app-main max-w-[1440px] mx-auto px-4 sm:px-6 py-5 sm:py-8 fade-up">{children}</main>
    </div>
  );
};

export default Layout;
