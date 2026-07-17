import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Bot, Send, Loader2, X, Minus, CheckCircle2, XCircle, MessageCircle, Paperclip, Image as ImageIcon, FileText, User } from "lucide-react";

const MAX_FILE_BYTES = 8 * 1024 * 1024;
const MAX_FILES = 4;

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
        comments: data.comments ? String(data.comments) : null,
      };
    }
  } catch (e) {
    // fall through
  }
  return null;
}

export default function AIWidget({ open, onOpenChange }) {
  const auth = useAuth() || {};
  const { user, authedApi } = auth;

  // Helper — uses authedApi when logged in (so backend can auto-identify), else plain api
  const aiApi = () => (user && authedApi ? authedApi() : api);

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
  const [pendingFiles, setPendingFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  // Identification state
  const [identified, setIdentified] = useState(false);
  const [identifyValue, setIdentifyValue] = useState("");
  const [identifying, setIdentifying] = useState(false);
  const [staffTyping, setStaffTyping] = useState(false);
  const [muted, setMuted] = useState(false);
  const [banned, setBanned] = useState(false);
  // Tab state — 'chat' vs 'history' (signed-in users only)
  const [activeTab, setActiveTab] = useState("chat");
  const [pastSessions, setPastSessions] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const fileInputRef = useRef(null);
  const endRef = useRef(null);
  const sessionIdRef = useRef(null);
  const lastPollAtRef = useRef(null);

  // Auto-identify if user is logged in (token sent via Authorization header in api client)
  useEffect(() => {
    if (user && !identified) {
      setIdentified(true);
    }
  }, [user, identified]);

  // Auto-connect signed-in users to a live human on OPEN — the AI is only a
  // fallback when no team member is around. We fire an immediate handover
  // request and preload their previous conversations.
  const openedRef = useRef(false);
  useEffect(() => {
    if (!open) { openedRef.current = false; return; }
    if (openedRef.current) return;
    openedRef.current = true;
    if (user) {
      // 1. Preload past sessions so the "Previous" tab is instant
      loadPastSessions();
      // 2. Request human handover right away — don't wait for the user to hit an error
      if (!humanTakeover && handoverState === "none") {
        (async () => {
          try {
            await api.post("/ai/request-handover", {
              session_id: sessionIdRef.current,
              reason: "user_opened_widget",
            });
            setHandoverState("waiting");
            setMessages((prev) => [
              ...prev,
              {
                role: "assistant",
                text: "👋 Hey! I'm paging a live agent for you now — please stay on this chat and we'll be right with you. Meanwhile you can still ask me anything and I'll try to help.",
              },
            ]);
          } catch { /* silent — user can still type */ }
        })();
      }
    }
    // eslint-disable-next-line
  }, [open, user]);

  // Ensure a session_id exists before any upload
  const ensureSession = () => {
    if (!sessionIdRef.current) {
      sessionIdRef.current = `ai-guest-${Math.random().toString(36).slice(2, 10)}`;
    }
    return sessionIdRef.current;
  };

  const openFilePicker = () => {
    if (uploading || sending) return;
    fileInputRef.current?.click();
  };

  const handleFileSelect = async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = ""; // reset so same file can be re-picked
    if (!files.length) return;
    if (pendingFiles.length + files.length > MAX_FILES) {
      setMessages((prev) => [
        ...prev,
        { role: "system", text: `⚠️ Max ${MAX_FILES} files at once.` },
      ]);
      return;
    }
    const sid = ensureSession();
    setUploading(true);
    for (const f of files) {
      if (f.size > MAX_FILE_BYTES) {
        setMessages((prev) => [
          ...prev,
          { role: "system", text: `⚠️ "${f.name}" is too big (max 8 MB).` },
        ]);
        continue;
      }
      const fd = new FormData();
      fd.append("session_id", sid);
      fd.append("file", f);
      try {
        const r = await api.post("/ai/upload", fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        setPendingFiles((prev) => [...prev, r.data]);
      } catch (err) {
        const reason = err.response?.data?.detail || "Upload failed";
        setMessages((prev) => [
          ...prev,
          { role: "system", text: `⚠️ ${f.name}: ${reason}` },
        ]);
      }
    }
    setUploading(false);
  };

  const removePendingFile = (id) => {
    setPendingFiles((prev) => prev.filter((p) => p.id !== id));
  };

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
        setStaffTyping(!!r.data.staff_typing);
        setMuted(!!r.data.muted);
        setBanned(!!r.data.banned);
        if (r.data.banned) {
          // Persist so the floating launcher button can hide itself on next render
          try { localStorage.setItem("bs_chat_banned", "1"); } catch {}
          setOpen(false);
          return;
        }
        // Clear ban flag if we were previously marked banned and now we're not
        try { if (localStorage.getItem("bs_chat_banned")) localStorage.removeItem("bs_chat_banned"); } catch {}
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
    const hasFiles = pendingFiles.length > 0;
    if ((!t && !hasFiles) || sending) return;

    // If user attached files: send via /attach-message (no LLM call) — admin sees in inbox
    if (hasFiles) {
      const sid = ensureSession();
      const attached = pendingFiles;
      const userMsg = {
        role: "user",
        text: t,
        attachments: attached,
      };
      setMessages((prev) => [...prev, userMsg]);
      setText("");
      setPendingFiles([]);
      setSending(true);
      try {
        await api.post("/ai/attach-message", {
          session_id: sid,
          file_ids: attached.map((f) => f.id),
          text: t,
        });
        // The backend auto-inserts an assistant ack — pollers will pick it up.
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            text: "⚠️ Couldn't attach the file — please try again.",
          },
        ]);
      } finally {
        setSending(false);
      }
      return;
    }

    // Normal text-only chat path
    const userMsg = { role: "user", text: t };
    const history = [...messages, userMsg];
    setMessages(history);
    setText("");
    setSending(true);
    // Retry-once helper: LLM providers throttle bursts, so first request may 502.
    // A single retry with a short backoff catches most transient failures cleanly.
    const attempt = async () => aiApi().post("/ai/chat", {
      messages: history,
      session_id: sessionIdRef.current,
    });
    let r;
    try {
      try {
        r = await attempt();
      } catch (err1) {
        const st = err1?.response?.status;
        // Only retry on transient errors (network, 429, 500-599)
        if (!st || st === 429 || st >= 500) {
          await new Promise((res) => setTimeout(res, 900));
          r = await attempt();
        } else {
          throw err1;
        }
      }
      sessionIdRef.current = r.data.session_id;
      setHumanTakeover(!!r.data.human_takeover);
      const reply = r.data.reply;
      if (reply && !r.data.human_takeover) {
        // Use the server's reply_id so the poll dedupes correctly and we don't show duplicates
        setMessages((prev) => [...prev, { role: "assistant", text: reply, _id: r.data.reply_id }]);
        // Bump the poll "since" pointer past this message
        if (r.data.reply_id) {
          lastPollAtRef.current = new Date().toISOString();
        }
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
      // AI backend is unreachable — render an inline handover CTA in the chat
      // instead of a generic error. The message has a `handover` flag the
      // renderer picks up to draw a "Connect with our team" button.
      const detail = err?.response?.data?.detail || "";
      const isRateLimit = err?.response?.status === 429 || /rate.limit/i.test(String(detail));
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          handover: true,
          text: isRateLimit
            ? "⏱ Sorry — I'm getting a lot of questions right now."
            : "⚠️ Sorry, our AI operator is currently unreachable.",
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  // Called when the user taps the inline "Connect with our team" button.
  // Fires the handover endpoint (best-effort) and drops the confirmation
  // system message into the chat so the user knows help is on the way.
  const requestHumanHandover = async () => {
    // Replace the CTA message so the button can't be spammed
    setMessages((prev) =>
      prev.map((m) => (m.handover ? { ...m, handover: false, handoverPending: true } : m)),
    );
    try {
      await api.post("/ai/request-handover", {
        session_id: sessionIdRef.current,
        reason: "ai_backend_unreachable",
      });
    } catch { /* non-fatal — we still show the confirmation locally */ }
    setMessages((prev) => [
      ...prev,
      {
        role: "assistant",
        text: "🤝 You'll be connected with a chat agent shortly — please stay in the chat, we'll be right with you.",
      },
    ]);
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

  const submitIdentify = async (e) => {
    e?.preventDefault();
    const v = identifyValue.trim();
    if (!v || identifying) return;
    setIdentifying(true);
    try {
      const r = await api.post("/ai/identify", {
        session_id: ensureSession(),
        identifier: v,
      });
      sessionIdRef.current = r.data.session_id;
      setIdentified(true);
      setIdentifyValue("");
      // Replace greeting with personalized one
      const name = r.data.identified_as.split("@")[0];
      setMessages([
        {
          role: "assistant",
          text: `Hey ${name} 👋 — I'm Better Social AI. What can I do for you today?`,
        },
      ]);
    } catch (err) {
      const reason = err.response?.data?.detail || "Failed";
      const msg = typeof reason === "string" ? reason : reason?.message || "Failed";
      setMessages((prev) => [
        ...prev,
        { role: "system", text: `⚠️ ${msg}`, _sys: "identify-err" },
      ]);
    } finally {
      setIdentifying(false);
    }
  };

  const openLiveChat = () => {
    // Trigger our built-in handover flow by sending a "talk to staff" message
    setText((prev) => prev || "I want to talk to a staff member");
  };

  const reset = () => {
    setMessages([GREETING]);
    setResult(null);
    setHumanTakeover(false);
    setHandoverState("none");
    setOfflineEmail("");
    setOfflineText("");
    setPendingFiles([]);
    // Only require re-identify if user is NOT signed-in (signed-in users stay identified)
    if (!user) {
      setIdentified(false);
      setIdentifyValue("");
    }
    sessionIdRef.current = null;
    lastPollAtRef.current = null;
    setActiveTab("chat");
  };

  // Load the current user's past AI conversations (signed-in only)
  const loadPastSessions = async () => {
    if (!user || !authedApi) return;
    setLoadingHistory(true);
    try {
      const r = await authedApi().get("/ai/my-sessions");
      setPastSessions(r.data.sessions || []);
    } catch {
      setPastSessions([]);
    } finally {
      setLoadingHistory(false);
    }
  };

  // Restore a past session into the chat window
  const openPastSession = async (sid) => {
    if (!user || !authedApi) return;
    setLoadingHistory(true);
    try {
      const r = await authedApi().get(`/ai/session/${encodeURIComponent(sid)}/messages`);
      const items = (r.data.messages || []).map((m) => ({
        role: m.role === "user" ? "user" : m.role === "admin" ? "admin" : "assistant",
        text: m.text,
      }));
      setMessages(items.length ? items : [GREETING]);
      sessionIdRef.current = sid;
      setActiveTab("chat");
    } catch {
      // ignore — fall back to current chat
    } finally {
      setLoadingHistory(false);
    }
  };

  if (!open) return null;
  if (banned) return null;

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
              title="Start a fresh conversation"
              data-testid="ai-widget-new-chat"
              className="text-[10px] uppercase tracking-wider text-white/60 hover:text-white px-2 py-1 rounded-sm hover:bg-white/5 whitespace-nowrap"
            >
              + New chat
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

        {/* Tab bar — signed-in users get access to their past conversations */}
        {user && (
          <div className="flex items-center gap-1 px-2 pt-2 bg-[#050505] border-b border-white/5" data-testid="ai-widget-tabs">
            <button
              onClick={() => setActiveTab("chat")}
              data-testid="ai-tab-chat"
              className={`px-3 py-1.5 text-[10px] uppercase tracking-widest font-bold rounded-t-sm transition ${activeTab === "chat" ? "text-white bg-[#1a1525] border-t border-x border-white/10" : "text-white/40 hover:text-white/70"}`}
            >
              Chat
            </button>
            <button
              onClick={() => { setActiveTab("history"); loadPastSessions(); }}
              data-testid="ai-tab-history"
              className={`px-3 py-1.5 text-[10px] uppercase tracking-widest font-bold rounded-t-sm transition ${activeTab === "history" ? "text-white bg-[#1a1525] border-t border-x border-white/10" : "text-white/40 hover:text-white/70"}`}
            >
              Previous
            </button>
            <div className="ml-auto pr-2 pb-0.5">
              <button
                onClick={reset}
                data-testid="ai-widget-start-new"
                className="text-[9px] uppercase tracking-widest font-black text-emerald-300 hover:text-emerald-200 px-2 py-1 rounded-sm hover:bg-emerald-500/10 whitespace-nowrap"
              >
                + Start new conversation
              </button>
            </div>
          </div>
        )}

        {/* Messages */}
        {activeTab === "history" && user ? (
          <div className="flex-1 overflow-y-auto px-3 py-4 space-y-2 bg-gradient-to-b from-[#0d0a14] to-[#080510]" data-testid="ai-history-panel">
            <div className="text-[10px] uppercase tracking-widest text-white/50 mb-2 px-1">Previous conversations</div>
            {loadingHistory ? (
              <div className="flex items-center justify-center py-8"><Loader2 className="w-4 h-4 animate-spin text-white/50" /></div>
            ) : pastSessions.length === 0 ? (
              <div className="text-center text-xs text-white/40 py-8">
                No past conversations yet. Start chatting — they&apos;ll show up here.
              </div>
            ) : (
              pastSessions.map((s) => (
                <button
                  key={s.session_id}
                  onClick={() => openPastSession(s.session_id)}
                  data-testid={`ai-history-item-${s.session_id}`}
                  className="w-full text-left bg-[#1a1525] hover:bg-[#251d33] border border-white/5 hover:border-white/15 rounded-sm px-3 py-2 transition group"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-[10px] uppercase tracking-widest text-emerald-300/70 font-bold">
                      {s.last_activity_at ? new Date(s.last_activity_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}
                    </div>
                    <div className="text-[9px] text-white/40 font-mono">{s.message_count} msg</div>
                  </div>
                  <div className="text-xs text-white/70 line-clamp-2 mt-0.5 group-hover:text-white">
                    {s.preview || "(no user message yet)"}
                  </div>
                </button>
              ))
            )}
          </div>
        ) : (
          <div
            className="flex-1 overflow-y-auto px-3 py-4 space-y-3 bg-gradient-to-b from-[#0d0a14] to-[#080510]"
            data-testid="ai-widget-messages"
          >
          {messages.map((m, i) => (
            <div key={i}>
              <Bubble m={m} />
              {/* Handover CTA — appears under the assistant's error message when AI backend is unreachable */}
              {m.handover && (
                <div className="mx-3 -mt-1 mb-2 flex items-start gap-2" data-testid={`ai-handover-cta-${i}`}>
                  <button
                    onClick={requestHumanHandover}
                    data-testid="ai-connect-team-btn"
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-sm bg-emerald-500 hover:bg-emerald-400 text-black text-[11px] font-black uppercase tracking-wider transition"
                  >
                    <User className="w-3 h-3" />
                    Connect with our team
                  </button>
                </div>
              )}
              {m.handoverPending && (
                <div className="mx-3 -mt-1 mb-2 text-[10px] uppercase tracking-widest text-emerald-300/70">
                  · Notifying team…
                </div>
              )}
            </div>
          ))}
          {sending && <Bubble m={{ role: "assistant", text: "…" }} typing />}
          {staffTyping && !sending && (
            <Bubble m={{ role: "admin", text: "", _staffname: staffName }} typing />
          )}
          <div ref={endRef} />
        </div>
        )}

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
                  <span className="font-bold">Order completed</span> · #{result.smm_order_id} ·
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

        {/* Identification gate — shown until guest enters email/username (or user is signed in) */}
        {!identified && (
          <form
            onSubmit={submitIdentify}
            data-testid="ai-widget-identify-form"
            className="mx-3 mb-2 p-3 rounded-sm border border-[#FF007F]/40 bg-[#FF007F]/10 space-y-2"
          >
            <div className="flex items-center gap-2 text-xs text-white/90">
              <User className="w-4 h-4 text-[#FF007F]" />
              <span className="font-bold">Before we start chatting</span>
            </div>
            <div className="text-[11px] text-white/60 leading-snug">
              Please enter your <span className="text-white">email</span> or{" "}
              <span className="text-white">username</span> so we can serve you better. If you
              already have an account, just{" "}
              <a href="/client" className="underline hover:text-[#00E5FF]">
                sign in
              </a>{" "}
              and we'll recognize you automatically.
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                data-testid="ai-widget-identify-input"
                placeholder="you@email.com or username"
                value={identifyValue}
                onChange={(e) => setIdentifyValue(e.target.value)}
                required
                minLength={2}
                maxLength={80}
                disabled={identifying}
                className="flex-1 bg-[#0d0a14] border border-white/10 rounded-sm px-3 py-2 text-sm outline-none focus:border-[#FF007F] text-white placeholder:text-white/30"
              />
              <button
                type="submit"
                disabled={identifying || !identifyValue.trim()}
                data-testid="ai-widget-identify-submit"
                className="px-4 py-2 gradient-pp rounded-sm text-xs uppercase tracking-wider font-bold disabled:opacity-50 inline-flex items-center gap-1.5"
              >
                {identifying ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                Continue
              </button>
            </div>
          </form>
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

        {/* Pending files preview */}
        {pendingFiles.length > 0 && (
          <div
            data-testid="ai-widget-pending-files"
            className="border-t border-white/10 bg-[#0d0a14] px-2.5 py-2 flex flex-wrap gap-2"
          >
            {pendingFiles.map((f) => (
              <div
                key={f.id}
                data-testid={`pending-file-${f.id}`}
                className="relative group flex items-center gap-2 bg-[#1a1525] border border-white/10 rounded-sm pr-7 pl-2 py-1.5 max-w-[180px]"
              >
                {f.is_image ? (
                  <ImageIcon className="w-3.5 h-3.5 text-[#00E5FF] shrink-0" />
                ) : (
                  <FileText className="w-3.5 h-3.5 text-[#FF007F] shrink-0" />
                )}
                <span className="text-[11px] text-white/80 truncate">{f.filename}</span>
                <button
                  type="button"
                  onClick={() => removePendingFile(f.id)}
                  data-testid={`remove-file-${f.id}`}
                  aria-label="Remove"
                  className="absolute right-1 top-1/2 -translate-y-1/2 w-5 h-5 rounded-sm flex items-center justify-center text-white/60 hover:text-white hover:bg-white/10"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
            {uploading && (
              <div className="flex items-center gap-2 text-[11px] text-white/50 px-2 py-1.5">
                <Loader2 className="w-3 h-3 animate-spin" /> Uploading…
              </div>
            )}
          </div>
        )}

        {/* Input */}
        <form
          onSubmit={send}
          className="border-t border-white/10 p-2.5 flex items-center gap-2 bg-[#050505]"
        >
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileSelect}
            accept="image/*,.pdf,.txt,.zip,.doc,.docx,.xls,.xlsx"
            multiple
            data-testid="ai-widget-file-input"
            className="hidden"
          />
          <button
            type="button"
            onClick={openFilePicker}
            disabled={!identified || sending || uploading || pendingFiles.length >= MAX_FILES}
            aria-label="Attach file"
            title={
              !identified
                ? "Identify first"
                : pendingFiles.length >= MAX_FILES
                ? `Max ${MAX_FILES} files`
                : "Attach image or file"
            }
            data-testid="ai-widget-attach"
            className="w-9 h-9 rounded-sm flex items-center justify-center text-white/60 hover:text-[#00E5FF] hover:bg-white/5 disabled:opacity-40 shrink-0"
          >
            {uploading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Paperclip className="w-4 h-4" />
            )}
          </button>
          <input
            data-testid="ai-widget-input"
            placeholder={
              muted
                ? "You're temporarily muted by staff…"
                : !identified
                ? "Enter email/username above first…"
                : humanTakeover
                ? `Message ${staffName}…`
                : handoverState === "waiting"
                ? "Waiting for staff to join…"
                : "Type your message…"
            }
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={!identified || sending || muted}
            readOnly={muted}
            className="flex-1 bg-[#1a1525] border border-white/10 rounded-sm px-3 py-2.5 text-sm outline-none focus:border-[#FF007F] text-white placeholder:text-white/40 disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={!identified || sending || muted || (!text.trim() && pendingFiles.length === 0)}
            data-testid="ai-widget-send"
            className="w-10 h-10 gradient-pp rounded-sm flex items-center justify-center font-bold disabled:opacity-40 shrink-0"
          >
            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </form>
        {/* Signature */}
        <div className="bg-[#050505] border-t border-white/5 px-3 py-1.5 text-center" data-testid="ai-widget-credit">
          <span className="text-[9px] uppercase tracking-widest text-white/30 font-bold">
            Developed by <span className="text-white/60">BK</span> and <span className="text-white/60">Sinester</span>
          </span>
        </div>
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
        {/* Attachments */}
        {Array.isArray(m.attachments) && m.attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-1.5 justify-end">
            {m.attachments.map((a) => {
              const url = a.url || `/api/ai/uploads/${a.id}`;
              const isImg = a.is_image || (a.content_type || "").startsWith("image/");
              if (isImg) {
                return (
                  <a
                    key={a.id}
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    data-testid={`bubble-image-${a.id}`}
                    className="block rounded-sm overflow-hidden border border-white/10 hover:border-[#00E5FF] transition"
                  >
                    <img
                      src={url}
                      alt={a.filename}
                      className="max-w-[180px] max-h-[180px] object-cover block"
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
                  data-testid={`bubble-file-${a.id}`}
                  className="inline-flex items-center gap-2 px-2 py-1.5 bg-white/10 hover:bg-white/15 rounded-sm border border-white/10 text-[11px] text-white max-w-[200px]"
                >
                  <FileText className="w-3 h-3 shrink-0" />
                  <span className="truncate">{a.filename}</span>
                </a>
              );
            })}
          </div>
        )}
        {(cleanText || typing) && (
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
              <span className="inline-flex gap-1 items-center py-1">
                <span
                  className={`w-1.5 h-1.5 rounded-full animate-bounce ${
                    isAdmin ? "bg-[#050505]/60" : "bg-white/60"
                  }`}
                  style={{ animationDelay: "0ms", animationDuration: "900ms" }}
                />
                <span
                  className={`w-1.5 h-1.5 rounded-full animate-bounce ${
                    isAdmin ? "bg-[#050505]/60" : "bg-white/60"
                  }`}
                  style={{ animationDelay: "180ms", animationDuration: "900ms" }}
                />
                <span
                  className={`w-1.5 h-1.5 rounded-full animate-bounce ${
                    isAdmin ? "bg-[#050505]/60" : "bg-white/60"
                  }`}
                  style={{ animationDelay: "360ms", animationDuration: "900ms" }}
                />
              </span>
            ) : (
              cleanText
            )}
          </div>
        )}
      </div>
    </div>
  );
}
