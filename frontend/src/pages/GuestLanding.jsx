import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Sparkles, Loader2, X, MessageCircle, ShoppingBag } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useLang, LanguagePicker } from "@/context/LanguageContext";
import GoalNotifier from "@/components/GoalNotifier";
import TikTokLookupBox from "@/components/TikTokLookupBox";

// Fake "social proof" toasts on first visit — 2 randomised purchase alerts,
// spaced 6-10s apart so they feel organic.
const FAKE_BUYS = [
  { user: "Milan B.",   country: "🇷🇸", service: "TikTok Followers",     qty: 1500, ago: "just now" },
  { user: "Lena K.",    country: "🇩🇪", service: "Instagram Likes",       qty: 500,  ago: "2 min ago" },
  { user: "Nadia V.",   country: "🇺🇸", service: "YouTube Views",         qty: 5000, ago: "just now" },
  { user: "Tarik S.",   country: "🇧🇦", service: "Auto-Live TikTok Boost", qty: 250,  ago: "1 min ago" },
  { user: "Alexis T.",  country: "🇬🇧", service: "Instagram Followers",   qty: 1000, ago: "just now" },
  { user: "Petra M.",   country: "🇦🇹", service: "TikTok Live Views",     qty: 300,  ago: "3 min ago" },
  { user: "Sean R.",    country: "🇺🇸", service: "YouTube Subscribers",   qty: 100,  ago: "just now" },
  { user: "Jovana P.",  country: "🇷🇸", service: "Instagram Story Views", qty: 800,  ago: "1 min ago" },
];

