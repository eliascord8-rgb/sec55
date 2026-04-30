import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { adminApi, api } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { LogOut, Sparkles, Loader2, Plus, Copy, KeyRound } from "lucide-react";
import { toast } from "sonner";

export default function Admin() {
  const [token, setToken] = useState(localStorage.getItem("bs_admin_token") || "");
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const login = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const r = await api.post("/admin/login", { username: u, password: p });
      localStorage.setItem("bs_admin_token", r.data.token);
      setToken(r.data.token);
      toast.success("Welcome, admin");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Invalid credentials");
    } finally {
      setLoading(false);
    }
  };

  const logout = () => {
    localStorage.removeItem("bs_admin_token");
    setToken("");
  };

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#050505] p-6 relative overflow-hidden">
        <div
          className="absolute -top-40 -left-40 w-[500px] h-[500px] rounded-full opacity-30 blur-[120px]"
          style={{ background: "radial-gradient(circle, #FF007F, transparent 70%)" }}
        />
        <div
          className="absolute -bottom-40 -right-40 w-[500px] h-[500px] rounded-full opacity-30 blur-[120px]"
          style={{ background: "radial-gradient(circle, #7000FF, transparent 70%)" }}
        />
        <form
          onSubmit={login}
          data-testid="admin-login-form"
          className="w-full max-w-sm glass rounded-sm p-8 relative"
        >
          <Link to="/" className="flex items-center gap-2 mb-8">
            <div className="w-8 h-8 rounded-sm gradient-pp flex items-center justify-center">
              <Sparkles className="w-4 h-4" strokeWidth={2.5} />
            </div>
            <span className="font-display font-black">
              Better<span className="text-[#FF007F]">Social</span>
            </span>
          </Link>
          <h1 className="font-display text-2xl font-black mb-1">Admin Access</h1>
          <p className="text-xs text-white/40 uppercase tracking-[0.2em] mb-8">Restricted area</p>

          <div className="space-y-4">
            <div>
              <Label className="text-[11px] uppercase tracking-wider text-white/60">Username</Label>
              <Input
                data-testid="admin-username"
                value={u}
                onChange={(e) => setU(e.target.value)}
                className="bg-[#1a1525] border-white/10 mt-1"
                autoFocus
              />
            </div>
            <div>
              <Label className="text-[11px] uppercase tracking-wider text-white/60">Password</Label>
              <Input
                data-testid="admin-password"
                type="password"
                value={p}
                onChange={(e) => setP(e.target.value)}
                className="bg-[#1a1525] border-white/10 mt-1"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              data-testid="admin-login-btn"
              className="w-full py-3 gradient-pp rounded-sm font-bold tracking-wide hover:opacity-90 transition disabled:opacity-50"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : "Sign in"}
            </button>
          </div>
        </form>
      </div>
    );
  }

  return <Dashboard token={token} onLogout={logout} />;
}

