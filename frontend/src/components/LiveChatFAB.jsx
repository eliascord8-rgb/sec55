import { useEffect, useRef, useState } from "react";
import { MessageCircle, Send, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

// Mobile floating live-chat button — appears just above the AI Robot FAB so
// visitors can peek at (and, if signed-in, join) the public shoutbox from any
// tab without navigating away. On desktop it stays hidden — the sidebar
// shoutbox already lives on-screen.
const POLL_MS = 4000;

export default function LiveChatFAB() {
  const { user, authedApi } = useAuth();
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [unread, setUnread] = useState(0);
  const lastIdRef = useRef(null);
  const bottomRef = useRef(null);

  const load = async () => {
    try {
      const r = await api.get("/public-chat/messages?limit=40");
      const items = r.data.messages || [];
      setMsgs(items);
      const newest = items[items.length - 1]?.id;
      if (!open && newest && lastIdRef.current && newest !== lastIdRef.current) {
        setUnread((n) => Math.min(99, n + 1));
      }
      if (newest) lastIdRef.current = newest;
    } catch { /* ignore polls between deploys */ }
  };

  useEffect(() => { load(); const t = setInterval(load, POLL_MS); return () => clearInterval(t); /* eslint-disable-next-line */ }, [open]);
  useEffect(() => { if (open) { setUnread(0); bottomRef.current?.scrollIntoView({ behavior: "smooth" }); } }, [open, msgs.length]);

  const send = async () => {
    const t = text.trim();
    if (!t || !user) return;
    setSending(true);
    try {
      await authedApi().post("/public-chat/send", { text: t });
      setText("");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't send.");
    } finally { setSending(false); }
  };

  return (
    <>
      {/* Floating trigger — mobile only. Positioned so it sits directly ABOVE the AI FAB. */}
      <button
        onClick={() => setOpen(true)}
        data-testid="live-chat-fab"
        title="Open live community chat"
        className="md:hidden fixed bottom-24 right-4 z-30 w-14 h-14 rounded-full bg-emerald-500 hover:bg-emerald-400 text-black shadow-lg shadow-emerald-500/40 flex items-center justify-center transition"
      >
        <MessageCircle className="w-6 h-6" strokeWidth={2.5} />
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[20px] h-5 px-1 rounded-full bg-red-500 text-[10px] font-bold text-white flex items-center justify-center leading-none border-2 border-black">
            {unread}
          </span>
        )}
      </button>

      {/* Bottom-sheet chat — full-height mobile panel */}
      {open && (
        <div className="md:hidden fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm flex items-end" onClick={() => setOpen(false)}>
          <div
            data-testid="live-chat-mobile-panel"
            onClick={(e) => e.stopPropagation()}
            className="w-full bg-[#0d2b12] border-t border-emerald-500/30 rounded-t-2xl shadow-2xl h-[85vh] flex flex-col"
          >
            <div className="flex items-center gap-2 px-4 py-3 border-b border-emerald-500/20 shrink-0">
              <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <div className="font-display font-black text-sm">Live chat</div>
              <span className="ml-2 text-[9px] uppercase tracking-widest text-emerald-400/60">Everyone</span>
              <div className="flex-1" />
              <button
                onClick={() => setOpen(false)}
                data-testid="live-chat-close"
                className="p-2 rounded-md text-white/70 hover:text-white hover:bg-white/5"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2 text-xs" data-testid="live-chat-messages">
              {msgs.length === 0 && <div className="text-white/40 text-center py-6">Say hi 👋</div>}
              {msgs.map((m) => {
                const roleTag = m.role === "owner" ? "OWNER" : m.role === "admin" ? "ADMIN" : m.role === "moderator" || m.role === "staff" ? "STAFF" : null;
                const roleCls = m.role === "owner" ? "text-amber-300 bg-amber-500/20 border-amber-500/40" : m.role === "admin" ? "text-emerald-200 bg-emerald-500/20 border-emerald-500/40" : "text-sky-200 bg-sky-500/20 border-sky-500/40";
                return (
                  <div key={m.id} className="bg-black/30 rounded-sm px-2 py-1.5">
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="text-emerald-300 font-bold">@{m.username || "user"}</span>
                      {roleTag && (
                        <span className={`text-[8px] px-1 py-px rounded-sm border font-bold uppercase tracking-wider ${roleCls}`}>{roleTag}</span>
                      )}
                      <span className="ml-auto text-[9px] text-white/40">
                        {m.created_at ? new Date(m.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""}
                      </span>
                    </div>
                    <div className="text-white/80 break-words">{m.text || m.content}</div>
                  </div>
                );
              })}
              <div ref={bottomRef} />
            </div>

            <div className="border-t border-emerald-500/20 p-3 shrink-0">
              {user ? (
                <form
                  onSubmit={(e) => { e.preventDefault(); send(); }}
                  className="flex items-center gap-2"
                >
                  <input
                    data-testid="live-chat-input"
                    value={text}
                    onChange={(e) => setText(e.target.value.slice(0, 500))}
                    placeholder="Say something…"
                    className="flex-1 bg-black/40 border border-emerald-500/30 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-emerald-400"
                  />
                  <button
                    type="submit"
                    disabled={!text.trim() || sending}
                    data-testid="live-chat-send"
                    className="w-10 h-10 rounded-md bg-emerald-500 hover:bg-emerald-400 text-black flex items-center justify-center disabled:opacity-40 transition"
                  >
                    <Send className="w-4 h-4" strokeWidth={2.5} />
                  </button>
                </form>
              ) : (
                <div className="text-center text-xs text-white/50 py-1">Sign in to join the conversation.</div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