function FakePurchaseAlerts() {
  useEffect(() => {
    const shown = new Set();
    const pick = () => {
      const remaining = FAKE_BUYS.filter((_, i) => !shown.has(i));
      if (!remaining.length) return null;
      const idx = FAKE_BUYS.indexOf(remaining[Math.floor(Math.random() * remaining.length)]);
      shown.add(idx);
      return FAKE_BUYS[idx];
    };
    const show = () => {
      const b = pick(); if (!b) return;
      toast(
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-md bg-emerald-500/25 border border-emerald-500/40 flex items-center justify-center text-lg">
            {b.country}
          </div>
          <div className="text-sm leading-tight">
            <div className="font-bold text-emerald-300">{b.user} just bought</div>
            <div className="text-white/80 text-xs">{b.service} × <b>{b.qty.toLocaleString()}</b> · <span className="text-white/40">{b.ago}</span></div>
          </div>
        </div>,
        { duration: 5500, position: "bottom-left", className: "fake-buy-toast" }
      );
    };
    // 2 alerts per user visit, first ~4s in, second ~10s later
    const t1 = setTimeout(show, 4000);
    const t2 = setTimeout(show, 14000);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, []);
  return null;
}

// Green-themed guest landing shown on /client/dashboard when the user is NOT
// signed in.  Renders a compact green header with Sign-in / Sign-up buttons
// on the right and a two-column preview (live orders left, public chat right)
// with a welcome card in the middle.  Clicking either button opens an inline
// auth modal so users never leave the dashboard shell.
export default function GuestLanding() {
  const [authOpen, setAuthOpen] = useState(null); // 'login' | 'signup' | null
  const { t } = useLang();

  return (
    <div className="min-h-screen flex flex-col text-white bg-[#0a1a0a] theme-green" data-testid="guest-landing">
      {/* Header */}
      <header className="bg-[#0d2b12] sticky top-0 z-20 shadow-lg shadow-emerald-900/40 border-b border-emerald-500/20">
        <div className="flex items-center h-16 px-4 md:px-8 gap-4">
          <div className="flex items-center gap-2">
            <div className="w-9 h-9 rounded-md bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-emerald-300" strokeWidth={2.5} />
            </div>
            <span className="font-display font-black text-base text-white tracking-tight">
              Better<span className="text-emerald-300">Social</span>
            </span>
          </div>
          <div className="flex-1" />
          <div className="flex items-center gap-2">
            <LanguagePicker />
            <a
              href="https://discord.gg/namelessstore"
              target="_blank"
              rel="noreferrer"
              data-testid="guest-discord-btn"
              title="Join our Discord — discord.gg/namelessstore"
              className="hidden sm:inline-flex items-center gap-1.5 px-3 py-2 rounded-md text-xs font-bold uppercase tracking-wider text-white bg-[#5865F2] hover:bg-[#4752C4] transition"
            >
              <svg viewBox="0 0 71 55" className="w-4 h-4" fill="currentColor" aria-hidden><path d="M60.1 4.9A58.5 58.5 0 0 0 45.4.4l-.7 1.2c5.3.9 10.2 2.8 14.5 5.5-4.5-2.2-9.5-3.8-14.9-4.4-1.8-.2-3.5-.4-5.3-.4h-.1c-2 0-4.1.2-6 .4-4.4.5-8.6 1.6-12.6 3.2-2.2.9-4.3 1.9-6.3 3.2 4.3-2.6 9.2-4.6 14.5-5.5L28 .4a58.4 58.4 0 0 0-14.6 4.5A70.1 70.1 0 0 0 .5 43.1a54.9 54.9 0 0 0 15.6 7.9c1.3-1.7 2.4-3.5 3.4-5.4a34.6 34.6 0 0 1-5.4-2.6l1.3-1c9.4 4.4 19.6 4.4 28.9 0l1.3 1c-1.7 1-3.5 1.9-5.4 2.6 1 1.9 2.1 3.7 3.4 5.4 5.5-1.7 10.8-4.3 15.6-7.9-.5-14.1-3.9-27.7-9-38.2ZM24.5 35.6c-3.4 0-6.1-3.1-6.1-6.9s2.7-6.9 6.1-6.9 6.2 3.1 6.1 6.9c0 3.8-2.7 6.9-6.1 6.9Zm22.6 0c-3.4 0-6.1-3.1-6.1-6.9s2.7-6.9 6.1-6.9 6.2 3.1 6.1 6.9c0 3.8-2.7 6.9-6.1 6.9Z"/></svg>
              Discord
            </a>
            <button
              onClick={() => setAuthOpen("login")}
              data-testid="guest-signin-btn"
              className="px-3 md:px-4 py-2 rounded-md text-xs font-bold uppercase tracking-wider text-emerald-200 border border-emerald-500/40 hover:bg-emerald-500/15 transition"
            >
              {t("sign_in")}
            </button>
            <button
              onClick={() => setAuthOpen("signup")}
              data-testid="guest-signup-btn"
              className="px-3 md:px-4 py-2 rounded-md text-xs font-bold uppercase tracking-wider text-black bg-emerald-400 hover:bg-emerald-300 transition"
            >
              {t("sign_up")}
            </button>
          </div>
        </div>
      </header>

      {/* Main preview */}
      <main className="flex-1 w-full max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-[280px_1fr_320px] gap-4 p-4 md:p-6">
        <GuestOrdersFeed />
        <div className="space-y-4">
          <GuestWelcome onSignIn={() => setAuthOpen("login")} onSignUp={() => setAuthOpen("signup")} />
          <TikTokLookupBox />
        </div>
        <GuestPublicChat />
      </main>

      {/* Guest footer — matches the signed-in dashboard footer 1:1 */}
      <footer className="border-t border-emerald-500/20 bg-[#0d2b12] py-4 px-4 md:px-8 text-center" data-testid="guest-footer">
        <div className="max-w-7xl mx-auto flex items-center justify-center gap-3 flex-wrap text-[10px] uppercase tracking-widest text-white/60">
          <span className="inline-flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span className="font-bold">© {new Date().getFullYear()} BetterSocial</span>
          </span>
          <span className="text-emerald-500/40">·</span>
          <span>
            Development by <span className="text-emerald-300 font-bold">BK</span> &amp; CEO <span className="text-emerald-300 font-bold">Sinester</span>
          </span>
        </div>
      </footer>

      {authOpen && <AuthModal mode={authOpen} onClose={() => setAuthOpen(null)} switchMode={setAuthOpen} />}
      <GoalNotifier />
      <FakePurchaseAlerts />
    </div>
  );
}

function GuestWelcome({ onSignIn, onSignUp }) {
  const { t } = useLang();
  return (
    <div className="bg-gradient-to-br from-[#0d2b12] to-[#0a1a0a] rounded-lg border border-emerald-500/30 p-8 md:p-10 flex flex-col items-center justify-center text-center min-h-[300px]">
      <div className="w-14 h-14 rounded-full bg-emerald-500/20 border border-emerald-500/50 flex items-center justify-center mb-4">
        <Sparkles className="w-6 h-6 text-emerald-300" />
      </div>
      <h1 className="font-display text-3xl md:text-5xl font-black text-white mb-3">
        {t("welcome_to")} <span className="text-emerald-300">BetterSocial</span>
      </h1>
      <p className="text-white/70 text-sm md:text-base max-w-md">
        {t("welcome_sub")}
      </p>
      <div className="mt-6 flex flex-wrap gap-3 justify-center">
        <button onClick={onSignIn} data-testid="guest-cta-signin"
          className="px-6 py-3 rounded-md text-sm font-bold uppercase tracking-wider bg-emerald-500 text-black hover:bg-emerald-400 transition">
          {t("sign_in")}
        </button>
        <button onClick={onSignUp} data-testid="guest-cta-signup"
          className="px-6 py-3 rounded-md text-sm font-bold uppercase tracking-wider border border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/10 transition">
          {t("create_account")}
        </button>
      </div>
    </div>
  );
}

function GuestOrdersFeed() {
  const [orders, setOrders] = useState([]);
  useEffect(() => {
    const tick = async () => {
      try {
        const r = await api.get("/orders/global?limit=15");
        setOrders(r.data.orders || []);
      } catch { /* endpoint optional */ }
    };
    tick();
    const t = setInterval(tick, 8000);
    return () => clearInterval(t);
  }, []);
  return (
    <aside className="bg-[#0d2b12] rounded-lg border border-emerald-500/20 p-3 h-[520px] overflow-hidden flex flex-col" data-testid="guest-orders-feed">
      <div className="flex items-center gap-2 mb-3">
        <ShoppingBag className="w-4 h-4 text-emerald-300" />
        <div className="text-[10px] uppercase tracking-widest text-emerald-300 font-bold">Latest orders</div>
      </div>
      <div className="flex-1 overflow-y-auto space-y-1.5 no-scrollbar">
        {orders.length === 0 && <div className="text-white/40 text-xs">No orders yet.</div>}
        {orders.map((o, i) => (
          <div key={o.id || i} className="text-[11px] bg-black/30 rounded-sm px-2 py-1.5">
            <div className="flex justify-between gap-2">
              <span className="text-white/60 truncate">@{o.masked_username || "user"}</span>
              <span className="text-emerald-300 font-mono">${Number(o.charge || 0).toFixed(2)}</span>
            </div>
            <div className="text-white/40 truncate">{o.service_name || "—"}</div>
          </div>
        ))}
      </div>
    </aside>
  );
}

function GuestPublicChat() {
  const [msgs, setMsgs] = useState([]);
  const bottomRef = useRef(null);
  useEffect(() => {
    const tick = async () => {
      try {
        const r = await api.get("/public-chat/messages?limit=30");
        setMsgs(r.data.messages || []);
      } catch { /* endpoint optional */ }
    };
    tick();
    const t = setInterval(tick, 5000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs.length]);
  return (
    <aside className="bg-[#0d2b12] rounded-lg border border-emerald-500/20 p-3 h-[520px] overflow-hidden flex flex-col" data-testid="guest-public-chat">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <MessageCircle className="w-4 h-4 text-emerald-300" />
          <div className="text-[10px] uppercase tracking-widest text-emerald-300 font-bold">Community chat</div>
        </div>
        <span className="text-[9px] text-emerald-400/60 uppercase tracking-widest">read-only</span>
      </div>
      <div className="flex-1 overflow-y-auto space-y-1.5 no-scrollbar text-xs" data-testid="guest-chat-messages">
        {msgs.length === 0 && <div className="text-white/40 text-center py-6">Chat is quiet — be the first to say hi (sign in required).</div>}
        {msgs.map((m) => {
          const roleTag = m.role === "owner" ? "OWNER" : m.role === "admin" ? "ADMIN" : m.role === "moderator" || m.role === "staff" ? "STAFF" : null;
          const roleCls = m.role === "owner" ? "text-amber-300 bg-amber-500/20 border-amber-500/40" : m.role === "admin" ? "text-emerald-200 bg-emerald-500/20 border-emerald-500/40" : "text-sky-200 bg-sky-500/20 border-sky-500/40";
          return (
            <div key={m.id} className="bg-black/30 rounded-sm px-2 py-1.5" data-testid={`guest-msg-${m.id}`}>
              <div className="flex items-center gap-1.5 mb-0.5">
                <span className="text-emerald-300 font-bold">@{m.username || m.sender_username || "user"}</span>
                {roleTag && (
                  <span className={`text-[8px] px-1 py-px rounded-sm border font-bold uppercase tracking-wider ${roleCls}`}>{roleTag}</span>
                )}
                <span className="ml-auto text-[9px] text-emerald-400/40">
                  {m.created_at ? new Date(m.created_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : ""}
                </span>
              </div>
              <div className="text-white/80 break-words">{m.text || m.content}</div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
      <div className="mt-2 text-[10px] text-white/40 text-center">Sign in to join the conversation.</div>
    </aside>
  );
}

// Play a short chime via Web Audio API — no asset file needed.
function playLoginChime() {
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    const ctx = new AC();
    const now = ctx.currentTime;
    [523.25, 659.25, 783.99].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const g = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      osc.connect(g); g.connect(ctx.destination);
      g.gain.setValueAtTime(0, now + i * 0.12);
      g.gain.linearRampToValueAtTime(0.18, now + i * 0.12 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.001, now + i * 0.12 + 0.18);
      osc.start(now + i * 0.12);
      osc.stop(now + i * 0.12 + 0.2);
    });
    setTimeout(() => ctx.close(), 800);
  } catch { /* audio blocked — silent */ }
}

function AuthModal({ mode, onClose, switchMode }) {
  const isLogin = mode === "login";
  const { setAuth } = useAuth();
  const [captcha, setCaptcha] = useState(null);
  const [form, setForm] = useState({ identifier: "", username: "", email: "", password: "", answer: "" });
  const [submitting, setSubmitting] = useState(false);
  const [forgotOpen, setForgotOpen] = useState(false);
  const [forgotEmail, setForgotEmail] = useState("");
  const [forgotSending, setForgotSending] = useState(false);

  const loadCaptcha = async () => {
    try {
      const r = await api.get("/auth/captcha");
      setCaptcha(r.data);
    } catch { /* ignore */ }
  };
  useEffect(() => { loadCaptcha(); }, [mode]);

  const submit = async (e) => {
    e.preventDefault();
    if (!captcha) return;
    setSubmitting(true);
    try {
      if (isLogin) {
        const r = await api.post("/auth/login", {
          identifier: form.identifier.trim(),
          password: form.password,
          captcha_id: captcha.id,
          captcha_answer: form.answer,
        });
        setAuth(r.data.token, r.data.user);
        playLoginChime();
        toast.success(`✅ Welcome back, ${r.data.user.username}!`);
        onClose();
      } else {
        const r = await api.post("/auth/register", {
          username: form.username.trim(),
          email: form.email.trim().toLowerCase(),
          password: form.password,
          captcha_id: captcha.id,
          captcha_answer: form.answer,
        });
        setAuth(r.data.token, r.data.user);
        playLoginChime();
        toast.success(`🎉 Account created — welcome, ${r.data.user.username}!`);
        onClose();
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || (isLogin ? "Login failed" : "Registration failed"));
      loadCaptcha(); // refresh captcha on failure
      setForm((f) => ({ ...f, answer: "" }));
    } finally { setSubmitting(false); }
  };

  const sendForgot = async (e) => {
    e.preventDefault();
    const em = forgotEmail.trim().toLowerCase();
    if (!em) { toast.error("Enter your email"); return; }
    setForgotSending(true);
    try {
      await api.post("/auth/forgot-password", { email: em });
      toast.success("✉️ If that email exists, a reset link is on its way. Check spam too.");
      setForgotOpen(false); setForgotEmail("");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Could not send reset email");
    } finally { setForgotSending(false); }
  };

  return (
    <div className="fixed inset-0 z-[90] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose} data-testid="auth-modal-backdrop">
      <div className="w-full max-w-lg bg-gradient-to-br from-emerald-500/15 via-[#0e2f18] to-[#0a1a0a] border-2 border-emerald-400/50 rounded-2xl p-8 md:p-10 shadow-[0_25px_80px_-15px_rgba(16,185,129,0.4)] relative" onClick={(e) => e.stopPropagation()} data-testid={isLogin ? "login-modal" : "signup-modal"}>
        <button onClick={onClose} className="absolute top-4 right-4 w-9 h-9 rounded-md hover:bg-white/10 text-white/70 flex items-center justify-center transition" aria-label="Close">
          <X className="w-5 h-5" />
        </button>
        <div className="flex items-center gap-3 mb-4">
          <div className="w-11 h-11 rounded-lg bg-gradient-to-br from-emerald-400 to-emerald-600 flex items-center justify-center shadow-lg shadow-emerald-500/30">
            <Sparkles className="w-5 h-5 text-white" strokeWidth={2.5} />
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-widest text-emerald-300 font-bold">BetterSocial</div>
            <h2 className="font-display font-black text-2xl md:text-3xl text-white leading-tight">{isLogin ? "Welcome back" : "Create your account"}</h2>
          </div>
        </div>
        <p className="text-white/60 text-sm mb-6">{isLogin ? "Sign in to place orders, deposit crypto and play games." : "Free to join. No card required — deposit later with crypto."}</p>

        {/* One-click Google — no password, no email verification, instant */}
        <button
          type="button"
          onClick={() => {
            // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
            const redirectUrl = window.location.origin + "/client/dashboard";
            window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
          }}
          data-testid={isLogin ? "modal-google-signin" : "modal-google-signup"}
          className="w-full inline-flex items-center justify-center gap-3 py-3 rounded-lg bg-white hover:bg-white/95 text-black font-bold text-sm shadow-lg transition mb-4"
        >
          <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
            <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
            <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
            <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
            <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
          </svg>
          {isLogin ? "Continue with Google" : "Sign up with Google"}
        </button>

        <div className="flex items-center gap-3 mb-4">
          <div className="flex-1 h-px bg-white/10" />
          <span className="text-[10px] uppercase tracking-widest text-white/40 font-bold">or use email</span>
          <div className="flex-1 h-px bg-white/10" />
        </div>

        <form onSubmit={submit} className="space-y-4">
          {isLogin ? (
            <input required value={form.identifier} onChange={(e) => setForm({ ...form, identifier: e.target.value })}
              placeholder="Username or email"
              data-testid="modal-login-identifier"
              className="w-full bg-emerald-950/40 border-2 border-emerald-500/25 rounded-lg px-4 py-3 text-base text-white outline-none focus:border-emerald-400 transition placeholder-white/40" />
          ) : (
            <>
              <input required minLength={3} maxLength={30} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })}
                placeholder="Username" data-testid="modal-signup-username"
                className="w-full bg-emerald-950/40 border-2 border-emerald-500/25 rounded-lg px-4 py-3 text-base text-white outline-none focus:border-emerald-400 transition placeholder-white/40" />
              <input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="Email" data-testid="modal-signup-email"
                className="w-full bg-emerald-950/40 border-2 border-emerald-500/25 rounded-lg px-4 py-3 text-base text-white outline-none focus:border-emerald-400 transition placeholder-white/40" />
            </>
          )}
          <input required type="password" minLength={isLogin ? 1 : 8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })}
            placeholder="Password" data-testid="modal-auth-password"
            className="w-full bg-emerald-950/40 border-2 border-emerald-500/25 rounded-lg px-4 py-3 text-base text-white outline-none focus:border-emerald-400 transition placeholder-white/40" />

          <div className="flex items-center gap-2 bg-emerald-950/40 border-2 border-emerald-500/25 rounded-lg px-3 py-1" data-testid="modal-captcha">
            <span className="text-sm text-emerald-200 font-mono whitespace-nowrap">{captcha?.question || "…"}</span>
            <input required value={form.answer} onChange={(e) => setForm({ ...form, answer: e.target.value })}
              placeholder="Answer" data-testid="modal-captcha-answer"
              className="flex-1 bg-transparent px-2 py-2 text-base text-white outline-none placeholder-white/30" />
            <button type="button" onClick={loadCaptcha} className="text-emerald-300 hover:text-emerald-200 text-lg px-1" title="Refresh captcha">↻</button>
          </div>

          <button type="submit" disabled={submitting || !captcha} data-testid={isLogin ? "modal-login-submit" : "modal-signup-submit"}
            className="w-full py-4 rounded-lg font-display font-black text-base uppercase tracking-widest bg-gradient-to-r from-emerald-400 to-emerald-500 text-black hover:from-emerald-300 hover:to-emerald-400 transition disabled:opacity-50 inline-flex items-center justify-center gap-2 shadow-lg shadow-emerald-500/30">
            {submitting ? <Loader2 className="w-5 h-5 animate-spin" /> : (isLogin ? "Sign in" : "Create account")}
          </button>
        </form>

        {isLogin && (
          <div className="mt-3 text-center">
            <button
              type="button"
              onClick={() => setForgotOpen(true)}
              data-testid="modal-forgot-password"
              className="text-xs text-emerald-300/80 hover:text-emerald-200 underline underline-offset-2"
            >
              Forgot password?
            </button>
          </div>
        )}

        <div className="mt-6 text-center text-sm text-white/60">
          {isLogin ? "New here? " : "Already have an account? "}
          <button onClick={() => switchMode(isLogin ? "signup" : "login")}
            data-testid={isLogin ? "switch-to-signup" : "switch-to-login"}
            className="text-emerald-300 hover:text-emerald-200 font-bold">
            {isLogin ? "Create an account" : "Sign in"}
          </button>
        </div>
      </div>

      {forgotOpen && (
        <div className="fixed inset-0 z-[95] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4"
             onClick={() => !forgotSending && setForgotOpen(false)} data-testid="forgot-modal-backdrop">
          <div onClick={(e) => e.stopPropagation()} data-testid="forgot-modal"
               className="w-full max-w-md bg-gradient-to-br from-emerald-500/15 via-[#0e2f18] to-[#0a1a0a] border-2 border-emerald-400/50 rounded-2xl p-8 shadow-2xl">
            <h3 className="font-display font-black text-xl text-white mb-2">Reset your password</h3>
            <p className="text-sm text-white/60 mb-5">
              Enter the email you signed up with. We'll send you a reset link — check your spam too.
            </p>
            <form onSubmit={sendForgot} className="space-y-4">
              <input required type="email" value={forgotEmail}
                onChange={(e) => setForgotEmail(e.target.value)}
                placeholder="you@example.com"
                data-testid="forgot-email-input"
                className="w-full bg-emerald-950/40 border-2 border-emerald-500/25 rounded-lg px-4 py-3 text-base text-white outline-none focus:border-emerald-400 transition placeholder-white/40" />
              <div className="flex gap-2">
                <button type="button" onClick={() => setForgotOpen(false)} disabled={forgotSending}
                  className="flex-1 py-3 rounded-lg border border-white/15 text-white/80 hover:bg-white/5 font-bold text-sm">
                  Cancel
                </button>
                <button type="submit" disabled={forgotSending} data-testid="forgot-submit"
                  className="flex-1 py-3 rounded-lg bg-emerald-400 hover:bg-emerald-300 text-black font-bold text-sm disabled:opacity-50 inline-flex items-center justify-center gap-2">
                  {forgotSending ? <Loader2 className="w-4 h-4 animate-spin" /> : "Send reset link"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