function Dashboard({ token, onLogout }) {
  return (
    <div className="min-h-screen bg-[#0d0a14]">
      <header className="border-b border-white/5 bg-[#050505]/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 md:px-10 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-sm gradient-pp flex items-center justify-center">
              <Sparkles className="w-4 h-4" strokeWidth={2.5} />
            </div>
            <span className="font-display font-black">Admin Console</span>
          </Link>
          <button
            onClick={onLogout}
            data-testid="admin-logout"
            className="inline-flex items-center gap-2 px-4 py-2 border border-white/10 rounded-sm text-xs uppercase tracking-wider hover:bg-white/5 transition"
          >
            <LogOut className="w-3 h-3" /> Logout
          </button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 md:px-10 py-10">
        <Tabs defaultValue="orders" className="w-full">
          <TabsList className="grid grid-cols-4 max-w-2xl bg-[#1a1525] mb-6 rounded-sm">
            <TabsTrigger
              value="orders"
              data-testid="tab-orders"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              Orders
            </TabsTrigger>
            <TabsTrigger
              value="services"
              data-testid="tab-services"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              Services
            </TabsTrigger>
            <TabsTrigger
              value="coupons"
              data-testid="tab-coupons"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              Coupons
            </TabsTrigger>
            <TabsTrigger
              value="settings"
              data-testid="tab-settings"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              Settings
            </TabsTrigger>
          </TabsList>

          <TabsContent value="orders">
            <OrdersPanel token={token} />
          </TabsContent>
          <TabsContent value="services">
            <ServicesPanel token={token} />
          </TabsContent>
          <TabsContent value="coupons">
            <CouponsPanel token={token} />
          </TabsContent>
          <TabsContent value="settings">
            <SettingsPanel token={token} />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}

function OrdersPanel({ token }) {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const r = await adminApi(token).get("/admin/orders");
      setOrders(r.data.orders || []);
    } catch {
      toast.error("Failed to load orders");
    }
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, [token]);

  return (
    <div className="bg-[#1a1525] border border-white/5 rounded-sm overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
        <h2 className="font-display font-bold text-lg">Order Logs</h2>
        <button
          onClick={load}
          data-testid="refresh-orders"
          className="text-xs uppercase tracking-wider text-white/60 hover:text-white"
        >
          Refresh
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="orders-table">
          <thead className="text-[10px] uppercase tracking-[0.2em] text-white/40 bg-[#0d0a14]">
            <tr>
              <th className="text-left px-6 py-3">Date</th>
              <th className="text-left px-6 py-3">IP</th>
              <th className="text-left px-6 py-3">Service</th>
              <th className="text-left px-6 py-3">Qty</th>
              <th className="text-left px-6 py-3">Price</th>
              <th className="text-left px-6 py-3">Method</th>
              <th className="text-left px-6 py-3">Status</th>
              <th className="text-left px-6 py-3">SMM ID</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={8} className="text-center py-12 text-white/40">
                  <Loader2 className="w-5 h-5 animate-spin inline mr-2" /> Loading…
                </td>
              </tr>
            )}
            {!loading && orders.length === 0 && (
              <tr>
                <td colSpan={8} className="text-center py-12 text-white/40 text-xs">
                  No orders yet.
                </td>
              </tr>
            )}
            {orders.map((o) => (
              <tr key={o.id} className="border-t border-white/5 hover:bg-white/[0.02]">
                <td className="px-6 py-3 text-white/60 font-mono text-xs">
                  {new Date(o.created_at).toLocaleString()}
                </td>
                <td className="px-6 py-3 font-mono text-xs text-[#00E5FF]">{o.ip}</td>
                <td className="px-6 py-3 font-mono text-xs">#{o.service_id}</td>
                <td className="px-6 py-3 font-mono">{o.quantity}</td>
                <td className="px-6 py-3 font-mono font-bold text-[#FF007F]">${o.price_usd?.toFixed(2)}</td>
                <td className="px-6 py-3 text-xs uppercase tracking-wider">{o.payment_method}</td>
                <td className="px-6 py-3">
                  <span
                    className={`text-[10px] uppercase tracking-wider px-2 py-1 rounded-sm ${
                      o.status === "completed"
                        ? "bg-[#00E5FF]/20 text-[#00E5FF]"
                        : "bg-[#FFB800]/20 text-[#FFB800]"
                    }`}
                  >
                    {o.status}
                  </span>
                </td>
                <td className="px-6 py-3 font-mono text-xs">{o.smm_order_id || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CouponsPanel({ token }) {
  const [list, setList] = useState([]);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);

  const load = async () => {
    try {
      const r = await adminApi(token).get("/admin/coupons");
      setList(r.data.coupons || []);
    } catch {
      toast.error("Failed to load coupons");
    }
  };

  useEffect(() => {
    load();
  }, [token]);

  const create = async (e) => {
    e.preventDefault();
    if (!amount) return;
    setCreating(true);
    try {
      const r = await adminApi(token).post("/admin/coupons", {
        amount: Number(amount),
        note,
      });
      toast.success(`Coupon ${r.data.code} created`);
      setAmount("");
      setNote("");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="grid lg:grid-cols-[1fr_2fr] gap-6">
      <form
        onSubmit={create}
        data-testid="coupon-create-form"
        className="bg-[#1a1525] border border-white/5 rounded-sm p-6 h-fit"
      >
        <h2 className="font-display font-bold text-lg mb-4">New Coupon</h2>
        <div className="space-y-4">
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">Amount (USD)</Label>
            <Input
              data-testid="coupon-amount"
              type="number"
              step="0.01"
              min="0.01"
              required
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="bg-[#0d0a14] border-white/10 mt-1 font-mono"
            />
          </div>
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">Note (optional)</Label>
            <Input
              data-testid="coupon-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className="bg-[#0d0a14] border-white/10 mt-1"
            />
          </div>
          <button
            type="submit"
            disabled={creating}
            data-testid="coupon-create-btn"
            className="w-full py-3 gradient-pp rounded-sm font-bold tracking-wide hover:opacity-90 transition flex items-center justify-center gap-2 disabled:opacity-50"
          >
            <Plus className="w-4 h-4" /> Generate
          </button>
        </div>
      </form>

      <div className="bg-[#1a1525] border border-white/5 rounded-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-white/5">
          <h2 className="font-display font-bold text-lg">Generated Coupons</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="coupons-table">
            <thead className="text-[10px] uppercase tracking-[0.2em] text-white/40 bg-[#0d0a14]">
              <tr>
                <th className="text-left px-6 py-3">Code</th>
                <th className="text-left px-6 py-3">Amount</th>
                <th className="text-left px-6 py-3">Balance</th>
                <th className="text-left px-6 py-3">Note</th>
                <th className="text-left px-6 py-3">Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {list.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-center py-12 text-white/40 text-xs">
                    No coupons yet.
                  </td>
                </tr>
              )}
              {list.map((c) => (
                <tr key={c.code} className="border-t border-white/5 hover:bg-white/[0.02]">
                  <td className="px-6 py-3 font-mono text-[#FF007F] font-bold">{c.code}</td>
                  <td className="px-6 py-3 font-mono">${c.amount?.toFixed(2)}</td>
                  <td className="px-6 py-3 font-mono text-[#00E5FF]">${c.balance?.toFixed(2)}</td>
                  <td className="px-6 py-3 text-white/60 text-xs">{c.note || "—"}</td>
                  <td className="px-6 py-3 text-white/40 text-xs font-mono">
                    {new Date(c.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-6 py-3">
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(c.code);
                        toast.success("Copied");
                      }}
                      className="text-white/60 hover:text-[#FF007F]"
                    >
                      <Copy className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ServicesPanel({ token }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all"); // all | enabled | disabled
  const [markup, setMarkup] = useState("");
  const [edits, setEdits] = useState({}); // { service_id: { custom_rate, enabled } }

  const load = async () => {
    setLoading(true);
    try {
      const r = await adminApi(token).get("/admin/services");
      setItems(r.data.services || []);
      setEdits({});
    } catch {
      toast.error("Failed to load services");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    load();
  }, [token]);

  const sync = async () => {
    setSyncing(true);
    try {
      const r = await adminApi(token).post("/admin/services/sync");
      toast.success(`Synced · added ${r.data.added}, updated ${r.data.updated}, total ${r.data.total}`);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const bulk = async (action, percent) => {
    try {
      await adminApi(token).post("/admin/services/bulk", { action, percent });
      toast.success("Done");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    }
  };

  const saveRow = async (id) => {
    const e = edits[id];
    if (!e) return;
    try {
      await adminApi(token).patch(`/admin/services/${id}`, e);
      toast.success(`Saved #${id}`);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  const toggle = async (id, enabled) => {
    try {
      await adminApi(token).patch(`/admin/services/${id}`, { enabled });
      setItems((prev) => prev.map((s) => (s.service_id === id ? { ...s, enabled } : s)));
    } catch (e) {
      toast.error("Failed to toggle");
    }
  };

  const setEdit = (id, patch) => setEdits((prev) => ({ ...prev, [id]: { ...(prev[id] || {}), ...patch } }));

  const filtered = items
    .filter((s) =>
      filter === "enabled" ? s.enabled : filter === "disabled" ? !s.enabled : true,
    )
    .filter((s) => {
      const q = search.trim().toLowerCase();
      if (!q) return true;
      return `${s.name} ${s.category} ${s.service_id}`.toLowerCase().includes(q);
    })
    .slice(0, 300);

  const enabledCount = items.filter((s) => s.enabled).length;

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="bg-[#1a1525] border border-white/5 rounded-sm p-4 flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[200px] flex items-center gap-2">
          <span className="text-xs uppercase tracking-wider text-white/50">Total</span>
          <span className="font-mono font-bold text-white">{items.length}</span>
          <span className="text-xs text-white/30">·</span>
          <span className="text-xs uppercase tracking-wider text-[#00E5FF]">
            {enabledCount} live
          </span>
        </div>
        <button
          onClick={sync}
          disabled={syncing}
          data-testid="services-sync-btn"
          className="px-4 py-2 bg-[#00E5FF]/10 border border-[#00E5FF]/40 text-[#00E5FF] rounded-sm text-xs font-bold uppercase tracking-wider hover:bg-[#00E5FF]/20 disabled:opacity-50"
        >
          {syncing ? "Syncing…" : "↻ Sync from provider"}
        </button>
        <button
          onClick={() => bulk("enable_all")}
          data-testid="enable-all-btn"
          className="px-3 py-2 bg-white/5 hover:bg-white/10 rounded-sm text-xs font-bold uppercase tracking-wider"
        >
          Enable all
        </button>
        <button
          onClick={() => bulk("disable_all")}
          data-testid="disable-all-btn"
          className="px-3 py-2 bg-white/5 hover:bg-white/10 rounded-sm text-xs font-bold uppercase tracking-wider"
        >
          Disable all
        </button>
        <div className="flex items-center gap-1">
          <Input
            type="number"
            placeholder="markup %"
            value={markup}
            onChange={(e) => setMarkup(e.target.value)}
            data-testid="markup-input"
            className="w-28 bg-[#0d0a14] border-white/10 h-9 text-xs"
          />
          <button
            onClick={() => markup && bulk("apply_markup", Number(markup))}
            data-testid="apply-markup-btn"
            className="px-3 py-2 gradient-pp rounded-sm text-xs font-bold uppercase tracking-wider"
          >
            Apply
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-[#1a1525] border border-white/5 rounded-sm p-4 flex flex-wrap items-center gap-3">
        <Input
          placeholder="Search name, category, ID…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          data-testid="services-search-admin"
          className="flex-1 min-w-[200px] bg-[#0d0a14] border-white/10"
        />
        <div className="flex gap-1">
          {["all", "enabled", "disabled"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              data-testid={`filter-${f}`}
              className={`px-3 py-2 text-xs uppercase tracking-wider rounded-sm ${
                filter === f ? "bg-[#FF007F] font-bold" : "bg-white/5 text-white/60 hover:bg-white/10"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="bg-[#1a1525] border border-white/5 rounded-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="services-table">
            <thead className="text-[10px] uppercase tracking-[0.2em] text-white/40 bg-[#0d0a14]">
              <tr>
                <th className="text-left px-4 py-3">ID</th>
                <th className="text-left px-4 py-3">Name</th>
                <th className="text-left px-4 py-3">Category</th>
                <th className="text-right px-4 py-3">Provider $/k</th>
                <th className="text-right px-4 py-3">Your $/k</th>
                <th className="text-center px-4 py-3">Live</th>
                <th className="text-right px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-white/40">
                    <Loader2 className="w-5 h-5 animate-spin inline mr-2" /> Loading…
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-white/40 text-xs">
                    No services. Click "Sync from provider" to import.
                  </td>
                </tr>
              )}
              {filtered.map((s) => {
                const dirty = edits[s.service_id];
                const customRate = dirty?.custom_rate ?? s.custom_rate;
                return (
                  <tr key={s.service_id} className="border-t border-white/5 hover:bg-white/[0.02]">
                    <td className="px-4 py-2 font-mono text-xs text-[#00E5FF]">#{s.service_id}</td>
                    <td className="px-4 py-2 max-w-md">
                      <div className="text-xs truncate">{s.name}</div>
                    </td>
                    <td className="px-4 py-2 text-xs text-white/60">{s.category}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-white/50">
                      ${Number(s.provider_rate || 0).toFixed(3)}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <Input
                        type="number"
                        step="0.001"
                        value={customRate}
                        onChange={(e) =>
                          setEdit(s.service_id, { custom_rate: Number(e.target.value) })
                        }
                        data-testid={`rate-input-${s.service_id}`}
                        className="w-24 h-8 bg-[#0d0a14] border-white/10 font-mono text-xs ml-auto text-right"
                      />
                    </td>
                    <td className="px-4 py-2 text-center">
                      <button
                        onClick={() => toggle(s.service_id, !s.enabled)}
                        data-testid={`toggle-${s.service_id}`}
                        className={`px-2 py-1 rounded-sm text-[10px] uppercase tracking-wider font-bold ${
                          s.enabled
                            ? "bg-[#00E5FF]/20 text-[#00E5FF]"
                            : "bg-white/5 text-white/40"
                        }`}
                      >
                        {s.enabled ? "On" : "Off"}
                      </button>
                    </td>
                    <td className="px-4 py-2 text-right">
                      {dirty && (
                        <button
                          onClick={() => saveRow(s.service_id)}
                          data-testid={`save-${s.service_id}`}
                          className="px-3 py-1 gradient-pp rounded-sm text-[10px] uppercase tracking-wider font-bold"
                        >
                          Save
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function SettingsPanel({ token }) {
  return (
    <div className="space-y-6">
      <SmmConfigPanel token={token} />
      <CoinPaymentsPanel token={token} />
    </div>
  );
}

function SmmConfigPanel({ token }) {
  const [cfg, setCfg] = useState(null);
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const r = await adminApi(token).get("/admin/smm-config");
      setCfg(r.data);
      setUrl(r.data.api_url || "");
    } catch {}
  };
  useEffect(() => {
    load();
  }, [token]);

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await adminApi(token).post("/admin/smm-config", { api_url: url, api_key: key });
      toast.success("SMM API saved");
      setKey("");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      onSubmit={save}
      data-testid="smm-config-form"
      className="bg-[#1a1525] border border-white/5 rounded-sm p-8 max-w-2xl"
    >
      <div className="flex items-center gap-3 mb-6">
        <KeyRound className="w-5 h-5 text-[#00E5FF]" />
        <h2 className="font-display font-bold text-lg">SMM Provider API</h2>
      </div>
      {cfg && (
        <div className="mb-4 p-3 rounded-sm bg-[#00E5FF]/10 border border-[#00E5FF]/30 text-xs text-[#00E5FF]">
          {cfg.configured ? "Custom config active" : "Using default config"} · key: {cfg.api_key_masked}
        </div>
      )}
      <div className="space-y-4">
        <div>
          <Label className="text-[11px] uppercase tracking-wider text-white/60">API URL</Label>
          <Input
            data-testid="smm-api-url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs"
            placeholder="https://yoursmmpanel.com/api/v2"
            required
          />
        </div>
        <div>
          <Label className="text-[11px] uppercase tracking-wider text-white/60">API Key</Label>
          <Input
            data-testid="smm-api-key"
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="re-enter to update"
            className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs"
            required
          />
        </div>
      </div>
      <button
        type="submit"
        disabled={saving}
        data-testid="smm-save-btn"
        className="mt-5 px-6 py-3 gradient-pp rounded-sm font-bold tracking-wide hover:opacity-90 transition disabled:opacity-50"
      >
        {saving ? "Saving…" : "Save SMM API"}
      </button>
    </form>
  );
}

function CoinPaymentsPanel({ token }) {
  const [cfg, setCfg] = useState(null);
  const [pub, setPub] = useState("");
  const [priv, setPriv] = useState("");
  const [ipn, setIpn] = useState("");
  const [merchant, setMerchant] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const r = await adminApi(token).get("/admin/coinpayments-config");
      setCfg(r.data);
      if (r.data.configured) {
        setPub(r.data.public_key || "");
        setMerchant(r.data.merchant_id || "");
      }
    } catch {}
  };

  useEffect(() => {
    load();
  }, [token]);

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await adminApi(token).post("/admin/coinpayments-config", {
        public_key: pub,
        private_key: priv,
        ipn_secret: ipn,
        merchant_id: merchant,
      });
      toast.success("CoinPayments config saved");
      setPriv("");
      setIpn("");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      onSubmit={save}
      data-testid="settings-form"
      className="bg-[#1a1525] border border-white/5 rounded-sm p-8 max-w-2xl"
    >
      <div className="flex items-center gap-3 mb-6">
        <KeyRound className="w-5 h-5 text-[#FF007F]" />
        <h2 className="font-display font-bold text-lg">CoinPayments Configuration</h2>
      </div>
      {cfg?.configured && (
        <div className="mb-4 p-3 rounded-sm bg-[#00E5FF]/10 border border-[#00E5FF]/30 text-xs text-[#00E5FF]">
          Currently configured · private key: {cfg.private_key_masked} · IPN: {cfg.ipn_secret_masked}
        </div>
      )}
      <div className="grid sm:grid-cols-2 gap-4">
        <div>
          <Label className="text-[11px] uppercase tracking-wider text-white/60">Public Key</Label>
          <Input
            data-testid="cp-public-key"
            value={pub}
            onChange={(e) => setPub(e.target.value)}
            className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs"
            required
          />
        </div>
        <div>
          <Label className="text-[11px] uppercase tracking-wider text-white/60">Merchant ID</Label>
          <Input
            data-testid="cp-merchant-id"
            value={merchant}
            onChange={(e) => setMerchant(e.target.value)}
            className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs"
            required
          />
        </div>
        <div>
          <Label className="text-[11px] uppercase tracking-wider text-white/60">Private Key</Label>
          <Input
            data-testid="cp-private-key"
            type="password"
            value={priv}
            onChange={(e) => setPriv(e.target.value)}
            placeholder="re-enter to update"
            className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs"
            required
          />
        </div>
        <div>
          <Label className="text-[11px] uppercase tracking-wider text-white/60">IPN Secret</Label>
          <Input
            data-testid="cp-ipn-secret"
            type="password"
            value={ipn}
            onChange={(e) => setIpn(e.target.value)}
            placeholder="re-enter to update"
            className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs"
            required
          />
        </div>
      </div>
      <button
        type="submit"
        disabled={saving}
        data-testid="cp-save-btn"
        className="mt-6 px-6 py-3 gradient-pp rounded-sm font-bold tracking-wide hover:opacity-90 transition disabled:opacity-50"
      >
        {saving ? "Saving…" : "Save credentials"}
      </button>
    </form>
  );
}
