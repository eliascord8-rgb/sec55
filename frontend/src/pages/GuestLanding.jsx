import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Sparkles, Loader2, X, MessageCircle, ShoppingBag } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useLang, LanguagePicker } from "@/context/LanguageContext";

// Green-themed guest landing shown on /client/dashboard when the user is NOT
// signed in.  Renders a compact green header with Sign-in / Sign-up buttons
// on the right and a two-column preview (live orders left, public chat right)
// with a welcome card in the middle.  Clicking either button opens an inline
// auth modal so users never leave the dashboard shell.
export default function GuestLanding() {
  const [authOpen, setAuthOpen] = useState(null); // 'login' | 'signup' | null
  const { t } = useLang();

  return (
    <div className="min-h-screen text-white bg-[#0a1a0a] theme-green" data-testid="guest-landing">
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
      <main className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-[280px_1fr_320px] gap-4 p-4 md:p-6">
        <GuestOrdersFeed />
        <GuestWelcome onSignIn={() => setAuthOpen("login")} onSignUp={() => setAuthOpen("signup")} />
        <GuestPublicChat />
      </main>

      {authOpen && <AuthModal mode={authOpen} onClose={() => setAuthOpen(null)} switchMode={setAuthOpen} />}
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

        <div className="mt-6 text-center text-sm text-white/60">
          {isLogin ? "New here? " : "Already have an account? "}
          <button onClick={() => switchMode(isLogin ? "signup" : "login")}
            data-testid={isLogin ? "switch-to-signup" : "switch-to-login"}
            className="text-emerald-300 hover:text-emerald-200 font-bold">
            {isLogin ? "Create an account" : "Sign in"}
          </button>
        </div>
      </div>
    </div>
  );
}
