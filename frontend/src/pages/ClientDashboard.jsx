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
  Ticket,
  Search,
  Zap,
  Dices,
  ArrowUpRight,
  Calendar,
  MessageSquare,
  Bell,
  Menu,
  FileText,
} from "lucide-react";
import SlotsView from "./SlotsView";
import MessagesView from "./MessagesView";
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
  const [view, setView] = useState("home"); // home | funds | tickets | buy | redeem | slots | withdraw | tos | messages
  const [viewLoading, setViewLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false); // mobile drawer
  const [balance, setBalance] = useState(0);
  const [withdrawable, setWithdrawable] = useState(0);
  const [unreadTickets, setUnreadTickets] = useState(0);
  const [unreadDms, setUnreadDms] = useState(0);
  const chatEndRef = useRef(null);

  // Smooth-preloader when switching tabs (short delay for perceived polish, no full-page reload)
  const changeView = (v) => {
    if (v === view) {
      setSidebarOpen(false);
      return;
    }
    setViewLoading(true);
    setSidebarOpen(false);
    setTimeout(() => {
      setView(v);
      setTimeout(() => setViewLoading(false), 150);
    }, 220);
  };

  const loadBalance = async () => {
    try {
      const r = await authedApi().get("/client/balance");
      setBalance(r.data.balance || 0);
      setWithdrawable(r.data.withdrawable || 0);
    } catch {}
  };

  const loadUnreadTickets = async () => {
    try {
      const r = await authedApi().get("/client/tickets-unread-count");
      setUnreadTickets(r.data.unread || 0);
    } catch {}
  };

  const loadUnreadDms = async () => {
    try {
      const r = await authedApi().get("/messages/unread-count");
      setUnreadDms(r.data.unread || 0);
    } catch {}
  };

  useEffect(() => {
    if (user) {
      loadUnreadTickets();
      loadUnreadDms();
      const t1 = setInterval(loadUnreadTickets, 15000);
      const t2 = setInterval(loadUnreadDms, 10000);
      return () => { clearInterval(t1); clearInterval(t2); };
    }
    // eslint-disable-next-line
  }, [user]);

  // Clear badge instantly when user opens the Tickets view
  useEffect(() => {
    if (view === "tickets") {
      // Give the TicketsView a beat to load, then reload count
      const t = setTimeout(loadUnreadTickets, 1500);
      return () => clearTimeout(t);
    }
    // eslint-disable-next-line
  }, [view]);

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

  // Selly return handler — show toast and jump to Funds view
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("selly_funds") === "1") {
      toast.success("Payment received — your balance will update once Selly confirms (usually within a minute).", { duration: 8000 });
      setView("funds");
      // Strip query so reload doesn't replay
      window.history.replaceState({}, "", "/client/dashboard");
      // Force-refresh balance soon after
      const t1 = setTimeout(() => loadBalance(), 4000);
      const t2 = setTimeout(() => loadBalance(), 15000);
      return () => { clearTimeout(t1); clearTimeout(t2); };
    }
    // NOWPayments return handler — /client/dashboard?nowpay=1&tx=<id>
    // Auto-jumps to Funds view and triggers the manual verify so we credit even
    // if the IPN webhook was blocked/delayed.
    if (params.get("nowpay") === "1" && params.get("tx")) {
      const txId = params.get("tx");
      toast.info("Checking your NOWPayments deposit…", { duration: 4000 });
      setView("funds");
      (async () => {
        try {
          const r = await authedApi().post(`/client/funds/nowpayments-verify/${txId}`);
          if (r.data?.credited) {
            toast.success(`✅ Deposit credited! +$${r.data.amount} (+ $${r.data.bonus} bonus)`);
            loadBalance();
          } else if (r.data?.already_credited) {
            toast.info("Already credited — balance refreshed.");
            loadBalance();
          } else {
            toast.info(`Payment status: ${r.data?.status || "pending"} — we'll keep checking. You can also click 'Verify deposit' below.`, { duration: 8000 });
          }
        } catch (e) {
          toast.info("Payment not confirmed yet — click 'Verify deposit' below in a minute.");
        }
      })();
      window.history.replaceState({}, "", "/client/dashboard");
    }
    if (params.get("nowpay") === "cancel") {
      toast.info("Deposit cancelled. You can start a new one anytime.");
      window.history.replaceState({}, "", "/client/dashboard");
    }
    // eslint-disable-next-line
  }, []);

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
    <div className="min-h-screen bg-[#0a0a14] text-white">
      {/* TOP BAR — blue, like Selly */}
      <header className="bg-[#2563eb] sticky top-0 z-20 shadow-lg shadow-[#2563eb]/20">
        <div className="flex items-center h-16">
          {/* Brand block — fixed width matches sidebar */}
          <div className="hidden lg:flex items-center gap-2 w-[240px] px-6 border-r border-white/10">
            <div className="w-8 h-8 rounded-md bg-white/20 backdrop-blur flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-white" strokeWidth={2.5} />
            </div>
            <span className="font-display font-black text-base text-white">Better<span className="text-white/70">Social</span></span>
          </div>
          <div className="lg:hidden flex items-center gap-2 px-4">
            <button
              onClick={() => setSidebarOpen(true)}
              data-testid="mobile-menu-btn"
              className="w-8 h-8 rounded-md hover:bg-white/15 flex items-center justify-center"
              title="Open menu"
            >
              <Menu className="w-5 h-5 text-white" />
            </button>
            <div className="w-7 h-7 rounded-md bg-white/20 flex items-center justify-center">
              <Sparkles className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="font-display font-black text-sm text-white">BS</span>
          </div>

          {/* Search */}
          <div className="flex-1 px-4 md:px-8 max-w-2xl">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/60" />
              <input
                data-testid="dashboard-search"
                placeholder="Search or ask a question"
                className="w-full bg-white/15 hover:bg-white/20 focus:bg-white/25 transition border-0 rounded-md pl-10 pr-4 py-2.5 text-sm text-white placeholder-white/60 outline-none focus:ring-2 focus:ring-white/30"
              />
            </div>
          </div>

          {/* Right cluster */}
          <div className="flex items-center gap-2 md:gap-3 px-4 md:px-6 ml-auto">
            <button
              onClick={() => unreadDms > 0 ? changeView("messages") : (unreadTickets > 0 && changeView("tickets"))}
              data-testid="header-bell"
              className="relative w-9 h-9 rounded-md hover:bg-white/15 flex items-center justify-center transition"
              title={unreadDms > 0 ? `${unreadDms} unread message${unreadDms > 1 ? "s" : ""}` : unreadTickets > 0 ? `${unreadTickets} ticket update${unreadTickets > 1 ? "s" : ""}` : "No new notifications"}
            >
              <Bell className="w-4 h-4 text-white" />
              {(unreadDms > 0 || unreadTickets > 0) && (
                <>
                  <span className="absolute top-0.5 right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-red-500 ring-2 ring-[#2563eb] text-[9px] font-bold text-white flex items-center justify-center leading-none">
                    {unreadDms + unreadTickets}
                  </span>
                  <span className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-red-500 ring-2 ring-[#2563eb] animate-ping opacity-60" />
                </>
              )}
            </button>
            <div className="hidden sm:flex items-center gap-2 pl-3 ml-1 border-l border-white/15">
              <div className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center text-xs font-bold text-white" data-testid="client-username">
                {user.username.slice(0, 2).toUpperCase()}
              </div>
              <div className="text-xs">
                <div className="font-bold text-white leading-tight">{user.username}</div>
                <div className="text-white/70 leading-tight">{user.role || "member"}</div>
              </div>
            </div>
            <button
              onClick={() => {
                logout();
                nav("/");
              }}
              data-testid="client-logout"
              className="ml-1 inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md hover:bg-white/15 text-white/90 transition"
              title="Logout"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      <div className="flex">
        {/* SIDEBAR — desktop (fixed) + mobile (drawer overlay) */}
        <aside
          data-testid="dashboard-sidebar"
          className={`${sidebarOpen ? "translate-x-0" : "-translate-x-full"} lg:translate-x-0 fixed lg:sticky top-16 left-0 h-[calc(100vh-4rem)] w-[280px] lg:w-[240px] bg-[#0a0a14] border-r border-white/5 flex flex-col z-40 transition-transform duration-300 self-start overflow-y-auto`}
        >
          <div className="px-6 pt-6 pb-3 text-[10px] uppercase tracking-[0.25em] text-white/30 font-bold">
            Main Menu
          </div>
          <nav className="px-3 space-y-0.5">
            <SideLinkV2 icon={LayoutDashboard} label="Dashboard" active={view === "home"} onClick={() => changeView("home")} testId="nav-home" />
          </nav>

          <div className="px-6 pt-6 pb-3 text-[10px] uppercase tracking-[0.25em] text-white/30 font-bold">Wallet</div>
          <nav className="px-3 space-y-0.5">
            <SideLinkV2 icon={CreditCard} label="Add Funds" active={view === "funds"} onClick={() => changeView("funds")} testId="nav-funds" badge={`$${balance.toFixed(2)}`} />
            <SideLinkV2 icon={Ticket} label="Redeem Coupon" active={view === "redeem"} onClick={() => changeView("redeem")} testId="nav-redeem" />
            <SideLinkV2 icon={ArrowUpRight} label="Withdraw" active={view === "withdraw"} onClick={() => changeView("withdraw")} testId="nav-withdraw" badge={withdrawable > 0 ? `$${withdrawable.toFixed(2)}` : null} />
          </nav>

          <div className="px-6 pt-6 pb-3 text-[10px] uppercase tracking-[0.25em] text-white/30 font-bold">Community</div>
          <nav className="px-3 space-y-0.5">
            <SideLinkV2 icon={MessageSquare} label="Messages" active={view === "messages"} onClick={() => changeView("messages")} testId="nav-messages" badge={unreadDms > 0 ? unreadDms : null} badgeKind="alert" />
          </nav>


          <div className="px-6 pt-6 pb-3 text-[10px] uppercase tracking-[0.25em] text-white/30 font-bold">Shop</div>
          <nav className="px-3 space-y-0.5">
            <SideLinkV2 icon={ShoppingBag} label="Buy Services" active={view === "buy"} onClick={() => changeView("buy")} testId="nav-buy" />
          </nav>

          <div className="px-6 pt-6 pb-3 text-[10px] uppercase tracking-[0.25em] text-white/30 font-bold">Support</div>
          <nav className="px-3 space-y-0.5 pb-6">
            <SideLinkV2 icon={LifeBuoy} label="Tickets" active={view === "tickets"} onClick={() => changeView("tickets")} testId="nav-tickets" badge={unreadTickets > 0 ? unreadTickets : null} badgeKind="alert" />
            <SideLinkV2 icon={FileText} label="Terms of Service" active={view === "tos"} onClick={() => changeView("tos")} testId="nav-tos" />
            <Link
              to="/"
              className="flex items-center gap-3 px-4 py-2.5 rounded-md text-sm text-white/55 hover:text-white hover:bg-white/[0.04] transition"
              data-testid="nav-catalog"
            >
              <ExternalLink className="w-4 h-4" />
              <span className="flex-1">Public site</span>
            </Link>
          </nav>

          <div className="mt-auto px-3 pb-6">
            <div className="flex items-center gap-2 px-4 py-3 bg-[#13091a] rounded-md">
              <div className="w-8 h-8 rounded-full bg-[#2563eb] flex items-center justify-center text-xs font-bold">
                {user.username.slice(0, 2).toUpperCase()}
              </div>
              <div className="text-xs">
                <div className="font-bold text-white leading-tight">{user.username}</div>
                <div className="text-white/40 leading-tight">{user.role || "member"}</div>
              </div>
            </div>
          </div>
        </aside>

        {/* Mobile drawer backdrop */}
        {sidebarOpen && (
          <div
            onClick={() => setSidebarOpen(false)}
            data-testid="sidebar-backdrop"
            className="lg:hidden fixed inset-0 top-16 z-30 bg-black/60 backdrop-blur-sm"
          />
        )}

        {/* MAIN CONTENT */}
        <main className="flex-1 px-4 md:px-8 lg:px-10 py-6 md:py-10 pb-24 lg:pb-10">
          {viewLoading ? (
            <div className="flex items-center justify-center py-24" data-testid="view-preloader">
              <div className="flex flex-col items-center gap-3">
                <div className="w-10 h-10 border-2 border-white/10 border-t-[#3b82f6] rounded-full animate-spin" />
                <div className="text-xs text-white/40 uppercase tracking-widest">Loading</div>
              </div>
            </div>
          ) : (
            <div className="animate-in fade-in duration-200">
              {view === "home" && (
                <HomeView user={user} stats={stats} />
              )}
              {view === "funds" && (
                <FundsView authedApi={authedApi} balance={balance} reloadBalance={loadBalance} />
              )}
              {view === "buy" && (
                <BuyView authedApi={authedApi} balance={balance} reloadBalance={loadBalance} />
              )}
              {view === "redeem" && (
                <RedeemView authedApi={authedApi} balance={balance} reloadBalance={loadBalance} />
              )}
              {view === "slots" && (
                <SlotsView authedApi={authedApi} balance={balance} withdrawable={withdrawable} onBalanceChange={loadBalance} />
              )}
              {view === "withdraw" && (
                <WithdrawView authedApi={authedApi} balance={balance} withdrawable={withdrawable} reloadBalance={loadBalance} />
              )}
              {view === "tickets" && <TicketsView authedApi={authedApi} />}
              {view === "messages" && <MessagesView authedApi={authedApi} me={user} onReadMessages={loadUnreadDms} />}
              {view === "tos" && <TermsOfServiceView />}
            </div>
          )}
        </main>
      </div>

      {/* Better Social AI floating widget */}
      <AIWidget open={aiOpen} onOpenChange={setAiOpen} />
      {!aiOpen && !(typeof window !== "undefined" && localStorage.getItem("bs_chat_banned") === "1") && (
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

function SideLink({ icon: Icon, label, active, onClick, testId, badge, badgeKind }) {
  return (
    <button
      onClick={onClick}
      data-testid={testId}
      className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-sm text-sm transition group ${
        active
          ? "bg-gradient-to-r from-[#FF007F]/20 to-transparent text-white border-l-2 border-[#FF007F]"
          : "text-white/60 hover:text-white hover:bg-white/[0.04] border-l-2 border-transparent"
      }`}
    >
      <Icon className={`w-4 h-4 transition ${active ? "text-[#FF007F]" : "group-hover:text-white"}`} />
      <span className="flex-1 text-left">{label}</span>
      {badge != null && badgeKind === "alert" && (
        <span
          data-testid={`${testId}-badge`}
          className="min-w-[20px] h-5 px-1.5 inline-flex items-center justify-center text-[10px] font-bold rounded-full bg-red-500 text-white shadow-[0_0_10px_rgba(239,68,68,0.6)] animate-pulse"
        >
          {badge}
        </span>
      )}
      {badge != null && badgeKind !== "alert" && (
        <span className="text-[10px] font-mono text-emerald-400">{badge}</span>
      )}
    </button>
  );
}

function SideLinkV2({ icon: Icon, label, active, onClick, testId, badge, badgeKind }) {
  return (
    <button
      onClick={onClick}
      data-testid={testId}
      className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-md text-sm transition relative ${
        active
          ? "bg-[#2563eb]/10 text-[#3b82f6] font-bold"
          : "text-white/55 hover:text-white hover:bg-white/[0.04]"
      }`}
    >
      {active && <span className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-[#3b82f6] rounded-r" />}
      <Icon className={`w-4 h-4 ${active ? "text-[#3b82f6]" : ""}`} />
      <span className="flex-1 text-left">{label}</span>
      {badge != null && badgeKind === "alert" && (
        <span
          data-testid={`${testId}-badge`}
          className="min-w-[20px] h-5 px-1.5 inline-flex items-center justify-center text-[10px] font-bold rounded-full bg-red-500 text-white"
        >
          {badge}
        </span>
      )}
      {badge != null && badgeKind !== "alert" && (
        <span className="text-[10px] font-mono text-emerald-400">{badge}</span>
      )}
    </button>
  );
}

function TermsOfServiceView() {
  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight">Terms of Service</h1>
        <p className="text-white/50 text-sm mt-2">Last updated: {new Date().toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}</p>
      </div>

      <div className="bg-[#13091a] border border-white/5 rounded-lg p-6 md:p-8 space-y-6 text-sm leading-relaxed text-white/75">
        <section>
          <h2 className="font-display font-bold text-lg text-white mb-2">1. Acceptance of Terms</h2>
          <p>By creating an account, placing an order, or otherwise using Better Social (&quot;the Service&quot;), you agree to be bound by these Terms of Service. If you do not agree, please do not use the Service.</p>
        </section>
        <section>
          <h2 className="font-display font-bold text-lg text-white mb-2">2. Services Provided</h2>
          <p>Better Social provides social-media growth services, custom orders, and related digital products. Delivery times are estimates; actual completion may vary based on the target platform, network conditions, and provider availability.</p>
        </section>
        <section>
          <h2 className="font-display font-bold text-lg text-white mb-2">3. Payments &amp; Refunds</h2>
          <p>Payments are processed via third-party providers (Selly.io, coupons, or account balance). Once an order has been submitted to the provider network, it cannot be cancelled. Refund requests must be sent to <span className="text-emerald-400 font-mono">billrelevant@better-social.pro</span> within 7 days and are reviewed case-by-case.</p>
        </section>
        <section>
          <h2 className="font-display font-bold text-lg text-white mb-2">4. Prohibited Uses</h2>
          <p>You may not use the Service to violate any platform&apos;s terms of service, harass others, place fraudulent orders, or use stolen payment methods. Doing so will result in immediate account termination and forfeiture of balance.</p>
        </section>
        <section>
          <h2 className="font-display font-bold text-lg text-white mb-2">5. Slot Machine &amp; Rewards</h2>
          <p>The Slot Machine minigame is provided for entertainment. Winnings are credited to your withdrawable balance and can be cashed out subject to a $10 minimum. Deposits are non-refundable once used for spins.</p>
        </section>
        <section>
          <h2 className="font-display font-bold text-lg text-white mb-2">6. Account Security</h2>
          <p>You are responsible for keeping your login credentials confidential. Use the &quot;Forgot password?&quot; link on the login page if you suspect compromise. We will never ask you for your password.</p>
        </section>
        <section>
          <h2 className="font-display font-bold text-lg text-white mb-2">7. Contact</h2>
          <p>General support: <span className="text-emerald-400 font-mono">support@better-social.pro</span><br />Billing &amp; refunds: <span className="text-emerald-400 font-mono">billrelevant@better-social.pro</span></p>
        </section>
      </div>
    </div>
  );
}

function HomeView({ user, stats, last7 }) {
  const balance = stats ? Number(stats.balance || 0) : 0;
  const withdrawable = stats ? Number(stats.withdrawable_balance || 0) : 0;
  const orders = stats ? Number(stats.total_orders || 0) : 0;
  const onlineUsers = stats ? Number(stats.online_users || 0) : 0;
  const dateRange = (() => {
    const today = new Date();
    const past = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000);
    const fmt = (d) => d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    return `${fmt(past)} – ${fmt(today)}`;
  })();

  return (
    <div className="space-y-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight">
            Dashboard
          </h1>
          <p className="text-white/50 text-sm mt-2">
            Welcome <span className="text-white font-bold">{user.username}</span>, let&apos;s see how things are going this week.
          </p>
        </div>
        <div className="inline-flex items-center gap-2 px-4 py-2.5 bg-[#13091a] border border-white/5 rounded-md text-xs text-white/70" data-testid="date-range-pill">
          <Calendar className="w-3.5 h-3.5 text-[#3b82f6]" />
          {dateRange}
        </div>
      </div>

      {/* Top row — three big metric cards (Sales / Orders / Customers style) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <BigStatCard
          label="Sales"
          value={`$${balance.toFixed(2)}`}
          sub="Current balance"
          accent="#3b82f6"
          testId="big-stat-balance"
        />
        <BigStatCard
          label="Orders"
          value={orders}
          sub="Total placed"
          accent="#3b82f6"
          testId="big-stat-orders"
        />
        <BigStatCard
          label="Withdrawable"
          value={`$${withdrawable.toFixed(2)}`}
          sub="From winnings"
          accent="#3b82f6"
          testId="big-stat-withdrawable"
        />
      </div>

      {/* Second row — Views / Visitors */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <BigStatCard
          label="Online Users"
          value={onlineUsers}
          sub="Right now"
          accent="#3b82f6"
          testId="big-stat-online"
        />
        <BigStatCard
          label="Members"
          value={stats ? stats.registered_users : "—"}
          sub="All-time"
          accent="#3b82f6"
          testId="big-stat-registered"
        />
      </div>

      {/* Quick actions */}
      <div>
        <div className="text-[10px] uppercase tracking-[0.25em] text-white/30 font-bold mb-3">Quick Actions</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <QuickAction icon={Plus} label="Add Funds" tab="funds" testId="quick-funds" />
          <QuickAction icon={ShoppingBag} label="New Order" tab="orders" testId="quick-orders" />
          <QuickAction icon={MessageSquare} label="Open Ticket" tab="tickets" testId="quick-tickets" />
        </div>
      </div>
    </div>
  );
}

function BigStatCard({ label, value, sub, accent, testId }) {
  return (
    <div
      data-testid={testId}
      className="bg-[#13091a] border border-white/5 rounded-lg p-6 hover:border-white/10 transition relative overflow-hidden"
    >
      <div className="text-xs uppercase tracking-wider text-white/40 mb-3 font-bold">{label}</div>
      <div className="text-3xl md:text-4xl font-display font-black text-white tracking-tight">{value}</div>
      {sub && <div className="text-[11px] text-white/40 mt-2">{sub}</div>}
      <div className="mt-5 flex items-center gap-1">
        {Array.from({ length: 14 }).map((_, i) => (
          <span
            key={i}
            className="flex-1 h-1 rounded-full"
            style={{ background: `${accent}${i < 7 ? "" : "30"}`, opacity: i < 7 ? 0.9 : 0.4 }}
          />
        ))}
      </div>
    </div>
  );
}

function QuickAction({ icon: Icon, label, tab, testId }) {
  const navigate = useNavigate();
  return (
    <button
      data-testid={testId}
      onClick={() => navigate(`/client/dashboard?tab=${tab}`)}
      className="bg-[#13091a] border border-white/5 rounded-lg p-5 flex items-center gap-4 hover:border-[#3b82f6]/40 hover:bg-[#15102e] transition text-left group"
    >
      <div className="w-11 h-11 rounded-md bg-[#3b82f6]/10 border border-[#3b82f6]/30 flex items-center justify-center group-hover:bg-[#3b82f6]/20 transition">
        <Icon className="w-5 h-5 text-[#3b82f6]" />
      </div>
      <div className="flex-1">
        <div className="font-bold text-sm">{label}</div>
        <div className="text-[11px] text-white/40 mt-0.5">Tap to open</div>
      </div>
      <ArrowUpRight className="w-4 h-4 text-white/30 group-hover:text-[#3b82f6] transition" />
    </button>
  );
}

function FundsView({ authedApi, balance, reloadBalance }) {
  const [amount, setAmount] = useState(10);
  const [txns, setTxns] = useState([]);
  const [pending, setPending] = useState([]);
  const [creating, setCreating] = useState(false);
  const [verifyingId, setVerifyingId] = useState(null);
  const [gateway] = useState("bitcoin");

  const loadTxns = async () => {
    try {
      const r = await authedApi().get("/client/transactions");
      setTxns(r.data.transactions || []);
    } catch {}
  };

  const loadPending = async () => {
    try {
      const r = await authedApi().get("/client/funds/pending-deposits");
      setPending(r.data.pending || []);
    } catch {}
  };

  const verifyDeposit = async (txId) => {
    setVerifyingId(txId);
    try {
      const r = await authedApi().post(`/client/funds/nowpayments-verify/${txId}`);
      if (r.data.credited) {
        toast.success(`✅ Deposit credited! +$${r.data.amount} (+ $${r.data.bonus} bonus)`);
        reloadBalance && reloadBalance();
        loadPending();
        loadTxns();
      } else if (r.data.already_credited) {
        toast.info("Already credited — refreshing balance.");
        reloadBalance && reloadBalance();
        loadPending();
      } else {
        toast.info(`Payment status: ${r.data.status || "unknown"} — try again in a minute.`);
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to verify deposit");
    }
    setVerifyingId(null);
  };

  useEffect(() => {
    loadTxns();
    loadPending();
    // Note: the ?nowpay=1&tx=... URL param is handled at the parent Dashboard level
    // (so it fires even when the user lands on Home). We only load pending here.
    // eslint-disable-next-line
  }, []);

  const paySelly = async () => {
    const a = Number(amount) || 0;
    if (a < 5) {
      toast.error("Min $5 for Selly checkout");
      return;
    }
    setCreating(true);
    try {
      const r = await authedApi().post("/client/funds/selly-create", { amount: a, gateway });
      window.location.href = r.data.checkout_url;
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to start Selly checkout");
      setCreating(false);
    }
  };

  const payNowpayments = async () => {
    const a = Number(amount) || 0;
    if (a < 1) {
      toast.error("Min $1 for crypto checkout");
      return;
    }
    setCreating(true);
    try {
      const r = await authedApi().post("/client/funds/nowpayments-create", { amount: a });
      window.location.href = r.data.checkout_url;
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to start crypto checkout");
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
        <div className="bg-[#0d0a14] border border-white/5 rounded-sm p-5 relative overflow-hidden">
          <div className="absolute -top-12 -right-12 w-32 h-32 rounded-full blur-3xl opacity-30 bg-[#FF007F]" />
          <div className="text-[10px] uppercase tracking-[0.2em] text-white/40 relative">Current balance</div>
          <div className="font-display font-black text-3xl md:text-4xl text-[#FF007F] mt-2 relative" data-testid="funds-balance">
            ${balance.toFixed(2)}
          </div>
        </div>
        <div className="bg-[#0d0a14] border border-emerald-500/30 rounded-sm p-5">
          <div className="text-[10px] uppercase tracking-[0.2em] text-white/40">Payment options</div>
          <div className="font-display font-bold text-lg mt-2 text-emerald-300">
            Crypto · Visa · Mastercard
          </div>
          <div className="text-[11px] text-white/40 mt-1">
            Instant credit after Selly confirms payment
          </div>
        </div>
      </div>

      <div className="bg-[#0d0a14] border border-white/5 rounded-sm p-5 md:p-6">
        <h2 className="font-display font-bold text-lg mb-1">Add funds</h2>
        <p className="text-xs text-white/50 mb-4">
          1) Enter an amount → 2) Pay via Selly hosted checkout → 3) Balance auto-credits within seconds.
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
        <div className="mb-3">
          <Label className="text-[11px] uppercase tracking-wider text-white/60 mb-2 block">Payment Method</Label>
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
            {[
              { id: "bitcoin", label: "BTC" },
              { id: "ethereum", label: "ETH" },
              { id: "litecoin", label: "LTC" },
              { id: "bitcoin_cash", label: "BCH" },
              { id: "dogecoin", label: "DOGE" },
              { id: "stripe", label: "Card" },
            ].map((g) => (
              <button
                key={g.id}
                type="button"
                onClick={() => setGateway(g.id)}
                data-testid={`funds-gateway-${g.id}`}
                className={`px-2 py-2 text-xs rounded-sm border transition ${
                  gateway === g.id
                    ? "border-emerald-400 bg-emerald-500/10 text-emerald-300 font-bold"
                    : "border-white/10 text-white/60 hover:bg-white/5"
                }`}
              >
                {g.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <button
            onClick={payNowpayments}
            disabled={creating || Number(amount) < 1}
            data-testid="funds-pay-nowpayments"
            className="w-full py-3.5 rounded-sm font-bold text-sm inline-flex items-center justify-center gap-2 disabled:opacity-40 bg-gradient-to-r from-amber-400 via-amber-300 to-amber-400 text-black hover:scale-[1.01] transition shadow-lg shadow-amber-500/20"
          >
            {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <span className="text-base">₿</span>}
            Pay ${Number(amount) || 0} with Crypto (300+ coins · No KYC)
          </button>
          <div className="text-[10px] text-center text-white/40 uppercase tracking-wider">
            Min $1 · Instant credit after payment confirmation
          </div>
        </div>
      </div>

      {pending.length > 0 && (
        <div className="bg-amber-500/5 border border-amber-500/30 rounded-sm overflow-hidden" data-testid="pending-deposits-panel">
          <div className="px-4 md:px-6 py-3 border-b border-amber-500/20 flex items-center gap-2">
            <Clock className="w-4 h-4 text-amber-400" />
            <h3 className="font-display font-bold text-sm text-amber-300">Waiting for confirmation</h3>
          </div>
          <div className="p-4 md:p-5 space-y-3">
            <p className="text-xs text-white/60">
              If you already paid but your balance hasn&apos;t updated yet, click <b>Verify deposit</b> — we&apos;ll check with NOWPayments and credit your account instantly.
            </p>
            {pending.map((p) => (
              <div key={p.id} className="flex flex-wrap items-center gap-3 justify-between bg-black/30 rounded-sm px-3 py-2.5" data-testid={`pending-deposit-${p.id}`}>
                <div className="text-xs">
                  <div className="font-bold text-white">${Number(p.amount).toFixed(2)}</div>
                  <div className="text-white/40 text-[10px]">Started {new Date(p.created_at).toLocaleString()}</div>
                </div>
                <div className="flex gap-2">
                  {p.nowpayments_url && (
                    <a href={p.nowpayments_url} target="_blank" rel="noreferrer" className="text-[11px] px-3 py-1.5 rounded-sm border border-white/20 hover:bg-white/5">Open invoice</a>
                  )}
                  <button
                    onClick={() => verifyDeposit(p.id)}
                    disabled={verifyingId === p.id}
                    data-testid={`verify-deposit-${p.id}`}
                    className="text-[11px] px-3 py-1.5 rounded-sm bg-amber-500 hover:bg-amber-400 text-black font-bold inline-flex items-center gap-1.5 disabled:opacity-50"
                  >
                    {verifyingId === p.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
                    Verify deposit
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

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
    pending: { bg: "bg-amber-500/15", color: "text-amber-400", label: "pending" },
    approved: { bg: "bg-emerald-500/15", color: "text-emerald-400", label: "approved" },
    rejected: { bg: "bg-red-500/15", color: "text-red-400", label: "rejected" },
  };
  const m = map[status] || map.open;
  return (
    <span className={`text-[10px] uppercase tracking-wider px-2 py-1 rounded-sm font-bold ${m.bg} ${m.color}`}>
      {m.label}
    </span>
  );
}



function RedeemView({ authedApi, balance, reloadBalance }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState(null);

  const submit = async (e) => {
    e?.preventDefault();
    const c = code.trim().toUpperCase();
    if (c.length < 4) {
      toast.error("Enter a valid code");
      return;
    }
    setBusy(true);
    try {
      const r = await authedApi().post("/client/redeem-coupon", { code: c });
      toast.success(`Credited $${r.data.amount.toFixed(2)} to your balance`);
      setLast({ amount: r.data.amount, code: c, balance: r.data.balance });
      setCode("");
      reloadBalance();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to redeem");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl md:text-4xl font-black tracking-tight">Redeem Coupon</h1>
        <p className="text-white/50 text-sm mt-1">
          Got a gift code? Cash it into your wallet — usable on any service afterwards.
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="bg-[#0d0a14] border border-white/5 rounded-sm p-5">
          <div className="text-[10px] uppercase tracking-[0.2em] text-white/40">Current balance</div>
          <div className="font-display font-black text-3xl md:text-4xl text-[#FF007F] mt-2" data-testid="redeem-balance">
            ${balance.toFixed(2)}
          </div>
        </div>
        <div className="bg-[#0d0a14] border border-white/5 rounded-sm p-5">
          <div className="text-[10px] uppercase tracking-[0.2em] text-white/40">How it works</div>
          <ul className="text-xs text-white/70 mt-2 space-y-1 leading-relaxed">
            <li>1. Paste your <span className="text-[#FF007F] font-mono">BS-XXXX-XXXX-XXXX</span> code.</li>
            <li>2. The full coupon balance is credited instantly.</li>
            <li>3. Buy any service from <em>Buy Services</em>.</li>
          </ul>
        </div>
      </div>

      <form onSubmit={submit} className="bg-[#0d0a14] border border-white/5 rounded-sm p-5 md:p-6 space-y-4">
        <div>
          <Label className="text-[11px] uppercase tracking-wider text-white/60">Coupon code</Label>
          <Input
            data-testid="redeem-code-input"
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            placeholder="BS-XXXX-XXXX-XXXX"
            className="bg-[#1a1525] border-white/10 mt-1 font-mono tracking-wider"
            autoComplete="off"
          />
        </div>
        <button
          type="submit"
          disabled={busy || code.trim().length < 4}
          data-testid="redeem-submit"
          className="w-full py-3 gradient-pp rounded-sm font-bold text-sm inline-flex items-center justify-center gap-2 disabled:opacity-40"
        >
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
          Redeem to balance
        </button>
      </form>

      {last && (
        <div
          data-testid="redeem-success"
          className="bg-[#0d0a14] border border-emerald-500/40 rounded-sm p-5"
        >
          <div className="flex items-center gap-2 text-emerald-400 font-bold text-sm">
            <CheckCircle2 className="w-4 h-4" /> Coupon redeemed
          </div>
          <div className="text-xs text-white/60 mt-1">
            Code <span className="font-mono text-white/80">{last.code}</span> credited{" "}
            <span className="text-[#FF007F] font-bold">${last.amount.toFixed(2)}</span> to your balance
            (now ${last.balance.toFixed(2)}).
          </div>
        </div>
      )}
    </div>
  );
}

function BuyView({ authedApi, balance, reloadBalance }) {
  const [services, setServices] = useState([]);
  const [loadingSvc, setLoadingSvc] = useState(true);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [selected, setSelected] = useState(null);
  const [link, setLink] = useState("");
  const [qty, setQty] = useState(0);
  const [comments, setComments] = useState("");
  const [placing, setPlacing] = useState(false);
  const [last, setLast] = useState(null);

  const loadServices = async () => {
    setLoadingSvc(true);
    try {
      const r = await api.get("/services");
      setServices(r.data.services || []);
    } catch {
      toast.error("Failed to load catalog");
    } finally {
      setLoadingSvc(false);
    }
  };

  useEffect(() => {
    loadServices();
  }, []);

  const categories = ["all", ...Array.from(new Set(services.map((s) => s.category))).slice(0, 30)];

  const filtered = services.filter((s) => {
    if (category !== "all" && s.category !== category) return false;
    if (search && !s.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const total = selected && qty ? (Number(selected.rate) * Number(qty)) / 1000 : 0;
  const needsComments = selected && selected.needs_custom_text;
  const commentsOk = !needsComments || comments.trim().length > 0;
  const canBuy = selected && qty >= (selected.min || 1) && qty <= (selected.max || 1e9) && link.trim().length > 4 && total <= balance && commentsOk;

  const place = async () => {
    if (!selected) return;
    setPlacing(true);
    try {
      const r = await authedApi().post("/client/order-with-balance", {
        service_id: selected.service,
        link: link.trim(),
        quantity: Number(qty),
        comments: needsComments ? comments.trim() : undefined,
      });
      toast.success(`Order placed! ID #${r.data.smm_order_id}`);
      setLast({ id: r.data.smm_order_id, charge: r.data.charge });
      setSelected(null);
      setLink("");
      setQty(0);
      setComments("");
      reloadBalance();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Order failed");
    } finally {
      setPlacing(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-2xl md:text-4xl font-black tracking-tight">Buy Services</h1>
          <p className="text-white/50 text-sm mt-1">
            Pay instantly with your account balance — no checkout, no waiting.
          </p>
        </div>
        <div className="bg-[#0d0a14] border border-white/5 rounded-sm px-4 py-2">
          <div className="text-[10px] uppercase tracking-[0.2em] text-white/40">Balance</div>
          <div
            className="font-display font-black text-xl text-[#FF007F]"
            data-testid="buy-balance"
          >
            ${balance.toFixed(2)}
          </div>
        </div>
      </div>

      {last && (
        <div className="bg-[#0d0a14] border border-emerald-500/40 rounded-sm p-4 flex items-center justify-between gap-3">
          <div className="text-xs">
            <span className="text-emerald-400 font-bold">Last order placed</span>{" "}
            — Order ID <span className="font-mono">#{last.id}</span> · charged{" "}
            <span className="text-[#FF007F] font-bold">${last.charge.toFixed(2)}</span>
          </div>
          <button
            onClick={() => setLast(null)}
            className="text-[10px] uppercase tracking-wider text-white/50 hover:text-white"
          >
            dismiss
          </button>
        </div>
      )}

      {selected ? (
        <div className="bg-[#0d0a14] border border-[#FF007F]/40 rounded-sm p-5 md:p-6 space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[10px] uppercase tracking-[0.2em] text-white/40">{selected.category}</div>
              <div className="font-bold text-base mt-0.5 break-words">{selected.name}</div>
              <div className="text-xs text-white/50 mt-1">
                ${Number(selected.rate).toFixed(3)} / 1000 · Min {selected.min} · Max {selected.max}
              </div>
            </div>
            <button
              onClick={() => setSelected(null)}
              data-testid="buy-deselect"
              className="text-xs uppercase tracking-wider text-white/50 hover:text-white"
            >
              ← Change
            </button>
          </div>

          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <Label className="text-[11px] uppercase tracking-wider text-white/60">Target link</Label>
              <Input
                data-testid="buy-link"
                value={link}
                onChange={(e) => setLink(e.target.value)}
                placeholder="https://…"
                className="bg-[#1a1525] border-white/10 mt-1"
              />
            </div>
            <div>
              <Label className="text-[11px] uppercase tracking-wider text-white/60">
                Quantity ({selected.min}–{selected.max})
              </Label>
              <Input
                data-testid="buy-qty"
                type="number"
                value={qty || ""}
                onChange={(e) => setQty(e.target.value)}
                min={selected.min}
                max={selected.max}
                className="bg-[#1a1525] border-white/10 mt-1"
              />
            </div>
          </div>

          {needsComments && (
            <div data-testid="buy-comments-block" className="bg-amber-500/10 border border-amber-500/40 rounded-sm p-4 space-y-2">
              <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-amber-300 font-bold">
                Custom comments required
              </div>
              <Label className="text-[11px] text-white/70">
                Enter your comments — one per line. We'll post {qty || 0} comment{qty !== 1 ? "s" : ""}, picking from this list.
              </Label>
              <textarea
                data-testid="buy-comments"
                value={comments}
                onChange={(e) => setComments(e.target.value.slice(0, 5000))}
                rows={5}
                placeholder={"great post!\nlove this 🔥\nawesome content"}
                className="w-full bg-[#1a1525] border border-white/10 rounded-sm px-3 py-2 text-sm font-mono text-white outline-none focus:border-[#FF007F]"
              />
              <div className="text-[10px] text-white/40">
                {comments.split("\n").filter((l) => l.trim()).length} non-empty line(s) · {comments.length}/5000 chars
              </div>
            </div>
          )}

          <div className="flex items-center justify-between bg-[#1a1525]/60 border border-white/5 rounded-sm px-4 py-3">
            <div className="text-xs uppercase tracking-wider text-white/50">Total</div>
            <div className="font-display font-black text-2xl text-[#FF007F]" data-testid="buy-total">
              ${total.toFixed(4)}
            </div>
          </div>

          {total > balance && qty > 0 && (
            <div className="text-xs text-amber-400">
              Not enough balance. Top up via Add Funds or redeem a coupon.
            </div>
          )}

          <button
            disabled={!canBuy || placing}
            onClick={place}
            data-testid="buy-confirm"
            className="w-full py-3 gradient-pp rounded-sm font-bold text-sm inline-flex items-center justify-center gap-2 disabled:opacity-40"
          >
            {placing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
            Place order — ${total.toFixed(2)}
          </button>
        </div>
      ) : (
        <>
          <div className="flex flex-col sm:flex-row gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
              <Input
                data-testid="buy-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search services…"
                className="bg-[#1a1525] border-white/10 pl-9"
              />
            </div>
            <select
              data-testid="buy-category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="bg-[#1a1525] border border-white/10 rounded-sm px-3 py-2 text-sm text-white outline-none"
            >
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c === "all" ? "All categories" : c}
                </option>
              ))}
            </select>
          </div>

          <div className="bg-[#0d0a14] border border-white/5 rounded-sm overflow-hidden">
            {loadingSvc && (
              <div className="px-6 py-12 text-center text-white/30 text-xs">
                <Loader2 className="w-5 h-5 animate-spin mx-auto" />
              </div>
            )}
            {!loadingSvc && filtered.length === 0 && (
              <div className="px-6 py-12 text-center text-white/30 text-xs">No services match.</div>
            )}
            <div className="max-h-[60vh] overflow-y-auto divide-y divide-white/5">
              {filtered.slice(0, 80).map((s) => (
                <button
                  key={s.service}
                  onClick={() => setSelected(s)}
                  data-testid={`buy-svc-${s.service}`}
                  className="w-full text-left px-5 py-3 hover:bg-white/[0.03] transition flex items-center justify-between gap-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-[10px] uppercase tracking-wider text-white/40 truncate">
                      {s.category}
                    </div>
                    <div className="text-sm font-medium text-white/90 truncate">{s.name}</div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="font-display font-bold text-[#FF007F] text-sm">
                      ${Number(s.rate).toFixed(3)}
                    </div>
                    <div className="text-[10px] uppercase tracking-wider text-white/40">/ 1000</div>
                  </div>
                </button>
              ))}
            </div>
            {filtered.length > 80 && (
              <div className="px-6 py-3 text-center text-[10px] uppercase tracking-wider text-white/40 border-t border-white/5">
                Showing 80 of {filtered.length} — refine your search.
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

const PRIZE_TABLE = [
  { mult: 10000, label: "10,000x", chance: "1 in 20,000", color: "#FFD700" },
  { mult: 1000, label: "1,000x", chance: "1 in 6,666", color: "#FF007F" },
  { mult: 100, label: "100x", chance: "1 in 3,333", color: "#FF6B6B" },
  { mult: 50, label: "50x", chance: "1 in 666", color: "#FFB800" },
  { mult: 10, label: "10x", chance: "1 in 250", color: "#00E5FF" },
  { mult: 5, label: "5x", chance: "~1 in 111", color: "#7000FF" },
  { mult: 2, label: "2x", chance: "~1 in 40", color: "#A78BFA" },
  { mult: 0.5, label: "0.5x", chance: "~1 in 25", color: "#94A3B8" },
  { mult: 0, label: "0x (lose)", chance: "~92%", color: "#475569" },
];

function CasinoView({ authedApi, balance, reloadBalance }) {
  const [stake, setStake] = useState(5);
  const [spinning, setSpinning] = useState(false);
  const [result, setResult] = useState(null); // {multiplier, win, stake}
  const [history, setHistory] = useState([]);
  const [reelText, setReelText] = useState("?");
  const reelInterval = useRef(null);

  const loadHistory = async () => {
    try {
      const r = await authedApi().get("/client/casino/history");
      setHistory(r.data.rolls || []);
    } catch {}
  };

  useEffect(() => {
    loadHistory();
    // eslint-disable-next-line
  }, []);

  useEffect(() => () => {
    if (reelInterval.current) clearInterval(reelInterval.current);
  }, []);

  const spin = async () => {
    const s = Number(stake);
    if (!s || s < 1 || s > 100) {
      toast.error("Stake must be between $1 and $100");
      return;
    }
    if (s > balance) {
      toast.error("Not enough balance");
      return;
    }
    setSpinning(true);
    setResult(null);
    // Animate reel — cycle random multipliers for ~1.8s
    const samples = ["0x", "0.5x", "2x", "5x", "10x", "50x", "100x", "1000x", "10000x"];
    let i = 0;
    reelInterval.current = setInterval(() => {
      i = (i + 1) % samples.length;
      setReelText(samples[Math.floor(Math.random() * samples.length)]);
    }, 70);

    try {
      // Slight delay so the reel actually visibly spins
      const spinPromise = authedApi().post("/client/casino/spin", { stake: s });
      await new Promise((res) => setTimeout(res, 1500));
      const r = await spinPromise;
      clearInterval(reelInterval.current);
      const m = r.data.multiplier;
      setReelText(m === 0 ? "💥" : `${m}x`);
      setResult({
        multiplier: m,
        win: r.data.win,
        stake: r.data.stake,
        net: r.data.net,
      });
      if (m >= 100) {
        toast.success(`🎰 JACKPOT! ${m}x — you won $${r.data.win.toFixed(2)}!`, { duration: 8000 });
      } else if (m > 0) {
        toast.success(`x${m} · won $${r.data.win.toFixed(2)}`);
      } else {
        toast(`No win this time — try again!`);
      }
      reloadBalance();
      loadHistory();
    } catch (err) {
      if (reelInterval.current) clearInterval(reelInterval.current);
      setReelText("?");
      toast.error(err.response?.data?.detail || "Spin failed");
    } finally {
      setSpinning(false);
    }
  };

  const resultColor =
    result?.multiplier >= 100
      ? "#FFD700"
      : result?.multiplier >= 5
      ? "#FF007F"
      : result?.multiplier > 0
      ? "#00E5FF"
      : "#94A3B8";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl md:text-4xl font-black tracking-tight flex items-center gap-3">
          <Dices className="w-7 h-7 text-[#FFB800]" /> Try Chance
        </h1>
        <p className="text-white/50 text-sm mt-1">
          Bet $1 – $100 from your balance. Multipliers up to <span className="text-[#FFD700] font-bold">10,000x</span> — but hard to hit. Play responsibly.
        </p>
      </div>

      {/* MAIN GAME PANEL */}
      <div className="relative bg-gradient-to-br from-[#0d0a14] via-[#1a0a22] to-[#0d0a14] border border-[#FFB800]/30 rounded-sm p-6 md:p-8 overflow-hidden">
        <div
          className="absolute -top-20 -right-20 w-72 h-72 rounded-full blur-3xl opacity-20"
          style={{ background: "#FFB800" }}
        />
        <div
          className="absolute -bottom-20 -left-20 w-72 h-72 rounded-full blur-3xl opacity-20"
          style={{ background: "#FF007F" }}
        />

        <div className="relative">
          <div className="flex items-center justify-between mb-4">
            <div className="text-[10px] uppercase tracking-[0.2em] text-white/40">Current balance</div>
            <div className="font-display font-black text-xl text-[#FF007F]" data-testid="casino-balance">
              ${balance.toFixed(2)}
            </div>
          </div>

          {/* REEL */}
          <div
            data-testid="casino-reel"
            className={`relative mx-auto w-full max-w-md h-44 md:h-56 bg-[#050505] border-2 rounded-sm flex items-center justify-center mb-6 overflow-hidden transition-colors ${
              spinning ? "border-[#FFB800] animate-pulse" : result ? "border-[#FF007F]" : "border-white/10"
            }`}
            style={{
              boxShadow: result?.multiplier >= 100 ? `0 0 80px ${resultColor}` : undefined,
            }}
          >
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(255,184,0,0.08),transparent_70%)] pointer-events-none" />
            <div
              data-testid="casino-reel-text"
              className={`font-display font-black tracking-tight transition-all ${
                spinning ? "text-5xl md:text-7xl text-white/80" : result?.multiplier >= 100 ? "text-6xl md:text-8xl" : "text-5xl md:text-7xl"
              }`}
              style={{ color: result ? resultColor : "white" }}
            >
              {result ? (result.multiplier === 0 ? "💥 0x" : `${result.multiplier}x`) : reelText}
            </div>
          </div>

          {result && (
            <div
              data-testid="casino-result"
              className={`text-center mb-6 ${result.multiplier > 0 ? "text-emerald-400" : "text-red-400"}`}
            >
              <div className="text-xs uppercase tracking-[0.2em] text-white/40">
                {result.multiplier > 0 ? "You won" : "Better luck next time"}
              </div>
              <div className="font-display font-black text-3xl md:text-4xl mt-1">
                {result.multiplier > 0 ? "+" : ""}${result.net.toFixed(2)}
              </div>
            </div>
          )}

          {/* STAKE + SPIN */}
          <div className="grid sm:grid-cols-[1fr_auto] gap-3 items-end max-w-md mx-auto">
            <div>
              <Label className="text-[11px] uppercase tracking-wider text-white/60">Stake (USD)</Label>
              <Input
                data-testid="casino-stake"
                type="number"
                min="1"
                max="100"
                step="1"
                value={stake}
                onChange={(e) => setStake(e.target.value)}
                disabled={spinning}
                className="bg-[#1a1525] border-white/10 mt-1 font-mono text-lg"
              />
            </div>
            <button
              onClick={spin}
              disabled={spinning || Number(stake) < 1 || Number(stake) > 100 || Number(stake) > balance}
              data-testid="casino-spin"
              className="h-[42px] mt-5 sm:mt-0 px-6 rounded-sm font-bold text-sm inline-flex items-center justify-center gap-2 disabled:opacity-40 bg-gradient-to-r from-[#FFB800] to-[#FF007F] text-black hover:scale-[1.02] transition"
            >
              {spinning ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" /> Spinning…
                </>
              ) : (
                <>
                  <Dices className="w-4 h-4" /> SPIN
                </>
              )}
            </button>
          </div>

          <div className="flex flex-wrap justify-center gap-2 mt-3 max-w-md mx-auto">
            {[1, 5, 10, 25, 50, 100].map((q) => (
              <button
                key={q}
                onClick={() => setStake(q)}
                disabled={spinning}
                data-testid={`casino-stake-${q}`}
                className="px-3 py-1 border border-white/10 rounded-sm text-xs hover:bg-white/5 disabled:opacity-40"
              >
                ${q}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* PRIZE TABLE */}
      <div className="bg-[#0d0a14] border border-white/5 rounded-sm overflow-hidden">
        <div className="px-5 py-3 border-b border-white/5">
          <h3 className="font-display font-bold text-sm">Prize table</h3>
          <p className="text-[10px] uppercase tracking-wider text-white/40">
            Higher payouts are rarer. Provably randomized server-side.
          </p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-px bg-white/5">
          {PRIZE_TABLE.map((p) => (
            <div
              key={p.mult}
              className="bg-[#0d0a14] px-4 py-3 flex items-center justify-between gap-3"
              data-testid={`prize-${p.mult}`}
            >
              <div>
                <div className="font-display font-black text-lg" style={{ color: p.color }}>
                  {p.label}
                </div>
                <div className="text-[10px] uppercase tracking-wider text-white/40">{p.chance}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* HISTORY */}
      <div className="bg-[#0d0a14] border border-white/5 rounded-sm overflow-hidden">
        <div className="px-5 py-3 border-b border-white/5 flex items-center justify-between">
          <h3 className="font-display font-bold text-sm">Your last spins</h3>
          <span className="text-[10px] uppercase tracking-wider text-white/40">{history.length}</span>
        </div>
        {history.length === 0 ? (
          <div className="px-5 py-10 text-center text-white/30 text-xs">No spins yet — try your luck!</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[10px] uppercase tracking-wider text-white/40">
                <tr>
                  <th className="text-left px-5 py-2">When</th>
                  <th className="text-left px-5 py-2">Stake</th>
                  <th className="text-left px-5 py-2">Roll</th>
                  <th className="text-right px-5 py-2">Net</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id} className="border-t border-white/5" data-testid={`casino-roll-${h.id}`}>
                    <td className="px-5 py-2 text-white/50 text-xs font-mono">
                      {new Date(h.created_at).toLocaleTimeString()}
                    </td>
                    <td className="px-5 py-2 font-mono text-xs">${Number(h.stake).toFixed(2)}</td>
                    <td className="px-5 py-2 font-mono text-xs">
                      <span
                        className={`px-2 py-0.5 rounded-sm font-bold ${
                          h.multiplier >= 100
                            ? "bg-[#FFD700]/20 text-[#FFD700]"
                            : h.multiplier > 0
                            ? "bg-[#00E5FF]/20 text-[#00E5FF]"
                            : "bg-white/5 text-white/40"
                        }`}
                      >
                        {h.multiplier}x
                      </span>
                    </td>
                    <td
                      className={`px-5 py-2 text-right font-mono text-xs ${
                        h.net > 0 ? "text-emerald-400" : "text-red-400"
                      }`}
                    >
                      {h.net > 0 ? "+" : ""}${Number(h.net).toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}


const CRYPTO_CHOICES = [
  { id: "USDT_TRC20", label: "USDT (TRC-20)", placeholder: "T..." },
  { id: "USDT_ERC20", label: "USDT (ERC-20)", placeholder: "0x..." },
  { id: "BTC", label: "Bitcoin", placeholder: "bc1q... / 1... / 3..." },
];

function WithdrawView({ authedApi, balance, withdrawable, reloadBalance }) {
  const [amount, setAmount] = useState(10);
  const [currency, setCurrency] = useState("USDT_TRC20");
  const [address, setAddress] = useState("");
  const [creating, setCreating] = useState(false);
  const [history, setHistory] = useState([]);

  const loadHistory = async () => {
    try {
      const r = await authedApi().get("/client/withdrawals");
      setHistory(r.data.withdrawals || []);
    } catch {}
  };

  useEffect(() => {
    loadHistory();
    // eslint-disable-next-line
  }, []);

  const chosen = CRYPTO_CHOICES.find((c) => c.id === currency) || CRYPTO_CHOICES[0];

  const submit = async (e) => {
    e.preventDefault();
    const a = Number(amount) || 0;
    if (a < 10) {
      toast.error("Minimum withdrawal is $10");
      return;
    }
    if (a > withdrawable) {
      toast.error(`You can only withdraw winnings ($${withdrawable.toFixed(2)} available).`);
      return;
    }
    if (!address.trim() || address.trim().length < 10) {
      toast.error("Enter a valid wallet address");
      return;
    }
    setCreating(true);
    try {
      await authedApi().post("/client/withdraw", {
        amount: a,
        currency,
        address: address.trim(),
      });
      toast.success("Withdrawal requested — staff will process within 24h.");
      setAmount(10);
      setAddress("");
      reloadBalance();
      loadHistory();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl md:text-4xl font-black tracking-tight flex items-center gap-3">
          <ArrowUpRight className="w-7 h-7 text-emerald-400" /> Withdraw
        </h1>
        <p className="text-white/50 text-sm mt-1">
          Cash out your casino winnings to a crypto wallet. <span className="text-amber-300 font-medium">Only winnings can be withdrawn</span> — deposited funds are for buying services.
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="bg-[#0d0a14] border border-emerald-500/30 rounded-sm p-5 relative overflow-hidden">
          <div className="absolute -top-10 -right-10 w-28 h-28 rounded-full blur-3xl opacity-40 bg-emerald-500" />
          <div className="text-[10px] uppercase tracking-[0.2em] text-white/40 relative">Withdrawable winnings</div>
          <div className="font-display font-black text-3xl md:text-4xl text-emerald-400 mt-2 relative" data-testid="withdraw-withdrawable">
            ${withdrawable.toFixed(2)}
          </div>
          <div className="text-[11px] text-white/50 mt-2 relative">
            Min withdrawal: $10
          </div>
        </div>
        <div className="bg-[#0d0a14] border border-white/5 rounded-sm p-5">
          <div className="text-[10px] uppercase tracking-[0.2em] text-white/40">Total balance</div>
          <div className="font-display font-black text-3xl md:text-4xl text-[#FF007F] mt-2">
            ${balance.toFixed(2)}
          </div>
          <div className="text-[11px] text-white/50 mt-2">
            Non-withdrawable: <span className="text-white/70">${Math.max(0, balance - withdrawable).toFixed(2)}</span>
          </div>
        </div>
      </div>

      <form onSubmit={submit} className="bg-[#0d0a14] border border-white/5 rounded-sm p-5 md:p-6 space-y-4">
        <h2 className="font-display font-bold text-lg">Request withdrawal</h2>

        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">Amount (USD)</Label>
            <Input
              data-testid="withdraw-amount"
              type="number"
              min="10"
              max={Math.floor(withdrawable * 100) / 100 || 10}
              step="1"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="bg-[#1a1525] border-white/10 mt-1 font-mono"
            />
            <div className="flex gap-1 mt-2">
              {[10, 25, 50, 100].map((q) => (
                <button
                  type="button"
                  key={q}
                  onClick={() => setAmount(q)}
                  disabled={q > withdrawable}
                  data-testid={`withdraw-quick-${q}`}
                  className="px-2 py-1 border border-white/10 rounded-sm text-[11px] hover:bg-white/5 disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  ${q}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setAmount(Math.floor(withdrawable * 100) / 100)}
                disabled={withdrawable < 10}
                data-testid="withdraw-max"
                className="px-2 py-1 border border-emerald-500/40 text-emerald-400 rounded-sm text-[11px] hover:bg-emerald-500/10 disabled:opacity-30"
              >
                MAX
              </button>
            </div>
          </div>
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-white/60">Currency</Label>
            <select
              data-testid="withdraw-currency"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              className="w-full bg-[#1a1525] border border-white/10 rounded-sm px-3 py-2 text-sm text-white outline-none mt-1"
            >
              {CRYPTO_CHOICES.map((c) => (
                <option key={c.id} value={c.id}>{c.label}</option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <Label className="text-[11px] uppercase tracking-wider text-white/60">Your {chosen.label} address</Label>
          <Input
            data-testid="withdraw-address"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder={chosen.placeholder}
            className="bg-[#1a1525] border-white/10 mt-1 font-mono text-xs"
            autoComplete="off"
            spellCheck={false}
          />
          <div className="text-[10px] text-white/40 mt-1">
            Double-check the address — crypto sends are irreversible.
          </div>
        </div>

        <button
          type="submit"
          disabled={creating || withdrawable < 10}
          data-testid="withdraw-submit"
          className="w-full py-3 rounded-sm font-bold text-sm inline-flex items-center justify-center gap-2 disabled:opacity-40 bg-gradient-to-r from-emerald-500 to-emerald-400 text-black hover:scale-[1.01] transition"
        >
          {creating ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <ArrowUpRight className="w-4 h-4" />
          )}
          Request withdrawal
        </button>
      </form>

      <div className="bg-[#0d0a14] border border-white/5 rounded-sm overflow-hidden">
        <div className="px-5 py-3 border-b border-white/5 flex items-center justify-between">
          <h3 className="font-display font-bold text-sm">Past withdrawals</h3>
          <span className="text-[10px] uppercase tracking-wider text-white/40">{history.length}</span>
        </div>
        {history.length === 0 ? (
          <div className="px-5 py-10 text-center text-white/30 text-xs">No withdrawals yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[10px] uppercase tracking-wider text-white/40">
                <tr>
                  <th className="text-left px-5 py-2">Date</th>
                  <th className="text-left px-5 py-2">Amount</th>
                  <th className="text-left px-5 py-2">Currency</th>
                  <th className="text-left px-5 py-2">Address</th>
                  <th className="text-left px-5 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {history.map((w) => (
                  <tr key={w.id} className="border-t border-white/5" data-testid={`withdraw-row-${w.id}`}>
                    <td className="px-5 py-2 text-white/60 text-xs font-mono">
                      {new Date(w.created_at).toLocaleString()}
                    </td>
                    <td className="px-5 py-2 font-mono text-emerald-400">
                      ${Math.abs(Number(w.amount)).toFixed(2)}
                    </td>
                    <td className="px-5 py-2 text-xs text-white/70">{w.currency}</td>
                    <td className="px-5 py-2 font-mono text-[10px] text-white/40 max-w-[180px] truncate" title={w.address}>
                      {w.address}
                    </td>
                    <td className="px-5 py-2">
                      <StatusPill status={w.status} />
                      {w.tx_hash && (
                        <div className="text-[10px] text-white/40 font-mono mt-1 truncate max-w-[160px]" title={w.tx_hash}>
                          {w.tx_hash}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

