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
  const [humanTakeover, setHumanTakeover] = useState(false);
  const [staffName, setStaffName] = useState("Support");
  const [handoverState, setHandoverState] = useState("none"); // none | waiting | offline_form | submitted
  const [offlineEmail, setOfflineEmail] = useState("");
  const [offlineText, setOfflineText] = useState("");
  const [offlineSending, setOfflineSending] = useState(false);
  const endRef = useRef(null);
  const sessionIdRef = useRef(null);
  const lastPollAtRef = useRef(null);

  useEffect(() => {
    if (open) {
      // Scroll to bottom when opened
      setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    }
  }, [open]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, sending]);

  // Poll for new admin/assistant messages every 3s while open
  useEffect(() => {
    if (!open) return;
    const tick = async () => {
      const sid = sessionIdRef.current;
      if (!sid) return;
      try {
        const r = await api.get("/ai/poll", {
          params: { session_id: sid, since: lastPollAtRef.current || undefined },
        });
        const wasTakeover = humanTakeover;
        setHumanTakeover(!!r.data.human_takeover);
        if (r.data.staff_display_name) setStaffName(r.data.staff_display_name);
        // If admin just took over → reset handover state to "submitted" so we don't show form
        if (r.data.human_takeover && handoverState !== "none") setHandoverState("none");
        // If admin RELEASED chat → flip back to AI mode so input shows AI placeholder
        if (wasTakeover && !r.data.human_takeover) {
          // assistant message about leaving will be in newOnes
        }
        const newOnes = r.data.messages || [];
        if (newOnes.length) {
          setMessages((prev) => {
            const existingIds = new Set(prev.map((m) => m._id).filter(Boolean));
            const adds = newOnes
              .filter((m) => !existingIds.has(m.id))
              .map((m) => ({
                role: m.role === "admin" ? "admin" : "assistant",
                text: m.text,
                _id: m.id,
                admin_name: m.admin_name,
              }));
            return adds.length ? [...prev, ...adds] : prev;
          });
          lastPollAtRef.current = newOnes[newOnes.length - 1].created_at;
        }
      } catch {
        /* ignore */
      }
    };
    const t = setInterval(tick, 3000);
    return () => clearInterval(t);
  }, [open, handoverState, humanTakeover]);

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
      setHumanTakeover(!!r.data.human_takeover);
      const reply = r.data.reply;
      if (reply && !r.data.human_takeover) {
        setMessages((prev) => [...prev, { role: "assistant", text: reply }]);
        const ready = parseReady(reply);
        if (ready) await tryExecuteOrder(reply);
        // Handover flow
        if (r.data.needs_handover) {
          if (r.data.admin_online) {
            setHandoverState("waiting");
            setMessages((prev) => {
              if (prev.some((m) => m._sys === "waiting")) return prev;
              return [
                ...prev,
                {
                  role: "system",
                  text: "🔔 Notifying our team — please hold on.",
                  _sys: "waiting",
                },
              ];
            });
          } else {
            setHandoverState("offline_form");
          }
        }
      } else if (r.data.human_takeover) {
        setMessages((prev) => {
          if (prev.some((m) => m._sys === "takeover")) return prev;
          return [
            ...prev,
            {
              role: "system",
              text: `👋 ${r.data.staff_display_name || staffName} is now handling your chat.`,
              _sys: "takeover",
            },
          ];
        });
      }
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

  const submitOfflineMessage = async (e) => {
    e?.preventDefault();
    if (offlineSending) return;
    const email = offlineEmail.trim();
    const msg = offlineText.trim();
    if (!email || !msg) return;
    setOfflineSending(true);
    try {
      await api.post("/ai/offline-message", {
        session_id: sessionIdRef.current,
        email,
        message: msg,
      });
      setHandoverState("submitted");
      setOfflineEmail("");
      setOfflineText("");
      setMessages((prev) => [
        ...prev,
        {
          role: "system",
          text: "✅ Got it — we'll email you back as soon as a team-member is online.",
          _sys: "offline_ok",
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: "⚠️ Couldn't send your message — please try again.",
        },
      ]);
    } finally {
      setOfflineSending(false);
    }
  };

  const cancelOfflineForm = () => {
    setHandoverState("none");
    setOfflineEmail("");
    setOfflineText("");
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
    setHumanTakeover(false);
    setHandoverState("none");
    setOfflineEmail("");
    setOfflineText("");
    sessionIdRef.current = null;
    lastPollAtRef.current = null;
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
              <div className="font-bold text-sm truncate">
                {humanTakeover ? `Better Social · ${staffName}` : "Better Social AI"}
              </div>
              <div className="text-[10px] text-white/50">
                {humanTakeover
                  ? "A human is replying live"
                  : handoverState === "waiting"
                  ? "Connecting to staff…"
                  : "Typically replies in seconds"}
              </div>
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

        {/* Offline contact form (shown when handover requested but no admin online) */}
        {handoverState === "offline_form" && (
          <form
            onSubmit={submitOfflineMessage}
            data-testid="ai-widget-offline-form"
            className="mx-3 mb-2 p-3 rounded-sm border border-[#FF007F]/40 bg-[#FF007F]/10 space-y-2"
          >
            <div className="text-xs text-white/80 leading-snug">
              No team-member is online right now. Leave your email + a message and we'll get back to you ASAP.
            </div>
            <input
              type="email"
              data-testid="offline-email"
              placeholder="your@email.com"
              value={offlineEmail}
              onChange={(e) => setOfflineEmail(e.target.value)}
              required
              disabled={offlineSending}
              className="w-full bg-[#0d0a14] border border-white/10 rounded-sm px-3 py-2 text-sm outline-none focus:border-[#FF007F] text-white placeholder:text-white/30"
            />
            <textarea
              data-testid="offline-message"
              placeholder="Your message…"
              value={offlineText}
              onChange={(e) => setOfflineText(e.target.value)}
              required
              rows={3}
              disabled={offlineSending}
              maxLength={2000}
              className="w-full bg-[#0d0a14] border border-white/10 rounded-sm px-3 py-2 text-sm outline-none focus:border-[#FF007F] text-white placeholder:text-white/30 resize-none"
            />
            <div className="flex gap-2">
              <button
                type="button"
                onClick={cancelOfflineForm}
                disabled={offlineSending}
                data-testid="offline-cancel"
                className="flex-1 py-2 text-[10px] uppercase tracking-wider border border-white/20 rounded-sm hover:bg-white/5 text-white/70"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={offlineSending || !offlineEmail.trim() || !offlineText.trim()}
                data-testid="offline-send"
                className="flex-1 py-2 text-[10px] uppercase tracking-wider gradient-pp rounded-sm font-bold disabled:opacity-50 inline-flex items-center justify-center gap-1.5"
              >
                {offlineSending ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                Send
              </button>
            </div>
          </form>
        )}

        {/* Input */}
        <form
          onSubmit={send}
          className="border-t border-white/10 p-2.5 flex items-center gap-2 bg-[#050505]"
        >
          <input
            data-testid="ai-widget-input"
            placeholder={
              humanTakeover
                ? `Message ${staffName}…`
                : handoverState === "waiting"
                ? "Waiting for staff to join…"
                : "Type your message…"
            }
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
  const isAdmin = m.role === "admin";
  const isSystem = m.role === "system";

  // System messages render centered, no avatar
  if (isSystem) {
    return (
      <div className="flex justify-center py-1">
        <div className="text-[10px] uppercase tracking-wider px-3 py-1 rounded-full bg-[#00E5FF]/10 border border-[#00E5FF]/30 text-[#00E5FF]">
          {m.text}
        </div>
      </div>
    );
  }

  // Strip ANY READY_TO_ORDER block before showing to user
  let cleanText = (m.text || "")
    .replace(/READY_TO_ORDER:[\s\S]*?(\{[\s\S]*?\})\s*/g, "")
    .replace(/```json|```/g, "")
    .trim();
  if (!cleanText && !isUser) cleanText = "Got it — placing your order…";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && (
        <div
          className={`w-7 h-7 rounded-full flex items-center justify-center mr-2 shrink-0 mt-auto ${
            isAdmin ? "bg-[#00E5FF]" : "gradient-pp"
          }`}
        >
          <Bot className={`w-3.5 h-3.5 ${isAdmin ? "text-[#050505]" : ""}`} />
        </div>
      )}
      <div className="max-w-[80%]">
        {isAdmin && (
          <div className="text-[9px] uppercase tracking-wider text-[#00E5FF] font-bold mb-1 ml-0.5">
            {m.admin_name || "Support"}
          </div>
        )}
        <div
          className={`px-3.5 py-2 rounded-sm text-sm leading-snug whitespace-pre-wrap ${
            isUser
              ? "bg-[#FF007F] text-white rounded-br-none"
              : isAdmin
              ? "bg-[#00E5FF] text-[#050505] rounded-bl-none font-medium"
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
    </div>
  );
}
