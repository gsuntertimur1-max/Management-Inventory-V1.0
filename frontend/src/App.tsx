import { Routes, Route } from "react-router-dom";
import Dashboard from "@/pages/Dashboard";
import Products from "@/pages/Products";
import StockMovement from "@/pages/StockMovement";
import Transactions from "@/pages/Transactions";
import Suppliers from "@/pages/Suppliers";
import PurchaseOrders from "@/pages/PurchaseOrders";
import SettingsPage from "@/pages/Settings";
import PrintDeliveryNote from "@/pages/PrintDeliveryNote";
import PrintLoadingSlip from "@/pages/PrintLoadingSlip";

// One <Route> per page in src/pages; BrowserRouter already wraps this in main.tsx.
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/products" element={<Products />} />
      <Route path="/stock-movement" element={<StockMovement />} />
      <Route path="/transactions" element={<Transactions />} />
      <Route path="/suppliers" element={<Suppliers />} />
      <Route path="/purchase-orders" element={<PurchaseOrders />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/print/surat-jalan" element={<PrintDeliveryNote />} />
      <Route path="/print/bon-muat/:id" element={<PrintLoadingSlip />} />
    </Routes>
  );
}
