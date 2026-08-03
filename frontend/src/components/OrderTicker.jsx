import { useEffect, useState } from "react";
import { toast } from "sonner";
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

function shortText(value, max = 42) {
  if (!value) return "";
  const text = String(value).trim();
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function shortService(name) {
  if (!name) return "an order";
  // Strip emojis and bracketed promo text
  let s = name.replace(/\[[^\]]*\]/g, "").replace(/[^\w\s|/–-]/g, "").trim();
  s = s.replace(/\|.*$/, "").trim();
  return shortText(s, 42) || shortText(name, 42);
}

function tickerText(it) {
  const qty = it.quantity ? `${it.quantity.toLocaleString()} × ` : "";
  const customer = shortText(it.customer_name || it.username || it.user || it.customer || it.link, 20);
  const service = shortService(it.service);
  return customer ? `${qty}${customer} · ${service}` : `${qty}${service}`;
}

export default function OrderTicker() {
  const [, setItem] = useState(null);

  const load = async () => {
    try {
      const r = await api.get("/orders/recent-feed");
      const feed = r.data.feed || [];
      const nextItem = feed[0] || null;
      setItem(nextItem);

      if (!nextItem) return;

      toast(
        <div className="flex items-center gap-3 rounded-2xl border border-emerald-500/25 bg-[#070707]/95 px-3.5 py-3 shadow-[0_0_30px_rgba(16,185,129,0.16)] backdrop-blur-xl">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-300">
            <ShoppingBag className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-[0.28em] text-emerald-400">
              New order
            </div>
            <div className="truncate text-sm font-medium text-white">
              {tickerText(nextItem)}
            </div>
            <div className="text-xs text-white/55">
              {timeAgo(nextItem.created_at)} · {nextItem.quantity ? `${nextItem.quantity}×` : "1×"} order
            </div>
          </div>
        </div>,
        {
          duration: 5000,
          position: "bottom-left",
          className: "border-0 bg-transparent p-0 shadow-none",
          unstyled: true,
        }
      );
    } catch {
      setItem(null);
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 300000);
    return () => clearInterval(t);
  }, []);

  return null;
}
