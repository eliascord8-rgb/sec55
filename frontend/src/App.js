import "@/index.css";
import { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Landing from "@/pages/Landing";
import Admin from "@/pages/Admin";
import OrderPage from "@/pages/OrderPage";
import StatusPage from "@/pages/StatusPage";
import ClientAuth from "@/pages/ClientAuth";
import ClientDashboard from "@/pages/ClientDashboard";
import Splash from "@/components/Splash";
import { AuthProvider } from "@/context/AuthContext";
import { Toaster } from "@/components/ui/sonner";

function App() {
  const [splashDone, setSplashDone] = useState(
    typeof sessionStorage !== "undefined" && sessionStorage.getItem("bs_splash_done") === "1"
  );

  useEffect(() => {
    if (splashDone) sessionStorage.setItem("bs_splash_done", "1");
  }, [splashDone]);

  return (
    <div className="min-h-screen bg-[#050505] text-white">
      {!splashDone && <Splash onDone={() => setSplashDone(true)} />}
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/order/:serviceId" element={<OrderPage />} />
            <Route path="/status/:orderId" element={<StatusPage />} />
            <Route path="/client" element={<ClientAuth />} />
            <Route path="/client/dashboard" element={<ClientDashboard />} />
            <Route path="/admin" element={<Admin />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
      <Toaster theme="dark" />
    </div>
  );
}

export default App;
