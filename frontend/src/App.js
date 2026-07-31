import "@/index.css";
import { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Landing from "@/pages/Landing";
import Admin from "@/pages/Admin";
import OrderPage from "@/pages/OrderPage";
import StatusPage from "@/pages/StatusPage";
import ClientAuth from "@/pages/ClientAuth";
import ResetPassword from "@/pages/ResetPassword";
import ClientDashboard from "@/pages/ClientDashboard";
import DbManager from "@/pages/DbManager";
import TikTokFinder from "@/pages/TikTokFinder";
import Splash from "@/components/Splash";
import MaintenanceGate from "@/components/MaintenanceGate";
import GoogleAuthCallback from "@/components/GoogleAuthCallback";
import LiveChatFAB from "@/components/LiveChatFAB";
import GlobalSupportWidget from "@/components/GlobalSupportWidget";
import { AuthProvider } from "@/context/AuthContext";
import { LanguageProvider } from "@/context/LanguageContext";
import { CurrencyProvider } from "@/context/CurrencyContext";
import { FeaturesProvider } from "@/context/FeaturesContext";
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
      <LanguageProvider>
        <CurrencyProvider>
          <FeaturesProvider>
            <AuthProvider>
              <BrowserRouter>
              <GoogleAuthCallback />
              <MaintenanceGate>
                <Routes>
                  <Route path="/" element={<Landing />} />
                  <Route path="/order/:serviceId" element={<OrderPage />} />
                  <Route path="/status/:orderId" element={<StatusPage />} />
                  <Route path="/client" element={<ClientDashboard />} />
                  <Route path="/client/login" element={<ClientDashboard />} />
                  <Route path="/reset" element={<ResetPassword />} />
                  <Route path="/client/dashboard" element={<ClientDashboard />} />
                  <Route path="/admin" element={<Admin />} />
                  <Route path="/db-manager" element={<DbManager />} />
                  <Route path="/tiktok-finder" element={<TikTokFinder />} />
                </Routes>
                <LiveChatFAB />
                <GlobalSupportWidget />
              </MaintenanceGate>
            </BrowserRouter>
          </AuthProvider>
          </FeaturesProvider>
        </CurrencyProvider>
      </LanguageProvider>
      <Toaster theme="dark" />
    </div>
  );
}

export default App;
