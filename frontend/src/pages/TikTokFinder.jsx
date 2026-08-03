import { useState } from "react";
import { Search, CheckCircle2, Globe, Calendar, Users, Heart, Video, ExternalLink, Loader2, Lock, Copy, Music2, ArrowLeft, MessageCircle, Download } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";

// Dedicated profile page: keep the TikTok username lookup and add Instagram lookup + profile-picture download.
export default function TikTokFinder() {
  const [platform, setPlatform] = useState("tiktok");
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const run = async (e) => {
    e?.preventDefault?.();
    const v = q.trim().replace(/^@/, "");
    if (!v) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const url = platform === "instagram"
        ? `/tools/instagram-lookup?username=${encodeURIComponent(v)}`
        : `/tools/tiktok-lookup?username=${encodeURIComponent(v)}`;
      const r = await api.get(url);
      setResult(r.data);
    } catch (err) {
      setError(err.response?.data?.detail || "Lookup failed");
    }
    setLoading(false);
  };

  const copy = (val, label) => {
    if (!val) return;
    try {
      navigator.clipboard.writeText(String(val));
      toast.success(`${label} copied`);
    } catch { /* noop */ }
  };

  const downloadAvatar = () => {
    if (!result?.avatar) return;
    try {
      const link = document.createElement("a");
      link.href = result.avatar;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.download = `${result.handle || "profile"}-${platform}.jpg`;
      link.click();
      toast.success("Profile picture opened for download");
    } catch {
      toast.error("Could not download profile picture");
    }
  };

  const fmt = (n) => {
    if (n == null) return "—";
    if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
    if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
    if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
    return String(n);
  };

  const statCards = platform === "instagram"
    ? [
        { icon: Users, label: "Followers", value: fmt(result?.followers), testId: "tt-finder-followers" },
        { icon: Users, label: "Following", value: fmt(result?.following), testId: "tt-finder-following" },
        { icon: Heart, label: "Posts", value: fmt(result?.posts), testId: "tt-finder-posts" },
      ]
    : [
        { icon: Users, label: "Followers", value: fmt(result?.followers), testId: "tt-finder-followers" },
        { icon: Heart, label: "Likes", value: fmt(result?.hearts), testId: "tt-finder-likes" },
        { icon: Video, label: "Videos", value: fmt(result?.videos), testId: "tt-finder-videos" },
        { icon: Users, label: "Following", value: fmt(result?.following), testId: "tt-finder-following" },
      ];

  return (
    <div className="min-h-screen text-white bg-[#0a1a0a] theme-green" data-testid="tiktok-finder-page">
      {/* Header */}
      <header className="bg-[#0d2b12] sticky top-0 z-20 shadow-lg shadow-emerald-900/40 border-b border-emerald-500/20">
        <div className="max-w-5xl mx-auto flex items-center h-16 px-4 md:px-8 gap-4">
          <Link to="/" className="inline-flex items-center gap-2 text-emerald-200 hover:text-white text-xs uppercase tracking-widest font-bold" data-testid="tt-finder-back">
            <ArrowLeft className="w-4 h-4" />
            Back
          </Link>
          <div className="flex items-center gap-2 ml-2">
            <div className="w-9 h-9 rounded-md bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center">
              <Music2 className="w-4 h-4 text-emerald-300" strokeWidth={2.5} />
            </div>
            <span className="font-display font-black text-base text-white tracking-tight">
              TikTok<span className="text-emerald-300">Finder</span>
            </span>
          </div>
          <div className="flex-1" />
          <button
            type="button"
            onClick={() => window.dispatchEvent(new CustomEvent("bs-open-support-chat"))}
            data-testid="tt-finder-open-support"
            title="Open customer support"
            className="inline-flex items-center gap-1.5 h-9 px-3 rounded-md bg-emerald-500 hover:bg-emerald-400 text-black text-[11px] font-black uppercase tracking-widest shadow-lg shadow-emerald-500/40 transition"
          >
            <MessageCircle className="w-4 h-4" strokeWidth={2.5} />
            Support
          </button>
          <span className="hidden sm:inline text-[10px] uppercase tracking-widest text-emerald-300/70 font-bold">Powered by Better Social</span>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 md:px-6 py-10 md:py-14">
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 mb-3">
            <span className="text-[10px] uppercase tracking-widest text-emerald-300 font-black">Free · Unlimited · No sign-up</span>
          </div>
          <h1 className="font-display font-black text-4xl sm:text-5xl lg:text-6xl leading-tight tracking-tight">
            Profile info + <span className="text-emerald-300">profile picture</span> downloader
          </h1>
          <p className="mt-4 text-sm text-white/60 max-w-2xl mx-auto">
            Keep the username lookup for TikTok accounts, and now also look up Instagram profiles and grab their profile picture in one place.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-2 mb-4 max-w-md mx-auto">
          <button
            onClick={() => setPlatform("tiktok")}
            data-testid="tt-finder-tab-tiktok"
            className={`px-3 py-2.5 rounded-md border-2 text-xs font-black uppercase tracking-widest inline-flex items-center justify-center gap-2 transition ${platform === "tiktok" ? "border-emerald-400 bg-emerald-500/15 text-white" : "border-white/10 bg-white/[0.02] text-white/50 hover:text-white/80"}`}
          >
            <Music2 className="w-3.5 h-3.5" /> TikTok
          </button>
          <button
            onClick={() => setPlatform("instagram")}
            data-testid="tt-finder-tab-instagram"
            className={`px-3 py-2.5 rounded-md border-2 text-xs font-black uppercase tracking-widest inline-flex items-center justify-center gap-2 transition ${platform === "instagram" ? "border-emerald-400 bg-emerald-500/15 text-white" : "border-white/10 bg-white/[0.02] text-white/50 hover:text-white/80"}`}
          >
            <span className="text-[11px] font-black">IG</span> Instagram
          </button>
        </div>

        <form onSubmit={run} className="flex gap-2 max-w-xl mx-auto">
          <div className="relative flex-1">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-emerald-300 font-bold">@</span>
            <input
              data-testid="tt-finder-input"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={platform === "instagram" ? "instagram username" : "tiktok username"}
              className="w-full pl-8 pr-3 py-3 rounded-md bg-black/40 border border-emerald-500/30 text-white outline-none focus:border-emerald-400 transition text-sm font-mono"
            />
          </div>
          <button
            type="submit"
            disabled={loading || !q.trim()}
            data-testid="tt-finder-btn"
            className="px-5 py-3 rounded-md bg-emerald-400 hover:bg-emerald-300 text-black font-black text-xs uppercase tracking-widest disabled:opacity-40 inline-flex items-center gap-2 transition"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            Lookup
          </button>
        </form>

        {/* Error */}
        {error && (
          <div data-testid="tt-finder-error" className="mt-6 max-w-xl mx-auto p-3 rounded-md bg-red-500/10 border border-red-500/30 text-red-200 text-xs">
            {error}
          </div>
        )}

        {/* Result */}
        {result && (
          <div data-testid="tt-finder-result" className="mt-8 rounded-2xl border border-emerald-500/25 bg-gradient-to-br from-emerald-500/10 via-[#0e2f18]/70 to-[#0a1a0a]/70 p-5 md:p-6 backdrop-blur space-y-5">
            <div className="flex flex-col md:flex-row md:items-center gap-4">
              {result.avatar ? (
                <img src={result.avatar} alt={result.handle} className="w-24 h-24 rounded-full object-cover border-2 border-emerald-500/40 shadow-lg shadow-emerald-500/20" />
              ) : (
                <div className="w-24 h-24 rounded-full bg-emerald-500/20 border-2 border-emerald-500/40 flex items-center justify-center text-3xl font-black text-emerald-200">
                  {result.handle?.[0]?.toUpperCase() || "?"}
                </div>
              )}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <a href={result.profile_url} target="_blank" rel="noreferrer" className="font-display font-black text-xl text-white hover:text-emerald-300 truncate inline-flex items-center gap-1" data-testid="tt-finder-handle">
                    @{result.handle}
                    <ExternalLink className="w-3.5 h-3.5 opacity-60" />
                  </a>
                  {result.verified && <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />}
                  {result.private && <Lock className="w-4 h-4 text-amber-400 shrink-0" title="Private account" />}
                </div>
                <div className="text-sm text-white/70 truncate">{result.nickname || result.full_name || "—"}</div>
                {result.signature && <div className="text-xs text-white/50 mt-1 whitespace-pre-line line-clamp-3">{result.signature}</div>}
                {result.biography && <div className="text-xs text-white/45 mt-1 whitespace-pre-line line-clamp-3">{result.biography}</div>}
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {statCards.map((stat) => (
                <Stat key={stat.label} icon={stat.icon} label={stat.label} value={stat.value} testId={stat.testId} />
              ))}
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
                  <span className="text-white/50">{result.created_note || result.category || "Unknown"}</span>
                )}
              </InfoRow>
              {result.user_id && (
                <InfoRow icon={Users} label="User ID">
                  <button onClick={() => copy(result.user_id, "User ID")} className="font-mono text-emerald-200 text-[11px] truncate inline-flex items-center gap-1 hover:text-white" data-testid="tt-finder-userid-copy">
                    {result.user_id}
                    <Copy className="w-3 h-3 opacity-60" />
                  </button>
                </InfoRow>
              )}
              {result.language && (
                <InfoRow icon={Globe} label="Language">
                  <span className="text-white uppercase font-bold">{result.language}</span>
                </InfoRow>
              )}
            </div>

            <div className="pt-2 border-t border-emerald-500/15 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={downloadAvatar}
                data-testid="tt-finder-download-avatar"
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md bg-black/30 border border-emerald-500/25 hover:border-emerald-400 hover:bg-emerald-500/10 text-emerald-200 text-[11px] font-black uppercase tracking-widest transition"
              >
                <Download className="w-3.5 h-3.5" /> Download profile picture
              </button>
              <a
                href={result.profile_url}
                target="_blank"
                rel="noreferrer"
                data-testid="tt-finder-open-profile"
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md bg-black/30 border border-emerald-500/25 hover:border-emerald-400 hover:bg-emerald-500/10 text-emerald-200 text-[11px] font-black uppercase tracking-widest transition"
              >
                <ExternalLink className="w-3.5 h-3.5" /> Open profile
              </a>
              <Link
                to="/"
                data-testid="tt-finder-cta-signup"
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md bg-emerald-400 hover:bg-emerald-300 text-black text-[11px] font-black uppercase tracking-widest transition"
              >
                Boost this account →
              </Link>
            </div>
          </div>
        )}
      </main>

      <footer className="border-t border-emerald-500/20 bg-[#0d2b12] py-4 px-4 md:px-8 text-center mt-10">
        <div className="max-w-7xl mx-auto flex items-center justify-center gap-3 flex-wrap text-[10px] uppercase tracking-widest text-white/60">
          <span className="inline-flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span className="font-bold">© {new Date().getFullYear()} BetterSocial</span>
          </span>
          <span className="text-emerald-500/40">·</span>
          <span>Development by <span className="text-emerald-300 font-bold">BK</span> &amp; CEO <span className="text-emerald-300 font-bold">Sinester</span></span>
        </div>
      </footer>
    </div>
  );
}

function Stat({ icon: Icon, label, value, testId }) {
  return (
    <div className="rounded-md bg-black/30 border border-white/5 p-3 text-center" data-testid={testId}>
      <Icon className="w-4 h-4 mx-auto text-emerald-300 mb-1" />
      <div className="text-xl font-black text-white leading-none">{value}</div>
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
