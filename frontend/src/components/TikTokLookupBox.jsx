import { useState } from "react";
import { Search, CheckCircle2, Globe, Calendar, Users, Heart, Video, ExternalLink, Loader2, Lock } from "lucide-react";
import { api } from "@/lib/api";

// Free public TikTok profile lookup — anyone can use it, no login required.
// Backend endpoint: GET /api/tools/tiktok-lookup?username=<handle>
export default function TikTokLookupBox({ variant = "hero" }) {
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const run = async (e) => {
    e?.preventDefault?.();
    const handle = q.trim().replace(/^@/, "");
    if (!handle) return;
    setLoading(true); setError(""); setResult(null);
    try {
      const r = await api.get(`/tools/tiktok-lookup?username=${encodeURIComponent(handle)}`);
      setResult(r.data);
    } catch (err) {
      setError(err.response?.data?.detail || "Lookup failed");
    }
    setLoading(false);
  };

  const fmt = (n) => {
    if (n == null) return "—";
    if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
    if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
    if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
    return String(n);
  };

  return (
    <div
      data-testid="tiktok-lookup-box"
      className={`rounded-2xl border ${variant === "hero" ? "bg-gradient-to-br from-emerald-500/10 via-[#0e2f18]/70 to-[#0a1a0a]/70 border-emerald-500/30" : "bg-emerald-950/40 border-emerald-500/25"} p-5 md:p-6 backdrop-blur`}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[10px] uppercase tracking-widest text-emerald-300 font-black">Free TikTok Lookup</span>
        <span className="text-[9px] uppercase tracking-widest px-1.5 py-0.5 rounded bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 font-bold">Unlimited · No sign-up</span>
      </div>
      <h3 className="font-display font-black text-xl md:text-2xl text-white mb-3 leading-tight">
        Look up any TikTok account
      </h3>
      <p className="text-xs text-white/60 mb-4">
        Enter a username to see the account&apos;s country, creation date, followers, likes, videos and verification status.
      </p>

      <form onSubmit={run} className="flex gap-2">
        <div className="relative flex-1">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-emerald-300 font-bold">@</span>
          <input
            data-testid="tiktok-lookup-input"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="username"
            className="w-full pl-8 pr-3 py-3 rounded-md bg-black/40 border border-emerald-500/30 text-white outline-none focus:border-emerald-400 transition text-sm font-mono"
          />
        </div>
        <button
          type="submit"
          disabled={loading || !q.trim()}
          data-testid="tiktok-lookup-btn"
          className="px-4 py-3 rounded-md bg-emerald-400 hover:bg-emerald-300 text-black font-black text-xs uppercase tracking-widest disabled:opacity-40 inline-flex items-center gap-2"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
          Lookup
        </button>
      </form>

      {error && (
        <div data-testid="tiktok-lookup-error" className="mt-3 p-3 rounded-md bg-red-500/10 border border-red-500/30 text-red-200 text-xs">
          {error}
        </div>
      )}

      {result && (
        <div data-testid="tiktok-lookup-result" className="mt-4 space-y-4">
          <div className="flex items-center gap-3">
            {result.avatar ? (
              <img src={result.avatar} alt={result.handle} className="w-16 h-16 rounded-full object-cover border-2 border-emerald-500/40" />
            ) : (
              <div className="w-16 h-16 rounded-full bg-emerald-500/20 border-2 border-emerald-500/40 flex items-center justify-center text-2xl font-black text-emerald-200">
                {result.handle?.[0]?.toUpperCase() || "?"}
              </div>
            )}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <a href={result.profile_url} target="_blank" rel="noreferrer" className="font-display font-black text-lg text-white hover:text-emerald-300 truncate inline-flex items-center gap-1">
                  @{result.handle}
                  <ExternalLink className="w-3.5 h-3.5 opacity-60" />
                </a>
                {result.verified && <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />}
                {result.private && <Lock className="w-4 h-4 text-amber-400 shrink-0" title="Private account" />}
              </div>
              <div className="text-sm text-white/70 truncate">{result.nickname || "—"}</div>
              {result.signature && <div className="text-xs text-white/50 mt-1 line-clamp-2">{result.signature}</div>}
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat icon={Users}    label="Followers" value={fmt(result.followers)} />
            <Stat icon={Heart}    label="Likes"     value={fmt(result.hearts)} />
            <Stat icon={Video}    label="Videos"    value={fmt(result.videos)} />
            <Stat icon={Users}    label="Following" value={fmt(result.following)} />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
            <InfoRow icon={Globe} label="Country / region">
              {result.detected_country?.country ? (
                <span className="text-white font-bold inline-flex items-center gap-1.5">
                  <span>{result.detected_country.name}</span>
                  <span
                    className={`text-[9px] uppercase font-black tracking-wider px-1.5 py-0.5 rounded ${
                      result.detected_country.confidence === "high" ? "bg-emerald-500/25 text-emerald-200" :
                      result.detected_country.confidence === "medium" ? "bg-sky-500/25 text-sky-200" :
                      "bg-white/10 text-white/50"
                    }`}
                    title={`Detected from: ${result.detected_country.source}`}
                  >
                    {result.detected_country.confidence}
                  </span>
                </span>
              ) : result.region ? (
                <span className="text-white font-bold">{result.region}</span>
              ) : (
                <span className="text-white/40">Not public</span>
              )}
            </InfoRow>
            <InfoRow icon={Calendar} label="Created">
              {result.created_at ? (
                <span className="text-white font-bold">{new Date(result.created_at).toLocaleDateString()}</span>
              ) : (
                <span className="text-white/50">{result.created_note || "Unknown"}</span>
              )}
            </InfoRow>
            {result.user_id && (
              <InfoRow icon={Users} label="User ID">
                <span className="font-mono text-emerald-200 text-[11px] truncate">{result.user_id}</span>
              </InfoRow>
            )}
            {result.language && (
              <InfoRow icon={Globe} label="Language">
                <span className="text-white uppercase font-bold">{result.language}</span>
              </InfoRow>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ icon: Icon, label, value }) {
  return (
    <div className="rounded-md bg-black/30 border border-white/5 p-3 text-center">
      <Icon className="w-4 h-4 mx-auto text-emerald-300 mb-1" />
      <div className="text-lg font-black text-white leading-none">{value}</div>
      <div className="text-[9px] uppercase tracking-widest text-white/40 mt-1">{label}</div>
    </div>
  );
}

function InfoRow({ icon: Icon, label, children }) {
  return (
    <div className="rounded-md bg-black/30 border border-white/5 px-3 py-2 flex items-center gap-2">
      <Icon className="w-3.5 h-3.5 text-emerald-300 shrink-0" />
      <span className="text-[10px] uppercase tracking-widest text-white/40">{label}</span>
      <span className="ml-auto truncate">{children}</span>
    </div>
  );
}
