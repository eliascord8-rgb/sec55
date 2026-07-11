import { useEffect, useState } from "react";
import { X, Megaphone } from "lucide-react";
import { api } from "@/lib/api";

// Shows the admin-configured news modal one time per user per news_id.
// Dismissal is remembered in localStorage keyed by "bs_news_seen_<id>".
export default function NewsModal() {
  const [news, setNews] = useState(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api.get("/news");
        if (cancelled) return;
        if (!r.data.enabled || !r.data.id) return;
        const key = `bs_news_seen_${r.data.id}`;
        if (localStorage.getItem(key) === "1") return; // already dismissed
        setNews(r.data);
        setVisible(true);
      } catch { /* no news configured is fine */ }
    })();
    return () => { cancelled = true; };
  }, []);

  const dismiss = () => {
    if (news?.id) localStorage.setItem(`bs_news_seen_${news.id}`, "1");
    setVisible(false);
  };

  if (!visible || !news) return null;
  return (
    <div
      className="fixed inset-0 z-[100] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={dismiss}
      data-testid="news-modal-backdrop"
    >
      <div
        className="w-full max-w-md bg-gradient-to-br from-[#0d2b12] to-[#0a1a0a] border border-emerald-500/40 rounded-lg p-6 md:p-8 shadow-2xl shadow-emerald-500/20 relative"
        onClick={(e) => e.stopPropagation()}
        data-testid="news-modal"
      >
        <button
          onClick={dismiss}
          data-testid="news-close-btn"
          className="absolute top-3 right-3 w-8 h-8 rounded-md hover:bg-white/10 text-white/70 hover:text-white flex items-center justify-center"
          aria-label="Close"
        >
          <X className="w-4 h-4" />
        </button>
        <div className="flex items-center gap-2 mb-4">
          <div className="w-10 h-10 rounded-md bg-emerald-500/20 border border-emerald-500/50 flex items-center justify-center">
            <Megaphone className="w-5 h-5 text-emerald-300" />
          </div>
          <div className="text-[10px] uppercase tracking-widest text-emerald-300/80">Announcement</div>
        </div>
        {news.title && (
          <h2 className="font-display text-2xl md:text-3xl font-black text-white mb-3" data-testid="news-title">
            {news.title}
          </h2>
        )}
        {news.body && (
          <p className="text-white/80 text-sm md:text-base whitespace-pre-wrap leading-relaxed" data-testid="news-body">
            {news.body}
          </p>
        )}
        <button
          onClick={dismiss}
          data-testid="news-got-it-btn"
          className="mt-6 w-full py-3 rounded-md font-bold uppercase tracking-wider text-xs bg-emerald-500 text-black hover:bg-emerald-400 transition"
        >
          Got it
        </button>
      </div>
    </div>
  );
}
