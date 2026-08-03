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
import GlobalSupportWidget from "@/components/GlobalSupportWidget";
import ClientRoute from "@/components/ClientRoute";
import { AuthProvider } from "@/context/AuthContext";
import { LanguageProvider } from "@/context/LanguageContext";
import { CurrencyProvider } from "@/context/CurrencyContext";
import { FeaturesProvider } from "@/context/FeaturesContext";
import { Toaster } from "@/components/ui/sonner";
import { setupAppRefresh } from "@/lib/realtime";

function App() {
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    try {
      const buildMeta = document.querySelector('meta[name="app-build"]');
      const buildVersion = buildMeta?.getAttribute("content") || "unknown";
      const cachedVersion = localStorage.getItem("bs_app_build");
      if (cachedVersion && cachedVersion !== buildVersion) {
        window.location.reload();
      }
      localStorage.setItem("bs_app_build", buildVersion);
    } catch {}
  }, []);
  const [splashDone, setSplashDone] = useState(
    typeof sessionStorage !== "undefined" && sessionStorage.getItem("bs_splash_done") === "1"
  );

  useEffect(() => {
    if (splashDone) sessionStorage.setItem("bs_splash_done", "1");
  }, [splashDone]);

  useEffect(() => {
    const stop = setupAppRefresh(() => setRefreshToken((v) => v + 1));
    return stop;
  }, []);

  // Capture referral code from share links (?ref=CODE) — used at signup.
  useEffect(() => {
    try {
      const ref = new URLSearchParams(window.location.search).get("ref");
      if (ref) localStorage.setItem("bs_ref", ref.trim().toUpperCase());
    } catch { /* ignore */ }
  }, []);

  return (
    <div className="min-h-screen bg-[#050505] text-white">
      <div className="fixed bottom-3 right-3 z-[9999] hidden md:block">
        <button
          type="button"
          onClick={() => {
            try {
              localStorage.removeItem("bs_app_build");
            } catch {}
            window.location.reload();
          }}
          className="rounded-full border border-emerald-500/30 bg-[#0d2b12]/95 px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-emerald-200 shadow-lg backdrop-blur"
        >
          Refresh new updates
        </button>
      </div>
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
                  <Route path="/client" element={<ClientRoute />} />
                  <Route path="/client/login" element={<ClientAuth />} />
                  <Route path="/client/dashboard" element={<ClientDashboard key={`dashboard-${refreshToken}`} />} />
                  <Route path="/reset" element={<ResetPassword />} />
                  <Route path="/client/dashboard" element={<ClientDashboard key={`dashboard-${refreshToken}`} />} />
                  <Route path="/admin" element={<Admin key={`admin-${refreshToken}`} />} />
                  <Route path="/db-manager" element={<DbManager />} />
                  <Route path="/tiktok-finder" element={<TikTokFinder />} />
                </Routes>
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
