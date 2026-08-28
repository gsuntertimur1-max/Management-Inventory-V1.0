import { Routes, Route } from "react-router-dom";
import RequireAuth from "@/components/RequireAuth";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Products from "@/pages/Products";
import ImportProducts from "@/pages/ImportProducts";
import StockMovement from "@/pages/StockMovement";
import Transactions from "@/pages/Transactions";
import Suppliers from "@/pages/Suppliers";
import PurchaseOrders from "@/pages/PurchaseOrders";
import Shipments from "@/pages/Shipments";
import QueueDisplay from "@/pages/QueueDisplay";
import SettingsPage from "@/pages/Settings";
import Users from "@/pages/Users";
import StockLocations from "@/pages/StockLocations";
import PrintDeliveryNote from "@/pages/PrintDeliveryNote";
import PrintLoadingSlip from "@/pages/PrintLoadingSlip";

// One <Route> per page in src/pages; BrowserRouter already wraps this in main.tsx.
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route
        path="/"
        element={
          <RequireAuth action="stock:read">
            <Dashboard />
          </RequireAuth>
        }
      />
      <Route
        path="/products"
        element={
          <RequireAuth action="procurement:write">
            <Products />
          </RequireAuth>
        }
      />
      <Route
        path="/import"
        element={
          <RequireAuth action="procurement:write">
            <ImportProducts />
          </RequireAuth>
        }
      />
      <Route
        path="/stock-movement"
        element={
          <RequireAuth action="sales:write|procurement:write">
            <StockMovement />
          </RequireAuth>
        }
      />
      <Route
        path="/lokasi"
        element={
          <RequireAuth action="stock:read">
            <StockLocations />
          </RequireAuth>
        }
      />
      <Route
        path="/transactions"
        element={
          <RequireAuth action="inventory:read">
            <Transactions />
          </RequireAuth>
        }
      />
      <Route
        path="/suppliers"
        element={
          <RequireAuth action="procurement:write">
            <Suppliers />
          </RequireAuth>
        }
      />
      <Route
        path="/purchase-orders"
        element={
          <RequireAuth action="procurement:write">
            <PurchaseOrders />
          </RequireAuth>
        }
      />
      <Route
        path="/shipments"
        element={
          <RequireAuth action="sales:read">
            <Shipments />
          </RequireAuth>
        }
      />
      <Route
        path="/antrian"
        element={
          <RequireAuth action="sales:read">
            <QueueDisplay />
          </RequireAuth>
        }
      />
      <Route
        path="/settings"
        element={
          <RequireAuth action="settings:write">
            <SettingsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/users"
        element={
          <RequireAuth action="users:manage">
            <Users />
          </RequireAuth>
        }
      />
      <Route
        path="/print/surat-jalan"
        element={
          <RequireAuth action="sales:read">
            <PrintDeliveryNote />
          </RequireAuth>
        }
      />
      <Route
        path="/print/bon-muat/:id"
        element={
          <RequireAuth action="sales:read">
            <PrintLoadingSlip />
          </RequireAuth>
        }
      />
    </Routes>
  );
}
