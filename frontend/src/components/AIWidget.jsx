import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Bot, Send, Loader2, X, Minus, CheckCircle2, XCircle, MessageCircle } from "lucide-react";

const GREETING = {
  role: "assistant",
  text:
    "Hi! I'm Better Social AI ✨  I can place an order for you in seconds. Tell me what you'd like — TikTok Live Likes, Views, or Comments? (Write in any language, I'll follow.)",
};

const READY_RE = /READY_TO_ORDER:\s*(\{[\s\S]*?\})/;

function parseReady(text) {
  if (!text) return null;
  // Strip code fences if any
  const stripped = text.replace(/```json|```/g, "");
  const m = stripped.match(READY_RE);
  if (!m) return null;
  try {
    const data = JSON.parse(m[1]);
    if (
      ["likes", "views", "comments"].includes(String(data.service_type).toLowerCase()) &&
      data.link &&
      data.quantity &&
      data.coupon_code
    ) {
      return {
        service_type: String(data.service_type).toLowerCase(),
        link: String(data.link),
        quantity: Number(data.quantity),
        coupon_code: String(data.coupon_code).toUpperCase(),
      };
    }
  } catch (e) {
    // fall through
  }
  return null;
}

export default function AIWidget({ open, onOpenChange }) {
  const [messages, setMessages] = useState([GREETING]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);
  const endRef = useRef(null);
  const sessionIdRef = useRef(null);

  useEffect(() => {
    if (open) {
      // Scroll to bottom when opened
      setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    }
  }, [open]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, sending]);

  const tryExecuteOrder = async (assistantText) => {
    const data = parseReady(assistantText);
    if (!data) return;
    try {
      const r = await api.post("/ai/confirm-order", data);
      setResult({ ok: true, ...r.data });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: `✅ Finish. Order has been sent — success!\nSMM ID: ${r.data.smm_order_id} · Charged: $${r.data.price.toFixed(2)}`,
        },
      ]);
    } catch (err) {
      const reason = err.response?.data?.detail || err.message || "Order failed";
      setResult({ ok: false, reason });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: `❌ Sorry — order failed: ${reason}\nPlease contact us via live chat and we'll resolve it quickly.`,
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
      const r = await api.post("/ai/chat", {
        messages: history,
        session_id: sessionIdRef.current,
      });
      sessionIdRef.current = r.data.session_id;
      const reply = r.data.reply;
      setMessages((prev) => [...prev, { role: "assistant", text: reply }]);
      const ready = parseReady(reply);
      if (ready) await tryExecuteOrder(reply);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: "⚠️ I had trouble reaching my brain. Try again in a moment.",
        },
      ]);
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

  const reset = () => {
    setMessages([GREETING]);
    setResult(null);
    sessionIdRef.current = null;
  };

  if (!open) return null;

  return (
    <>
      {/* Mobile backdrop */}
      <div
        data-testid="ai-widget-backdrop"
        onClick={() => onOpenChange(false)}
        className="fixed inset-0 z-[60] bg-black/50 md:hidden"
      />
      {/* Widget */}
      <div
        data-testid="ai-widget"
        className="fixed z-[70] bottom-0 right-0 left-0 md:left-auto md:bottom-6 md:right-6 w-full md:w-[380px] h-[80vh] md:h-[580px] md:max-h-[calc(100vh-48px)] bg-[#0d0a14] md:rounded-sm border-t md:border border-white/10 shadow-2xl flex flex-col overflow-hidden animate-ai-slide-in"
      >
        {/* Header */}
        <div className="px-4 py-3 border-b border-white/10 bg-[#050505] flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-9 h-9 rounded-full gradient-pp flex items-center justify-center shrink-0 relative">
              <Bot className="w-4 h-4" />
              <span className="absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full bg-[#00E5FF] border-2 border-[#050505]" />
            </div>
            <div className="min-w-0">
              <div className="font-bold text-sm truncate">Better Social AI</div>
              <div className="text-[10px] text-white/50">Typically replies in seconds</div>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={reset}
              title="New chat"
              data-testid="ai-widget-reset"
              className="text-[10px] uppercase tracking-wider text-white/50 hover:text-white px-2 py-1 rounded-sm hover:bg-white/5"
            >
              Reset
            </button>
            <button
              onClick={() => onOpenChange(false)}
              aria-label="Minimize"
              data-testid="ai-widget-minimize"
              className="p-1.5 rounded-sm text-white/60 hover:text-white hover:bg-white/5"
            >
              <Minus className="w-4 h-4" />
            </button>
            <button
              onClick={() => onOpenChange(false)}
              aria-label="Close"
              data-testid="ai-widget-close"
              className="p-1.5 rounded-sm text-white/60 hover:text-white hover:bg-white/5"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Messages */}
        <div
          className="flex-1 overflow-y-auto px-3 py-4 space-y-3 bg-gradient-to-b from-[#0d0a14] to-[#080510]"
          data-testid="ai-widget-messages"
        >
          {messages.map((m, i) => (
            <Bubble key={i} m={m} />
          ))}
          {sending && <Bubble m={{ role: "assistant", text: "…" }} typing />}
          <div ref={endRef} />
        </div>

        {/* Success/Failure result */}
        {result && (
          <div
            data-testid="ai-widget-result"
            className={`mx-3 mb-2 p-2.5 rounded-sm border text-xs flex items-start gap-2 ${
              result.ok
                ? "bg-[#00E5FF]/10 border-[#00E5FF]/40 text-[#00E5FF]"
                : "bg-[#FF3B30]/10 border-[#FF3B30]/40 text-[#FF3B30]"
            }`}
          >
            {result.ok ? (
              <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
            ) : (
              <XCircle className="w-4 h-4 shrink-0 mt-0.5" />
            )}
            <div className="flex-1 min-w-0">
              {result.ok ? (
                <div>
                  <span className="font-bold">Order completed</span> · SMM #{result.smm_order_id} ·
                  ${result.price?.toFixed(2)}
                </div>
              ) : (
                <div>
                  <div className="font-bold mb-1">Order failed</div>
                  <div className="text-white/70">{result.reason}</div>
                  <button
                    onClick={openLiveChat}
                    data-testid="ai-widget-open-livechat"
                    className="mt-1.5 inline-flex items-center gap-1 text-[10px] uppercase tracking-wider bg-white/10 hover:bg-white/20 px-2 py-1 rounded-sm text-white"
                  >
                    <MessageCircle className="w-3 h-3" /> Live chat
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Input */}
        <form
          onSubmit={send}
          className="border-t border-white/10 p-2.5 flex items-center gap-2 bg-[#050505]"
        >
          <input
            data-testid="ai-widget-input"
            placeholder="Type your message…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={sending}
            className="flex-1 bg-[#1a1525] border border-white/10 rounded-sm px-3 py-2.5 text-sm outline-none focus:border-[#FF007F] text-white placeholder:text-white/40"
          />
          <button
            type="submit"
            disabled={sending || !text.trim()}
            data-testid="ai-widget-send"
            className="w-10 h-10 gradient-pp rounded-sm flex items-center justify-center font-bold disabled:opacity-40 shrink-0"
          >
            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </form>
      </div>

      <style>{`
        @keyframes ai-slide-in {
          from { transform: translateY(16px); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }
        .animate-ai-slide-in { animation: ai-slide-in 240ms ease-out; }
      `}</style>
    </>
  );
}

function Bubble({ m, typing }) {
  const isUser = m.role === "user";
  const cleanText = m.text.replace(READY_RE, "").trim() || m.text;
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full gradient-pp flex items-center justify-center mr-2 shrink-0 mt-auto">
          <Bot className="w-3.5 h-3.5" />
        </div>
      )}
      <div
        className={`max-w-[80%] px-3.5 py-2 rounded-sm text-sm leading-snug whitespace-pre-wrap ${
          isUser
            ? "bg-[#FF007F] text-white rounded-br-none"
            : "bg-[#1a1525] border border-white/10 text-white/90 rounded-bl-none"
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
