import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Input } from "@/components/ui/input";
import { Bot, Sparkles, Send, Loader2, ArrowLeft, CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";

const GREETING = {
  role: "assistant",
  text:
    "Hi! I'm Better Social AI ✨  Tell me what you'd like to boost today — TikTok Live Likes, Live Views, or Live Comments. I speak any language, just write to me naturally.",
};

const READY_RE = /READY_TO_ORDER:\s*(\{[^}]*\})/;

export default function AIBuy() {
  const { user, loading, authedApi } = useAuth();
  const nav = useNavigate();
  const [messages, setMessages] = useState([GREETING]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [orderResult, setOrderResult] = useState(null);
  const endRef = useRef(null);
  const sessionIdRef = useRef(null);

  useEffect(() => {
    if (!loading && !user) nav("/client");
  }, [loading, user, nav]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, sending]);

  const tryExecuteOrder = async (assistantText) => {
    const m = assistantText.match(READY_RE);
    if (!m) return;
    try {
      const data = JSON.parse(m[1]);
      if (!data.service_type || !data.link || !data.quantity || !data.coupon_code) return;
      // Execute
      const r = await authedApi().post("/ai/confirm-order", data);
      setOrderResult({ ok: true, ...r.data });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: `✅ Finish. Order has been sent — success! SMM Order ID: ${r.data.smm_order_id} · Amount charged: $${r.data.price.toFixed(2)}`,
        },
      ]);
    } catch (err) {
      const reason = err.response?.data?.detail || err.message || "Order failed";
      setOrderResult({ ok: false, reason });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: `❌ Sorry — couldn't place the order: ${reason}. Please contact us via live chat and we'll help you right away.`,
        },
      ]);
    }
  };

  const send = async (e) => {
    e?.preventDefault();
    const t = text.trim();
    if (!t || sending) return;
    const userMsg = { role: "user", text: t };
    const history = [...messages, userMsg];
    setMessages(history);
    setText("");
    setSending(true);
    try {
      const r = await authedApi().post("/ai/chat", {
        messages: history,
        session_id: sessionIdRef.current,
      });
      sessionIdRef.current = r.data.session_id;
      const reply = r.data.reply;
      setMessages((prev) => [...prev, { role: "assistant", text: reply }]);
      // If the bot is ready to order, execute
      if (READY_RE.test(reply)) {
        await tryExecuteOrder(reply);
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "AI error");
    } finally {
      setSending(false);
    }
  };

  const openLiveChat = () => {
    if (window.Tawk_API && typeof window.Tawk_API.maximize === "function") {
      window.Tawk_API.maximize();
    } else {
      window.location.href = "mailto:balkinstr@web.de";
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
    <div className="min-h-screen bg-[#050505] text-white flex flex-col">
      <header className="border-b border-white/5 bg-[#0d0a14]/90 backdrop-blur sticky top-0 z-10">
        <div className="max-w-3xl mx-auto px-4 md:px-10 h-14 md:h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-sm gradient-pp flex items-center justify-center">
              <Sparkles className="w-3.5 h-3.5" strokeWidth={2.5} />
            </div>
            <span className="font-display font-black text-base">
              Better<span className="text-[#FF007F]">Social</span>
            </span>
          </Link>
          <Link
            to="/client/dashboard"
            data-testid="ai-back-dash"
            className="text-xs uppercase tracking-wider text-white/60 hover:text-white flex items-center gap-1"
          >
            <ArrowLeft className="w-3 h-3" /> Dashboard
          </Link>
        </div>
      </header>

      <main className="flex-1 max-w-3xl w-full mx-auto px-3 md:px-6 py-4 md:py-6 flex flex-col">
        {/* Title */}
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-sm gradient-pp flex items-center justify-center">
            <Bot className="w-5 h-5" />
          </div>
          <div>
            <h1 className="font-display text-xl md:text-2xl font-black">Better Social AI</h1>
            <p className="text-[11px] uppercase tracking-wider text-white/40">
              Talk naturally · I speak your language
            </p>
          </div>
        </div>

        {/* Messages */}
        <div
          className="flex-1 overflow-y-auto space-y-3 md:space-y-4 pr-1 pb-4"
          data-testid="ai-messages"
        >
          {messages.map((m, i) => (
            <Bubble key={i} m={m} />
          ))}
          {sending && (
            <Bubble m={{ role: "assistant", text: "…" }} typing />
          )}
          <div ref={endRef} />
        </div>

        {/* Result panel (sticky success/fail) */}
        {orderResult && (
          <div
            className={`mb-3 p-3 rounded-sm border text-sm flex items-start gap-3 ${
              orderResult.ok
                ? "bg-[#00E5FF]/10 border-[#00E5FF]/40 text-[#00E5FF]"
                : "bg-[#FF3B30]/10 border-[#FF3B30]/40 text-[#FF3B30]"
            }`}
            data-testid="ai-order-result"
          >
            {orderResult.ok ? (
              <CheckCircle2 className="w-5 h-5 shrink-0 mt-0.5" />
            ) : (
              <XCircle className="w-5 h-5 shrink-0 mt-0.5" />
            )}
            <div className="flex-1">
              {orderResult.ok ? (
                <>
                  <div className="font-bold mb-1">Order completed</div>
                  <div className="text-xs text-white/70 font-mono">
                    SMM ID: {orderResult.smm_order_id} · ${orderResult.price?.toFixed(2)}
                  </div>
                </>
              ) : (
                <>
                  <div className="font-bold mb-1">Order failed</div>
                  <div className="text-xs text-white/70">{orderResult.reason}</div>
                  <button
                    onClick={openLiveChat}
                    data-testid="ai-open-chat"
                    className="mt-2 inline-block text-[11px] uppercase tracking-wider bg-white/10 hover:bg-white/20 px-3 py-1 rounded-sm"
                  >
                    Contact us via live chat
                  </button>
                </>
              )}
            </div>
          </div>
        )}

        {/* Input */}
        <form
          onSubmit={send}
          className="flex gap-2 bg-[#0d0a14] border border-white/10 rounded-sm p-2"
        >
          <Input
            data-testid="ai-input"
            placeholder="Type your answer…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={sending}
            className="bg-transparent border-0 focus-visible:ring-0"
          />
          <button
            type="submit"
            disabled={sending || !text.trim()}
            data-testid="ai-send"
            className="px-4 gradient-pp rounded-sm font-bold disabled:opacity-40 inline-flex items-center"
          >
            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </form>
      </main>
    </div>
  );
}

function Bubble({ m, typing }) {
  const isUser = m.role === "user";
  const cleanText = m.text.replace(READY_RE, "").trim() || m.text;
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] md:max-w-[75%] px-4 py-2.5 rounded-sm text-sm leading-relaxed ${
          isUser
            ? "bg-[#FF007F] text-white"
            : "bg-[#1a1525] border border-white/10 text-white/90"
        }`}
      >
        {typing ? (
          <span className="inline-flex gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-white/50 animate-bounce" style={{ animationDelay: "0ms" }} />
            <span className="w-1.5 h-1.5 rounded-full bg-white/50 animate-bounce" style={{ animationDelay: "150ms" }} />
            <span className="w-1.5 h-1.5 rounded-full bg-white/50 animate-bounce" style={{ animationDelay: "300ms" }} />
          </span>
        ) : (
          cleanText
        )}
      </div>
    </div>
  );
}
