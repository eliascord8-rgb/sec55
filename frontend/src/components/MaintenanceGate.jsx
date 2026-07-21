import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Wrench, Sparkles } from "lucide-react";

// MaintenanceGate — polls /api/maintenance every 30s.
// When maintenance.enabled === true, replaces the whole app with a maintenance
// screen for regular clients.  Owner / admin / staff can still access the app
// so they can flip the switch off, and the /admin route is always allowed.
const POLL_MS = 30000;

export default function MaintenanceGate({ children }) {
  const [state, setState] = useState({ enabled: false, message: "" });
  const { user } = useAuth() || {};
  const loc = useLocation();

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await api.get("/maintenance");
        if (!cancelled) setState(r.data || { enabled: false });
      } catch { /* ignore */ }
    };
    tick();
    const t = setInterval(tick, POLL_MS);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  const isPrivileged = user && ["owner", "admin", "staff", "moderator"].includes(user.role);
  const onAdminRoute = loc.pathname.startsWith("/admin");

  if (state.enabled && !isPrivileged && !onAdminRoute) {
    return <MaintenanceScreen message={state.message} />;
  }
  return children;
}

function MaintenanceScreen({ message }) {
  return (
    <div
      data-testid="maintenance-screen"
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-[#0a1a0a] px-6"
    >
      <div className="max-w-lg w-full text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-500/15 border border-amber-500/40 text-[10px] uppercase tracking-widest text-amber-200 font-bold mb-8">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
          Scheduled maintenance
        </div>
        <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-emerald-500/15 border border-emerald-500/40 mb-8 shadow-[0_0_40px_rgba(52,211,153,0.25)]">
          <Wrench className="w-10 h-10 text-emerald-300" strokeWidth={2} />
        </div>
        <h1 className="font-display font-black text-3xl md:text-5xl tracking-tight text-white mb-5">
          Be right back.
        </h1>
        <p className="text-white/70 md:text-lg leading-relaxed max-w-md mx-auto font-manrope whitespace-pre-line">
          {message || "We're doing quick maintenance — we'll be back in a few minutes."}
        </p>
        <div className="mt-10 flex items-center justify-center gap-2 text-[10px] uppercase tracking-widest text-emerald-300/70 font-bold">
          <Sparkles className="w-3 h-3" />
          BetterSocial
        </div>
      </div>
    </div>
  );
}
