import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { adminApi, api } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { LogOut, Sparkles, Loader2, Plus, Copy, KeyRound, Trash2, Pencil, FileText, Bell, BellOff, Send, RotateCw } from "lucide-react";
import { toast } from "sonner";

export default function Admin() {
  const [token, setToken] = useState(localStorage.getItem("bs_admin_token") || "");
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [loading, setLoading] = useState(false);
  const [secretLoggingIn, setSecretLoggingIn] = useState(false);
  const [role, setRole] = useState("owner"); // 'owner' | 'staff'
  const [perms, setPerms] = useState([]);
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const navigate = useNavigate();

  // Load role + perms + display_name once we have a token
  const loadMe = () => {
    if (!token) return;
    adminApi(token)
      .get("/admin/me")
      .then((r) => {
        setRole(r.data.role || "owner");
        setPerms(r.data.perms || []);
        setDisplayName(r.data.display_name || "");
        setUsername(r.data.username || "");
      })
      .catch(() => {
        // invalid token — clear
        localStorage.removeItem("bs_admin_token");
        setToken("");
      });
  };
  useEffect(() => {
    loadMe();
    // eslint-disable-next-line
  }, [token]);

  const can = (p) => role === "owner" || perms.includes(p);

  // Auto-login via secret URL (e.g. /admin?key=mysecret)
  useEffect(() => {
    if (token) return;
    const params = new URLSearchParams(window.location.search);
    // Accept ?key=X, ?secret=X, or bare ?X (with no value)
    let secret = params.get("key") || params.get("secret");
    if (!secret) {
      // Bare query like /admin?haha123
      const raw = window.location.search.replace(/^\?/, "");
      if (raw && !raw.includes("=") && !raw.includes("&")) {
        secret = decodeURIComponent(raw);
      }
    }
    if (!secret) return;
    setSecretLoggingIn(true);
    api
      .post("/admin/login-secret", { secret })
      .then((r) => {
        localStorage.setItem("bs_admin_token", r.data.token);
        setToken(r.data.token);
        toast.success("Logged in via secret URL");
        // Clean the URL so the secret doesn't sit in history
        window.history.replaceState({}, document.title, "/admin");
      })
      .catch((err) => {
        toast.error(err.response?.data?.detail || "Secret login failed");
      })
      .finally(() => setSecretLoggingIn(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      // Try owner login first; if 401, try staff
      let r;
      try {
        r = await api.post("/admin/login", { username: u.trim(), password: p });
      } catch (err) {
        if (err.response?.status === 401 || err.response?.status === 403) {
          r = await api.post("/admin/staff/login", { username: u.trim(), password: p });
        } else {
          throw err;
        }
      }
      localStorage.setItem("bs_admin_token", r.data.token);
      setToken(r.data.token);
      toast.success(`Welcome, ${r.data.username || "admin"}`);
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
    if (secretLoggingIn) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-[#050505] text-white">
          <div className="flex items-center gap-3 text-sm">
            <Loader2 className="w-4 h-4 animate-spin text-[#FF007F]" />
            Authenticating via secret URL…
          </div>
        </div>
      );
    }
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

  return <Dashboard token={token} onLogout={logout} role={role} can={can} displayName={displayName} username={username} loadMe={loadMe} />;
}

function Dashboard({ token, onLogout, role, can, displayName, username, loadMe }) {
  const [nickOpen, setNickOpen] = useState(false);
  const [nickValue, setNickValue] = useState(displayName || "");
  const [savingNick, setSavingNick] = useState(false);
  useEffect(() => { setNickValue(displayName || ""); }, [displayName]);

  const saveNick = async () => {
    const v = (nickValue || "").trim();
    if (v.length < 1) {
      toast.error("Nickname can't be empty");
      return;
    }
    setSavingNick(true);
    try {
      await adminApi(token).post("/admin/me/nickname", { display_name: v });
      toast.success(`Nickname updated to "${v}"`);
      setNickOpen(false);
      loadMe && loadMe();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to update nickname");
    } finally {
      setSavingNick(false);
    }
  };

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
          <div className="flex items-center gap-2">
            <button
              onClick={() => setNickOpen(true)}
              data-testid="admin-nickname-btn"
              className="hidden sm:inline-flex items-center gap-2 px-3 py-2 border border-emerald-400/30 bg-emerald-500/10 rounded-sm text-xs hover:bg-emerald-500/20 transition"
              title="Click to change the nickname shown to clients"
            >
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-emerald-200">
                Posting as <span className="font-bold text-white">{displayName || username || "—"}</span>
              </span>
            </button>
            <button
              onClick={onLogout}
              data-testid="admin-logout"
              className="inline-flex items-center gap-2 px-4 py-2 border border-white/10 rounded-sm text-xs uppercase tracking-wider hover:bg-white/5 transition"
            >
              <LogOut className="w-3 h-3" /> Logout
            </button>
          </div>
        </div>
      </header>

      {nickOpen && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => !savingNick && setNickOpen(false)}>
          <div onClick={(e) => e.stopPropagation()} className="bg-[#1a1525] border border-emerald-500/30 rounded-sm p-6 max-w-md w-full">
            <h3 className="font-display font-bold text-lg mb-1">Change your nickname</h3>
            <p className="text-[11px] text-white/50 mb-4">
              This is the name clients will see when you reply in chats and tickets. ({role === "owner" ? "Owner" : `Staff: @${username}`})
            </p>
            <Input
              data-testid="nickname-input"
              value={nickValue}
              onChange={(e) => setNickValue(e.target.value.slice(0, 40))}
              placeholder="e.g. Alex from Support"
              className="bg-[#0d0a14] border-white/10 mb-4"
            />
            <div className="flex gap-2 justify-end">
              <button onClick={() => setNickOpen(false)} disabled={savingNick} className="px-4 py-2 border border-white/10 rounded-sm text-xs uppercase tracking-wider hover:bg-white/5">
                Cancel
              </button>
              <button onClick={saveNick} disabled={savingNick} data-testid="nickname-save" className="px-4 py-2 bg-emerald-500 hover:bg-emerald-400 text-black rounded-sm text-xs font-bold uppercase tracking-wider disabled:opacity-50 inline-flex items-center gap-2">
                {savingNick ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                Save Nickname
              </button>
            </div>
          </div>
        </div>
      )}

      <main className="max-w-7xl mx-auto px-6 md:px-10 py-10">
        <Tabs defaultValue={role === "staff" ? (can("ai_inbox") ? "inbox" : "tickets") : "orders"} className="w-full">
          <TabsList className="grid grid-cols-12 max-w-7xl bg-[#1a1525] mb-6 rounded-sm">
            {can("orders") && (
            <TabsTrigger
              value="orders"
              data-testid="tab-orders"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              Orders
            </TabsTrigger>
            )}
            {role === "owner" && (
            <TabsTrigger
              value="services"
              data-testid="tab-services"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              Services
            </TabsTrigger>
            )}
            {role === "owner" && (
            <TabsTrigger
              value="coupons"
              data-testid="tab-coupons"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              Coupons
            </TabsTrigger>
            )}
            {role === "owner" && (
            <TabsTrigger
              value="users"
              data-testid="tab-users"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              Users
            </TabsTrigger>
            )}
            {role === "owner" && (
            <TabsTrigger
              value="funds"
              data-testid="tab-funds"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              Funds
            </TabsTrigger>
            )}
            {can("withdrawals") && (
            <TabsTrigger
              value="withdrawals"
              data-testid="tab-withdrawals"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              Withdrawals
            </TabsTrigger>
            )}
            {can("tickets") && (
            <TabsTrigger
              value="tickets"
              data-testid="tab-tickets"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              Tickets
            </TabsTrigger>
            )}
            {role === "owner" && (
            <TabsTrigger
              value="ai"
              data-testid="tab-ai"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              AI Buy
            </TabsTrigger>
            )}
            {can("ai_inbox") && (
            <TabsTrigger
              value="inbox"
              data-testid="tab-inbox"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              AI Inbox
            </TabsTrigger>
            )}
            {can("discord") && (
            <TabsTrigger
              value="discord"
              data-testid="tab-discord"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              Discord
            </TabsTrigger>
            )}
            {role === "owner" && (
            <TabsTrigger
              value="settings"
              data-testid="tab-settings"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              Settings
            </TabsTrigger>
            )}
            {role === "owner" && (
            <TabsTrigger
              value="providers"
              data-testid="tab-providers"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              Providers
            </TabsTrigger>
            )}
            {role === "owner" && (
            <TabsTrigger
              value="staff"
              data-testid="tab-staff"
              className="data-[state=active]:bg-[#FF007F] rounded-sm"
            >
              Team
            </TabsTrigger>
            )}
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
          <TabsContent value="users">
            <UsersPanel token={token} />
          </TabsContent>
          <TabsContent value="funds">
            <FundsAdminPanel token={token} />
          </TabsContent>
          <TabsContent value="withdrawals">
            <WithdrawalsAdminPanel token={token} />
          </TabsContent>
          <TabsContent value="tickets">
            <TicketsAdminPanel token={token} displayName={displayName} />
          </TabsContent>
          <TabsContent value="ai">
            <AIPanel token={token} />
          </TabsContent>
          <TabsContent value="inbox">
            <AIInboxPanel token={token} displayName={displayName} reloadMe={loadMe} />
          </TabsContent>
          <TabsContent value="discord">
            <DiscordPanel token={token} />
          </TabsContent>
          <TabsContent value="settings">
            <SettingsPanel token={token} />
          </TabsContent>
          <TabsContent value="providers">
            <ProvidersPanel token={token} />
          </TabsContent>
          <TabsContent value="staff">
            <StaffPanel token={token} />
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
  const [editing, setEditing] = useState(null); // { code, balance }
  const [editValue, setEditValue] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);

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

  const remove = async (code) => {
    if (!window.confirm(`Delete coupon ${code}? This cannot be undone.`)) return;
    try {
      await adminApi(token).delete(`/admin/coupons/${code}`);
      toast.success("Coupon deleted");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    }
  };

  const startEdit = (c) => {
    setEditing(c);
    setEditValue(String(c.balance ?? 0));
  };

  const saveEdit = async () => {
    const newBal = Number(editValue);
    if (Number.isNaN(newBal) || newBal < 0) {
      toast.error("Enter a valid non-negative amount");
      return;
    }
    setSavingEdit(true);
    try {
      await adminApi(token).put(`/admin/coupons/${editing.code}/balance`, {
        balance: newBal,
      });
      toast.success(`Balance updated to $${newBal.toFixed(2)}`);
      setEditing(null);
      setEditValue("");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    } finally {
      setSavingEdit(false);
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
                    <div className="flex items-center gap-2 justify-end">
                      <button
                        onClick={() => {
                          navigator.clipboard.writeText(c.code);
                          toast.success("Copied");
                        }}
                        className="text-white/60 hover:text-[#FF007F]"
                        data-testid={`copy-coupon-${c.code}`}
                      >
                        <Copy className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => startEdit(c)}
                        data-testid={`edit-coupon-${c.code}`}
                        className="text-white/60 hover:text-[#00E5FF]"
                        title="Edit balance"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => remove(c.code)}
                        data-testid={`delete-coupon-${c.code}`}
                        className="text-white/60 hover:text-[#FF3B30]"
                        title="Delete coupon"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Edit Balance Modal */}
      {editing && (
        <div
          data-testid="edit-coupon-modal"
          className="fixed inset-0 z-[80] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => !savingEdit && setEditing(null)}
        >
          <div
            className="w-full max-w-sm bg-[#1a1525] border border-white/10 rounded-sm p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="font-display font-bold text-lg mb-1">Edit Coupon Balance</h3>
            <div className="text-xs text-white/50 font-mono mb-4">{editing.code}</div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">
              New balance (USD)
            </Label>
            <Input
              type="number"
              step="0.01"
              min="0"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              data-testid="edit-coupon-balance-input"
              className="bg-[#0d0a14] border-white/10 mt-1 font-mono"
              autoFocus
              disabled={savingEdit}
            />
            <div className="flex gap-2 mt-5">
              <button
                onClick={() => setEditing(null)}
                disabled={savingEdit}
                data-testid="edit-coupon-cancel"
                className="flex-1 py-2.5 border border-white/10 rounded-sm text-xs uppercase tracking-wider hover:bg-white/5"
              >
                Cancel
              </button>
              <button
                onClick={saveEdit}
                disabled={savingEdit}
                data-testid="edit-coupon-save"
                className="flex-1 py-2.5 gradient-pp rounded-sm text-xs uppercase tracking-wider font-bold disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {savingEdit ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                Save
              </button>
            </div>
          </div>
        </div>
      )}
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
  const [singleId, setSingleId] = useState("");
  const [adding, setAdding] = useState(false);
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

  const addById = async () => {
    if (!singleId) return;
    setAdding(true);
    try {
      const r = await adminApi(token).post("/admin/services/add-by-id", {
        service_id: Number(singleId),
      });
      toast.success(`${r.data.action === "added" ? "Added" : "Updated"} #${r.data.service_id} · ${r.data.name?.slice(0, 40)}`);
      setSingleId("");
      // Filter to highlight the newly added service
      setSearch(String(r.data.service_id));
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to add");
    } finally {
      setAdding(false);
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
      return `${s.name} ${s.custom_name || ""} ${s.category} ${s.service_id}`.toLowerCase().includes(q);
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
        <div className="flex items-center gap-1">
          <Input
            type="number"
            placeholder="provider service ID"
            value={singleId}
            onChange={(e) => setSingleId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addById())}
            data-testid="single-service-id"
            className="w-44 bg-[#0d0a14] border-white/10 h-9 text-xs"
          />
          <button
            onClick={addById}
            disabled={adding || !singleId}
            data-testid="add-by-id-btn"
            className="px-3 py-2 bg-[#FF007F]/15 border border-[#FF007F]/40 text-[#FF007F] rounded-sm text-xs font-bold uppercase tracking-wider hover:bg-[#FF007F]/25 disabled:opacity-50"
          >
            {adding ? "Adding…" : "+ Add by ID"}
          </button>
        </div>
        <button
          onClick={sync}
          disabled={syncing}
          data-testid="services-sync-btn"
          className="px-4 py-2 bg-[#00E5FF]/10 border border-[#00E5FF]/40 text-[#00E5FF] rounded-sm text-xs font-bold uppercase tracking-wider hover:bg-[#00E5FF]/20 disabled:opacity-50"
        >
          {syncing ? "Syncing…" : "↻ Sync all"}
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
        <button
          onClick={() => {
            if (window.confirm(`Delete ALL ${items.length} services? This cannot be undone.`)) {
              bulk("delete_all");
            }
          }}
          data-testid="delete-all-btn"
          className="px-3 py-2 bg-[#FF3B30]/15 border border-[#FF3B30]/40 text-[#FF3B30] hover:bg-[#FF3B30]/25 rounded-sm text-xs font-bold uppercase tracking-wider"
        >
          Delete all
        </button>
        <ManualServiceQuickAdd token={token} onAdded={load} />
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
                <th className="text-left px-4 py-3">Provider name / Your label</th>
                <th className="text-left px-4 py-3">Category</th>
                <th className="text-right px-4 py-3">Provider $/k</th>
                <th className="text-right px-4 py-3">Your $/k</th>
                <th className="text-center px-4 py-3">Live</th>
                <th className="text-center px-4 py-3" title="Service requires user to enter custom comment text">
                  Custom?
                </th>
                <th className="text-right px-4 py-3"></th>
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
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-center py-12 text-white/40 text-xs">
                    No services. Click "Sync from provider" to import.
                  </td>
                </tr>
              )}
              {filtered.map((s) => {
                const dirty = edits[s.service_id];
                const customRate = dirty?.custom_rate ?? s.custom_rate;
                const customName = dirty?.custom_name ?? (s.custom_name ?? "");
                return (
                  <tr key={s.service_id} className="border-t border-white/5 hover:bg-white/[0.02]">
                    <td className="px-4 py-2 font-mono text-xs text-[#00E5FF]">#{s.service_id}</td>
                    <td className="px-4 py-2 max-w-md">
                      <div
                        className="text-xs truncate text-white/40"
                        title={`Provider: ${s.name}`}
                      >
                        {s.name}
                      </div>
                      <Input
                        value={customName}
                        onChange={(e) =>
                          setEdit(s.service_id, { custom_name: e.target.value })
                        }
                        placeholder="Custom display name (optional)"
                        data-testid={`custom-name-${s.service_id}`}
                        maxLength={200}
                        className="mt-1 h-7 bg-[#0d0a14] border-white/10 text-xs"
                      />
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
                    <td className="px-4 py-2 text-center">
                      <button
                        onClick={async () => {
                          try {
                            await adminApi(token).patch(`/admin/services/${s.service_id}`, { needs_custom_text: !s.needs_custom_text });
                            setItems((prev) => prev.map((x) => (x.service_id === s.service_id ? { ...x, needs_custom_text: !s.needs_custom_text } : x)));
                          } catch { toast.error("Failed"); }
                        }}
                        data-testid={`custom-toggle-${s.service_id}`}
                        title={s.needs_custom_text ? "User must enter comment text" : "No comment text needed"}
                        className={`px-2 py-1 rounded-sm text-[10px] uppercase tracking-wider font-bold ${
                          s.needs_custom_text
                            ? "bg-amber-500/20 text-amber-300"
                            : "bg-white/5 text-white/30"
                        }`}
                      >
                        {s.needs_custom_text ? "Yes" : "No"}
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
      <SellyConfigPanel token={token} />
      <EmailConfigPanel token={token} />
    </div>
  );
}

function EmailConfigPanel({ token }) {
  const [cfg, setCfg] = useState(null);
  const [host, setHost] = useState("");
  const [port, setPort] = useState(587);
  const [user, setUser] = useState("");
  const [pw, setPw] = useState("");
  const [fromEmail, setFromEmail] = useState("");
  const [fromName, setFromName] = useState("Better Social");
  const [useTls, setUseTls] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testTo, setTestTo] = useState("");
  const [testing, setTesting] = useState(false);

  const load = async () => {
    try {
      const r = await adminApi(token).get("/admin/email-config");
      setCfg(r.data);
      setHost(r.data.smtp_host || "");
      setPort(r.data.smtp_port || 587);
      setUser(r.data.smtp_user || "");
      setFromEmail(r.data.from_email || "");
      setFromName(r.data.from_name || "Better Social");
      setUseTls(r.data.use_tls !== false);
    } catch {}
  };
  useEffect(() => {
    load();
  }, [token]);

  const save = async (e) => {
    e.preventDefault();
    if (!host.trim() || !user.trim()) {
      toast.error("Host and username are required");
      return;
    }
    if (!cfg?.password_set && !pw) {
      toast.error("Password is required on first save");
      return;
    }
    setSaving(true);
    try {
      const body = {
        smtp_host: host.trim(),
        smtp_port: Number(port),
        smtp_user: user.trim(),
        from_email: fromEmail.trim() || user.trim(),
        from_name: fromName.trim() || "Better Social",
        use_tls: useTls,
      };
      if (pw) body.smtp_password = pw;
      await adminApi(token).post("/admin/email-config", body);
      toast.success("SMTP saved");
      setPw("");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    } finally {
      setSaving(false);
    }
  };

  const sendTest = async () => {
    if (!testTo.includes("@")) {
      toast.error("Enter a valid email");
      return;
    }
    setTesting(true);
    try {
      await adminApi(token).post("/admin/email-config/test", { to: testTo.trim() });
      toast.success(`Test email sent to ${testTo}`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Send failed — check host/port/password");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="bg-[#1a1525] border border-blue-400/30 rounded-sm p-8 max-w-2xl">
      <div className="flex items-center gap-3 mb-2">
        <Send className="w-5 h-5 text-blue-400" />
        <h2 className="font-display font-bold text-lg">Email (SMTP) Configuration</h2>
      </div>
      <p className="text-xs text-white/50 mb-5">
        Used for welcome emails after registration and password reset links. Compatible with Gmail, Outlook, SendGrid SMTP relay, custom mailservers, etc.
      </p>
      {cfg && (
        <div className={`mb-4 p-3 rounded-sm text-xs ${cfg.configured ? "bg-emerald-500/10 border border-emerald-500/30 text-emerald-300" : "bg-amber-500/10 border border-amber-500/30 text-amber-300"}`}>
          {cfg.configured ? `Active · ${cfg.smtp_user} via ${cfg.smtp_host}:${cfg.smtp_port}` : "Not configured — welcome emails & password reset are disabled."}
        </div>
      )}
      <form onSubmit={save} className="space-y-3" data-testid="email-config-form">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="sm:col-span-2">
            <Label className="text-[11px] uppercase tracking-wider text-white/60">SMTP Host</Label>
            <Input data-testid="smtp-host" value={host} onChange={(e) => setHost(e.target.value)} placeholder="smtp.gmail.com" className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs" />
          </div>
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">Port</Label>
            <Input data-testid="smtp-port" type="number" value={port} onChange={(e) => setPort(e.target.value)} placeholder="587" className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs" />
          </div>
        </div>
        <div>
          <Label className="text-[11px] uppercase tracking-wider text-white/60">Username (Email)</Label>
          <Input data-testid="smtp-user" type="email" value={user} onChange={(e) => setUser(e.target.value)} placeholder="you@gmail.com" className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs" />
        </div>
        <div>
          <Label className="text-[11px] uppercase tracking-wider text-white/60">Password / App Password</Label>
          <Input data-testid="smtp-password" type="password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder={cfg?.password_set ? "•••••••• (saved — re-enter to update)" : "App password or SMTP key"} className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs" />
          <div className="text-[10px] text-white/40 mt-1">
            For Gmail use an <span className="text-blue-400">App Password</span> (Google Account → Security → 2-Step → App Passwords).
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">From Email</Label>
            <Input data-testid="smtp-from-email" type="email" value={fromEmail} onChange={(e) => setFromEmail(e.target.value)} placeholder="noreply@yourdomain.com" className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs" />
          </div>
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">From Name</Label>
            <Input data-testid="smtp-from-name" value={fromName} onChange={(e) => setFromName(e.target.value)} placeholder="Better Social" className="bg-[#0d0a14] border-white/10 mt-1" />
          </div>
        </div>
        <label className="flex items-center gap-2 text-xs text-white/70 cursor-pointer pt-1">
          <input type="checkbox" checked={useTls} onChange={(e) => setUseTls(e.target.checked)} data-testid="smtp-use-tls" /> Use TLS/STARTTLS (recommended)
        </label>
        <button type="submit" disabled={saving} data-testid="email-config-save" className="px-5 py-2 bg-blue-500 hover:bg-blue-400 text-black rounded-sm font-bold text-xs uppercase tracking-wider disabled:opacity-50 inline-flex items-center gap-2">
          {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
          Save SMTP Settings
        </button>
      </form>

      {cfg?.configured && (
        <div className="mt-6 pt-5 border-t border-white/5">
          <div className="text-[11px] uppercase tracking-wider text-white/60 mb-2">Send a Test Email</div>
          <div className="flex gap-2">
            <Input data-testid="smtp-test-to" type="email" value={testTo} onChange={(e) => setTestTo(e.target.value)} placeholder="recipient@example.com" className="bg-[#0d0a14] border-white/10 flex-1 font-mono text-xs" />
            <button onClick={sendTest} disabled={testing || !testTo.includes("@")} data-testid="smtp-test-send" className="px-4 py-2 bg-emerald-500 hover:bg-emerald-400 text-black rounded-sm text-xs font-bold uppercase tracking-wider disabled:opacity-50 inline-flex items-center gap-2">
              {testing ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
              Send Test
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function SellyConfigPanel({ token }) {
  const [cfg, setCfg] = useState(null);
  const [key, setKey] = useState("");
  const [email, setEmail] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const r = await adminApi(token).get("/admin/selly-config");
      setCfg(r.data);
      setEmail(r.data?.email || "");
    } catch {}
  };
  useEffect(() => {
    load();
  }, [token]);

  const save = async (e) => {
    e.preventDefault();
    if (key.trim().length < 10) {
      toast.error("Enter a valid Selly API key");
      return;
    }
    setSaving(true);
    try {
      await adminApi(token).post("/admin/selly-config", { api_key: key.trim(), email: email.trim() });
      toast.success("Selly credentials saved");
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
      data-testid="selly-config-form"
      className="bg-[#1a1525] border border-emerald-500/30 rounded-sm p-8 max-w-2xl"
    >
      <div className="flex items-center gap-3 mb-2">
        <KeyRound className="w-5 h-5 text-emerald-400" />
        <h2 className="font-display font-bold text-lg">Selly.io Payments</h2>
      </div>
      <p className="text-xs text-white/50 mb-5">
        Accepts crypto (BTC, ETH, USDT, LTC) and credit/debit cards via Selly&apos;s hosted checkout.
        Selly requires <span className="text-emerald-300 font-bold">both your account email AND the API key</span> (HTTP Basic Auth).
      </p>
      {cfg && (
        <div className={`mb-4 p-3 rounded-sm text-xs ${cfg.configured ? "bg-emerald-500/10 border border-emerald-500/30 text-emerald-300" : "bg-amber-500/10 border border-amber-500/30 text-amber-300"}`}>
          {cfg.configured ? `Active · key: ${cfg.api_key_masked} · email: ${cfg.email || "(not set — required!)"}` : "Not configured — Selly checkout is disabled until you add credentials."}
        </div>
      )}
      <div className="space-y-4">
        <div>
          <Label className="text-[11px] uppercase tracking-wider text-white/60">Selly Account Email</Label>
          <Input
            data-testid="selly-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="The email you log into Selly with"
            className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs"
          />
          <div className="text-[10px] text-white/40 mt-1">
            Required — same email you use to log in to selly.io
          </div>
        </div>
        <div>
          <Label className="text-[11px] uppercase tracking-wider text-white/60">Selly API Key</Label>
          <Input
            data-testid="selly-api-key"
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder={cfg?.configured ? "re-enter to update" : "Paste your Selly API key here"}
            className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs"
          />
          <div className="text-[10px] text-white/40 mt-1">
            Get this from <span className="font-mono text-emerald-400">selly.io → Settings → API</span>
          </div>
        </div>
        <div className="bg-[#0d0a14] border border-white/5 rounded-sm p-3 text-xs">
          <div className="text-[10px] uppercase tracking-wider text-white/40 mb-1">Webhook URL (set this in Selly&apos;s dashboard)</div>
          <div className="font-mono text-emerald-300 break-all">
            https://better-social.pro/api/selly/webhook
          </div>
        </div>
        <button
          type="submit"
          disabled={saving}
          data-testid="selly-config-save"
          className="px-5 py-2 bg-emerald-500 hover:bg-emerald-400 text-black rounded-sm font-bold text-xs uppercase tracking-wider disabled:opacity-50 inline-flex items-center gap-2"
        >
          {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
          Save Selly Credentials
        </button>
      </div>
    </form>
  );
}

function ManualServiceQuickAdd({ token, onAdded }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("Custom");
  const [price, setPrice] = useState("");
  const [deliveryMinutes, setDeliveryMinutes] = useState(60);
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim() || !(Number(price) > 0)) {
      toast.error("Name and price (> 0) required");
      return;
    }
    setSaving(true);
    try {
      await adminApi(token).post("/admin/services/manual", {
        name: name.trim(),
        description: description.trim(),
        category: category.trim() || "Custom",
        price_usd: Number(price),
        delivery_minutes: Number(deliveryMinutes) || 60,
      });
      toast.success("Manual service added");
      setName("");
      setDescription("");
      setPrice("");
      setDeliveryMinutes(60);
      setOpen(false);
      onAdded && onAdded();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid="add-manual-service-btn"
        className="px-3 py-2 bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 rounded-sm text-xs font-bold uppercase tracking-wider hover:bg-emerald-500/25"
      >
        + Manual service
      </button>
      {open && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => !saving && setOpen(false)}>
          <div onClick={(e) => e.stopPropagation()} className="bg-[#1a1525] border border-emerald-500/30 rounded-sm p-6 max-w-lg w-full max-h-[90vh] overflow-auto">
            <h3 className="font-display font-bold text-lg mb-1">Add Manual Service</h3>
            <p className="text-[11px] text-white/50 mb-4">
              No SMM API needed — you fulfill orders for this service manually. Set your title, description, flat price, and delivery time.
            </p>
            <form onSubmit={submit} data-testid="manual-service-form" className="space-y-3">
              <div>
                <Label className="text-[11px] uppercase tracking-wider text-white/60">Service Title *</Label>
                <Input data-testid="manual-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} placeholder="e.g. Custom YouTube thumbnail design" className="bg-[#0d0a14] border-white/10 mt-1" />
              </div>
              <div>
                <Label className="text-[11px] uppercase tracking-wider text-white/60">Description</Label>
                <textarea data-testid="manual-description" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} rows={3} placeholder="Describe what the customer gets, examples, deliverables…" className="w-full bg-[#0d0a14] border border-white/10 rounded-sm mt-1 px-3 py-2 text-sm outline-none focus:border-emerald-400 resize-none" />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <Label className="text-[11px] uppercase tracking-wider text-white/60">Category</Label>
                  <Input data-testid="manual-category" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Custom" className="bg-[#0d0a14] border-white/10 mt-1" />
                </div>
                <div>
                  <Label className="text-[11px] uppercase tracking-wider text-white/60">Price (USD) *</Label>
                  <Input data-testid="manual-price" type="number" min="0.01" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} required placeholder="29.99" className="bg-[#0d0a14] border-white/10 mt-1 font-mono" />
                </div>
                <div>
                  <Label className="text-[11px] uppercase tracking-wider text-white/60">Delivery (minutes)</Label>
                  <Input data-testid="manual-delivery" type="number" min="0" value={deliveryMinutes} onChange={(e) => setDeliveryMinutes(e.target.value)} placeholder="60" className="bg-[#0d0a14] border-white/10 mt-1 font-mono" />
                </div>
              </div>
              <div className="flex gap-2 justify-end pt-2">
                <button type="button" onClick={() => setOpen(false)} disabled={saving} className="px-4 py-2 border border-white/10 rounded-sm text-xs uppercase tracking-wider hover:bg-white/5">
                  Cancel
                </button>
                <button type="submit" disabled={saving} data-testid="manual-save" className="px-5 py-2 bg-emerald-500 hover:bg-emerald-400 text-black rounded-sm text-xs font-bold uppercase tracking-wider disabled:opacity-50 inline-flex items-center gap-2">
                  {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                  Create Service
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
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

function AIPanel({ token }) {
  const [map, setMap] = useState({ likes: 0, views: 0, comments: 0 });
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [m, o] = await Promise.all([
        adminApi(token).get("/ai/admin/service-map"),
        adminApi(token).get("/ai/admin/orders"),
      ]);
      setMap({
        likes: m.data.likes || 0,
        views: m.data.views || 0,
        comments: m.data.comments || 0,
      });
      setOrders(o.data.orders || []);
    } catch {
      toast.error("Failed to load AI data");
    }
    setLoading(false);
  };
  useEffect(() => {
    load();
  }, [token]);

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await adminApi(token).post("/ai/admin/service-map", {
        likes: Number(map.likes) || 0,
        views: Number(map.views) || 0,
        comments: Number(map.comments) || 0,
      });
      toast.success("AI service map saved");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    }
    setSaving(false);
  };

  return (
    <div className="space-y-6">
      <form
        onSubmit={save}
        data-testid="ai-map-form"
        className="bg-[#1a1525] border border-white/5 rounded-sm p-6 md:p-8 max-w-2xl"
      >
        <h2 className="font-display font-bold text-lg mb-1">AI Buy · Service Mapping</h2>
        <p className="text-xs text-white/50 mb-5">
          Assign a provider service ID to each category the AI can sell. Only curated services with
          those IDs (enabled & priced) will work.
        </p>
        <div className="grid sm:grid-cols-3 gap-4">
          {["likes", "views", "comments"].map((k) => (
            <div key={k}>
              <Label className="text-[11px] uppercase tracking-wider text-white/60">
                TikTok Live {k}
              </Label>
              <Input
                data-testid={`ai-map-${k}`}
                type="number"
                value={map[k]}
                onChange={(e) => setMap({ ...map, [k]: e.target.value })}
                className="bg-[#0d0a14] border-white/10 mt-1 font-mono"
                placeholder="service ID"
              />
            </div>
          ))}
        </div>
        <button
          type="submit"
          disabled={saving}
          data-testid="ai-map-save"
          className="mt-5 px-6 py-3 gradient-pp rounded-sm font-bold tracking-wide hover:opacity-90 transition disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save mapping"}
        </button>
      </form>

      <div className="bg-[#1a1525] border border-white/5 rounded-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-white/5 flex justify-between items-center">
          <h2 className="font-display font-bold text-lg">AI Buy · Order Log</h2>
          <button onClick={load} className="text-xs uppercase tracking-wider text-white/60 hover:text-white">
            Refresh
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="ai-orders-table">
            <thead className="text-[10px] uppercase tracking-[0.2em] text-white/40 bg-[#0d0a14]">
              <tr>
                <th className="text-left px-6 py-3">Date</th>
                <th className="text-left px-6 py-3">User</th>
                <th className="text-left px-6 py-3">Service</th>
                <th className="text-left px-6 py-3">Link</th>
                <th className="text-left px-6 py-3">Qty</th>
                <th className="text-left px-6 py-3">Price</th>
                <th className="text-left px-6 py-3">Coupon</th>
                <th className="text-left px-6 py-3">Status</th>
                <th className="text-left px-6 py-3">SMM ID</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={9} className="text-center py-10 text-white/40">
                    <Loader2 className="inline w-4 h-4 animate-spin mr-2" /> Loading…
                  </td>
                </tr>
              )}
              {!loading && orders.length === 0 && (
                <tr>
                  <td colSpan={9} className="text-center py-10 text-white/40 text-xs">
                    No AI orders yet.
                  </td>
                </tr>
              )}
              {orders.map((o) => (
                <tr key={o.id} className="border-t border-white/5 hover:bg-white/[0.02]">
                  <td className="px-6 py-3 font-mono text-xs text-white/60">
                    {new Date(o.created_at).toLocaleString()}
                  </td>
                  <td className="px-6 py-3 text-[#00E5FF] font-mono text-xs">
                    @{o.username || "—"}
                  </td>
                  <td className="px-6 py-3 font-mono text-xs">#{o.service_id}</td>
                  <td className="px-6 py-3 text-xs truncate max-w-[180px]">{o.link}</td>
                  <td className="px-6 py-3 font-mono">{o.quantity}</td>
                  <td className="px-6 py-3 font-mono text-[#FF007F]">
                    ${o.price_usd?.toFixed(2)}
                  </td>
                  <td className="px-6 py-3 font-mono text-xs">{o.coupon_code || "—"}</td>
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
    </div>
  );
}

function DiscordPanel({ token }) {
  const [cfg, setCfg] = useState(null);
  const [role, setRole] = useState("Developer");
  const [secret, setSecret] = useState("");
  const [botToken, setBotToken] = useState("");
  const [saving, setSaving] = useState(false);
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [c, o] = await Promise.all([
        adminApi(token).get("/admin/discord-config"),
        adminApi(token).get("/admin/discord/orders"),
      ]);
      setCfg(c.data);
      setRole(c.data.developer_role_name || "Developer");
      setOrders(o.data.orders || []);
    } catch {
      toast.error("Failed to load Discord data");
    }
    setLoading(false);
  };
  useEffect(() => {
    load();
  }, [token]);

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await adminApi(token).post("/admin/discord-config", {
        bot_token: botToken || undefined,
        developer_role_name: role,
        shared_secret: secret,
      });
      toast.success("Discord config saved");
      setSecret("");
      setBotToken("");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    }
    setSaving(false);
  };

  const genSecret = () => {
    const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    let out = "";
    for (let i = 0; i < 32; i++) out += chars[Math.floor(Math.random() * chars.length)];
    setSecret(out);
  };

  return (
    <div className="space-y-6">
      <form
        onSubmit={save}
        data-testid="discord-form"
        className="bg-[#1a1525] border border-white/5 rounded-sm p-6 md:p-8 max-w-2xl"
      >
        <h2 className="font-display font-bold text-lg mb-1">Discord Bot Configuration</h2>
        <p className="text-xs text-white/50 mb-5">
          Shared secret is used by your Discord bot to authenticate with the backend. Set the same value
          as the bot's <code className="text-[#FF007F]">BS_BOT_SHARED_SECRET</code> env var.
        </p>
        {cfg && (
          <div className="mb-4 p-3 rounded-sm bg-[#00E5FF]/10 border border-[#00E5FF]/30 text-xs text-[#00E5FF]">
            {cfg.configured ? "Bot configured" : "Not configured yet"} · role:{" "}
            <b>{cfg.developer_role_name}</b>
            {cfg.configured && (
              <>
                {" "}
                · token: {cfg.bot_token_masked} · secret: {cfg.shared_secret_masked}
              </>
            )}
          </div>
        )}
        <div className="space-y-4">
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">
              Discord Bot Token
            </Label>
            <Input
              data-testid="discord-bot-token"
              type="password"
              value={botToken}
              onChange={(e) => setBotToken(e.target.value)}
              placeholder={cfg?.configured ? "re-enter to update" : "MTA..."}
              className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs"
            />
            <p className="text-[10px] text-white/40 mt-1">
              From https://discord.com/developers/applications → Bot → Token. Stored here for your
              reference; the bot process itself reads it from its environment variable.
            </p>
          </div>
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">
              Developer Role Name
            </Label>
            <Input
              data-testid="discord-role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              required
              className="bg-[#0d0a14] border-white/10 mt-1"
            />
            <p className="text-[10px] text-white/40 mt-1">
              Members with this exact role can order without a coupon. Everyone else must supply one.
            </p>
          </div>
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">
              Shared Secret
            </Label>
            <div className="flex gap-2 mt-1">
              <Input
                data-testid="discord-secret"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                placeholder={cfg?.configured ? "re-enter to rotate" : "32+ chars"}
                className="bg-[#0d0a14] border-white/10 font-mono text-xs"
              />
              <button
                type="button"
                onClick={genSecret}
                data-testid="discord-gen-secret"
                className="px-3 bg-white/5 hover:bg-white/10 rounded-sm text-xs font-bold uppercase tracking-wider whitespace-nowrap"
              >
                Generate
              </button>
            </div>
          </div>
        </div>
        <button
          type="submit"
          disabled={saving || !secret}
          data-testid="discord-save"
          className="mt-5 px-6 py-3 gradient-pp rounded-sm font-bold tracking-wide hover:opacity-90 transition disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save Discord config"}
        </button>
      </form>

      <div className="bg-[#1a1525] border border-white/5 rounded-sm p-6">
        <h2 className="font-display font-bold text-lg mb-3">How to run the bot</h2>
        <ol className="text-sm text-white/70 space-y-2 list-decimal ml-5">
          <li>
            SSH to the VPS and cd to <code className="text-[#FF007F]">/opt/better-social/discord_bot</code>
          </li>
          <li>
            Install deps once:{" "}
            <code className="text-[#00E5FF]">sudo /opt/better-social/backend/venv/bin/pip install "discord.py&gt;=2.3"</code>
          </li>
          <li>Follow the README to add the systemd service and start it</li>
          <li>
            In Discord: create a <b>{role}</b> role and assign it to team members who should order free
          </li>
          <li>
            Invite the bot with <code className="text-[#FF007F]">bot</code> +{" "}
            <code className="text-[#FF007F]">applications.commands</code> scopes
          </li>
        </ol>
      </div>

      <div className="bg-[#1a1525] border border-white/5 rounded-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-white/5 flex justify-between items-center">
          <h2 className="font-display font-bold text-lg">Discord Orders</h2>
          <button onClick={load} className="text-xs uppercase tracking-wider text-white/60 hover:text-white">
            Refresh
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="discord-orders-table">
            <thead className="text-[10px] uppercase tracking-[0.2em] text-white/40 bg-[#0d0a14]">
              <tr>
                <th className="text-left px-6 py-3">Date</th>
                <th className="text-left px-6 py-3">Discord User</th>
                <th className="text-left px-6 py-3">Dev?</th>
                <th className="text-left px-6 py-3">Service</th>
                <th className="text-left px-6 py-3">Link</th>
                <th className="text-left px-6 py-3">Qty</th>
                <th className="text-left px-6 py-3">Price</th>
                <th className="text-left px-6 py-3">Coupon</th>
                <th className="text-left px-6 py-3">SMM ID</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={9} className="text-center py-10 text-white/40">
                    <Loader2 className="inline w-4 h-4 animate-spin mr-2" /> Loading…
                  </td>
                </tr>
              )}
              {!loading && orders.length === 0 && (
                <tr>
                  <td colSpan={9} className="text-center py-10 text-white/40 text-xs">
                    No Discord orders yet.
                  </td>
                </tr>
              )}
              {orders.map((o) => (
                <tr key={o.id} className="border-t border-white/5 hover:bg-white/[0.02]">
                  <td className="px-6 py-3 font-mono text-xs text-white/60">
                    {new Date(o.created_at).toLocaleString()}
                  </td>
                  <td className="px-6 py-3 text-[#00E5FF] font-mono text-xs">{o.discord_username || "—"}</td>
                  <td className="px-6 py-3 text-xs">
                    {o.is_developer ? (
                      <span className="text-[10px] uppercase tracking-wider bg-[#FFB800]/20 text-[#FFB800] px-2 py-1 rounded-sm">
                        dev
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-6 py-3 text-xs">{o.service_type || `#${o.service_id}`}</td>
                  <td className="px-6 py-3 text-xs truncate max-w-[160px]">{o.link}</td>
                  <td className="px-6 py-3 font-mono">{o.quantity}</td>
                  <td className="px-6 py-3 font-mono text-[#FF007F]">${o.price_usd?.toFixed(2)}</td>
                  <td className="px-6 py-3 font-mono text-xs">{o.coupon_code || "—"}</td>
                  <td className="px-6 py-3 font-mono text-xs">{o.smm_order_id || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function CryptomusPanel({ token }) {
  const [cfg, setCfg] = useState(null);
  const [merchantUuid, setMerchantUuid] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const r = await adminApi(token).get("/admin/cryptomus-config");
      setCfg(r.data);
      if (r.data.configured) setMerchantUuid(r.data.merchant_uuid || "");
    } catch {}
  };
  useEffect(() => {
    load();
  }, [token]);

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await adminApi(token).post("/admin/cryptomus-config", {
        merchant_uuid: merchantUuid,
        payment_api_key: apiKey,
      });
      toast.success("Cryptomus configured");
      setApiKey("");
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
      data-testid="cryptomus-form"
      className="bg-[#1a1525] border border-white/5 rounded-sm p-8 max-w-2xl"
    >
      <div className="flex items-center gap-3 mb-6">
        <KeyRound className="w-5 h-5 text-[#FF007F]" />
        <h2 className="font-display font-bold text-lg">Cryptomus Payment Gateway</h2>
      </div>
      {cfg?.configured && (
        <div className="mb-4 p-3 rounded-sm bg-[#00E5FF]/10 border border-[#00E5FF]/30 text-xs text-[#00E5FF]">
          Configured · merchant: {cfg.merchant_uuid} · api key: {cfg.payment_api_key_masked}
        </div>
      )}
      <div className="space-y-4">
        <div>
          <Label className="text-[11px] uppercase tracking-wider text-white/60">
            Merchant UUID
          </Label>
          <Input
            data-testid="cryptomus-merchant"
            value={merchantUuid}
            onChange={(e) => setMerchantUuid(e.target.value)}
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs"
            required
          />
          <p className="text-[10px] text-white/40 mt-1">
            Dashboard → Merchant → API → Merchant UUID
          </p>
        </div>
        <div>
          <Label className="text-[11px] uppercase tracking-wider text-white/60">
            Payment API Key
          </Label>
          <Input
            data-testid="cryptomus-api-key"
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="re-enter to update"
            className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs"
            required
          />
          <p className="text-[10px] text-white/40 mt-1">
            Used to sign requests and verify webhook postbacks.
          </p>
        </div>
        <div className="p-3 bg-[#0d0a14] border border-white/5 rounded-sm">
          <div className="text-[10px] uppercase tracking-wider text-white/50 mb-1">
            Webhook URL (add this in Cryptomus dashboard)
          </div>
          <div className="font-mono text-xs text-[#00E5FF] break-all">
            {typeof window !== "undefined" ? window.location.origin : ""}/api/cryptomus/webhook
          </div>
        </div>
      </div>
      <button
        type="submit"
        disabled={saving}
        data-testid="cryptomus-save-btn"
        className="mt-6 px-6 py-3 gradient-pp rounded-sm font-bold tracking-wide hover:opacity-90 transition disabled:opacity-50"
      >
        {saving ? "Saving…" : "Save Cryptomus credentials"}
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


function AIInboxPanel({ token, displayName }) {
  const [sessions, setSessions] = useState([]);
  const [waiting, setWaiting] = useState(0);
  const [activeId, setActiveId] = useState(null);
  const [activeSess, setActiveSess] = useState(null);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingList, setLoadingList] = useState(true);
  const [staffName, setStaffName] = useState("Support");
  const [savingName, setSavingName] = useState(false);
  const [offlineMsgs, setOfflineMsgs] = useState([]);
  const [showOffline, setShowOffline] = useState(false);
  const [soundOn, setSoundOn] = useState(
    typeof localStorage !== "undefined"
      ? localStorage.getItem("bs_inbox_sound") !== "0"
      : true
  );
  const prevWaitingRef = useRef(0);
  const audioRef = useRef(null);
  const originalTitleRef = useRef(typeof document !== "undefined" ? document.title : "Admin");
  const titleFlashRef = useRef(null);
  const lastTypingPingRef = useRef(0);

  const pingTyping = () => {
    if (!activeId) return;
    const now = Date.now();
    if (now - lastTypingPingRef.current < 3000) return; // throttle to 1 ping every 3s
    lastTypingPingRef.current = now;
    adminApi(token).post(`/ai/admin/sessions/${activeId}/typing`).catch(() => {});
  };

  const massDelete = async () => {
    if (!window.confirm("Delete ALL AI chat sessions and messages? This wipes the inbox completely (bans are kept).")) return;
    try {
      const r = await adminApi(token).post(`/ai/admin/sessions/clear-all`);
      toast.success(`Cleared ${r.data.sessions_deleted} sessions, ${r.data.messages_deleted} messages`);
      setActiveId(null);
      setActiveSess(null);
      setMessages([]);
      loadSessions();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    }
  };

  // Lazy-init the alert sound — short pleasant chime (data URI = no asset needed)
  const playChime = () => {
    if (!soundOn) return;
    try {
      // Web Audio API tone for reliability
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      const ctx = audioRef.current || new AC();
      audioRef.current = ctx;
      // Two-note chime (G5 → C6)
      const playNote = (freq, start, dur) => {
        const o = ctx.createOscillator();
        const g = ctx.createGain();
        o.type = "sine";
        o.frequency.setValueAtTime(freq, ctx.currentTime + start);
        g.gain.setValueAtTime(0, ctx.currentTime + start);
        g.gain.linearRampToValueAtTime(0.18, ctx.currentTime + start + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + dur);
        o.connect(g);
        g.connect(ctx.destination);
        o.start(ctx.currentTime + start);
        o.stop(ctx.currentTime + start + dur + 0.05);
      };
      playNote(784, 0, 0.22);     // G5
      playNote(1047, 0.18, 0.32); // C6
    } catch {
      // browser blocked audio (no user gesture) — silently skip
    }
  };

  const startTitleFlash = (count) => {
    if (titleFlashRef.current) clearInterval(titleFlashRef.current);
    const original = originalTitleRef.current;
    let on = true;
    titleFlashRef.current = setInterval(() => {
      document.title = on ? `🔴 (${count}) waiting — ${original}` : original;
      on = !on;
    }, 1200);
  };

  const stopTitleFlash = () => {
    if (titleFlashRef.current) {
      clearInterval(titleFlashRef.current);
      titleFlashRef.current = null;
    }
    document.title = originalTitleRef.current;
  };

  // Cleanup title on unmount
  useEffect(() => {
    return () => stopTitleFlash();
  }, []);

  // React to waiting count changes
  useEffect(() => {
    const prev = prevWaitingRef.current;
    if (waiting > prev) {
      playChime();
    }
    if (waiting > 0) {
      startTitleFlash(waiting);
    } else {
      stopTitleFlash();
    }
    prevWaitingRef.current = waiting;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [waiting]);

  const toggleSound = () => {
    const next = !soundOn;
    setSoundOn(next);
    if (typeof localStorage !== "undefined") {
      localStorage.setItem("bs_inbox_sound", next ? "1" : "0");
    }
    if (next) {
      // Play a small confirmation chime so user knows it works (also unlocks audio context on mobile)
      setTimeout(() => playChime(), 50);
    }
  };

  const loadSessions = async () => {
    try {
      const r = await adminApi(token).get("/ai/admin/sessions");
      setSessions(r.data.sessions || []);
      setWaiting(r.data.handover_waiting || 0);
    } catch {
      // ignore
    } finally {
      setLoadingList(false);
    }
  };

  const loadMessages = async (sid) => {
    try {
      const r = await adminApi(token).get(`/ai/admin/sessions/${sid}/messages`);
      setMessages(r.data.messages || []);
      setActiveSess(r.data.session || null);
    } catch {
      toast.error("Failed to load conversation");
    }
  };

  const loadSettings = async () => {
    try {
      const r = await adminApi(token).get("/ai/admin/settings");
      setStaffName(r.data.staff_display_name || "Support");
    } catch {
      // ignore
    }
  };

  const loadOffline = async () => {
    try {
      const r = await adminApi(token).get("/ai/admin/offline-messages");
      setOfflineMsgs(r.data.messages || []);
    } catch {
      // ignore
    }
  };

  const heartbeat = async () => {
    try {
      await adminApi(token).post("/ai/admin/heartbeat");
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    loadSessions();
    loadSettings();
    loadOffline();
    heartbeat();
    const t = setInterval(() => {
      loadSessions();
      heartbeat();
      loadOffline();
    }, 8000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    if (!activeId) return;
    loadMessages(activeId);
    const t = setInterval(() => loadMessages(activeId), 4000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, token]);

  const saveStaffName = async (e) => {
    e?.preventDefault();
    const n = staffName.trim();
    if (!n) return;
    setSavingName(true);
    try {
      await adminApi(token).post("/ai/admin/settings", { staff_display_name: n });
      toast.success(`Staff name set to "${n}"`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    } finally {
      setSavingName(false);
    }
  };

  const takeover = async () => {
    if (!activeId) return;
    try {
      await adminApi(token).post(`/ai/admin/sessions/${activeId}/takeover`);
      toast.success("You're now handling this chat");
      loadMessages(activeId);
      loadSessions();
    } catch {
      toast.error("Failed");
    }
  };

  const release = async () => {
    if (!activeId) return;
    try {
      await adminApi(token).post(`/ai/admin/sessions/${activeId}/release`);
      toast.success("AI is back in the chat");
      loadMessages(activeId);
      loadSessions();
    } catch {
      toast.error("Failed");
    }  };

  const muteChat = async () => {
    if (!activeId) return;
    const mins = window.prompt("Mute for how many minutes?", "60");
    if (!mins) return;
    const m = parseInt(mins, 10);
    if (!m || m < 1) return;
    try {
      await adminApi(token).post(`/ai/admin/sessions/${activeId}/mute`, { minutes: m });
      toast.success(`Muted for ${m} min`);
      loadMessages(activeId);
      loadSessions();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  const unmuteChat = async () => {
    if (!activeId) return;
    try {
      await adminApi(token).post(`/ai/admin/sessions/${activeId}/unmute`);
      toast.success("Unmuted");
      loadMessages(activeId);
      loadSessions();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  const banChat = async () => {
    if (!activeId) return;
    if (!window.confirm("Permanently ban this identifier from the AI chat?")) return;
    try {
      const r = await adminApi(token).post(`/ai/admin/sessions/${activeId}/ban`);
      toast.success(`Banned ${r.data.banned}`);
      loadMessages(activeId);
      loadSessions();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  const send = async (e) => {
    e?.preventDefault();
    const t = text.trim();
    if (!t || !activeId || sending) return;
    setSending(true);
    try {
      await adminApi(token).post(`/ai/admin/sessions/${activeId}/send`, {
        text: t,
      });
      setText("");
      loadMessages(activeId);
      loadSessions();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to send");
    } finally {
      setSending(false);
    }
  };

  const markOfflineRead = async (id) => {
    try {
      await adminApi(token).post(`/ai/admin/offline-messages/${id}/mark-read`);
      loadOffline();
    } catch {
      // ignore
    }
  };

  const fmtTime = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleString();
  };

  const isHuman = activeSess?.status === "human";
  const needsHandover = !!activeSess?.needs_handover;
  const newOffline = offlineMsgs.filter((m) => m.status === "new").length;

  return (
    <div className="space-y-4">
      {/* Top toolbar — staff name + offline messages toggle */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 bg-[#1a1525] border border-white/5 rounded-sm p-4">
        <form onSubmit={saveStaffName} className="flex items-center gap-2">
          <Label className="text-[11px] uppercase tracking-wider text-white/60 shrink-0">
            Staff name (shown to user)
          </Label>
          <Input
            data-testid="staff-name-input"
            value={staffName}
            onChange={(e) => setStaffName(e.target.value)}
            maxLength={40}
            className="bg-[#0d0a14] border-white/10 max-w-[180px] text-sm"
          />
          <button
            type="submit"
            disabled={savingName}
            data-testid="staff-name-save"
            className="px-3 py-2 gradient-pp rounded-sm text-[10px] uppercase tracking-wider font-bold disabled:opacity-50"
          >
            {savingName ? <Loader2 className="w-3 h-3 animate-spin" /> : "Save"}
          </button>
        </form>
        <div className="flex items-center gap-3">
          {waiting > 0 && (
            <span
              data-testid="handover-waiting-badge"
              className="text-[10px] uppercase tracking-wider px-2.5 py-1 rounded-full bg-[#FF007F]/20 border border-[#FF007F]/40 text-[#FF007F] font-bold animate-pulse"
            >
              🔴 {waiting} waiting for staff
            </span>
          )}
          <button
            onClick={toggleSound}
            data-testid="sound-toggle"
            title={soundOn ? "Sound alerts ON — click to mute" : "Sound alerts OFF — click to enable"}
            className={`w-9 h-9 rounded-sm border inline-flex items-center justify-center transition ${
              soundOn
                ? "border-[#00E5FF]/40 text-[#00E5FF] bg-[#00E5FF]/5 hover:bg-[#00E5FF]/10"
                : "border-white/20 text-white/40 hover:bg-white/5"
            }`}
            aria-label={soundOn ? "Mute alerts" : "Enable sound alerts"}
          >
            {soundOn ? <Bell className="w-4 h-4" /> : <BellOff className="w-4 h-4" />}
          </button>
          <button
            onClick={() => setShowOffline((v) => !v)}
            data-testid="offline-msgs-toggle"
            className="px-3 py-2 text-[10px] uppercase tracking-wider border border-white/20 rounded-sm hover:bg-white/5 inline-flex items-center gap-2"
          >
            Offline messages
            {newOffline > 0 && (
              <span className="px-1.5 py-0.5 rounded-full bg-[#FF007F] text-white text-[9px] font-bold">
                {newOffline}
              </span>
            )}
          </button>
          <ChatBansButton token={token} />
          <button
            onClick={massDelete}
            data-testid="inbox-clear-all"
            className="px-3 py-2 text-[10px] uppercase tracking-wider border border-red-500/40 text-red-300 rounded-sm hover:bg-red-500/10 inline-flex items-center gap-1"
            title="Wipe ALL chat sessions and messages"
          >
            <Trash2 className="w-3 h-3" /> Clear all
          </button>
        </div>
      </div>

      {/* Offline messages drawer */}
      {showOffline && (
        <div
          data-testid="offline-messages-list"
          className="bg-[#1a1525] border border-white/5 rounded-sm overflow-hidden"
        >
          <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
            <h3 className="font-display font-bold text-sm">Offline messages</h3>
            <span className="text-[10px] uppercase tracking-wider text-white/40">
              {offlineMsgs.length}
            </span>
          </div>
          <div className="max-h-72 overflow-y-auto">
            {offlineMsgs.length === 0 && (
              <div className="p-4 text-xs text-white/40">Nothing here yet.</div>
            )}
            {offlineMsgs.map((m) => (
              <div
                key={m.id}
                data-testid={`offline-msg-${m.id}`}
                className={`px-4 py-3 border-b border-white/5 ${
                  m.status === "new" ? "bg-[#FF007F]/5" : ""
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-mono text-xs text-[#00E5FF] truncate">{m.email}</div>
                    <div className="text-[10px] text-white/40 font-mono mt-0.5">
                      {fmtTime(m.created_at)} · {m.ip}
                    </div>
                  </div>
                  {m.status === "new" && (
                    <button
                      onClick={() => markOfflineRead(m.id)}
                      data-testid={`mark-read-${m.id}`}
                      className="text-[10px] uppercase tracking-wider px-2 py-1 border border-white/20 rounded-sm hover:bg-white/5 shrink-0"
                    >
                      Mark read
                    </button>
                  )}
                </div>
                <div className="mt-2 text-sm text-white/80 whitespace-pre-wrap">
                  {m.message}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Inbox grid */}
      <div className="grid lg:grid-cols-[320px_1fr] gap-6 h-[calc(100vh-320px)] min-h-[480px]">
        {/* Sessions list */}
        <div
          data-testid="ai-inbox-sessions"
          className="bg-[#1a1525] border border-white/5 rounded-sm overflow-hidden flex flex-col"
        >
          <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
            <h3 className="font-display font-bold text-sm">Conversations</h3>
            <span className="text-[10px] uppercase tracking-wider text-white/40">
              {sessions.length}
            </span>
          </div>
          <div className="overflow-y-auto flex-1">
            {loadingList && (
              <div className="p-4 text-xs text-white/40">Loading…</div>
            )}
            {!loadingList && sessions.length === 0 && (
              <div className="p-4 text-xs text-white/40">No AI chats yet.</div>
            )}
            {sessions.map((s) => {
              const active = s.session_id === activeId;
              const human = s.status === "human";
              const handover = s.needs_handover && !human;
              return (
                <button
                  key={s.session_id}
                  onClick={() => setActiveId(s.session_id)}
                  data-testid={`inbox-session-${s.session_id}`}
                  className={`w-full text-left px-4 py-3 border-b border-white/5 hover:bg-white/[0.03] transition ${
                    active ? "bg-[#FF007F]/10 border-l-2 border-l-[#FF007F]" : ""
                  } ${handover ? "bg-[#FF007F]/[0.07]" : ""}`}
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="font-mono text-[11px] text-white/80 truncate">
                      {s.identified_as || s.session_id}
                    </span>
                    <div className="flex items-center gap-1 shrink-0">
                      {handover && (
                        <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm bg-[#FF007F]/20 text-[#FF007F] font-bold animate-pulse">
                          Wants Staff
                        </span>
                      )}
                      {human && (
                        <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm bg-[#00E5FF]/20 text-[#00E5FF] font-bold">
                          Live
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="text-xs text-white/50 truncate">
                    {s.last_user_text || "—"}
                  </div>
                  <div className="text-[10px] text-white/30 mt-1 font-mono flex items-center justify-between">
                    <span>{fmtTime(s.last_activity)}</span>
                    {s.identified_kind && (
                      <span className="uppercase tracking-wider opacity-70">
                        {s.identified_kind}
                      </span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Conversation */}
        <div
          data-testid="ai-inbox-conversation"
          className="bg-[#1a1525] border border-white/5 rounded-sm flex flex-col overflow-hidden"
        >
          {!activeId ? (
            <div className="flex-1 flex items-center justify-center text-sm text-white/40">
              Pick a conversation on the left.
            </div>
          ) : (
            <>
              <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-display font-bold text-sm truncate flex items-center gap-2">
                    {activeSess?.identified_as || activeId}
                    {needsHandover && !isHuman && (
                      <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm bg-[#FF007F]/20 text-[#FF007F] font-bold animate-pulse">
                        Wants Staff
                      </span>
                    )}
                  </div>
                  <div className="text-[10px] uppercase tracking-wider text-white/40 truncate">
                    {activeSess?.identified_kind && (
                      <span className="mr-2">{activeSess.identified_kind}</span>
                    )}
                    {isHuman
                      ? `You're handling this as "${staffName}"`
                      : needsHandover
                      ? "User asked for staff — Take Over now"
                      : "AI handling · click Take Over to reply"}
                  </div>
                  {(activeSess?.ip || activeSess?.country || activeSess?.isp) && (
                    <div
                      data-testid="session-geo"
                      className="mt-1.5 flex flex-wrap gap-1.5 text-[9px] font-mono"
                    >
                      {activeSess.country_code && (
                        <span className="px-1.5 py-0.5 rounded-sm bg-white/5 text-white/70">
                          {activeSess.country_code} · {activeSess.country}
                          {activeSess.city ? ` · ${activeSess.city}` : ""}
                        </span>
                      )}
                      {activeSess.ip && (
                        <span className="px-1.5 py-0.5 rounded-sm bg-white/5 text-[#00E5FF]/80">
                          IP: {activeSess.ip}
                        </span>
                      )}
                      {activeSess.isp && (
                        <span className="px-1.5 py-0.5 rounded-sm bg-white/5 text-amber-300/80 truncate max-w-[260px]" title={activeSess.isp}>
                          ISP: {activeSess.isp}
                        </span>
                      )}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {!isHuman ? (
                    <button
                      onClick={takeover}
                      data-testid="inbox-takeover"
                      className={`px-3 py-1.5 text-[10px] uppercase tracking-wider rounded-sm font-bold ${
                        needsHandover ? "gradient-pp animate-pulse" : "gradient-pp"
                      }`}
                    >
                      Take Over
                    </button>
                  ) : (
                    <button
                      onClick={release}
                      data-testid="inbox-release"
                      className="px-3 py-1.5 text-[10px] uppercase tracking-wider border border-white/20 rounded-sm hover:bg-white/5"
                    >
                      Leave Chat
                    </button>
                  )}
                  {activeSess?.muted_until ? (
                    <button
                      onClick={unmuteChat}
                      data-testid="inbox-unmute"
                      title={`Muted until ${activeSess.muted_until}`}
                      className="px-3 py-1.5 text-[10px] uppercase tracking-wider border border-amber-500/40 text-amber-300 rounded-sm hover:bg-amber-500/10"
                    >
                      Unmute
                    </button>
                  ) : (
                    <button
                      onClick={muteChat}
                      data-testid="inbox-mute"
                      className="px-3 py-1.5 text-[10px] uppercase tracking-wider border border-white/20 text-white/70 rounded-sm hover:bg-white/5"
                    >
                      Mute
                    </button>
                  )}
                  <button
                    onClick={banChat}
                    data-testid="inbox-ban"
                    disabled={!activeSess?.identified_as}
                    className="px-3 py-1.5 text-[10px] uppercase tracking-wider border border-red-500/40 text-red-400 rounded-sm hover:bg-red-500/10 disabled:opacity-30"
                  >
                    Ban
                  </button>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-[#0d0a14]">
                {messages.length === 0 && (
                  <div className="text-xs text-white/40 text-center py-12">
                    No messages yet.
                  </div>
                )}
                {messages.map((m) => {
                  const isUser = m.role === "user";
                  const isAdmin = m.role === "admin";
                  const cleanText = (m.text || "")
                    .replace(/READY_TO_ORDER:[\s\S]*?(\{[\s\S]*?\})\s*/g, "")
                    .trim();
                  const atts = Array.isArray(m.attachments) ? m.attachments : [];
                  return (
                    <div
                      key={m.id}
                      className={`flex ${isUser ? "justify-start" : "justify-end"}`}
                    >
                      <div className="max-w-[78%]">
                        {atts.length > 0 && (
                          <div className={`flex flex-wrap gap-1.5 mb-1.5 ${isUser ? "" : "justify-end"}`}>
                            {atts.map((a) => {
                              const url = `/api/ai/uploads/${a.id}`;
                              const isImg = (a.content_type || "").startsWith("image/");
                              if (isImg) {
                                return (
                                  <a
                                    key={a.id}
                                    href={url}
                                    target="_blank"
                                    rel="noreferrer"
                                    data-testid={`inbox-image-${a.id}`}
                                    className="block rounded-sm overflow-hidden border border-white/10 hover:border-[#00E5FF] transition"
                                  >
                                    <img
                                      src={url}
                                      alt={a.filename}
                                      className="max-w-[200px] max-h-[200px] object-cover block"
                                    />
                                  </a>
                                );
                              }
                              return (
                                <a
                                  key={a.id}
                                  href={url}
                                  target="_blank"
                                  rel="noreferrer"
                                  data-testid={`inbox-file-${a.id}`}
                                  className="inline-flex items-center gap-2 px-2 py-1.5 bg-white/10 hover:bg-white/15 rounded-sm border border-white/10 text-[11px] text-white max-w-[200px]"
                                >
                                  <FileText className="w-3 h-3 shrink-0" />
                                  <span className="truncate">{a.filename}</span>
                                </a>
                              );
                            })}
                          </div>
                        )}
                        {(cleanText || !atts.length) && (
                          <div
                            className={`px-3 py-2 rounded-sm text-sm whitespace-pre-wrap leading-snug ${
                              isUser
                                ? "bg-[#1a1525] border border-white/10 text-white/90"
                                : isAdmin
                                ? "bg-[#00E5FF] text-[#050505] font-medium"
                                : "bg-[#FF007F] text-white"
                            }`}
                          >
                            {cleanText || (isUser ? "(empty)" : "…")}
                            <div className={`text-[9px] mt-1 ${isAdmin ? "text-[#050505]/60" : "text-white/40"}`}>
                              {isAdmin ? `${m.admin_name || staffName} · ` : ""}
                              {fmtTime(m.created_at)}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              <form
                onSubmit={send}
                className="border-t border-white/5 p-3 bg-[#050505]"
              >
                <div className="text-[10px] uppercase tracking-wider text-emerald-400/80 mb-1.5 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  Replying as <span className="text-white font-bold">{displayName || staffName}</span>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    data-testid="inbox-input"
                    value={text}
                    onChange={(e) => {
                      setText(e.target.value);
                      if (e.target.value.trim()) pingTyping();
                    }}
                    placeholder={isHuman ? `Reply as "${displayName || staffName}"…` : "Click Take Over first to reply…"}
                    className="flex-1 bg-[#1a1525] border border-white/10 rounded-sm px-3 py-2 text-sm outline-none focus:border-[#FF007F]"
                  />
                  <button
                    type="submit"
                    disabled={sending || !text.trim() || !isHuman}
                    data-testid="inbox-send"
                    className="px-4 py-2 gradient-pp rounded-sm text-xs uppercase tracking-wider font-bold disabled:opacity-40"
                  >
                    {sending ? <Loader2 className="w-3 h-3 animate-spin" /> : "Send"}
                  </button>
                </div>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function UsersPanel({ token }) {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState(null); // user doc
  const [edit, setEdit] = useState({ email: "", role: "user", new_password: "" });
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await adminApi(token).get("/admin/users");
      setUsers(r.data.users || []);
    } catch {
      toast.error("Failed to load users");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const filtered = users.filter((u) => {
    const s = search.trim().toLowerCase();
    if (!s) return true;
    return (
      (u.username || "").toLowerCase().includes(s) ||
      (u.email || "").toLowerCase().includes(s)
    );
  });

  const startEdit = (u) => {
    setEditing(u);
    setEdit({
      email: u.email || "",
      role: u.role || "user",
      new_password: "",
    });
  };

  const saveEdit = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      const payload = {};
      if (edit.email && edit.email !== editing.email) payload.email = edit.email;
      if (edit.role && edit.role !== editing.role) payload.role = edit.role;
      if (edit.new_password) payload.new_password = edit.new_password;
      if (Object.keys(payload).length === 0) {
        toast.error("Nothing changed");
        setSaving(false);
        return;
      }
      await adminApi(token).put(`/admin/users/${editing.id}`, payload);
      toast.success("User updated");
      setEditing(null);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to update");
    } finally {
      setSaving(false);
    }
  };

  const mute = async (u, minutes) => {
    try {
      await adminApi(token).post(`/admin/users/${u.id}/mute`, { minutes });
      toast.success(`${u.username} muted for ${minutes} min`);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  const unmute = async (u) => {
    try {
      await adminApi(token).post(`/admin/users/${u.id}/unmute`);
      toast.success(`${u.username} unmuted`);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  const remove = async (u) => {
    if (!window.confirm(`Delete user "${u.username}"? This cannot be undone.`)) return;
    try {
      await adminApi(token).delete(`/admin/users/${u.id}`);
      toast.success(`Deleted ${u.username}`);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  const fmtDate = (iso) => {
    if (!iso) return "—";
    return new Date(iso).toLocaleDateString();
  };

  const isMuted = (u) => {
    if (!u.muted_until) return false;
    return new Date(u.muted_until) > new Date();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 bg-[#1a1525] border border-white/5 rounded-sm p-4">
        <div>
          <h3 className="font-display font-bold text-sm">All Registered Users</h3>
          <div className="text-[11px] text-white/40 mt-0.5">{users.length} total</div>
        </div>
        <Input
          data-testid="users-search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search username or email…"
          className="bg-[#0d0a14] border-white/10 max-w-xs text-sm"
        />
      </div>

      <div className="bg-[#1a1525] border border-white/5 rounded-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-[#0d0a14] text-[10px] uppercase tracking-wider text-white/50">
              <tr>
                <th className="text-left px-6 py-3">User</th>
                <th className="text-left px-6 py-3">Email</th>
                <th className="text-left px-6 py-3">Role</th>
                <th className="text-left px-6 py-3">Joined</th>
                <th className="text-left px-6 py-3">Status</th>
                <th className="text-right px-6 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-white/40 text-xs">
                    Loading…
                  </td>
                </tr>
              )}
              {!loading && filtered.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-white/40 text-xs">
                    No users.
                  </td>
                </tr>
              )}
              {filtered.map((u) => {
                const muted = isMuted(u);
                return (
                  <tr
                    key={u.id}
                    data-testid={`user-row-${u.id}`}
                    className="border-t border-white/5 hover:bg-white/[0.02]"
                  >
                    <td className="px-6 py-3 font-mono text-white/90">{u.username}</td>
                    <td className="px-6 py-3 text-white/60">{u.email}</td>
                    <td className="px-6 py-3">
                      <span
                        className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-sm ${
                          u.role === "owner"
                            ? "bg-[#FF007F]/20 text-[#FF007F]"
                            : u.role === "admin"
                            ? "bg-[#00E5FF]/20 text-[#00E5FF]"
                            : "bg-white/10 text-white/60"
                        }`}
                      >
                        {u.role}
                      </span>
                    </td>
                    <td className="px-6 py-3 text-white/50 text-xs">{fmtDate(u.created_at)}</td>
                    <td className="px-6 py-3">
                      {muted ? (
                        <span className="text-[10px] uppercase tracking-wider text-[#FF3B30] font-bold">
                          Muted
                        </span>
                      ) : (
                        <span className="text-[10px] uppercase tracking-wider text-white/40">
                          Active
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-3">
                      <div className="flex items-center gap-2 justify-end">
                        <button
                          onClick={() => startEdit(u)}
                          data-testid={`edit-user-${u.id}`}
                          title="Edit user"
                          className="text-white/60 hover:text-[#00E5FF]"
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                        {muted ? (
                          <button
                            onClick={() => unmute(u)}
                            data-testid={`unmute-user-${u.id}`}
                            title="Unmute"
                            className="text-[10px] uppercase tracking-wider px-2 py-1 border border-white/10 rounded-sm hover:bg-white/5"
                          >
                            Unmute
                          </button>
                        ) : (
                          <button
                            onClick={() => mute(u, 1440)}
                            data-testid={`mute-user-${u.id}`}
                            title="Mute for 24h"
                            className="text-[10px] uppercase tracking-wider px-2 py-1 border border-white/10 rounded-sm hover:bg-white/5"
                          >
                            Mute 24h
                          </button>
                        )}
                        {u.role !== "owner" && (
                          <button
                            onClick={() => remove(u)}
                            data-testid={`delete-user-${u.id}`}
                            title="Delete user"
                            className="text-white/60 hover:text-[#FF3B30]"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {editing && (
        <div
          data-testid="edit-user-modal"
          className="fixed inset-0 z-[80] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => !saving && setEditing(null)}
        >
          <div
            className="w-full max-w-md bg-[#1a1525] border border-white/10 rounded-sm p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="font-display font-bold text-lg mb-1">Edit User</h3>
            <div className="text-xs text-white/50 font-mono mb-4">{editing.username}</div>
            <div className="space-y-3">
              <div>
                <Label className="text-[11px] uppercase tracking-wider text-white/60">
                  Email
                </Label>
                <Input
                  data-testid="edit-user-email"
                  type="email"
                  value={edit.email}
                  onChange={(e) => setEdit({ ...edit, email: e.target.value })}
                  className="bg-[#0d0a14] border-white/10 mt-1"
                />
              </div>
              <div>
                <Label className="text-[11px] uppercase tracking-wider text-white/60">
                  Role
                </Label>
                <select
                  data-testid="edit-user-role"
                  value={edit.role}
                  onChange={(e) => setEdit({ ...edit, role: e.target.value })}
                  disabled={editing.role === "owner"}
                  className="w-full bg-[#0d0a14] border border-white/10 rounded-sm px-3 py-2 text-sm mt-1 disabled:opacity-50"
                >
                  <option value="user">User</option>
                  <option value="admin">Admin</option>
                  {editing.role === "owner" && <option value="owner">Owner</option>}
                </select>
              </div>
              <div>
                <Label className="text-[11px] uppercase tracking-wider text-white/60">
                  New password (optional)
                </Label>
                <Input
                  data-testid="edit-user-password"
                  type="text"
                  placeholder="leave empty to keep current"
                  value={edit.new_password}
                  onChange={(e) => setEdit({ ...edit, new_password: e.target.value })}
                  className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-sm"
                />
              </div>
            </div>
            <div className="flex gap-2 mt-5">
              <button
                onClick={() => setEditing(null)}
                disabled={saving}
                data-testid="edit-user-cancel"
                className="flex-1 py-2.5 border border-white/10 rounded-sm text-xs uppercase tracking-wider hover:bg-white/5"
              >
                Cancel
              </button>
              <button
                onClick={saveEdit}
                disabled={saving}
                data-testid="edit-user-save"
                className="flex-1 py-2.5 gradient-pp rounded-sm text-xs uppercase tracking-wider font-bold disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


function FundsAdminPanel({ token }) {
  const [paypal, setPaypal] = useState({ paypal_email: "", paypal_me_url: "" });
  const [savingPaypal, setSavingPaypal] = useState(false);
  const [tab, setTab] = useState("pending"); // pending | all
  const [txns, setTxns] = useState([]);
  const [note, setNote] = useState("");

  const load = async () => {
    try {
      const r = await adminApi(token).get(`/admin/transactions${tab === "pending" ? "?status=pending" : ""}`);
      setTxns(r.data.transactions || []);
    } catch {
      toast.error("Failed to load transactions");
    }
  };

  const loadPaypal = async () => {
    try {
      const r = await api.get("/paypal-config");
      setPaypal({
        paypal_email: r.data.paypal_email || "",
        paypal_me_url: r.data.paypal_me_url || "",
      });
    } catch {}
  };

  useEffect(() => {
    loadPaypal();
    // eslint-disable-next-line
  }, [token]);

  useEffect(() => {
    load();
    // eslint-disable-next-line
  }, [tab, token]);

  const savePaypal = async (e) => {
    e?.preventDefault();
    setSavingPaypal(true);
    try {
      await adminApi(token).post("/admin/paypal-config", paypal);
      toast.success("PayPal settings saved");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    } finally {
      setSavingPaypal(false);
    }
  };

  const decide = async (tx, action) => {
    try {
      await adminApi(token).post(`/admin/transactions/${tx.id}/${action}`, { note });
      toast.success(`${action === "approve" ? "Approved" : "Rejected"} ${tx.username}'s $${tx.amount}`);
      setNote("");
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  return (
    <div className="space-y-6">
      <form onSubmit={savePaypal} className="bg-[#1a1525] border border-white/5 rounded-sm p-5 space-y-3">
        <h3 className="font-display font-bold text-sm">PayPal Settings</h3>
        <div className="text-[11px] text-white/50">
          Your business PayPal email + paypal.me link. Users will be redirected here to pay.
        </div>
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">
              Business PayPal email
            </Label>
            <Input
              data-testid="paypal-email"
              type="email"
              placeholder="you@business.com"
              value={paypal.paypal_email}
              onChange={(e) => setPaypal({ ...paypal, paypal_email: e.target.value })}
              className="bg-[#0d0a14] border-white/10 mt-1"
            />
          </div>
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">
              paypal.me link
            </Label>
            <Input
              data-testid="paypal-me"
              placeholder="https://paypal.me/YourHandle"
              value={paypal.paypal_me_url}
              onChange={(e) => setPaypal({ ...paypal, paypal_me_url: e.target.value })}
              className="bg-[#0d0a14] border-white/10 mt-1"
            />
          </div>
        </div>
        <button
          type="submit"
          disabled={savingPaypal}
          data-testid="paypal-save"
          className="px-4 py-2 gradient-pp rounded-sm text-xs uppercase tracking-wider font-bold disabled:opacity-50 inline-flex items-center gap-2"
        >
          {savingPaypal ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
          Save
        </button>
      </form>

      <div className="bg-[#1a1525] border border-white/5 rounded-sm overflow-hidden">
        <div className="px-4 py-3 border-b border-white/5 flex items-center gap-3">
          <h3 className="font-display font-bold text-sm">Fund requests</h3>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => setTab("pending")}
              data-testid="tab-funds-pending"
              className={`text-[10px] uppercase tracking-wider px-3 py-1 rounded-sm ${
                tab === "pending" ? "bg-[#FF007F] text-white" : "border border-white/10 hover:bg-white/5"
              }`}
            >
              Pending
            </button>
            <button
              onClick={() => setTab("all")}
              data-testid="tab-funds-all"
              className={`text-[10px] uppercase tracking-wider px-3 py-1 rounded-sm ${
                tab === "all" ? "bg-[#FF007F] text-white" : "border border-white/10 hover:bg-white/5"
              }`}
            >
              All
            </button>
          </div>
        </div>
        <div className="px-4 py-3 border-b border-white/5">
          <Input
            data-testid="approval-note"
            placeholder="Optional note for the approval/rejection (e.g. tx id)…"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="bg-[#0d0a14] border-white/10 text-sm"
          />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-[10px] uppercase tracking-wider text-white/40">
              <tr>
                <th className="text-left px-6 py-2">When</th>
                <th className="text-left px-6 py-2">User</th>
                <th className="text-left px-6 py-2">Amount</th>
                <th className="text-left px-6 py-2">Method</th>
                <th className="text-left px-6 py-2">Status</th>
                <th className="text-right px-6 py-2">Action</th>
              </tr>
            </thead>
            <tbody>
              {txns.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-6 py-10 text-center text-white/30 text-xs">
                    Nothing here.
                  </td>
                </tr>
              )}
              {txns.map((t) => (
                <tr key={t.id} className="border-t border-white/5" data-testid={`admin-tx-${t.id}`}>
                  <td className="px-6 py-2 text-white/60 text-xs font-mono">
                    {new Date(t.created_at).toLocaleString()}
                  </td>
                  <td className="px-6 py-2 font-mono">{t.username}</td>
                  <td className="px-6 py-2 font-mono text-[#FF007F]">${Number(t.amount).toFixed(2)}</td>
                  <td className="px-6 py-2 text-white/60 text-xs uppercase">{t.method}</td>
                  <td className="px-6 py-2 text-[10px] uppercase tracking-wider text-white/60">{t.status}</td>
                  <td className="px-6 py-2 text-right">
                    {t.status === "pending" && (
                      <div className="inline-flex gap-2">
                        <button
                          onClick={() => decide(t, "approve")}
                          data-testid={`approve-tx-${t.id}`}
                          className="text-[10px] uppercase tracking-wider px-2 py-1 bg-emerald-500/15 border border-emerald-500/40 text-emerald-400 rounded-sm hover:bg-emerald-500/25"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => decide(t, "reject")}
                          data-testid={`reject-tx-${t.id}`}
                          className="text-[10px] uppercase tracking-wider px-2 py-1 bg-red-500/15 border border-red-500/40 text-red-400 rounded-sm hover:bg-red-500/25"
                        >
                          Reject
                        </button>
                      </div>
                    )}
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

function WithdrawalsAdminPanel({ token }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("pending");

  const load = async () => {
    setLoading(true);
    try {
      const q = filter === "all" ? "" : `?status=${filter}`;
      const r = await adminApi(token).get(`/admin/withdrawals${q}`);
      setItems(r.data.withdrawals || []);
    } catch (e) {
      toast.error("Failed to load withdrawals");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 12000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [filter]);

  const approve = async (id) => {
    const hash = window.prompt(
      "Enter the blockchain TX hash (optional — leave blank to approve without proof)",
      "",
    );
    if (hash === null) return;
    try {
      await adminApi(token).post(`/admin/withdrawals/${id}/approve`, { tx_hash: hash || null });
      toast.success("Withdrawal approved");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    }
  };

  const reject = async (id) => {
    const note = window.prompt("Reason for rejection (shown to user)", "");
    if (note === null) return;
    if (!window.confirm("Reject this withdrawal? Funds will be refunded to the user's withdrawable balance.")) return;
    try {
      await adminApi(token).post(`/admin/withdrawals/${id}/reject`, { note });
      toast.success("Withdrawal rejected & refunded");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    }
  };

  const pendingCount = items.filter((w) => w.status === "pending").length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="text-sm text-white/60">
          <span className="font-display font-black text-2xl text-white">{items.length}</span>{" "}
          <span className="text-[10px] uppercase tracking-wider">in view</span>
          {filter !== "pending" && pendingCount > 0 && (
            <span className="ml-3 inline-flex items-center gap-1 px-2 py-1 bg-amber-500/15 text-amber-300 text-[10px] uppercase tracking-wider rounded-sm">
              {pendingCount} pending
            </span>
          )}
        </div>
        <div className="ml-auto flex gap-1">
          {["pending", "approved", "rejected", "all"].map((s) => (
            <button
              key={s}
              data-testid={`withdraw-filter-${s}`}
              onClick={() => setFilter(s)}
              className={`px-3 py-1.5 text-[10px] uppercase tracking-wider rounded-sm ${
                filter === s ? "bg-[#FF007F] text-white" : "border border-white/10 text-white/60 hover:bg-white/5"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-[#1a1525] border border-white/5 rounded-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="withdrawals-table">
            <thead className="text-[10px] uppercase tracking-[0.2em] text-white/40 bg-[#0d0a14]">
              <tr>
                <th className="text-left px-5 py-3">Date</th>
                <th className="text-left px-5 py-3">User</th>
                <th className="text-right px-5 py-3">Amount</th>
                <th className="text-left px-5 py-3">Currency</th>
                <th className="text-left px-5 py-3">Address</th>
                <th className="text-left px-5 py-3">Status</th>
                <th className="text-right px-5 py-3"></th>
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
                    No withdrawals in this filter.
                  </td>
                </tr>
              )}
              {items.map((w) => (
                <tr key={w.id} className="border-t border-white/5" data-testid={`withdrawal-row-${w.id}`}>
                  <td className="px-5 py-3 text-xs font-mono text-white/60">
                    {new Date(w.created_at).toLocaleString()}
                  </td>
                  <td className="px-5 py-3 text-xs">@{w.username}</td>
                  <td className="px-5 py-3 text-right font-mono text-emerald-400">
                    ${Math.abs(Number(w.amount)).toFixed(2)}
                  </td>
                  <td className="px-5 py-3 text-xs">{w.currency}</td>
                  <td className="px-5 py-3 font-mono text-[10px] text-white/60 max-w-[260px]">
                    <div className="truncate" title={w.address}>{w.address}</div>
                    {w.tx_hash && (
                      <div className="truncate text-emerald-400/80 mt-1" title={w.tx_hash}>
                        TX: {w.tx_hash}
                      </div>
                    )}
                  </td>
                  <td className="px-5 py-3">
                    {w.status === "pending" && (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-sm bg-amber-500/15 text-amber-400 font-bold">
                        pending
                      </span>
                    )}
                    {w.status === "approved" && (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-sm bg-emerald-500/15 text-emerald-400 font-bold">
                        paid
                      </span>
                    )}
                    {w.status === "rejected" && (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-sm bg-red-500/15 text-red-400 font-bold">
                        rejected
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-3 text-right whitespace-nowrap">
                    {w.status === "pending" && (
                      <>
                        <button
                          onClick={() => approve(w.id)}
                          data-testid={`withdraw-approve-${w.id}`}
                          className="px-3 py-1 bg-emerald-500/20 text-emerald-300 rounded-sm text-[10px] uppercase tracking-wider font-bold mr-2 hover:bg-emerald-500/30"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => reject(w.id)}
                          data-testid={`withdraw-reject-${w.id}`}
                          className="px-3 py-1 bg-red-500/20 text-red-300 rounded-sm text-[10px] uppercase tracking-wider font-bold hover:bg-red-500/30"
                        >
                          Reject
                        </button>
                      </>
                    )}
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



function TicketsAdminPanel({ token, displayName }) {
  const [tickets, setTickets] = useState([]);
  const [waiting, setWaiting] = useState(0);
  const [open, setOpen] = useState(null);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);

  const load = async () => {
    try {
      const r = await adminApi(token).get("/admin/tickets");
      setTickets(r.data.tickets || []);
      setWaiting(r.data.waiting || 0);
    } catch {}
  };

  const openTicket = async (id) => {
    try {
      const r = await adminApi(token).get(`/admin/tickets/${id}`);
      setOpen(r.data);
    } catch {
      toast.error("Failed to load ticket");
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [token]);

  useEffect(() => {
    if (!open) return;
    const t = setInterval(() => openTicket(open.ticket.id), 4000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [open?.ticket?.id]);

  const send = async (e) => {
    e?.preventDefault();
    const r = reply.trim();
    if (!r || !open) return;
    setSending(true);
    try {
      await adminApi(token).post(`/admin/tickets/${open.ticket.id}/reply`, { message: r });
      setReply("");
      openTicket(open.ticket.id);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    } finally {
      setSending(false);
    }
  };

  const close = async () => {
    if (!open) return;
    if (!window.confirm("Close this ticket? User won't be able to reply.")) return;
    try {
      await adminApi(token).post(`/admin/tickets/${open.ticket.id}/close`);
      toast.success("Closed");
      openTicket(open.ticket.id);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  const remove = async () => {
    if (!open) return;
    if (!window.confirm(`Permanently DELETE ticket "${open.ticket.subject}" and all its messages? This cannot be undone.`)) return;
    try {
      await adminApi(token).delete(`/admin/tickets/${open.ticket.id}`);
      toast.success("Ticket deleted");
      setOpen(null);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  return (
    <div className="grid lg:grid-cols-[340px_1fr] gap-6 h-[calc(100vh-220px)] min-h-[480px]">
      <div className="bg-[#1a1525] border border-white/5 rounded-sm overflow-hidden flex flex-col">
        <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
          <h3 className="font-display font-bold text-sm">Tickets</h3>
          <div className="flex items-center gap-2">
            {waiting > 0 && (
              <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-sm bg-[#FF007F]/20 text-[#FF007F] font-bold animate-pulse">
                {waiting} waiting
              </span>
            )}
            <span className="text-[10px] uppercase tracking-wider text-white/40">{tickets.length}</span>
          </div>
        </div>
        <div className="overflow-y-auto flex-1">
          {tickets.length === 0 && (
            <div className="p-4 text-xs text-white/40">No tickets yet.</div>
          )}
          {tickets.map((t) => {
            const active = open?.ticket?.id === t.id;
            const isWaiting = t.last_reply_by === "user" && t.status === "open";
            return (
              <button
                key={t.id}
                onClick={() => openTicket(t.id)}
                data-testid={`admin-ticket-${t.id}`}
                className={`w-full text-left px-4 py-3 border-b border-white/5 hover:bg-white/[0.03] transition ${
                  active ? "bg-[#FF007F]/10 border-l-2 border-l-[#FF007F]" : ""
                }`}
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className="font-bold text-xs truncate">{t.subject}</span>
                  {isWaiting && (
                    <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm bg-[#FF007F]/20 text-[#FF007F] font-bold shrink-0">
                      New
                    </span>
                  )}
                </div>
                <div className="text-[11px] text-white/50 font-mono">@{t.username}</div>
                <div className="text-[10px] text-white/30 mt-0.5 font-mono">
                  {new Date(t.updated_at).toLocaleString()}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="bg-[#1a1525] border border-white/5 rounded-sm flex flex-col overflow-hidden">
        {!open ? (
          <div className="flex-1 flex items-center justify-center text-sm text-white/40">
            Pick a ticket on the left.
          </div>
        ) : (
          <>
            <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
              <div className="min-w-0">
                <div className="font-display font-bold text-sm truncate">{open.ticket.subject}</div>
                <div className="text-[10px] uppercase tracking-wider text-white/40">
                  @{open.ticket.username} · status: {open.ticket.status}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {open.ticket.status !== "closed" && (
                  <button
                    onClick={close}
                    data-testid="ticket-close"
                    className="text-[10px] uppercase tracking-wider px-3 py-1.5 border border-white/20 rounded-sm hover:bg-white/5"
                  >
                    Close
                  </button>
                )}
                <button
                  onClick={remove}
                  data-testid="ticket-delete"
                  className="text-[10px] uppercase tracking-wider px-3 py-1.5 border border-red-500/40 text-red-400 rounded-sm hover:bg-red-500/10 inline-flex items-center gap-1"
                >
                  <Trash2 className="w-3 h-3" /> Delete
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-[#0d0a14]">
              {open.messages.map((m) => {
                const isStaff = m.author_role === "staff";
                return (
                  <div key={m.id} className={`flex ${isStaff ? "justify-end" : "justify-start"}`}>
                    <div className="max-w-[78%]">
                      <div className={`text-[10px] uppercase tracking-wider mb-1 ${isStaff ? "text-[#00E5FF]" : "text-[#FF007F]"}`}>
                        {isStaff ? `Staff · ${m.author_name}` : `User · ${m.author_name}`}
                      </div>
                      <div
                        className={`px-3 py-2 rounded-sm text-sm whitespace-pre-wrap leading-snug ${
                          isStaff
                            ? "bg-[#00E5FF] text-[#050505] font-medium"
                            : "bg-[#1a1525] border border-white/10 text-white/90"
                        }`}
                      >
                        {m.message}
                      </div>
                      <div className="text-[10px] text-white/30 font-mono mt-1">
                        {new Date(m.created_at).toLocaleString()}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
            {open.ticket.status !== "closed" && (
              <form onSubmit={send} className="border-t border-white/5 p-3 bg-[#050505]">
                <div className="text-[10px] uppercase tracking-wider text-emerald-400/80 mb-1.5 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  Replying as <span className="text-white font-bold">{displayName || "Support"}</span>
                </div>
                <div className="flex gap-2">
                  <Input
                    data-testid="admin-ticket-reply-input"
                    placeholder={`Reply as "${displayName || "Support"}"…`}
                    value={reply}
                    onChange={(e) => setReply(e.target.value)}
                    className="bg-[#1a1525] border-white/10 flex-1"
                  />
                  <button
                    type="submit"
                    disabled={sending || !reply.trim()}
                    data-testid="admin-ticket-send"
                    className="px-4 gradient-pp rounded-sm font-bold disabled:opacity-40 inline-flex items-center"
                  >
                    {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                  </button>
                </div>
              </form>
            )}
          </>
        )}
      </div>
    </div>
  );
}


function ProvidersPanel({ token }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [syncing, setSyncing] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await adminApi(token).get("/admin/smm-providers");
      setItems(r.data.providers || []);
    } catch (e) {
      toast.error("Failed to load providers");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line
  }, []);

  const create = async (e) => {
    e.preventDefault();
    if (!name.trim() || !url.trim() || !key.trim()) return;
    setBusy(true);
    try {
      await adminApi(token).post("/admin/smm-providers", { name: name.trim(), api_url: url.trim(), api_key: key.trim() });
      toast.success(`Added ${name}`);
      setName(""); setUrl(""); setKey(""); setShowAdd(false);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    } finally {
      setBusy(false);
    }
  };

  const syncProvider = async (id, providerName) => {
    setSyncing(id);
    try {
      const r = await adminApi(token).post(`/admin/smm-providers/${id}/sync`);
      toast.success(`${providerName}: +${r.data.added} added · ${r.data.updated} updated`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Sync failed");
    } finally {
      setSyncing(null);
    }
  };

  const toggle = async (p) => {
    try {
      await adminApi(token).patch(`/admin/smm-providers/${p.id}`, { enabled: !p.enabled });
      load();
    } catch {
      toast.error("Failed");
    }
  };

  const remove = async (p) => {
    if (!window.confirm(`Delete provider "${p.name}"? Services using it must be reassigned first.`)) return;
    try {
      await adminApi(token).delete(`/admin/smm-providers/${p.id}`);
      toast.success("Deleted");
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-display font-black text-xl">SMM Providers</h2>
          <p className="text-xs text-white/40 mt-1">
            Add multiple panel APIs. Each service is bound to one provider — orders auto-route to the correct API.
          </p>
        </div>
        <button
          onClick={() => setShowAdd((v) => !v)}
          data-testid="provider-add-btn"
          className="px-4 py-2 gradient-pp rounded-sm font-bold text-xs uppercase tracking-wider inline-flex items-center gap-2"
        >
          <Plus className="w-4 h-4" /> Add provider
        </button>
      </div>

      {showAdd && (
        <form onSubmit={create} className="bg-[#1a1525] border border-[#FF007F]/40 rounded-sm p-5 space-y-3" data-testid="provider-add-form">
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <Label className="text-[11px] uppercase tracking-wider text-white/60">Display name</Label>
              <Input
                data-testid="provider-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. SmmCost"
                maxLength={60}
                className="bg-[#0d0a14] border-white/10 mt-1"
              />
            </div>
            <div>
              <Label className="text-[11px] uppercase tracking-wider text-white/60">API URL</Label>
              <Input
                data-testid="provider-url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://smmcost.com/api/v2"
                className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs"
              />
            </div>
          </div>
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">API key</Label>
            <Input
              data-testid="provider-key"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="Your panel API key"
              className="bg-[#0d0a14] border-white/10 mt-1 font-mono text-xs"
              autoComplete="off"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setShowAdd(false)}
              className="flex-1 py-2 border border-white/10 rounded-sm text-xs uppercase tracking-wider hover:bg-white/5"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              data-testid="provider-create"
              className="flex-1 py-2 gradient-pp rounded-sm text-xs uppercase tracking-wider font-bold disabled:opacity-50"
            >
              {busy ? <Loader2 className="w-3 h-3 animate-spin inline" /> : "Save & Add"}
            </button>
          </div>
        </form>
      )}

      <div className="bg-[#1a1525] border border-white/5 rounded-sm overflow-hidden">
        <table className="w-full text-sm" data-testid="providers-table">
          <thead className="text-[10px] uppercase tracking-[0.2em] text-white/40 bg-[#0d0a14]">
            <tr>
              <th className="text-left px-4 py-3">Name</th>
              <th className="text-left px-4 py-3">URL</th>
              <th className="text-left px-4 py-3">Key</th>
              <th className="text-center px-4 py-3">Enabled</th>
              <th className="text-right px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={5} className="text-center py-10 text-white/40">
                  <Loader2 className="w-5 h-5 animate-spin inline mr-2" /> Loading…
                </td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={5} className="text-center py-10 text-white/40 text-xs">
                  No providers yet. Click "Add provider" to register your first SMM panel API.
                </td>
              </tr>
            )}
            {items.map((p) => (
              <tr key={p.id} className="border-t border-white/5" data-testid={`provider-row-${p.id}`}>
                <td className="px-4 py-3 font-bold">{p.name}</td>
                <td className="px-4 py-3 font-mono text-xs text-white/60 truncate max-w-[280px]">{p.api_url}</td>
                <td className="px-4 py-3 font-mono text-xs text-white/40">{p.api_key_masked}</td>
                <td className="px-4 py-3 text-center">
                  <button
                    onClick={() => toggle(p)}
                    className={`px-2 py-1 rounded-sm text-[10px] uppercase tracking-wider font-bold ${
                      p.enabled ? "bg-[#00E5FF]/20 text-[#00E5FF]" : "bg-white/5 text-white/40"
                    }`}
                  >
                    {p.enabled ? "On" : "Off"}
                  </button>
                </td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  <button
                    onClick={() => syncProvider(p.id, p.name)}
                    disabled={syncing === p.id}
                    data-testid={`provider-sync-${p.id}`}
                    className="px-3 py-1 bg-[#00E5FF]/20 text-[#00E5FF] rounded-sm text-[10px] uppercase tracking-wider font-bold mr-2 hover:bg-[#00E5FF]/30 disabled:opacity-40 inline-flex items-center gap-1"
                  >
                    {syncing === p.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCw className="w-3 h-3" />}
                    Sync
                  </button>
                  <button
                    onClick={() => remove(p)}
                    data-testid={`provider-delete-${p.id}`}
                    className="px-3 py-1 bg-red-500/20 text-red-300 rounded-sm text-[10px] uppercase tracking-wider font-bold hover:bg-red-500/30"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


function ChatBansButton({ token }) {
  const [open, setOpen] = useState(false);
  const [bans, setBans] = useState([]);

  const load = async () => {
    try {
      const r = await adminApi(token).get("/ai/admin/chat-bans");
      setBans(r.data.bans || []);
    } catch {}
  };

  useEffect(() => {
    if (open) load();
    // eslint-disable-next-line
  }, [open]);

  const unban = async (ident) => {
    if (!window.confirm(`Unban "${ident}"?`)) return;
    try {
      await adminApi(token).post("/ai/admin/chat-bans/unban", { identifier: ident });
      toast.success(`Unbanned ${ident}`);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    }
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        data-testid="inbox-bans"
        className="px-3 py-2 text-[10px] uppercase tracking-wider border border-amber-500/40 text-amber-300 rounded-sm hover:bg-amber-500/10 inline-flex items-center gap-2"
      >
        Banned users
        {bans.length > 0 && (
          <span className="px-1.5 py-0.5 rounded-full bg-amber-500 text-black text-[9px] font-bold">
            {bans.length}
          </span>
        )}
      </button>
      {open && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
          onClick={() => setOpen(false)}
          data-testid="bans-modal"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="bg-[#1a1525] border border-white/10 rounded-sm max-w-2xl w-full max-h-[80vh] overflow-hidden flex flex-col"
          >
            <div className="px-5 py-3 border-b border-white/10 flex items-center justify-between">
              <h3 className="font-bold text-sm">Chat bans ({bans.length})</h3>
              <button onClick={() => setOpen(false)} className="text-white/50 hover:text-white text-xs">
                ✕
              </button>
            </div>
            <div className="overflow-y-auto flex-1">
              {bans.length === 0 ? (
                <div className="text-center py-12 text-xs text-white/40">No banned users.</div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="text-[10px] uppercase tracking-wider text-white/40 bg-[#0d0a14]">
                    <tr>
                      <th className="text-left px-4 py-2">Identifier</th>
                      <th className="text-left px-4 py-2">IP</th>
                      <th className="text-left px-4 py-2">Banned at</th>
                      <th className="text-right px-4 py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {bans.map((b) => (
                      <tr key={b.identifier} className="border-t border-white/5">
                        <td className="px-4 py-2 font-mono text-xs">{b.identifier}</td>
                        <td className="px-4 py-2 font-mono text-[10px] text-white/50">{b.ip || "—"}</td>
                        <td className="px-4 py-2 font-mono text-[10px] text-white/50">
                          {b.banned_at ? new Date(b.banned_at).toLocaleString() : ""}
                        </td>
                        <td className="px-4 py-2 text-right">
                          <button
                            onClick={() => unban(b.identifier)}
                            data-testid={`unban-${b.identifier}`}
                            className="px-3 py-1 bg-emerald-500/20 text-emerald-300 rounded-sm text-[10px] uppercase tracking-wider font-bold hover:bg-emerald-500/30"
                          >
                            Unban
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

const STAFF_PERMS_OPTIONS = ["tickets", "ai_inbox", "orders", "discord", "withdrawals"];

function StaffPanel({ token }) {
  const [items, setItems] = useState([]);
  const [showAdd, setShowAdd] = useState(false);
  const [uname, setUname] = useState("");
  const [pw, setPw] = useState("");
  const [selectedPerms, setSelectedPerms] = useState([...STAFF_PERMS_OPTIONS]);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const r = await adminApi(token).get("/admin/staff");
      setItems(r.data.staff || []);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Owner only");
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line
  }, []);

  const create = async (e) => {
    e.preventDefault();
    if (uname.trim().length < 3 || pw.length < 8) {
      toast.error("Username (3+) and password (8+) required");
      return;
    }
    setBusy(true);
    try {
      await adminApi(token).post("/admin/staff", {
        username: uname.trim(),
        password: pw,
        perms: selectedPerms,
      });
      toast.success(`Staff "${uname}" created`);
      setUname("");
      setPw("");
      setShowAdd(false);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    } finally {
      setBusy(false);
    }
  };

  const togglePerm = (p) => {
    setSelectedPerms((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]));
  };

  const remove = async (id, uname) => {
    if (!window.confirm(`Delete staff "${uname}"? They will be logged out immediately.`)) return;
    try {
      await adminApi(token).delete(`/admin/staff/${id}`);
      toast.success("Staff deleted");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed");
    }
  };

  const toggleActive = async (s) => {
    try {
      await adminApi(token).patch(`/admin/staff/${s.id}`, { active: !s.active });
      load();
    } catch {
      toast.error("Failed");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-display font-black text-xl">Team / Staff Agents</h2>
          <p className="text-xs text-white/40 mt-1">
            Create scoped accounts for your support team. Staff cannot create other accounts or change settings.
          </p>
        </div>
        <button
          onClick={() => setShowAdd((v) => !v)}
          data-testid="staff-add-btn"
          className="px-4 py-2 gradient-pp rounded-sm font-bold text-xs uppercase tracking-wider inline-flex items-center gap-2"
        >
          <Plus className="w-4 h-4" /> Add staff
        </button>
      </div>

      {showAdd && (
        <form
          onSubmit={create}
          data-testid="staff-add-form"
          className="bg-[#1a1525] border border-[#FF007F]/40 rounded-sm p-5 space-y-3"
        >
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <Label className="text-[11px] uppercase tracking-wider text-white/60">Username</Label>
              <Input
                data-testid="staff-username"
                value={uname}
                onChange={(e) => setUname(e.target.value)}
                placeholder="e.g. agent1"
                className="bg-[#0d0a14] border-white/10 mt-1 font-mono"
              />
            </div>
            <div>
              <Label className="text-[11px] uppercase tracking-wider text-white/60">Password</Label>
              <Input
                data-testid="staff-password"
                type="password"
                value={pw}
                onChange={(e) => setPw(e.target.value)}
                placeholder="min 8 chars"
                className="bg-[#0d0a14] border-white/10 mt-1 font-mono"
              />
            </div>
          </div>
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">Permissions</Label>
            <div className="flex flex-wrap gap-2 mt-1">
              {STAFF_PERMS_OPTIONS.map((p) => (
                <button
                  type="button"
                  key={p}
                  data-testid={`perm-${p}`}
                  onClick={() => togglePerm(p)}
                  className={`px-3 py-1 rounded-sm text-[11px] uppercase tracking-wider font-bold ${
                    selectedPerms.includes(p)
                      ? "bg-[#00E5FF]/20 text-[#00E5FF]"
                      : "bg-white/5 text-white/40 border border-white/10"
                  }`}
                >
                  {p.replace("_", " ")}
                </button>
              ))}
            </div>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setShowAdd(false)}
              className="flex-1 py-2 border border-white/10 rounded-sm text-xs uppercase tracking-wider"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              data-testid="staff-create-submit"
              className="flex-1 py-2 gradient-pp rounded-sm text-xs uppercase tracking-wider font-bold disabled:opacity-50"
            >
              {busy ? <Loader2 className="w-3 h-3 animate-spin inline" /> : "Create staff"}
            </button>
          </div>
        </form>
      )}

      <div className="bg-[#1a1525] border border-white/5 rounded-sm overflow-hidden">
        <table className="w-full text-sm" data-testid="staff-table">
          <thead className="text-[10px] uppercase tracking-[0.2em] text-white/40 bg-[#0d0a14]">
            <tr>
              <th className="text-left px-4 py-3">Username</th>
              <th className="text-left px-4 py-3">Permissions</th>
              <th className="text-center px-4 py-3">Active</th>
              <th className="text-right px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr>
                <td colSpan={4} className="text-center py-10 text-xs text-white/40">
                  No staff yet. Click "Add staff" to create the first one.
                </td>
              </tr>
            )}
            {items.map((s) => (
              <tr key={s.id} className="border-t border-white/5" data-testid={`staff-row-${s.username}`}>
                <td className="px-4 py-3 font-bold">@{s.username}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {(s.perms || []).map((p) => (
                      <span key={p} className="px-1.5 py-0.5 bg-[#00E5FF]/15 text-[#00E5FF] rounded-sm text-[9px] uppercase tracking-wider font-bold">
                        {p.replace("_", " ")}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3 text-center">
                  <button
                    onClick={() => toggleActive(s)}
                    className={`px-2 py-1 rounded-sm text-[10px] uppercase tracking-wider font-bold ${
                      s.active ? "bg-emerald-500/20 text-emerald-300" : "bg-white/5 text-white/40"
                    }`}
                  >
                    {s.active ? "On" : "Off"}
                  </button>
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={() => remove(s.id, s.username)}
                    data-testid={`staff-delete-${s.username}`}
                    className="px-3 py-1 bg-red-500/20 text-red-300 rounded-sm text-[10px] uppercase tracking-wider font-bold hover:bg-red-500/30"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

