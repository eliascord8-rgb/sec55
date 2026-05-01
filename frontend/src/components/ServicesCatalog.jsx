import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Loader2, Search, TrendingUp, ArrowRight } from "lucide-react";

export default function ServicesCatalog() {
  const [services, setServices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");
  const navigate = useNavigate();

  useEffect(() => {
    api
      .get("/services")
      .then((r) => setServices(Array.isArray(r.data.services) ? r.data.services : []))
      .catch(() => setServices([]))
      .finally(() => setLoading(false));
  }, []);

  const categories = useMemo(() => {
    const set = new Set(["All"]);
    services.forEach((s) => s.category && set.add(s.category));
    return Array.from(set);
  }, [services]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return services
      .filter((s) => (category === "All" ? true : s.category === category))
      .filter((s) => (q ? `${s.name} ${s.category}`.toLowerCase().includes(q) : true));
  }, [services, search, category]);

  return (
    <section className="py-16 md:py-24 border-t border-white/5 bg-[#0d0a14]" id="services">
      <div className="max-w-7xl mx-auto px-4 md:px-10">
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-6 mb-8">
          <div>
            <div className="text-xs uppercase tracking-[0.3em] text-[#00E5FF] mb-3">Live catalog</div>
            <h2 className="font-display text-3xl md:text-5xl font-black tracking-tighter">
              Pick your <span className="gradient-text">boost</span>.
            </h2>
          </div>
          <div className="relative w-full md:w-80">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-white/40" />
            <Input
              data-testid="catalog-search"
              placeholder="Search services…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 bg-[#1a1525] border-white/10 text-white"
            />
          </div>
        </div>

        <div className="flex gap-2 overflow-x-auto pb-3 mb-6 -mx-4 px-4 md:mx-0 md:px-0">
          {categories.slice(0, 20).map((c) => (
            <button
              key={c}
              onClick={() => setCategory(c)}
              data-testid={`cat-${c}`}
              className={`shrink-0 px-3 py-1.5 text-xs uppercase tracking-wider rounded-sm whitespace-nowrap transition ${
                category === c
                  ? "bg-[#FF007F] text-white font-bold"
                  : "bg-white/5 text-white/60 hover:bg-white/10"
              }`}
            >
              {c}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 text-white/40">
            <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading services…
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-16 text-white/40 text-sm">
            No services live yet. Admin needs to enable services.
          </div>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3 md:gap-4">
            {filtered.slice(0, 60).map((s) => (
              <button
                key={s.service}
                data-testid={`card-service-${s.service}`}
                onClick={() => navigate(`/order/${s.service}`)}
                className="group text-left p-5 rounded-sm border border-white/5 bg-[#1a1525] hover:border-[#FF007F]/50 hover:-translate-y-0.5 transition"
              >
                <div className="flex items-start justify-between gap-3 mb-2">
                  <span className="text-[10px] uppercase tracking-wider text-[#00E5FF] truncate max-w-[60%]">
                    {s.category}
                  </span>
                  <span className="font-mono text-[10px] text-white/40">#{s.service}</span>
                </div>
                <div className="text-sm font-medium mb-4 leading-snug line-clamp-2 min-h-[2.5rem]">
                  {s.name}
                </div>
                <div className="flex items-end justify-between">
                  <div>
                    <div className="font-display font-black text-2xl gradient-text">
                      ${Number(s.rate).toFixed(2)}
                    </div>
                    <div className="text-[10px] uppercase tracking-wider text-white/40">per 1k</div>
                  </div>
                  <div className="text-[#FF007F] flex items-center gap-1 text-xs uppercase tracking-wider font-bold group-hover:gap-2 transition-all">
                    Order <ArrowRight className="w-3.5 h-3.5" />
                  </div>
                </div>
                <div className="mt-3 pt-3 border-t border-white/5 text-[10px] font-mono text-white/30">
                  Min {s.min} · Max {s.max}
                </div>
              </button>
            ))}
          </div>
        )}

        {filtered.length > 60 && (
          <div className="text-center mt-6 text-xs text-white/40">
            Showing first 60 · refine your search to see more
          </div>
        )}
      </div>
    </section>
  );
}
