import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Input } from "@/components/ui/input";
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
  const chatEndRef = useRef(null);

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
    const statInt = setInterval(loadStats, 12000);
    const msgInt = setInterval(loadMessages, POLL_MS);
    return () => {
      clearInterval(statInt);
      clearInterval(msgInt);
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
        <div className="mb-6">
          <h1 className="font-display text-2xl md:text-4xl font-black tracking-tight">
            Hey <span className="gradient-text">{user.username}</span>.
          </h1>
          <p className="text-white/50 text-sm mt-1">
            Your overview and the community lobby — all in one place.
          </p>
        </div>

        <div className="grid lg:grid-cols-[2fr_1.2fr] gap-6">
          {/* LEFT: Stats + quick actions */}
          <div>
            <div className="grid grid-cols-2 gap-3 md:gap-4 mb-6">
              <StatBox
                icon={Wallet}
                label="Balance"
                value={stats ? `$${Number(stats.balance).toFixed(2)}` : "—"}
                color="#FF007F"
                testId="stat-balance"
              />
              <StatBox
                icon={Users}
                label="Online Users"
                value={stats ? stats.online_users : "—"}
                color="#00E5FF"
                testId="stat-online"
              />
              <StatBox
                icon={ShoppingBag}
                label="Total Orders"
                value={stats ? stats.total_orders : "—"}
                color="#7000FF"
                testId="stat-orders"
              />
              <StatBox
                icon={UserCheck}
                label="Registered Users"
                value={stats ? stats.registered_users : "—"}
                color="#FFB800"
                testId="stat-registered"
              />
            </div>

            <div className="bg-[#0d0a14] border border-white/5 rounded-sm p-6">
              <h2 className="font-display font-bold text-lg mb-4">Shortcuts</h2>
              <div className="grid sm:grid-cols-2 gap-3">
                <Link
                  to="/"
                  data-testid="shortcut-catalog"
                  className="p-4 rounded-sm bg-[#1a1525] hover:bg-[#2a1f3a] transition border border-white/5"
                >
                  <div className="text-xs uppercase tracking-wider text-[#FF007F] mb-1">Catalog</div>
                  <div className="font-bold">Browse all services</div>
                </Link>
                <Link
                  to="/ai-buy"
                  data-testid="shortcut-ai"
                  className="p-4 rounded-sm bg-[#1a1525] hover:bg-[#2a1f3a] transition border border-white/5"
                >
                  <div className="text-xs uppercase tracking-wider text-[#00E5FF] mb-1">AI</div>
                  <div className="font-bold">Try Buy Via AI</div>
                </Link>
              </div>
            </div>
          </div>

          {/* RIGHT: Community chat */}
          <aside
            data-testid="community-chat"
            className="bg-[#0d0a14] border border-white/5 rounded-sm flex flex-col h-[520px] md:h-[640px]"
          >
            <div className="px-4 md:px-5 py-3 border-b border-white/5 flex items-center justify-between">
              <div>
                <h2 className="font-display font-bold">Community Chat</h2>
                <p className="text-[10px] uppercase tracking-wider text-white/40">
                  Be kind · be useful
                </p>
              </div>
              <div className="text-[10px] uppercase tracking-wider text-[#00E5FF]">LIVE</div>
            </div>

            <div
              className="flex-1 overflow-y-auto px-3 md:px-4 py-3 space-y-2"
              data-testid="chat-messages"
            >
              {messages.length === 0 && (
                <div className="text-center text-white/30 text-xs py-10">
                  No messages yet — say hi!
                </div>
              )}
              {messages.map((m) => (
                <Msg key={m.id} m={m} />
              ))}
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
            {(user.role === "owner" || user.role === "moderator") && (
              <div className="px-3 pb-3 text-[10px] text-white/40">
                Staff cmd: <span className="font-mono text-[#FF007F]">/mute @username 10m</span>
              </div>
            )}
          </aside>
        </div>
      </main>
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
