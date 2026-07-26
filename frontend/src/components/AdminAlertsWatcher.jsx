import { useState, useEffect, useRef } from "react";
import { adminApi } from "@/lib/api";
import { toast } from "sonner";
import { Loader2, AlertTriangle } from "lucide-react";

export const AdminAlertsWatcher = ({ token }) => {
  const [alerts, setAlerts] = useState([]);
  const [open, setOpen] = useState(false);
  const [busyId, setBusyId] = useState("");
  const [amounts, setAmounts] = useState({});
  const seenRef = useRef(new Set());

  const load = async () => {
    try {
      const r = await adminApi(token).get("/admin/alerts", { params: { status: "open" } });
      const list = r.data.alerts || [];
      setAlerts(list);
      const hasNew = list.some((a) => !seenRef.current.has(a.id));
      if (hasNew && list.length > 0) {
        list.forEach((a) => seenRef.current.add(a.id));
        setOpen(true);
      }
    } catch { /* silent */ }
  };

  useEffect(() => {
    load();
    const int = setInterval(load, 30000);
    return () => clearInterval(int);
    // eslint-disable-next-line
  }, [token]);

  const creditPartial = async (a) => {
    const amt = parseFloat(amounts[a.id] ?? a.paid_usd ?? 0);
    if (!amt || amt <= 0) { toast.error("Enter a valid amount"); return; }
    setBusyId(a.id);
    try {
      const r = await adminApi(token).post(`/admin/deposits/${a.tx_id}/credit-partial`, { amount: amt });
      toast.success(`Credited $${r.data.credited?.toFixed(2)} (+$${r.data.bonus?.toFixed(2)} bonus) to @${a.username}`);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Credit failed");
    } finally { setBusyId(""); }
  };

  const dismiss = async (a) => {
    setBusyId(a.id);
    try {
      await adminApi(token).post(`/admin/alerts/${a.id}/dismiss`);
      toast.success("Alert dismissed");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Dismiss failed");
    } finally { setBusyId(""); }
  };

  if (alerts.length === 0) return null;

  return (
    <>
      {/* Persistent banner when popup is closed */}
      {!open && (
        <button onClick={() => setOpen(true)} data-testid="admin-alerts-banner"
                className="fixed bottom-4 right-4 z-40 flex items-center gap-2 px-4 py-2.5 bg-red-950/90 border border-red-600/60 rounded-md text-red-200 text-xs font-bold shadow-xl hover:bg-red-900 animate-pulse">
          <AlertTriangle className="w-4 h-4" /> {alerts.length} payment alert{alerts.length > 1 ? "s" : ""} need attention
        </button>
      )}

      {open && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4" data-testid="admin-alerts-popup">
          <div className="bg-[#140a0a] border border-red-600/50 rounded-md w-full max-w-lg max-h-[80vh] overflow-y-auto p-5">
            <div className="flex items-center gap-2 mb-1">
              <AlertTriangle className="w-5 h-5 text-red-400" />
              <h3 className="font-black text-red-200">Missing funds — underpaid crypto deposits</h3>
            </div>
            <p className="text-[11px] text-white/50 mb-4">These users paid less than their invoice. Review and credit what they actually sent, or dismiss.</p>
            <div className="space-y-3">
              {alerts.map((a) => {
                const missing = Number(a.missing_usd || 0);
                const paid = Number(a.paid_usd || 0);
                return (
                  <div key={a.id} className="bg-black/40 border border-red-800/40 rounded p-3" data-testid={`admin-alert-${a.id}`}>
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="font-bold text-white">@{a.username || a.user_id}</span>
                      <span className="text-white/40">{new Date(a.created_at).toLocaleString()}</span>
                    </div>
                    <div className="grid grid-cols-3 gap-2 mt-2 text-center">
                      <div className="bg-white/5 rounded p-1.5">
                        <div className="text-[9px] uppercase tracking-widest text-white/40">Invoice</div>
                        <div className="font-mono font-bold text-white text-sm">${Number(a.invoice_amount || 0).toFixed(2)}</div>
                      </div>
                      <div className="bg-emerald-950/40 rounded p-1.5">
                        <div className="text-[9px] uppercase tracking-widest text-emerald-300/60">Deposited</div>
                        <div className="font-mono font-bold text-emerald-300 text-sm">${paid.toFixed(2)}</div>
                      </div>
                      <div className="bg-red-950/40 rounded p-1.5">
                        <div className="text-[9px] uppercase tracking-widest text-red-300/60">Missing</div>
                        <div className="font-mono font-bold text-red-300 text-sm">${missing.toFixed(2)}</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 mt-2.5">
                      <input type="number" step="0.01" min="0"
                             value={amounts[a.id] ?? paid}
                             onChange={(e) => setAmounts((m) => ({ ...m, [a.id]: e.target.value }))}
                             data-testid={`admin-alert-amount-${a.id}`}
                             className="w-24 bg-black/50 border border-white/15 rounded px-2 py-1.5 text-xs font-mono text-white outline-none focus:border-emerald-400" />
                      <button onClick={() => creditPartial(a)} disabled={busyId === a.id}
                              data-testid={`admin-alert-credit-${a.id}`}
                              className="px-3 py-1.5 bg-emerald-500 hover:bg-emerald-400 text-black rounded text-[11px] font-bold uppercase tracking-wider disabled:opacity-50 flex items-center gap-1">
                        {busyId === a.id ? <Loader2 className="w-3 h-3 animate-spin" /> : null} Credit paid amount
                      </button>
                      <button onClick={() => dismiss(a)} disabled={busyId === a.id}
                              data-testid={`admin-alert-dismiss-${a.id}`}
                              className="px-3 py-1.5 border border-white/15 rounded text-[11px] uppercase tracking-wider text-white/60 hover:bg-white/5 disabled:opacity-50">
                        Dismiss
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="flex justify-end mt-4">
              <button onClick={() => setOpen(false)} data-testid="admin-alerts-close"
                      className="px-4 py-2 border border-white/15 rounded text-xs uppercase tracking-wider hover:bg-white/5">Later</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default AdminAlertsWatcher;
