import { useEffect, useState } from "react";
import { Loader2, Trophy, Radio, Calendar } from "lucide-react";
import { api } from "@/lib/api";

// Football / Soccer live + upcoming matches using the RapidAPI free-football
// endpoints. Read-only for now — no bets can be placed on these fixtures.
export default function SportsView() {
  const [tab, setTab] = useState("live");
  const [live, setLive] = useState([]);
  const [upcoming, setUpcoming] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = async () => {
    setLoading(true);
    setErr("");
    try {
      const [rl, ru] = await Promise.all([
        api.get("/sports/livescores"),
        api.get("/sports/upcoming"),
      ]);
      const liveList = extractMatches(rl.data.matches);
      const upList = extractMatches(ru.data.matches);
      setLive(liveList);
      setUpcoming(upList);
      if (rl.data.error && ru.data.error) setErr("Sports source is temporarily unavailable — retry in a minute.");
    } catch (e) {
      setErr("Couldn't load sports data.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // Auto-refresh live scores every 30s
    const int = setInterval(load, 30000);
    return () => clearInterval(int);
  }, []);

  const activeList = tab === "live" ? live : upcoming;

  return (
    <div className="max-w-5xl mx-auto space-y-6" data-testid="sports-view">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight flex items-center gap-2">
            <Trophy className="w-7 h-7 text-emerald-400" /> Sports · Football
          </h1>
          <p className="text-white/50 text-sm mt-2">Live & upcoming fixtures across the world&apos;s top leagues.</p>
        </div>
        <div className="flex gap-2">
          <button
            data-testid="sports-tab-live"
            onClick={() => setTab("live")}
            className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-[11px] font-black uppercase tracking-wider transition ${tab === "live" ? "bg-red-500 text-white" : "bg-[#0d0a14] text-white/70 hover:text-white border border-white/10"}`}
          >
            <Radio className="w-3 h-3" /> Live ({live.length})
          </button>
          <button
            data-testid="sports-tab-upcoming"
            onClick={() => setTab("upcoming")}
            className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-[11px] font-black uppercase tracking-wider transition ${tab === "upcoming" ? "bg-emerald-500 text-black" : "bg-[#0d0a14] text-white/70 hover:text-white border border-white/10"}`}
          >
            <Calendar className="w-3 h-3" /> Upcoming ({upcoming.length})
          </button>
        </div>
      </div>

      {err && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-md p-3 text-xs text-amber-300 text-center">{err}</div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16"><Loader2 className="w-6 h-6 animate-spin text-emerald-400" /></div>
      ) : activeList.length === 0 ? (
        <div className="bg-[#0d0a14] border border-white/10 rounded-md p-10 text-center text-sm text-white/50">
          {tab === "live" ? "No matches currently live." : "No upcoming matches in the next few hours."}
        </div>
      ) : (
        <div className="grid gap-2" data-testid={`sports-list-${tab}`}>
          {activeList.map((m, i) => (
            <MatchRow key={m.id || i} m={m} isLive={tab === "live"} />
          ))}
        </div>
      )}
    </div>
  );
}

function MatchRow({ m, isLive }) {
  return (
    <div className="bg-[#0d0a14] border border-white/10 rounded-md p-4 flex items-center gap-4 hover:border-emerald-500/30 transition" data-testid={`sports-match-${m.id || ""}`}>
      <div className="flex-1 flex items-center justify-between gap-4 min-w-0">
        <div className="flex-1 text-right min-w-0">
          <div className="font-bold text-white truncate">{m.home}</div>
        </div>
        <div className="shrink-0 text-center min-w-[70px]">
          {isLive ? (
            <>
              <div className="font-display text-2xl font-black text-emerald-300">{m.homeScore ?? "-"} : {m.awayScore ?? "-"}</div>
              <div className="text-[9px] uppercase tracking-widest text-red-300 font-bold flex items-center justify-center gap-1 mt-0.5">
                <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />
                {m.minute || "LIVE"}
              </div>
            </>
          ) : (
            <>
              <div className="font-display text-sm font-black text-emerald-300">{m.kickoff || "TBD"}</div>
              <div className="text-[9px] uppercase tracking-widest text-white/40 font-bold mt-0.5">vs</div>
            </>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-bold text-white truncate">{m.away}</div>
        </div>
      </div>
      {m.league && (
        <div className="hidden sm:block text-[9px] uppercase tracking-widest text-emerald-400/60 shrink-0 max-w-[120px] truncate">{m.league}</div>
      )}
    </div>
  );
}

// The RapidAPI response format varies by endpoint — normalise whatever we get
// so the UI never has to guess field names.
function extractMatches(raw) {
  if (!raw) return [];
  const arr = Array.isArray(raw) ? raw : Array.isArray(raw.matches) ? raw.matches : Array.isArray(raw.data) ? raw.data : [];
  return arr.slice(0, 100).map((m, i) => {
    const home = m.home?.name || m.homeTeam?.name || m.homeTeam || m.team1?.name || m.home_name || m.homeShortName || "Home";
    const away = m.away?.name || m.awayTeam?.name || m.awayTeam || m.team2?.name || m.away_name || m.awayShortName || "Away";
    const homeScore = m.home?.score ?? m.homeScore ?? m.score?.home ?? m.goalsHome ?? null;
    const awayScore = m.away?.score ?? m.awayScore ?? m.score?.away ?? m.goalsAway ?? null;
    const minute = m.status?.liveTime?.short || m.time || m.minute || m.status?.name || null;
    const kickoff = m.time?.starting_at?.date_time || m.startTime || m.kickoff || m.datetime || m.fixture?.date || m.date || null;
    const league = m.league?.name || m.competition?.name || m.tournament?.name || null;
    let kickoffFmt = kickoff;
    try {
      if (kickoff && !isNaN(Date.parse(kickoff))) {
        kickoffFmt = new Date(kickoff).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
      }
    } catch { /* keep raw */ }
    return {
      id: m.id || m.fixture?.id || m.match_id || i,
      home,
      away,
      homeScore,
      awayScore,
      minute,
      kickoff: kickoffFmt,
      league,
    };
  });
}
