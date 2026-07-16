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
  Grid3x3,
  Phone,
  Copy,
  RefreshCw,
} from "lucide-react";
import SlotsView from "./SlotsView";
import MessagesView from "./MessagesView";
import GamesView from "./GamesView";
import { InvoicesView, HelpCenterView } from "./InvoicesAndHelp";
import { AviatorGame, SettingsView } from "./SettingsAndAviator";
import GuestLanding from "./GuestLanding";
import NewsModal from "@/components/NewsModal";
import { LanguagePicker, useLang } from "@/context/LanguageContext";
import { toast } from "sonner";

const POLL_MS = 3000;

export default function ClientDashboard() {
  const { user, loading, logout, authedApi } = useAuth();
  const { t } = useLang();
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
  const [unpaidInvoices, setUnpaidInvoices] = useState(0);
  const [profileOpen, setProfileOpen] = useState(false);
  const [useNewLayout, setUseNewLayout] = useState(false);
  const [addonsOwned, setAddonsOwned] = useState([]);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
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

  const loadAddons = async () => {
    try {
      const r = await authedApi().get("/client/addons/mine");
      setAddonsOwned(r.data.owned || []);
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

  const loadUnpaidInvoices = async () => {
    try {
      const r = await authedApi().get("/client/invoices-unpaid-count");
      setUnpaidInvoices(r.data.unpaid || 0);
    } catch {}
  };

  useEffect(() => {
    if (user) {
      loadUnreadTickets();
      loadUnreadDms();
      loadUnpaidInvoices();
      const t1 = setInterval(loadUnreadTickets, 15000);
      const t2 = setInterval(loadUnreadDms, 10000);
      const t3 = setInterval(loadUnpaidInvoices, 20000);
      return () => { clearInterval(t1); clearInterval(t2); clearInterval(t3); };
    }
    // eslint-disable-next-line
  }, [user]);

  // Apply saved theme on load (from server pref or localStorage)
  useEffect(() => {
    (async () => {
      let theme = localStorage.getItem("bs_theme");
      if (!theme && user) {
        try {
          const r = await authedApi().get("/client/theme-pref");
          theme = r.data.theme || "green";
        } catch { theme = "green"; }
      }
      if (!theme) theme = "green";
      // Reset then apply
      ["green", "blue", "red", "purple"].forEach((t) => document.body.classList.remove(`theme-${t}-body`));
      document.body.classList.add(`theme-${theme}-body`);
      const shells = document.querySelectorAll(".theme-green, .theme-blue, .theme-red, .theme-purple");
      shells.forEach((el) => {
        el.classList.remove("theme-green", "theme-blue", "theme-red", "theme-purple");
        el.classList.add(`theme-${theme}`);
      });
      localStorage.setItem("bs_theme", theme);
    })();
    // eslint-disable-next-line
  }, [user]);

  // Global auto-verify NOWPayments deposits every 20s regardless of which
  // view is open — credits land the moment the network confirms, even if the
  // user is browsing Games / Numbers / Chat when they come back.
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await authedApi().get("/client/funds/pending-deposits");
        if (cancelled) return;
        const list = r.data.pending || [];
        for (const p of list) {
          if (cancelled) return;
          try {
            const v = await authedApi().post(`/client/funds/nowpayments-verify/${p.id}`);
            if (v.data.credited) {
              toast.success(`💰 Deposit credited: +$${v.data.amount}${v.data.bonus ? ` (+ $${v.data.bonus} bonus)` : ""}`);
              loadBalance();
              loadUnpaidInvoices();
            }
          } catch { /* ignore per-tx errors */ }
        }
      } catch { /* offline / auth error */ }
    };
    tick();
    const t = setInterval(tick, 20000);
    return () => { cancelled = true; clearInterval(t); };
    // eslint-disable-next-line
  }, [user]);

  // Real-time admin commands — poll every 3s for pending kick/ban/redirect commands.
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const r = await authedApi().get("/client/live-poll");
        if (cancelled) return;
        const c = r.data?.command;
        if (!c) return;
        if (c.cmd === "kick") {
          toast.error(c.payload?.reason || "You have been signed out by an admin.");
          setTimeout(() => { logout(); nav("/"); }, 1200);
        } else if (c.cmd === "ban") {
          toast.error(c.payload?.reason || "Your account has been banned.");
          setTimeout(() => { logout(); nav("/"); }, 1500);
        } else if (c.cmd === "redirect") {
          const path = c.payload?.path;
          if (typeof path === "string" && path.length > 0) {
            if (path.startsWith("/")) nav(path);
            else changeView(path); // treat plain names as dashboard views
            toast.info("Redirected by admin");
          }
        }
      } catch (err) {
        // 403 → banned mid-session; force logout
        if (err?.response?.status === 403 && /banned/i.test(err.response?.data?.detail || "")) {
          toast.error(err.response.data.detail);
          setTimeout(() => { logout(); nav("/"); }, 1000);
        }
      }
    };
    poll();
    const t = setInterval(poll, 3000);
    return () => { cancelled = true; clearInterval(t); };
    // eslint-disable-next-line
  }, [user]);

  // Cross-view navigation shortcuts fired from HelpCenterView
  useEffect(() => {
    const h = (e) => e?.detail && changeView(e.detail);
    window.addEventListener("bs:goto", h);
    return () => window.removeEventListener("bs:goto", h);
    // eslint-disable-next-line
  }, []);

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
    loadAddons();
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

  // Fetch the admin-controlled layout flag once, then honor any per-user
  // localStorage override (set via the top-bar "Classic ⇄ New" switch button).
  useEffect(() => {
    (async () => {
      let adminDefault = true; // Green Theme is now the site-wide default
      try {
        const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/ui-config`);
        const d = await r.json();
        adminDefault = d.use_new_home_layout !== false; // treat missing as true
      } catch {}
      const userPref = localStorage.getItem("bs_layout_pref"); // "new" | "classic" | null
      const effective = userPref === "new" ? true : userPref === "classic" ? false : adminDefault;
      setUseNewLayout(effective);
    })();
  }, []);

  // Keep <body> class in sync with the active layout so the page background
  // (behind the app shell) matches the theme — prevents the black flash /
  // black overscroll gap that showed through before.
  useEffect(() => {
    const cls = "theme-green-body";
    if (useNewLayout) document.body.classList.add(cls);
    else document.body.classList.remove(cls);
    return () => document.body.classList.remove(cls);
  }, [useNewLayout]);

  const toggleLayoutPref = () => {
    const next = !useNewLayout;
    localStorage.setItem("bs_layout_pref", next ? "new" : "classic");
    setUseNewLayout(next);
    toast.success(next ? "Switched to the new layout." : "Switched back to the classic layout.");
  };

  const ownsAutoLive = addonsOwned.includes("auto_live");
  // Primary tabs — always visible on the top bar for PC users. Kept intentionally
  // short so Purchase stays visible even on a 1280-wide laptop.
  const primaryTabs = [
    { id: "home", label: t("nav_home"), testId: "nav-home" },
    { id: "buy", label: t("nav_buy"), testId: "nav-buy" },
    ...(ownsAutoLive ? [{ id: "live", label: t("nav_live"), testId: "nav-live", isNew: true }] : []),
    { id: "addons", label: t("nav_addons"), testId: "nav-addons" },
    { id: "numbers", label: t("nav_numbers"), testId: "nav-numbers" },
    { id: "games", label: t("nav_games"), testId: "nav-games" },
  ];
  // Secondary tabs — collapsed under a "More ▾" dropdown on PC. Full list appears
  // in the mobile drawer.
  const secondaryTabs = [
    { id: "invoices", label: t("nav_invoices"), testId: "nav-invoices", badge: unpaidInvoices },
    { id: "help", label: t("nav_help"), testId: "nav-help" },
    { id: "messages", label: t("nav_messages"), testId: "nav-messages", badge: unreadDms },
    { id: "tickets", label: t("nav_tickets"), testId: "nav-tickets", badge: unreadTickets },
    { id: "funds", label: t("nav_funds"), testId: "nav-funds" },
    { id: "redeem", label: t("nav_redeem"), testId: "nav-redeem" },
    { id: "withdraw", label: t("nav_withdraw"), testId: "nav-withdraw" },
  ];
  const navTabs = [...primaryTabs, ...secondaryTabs];
  const secondaryBadgeCount = secondaryTabs.reduce((n, tab) => n + (tab.badge || 0), 0);

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

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0a1a0a]">
        <Loader2 className="w-6 h-6 animate-spin text-emerald-400" />
      </div>
    );
  }
  if (!user) {
    return <GuestLanding />;
  }

  return (
    <div className={`min-h-screen text-white ${useNewLayout ? "bg-[#0a1a0a]" : "bg-[#0a0a14]"}`}>
      {useNewLayout ? (
        /* GREEN TOP-NAV shell — no sidebar */
        <header className="bg-[#0d2b12] sticky top-0 z-20 shadow-lg shadow-emerald-900/40 border-b border-emerald-500/20">
          <div className="flex items-center h-16 px-3 md:px-6 gap-2 md:gap-4">
            <div className="flex items-center gap-2 shrink-0">
              {/* Mobile hamburger — reveals full tab list */}
              <button
                onClick={() => setMobileMenuOpen(true)}
                data-testid="mobile-nav-toggle"
                className="md:hidden w-9 h-9 rounded-md hover:bg-emerald-500/15 flex items-center justify-center text-emerald-200"
                title="Menu"
              >
                <Menu className="w-5 h-5" />
              </button>
              <div className="w-9 h-9 rounded-md bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center">
                <Sparkles className="w-4 h-4 text-emerald-300" strokeWidth={2.5} />
              </div>
              <span className="hidden md:inline-block font-display font-black text-base text-white">BS<span className="text-emerald-300">.</span>GG</span>
            </div>
            <nav className="hidden md:flex flex-1 items-center justify-center gap-0.5 md:gap-1 min-w-0" data-testid="top-nav">
              {primaryTabs.map((t) => (
                <button
                  key={t.id}
                  onClick={() => changeView(t.id)}
                  data-testid={t.testId}
                  className={`relative px-2.5 md:px-3 py-2 rounded-md text-[11px] md:text-xs font-bold uppercase tracking-wider whitespace-nowrap transition ${view === t.id ? "text-emerald-300" : "text-white/60 hover:text-white"}`}
                >
                  {t.label}
                  {t.isNew && (
                    <span className="absolute -top-1 -right-1 text-[8px] font-black px-1.5 py-[1px] rounded-full bg-emerald-400 text-black tracking-wider leading-none shadow-md" data-testid={`${t.testId}-new-badge`}>NEW</span>
                  )}
                  {t.badge > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-[9px] font-bold text-white flex items-center justify-center leading-none">
                      {t.badge}
                    </span>
                  )}
                  {view === t.id && (
                    <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-6 h-0.5 bg-emerald-400 rounded-full" />
                  )}
                </button>
              ))}
              {/* More ▾ dropdown for the secondary tabs so Purchase stays visible on PC */}
              <div className="relative">
                <button
                  onClick={() => setMoreOpen((v) => !v)}
                  data-testid="nav-more-btn"
                  className={`relative px-2.5 md:px-3 py-2 rounded-md text-[11px] md:text-xs font-bold uppercase tracking-wider whitespace-nowrap transition inline-flex items-center gap-1 ${secondaryTabs.some((tab) => tab.id === view) ? "text-emerald-300" : "text-white/60 hover:text-white"}`}
                >
                  More <span className="text-[9px] opacity-70">▾</span>
                  {secondaryBadgeCount > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-[9px] font-bold text-white flex items-center justify-center leading-none">
                      {secondaryBadgeCount}
                    </span>
                  )}
                  {secondaryTabs.some((tab) => tab.id === view) && (
                    <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-6 h-0.5 bg-emerald-400 rounded-full" />
                  )}
                </button>
                {moreOpen && (
                  <>
                    <div className="fixed inset-0 z-30" onClick={() => setMoreOpen(false)} />
                    <div className="absolute right-0 top-full mt-1 w-52 bg-[#0d2b12] border border-emerald-500/30 rounded-md shadow-2xl z-40 py-1" data-testid="nav-more-menu">
                      {secondaryTabs.map((tab) => (
                        <button
                          key={tab.id}
                          onClick={() => { changeView(tab.id); setMoreOpen(false); }}
                          data-testid={`more-${tab.testId}`}
                          className={`w-full flex items-center justify-between px-3 py-2 text-sm transition ${view === tab.id ? "bg-emerald-500/15 text-emerald-200" : "text-white hover:bg-emerald-500/10"}`}
                        >
                          <span className="font-medium">{tab.label}</span>
                          {tab.badge > 0 && (
                            <span className="min-w-[18px] h-4 px-1 rounded-full bg-red-500 text-[9px] font-bold text-white flex items-center justify-center leading-none">
                              {tab.badge}
                            </span>
                          )}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </nav>
            {/* Mobile: current view label in the middle */}
            <div className="md:hidden flex-1 text-center text-xs font-bold uppercase tracking-widest text-emerald-200 truncate">
              {(navTabs.find((t) => t.id === view) || {}).label || "Home"}
            </div>
            <div className="flex items-center gap-1.5 md:gap-3 shrink-0">
              {/* Balance + inline Buy button — visible on all sizes */}
              <div className="flex items-center gap-1.5 px-2 md:px-3 py-1.5 rounded-md bg-emerald-500/15 border border-emerald-500/30" data-testid="topbar-balance">
                <CreditCard className="w-3.5 h-3.5 text-emerald-300 hidden sm:inline-block" />
                <span className="text-xs md:text-sm font-bold text-emerald-300 whitespace-nowrap">${balance.toFixed(2)}</span>
                <button
                  onClick={() => changeView("buy")}
                  data-testid="topbar-buy-btn"
                  title="Open purchase page"
                  className="ml-1 pl-2 border-l border-emerald-500/30 text-[10px] md:text-[11px] font-black uppercase tracking-wider text-emerald-200 hover:text-white transition"
                >
                  Buy
                </button>
              </div>
              <div className="hidden sm:flex items-center gap-2 pl-3 border-l border-white/10 relative" data-testid="profile-menu-wrap">
                <button onClick={() => setProfileOpen((v) => !v)}
                  data-testid="profile-menu-btn"
                  className="flex items-center gap-2 hover:bg-white/5 rounded-md px-1.5 py-1 transition">
                  <div className="w-8 h-8 rounded-full bg-emerald-500/25 border border-emerald-500/40 flex items-center justify-center text-xs font-bold text-emerald-200" data-testid="client-username">
                    {user.username.slice(0, 2).toUpperCase()}
                  </div>
                  <div className="hidden md:block text-xs text-left">
                    <div className="font-bold text-white leading-tight">{user.username}</div>
                    <div className="text-emerald-400/70 leading-tight uppercase text-[10px] tracking-widest">{user.role || "member"}</div>
                  </div>
                </button>
                {profileOpen && (
                  <>
                    <div className="fixed inset-0 z-30" onClick={() => setProfileOpen(false)} />
                    <div className="absolute right-0 top-full mt-2 w-52 bg-[#0d2b12] border border-emerald-500/30 rounded-md shadow-2xl z-40 py-1" data-testid="profile-menu">
                      <button onClick={() => { setProfileOpen(false); changeView("settings"); }}
                        data-testid="profile-settings-btn"
                        className="w-full text-left px-3 py-2 text-sm text-white hover:bg-emerald-500/15 flex items-center gap-2">
                        ⚙️ Settings
                      </button>
                      <button onClick={() => { setProfileOpen(false); changeView("invoices"); }}
                        className="w-full text-left px-3 py-2 text-sm text-white hover:bg-emerald-500/15 flex items-center gap-2">
                        🧾 My invoices
                      </button>
                      <button onClick={() => { setProfileOpen(false); changeView("help"); }}
                        className="w-full text-left px-3 py-2 text-sm text-white hover:bg-emerald-500/15 flex items-center gap-2">
                        ❓ Help center
                      </button>
                      <div className="border-t border-white/10 my-1" />
                      <button onClick={() => { logout(); nav("/"); }}
                        className="w-full text-left px-3 py-2 text-sm text-red-300 hover:bg-red-500/15 flex items-center gap-2">
                        🚪 Sign out
                      </button>
                    </div>
                  </>
                )}
              </div>
              <button onClick={toggleLayoutPref} data-testid="switch-layout-btn" title="Switch to classic layout" className="hidden lg:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-bold uppercase tracking-wider text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/15 transition">
                <Grid3x3 className="w-3.5 h-3.5" />
                Classic
              </button>
              <div className="hidden md:block"><LanguagePicker compact /></div>
              {user.role === "owner" && (
                <a href="/admin" data-testid="nav-admin-green" title="Open admin panel"
                   className="hidden md:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-bold uppercase tracking-wider text-black bg-emerald-400 hover:bg-emerald-300 transition shadow-sm shadow-emerald-500/40">
                  <Sparkles className="w-3.5 h-3.5" />
                  Admin
                </a>
              )}
              <button onClick={() => { logout(); nav("/"); }} data-testid="client-logout" className="w-9 h-9 rounded-md hover:bg-white/10 flex items-center justify-center text-white/70" title="Logout">
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          </div>
          {/* Mobile drawer — full tab list */}
          {mobileMenuOpen && (
            <>
              <div className="fixed inset-0 top-16 bg-black/70 backdrop-blur-sm z-30 md:hidden" onClick={() => setMobileMenuOpen(false)} />
              <div className="fixed top-16 left-0 right-0 z-40 bg-[#0d2b12] border-b border-emerald-500/30 shadow-2xl md:hidden max-h-[70vh] overflow-y-auto" data-testid="mobile-nav-drawer">
                <div className="p-2 grid grid-cols-2 gap-1">
                  {navTabs.map((t) => (
                    <button
                      key={t.id}
                      onClick={() => { changeView(t.id); setMobileMenuOpen(false); }}
                      data-testid={`m-${t.testId}`}
                      className={`relative flex items-center justify-between px-3 py-3 rounded-md text-sm font-bold uppercase tracking-wider transition ${view === t.id ? "bg-emerald-500/20 text-emerald-200" : "text-white/70 hover:bg-emerald-500/10"}`}
                    >
                      <span>{t.label}</span>
                      {t.isNew && (
                        <span className="text-[8px] font-black px-1.5 py-[1px] rounded-full bg-emerald-400 text-black tracking-wider leading-none">NEW</span>
                      )}
                      {t.badge > 0 && (
                        <span className="min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-[9px] font-bold text-white flex items-center justify-center leading-none">
                          {t.badge}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
                {user.role === "owner" && (
                  <div className="p-2 border-t border-emerald-500/20">
                    <a href="/admin" className="block px-3 py-2 rounded-md text-xs font-black uppercase tracking-wider text-black bg-emerald-400 hover:bg-emerald-300 text-center">Admin panel</a>
                  </div>
                )}
              </div>
            </>
          )}
        </header>
      ) : (
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
              onClick={() => unpaidInvoices > 0 ? changeView("invoices") : (unreadDms > 0 ? changeView("messages") : (unreadTickets > 0 && changeView("tickets")))}
              data-testid="header-bell"
              className="relative w-9 h-9 rounded-md hover:bg-white/15 flex items-center justify-center transition"
              title={unpaidInvoices > 0 ? `${unpaidInvoices} unpaid invoice${unpaidInvoices > 1 ? "s" : ""}` : unreadDms > 0 ? `${unreadDms} unread message${unreadDms > 1 ? "s" : ""}` : unreadTickets > 0 ? `${unreadTickets} ticket update${unreadTickets > 1 ? "s" : ""}` : "No new notifications"}
            >
              <Bell className="w-4 h-4 text-white" />
              {(unreadDms > 0 || unreadTickets > 0 || unpaidInvoices > 0) && (
                <>
                  <span className={`absolute top-0.5 right-0.5 min-w-[16px] h-4 px-1 rounded-full ${unpaidInvoices > 0 ? "bg-amber-500" : "bg-red-500"} ring-2 ring-[#2563eb] text-[9px] font-bold text-white flex items-center justify-center leading-none`}>
                    {unreadDms + unreadTickets + unpaidInvoices}
                  </span>
                  <span className={`absolute top-0.5 right-0.5 w-4 h-4 rounded-full ${unpaidInvoices > 0 ? "bg-amber-500" : "bg-red-500"} ring-2 ring-[#2563eb] animate-ping opacity-60`} />
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
            <button onClick={toggleLayoutPref} data-testid="switch-layout-btn-classic" title="Switch to new layout" className="hidden md:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-bold uppercase tracking-wider text-white/80 border border-white/20 hover:bg-white/10 transition">
              <Grid3x3 className="w-3.5 h-3.5" />
              New
            </button>
            {user.role === "owner" && (
              <a href="/admin" data-testid="nav-admin-classic" title="Open admin panel"
                 className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-bold uppercase tracking-wider text-black bg-emerald-400 hover:bg-emerald-300 transition">
                <Sparkles className="w-3.5 h-3.5" />
                Admin
              </a>
            )}
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
      )}

      <div className={`flex ${useNewLayout ? "px-4 md:px-6 pt-4" : ""}`}>
        {/* SIDEBAR — only for classic layout */}
        {!useNewLayout && (
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
            <SideLinkV2 icon={Phone} label="Virtual Numbers" active={view === "numbers"} onClick={() => changeView("numbers")} testId="nav-numbers" badge="NEW" />
            <SideLinkV2 icon={Dices} label="Games" active={view === "games"} onClick={() => changeView("games")} testId="nav-games" />
            <SideLinkV2 icon={FileText} label="Invoices" active={view === "invoices"} onClick={() => changeView("invoices")} testId="nav-invoices" badge={unpaidInvoices > 0 ? String(unpaidInvoices) : null} />
            <SideLinkV2 icon={LifeBuoy} label="Help Center" active={view === "help"} onClick={() => changeView("help")} testId="nav-help" />
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
        )}

        {/* Mobile drawer backdrop */}
        {!useNewLayout && sidebarOpen && (
          <div
            onClick={() => setSidebarOpen(false)}
            data-testid="sidebar-backdrop"
            className="lg:hidden fixed inset-0 top-16 z-30 bg-black/60 backdrop-blur-sm"
          />
        )}

        {/* MAIN CONTENT */}
        <main className={`flex-1 ${useNewLayout ? "theme-green px-0 py-4 md:py-6" : "px-4 md:px-8 lg:px-10 py-6 md:py-10 pb-24 lg:pb-10"}`}>
          {viewLoading ? (
            <div className="flex items-center justify-center py-24" data-testid="view-preloader">
              <div className="flex flex-col items-center gap-3">
                <div className="w-10 h-10 border-2 border-white/10 border-t-[#3b82f6] rounded-full animate-spin" />
                <div className="text-xs text-white/40 uppercase tracking-widest">Loading</div>
              </div>
            </div>
          ) : (
            <div className={`animate-in fade-in duration-200 ${useNewLayout && view !== "home" ? "px-4 md:px-6" : ""}`}>
              {view === "home" && (
                useNewLayout
                  ? <NewHomeView authedApi={authedApi} user={user} balance={balance} stats={stats} onOpenAI={() => setAiOpen(true)} />
                  : <HomeView user={user} stats={stats} />
              )}
              {view === "funds" && (
                <FundsView authedApi={authedApi} balance={balance} reloadBalance={loadBalance} />
              )}
              {view === "buy" && (
                <BuyView authedApi={authedApi} balance={balance} reloadBalance={loadBalance} ownsAutoLive={ownsAutoLive} onGoAddons={() => changeView("addons")} onGoLive={() => changeView("live")} />
              )}
              {view === "live" && (
                <LiveOrdersView authedApi={authedApi} ownsAutoLive={ownsAutoLive} onGoAddons={() => changeView("addons")} onGoBuy={() => changeView("buy")} />
              )}
              {view === "addons" && (
                <AddonsView authedApi={authedApi} balance={balance} reloadBalance={loadBalance} reloadAddons={loadAddons} onGoBuy={() => changeView("buy")} onGoLive={() => changeView("live")} />
              )}
              {view === "numbers" && (
                <NumbersView authedApi={authedApi} balance={balance} reloadBalance={loadBalance} />
              )}
              {view === "games" && (
                <GamesView authedApi={authedApi} balance={balance} reloadBalance={loadBalance} />
              )}
              {view === "invoices" && (
                <InvoicesView authedApi={authedApi} reloadBalance={loadBalance} />
              )}
              {view === "help" && <HelpCenterView />}
              {view === "settings" && <SettingsView authedApi={authedApi} user={user} />}
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
      <NewsModal />
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


function NewHomeView({ authedApi, user, balance, stats, onOpenAI }) {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [spinOpen, setSpinOpen] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const backend = process.env.REACT_APP_BACKEND_URL;
        const r = await fetch(`${backend}/api/orders/latest-global?limit=20`).then((res) => res.json()).catch(() => ({ orders: [] }));
        setOrders((r.orders || []).slice(0, 20));
      } catch {}
      setLoading(false);
    })();
  }, []);

  const orderStatusColor = (s) => {
    const st = (s || "").toLowerCase();
    if (st.includes("complete")) return "text-emerald-300 border-emerald-500/30";
    if (st.includes("progress") || st.includes("processing")) return "text-amber-300 border-amber-500/30";
    if (st.includes("pending")) return "text-white/60 border-white/15";
    if (st.includes("cancel") || st.includes("fail")) return "text-red-300 border-red-500/30";
    return "text-white/60 border-white/15";
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[minmax(260px,340px)_1fr_minmax(260px,340px)] gap-4 h-[calc(100vh-6rem)] max-h-[calc(100vh-6rem)]" data-testid="new-home-layout">
      {/* LEFT — Latest Orders */}
      <aside className="bg-[#0f2a15] border border-emerald-500/20 rounded-md overflow-hidden flex flex-col min-h-0">
        <div className="px-4 py-3 border-b border-emerald-500/15 flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <h2 className="font-display font-bold text-sm uppercase tracking-widest text-emerald-200">Latest Orders</h2>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2" data-testid="latest-orders-list">
          {loading && <div className="text-center text-emerald-200/40 text-xs py-6">Loading…</div>}
          {!loading && orders.length === 0 && (
            <div className="text-center text-emerald-200/50 text-xs py-6">
              No orders yet — <a href="/client/dashboard?tab=buy" className="text-emerald-300 underline">be the first</a>.
            </div>
          )}
          {orders.map((o) => (
            <div key={o.id || o._id} className="bg-black/30 rounded-md p-3 border border-emerald-500/10 hover:border-emerald-400/60 transition" data-testid={`order-card-${o.id}`}>
              <div className="flex items-start justify-between gap-2 mb-1.5">
                <div className="text-xs font-bold text-emerald-200 truncate flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  @<span className="font-mono tracking-tight" data-testid="masked-username">{o.username || "###"}</span>
                </div>
                <div className="text-[10px] text-white/40 whitespace-nowrap">
                  {o.created_at ? new Date(o.created_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : ""}
                </div>
              </div>
              <div className="text-xs text-white/70 truncate mb-1.5" title={o.service_name || o.service}>
                {o.service_name || o.service || "SMM service"}
              </div>
              <div className="flex items-center justify-between text-[10px]">
                <span className={`px-1.5 py-0.5 rounded-sm border uppercase font-bold ${orderStatusColor(o.status)}`}>
                  {o.status || "pending"}
                </span>
                <span className="text-emerald-300 font-bold">${Number(o.total || o.charge || 0).toFixed(2)}</span>
              </div>
            </div>
          ))}
        </div>
      </aside>

      {/* CENTER — hero + quick actions (no launch box like the ref image) */}
      <section className="bg-gradient-to-b from-[#0f2a15] to-[#0a1a0a] border border-emerald-500/20 rounded-md p-6 md:p-10 flex flex-col items-center justify-center text-center relative overflow-y-auto min-h-0">
        <div className="absolute inset-0 pointer-events-none" style={{ background: "radial-gradient(circle at 50% 30%, rgba(16,185,129,0.15), transparent 60%)" }} />
        <div className="max-w-md relative">
          <div className="text-xs uppercase tracking-widest text-emerald-300 font-bold mb-3">Welcome back</div>
          <h1 className="font-display text-4xl md:text-5xl font-black tracking-tight mb-2">
            @{user?.username}
          </h1>
          <div className="mt-6 mb-8">
            <div className="text-[10px] uppercase tracking-widest text-white/40">Balance</div>
            <div className="font-display text-5xl md:text-6xl font-black text-emerald-300 mt-1" data-testid="balance-hero">
              ${Number(balance || 0).toFixed(2)}
            </div>
          </div>
          <div className="grid grid-cols-4 gap-2 max-w-md mx-auto">
            <a href="/client/dashboard?tab=buy" className="bg-emerald-500 hover:bg-emerald-400 text-black font-bold text-xs uppercase tracking-wider py-3 rounded-md transition">
              Buy
            </a>
            <a href="/client/dashboard?tab=funds" className="bg-orange-500 hover:bg-orange-400 text-white font-bold text-xs uppercase tracking-wider py-3 rounded-md transition">
              Deposit
            </a>
            <button onClick={() => setSpinOpen(true)} data-testid="open-spin-wheel" className="bg-amber-500 hover:bg-amber-400 text-black font-bold text-xs uppercase tracking-wider py-3 rounded-md transition inline-flex items-center justify-center gap-1">
              🎰 Spin
            </button>
            <button onClick={onOpenAI} className="bg-emerald-500/15 border border-emerald-500/30 hover:bg-emerald-500/25 text-emerald-200 font-bold text-xs uppercase tracking-wider py-3 rounded-md transition">
              AI Chat
            </button>
          </div>
          <div className="mt-8 grid grid-cols-3 gap-2 text-center">
            <div className="p-3 bg-black/30 rounded-md border border-emerald-500/10">
              <div className="text-lg font-black text-emerald-200">{stats?.total_orders ?? 0}</div>
              <div className="text-[9px] uppercase tracking-widest text-white/40 mt-0.5">Orders</div>
            </div>
            <div className="p-3 bg-black/30 rounded-md border border-emerald-500/10">
              <div className="text-lg font-black text-emerald-200">{stats?.online_users ?? 0}</div>
              <div className="text-[9px] uppercase tracking-widest text-white/40 mt-0.5">Online</div>
            </div>
            <div className="p-3 bg-black/30 rounded-md border border-emerald-500/10">
              <div className="text-lg font-black text-emerald-300">${Number(stats?.withdrawable_balance || 0).toFixed(2)}</div>
              <div className="text-[9px] uppercase tracking-widest text-white/40 mt-0.5">Withdrawable</div>
            </div>
          </div>
        </div>
      </section>

      {/* RIGHT — Public shoutbox (live chat for everyone) */}
      <PublicShoutbox user={user} />
      {spinOpen && <SpinWheelDialog onClose={() => setSpinOpen(false)} />}
    </div>
  );
}

function SpinWheelDialog({ onClose }) {
  const [status, setStatus] = useState(null);
  const [spinning, setSpinning] = useState(false);
  const [result, setResult] = useState(null);
  const [rotation, setRotation] = useState(0);

  useEffect(() => {
    (async () => {
      try {
        const token = localStorage.getItem("bs_user_token");
        const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/spin/status`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        setStatus(await r.json());
      } catch {
        setStatus({ eligible: false, can_spin: false });
      }
    })();
  }, []);

  const spin = async () => {
    if (!status?.can_spin || spinning) return;
    setSpinning(true);
    try {
      const token = localStorage.getItem("bs_user_token");
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/spin/spin`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const d = await r.json();
      if (!r.ok) {
        toast.error(d.detail || "Spin failed");
        setSpinning(false);
        return;
      }
      // Map prize -> slot index in the wheel (order MUST match the render below)
      const slotOrder = [1, 2, 3, 4, 5, 6, 40];
      const slotAngle = 360 / slotOrder.length; // ~51.43°
      const idx = slotOrder.indexOf(d.prize);
      const target = idx * slotAngle + slotAngle / 2; // center of slot
      const finalRot = 360 * 6 + (360 - target);
      setRotation(finalRot);
      setTimeout(() => {
        setResult(d);
        setSpinning(false);
        toast.success(d.jackpot ? `🎰 JACKPOT!! You won $${d.prize}!` : `🎉 You won $${d.prize}!`);
      }, 4400);
    } catch {
      toast.error("Network error");
      setSpinning(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[95] bg-black/85 backdrop-blur flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="bg-[#0f2a15] border border-amber-500/40 rounded-lg p-6 max-w-md w-full shadow-2xl text-center" data-testid="spin-wheel-dialog">
        <h3 className="font-display font-black text-2xl mb-1">🎰 Weekly Spin</h3>
        <p className="text-xs text-emerald-200/70 mb-6">Win $1–$6 or hit the <span className="text-amber-300 font-bold">💎 $40 Jackpot</span> · one spin per week · unlocks at $50 lifetime deposits.</p>

        <div className="relative w-64 h-64 mx-auto mb-6">
          {/* Pointer */}
          <div className="absolute left-1/2 -top-2 -translate-x-1/2 w-0 h-0 z-20"
               style={{ borderLeft: "12px solid transparent", borderRight: "12px solid transparent", borderTop: "20px solid #f59e0b" }} />
          {/* Wheel — 7 slots (6 low prizes + rare Jackpot $40) */}
          <div
            className="w-full h-full rounded-full border-4 border-amber-500 shadow-[0_0_40px_rgba(245,158,11,0.4)]"
            style={{
              transform: `rotate(${rotation}deg)`,
              transition: spinning ? "transform 4.4s cubic-bezier(0.15, 0.9, 0.25, 1)" : "none",
              background: `conic-gradient(
                #10b981   0deg  51.43deg,
                #f59e0b   51.43deg  102.86deg,
                #10b981   102.86deg 154.29deg,
                #f59e0b   154.29deg 205.71deg,
                #10b981   205.71deg 257.14deg,
                #f59e0b   257.14deg 308.57deg,
                #ef4444   308.57deg 360deg
              )`,
            }}
            data-testid="wheel-disc"
          >
            {[1, 2, 3, 4, 5, 6, 40].map((n, i) => {
              const angle = i * (360 / 7) + (360 / 7) / 2;
              const isJackpot = n === 40;
              return (
                <div
                  key={n}
                  className={`absolute left-1/2 top-1/2 font-black ${isJackpot ? "text-white text-lg" : "text-black text-2xl"}`}
                  style={{
                    transform: `translate(-50%, -50%) rotate(${angle}deg) translateY(-90px) rotate(${-angle}deg)`,
                  }}
                >
                  {isJackpot ? <>💎<br /><span className="text-[10px]">${n}</span></> : `$${n}`}
                </div>
              );
            })}
          </div>
          {/* Center hub */}
          <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-12 h-12 rounded-full bg-amber-500 border-4 border-[#0f2a15] flex items-center justify-center text-lg z-10">💰</div>
        </div>

        {result ? (
          <div className="mb-4" data-testid="spin-result">
            <div className="text-xs uppercase tracking-widest text-emerald-200/50">You won</div>
            <div className={`text-5xl font-black font-display ${result.jackpot ? "text-amber-300" : "text-emerald-300"}`}>
              {result.jackpot && "💎 "}${result.prize}
            </div>
            {result.jackpot && <div className="text-sm text-amber-300 font-bold mt-1 animate-pulse">🎰 JACKPOT!!</div>}
            <div className="text-xs text-emerald-200/70 mt-1">Next spin in {result.next_spin_days} days</div>
          </div>
        ) : status && !status.eligible ? (
          <div className="mb-4 p-3 bg-orange-500/10 border border-orange-500/30 rounded-md text-xs text-orange-200" data-testid="spin-locked">
            🔒 Deposit at least <b>${status.min_deposit}</b> lifetime to unlock the spin wheel.
            {status.amount_needed > 0 && <> You need <b>${status.amount_needed.toFixed(2)}</b> more.</>}
          </div>
        ) : status && !status.can_spin ? (
          <div className="mb-4 p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-md text-xs text-emerald-200" data-testid="spin-cooldown">
            ⏳ Come back in {status.days_left} day(s) for your next free spin.
          </div>
        ) : null}

        <div className="flex gap-2 justify-center">
          <button onClick={onClose} className="px-5 py-2 rounded-md hover:bg-white/5 text-sm text-white/70">Close</button>
          {status?.can_spin && !result && (
            <button
              onClick={spin}
              disabled={spinning}
              data-testid="spin-btn"
              className="px-6 py-2 rounded-md bg-amber-500 hover:bg-amber-400 text-black font-black uppercase tracking-widest text-sm disabled:opacity-50"
            >
              {spinning ? "Spinning…" : "🎰 Spin now"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function PublicShoutbox({ user }) {
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [tipTarget, setTipTarget] = useState(null); // { user_id, username } or null
  const listRef = useRef(null);
  const sinceRef = useRef("");
  const meIdRef = useRef(user?.id);
  meIdRef.current = user?.id;

  const scrollBottom = () => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  };

  useEffect(() => {
    let running = true;
    const backend = process.env.REACT_APP_BACKEND_URL;
    const poll = async () => {
      try {
        const url = sinceRef.current
          ? `${backend}/api/public-chat/messages?since=${encodeURIComponent(sinceRef.current)}`
          : `${backend}/api/public-chat/messages?limit=50`;
        const r = await fetch(url);
        const d = await r.json();
        if (!running) return;
        if (d.messages?.length) {
          setMessages((m) => {
            const raw = sinceRef.current ? [...m, ...d.messages] : d.messages;
            const combined = Array.from(new Map(raw.map((x) => [x.id, x])).values());
            sinceRef.current = combined[combined.length - 1]?.created_at || sinceRef.current;
            return combined.slice(-100);
          });
          setTimeout(scrollBottom, 30);
        }
      } catch {}
      setLoading(false);
    };
    poll();
    const t = setInterval(poll, 2500);
    return () => { running = false; clearInterval(t); };
  }, []);

  const send = async (e) => {
    e.preventDefault();
    const t = text.trim();
    if (!t || sending) return;
    setSending(true);
    try {
      const token = localStorage.getItem("bs_user_token");
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/public-chat/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ text: t }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        toast.error(j.detail || "Failed to send");
      } else {
        setText("");
      }
    } catch {
      toast.error("Network error — try again");
    }
    setSending(false);
  };

  const roleBadge = (role) => {
    if (role === "owner") return { text: "OWNER", cls: "bg-amber-500/20 text-amber-300 border-amber-500/40" };
    if (role === "admin") return { text: "ADMIN", cls: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40" };
    if (role === "staff" || role === "moderator") return { text: "STAFF", cls: "bg-sky-500/20 text-sky-300 border-sky-500/40" };
    return null;
  };

  return (
    <>
    <aside className="bg-[#0f2a15] border border-emerald-500/20 rounded-md overflow-hidden flex flex-col min-h-0" data-testid="public-shoutbox">
      <div className="px-4 py-3 border-b border-emerald-500/15 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <h2 className="font-display font-bold text-sm uppercase tracking-widest text-emerald-200">Live Chat</h2>
        </div>
        <span className="text-[10px] text-emerald-400/60 uppercase tracking-widest">everyone</span>
      </div>

      <div ref={listRef} className="flex-1 overflow-y-auto px-3 py-3 space-y-2 min-h-0" data-testid="shoutbox-messages">
        {loading && <div className="text-center text-emerald-200/40 text-xs py-6">Loading…</div>}
        {!loading && messages.length === 0 && (
          <div className="text-center text-emerald-200/50 text-xs py-6">Be the first to say hi 👋</div>
        )}
        {messages.map((m) => {
          const b = roleBadge(m.role);
          const mine = m.user_id === meIdRef.current;
          const isTip = m.kind === "tip";
          return (
            <div key={m.id} className={`group ${isTip ? "bg-amber-500/10 border border-amber-500/25 rounded-md p-2" : ""}`} data-testid={`chat-msg-${m.id}`}>
              <div className="flex items-baseline gap-1.5 mb-0.5 flex-wrap">
                <button
                  type="button"
                  disabled={mine || !user}
                  onClick={() => !mine && setTipTarget({ user_id: m.user_id, username: m.username })}
                  data-testid={`chat-user-${m.user_id}`}
                  title={mine ? "That's you" : `Tip @${m.username}`}
                  className={`text-[11px] font-bold ${mine ? "text-emerald-300 cursor-default" : "text-emerald-100 hover:text-emerald-300 hover:underline cursor-pointer"} disabled:cursor-default`}
                >
                  @{m.username}
                </button>
                {b && (
                  <span className={`text-[8px] px-1 py-px rounded-sm border font-bold uppercase tracking-wider ${b.cls}`}>{b.text}</span>
                )}
                {m.rank_name && !b && (
                  <span className={`text-[8px] px-1 py-px rounded-sm border font-bold uppercase tracking-wider ${m.rank_border_class || "border-white/20 bg-white/5"} ${m.rank_text_class || "text-white/70"}`} data-testid={`rank-badge-${m.user_id}`}>{m.rank_name}</span>
                )}
                <span className="ml-auto text-[9px] text-emerald-400/40">
                  {new Date(m.created_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
                </span>
              </div>
              <div className={`text-[13px] break-words leading-snug ${isTip ? "text-amber-200 font-bold" : "text-white/85"}`}>
                {isTip ? <>💰 {m.text}</> : m.text}
              </div>
            </div>
          );
        })}
      </div>

      <form onSubmit={send} className="border-t border-emerald-500/15 p-2 flex gap-2 bg-black/30 flex-shrink-0">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={500}
          placeholder={user ? "Say hi — click a username to tip 💰" : "Log in to chat"}
          disabled={!user || sending}
          data-testid="shoutbox-input"
          className="flex-1 bg-[#0a1a0a] border border-emerald-500/20 rounded-md px-3 py-2 text-sm outline-none focus:border-emerald-400 text-white placeholder:text-emerald-200/40 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!user || !text.trim() || sending}
          data-testid="shoutbox-send"
          className="w-10 h-10 rounded-md bg-emerald-500 hover:bg-emerald-400 text-black flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed transition"
        >
          {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
        </button>
      </form>
    </aside>
    {tipTarget && <TipDialog target={tipTarget} onClose={() => setTipTarget(null)} />}
    </>
  );
}

function TipDialog({ target, onClose }) {
  const [amount, setAmount] = useState(1);
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);

  const send = async () => {
    const a = Number(amount);
    if (!a || a < 0.5) return toast.error("Minimum tip is $0.50");
    setSending(true);
    try {
      const token = localStorage.getItem("bs_user_token");
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/tips/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ to_user_id: target.user_id, amount: a, note: note.trim() || undefined }),
      });
      const d = await r.json();
      if (r.ok) {
        toast.success(`✅ Tipped @${target.username} $${a}`);
        onClose();
      } else {
        toast.error(d.detail || "Failed to tip");
      }
    } catch {
      toast.error("Network error");
    }
    setSending(false);
  };

  return (
    <div className="fixed inset-0 z-[95] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="bg-[#0f2a15] border border-emerald-500/40 rounded-lg p-6 max-w-sm w-full shadow-2xl" data-testid="tip-dialog">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-11 h-11 rounded-full bg-amber-500/20 border border-amber-500/40 flex items-center justify-center text-2xl">💰</div>
          <div>
            <h3 className="font-display font-black text-lg">Send a tip</h3>
            <p className="text-xs text-emerald-200/70">to @{target.username}</p>
          </div>
        </div>
        <label className="block text-[10px] uppercase tracking-widest text-emerald-200/50 font-bold mb-1">Amount (USD)</label>
        <div className="flex gap-2 mb-3">
          {[1, 2, 5, 10].map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setAmount(v)}
              data-testid={`tip-quick-${v}`}
              className={`flex-1 py-2 rounded-md text-sm font-bold border transition ${amount === v ? "bg-emerald-500 text-black border-emerald-500" : "bg-black/30 border-emerald-500/20 text-emerald-200 hover:border-emerald-400"}`}
            >
              ${v}
            </button>
          ))}
        </div>
        <input
          type="number"
          min="0.5"
          step="0.5"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          data-testid="tip-amount"
          className="w-full bg-[#0a1a0a] border border-emerald-500/20 rounded-md px-3 py-2 text-lg font-bold text-emerald-300 outline-none focus:border-emerald-400 mb-3"
        />
        <label className="block text-[10px] uppercase tracking-widest text-emerald-200/50 font-bold mb-1">Note (optional)</label>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={120}
          placeholder="thanks bro!"
          data-testid="tip-note"
          className="w-full bg-[#0a1a0a] border border-emerald-500/20 rounded-md px-3 py-2 text-sm outline-none focus:border-emerald-400 mb-4"
        />
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 rounded-md hover:bg-white/5 text-sm text-white/70">Cancel</button>
          <button onClick={send} disabled={sending} data-testid="tip-submit" className="px-4 py-2 rounded-md bg-amber-500 hover:bg-amber-400 text-black font-bold text-sm inline-flex items-center gap-2 disabled:opacity-50">
            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <>💰</>}
            Send tip
          </button>
        </div>
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
    // Auto-verify any pending NOWPayments deposits every 30s so users don't have
    // to press the manual "Verify" button when the IPN webhook is late.
    const t = setInterval(async () => {
      try {
        const r = await authedApi().get("/client/funds/pending-deposits");
        const list = r.data.pending || [];
        setPending(list);
        for (const p of list) {
          try {
            const v = await authedApi().post(`/client/funds/nowpayments-verify/${p.id}`);
            if (v.data.credited) {
              toast.success(`Deposit credited: +$${v.data.amount}${v.data.bonus ? ` (+ $${v.data.bonus} bonus)` : ""}`);
              reloadBalance && reloadBalance();
              loadTxns();
              loadPending();
            }
          } catch {}
        }
      } catch {}
    }, 30000);
    return () => clearInterval(t);
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
    if (a < 0.10) {
      toast.error("Min $0.10 for crypto checkout");
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
            Min $0.10 · Instant credit after payment confirmation
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

function LiveOrdersView({ authedApi, ownsAutoLive, onGoAddons, onGoBuy }) {
  const [subs, setSubs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [autoEnabled, setAutoEnabled] = useState(false);

  const load = async () => {
    try {
      const r = await authedApi().get("/client/live-sub/my");
      setSubs(r.data.subscriptions || []);
      setAutoEnabled(!!r.data.auto_live_enabled);
    } catch {}
    setLoading(false);
  };
  useEffect(() => { load(); const t = setInterval(load, 20000); return () => clearInterval(t); }, []);

  const cancel = async (sid) => {
    if (!window.confirm("Cancel this auto-live subscription? No more bursts will be placed.")) return;
    try {
      await authedApi().post(`/client/live-sub/${sid}/cancel`);
      toast.success("Subscription cancelled.");
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Cancel failed"); }
  };

  const active = subs.filter((s) => s.status === "active");
  const inactive = subs.filter((s) => s.status !== "active");

  if (!ownsAutoLive && !autoEnabled) {
    return (
      <div className="max-w-3xl mx-auto space-y-6" data-testid="live-orders-view">
        <div>
          <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight flex items-center gap-2">
            <Zap className="w-7 h-7 text-fuchsia-400" /> Live orders
          </h1>
          <p className="text-white/50 text-sm mt-2">Automatic TikTok-live SMM bursts every 10 minutes while your target streams.</p>
        </div>
        <div className="bg-fuchsia-500/10 border border-fuchsia-500/30 rounded-lg p-8 text-center space-y-4" data-testid="live-locked">
          <div className="text-4xl">🔒</div>
          <div className="font-display font-black text-xl">Auto-Live is a paid add-on</div>
          <div className="text-sm text-white/60 max-w-md mx-auto">Purchase the Auto-Live add-on once — then this page becomes your control panel for recurring TikTok orders.</div>
          <button onClick={onGoAddons} data-testid="live-goto-addons" className="mt-2 px-5 py-2.5 rounded-md bg-emerald-500 hover:bg-emerald-400 text-black text-sm font-black uppercase tracking-wider transition">
            View add-ons →
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6" data-testid="live-orders-view">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight flex items-center gap-2">
            <Zap className="w-7 h-7 text-fuchsia-400" /> Live orders
          </h1>
          <p className="text-white/50 text-sm mt-2">Every 5 min we check TikTok. When live, a fresh order is placed — repeated every 10 minutes.</p>
        </div>
        <button
          onClick={onGoBuy}
          data-testid="live-goto-buy"
          className="px-4 py-2 rounded-md bg-fuchsia-500 hover:bg-fuchsia-400 text-white text-xs font-black uppercase tracking-wider transition"
        >
          + New auto-live
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="bg-[#0d0a14] border border-emerald-500/20 rounded-md p-4">
          <div className="text-[10px] uppercase tracking-widest text-white/50">Active</div>
          <div className="font-display font-black text-3xl text-emerald-300 mt-1" data-testid="live-active-count">{active.length}</div>
        </div>
        <div className="bg-[#0d0a14] border border-white/10 rounded-md p-4">
          <div className="text-[10px] uppercase tracking-widest text-white/50">Bursts placed</div>
          <div className="font-display font-black text-3xl text-white mt-1">{subs.reduce((a, s) => a + (s.total_bursts || 0), 0)}</div>
        </div>
        <div className="bg-[#0d0a14] border border-fuchsia-500/20 rounded-md p-4">
          <div className="text-[10px] uppercase tracking-widest text-white/50">Total spent</div>
          <div className="font-display font-black text-3xl text-fuchsia-300 mt-1">${subs.reduce((a, s) => a + (s.total_spent || 0), 0).toFixed(2)}</div>
        </div>
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-widest text-emerald-300 mb-2 font-bold">Active subscriptions</div>
        {loading ? (
          <div className="flex items-center justify-center py-10"><Loader2 className="w-6 h-6 animate-spin text-emerald-400" /></div>
        ) : active.length === 0 ? (
          <div className="bg-[#0d0a14] border border-white/10 rounded-md p-6 text-center text-sm text-white/50">
            No active auto-live subscriptions. <button onClick={onGoBuy} className="text-emerald-300 underline">Create one →</button>
          </div>
        ) : (
          <div className="space-y-2" data-testid="live-active-list">
            {active.map((s) => (
              <div key={s.id} className="bg-[#0d0a14] border border-fuchsia-500/30 rounded-md p-4" data-testid={`live-row-${s.id}`}>
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-fuchsia-400 animate-pulse" />
                      <a href={`https://www.tiktok.com/@${s.tiktok_username}/live`} target="_blank" rel="noopener noreferrer" className="font-bold text-fuchsia-200 hover:underline">@{s.tiktok_username}</a>
                    </div>
                    <div className="text-xs text-white/60 mt-1">{s.service_name} — <span className="font-mono">{s.quantity_per_burst}</span> per burst · ${(s.charge_per_burst || 0).toFixed(3)} each</div>
                  </div>
                  <button
                    onClick={() => cancel(s.id)}
                    data-testid={`live-cancel-${s.id}`}
                    className="px-3 py-1.5 rounded-md bg-red-500/20 border border-red-500/40 text-red-300 hover:bg-red-500/30 text-[11px] font-black uppercase tracking-wider transition"
                  >
                    Cancel
                  </button>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-3 text-[10px]">
                  <div className="bg-black/40 rounded p-2">
                    <div className="text-white/40 uppercase tracking-widest">Bursts</div>
                    <div className="text-emerald-300 font-bold text-sm">{s.total_bursts || 0}</div>
                  </div>
                  <div className="bg-black/40 rounded p-2">
                    <div className="text-white/40 uppercase tracking-widest">Spent</div>
                    <div className="text-emerald-300 font-bold text-sm">${(s.total_spent || 0).toFixed(2)}</div>
                  </div>
                  <div className="bg-black/40 rounded p-2">
                    <div className="text-white/40 uppercase tracking-widest">Last burst</div>
                    <div className="text-white/80 font-mono text-[11px]">{s.last_burst_at ? new Date(s.last_burst_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}</div>
                  </div>
                  <div className="bg-black/40 rounded p-2">
                    <div className="text-white/40 uppercase tracking-widest">Expires</div>
                    <div className="text-white/80 font-mono text-[11px]">{s.expires_at ? new Date(s.expires_at).toLocaleDateString() : "—"}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {inactive.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-widest text-white/40 mb-2 font-bold">History ({inactive.length})</div>
          <div className="space-y-1.5 max-h-64 overflow-y-auto">
            {inactive.map((s) => (
              <div key={s.id} className="bg-[#0d0a14] border border-white/5 rounded-md px-4 py-2.5 text-xs flex items-center gap-3 flex-wrap">
                <span className="text-white/70 font-mono">@{s.tiktok_username}</span>
                <span className="text-white/50 truncate flex-1 min-w-0">{s.service_name}</span>
                <span className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded bg-white/10 text-white/60">{s.status}</span>
                <span className="text-white/50">${(s.total_spent || 0).toFixed(2)} · {s.total_bursts || 0} bursts</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


function AddonsView({ authedApi, balance, reloadBalance, reloadAddons, onGoBuy, onGoLive }) {
  const [addons, setAddons] = useState([]);
  const [loading, setLoading] = useState(true);
  const [buying, setBuying] = useState(null); // addon.id in-flight
  const [checkout, setCheckout] = useState(null); // addon in confirm-modal

  const load = async () => {
    setLoading(true);
    try {
      const r = await authedApi().get("/client/addons/catalog");
      setAddons(r.data.addons || []);
    } catch {}
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const purchase = async (addon) => {
    setBuying(addon.id);
    try {
      const r = await authedApi().post("/client/addons/purchase", { addon_id: addon.id });
      toast.success(`✅ ${addon.name} unlocked — new balance $${r.data.balance.toFixed(2)}`);
      setCheckout(null);
      await Promise.all([reloadBalance?.(), reloadAddons?.(), load()]);
      // If the user bought Auto-Live, drop them into the Live orders panel
      if (addon.id === "auto_live" && onGoLive) {
        setTimeout(() => onGoLive(), 400);
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Purchase failed");
    } finally { setBuying(null); }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6" data-testid="addons-view">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight flex items-center gap-2">
            <Sparkles className="w-7 h-7 text-emerald-400" /> Add-ons store
          </h1>
          <p className="text-white/50 text-sm mt-2">Unlock premium features with your account balance — one-time payment, permanent access.</p>
        </div>
        <div className="bg-[#0d0a14] border border-emerald-500/30 rounded-md px-4 py-2">
          <div className="text-[10px] uppercase tracking-widest text-white/50">Balance</div>
          <div className="font-display font-black text-xl text-emerald-300" data-testid="addons-balance">${balance.toFixed(2)}</div>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16"><Loader2 className="w-6 h-6 animate-spin text-emerald-400" /></div>
      ) : addons.length === 0 ? (
        <div className="text-center py-10 text-white/50">No add-ons available yet.</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {addons.map((a) => (
            <div key={a.id} className={`relative bg-gradient-to-br ${a.owned ? "from-emerald-500/10 to-transparent border-emerald-500/50" : "from-fuchsia-500/10 to-transparent border-fuchsia-500/30 hover:border-fuchsia-400"} border rounded-lg p-6 transition`} data-testid={`addon-card-${a.id}`}>
              {a.owned && (
                <div className="absolute top-3 right-3 px-2 py-1 rounded-full bg-emerald-500 text-black text-[10px] font-black uppercase tracking-wider">Owned</div>
              )}
              <div className="font-display font-black text-2xl mb-1">{a.name}</div>
              <div className="text-sm text-white/60 mb-4">{a.tagline}</div>
              <p className="text-sm text-white/75 leading-relaxed mb-4">{a.description}</p>
              <ul className="space-y-1.5 mb-6">
                {(a.features || []).map((f, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-white/70">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 mt-0.5 shrink-0" />
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
              <div className="flex items-end justify-between gap-3 pt-4 border-t border-white/10">
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-white/40">Price</div>
                  <div className="font-display font-black text-3xl text-emerald-300">${a.price.toFixed(2)}</div>
                </div>
                {a.owned ? (
                  <button
                    onClick={() => (a.id === "auto_live" ? onGoLive?.() : onGoBuy?.())}
                    data-testid={`addon-open-${a.id}`}
                    className="px-5 py-2.5 rounded-md bg-emerald-500 hover:bg-emerald-400 text-black text-sm font-black uppercase tracking-wider transition"
                  >
                    Open
                  </button>
                ) : (
                  <button
                    onClick={() => setCheckout(a)}
                    data-testid={`addon-buy-${a.id}`}
                    disabled={buying === a.id}
                    className="px-5 py-2.5 rounded-md bg-fuchsia-500 hover:bg-fuchsia-400 text-white text-sm font-black uppercase tracking-wider transition disabled:opacity-40"
                  >
                    {buying === a.id ? <Loader2 className="w-4 h-4 animate-spin" /> : "Unlock"}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {checkout && (
        <div
          data-testid="addon-checkout-modal"
          className="fixed inset-0 z-[85] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => (buying ? null : setCheckout(null))}
        >
          <div className="w-full max-w-md bg-[#0d2b12] border border-emerald-500/40 rounded-lg p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="text-[10px] uppercase tracking-widest text-emerald-300 mb-1 font-bold">Checkout</div>
            <h3 className="font-display font-black text-2xl mb-1">{checkout.name}</h3>
            <p className="text-sm text-white/60 mb-4">{checkout.tagline}</p>
            <div className="bg-black/30 rounded-md p-4 space-y-2 mb-4 text-sm">
              <div className="flex justify-between"><span className="text-white/60">Price</span><span className="text-white font-bold">${checkout.price.toFixed(2)}</span></div>
              <div className="flex justify-between"><span className="text-white/60">Payment</span><span className="text-emerald-300 font-bold">Account balance</span></div>
              <div className="flex justify-between border-t border-white/10 pt-2"><span className="text-white/60">Balance after</span><span className={`font-bold ${balance - checkout.price >= 0 ? "text-emerald-300" : "text-red-300"}`}>${(balance - checkout.price).toFixed(2)}</span></div>
            </div>
            {balance < checkout.price && (
              <div className="mb-3 text-xs text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded p-2 text-center">
                Not enough balance. Top up in the Wallet tab first.
              </div>
            )}
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => setCheckout(null)}
                disabled={buying === checkout.id}
                className="py-2.5 rounded-md bg-white/10 hover:bg-white/15 text-white text-sm font-bold uppercase tracking-wider transition disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                onClick={() => purchase(checkout)}
                data-testid="addon-checkout-confirm"
                disabled={buying === checkout.id || balance < checkout.price}
                className="py-2.5 rounded-md bg-emerald-500 hover:bg-emerald-400 text-black text-sm font-black uppercase tracking-wider transition disabled:opacity-40"
              >
                {buying === checkout.id ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : "Pay & Unlock"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


function BuyView({ authedApi, balance, reloadBalance, ownsAutoLive, onGoAddons, onGoLive }) {
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
  const [bulkMode, setBulkMode] = useState(false);
  const [bulkTargets, setBulkTargets] = useState("");
  const [bulkResult, setBulkResult] = useState(null);
  const [subMode, setSubMode] = useState(false);
  const [subUsername, setSubUsername] = useState("");
  const [subDays, setSubDays] = useState(7);
  const [subSubmitting, setSubSubmitting] = useState(false);
  const [mySubs, setMySubs] = useState([]);
  // Saved bulk-target lists
  const [bulkLists, setBulkLists] = useState([]);
  const [saveListName, setSaveListName] = useState("");
  const [savingList, setSavingList] = useState(false);
  // Repeat-order flow
  const [repeating, setRepeating] = useState(false);

  const loadBulkLists = async () => {
    try {
      const r = await authedApi().get("/client/bulk-lists");
      setBulkLists(r.data.lists || []);
    } catch { /* ignore */ }
  };
  useEffect(() => { loadBulkLists(); }, []);

  const saveCurrentBulk = async () => {
    const name = saveListName.trim();
    if (!name) { toast.error("Name your list first"); return; }
    if (bulkTargetList.length === 0) { toast.error("Enter at least one target"); return; }
    setSavingList(true);
    try {
      await authedApi().post("/client/bulk-lists", { name, targets: bulkTargetList });
      toast.success(`Saved "${name}" (${bulkTargetList.length} targets)`);
      setSaveListName("");
      loadBulkLists();
    } catch (e) { toast.error(e.response?.data?.detail || "Save failed"); }
    finally { setSavingList(false); }
  };

  const loadList = (l) => {
    setBulkTargets((l.targets || []).join("\n"));
    toast.success(`Loaded "${l.name}" (${(l.targets || []).length} targets)`);
  };

  const deleteList = async (lid, name) => {
    if (!window.confirm(`Delete saved list "${name}"?`)) return;
    try {
      await authedApi().delete(`/client/bulk-lists/${lid}`);
      toast.success("List deleted");
      loadBulkLists();
    } catch (e) { toast.error(e.response?.data?.detail || "Delete failed"); }
  };

  const repeatLast = async () => {
    if (!last?.orderId) return;
    setRepeating(true);
    try {
      const r = await authedApi().post(`/client/orders/${last.orderId}/repeat`);
      toast.success(`Order repeated! New ID #${r.data.smm_order_id}`);
      setLast({ id: r.data.smm_order_id, charge: r.data.charge, orderId: last.orderId });
      reloadBalance();
    } catch (e) { toast.error(e.response?.data?.detail || "Repeat failed"); }
    finally { setRepeating(false); }
  };

  const loadMySubs = async () => {
    try {
      const r = await authedApi().get("/client/live-sub/my");
      setMySubs(r.data.subscriptions || []);
    } catch { /* ignore */ }
  };
  useEffect(() => { loadMySubs(); }, []);

  const subscribe = async () => {
    if (!selected) return;
    if (!subUsername.trim()) { toast.error("Enter the TikTok @username"); return; }
    if (qty < (selected.min || 1)) { toast.error(`Minimum quantity is ${selected.min}`); return; }
    setSubSubmitting(true);
    try {
      const r = await authedApi().post("/client/live-sub/create", {
        service_id: selected.service,
        tiktok_username: subUsername.trim().replace(/^@/, ""),
        quantity_per_burst: Number(qty),
        duration_days: subDays,
      });
      toast.success(`✅ Auto-live activated for @${r.data.subscription.tiktok_username} (${subDays} days)`);
      setSubUsername("");
      loadMySubs();
      reloadBalance();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Subscription failed");
    } finally { setSubSubmitting(false); }
  };

  const cancelSub = async (sid) => {
    try {
      await authedApi().post(`/client/live-sub/${sid}/cancel`);
      toast.success("Subscription cancelled.");
      loadMySubs();
    } catch (e) { toast.error(e.response?.data?.detail || "Cancel failed"); }
  };

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
      setLast({ id: r.data.smm_order_id, charge: r.data.charge, orderId: r.data.order_id });
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

  // Parse the bulk-targets textarea into a clean array of links/usernames.
  const parseBulkTargets = () => bulkTargets
    .split(/[\n,]+/g)
    .map((s) => s.trim())
    .filter(Boolean)
    // Dedupe (case-insensitive) client-side too so the count shown matches
    .filter((v, i, a) => a.findIndex((x) => x.toLowerCase() === v.toLowerCase()) === i);
  const bulkTargetList = parseBulkTargets();
  const bulkTotal = selected && qty ? (Number(selected.rate) * Number(qty) * bulkTargetList.length) / 1000 : 0;
  const canBulkBuy = selected && qty >= (selected.min || 1) && qty <= (selected.max || 1e9) && bulkTargetList.length >= 1 && bulkTotal <= balance && commentsOk;
  const isTiktokService = selected && /tiktok/i.test((selected.category || "") + " " + (selected.name || ""));

  const placeBulk = async () => {
    if (!selected) return;
    setPlacing(true);
    setBulkResult(null);
    try {
      const r = await authedApi().post("/client/order-bulk", {
        service_id: selected.service,
        quantity: Number(qty),
        targets: bulkTargetList,
        comments: needsComments ? comments.trim() : undefined,
      });
      const { successes, failures, charged, results } = r.data;
      setBulkResult({ successes, failures, charged, results });
      if (successes > 0) toast.success(`✅ Placed ${successes}/${bulkTargetList.length} orders — charged $${charged.toFixed(2)}`);
      if (failures > 0) toast.error(`${failures} target(s) failed — see details below`);
      reloadBalance();
      // Keep the service selected so user can review results; but clear the list
      setBulkTargets("");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Bulk order failed");
    } finally {
      setPlacing(false);
    }
  };

  return (
    <div className="space-y-6">
      {mySubs.filter((s) => s.status === "active").length > 0 && (
        <div className="bg-fuchsia-500/10 border border-fuchsia-500/40 rounded-md p-4" data-testid="live-subs-panel">
          <div className="flex items-center gap-2 mb-3">
            <span className="w-2 h-2 rounded-full bg-fuchsia-400 animate-pulse" />
            <div className="text-[10px] uppercase tracking-widest text-fuchsia-300 font-bold">
              Auto-Live subscriptions ({mySubs.filter((s) => s.status === "active").length} active)
            </div>
          </div>
          <div className="space-y-2">
            {mySubs.filter((s) => s.status === "active").map((s) => (
              <div key={s.id} className="flex flex-wrap items-center gap-3 bg-black/40 rounded-sm p-3 text-xs" data-testid={`live-sub-${s.id}`}>
                <span className="font-mono text-fuchsia-200">@{s.tiktok_username}</span>
                <span className="text-white/60">{s.service_name}</span>
                <span className="text-white/50">{s.quantity_per_burst}/burst</span>
                <span className="text-emerald-300 font-mono">${(s.total_spent || 0).toFixed(2)} spent · {s.total_bursts || 0} bursts</span>
                <span className="text-white/40 ml-auto">expires {s.expires_at ? new Date(s.expires_at).toLocaleDateString() : "-"}</span>
                <button onClick={() => cancelSub(s.id)} data-testid={`live-sub-cancel-${s.id}`}
                  className="text-red-300 hover:text-red-200 text-[11px] font-bold uppercase tracking-wider">
                  Cancel
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
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
        <div className="bg-[#0d0a14] border border-emerald-500/40 rounded-sm p-4 flex items-center justify-between gap-3 flex-wrap">
          <div className="text-xs">
            <span className="text-emerald-400 font-bold">Last order placed</span>{" "}
            — Order ID <span className="font-mono">#{last.id}</span> · charged{" "}
            <span className="text-[#FF007F] font-bold">${last.charge.toFixed(2)}</span>
          </div>
          <div className="flex items-center gap-2">
            {last.orderId && (
              <button
                onClick={repeatLast}
                disabled={repeating}
                data-testid="buy-repeat-last"
                className="px-3 py-1.5 rounded-md bg-emerald-500 hover:bg-emerald-400 text-black text-[11px] font-black uppercase tracking-wider transition inline-flex items-center gap-1.5 disabled:opacity-40"
              >
                {repeating ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                Repeat same order
              </button>
            )}
            <button
              onClick={() => setLast(null)}
              className="text-[10px] uppercase tracking-wider text-white/50 hover:text-white"
            >
              dismiss
            </button>
          </div>
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

          <div className="flex items-center justify-between bg-[#1a1525]/60 border border-white/5 rounded-sm px-4 py-3 flex-wrap gap-3">
            <div className="flex items-center gap-3 flex-wrap">
              <div className="text-xs uppercase tracking-wider text-white/50">Bulk order</div>
              <button
                onClick={() => { setBulkMode((v) => !v); setBulkResult(null); if (!bulkMode) setSubMode(false); }}
                data-testid="buy-bulk-toggle"
                className={`relative w-11 h-6 rounded-full transition ${bulkMode ? "bg-emerald-500" : "bg-white/15"}`}
              >
                <span className={`absolute top-0.5 ${bulkMode ? "left-6" : "left-0.5"} w-5 h-5 rounded-full bg-white shadow transition-all`} />
              </button>
              <span className="text-[11px] text-white/50">{bulkMode ? `${bulkTargetList.length} target(s)` : "single"}</span>
              {isTiktokService && /live/i.test(selected?.name || selected?.category || "") && (
                ownsAutoLive ? (
                  <>
                    <div className="ml-2 md:ml-4 text-xs uppercase tracking-wider text-fuchsia-300">Auto-Live</div>
                    <button
                      onClick={() => { setSubMode((v) => !v); if (!subMode) setBulkMode(false); }}
                      data-testid="buy-sub-toggle"
                      className={`relative w-11 h-6 rounded-full transition ${subMode ? "bg-fuchsia-500" : "bg-white/15"}`}
                    >
                      <span className={`absolute top-0.5 ${subMode ? "left-6" : "left-0.5"} w-5 h-5 rounded-full bg-white shadow transition-all`} />
                    </button>
                  </>
                ) : (
                  <button
                    onClick={onGoAddons}
                    data-testid="buy-auto-live-locked"
                    title="Unlock Auto-Live in the Add-ons store"
                    className="ml-2 md:ml-4 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-black uppercase tracking-wider text-fuchsia-300 border border-fuchsia-500/40 bg-fuchsia-500/10 hover:bg-fuchsia-500/20 transition"
                  >
                    🔒 Auto-Live — Unlock
                  </button>
                )
              )}
            </div>
            <div className="text-right">
              <div className="text-xs uppercase tracking-wider text-white/50">Total</div>
              <div className="font-display font-black text-2xl text-[#FF007F]" data-testid="buy-total">
                ${(bulkMode ? bulkTotal : total).toFixed(4)}
              </div>
            </div>
          </div>

          {bulkMode && (
            <div className="bg-emerald-500/5 border border-emerald-500/30 rounded-sm p-4 space-y-3" data-testid="buy-bulk-panel">
              {/* Saved lists row */}
              {bulkLists.length > 0 && (
                <div className="flex items-center gap-2 flex-wrap" data-testid="bulk-saved-lists">
                  <div className="text-[10px] uppercase tracking-widest text-emerald-300 font-bold">Saved lists</div>
                  {bulkLists.map((l) => (
                    <div key={l.id} className="inline-flex items-center gap-1 bg-black/40 border border-emerald-500/30 rounded-md">
                      <button
                        onClick={() => loadList(l)}
                        data-testid={`bulk-list-load-${l.id}`}
                        title="Load into the textarea"
                        className="px-2.5 py-1 text-[11px] font-bold text-emerald-200 hover:text-white"
                      >
                        {l.name} <span className="text-emerald-400/60 font-mono ml-1">·{(l.targets || []).length}</span>
                      </button>
                      <button
                        onClick={() => deleteList(l.id, l.name)}
                        data-testid={`bulk-list-del-${l.id}`}
                        title="Delete list"
                        className="px-1.5 py-1 text-white/40 hover:text-red-300 text-xs"
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <Label className="text-[11px] uppercase tracking-wider text-emerald-300">
                Targets — one link or @username per line (up to 200)
              </Label>
              <textarea
                data-testid="buy-bulk-targets"
                value={bulkTargets}
                onChange={(e) => setBulkTargets(e.target.value.slice(0, 20000))}
                rows={6}
                placeholder={"https://tiktok.com/@user1/live\n@streamer2\nhttps://tiktok.com/@creator3/live"}
                className="w-full bg-[#1a1525] border border-white/10 rounded-sm px-3 py-2 text-sm font-mono text-white outline-none focus:border-emerald-500"
              />
              <div className="text-[10px] text-white/40">
                {bulkTargetList.length} unique target(s) · each will receive {qty || 0} × ${(Number(selected.rate) * Number(qty || 0) / 1000).toFixed(4)} = <span className="text-emerald-300 font-bold">${bulkTotal.toFixed(2)} total</span>
                {isTiktokService ? " · optimised for TikTok Live" : ""}
              </div>
              {/* Save current list */}
              <div className="flex flex-col sm:flex-row gap-2 pt-2 border-t border-emerald-500/20">
                <Input
                  data-testid="bulk-save-name"
                  value={saveListName}
                  onChange={(e) => setSaveListName(e.target.value.slice(0, 60))}
                  placeholder="Give this list a name (e.g. Regulars)"
                  className="bg-[#1a1525] border-white/10 text-sm flex-1"
                />
                <button
                  onClick={saveCurrentBulk}
                  disabled={savingList || bulkTargetList.length === 0 || !saveListName.trim()}
                  data-testid="bulk-save-btn"
                  className="px-4 py-2 rounded-md bg-emerald-500 hover:bg-emerald-400 text-black text-xs font-black uppercase tracking-wider transition disabled:opacity-40 inline-flex items-center justify-center gap-1.5"
                  title="Save the current targets as a reusable list"
                >
                  {savingList ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "💾"}
                  Save list
                </button>
              </div>
            </div>
          )}

          {subMode && ownsAutoLive && (
            <div className="bg-fuchsia-500/5 border border-fuchsia-500/40 rounded-sm p-4 space-y-3" data-testid="buy-sub-panel">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-fuchsia-400 animate-pulse" />
                <div className="text-[11px] uppercase tracking-widest text-fuchsia-300 font-bold">Auto-Live setup</div>
              </div>
              <p className="text-xs text-white/60">
                We&apos;ll check the TikTok profile every 5 minutes. Each time they&apos;re live, we place a fresh order for <span className="text-fuchsia-200 font-bold">{qty || 0}</span> {selected?.name || "unit(s)"}, repeating every 10 minutes while the stream stays up. Balance is charged only per burst.
              </p>
              <div className="grid sm:grid-cols-2 gap-3">
                <div>
                  <Label className="text-[11px] uppercase tracking-wider text-white/60">TikTok @username</Label>
                  <Input
                    data-testid="buy-sub-username"
                    value={subUsername}
                    onChange={(e) => setSubUsername(e.target.value)}
                    placeholder="creatorhandle"
                    className="bg-[#1a1525] border-fuchsia-500/30 mt-1"
                  />
                </div>
                <div>
                  <Label className="text-[11px] uppercase tracking-wider text-white/60">Duration</Label>
                  <select
                    data-testid="buy-sub-days"
                    value={subDays}
                    onChange={(e) => setSubDays(Number(e.target.value))}
                    className="mt-1 w-full bg-[#1a1525] border border-fuchsia-500/30 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-fuchsia-400"
                  >
                    {[7, 14, 30, 60, 90, 365].map((d) => (
                      <option key={d} value={d} className="bg-[#0a1a0a]">{d} days</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="text-[11px] text-fuchsia-200/70 bg-black/30 rounded-md px-3 py-2">
                Charged <span className="text-fuchsia-300 font-bold font-mono">${(Number(selected?.rate || 0) * Number(qty || 0) / 1000).toFixed(4)}</span> per burst.
                We need at least this much in your balance to start.
              </div>
              <button
                onClick={subscribe}
                disabled={subSubmitting || !subUsername.trim() || !qty}
                data-testid="buy-sub-confirm"
                className="w-full py-3 rounded-md bg-fuchsia-500 hover:bg-fuchsia-400 text-white font-black text-sm uppercase tracking-wider transition disabled:opacity-40 inline-flex items-center justify-center gap-2"
              >
                {subSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                Activate Auto-Live for {subDays} days
              </button>
              <button
                onClick={onGoLive}
                data-testid="buy-sub-go-live"
                className="w-full text-center text-[11px] text-fuchsia-200/70 hover:text-white uppercase tracking-widest transition"
              >
                → Manage active subscriptions
              </button>
            </div>
          )}

          {bulkResult && (
            <div className="bg-black/40 border border-white/10 rounded-sm p-3 max-h-56 overflow-y-auto text-xs space-y-1" data-testid="buy-bulk-results">
              <div className="text-white/60 mb-1">
                Result: <span className="text-emerald-300 font-bold">{bulkResult.successes} placed</span>
                {bulkResult.failures > 0 && <> · <span className="text-red-300 font-bold">{bulkResult.failures} failed</span></>}
                {" · charged "}<span className="text-emerald-300 font-mono">${bulkResult.charged.toFixed(2)}</span>
              </div>
              {(bulkResult.results || []).map((r, i) => (
                <div key={i} className={`flex justify-between gap-2 ${r.ok ? "text-white/70" : "text-red-300/80"}`}>
                  <span className="truncate font-mono">{r.target}</span>
                  <span>{r.ok ? `#${r.smm_order_id}` : (r.error || "failed").slice(0, 40)}</span>
                </div>
              ))}
            </div>
          )}

          {(bulkMode ? bulkTotal : total) > balance && qty > 0 && (
            <div className="text-xs text-amber-400">
              Not enough balance. Top up via Add Funds or redeem a coupon.
            </div>
          )}

          {!subMode && (
            <button
              disabled={bulkMode ? (!canBulkBuy || placing) : (!canBuy || placing)}
              onClick={bulkMode ? placeBulk : place}
              data-testid={bulkMode ? "buy-bulk-confirm" : "buy-confirm"}
              className="w-full py-3 gradient-pp rounded-sm font-bold text-sm inline-flex items-center justify-center gap-2 disabled:opacity-40"
            >
              {placing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
              {bulkMode
                ? `Place ${bulkTargetList.length} orders — $${bulkTotal.toFixed(2)}`
                : `Place order — $${total.toFixed(2)}`}
            </button>
          )}
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

// Virtual number rental (WhatsApp / Telegram / Signal / Viber / TikTok)

// Official brand SVG paths (Simple Icons, CC0). No external dependency.
const APP_ICONS = {
  whatsapp: {
    color: "#25D366",
    path: "M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z",
  },
  telegram: {
    color: "#26A5E4",
    path: "M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z",
  },
  signal: {
    color: "#3A76F0",
    path: "M9.12.35A11.914 11.914 0 0 0 6.32 1.5l.9 1.55a10.087 10.087 0 0 1 2.37-.97Zm5.75 0-.46 1.73a10.077 10.077 0 0 1 2.37.98l.9-1.56c-.88-.5-1.82-.9-2.81-1.15zm-9.79 2.6A12.084 12.084 0 0 0 2.96 5.1L4.42 6.28c.53-.65 1.14-1.26 1.79-1.8Zm13.84 0-1.14 1.4c.66.54 1.26 1.14 1.79 1.8l1.4-1.14a11.98 11.98 0 0 0-2.05-2.06zM.35 9.13c-.24.99-.35 1.98-.35 3l1.79-.24a10.08 10.08 0 0 1 .3-2.29Zm23.29 0-1.74.47a10.077 10.077 0 0 1 .3 2.3L24 12c0-1.02-.11-2.02-.35-3zM2.09 14.55l-1.74.46c.26.99.65 1.93 1.15 2.82l1.55-.9a10.07 10.07 0 0 1-.97-2.38zm19.83 0a10.077 10.077 0 0 1-.97 2.37l1.55.9c.5-.88.9-1.82 1.15-2.81zM12 2.4c-2.55 0-5 1.01-6.8 2.81a9.61 9.61 0 0 0-2.34 9.79l-.86 3.06c-.06.2 0 .4.14.55a.5.5 0 0 0 .55.14l3.06-.86A9.61 9.61 0 0 0 12 21.6a9.62 9.62 0 0 0 9.6-9.6c0-2.55-1.01-5-2.81-6.8A9.62 9.62 0 0 0 12 2.4zm-8.42 15.8-1.4 1.14c.62.77 1.32 1.47 2.09 2.09l1.14-1.4a10.087 10.087 0 0 1-1.83-1.83zm5.28 3.42-.46 1.74c.99.24 1.98.35 3 .35v-1.8a10.08 10.08 0 0 1-2.29-.3z",
  },
  viber: {
    color: "#7360F2",
    path: "M11.4 0C9.473.028 5.333.344 3.02 2.467 1.302 4.187.696 6.7.633 9.817c-.063 3.118-.144 8.968 5.495 10.554h.005l-.004 2.421s-.037.98.61 1.18c.783.243 1.24-.502 1.986-1.303.412-.442.98-1.093 1.407-1.593 3.855.324 6.815-.418 7.153-.528.777-.253 5.176-.816 5.892-6.653.732-6.02-.36-9.826-2.328-11.55l-.011-.006c-.596-.55-2.98-2.287-8.302-2.306 0 0-.392-.026-1.135-.033zm.061 1.717c.63.005.99.026.99.026 4.516.016 6.474 1.377 6.98 1.836 1.66 1.44 2.518 4.874 1.9 9.897-.61 4.891-4.169 5.198-4.825 5.41-.28.09-2.876.738-6.14.526 0 0-2.43 2.931-3.187 3.694-.111.117-.242.163-.328.144-.122-.03-.156-.176-.153-.39l.023-4.028c-4.769-1.325-4.487-6.303-4.436-8.906.053-2.604.545-4.735 1.998-6.169 1.966-1.767 5.516-2.031 7.15-2.041 0 0 .085-.005.219 0zm.372 2.548a.734.734 0 0 0-.735.734.735.735 0 0 0 .735.735c1.995 0 3.634.647 4.75 1.759 1.113 1.116 1.759 2.755 1.759 4.75a.734.734 0 0 0 .735.735.735.735 0 0 0 .735-.735c0-2.36-.788-4.427-2.194-5.833-1.406-1.406-3.473-2.194-5.833-2.194l.048.049zm-3.398.42a1.94 1.94 0 0 0-.898.14h-.02c-.622.226-1.223.616-1.85 1.234C4.895 6.79 4.5 7.44 4.35 8.06c-.152.62-.084 1.244.153 1.696l.01.024c1.328 2.353 3.048 4.55 5.15 6.596l.024.03c1.032.972 2.029 1.716 3.032 2.234.633.328 1.288.523 1.936.53a2.63 2.63 0 0 0 1.05-.219l.02-.01c.34-.17.68-.398 1.032-.68.359-.29.664-.617.916-.976l.014-.028c.226-.365.297-.831.144-1.263-.156-.428-.456-.796-.834-1.028l-1.5-.883-.014-.01c-.36-.204-.784-.204-1.144 0-.359.203-.596.564-.634.964l-.06.53c-.037.288-.343.514-.68.532-.66-.028-1.264-.315-1.75-.786-.485-.472-.766-1.075-.79-1.694.014-.324.222-.61.514-.66l.517-.06.007-.008c.406-.036.775-.267.988-.628.213-.36.244-.807.077-1.192l-.87-1.516-.007-.014a1.727 1.727 0 0 0-.99-.802 1.938 1.938 0 0 0-.55-.09zm3.435 1.15a.735.735 0 0 0-.708.762.734.734 0 0 0 .734.708c.732.005 1.276.235 1.72.688.44.454.665 1.008.665 1.782a.734.734 0 0 0 .734.735.735.735 0 0 0 .735-.735c0-1.115-.377-2.093-1.056-2.79-.68-.702-1.664-1.128-2.783-1.14l-.041-.01zm.13 2.44a.734.734 0 0 0-.75.734.734.734 0 0 0 .734.735c.174 0 .262.028.322.088.06.06.09.146.09.32a.734.734 0 0 0 .734.735.735.735 0 0 0 .735-.735c0-.44-.117-.885-.446-1.221-.33-.336-.79-.462-1.235-.462l-.185.005z",
  },
  tiktok: {
    color: "#FF0050",
    path: "M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z",
  },
};

function AppIcon({ name, size = 32 }) {
  const spec = APP_ICONS[name];
  if (!spec) return null;
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill={spec.color} aria-label={name}>
      <path d={spec.path} />
    </svg>
  );
}

const NUMBERS_COUNTRIES = [
  { code: "any", name: "Any country (cheapest)", flag: "🌍" },
  { code: "usa", name: "United States", flag: "🇺🇸" },
  { code: "england", name: "United Kingdom", flag: "🇬🇧" },
  { code: "germany", name: "Germany", flag: "🇩🇪" },
  { code: "france", name: "France", flag: "🇫🇷" },
  { code: "spain", name: "Spain", flag: "🇪🇸" },
  { code: "italy", name: "Italy", flag: "🇮🇹" },
  { code: "netherlands", name: "Netherlands", flag: "🇳🇱" },
  { code: "poland", name: "Poland", flag: "🇵🇱" },
  { code: "romania", name: "Romania", flag: "🇷🇴" },
  { code: "russia", name: "Russia", flag: "🇷🇺" },
  { code: "ukraine", name: "Ukraine", flag: "🇺🇦" },
  { code: "india", name: "India", flag: "🇮🇳" },
  { code: "indonesia", name: "Indonesia", flag: "🇮🇩" },
  { code: "philippines", name: "Philippines", flag: "🇵🇭" },
  { code: "vietnam", name: "Vietnam", flag: "🇻🇳" },
  { code: "kazakhstan", name: "Kazakhstan", flag: "🇰🇿" },
  { code: "brazil", name: "Brazil", flag: "🇧🇷" },
  { code: "argentina", name: "Argentina", flag: "🇦🇷" },
  { code: "mexico", name: "Mexico", flag: "🇲🇽" },
  { code: "canada", name: "Canada", flag: "🇨🇦" },
  { code: "turkey", name: "Turkey", flag: "🇹🇷" },
  { code: "nigeria", name: "Nigeria", flag: "🇳🇬" },
  { code: "southafrica", name: "South Africa", flag: "🇿🇦" },
];

function NumbersView({ authedApi, balance, reloadBalance }) {
  const [products, setProducts] = useState([]);
  const [country, setCountry] = useState("any");
  const [loading, setLoading] = useState(true);
  const [buying, setBuying] = useState(null); // product id in-flight
  const [orders, setOrders] = useState([]);

  const loadCatalog = async () => {
    setLoading(true);
    try {
      const r = await api.get("/numbers/services");
      setProducts(r.data.products || []);
      if (r.data.default_country && r.data.default_country !== "any") {
        setCountry(r.data.default_country);
      }
    } catch {
      toast.error("Failed to load virtual number catalog.");
    } finally {
      setLoading(false);
    }
  };

  const loadOrders = async () => {
    try {
      const r = await authedApi().get("/5sim/orders/my");
      setOrders(r.data.orders || []);
    } catch {}
  };

  useEffect(() => {
    loadCatalog();
    loadOrders();
    const t = setInterval(loadOrders, 8000); // auto-refresh so SMS codes appear
    return () => clearInterval(t);
  }, []);

  const buy = async (product) => {
    if (balance < product.price) {
      toast.error(`Not enough balance — need $${product.price.toFixed(2)}.`);
      return;
    }
    setBuying(product.id);
    try {
      const r = await authedApi().post("/numbers/buy", { product: product.id, country });
      toast.success(`Number rented: ${r.data.phone}`);
      await Promise.all([loadOrders(), reloadBalance?.()]);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Purchase failed. Try another country.");
    } finally {
      setBuying(null);
    }
  };

  const cancel = async (oid) => {
    try {
      await authedApi().post(`/5sim/orders/${oid}/cancel`);
      toast.success("Order cancelled — you were refunded.");
      await Promise.all([loadOrders(), reloadBalance?.()]);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Cancel failed");
    }
  };

  const finish = async (oid) => {
    try {
      await authedApi().post(`/numbers/orders/${oid}/finish`);
      toast.success("Marked as finished.");
      await loadOrders();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Finish failed");
    }
  };

  const activeOrders = orders.filter((o) => !["FINISHED", "CANCELED", "CANCELLED", "BANNED", "TIMEOUT"].includes(String(o.status || "").toUpperCase()));
  const pastOrders = orders.filter((o) => ["FINISHED", "CANCELED", "CANCELLED", "BANNED", "TIMEOUT"].includes(String(o.status || "").toUpperCase()));

  return (
    <div className="max-w-6xl space-y-6" data-testid="numbers-view">
      <div>
        <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight flex items-center gap-2">
          <Phone className="w-7 h-7 text-emerald-400" /> Virtual Numbers
        </h1>
        <p className="text-white/50 text-sm mt-2">
          Rent a real phone number to receive SMS verification codes for WhatsApp, Telegram, Signal, Viber and TikTok. Pick a country, tap Buy, and the SMS code will appear here in seconds.
        </p>
      </div>

      {/* Country picker */}
      <div className="bg-[#0d0a14] border border-white/5 rounded-md p-4 md:p-5">
        <Label className="text-[10px] uppercase tracking-widest text-white/50">Country</Label>
        <select
          data-testid="numbers-country"
          value={country}
          onChange={(e) => setCountry(e.target.value)}
          className="mt-2 w-full md:w-96 bg-black/40 border border-emerald-500/25 rounded-md px-3 py-2.5 text-sm text-white focus:outline-none focus:border-emerald-400"
        >
          {NUMBERS_COUNTRIES.map((c) => (
            <option key={c.code} value={c.code} className="bg-[#0a1a0a]">
              {c.flag}  {c.name}
            </option>
          ))}
        </select>
        <p className="text-[11px] text-white/40 mt-2">Stock varies by country — if a country has no numbers left, try &quot;Any country&quot; or another.</p>
      </div>

      {/* Product grid */}
      <div>
        <div className="text-[10px] uppercase tracking-widest text-white/50 mb-3">Available services</div>
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="w-6 h-6 animate-spin text-emerald-400" />
          </div>
        ) : products.length === 0 ? (
          <div className="text-white/50 text-sm bg-[#0d0a14] border border-white/5 rounded-md p-8 text-center">
            No services available right now — please try again later.
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
            {products.map((p) => (
              <div
                key={p.id}
                data-testid={`number-product-${p.id}`}
                className="bg-[#0d0a14] border border-emerald-500/15 hover:border-emerald-400/60 transition rounded-md p-4 flex flex-col items-center text-center"
              >
                <div className="mb-2 flex items-center justify-center h-12">
                  <AppIcon name={p.id} size={40} />
                </div>
                <div className="font-bold text-white">{p.name}</div>
                <div className="font-display font-black text-2xl text-emerald-400 my-2">${p.price.toFixed(2)}</div>
                <button
                  onClick={() => buy(p)}
                  disabled={buying === p.id || balance < p.price}
                  data-testid={`buy-number-${p.id}`}
                  className="mt-1 w-full py-2 rounded-md text-xs font-bold uppercase tracking-wider bg-emerald-500 text-black hover:bg-emerald-400 disabled:opacity-40 disabled:cursor-not-allowed transition"
                >
                  {buying === p.id ? <Loader2 className="w-4 h-4 animate-spin inline" /> : balance < p.price ? "Low balance" : "Buy"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Active rentals */}
      {activeOrders.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="text-[10px] uppercase tracking-widest text-white/50">Active rentals — waiting for SMS</div>
            <button onClick={loadOrders} className="text-[11px] text-emerald-400 hover:text-emerald-300 inline-flex items-center gap-1" data-testid="refresh-orders">
              <RefreshCw className="w-3 h-3" /> Refresh
            </button>
          </div>
          <div className="space-y-3">
            {activeOrders.map((o) => (
              <NumberOrderCard key={o.id} order={o} onCancel={cancel} onFinish={finish} />
            ))}
          </div>
        </div>
      )}

      {/* History */}
      {pastOrders.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-widest text-white/50 mb-3">History</div>
          <div className="space-y-2 opacity-75">
            {pastOrders.slice(0, 10).map((o) => (
              <div key={o.id} className="flex items-center justify-between bg-[#0d0a14] border border-white/5 rounded-md px-3 py-2 text-xs" data-testid={`past-order-${o.id}`}>
                <span className="font-mono text-white/80">{o.phone || "(no number)"}</span>
                <span className="uppercase tracking-wider text-white/50">{o.product}</span>
                <span className="uppercase tracking-wider text-white/50">{o.status}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function NumberOrderCard({ order, onCancel, onFinish }) {
  const [copying, setCopying] = useState(false);
  const smsList = Array.isArray(order.sms) ? order.sms : [];
  const copy = async () => {
    if (!order.phone) return;
    try {
      await navigator.clipboard.writeText(order.phone);
      setCopying(true);
      setTimeout(() => setCopying(false), 1200);
    } catch {}
  };
  return (
    <div className="bg-[#0d0a14] border border-emerald-500/25 rounded-md p-4" data-testid={`active-order-${order.id}`}>
      <div className="flex flex-wrap items-center gap-3 justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-md bg-emerald-500/15 border border-emerald-500/40 flex items-center justify-center">
            <Phone className="w-4 h-4 text-emerald-300" />
          </div>
          <div className="min-w-0">
            <div className="font-mono text-lg text-white truncate" data-testid={`order-phone-${order.id}`}>{order.phone || "—"}</div>
            <div className="text-[11px] text-white/50 uppercase tracking-wider">
              {order.product} · {order.country} · <span className="text-emerald-300">{order.status || "waiting"}</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={copy} className="px-3 py-1.5 rounded-md text-[11px] font-bold uppercase tracking-wider bg-white/5 hover:bg-white/10 text-white/80 inline-flex items-center gap-1" data-testid={`copy-phone-${order.id}`}>
            <Copy className="w-3 h-3" /> {copying ? "Copied!" : "Copy"}
          </button>
          <button onClick={() => onFinish(order.id)} className="px-3 py-1.5 rounded-md text-[11px] font-bold uppercase tracking-wider bg-emerald-500 text-black hover:bg-emerald-400" data-testid={`finish-order-${order.id}`}>
            Finish
          </button>
          <button onClick={() => onCancel(order.id)} className="px-3 py-1.5 rounded-md text-[11px] font-bold uppercase tracking-wider bg-red-500/20 border border-red-500/40 text-red-300 hover:bg-red-500/30" data-testid={`cancel-order-${order.id}`}>
            Cancel &amp; refund
          </button>
        </div>
      </div>
      <div className="mt-3 pt-3 border-t border-white/5">
        <div className="text-[10px] uppercase tracking-widest text-white/40 mb-2">SMS messages received</div>
        {smsList.length === 0 ? (
          <div className="text-xs text-white/50 flex items-center gap-2">
            <Loader2 className="w-3 h-3 animate-spin" /> Waiting for SMS… codes usually arrive in 10–60 seconds.
          </div>
        ) : (
          <div className="space-y-1.5">
            {smsList.map((s, i) => (
              <div key={i} className="bg-black/40 rounded-sm px-3 py-2 text-sm text-white/90 break-words" data-testid={`sms-${order.id}-${i}`}>
                <span className="font-mono text-emerald-300 mr-2">{s.sender || s.from || "SMS"}</span>
                {s.text || s.body || s.code || JSON.stringify(s)}
              </div>
            ))}
          </div>
        )}
      </div>
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
