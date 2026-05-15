import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import AIWidget from "@/components/AIWidget";
import {
  Sparkles,
  LogOut,
  Wallet,
  Users,
  ShoppingBag,
  UserCheck,
  Send,
  Crown,
  Shield,
  Loader2,
  Bot,
  LayoutDashboard,
  CreditCard,
  LifeBuoy,
  Plus,
  ExternalLink,
  CheckCircle2,
  XCircle,
  Clock,
} from "lucide-react";
import { toast } from "sonner";

const POLL_MS = 3000;

export default function ClientDashboard() {
  const { user, loading, logout, authedApi } = useAuth();
  const nav = useNavigate();
  const [stats, setStats] = useState(null);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [view, setView] = useState("home"); // home | funds | tickets
  const [balance, setBalance] = useState(0);
  const chatEndRef = useRef(null);

  const loadBalance = async () => {
    try {
      const r = await authedApi().get("/client/balance");
      setBalance(r.data.balance || 0);
    } catch {}
  };

  useEffect(() => {
    if (!loading && !user) nav("/client");
  }, [loading, user, nav]);

  const loadStats = async () => {
    try {
      const r = await authedApi().get("/client/dashboard");
      setStats(r.data);
    } catch {}
  };

  const loadMessages = async () => {
    try {
      const r = await authedApi().get("/chat/messages");
      setMessages(r.data.messages || []);
    } catch {}
  };

  useEffect(() => {
    if (!user) return;
    loadStats();
    loadMessages();
    loadBalance();
    const statInt = setInterval(loadStats, 12000);
    const msgInt = setInterval(loadMessages, POLL_MS);
    const balInt = setInterval(loadBalance, 15000);
    return () => {
      clearInterval(statInt);
      clearInterval(msgInt);
      clearInterval(balInt);
    };
    // eslint-disable-next-line
  }, [user]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  const send = async (e) => {
    e?.preventDefault();
    const t = text.trim();
    if (!t) return;
    setSending(true);
    try {
      await authedApi().post("/chat/send", { text: t });
      setText("");
      await loadMessages();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Send failed");
    } finally {
      setSending(false);
    }
  };

  if (loading || !user) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-white/40" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#050505] text-white">
      <header className="border-b border-white/5 bg-[#0d0a14]/90 backdrop-blur sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 md:px-10 h-14 md:h-16 flex items-center justify-between gap-3">
          <Link to="/" className="flex items-center gap-2" data-testid="brand-logo">
            <div className="w-7 h-7 rounded-sm gradient-pp flex items-center justify-center">
              <Sparkles className="w-3.5 h-3.5" strokeWidth={2.5} />
            </div>
            <span className="font-display font-black text-base">
              Better<span className="text-[#FF007F]">Social</span>
            </span>
            <span className="ml-2 text-[10px] uppercase tracking-[0.2em] text-white/40 hidden md:inline">
              Client Area
            </span>
          </Link>
          <div className="flex items-center gap-3">
            <RoleBadge role={user.role} />
            <span className="text-sm text-white/80 hidden sm:inline" data-testid="client-username">
              @{user.username}
            </span>
            <button
              onClick={() => {
                logout();
                nav("/");
              }}
              data-testid="client-logout"
              className="inline-flex items-center gap-1 px-3 py-1.5 border border-white/10 rounded-sm text-[11px] uppercase tracking-wider hover:bg-white/5"
            >
              <LogOut className="w-3 h-3" /> Logout
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 md:px-10 py-6 md:py-10">
        <div className="grid lg:grid-cols-[220px_1fr] gap-6">
          {/* SIDEBAR */}
          <aside
            data-testid="dashboard-sidebar"
            className="bg-[#0d0a14] border border-white/5 rounded-sm p-2 h-fit lg:sticky lg:top-20"
          >
            <SideLink
              icon={LayoutDashboard}
              label="Dashboard"
              active={view === "home"}
              onClick={() => setView("home")}
              testId="nav-home"
            />
            <SideLink
              icon={CreditCard}
              label="Add Funds"
              active={view === "funds"}
              onClick={() => setView("funds")}
              testId="nav-funds"
              badge={`$${balance.toFixed(2)}`}
            />
            <SideLink
              icon={LifeBuoy}
              label="Tickets"
              active={view === "tickets"}
              onClick={() => setView("tickets")}
              testId="nav-tickets"
            />
            <Link
              to="/"
              className="flex items-center gap-3 px-3 py-2.5 rounded-sm text-sm text-white/60 hover:text-white hover:bg-white/5 transition"
              data-testid="nav-catalog"
            >
              <ShoppingBag className="w-4 h-4" />
              <span>Service Catalog</span>
              <ExternalLink className="w-3 h-3 ml-auto opacity-50" />
            </Link>
            <button
              onClick={() => {
                logout();
                nav("/");
              }}
              data-testid="nav-logout"
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-sm text-sm text-white/60 hover:text-[#FF3B30] hover:bg-white/5 transition"
            >
              <LogOut className="w-4 h-4" />
              Logout
            </button>
          </aside>

          {/* MAIN CONTENT */}
          <div>
            {view === "home" && (
              <HomeView
                user={user}
                stats={stats}
                messages={messages}
                send={send}
                sending={sending}
                text={text}
                setText={setText}
                chatEndRef={chatEndRef}
              />
            )}
            {view === "funds" && (
              <FundsView authedApi={authedApi} balance={balance} reloadBalance={loadBalance} />
            )}
            {view === "tickets" && <TicketsView authedApi={authedApi} />}
          </div>
        </div>
      </main>

      {/* Better Social AI floating widget */}
      <AIWidget open={aiOpen} onOpenChange={setAiOpen} />
      {!aiOpen && (
        <button
          onClick={() => setAiOpen(true)}
          data-testid="dashboard-ai-fab"
          aria-label="Open AI assistant"
          className="fixed bottom-5 right-5 z-50 group flex items-center gap-3"
        >
          <span className="hidden sm:inline-block px-3 py-1.5 rounded-full bg-[#1a1525]/95 backdrop-blur border border-white/10 text-xs font-medium text-white shadow-lg group-hover:border-[#FF007F]/50 transition">
            Live Chat?
          </span>
          <div className="relative">
            <span className="absolute inset-0 rounded-full gradient-pp blur-lg opacity-70 group-hover:opacity-100 transition animate-pulse" />
            <div className="relative w-14 h-14 rounded-full gradient-pp flex items-center justify-center shadow-[0_10px_40px_-12px_rgba(255,0,127,0.8)] group-hover:scale-105 transition">
              <Bot className="w-6 h-6 text-white" />
            </div>
            <span className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 rounded-full bg-[#00E5FF] border-2 border-[#050505] animate-pulse" />
          </div>
        </button>
      )}
    </div>
  );
}

function StatBox({ icon: Icon, label, value, color, testId }) {
  return (
    <div
      data-testid={testId}
      className="relative overflow-hidden p-4 md:p-5 rounded-sm bg-[#0d0a14] border border-white/5"
    >
      <div className="absolute -top-10 -right-10 w-28 h-28 rounded-full blur-3xl opacity-40" style={{ background: color }} />
      <Icon className="w-5 h-5 mb-3" style={{ color }} />
      <div className="font-display font-black text-2xl md:text-3xl text-white">{value}</div>
      <div className="text-[10px] uppercase tracking-[0.2em] text-white/50 mt-0.5">{label}</div>
    </div>
  );
}

function RoleBadge({ role }) {
  if (role === "owner")
    return (
      <span className="inline-flex items-center gap-1 px-2 py-1 bg-[#FFB800]/15 border border-[#FFB800]/40 text-[#FFB800] text-[10px] uppercase tracking-wider rounded-sm font-bold">
        <Crown className="w-3 h-3" /> Owner
      </span>
    );
  if (role === "moderator")
    return (
      <span className="inline-flex items-center gap-1 px-2 py-1 bg-[#00E5FF]/15 border border-[#00E5FF]/40 text-[#00E5FF] text-[10px] uppercase tracking-wider rounded-sm font-bold">
        <Shield className="w-3 h-3" /> Mod
      </span>
    );
  return null;
}

function Msg({ m }) {
  const d = new Date(m.created_at);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const date = d.toLocaleDateString();
  const isSystem = m.role === "system";

  if (isSystem) {
    return (
      <div className="text-center py-1 px-2 text-[10px] uppercase tracking-wider text-white/40 italic">
        — {m.text} · {time} —
      </div>
    );
  }
  const nameColor =
    m.role === "owner" ? "text-[#FFB800]" : m.role === "moderator" ? "text-[#00E5FF]" : "text-[#FF007F]";
  return (
    <div className="flex flex-col group">
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className={`text-xs font-bold ${nameColor}`} data-testid="msg-username">
          @{m.username_display}
        </span>
        {m.role === "owner" && <Crown className="w-3 h-3 text-[#FFB800]" />}
        {m.role === "moderator" && <Shield className="w-3 h-3 text-[#00E5FF]" />}
        <span className="text-[10px] text-white/30 font-mono">
          {date} · {time}
        </span>
      </div>
      <div className="text-sm text-white/90 break-words leading-snug">{m.text}</div>
    </div>
  );
}

function SideLink({ icon: Icon, label, active, onClick, testId, badge }) {
  return (
    <button
      onClick={onClick}
      data-testid={testId}
      className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-sm text-sm transition ${
        active
          ? "bg-[#FF007F]/15 text-white border-l-2 border-[#FF007F]"
          : "text-white/60 hover:text-white hover:bg-white/5"
      }`}
    >
      <Icon className="w-4 h-4" />
      <span className="flex-1 text-left">{label}</span>
      {badge != null && (
        <span className="text-[10px] font-mono text-white/40">{badge}</span>
      )}
    </button>
  );
}

function HomeView({ user, stats, messages, send, sending, text, setText, chatEndRef }) {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl md:text-4xl font-black tracking-tight">
          Hey <span className="gradient-text">{user.username}</span>.
        </h1>
        <p className="text-white/50 text-sm mt-1">Your overview and the community lobby.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4">
        <StatBox icon={Wallet} label="Balance" value={stats ? `$${Number(stats.balance).toFixed(2)}` : "—"} color="#FF007F" testId="stat-balance" />
        <StatBox icon={Users} label="Online" value={stats ? stats.online_users : "—"} color="#00E5FF" testId="stat-online" />
        <StatBox icon={ShoppingBag} label="Orders" value={stats ? stats.total_orders : "—"} color="#7000FF" testId="stat-orders" />
        <StatBox icon={UserCheck} label="Users" value={stats ? stats.registered_users : "—"} color="#FFB800" testId="stat-registered" />
      </div>

      <div
        data-testid="community-chat"
        className="bg-[#0d0a14] border border-white/5 rounded-sm flex flex-col h-[420px] md:h-[520px]"
      >
        <div className="px-4 md:px-5 py-3 border-b border-white/5 flex items-center justify-between">
          <div>
            <h2 className="font-display font-bold">Community Chat</h2>
            <p className="text-[10px] uppercase tracking-wider text-white/40">Be kind · be useful</p>
          </div>
          <div className="text-[10px] uppercase tracking-wider text-[#00E5FF]">LIVE</div>
        </div>
        <div className="flex-1 overflow-y-auto px-3 md:px-4 py-3 space-y-2" data-testid="chat-messages">
          {messages.length === 0 && (
            <div className="text-center text-white/30 text-xs py-10">No messages yet — say hi!</div>
          )}
          {messages.map((m) => <Msg key={m.id} m={m} />)}
          <div ref={chatEndRef} />
        </div>
        <form onSubmit={send} className="border-t border-white/5 p-3 flex gap-2">
          <Input
            data-testid="chat-input"
            placeholder="Say something…"
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, 500))}
            maxLength={500}
            className="bg-[#1a1525] border-white/10"
          />
          <button
            type="submit"
            disabled={sending || !text.trim()}
            data-testid="chat-send"
            className="px-4 gradient-pp rounded-sm font-bold disabled:opacity-40 inline-flex items-center"
          >
            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </form>
      </div>
    </div>
  );
}

function FundsView({ authedApi, balance, reloadBalance }) {
  const [amount, setAmount] = useState(10);
  const [paypal, setPaypal] = useState({ paypal_email: "", paypal_me_url: "", configured: false });
  const [txns, setTxns] = useState([]);
  const [creating, setCreating] = useState(false);

  const loadConfig = async () => {
    try {
      const r = await api.get("/paypal-config");
      setPaypal(r.data);
    } catch {}
  };

  const loadTxns = async () => {
    try {
      const r = await authedApi().get("/client/transactions");
      setTxns(r.data.transactions || []);
    } catch {}
  };

  useEffect(() => {
    loadConfig();
    loadTxns();
    // eslint-disable-next-line
  }, []);

  const openPaypal = () => {
    if (!paypal.paypal_me_url) {
      toast.error("PayPal not configured yet — please use crypto or contact support.");
      return;
    }
    const a = Number(amount) || 0;
    if (a < 1) {
      toast.error("Min $1");
      return;
    }
    // paypal.me/USER/AMOUNT opens with prefilled amount
    const url = paypal.paypal_me_url.replace(/\/$/, "") + `/${a}`;
    window.open(url, "_blank");
  };

  const submitRequest = async () => {
    const a = Number(amount) || 0;
    if (a < 1) {
      toast.error("Min $1");
      return;
    }
    setCreating(true);
    try {
      await authedApi().post("/client/funds/request", { amount: a, method: "paypal" });
      toast.success("Submitted — staff will credit your account after verifying payment.");
      setAmount(10);
      loadTxns();
      reloadBalance();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl md:text-4xl font-black tracking-tight">Add Funds</h1>
        <p className="text-white/50 text-sm mt-1">
          Top up your account balance — use it for any service in the catalog.
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="bg-[#0d0a14] border border-white/5 rounded-sm p-5">
          <div className="text-[10px] uppercase tracking-[0.2em] text-white/40">Current balance</div>
          <div className="font-display font-black text-3xl md:text-4xl text-[#FF007F] mt-2" data-testid="funds-balance">
            ${balance.toFixed(2)}
          </div>
        </div>
        <div className="bg-[#0d0a14] border border-white/5 rounded-sm p-5">
          <div className="text-[10px] uppercase tracking-[0.2em] text-white/40">Payment method</div>
          <div className="font-display font-bold text-lg mt-2 flex items-center gap-2">
            <img alt="PayPal" src="https://www.paypalobjects.com/webstatic/icon/pp32.png" className="w-5 h-5" />
            PayPal
          </div>
          <div className="text-[11px] text-white/40 mt-1">
            {paypal.configured ? "Manual approval after payment" : "Not configured — contact support"}
          </div>
        </div>
      </div>

      <div className="bg-[#0d0a14] border border-white/5 rounded-sm p-5 md:p-6">
        <h2 className="font-display font-bold text-lg mb-1">Top up via PayPal</h2>
        <p className="text-xs text-white/50 mb-4">
          1) Enter an amount → 2) Pay via PayPal → 3) Click "I've Paid" → 4) We credit your account after verification (usually &lt; 30 min).
        </p>
        <div className="flex items-end gap-2 mb-4">
          <div className="flex-1">
            <Label className="text-[11px] uppercase tracking-wider text-white/60">Amount (USD)</Label>
            <Input
              data-testid="funds-amount"
              type="number"
              min="1"
              step="1"
              max="10000"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="bg-[#1a1525] border-white/10 mt-1"
            />
          </div>
          {[5, 10, 25, 50, 100].map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => setAmount(q)}
              data-testid={`quick-amount-${q}`}
              className="px-3 py-2 border border-white/10 rounded-sm text-xs hover:bg-white/5"
            >
              ${q}
            </button>
          ))}
        </div>
        <div className="flex flex-col sm:flex-row gap-2">
          <button
            onClick={openPaypal}
            disabled={!paypal.configured}
            data-testid="open-paypal"
            className="flex-1 py-3 gradient-pp rounded-sm font-bold text-sm inline-flex items-center justify-center gap-2 disabled:opacity-40"
          >
            <ExternalLink className="w-4 h-4" />
            Pay ${Number(amount) || 0} on PayPal
          </button>
          <button
            onClick={submitRequest}
            disabled={creating || !paypal.configured}
            data-testid="confirm-paid"
            className="flex-1 py-3 border border-[#00E5FF]/40 text-[#00E5FF] rounded-sm font-bold text-sm inline-flex items-center justify-center gap-2 hover:bg-[#00E5FF]/5 disabled:opacity-40"
          >
            {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
            I've Paid — Submit for Approval
          </button>
        </div>
      </div>

      <div className="bg-[#0d0a14] border border-white/5 rounded-sm overflow-hidden">
        <div className="px-4 md:px-6 py-3 border-b border-white/5 flex items-center justify-between">
          <h3 className="font-display font-bold text-sm">Recent transactions</h3>
          <span className="text-[10px] uppercase tracking-wider text-white/40">{txns.length}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-[10px] uppercase tracking-wider text-white/40">
              <tr>
                <th className="text-left px-6 py-2">Date</th>
                <th className="text-left px-6 py-2">Amount</th>
                <th className="text-left px-6 py-2">Method</th>
                <th className="text-left px-6 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {txns.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-6 py-10 text-center text-white/30 text-xs">
                    No transactions yet.
                  </td>
                </tr>
              )}
              {txns.map((t) => (
                <tr key={t.id} className="border-t border-white/5" data-testid={`tx-row-${t.id}`}>
                  <td className="px-6 py-2 text-white/60 text-xs font-mono">
                    {new Date(t.created_at).toLocaleString()}
                  </td>
                  <td className="px-6 py-2 font-mono text-[#FF007F]">${Number(t.amount).toFixed(2)}</td>
                  <td className="px-6 py-2 text-white/60 text-xs uppercase">{t.method}</td>
                  <td className="px-6 py-2">
                    {t.status === "approved" && (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-sm bg-emerald-500/15 text-emerald-400 font-bold">
                        <CheckCircle2 className="w-3 h-3" /> approved
                      </span>
                    )}
                    {t.status === "pending" && (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-sm bg-amber-500/15 text-amber-400 font-bold">
                        <Clock className="w-3 h-3" /> pending
                      </span>
                    )}
                    {t.status === "rejected" && (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-sm bg-red-500/15 text-red-400 font-bold">
                        <XCircle className="w-3 h-3" /> rejected
                      </span>
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

function TicketsView({ authedApi }) {
  const [tickets, setTickets] = useState([]);
  const [open, setOpen] = useState(null); // ticket with messages
  const [creating, setCreating] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);

  const load = async () => {
    try {
      const r = await authedApi().get("/client/tickets");
      setTickets(r.data.tickets || []);
    } catch {}
  };

  const openTicket = async (id) => {
    try {
      const r = await authedApi().get(`/client/tickets/${id}`);
      setOpen(r.data);
    } catch {
      toast.error("Failed to load ticket");
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 12000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, []);

  useEffect(() => {
    if (!open) return;
    const t = setInterval(() => openTicket(open.ticket.id), 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [open?.ticket?.id]);

  const create = async (e) => {
    e.preventDefault();
    if (!subject.trim() || !message.trim()) return;
    setCreating(true);
    try {
      const r = await authedApi().post("/client/tickets", { subject, message });
      toast.success("Ticket opened");
      setSubject("");
      setMessage("");
      setShowNew(false);
      await load();
      await openTicket(r.data.id);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    } finally {
      setCreating(false);
    }
  };

  const replyToTicket = async (e) => {
    e.preventDefault();
    const r = reply.trim();
    if (!r || !open) return;
    setSending(true);
    try {
      await authedApi().post(`/client/tickets/${open.ticket.id}/reply`, { message: r });
      setReply("");
      await openTicket(open.ticket.id);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    } finally {
      setSending(false);
    }
  };

  if (open) {
    return (
      <div className="space-y-4">
        <button
          onClick={() => setOpen(null)}
          data-testid="ticket-back"
          className="text-xs uppercase tracking-wider text-white/60 hover:text-white"
        >
          ← Back to tickets
        </button>
        <div className="bg-[#0d0a14] border border-white/5 rounded-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-white/5">
            <h2 className="font-display font-bold text-lg">{open.ticket.subject}</h2>
            <div className="text-[10px] uppercase tracking-wider text-white/40 mt-1">
              {open.ticket.status} · opened {new Date(open.ticket.created_at).toLocaleDateString()}
            </div>
          </div>
          <div className="p-5 space-y-4 max-h-[60vh] overflow-y-auto">
            {open.messages.map((m) => {
              const isStaff = m.author_role === "staff";
              return (
                <div key={m.id} className={`flex ${isStaff ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[80%] ${isStaff ? "items-end" : "items-start"}`}>
                    <div className={`text-[10px] uppercase tracking-wider mb-1 ${isStaff ? "text-[#00E5FF]" : "text-[#FF007F]"}`}>
                      {isStaff ? "Staff" : "You"} · {m.author_name}
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
            <form onSubmit={replyToTicket} className="border-t border-white/5 p-3 flex gap-2">
              <Input
                data-testid="ticket-reply-input"
                placeholder="Your reply…"
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                className="bg-[#1a1525] border-white/10"
              />
              <button
                type="submit"
                disabled={sending || !reply.trim()}
                data-testid="ticket-reply-send"
                className="px-4 gradient-pp rounded-sm font-bold disabled:opacity-40 inline-flex items-center"
              >
                {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </button>
            </form>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl md:text-4xl font-black tracking-tight">Support Tickets</h1>
          <p className="text-white/50 text-sm mt-1">Open a ticket for refunds, slow orders, anything else.</p>
        </div>
        <button
          onClick={() => setShowNew((v) => !v)}
          data-testid="new-ticket-btn"
          className="px-4 py-2 gradient-pp rounded-sm font-bold text-sm inline-flex items-center gap-2"
        >
          <Plus className="w-4 h-4" /> New ticket
        </button>
      </div>

      {showNew && (
        <form onSubmit={create} data-testid="new-ticket-form" className="bg-[#0d0a14] border border-white/5 rounded-sm p-5 space-y-3">
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">Subject</Label>
            <Input
              data-testid="ticket-subject"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              required
              maxLength={120}
              className="bg-[#1a1525] border-white/10 mt-1"
            />
          </div>
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">Message</Label>
            <textarea
              data-testid="ticket-message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              required
              rows={4}
              maxLength={4000}
              className="w-full bg-[#1a1525] border border-white/10 rounded-sm px-3 py-2 text-sm mt-1 outline-none focus:border-[#FF007F] text-white"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setShowNew(false)}
              data-testid="ticket-cancel"
              className="flex-1 py-2 border border-white/10 rounded-sm text-xs uppercase tracking-wider hover:bg-white/5"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={creating}
              data-testid="ticket-submit"
              className="flex-1 py-2 gradient-pp rounded-sm text-xs uppercase tracking-wider font-bold disabled:opacity-50 inline-flex items-center justify-center gap-2"
            >
              {creating ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
              Open Ticket
            </button>
          </div>
        </form>
      )}

      <div className="bg-[#0d0a14] border border-white/5 rounded-sm overflow-hidden">
        {tickets.length === 0 && (
          <div className="px-6 py-12 text-center text-white/30 text-xs">No tickets yet.</div>
        )}
        {tickets.map((t) => (
          <button
            key={t.id}
            onClick={() => openTicket(t.id)}
            data-testid={`ticket-row-${t.id}`}
            className="w-full text-left px-5 py-4 border-b border-white/5 last:border-b-0 hover:bg-white/[0.02] transition flex items-center justify-between gap-3"
          >
            <div className="min-w-0">
              <div className="font-bold text-sm truncate">{t.subject}</div>
              <div className="text-[10px] text-white/40 font-mono mt-0.5">
                {new Date(t.updated_at).toLocaleString()}
              </div>
            </div>
            <StatusPill status={t.status} />
          </button>
        ))}
      </div>
    </div>
  );
}

function StatusPill({ status }) {
  const map = {
    open: { bg: "bg-amber-500/15", color: "text-amber-400", label: "open" },
    answered: { bg: "bg-emerald-500/15", color: "text-emerald-400", label: "answered" },
    closed: { bg: "bg-white/5", color: "text-white/40", label: "closed" },
  };
  const m = map[status] || map.open;
  return (
    <span className={`text-[10px] uppercase tracking-wider px-2 py-1 rounded-sm font-bold ${m.bg} ${m.color}`}>
      {m.label}
    </span>
  );
}

