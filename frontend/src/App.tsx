import { Routes, Route } from "react-router-dom";
import Dashboard from "@/pages/Dashboard";
import Products from "@/pages/Products";
import StockMovement from "@/pages/StockMovement";
import Transactions from "@/pages/Transactions";
import Suppliers from "@/pages/Suppliers";

// One <Route> per page in src/pages; BrowserRouter already wraps this in main.tsx.
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/products" element={<Products />} />
      <Route path="/stock-movement" element={<StockMovement />} />
      <Route path="/transactions" element={<Transactions />} />
      <Route path="/suppliers" element={<Suppliers />} />
    </Routes>
  );
}
