import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ShoppingBag } from "lucide-react";

function timeAgo(iso) {
  if (!iso) return "";
  const diff = Math.max(0, Date.now() - new Date(iso).getTime());
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function shortService(name) {
  if (!name) return "an order";
  // Strip emojis and bracketed promo text
  let s = name.replace(/\[[^\]]*\]/g, "").replace(/[^\w\s|/–-]/g, "").trim();
  s = s.replace(/\|.*$/, "").trim();
  if (s.length > 42) s = s.slice(0, 39) + "…";
  return s || name.slice(0, 42);
}

export default function OrderTicker() {
  const [items, setItems] = useState([]);

  const load = async () => {
    try {
      const r = await api.get("/orders/recent-feed");
      setItems(r.data.feed || []);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  if (!items.length) return null;

  // Duplicate for seamless marquee loop
  const loop = [...items, ...items];

  return (
    <div
      data-testid="order-ticker"
      className="fixed bottom-0 left-0 right-0 z-40 border-t border-white/10 bg-[#050505]/95 backdrop-blur-md"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="flex items-center gap-3 py-2 px-3 md:px-6">
        <div
          className="hidden sm:flex items-center gap-2 shrink-0 text-[10px] uppercase tracking-[0.25em] text-[#00E5FF] font-bold"
          data-testid="ticker-label"
        >
          <span className="w-2 h-2 rounded-full bg-[#00E5FF] animate-pulse" />
          Live orders
        </div>
        <div className="flex-1 overflow-hidden mask-fade">
          <div className="flex gap-8 animate-ticker whitespace-nowrap will-change-transform pr-20">
            {loop.map((it, i) => (
              <span
                key={i}
                data-testid={`ticker-item-${i}`}
                className="inline-flex items-center gap-2 text-xs text-white/70"
              >
                <ShoppingBag className="w-3 h-3 text-[#FF007F] shrink-0" />
                <span className="font-mono text-[#FF007F] font-bold">{it.user}</span>
                <span className="text-white/40">bought</span>
                <span className="text-white">
                  {it.quantity?.toLocaleString()} <span className="text-white/60">·</span>{" "}
                  {shortService(it.service)}
                </span>
                <span className="text-white/30">· {timeAgo(it.created_at)}</span>
              </span>
            ))}
          </div>
        </div>
      </div>
      <style>{`
        @keyframes bs-ticker {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
        .animate-ticker {
          animation: bs-ticker 60s linear infinite;
        }
        .animate-ticker:hover {
          animation-play-state: paused;
        }
        .mask-fade {
          -webkit-mask-image: linear-gradient(to right, transparent, black 6%, black 94%, transparent);
          mask-image: linear-gradient(to right, transparent, black 6%, black 94%, transparent);
        }
      `}</style>
    </div>
  );
}
