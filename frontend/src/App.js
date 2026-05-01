import "@/index.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Landing from "@/pages/Landing";
import Admin from "@/pages/Admin";
import OrderPage from "@/pages/OrderPage";
import StatusPage from "@/pages/StatusPage";
import { Toaster } from "@/components/ui/sonner";

function App() {
  return (
    <div className="min-h-screen bg-[#050505] text-white">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/order/:serviceId" element={<OrderPage />} />
          <Route path="/status/:orderId" element={<StatusPage />} />
          <Route path="/admin" element={<Admin />} />
        </Routes>
      </BrowserRouter>
      <Toaster theme="dark" />
    </div>
  );
}

export default App;
