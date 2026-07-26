import { useEffect, useState, useMemo, useCallback } from "react";
import { Loader2, Trophy, Radio, Calendar, X, Ticket, DollarSign, TrendingUp, ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

// Live sports view with betting.
// Users can pick 1X2 odds on any match, build a slip, and place single or
// combo bets. Combos multiply odds. Balance is deducted on place.
// Cashout button on My Bets refunds 85% of stake for open bets.
const DEFAULT_ODDS = { home: 2.10, draw: 3.20, away: 3.40 };

export default function SportsView() {
  const { user, authedApi, reloadBalance } = useAuth();
  const [tab, setTab] = useState("live"); // live | upcoming | mybets
  const [live, setLive] = useState([]);
  const [upcoming, setUpcoming] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [oddsMap, setOddsMap] = useState({}); // { matchId: { home, draw, away } }
  const [slip, setSlip] = useState([]); // [{ matchId, matchLabel, selection: 'home'|'draw'|'away', odds }]
  const [stake, setStake] = useState("1");
  const [placing, setPlacing] = useState(false);
  const [myBets, setMyBets] = useState([]);
  const [betsLoading, setBetsLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const [rl, ru] = await Promise.all([api.get("/sports/livescores"), api.get("/sports/upcoming")]);
      const liveList = extractMatches(rl.data.matches);
      const upList = extractMatches(ru.data.matches);
      setLive(liveList);
      setUpcoming(upList);
      if (rl.data.error && ru.data.error) setErr("Sports source is temporarily unavailable — retry in a minute.");
      // Prefetch odds for all matches in parallel (best-effort, fall back to defaults)
      const ids = [...liveList, ...upList].map((m) => m.id).filter(Boolean).slice(0, 40);
      if (ids.length) {
        const results = await Promise.all(
          ids.map((id) =>
            api.get(`/sports/odds/${encodeURIComponent(id)}`).catch(() => ({ data: { markets: { "1X2": DEFAULT_ODDS } } }))
          )
        );
        const next = {};
        ids.forEach((id, i) => {
          const m = results[i]?.data?.markets?.["1X2"] || DEFAULT_ODDS;
          next[id] = { home: m.home ?? DEFAULT_ODDS.home, draw: m.draw ?? DEFAULT_ODDS.draw, away: m.away ?? DEFAULT_ODDS.away };
        });
        setOddsMap(next);
      }
    } catch (e) {
      setErr("Couldn't load sports data.");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadMyBets = useCallback(async () => {
    if (!user) return;
    setBetsLoading(true);
    try {
      const r = await authedApi().get("/client/sports/my-bets");
      setMyBets(r.data.bets || []);
    } catch { /* keep silent */ } finally { setBetsLoading(false); }
  }, [user, authedApi]);

  useEffect(() => {
    load();
    const int = setInterval(load, 30000);
    return () => clearInterval(int);
  }, [load]);

  useEffect(() => { if (tab === "mybets") loadMyBets(); }, [tab, loadMyBets]);

  const activeList = tab === "live" ? live : tab === "upcoming" ? upcoming : [];

  const addToSlip = (m, selection) => {
    if (!user) { toast.error("Sign in to place bets."); return; }
    const odds = (oddsMap[m.id] || DEFAULT_ODDS)[selection];
    setSlip((prev) => {
      // If a selection for this match already exists, replace it (can't bet on multiple outcomes of same match).
      const filtered = prev.filter((s) => s.matchId !== String(m.id));
      return [...filtered, { matchId: String(m.id), matchLabel: `${m.home} vs ${m.away}`, selection, odds }];
    });
    toast.success(`${selection.toUpperCase()} @ ${odds.toFixed(2)} added to slip`);
  };

  const removeFromSlip = (matchId) => setSlip((prev) => prev.filter((s) => s.matchId !== matchId));
  const combinedOdds = useMemo(() => slip.reduce((a, s) => a * s.odds, 1), [slip]);
  const potentialWin = useMemo(() => (Number(stake) || 0) * combinedOdds, [stake, combinedOdds]);

  const placeBet = async () => {
    if (!slip.length) { toast.error("Add at least one selection"); return; }
    const stakeNum = Number(stake) || 0;
    if (stakeNum < 0.10) { toast.error("Min stake is $0.10"); return; }
    if (stakeNum > 20) { toast.error("Max stake is $20"); return; }
    setPlacing(true);
    try {
      const body = {
        stake: stakeNum,
        selections: slip.map((s) => ({
          match_id: s.matchId,
          match_label: s.matchLabel,
          market: "1X2",
          selection: s.selection,
          odds: s.odds,
        })),
      };
      const r = await authedApi().post("/client/sports/bet", body);
      toast.success(`Bet placed! Stake $${stakeNum.toFixed(2)} → potential win $${r.data.bet.potential_win.toFixed(2)}`);
      setSlip([]);
      setStake("1");
      reloadBalance && reloadBalance();
      loadMyBets();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to place bet");
    } finally { setPlacing(false); }
  };

  const cashout = async (betId) => {
    try {
      const r = await authedApi().post(`/client/sports/bet/${betId}/cashout`);
      toast.success(`Cashed out $${r.data.refund.toFixed(2)} @ ${Math.round(r.data.rate * 100)}%`);
      reloadBalance && reloadBalance();
      loadMyBets();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Cashout failed");
    }
  };

  return (
    <div className="max-w-7xl mx-auto space-y-6" data-testid="sports-view">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight flex items-center gap-2">
            <Trophy className="w-7 h-7 text-emerald-400" /> Sports · Football
          </h1>
          <p className="text-white/50 text-sm mt-2">Live & upcoming fixtures — tap odds to bet. Min $0.10 · Max $20 per slip.</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <TabBtn active={tab === "live"} onClick={() => setTab("live")} testId="sports-tab-live" tone="red">
            <Radio className="w-3 h-3" /> Live ({live.length})
          </TabBtn>
          <TabBtn active={tab === "upcoming"} onClick={() => setTab("upcoming")} testId="sports-tab-upcoming" tone="emerald">
            <Calendar className="w-3 h-3" /> Upcoming ({upcoming.length})
          </TabBtn>
          <TabBtn active={tab === "mybets"} onClick={() => setTab("mybets")} testId="sports-tab-mybets" tone="amber">
            <Ticket className="w-3 h-3" /> My Bets ({myBets.length})
          </TabBtn>
        </div>
      </div>

      {err && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-md p-3 text-xs text-amber-300 text-center">{err}</div>
      )}

      <div className="grid lg:grid-cols-[1fr_320px] gap-6">
        {/* Match list OR my bets */}
        <div>
          {tab === "mybets" ? (
            <MyBetsList bets={myBets} loading={betsLoading} onCashout={cashout} />
          ) : loading ? (
            <div className="flex items-center justify-center py-16"><Loader2 className="w-6 h-6 animate-spin text-emerald-400" /></div>
          ) : activeList.length === 0 ? (
            <div className="bg-[#0d0a14] border border-white/10 rounded-md p-10 text-center text-sm text-white/50">
              {tab === "live" ? "No matches currently live." : "No upcoming matches in the next few hours."}
            </div>
          ) : (
            <div className="grid gap-2" data-testid={`sports-list-${tab}`}>
              {activeList.map((m, i) => (
                <MatchRow
                  key={m.id || i}
                  m={m}
                  isLive={tab === "live"}
                  odds={oddsMap[m.id] || DEFAULT_ODDS}
                  onPick={(sel) => addToSlip(m, sel)}
                  activePick={slip.find((s) => s.matchId === String(m.id))?.selection}
                />
              ))}
            </div>
          )}
        </div>

        {/* Betslip */}
        <BetSlip
          slip={slip}
          onRemove={removeFromSlip}
          onClear={() => setSlip([])}
          stake={stake}
          setStake={setStake}
          combinedOdds={combinedOdds}
          potentialWin={potentialWin}
          onPlace={placeBet}
          placing={placing}
          signedIn={!!user}
        />
      </div>
    </div>
  );
}

function TabBtn({ active, onClick, testId, tone, children }) {
  const activeCls = tone === "red"
    ? "bg-red-500 text-white"
    : tone === "amber"
    ? "bg-amber-500 text-black"
    : "bg-emerald-500 text-black";
  return (
    <button
      onClick={onClick}
      data-testid={testId}
      className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-[11px] font-black uppercase tracking-wider transition ${active ? activeCls : "bg-[#0d0a14] text-white/70 hover:text-white border border-white/10"}`}
    >
      {children}
    </button>
  );
}

function MatchRow({ m, isLive, odds, onPick, activePick }) {
  return (
    <div className="bg-[#0d0a14] border border-white/10 rounded-md p-3 md:p-4 hover:border-emerald-500/30 transition" data-testid={`sports-match-${m.id || ""}`}>
      <div className="flex items-center gap-3 md:gap-4">
        <div className="flex-1 min-w-0 flex items-center justify-between gap-3">
          <div className="flex-1 text-right min-w-0">
            <div className="font-bold text-white truncate text-sm md:text-base">{m.home}</div>
          </div>
          <div className="shrink-0 text-center min-w-[70px]">
            {isLive ? (
              <>
                <div className="font-display text-xl md:text-2xl font-black text-emerald-300">{m.homeScore ?? "-"} : {m.awayScore ?? "-"}</div>
                <div className="text-[9px] uppercase tracking-widest text-red-300 font-bold flex items-center justify-center gap-1 mt-0.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />
                  {m.minute || "LIVE"}
                </div>
              </>
            ) : (
              <>
                <div className="font-display text-xs md:text-sm font-black text-emerald-300">{m.kickoff || "TBD"}</div>
                <div className="text-[9px] uppercase tracking-widest text-white/40 font-bold mt-0.5">vs</div>
              </>
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-bold text-white truncate text-sm md:text-base">{m.away}</div>
          </div>
        </div>
      </div>
      {m.league && (
        <div className="text-[9px] uppercase tracking-widest text-emerald-400/60 mt-2">{m.league}</div>
      )}
      {/* Odds row */}
      <div className="grid grid-cols-3 gap-2 mt-3">
        <OddsBtn label="1" hint={m.home} value={odds.home} active={activePick === "home"} onClick={() => onPick("home")} testId={`odds-home-${m.id}`} />
        <OddsBtn label="X" hint="Draw" value={odds.draw} active={activePick === "draw"} onClick={() => onPick("draw")} testId={`odds-draw-${m.id}`} />
        <OddsBtn label="2" hint={m.away} value={odds.away} active={activePick === "away"} onClick={() => onPick("away")} testId={`odds-away-${m.id}`} />
      </div>
    </div>
  );
}

function OddsBtn({ label, hint, value, active, onClick, testId }) {
  return (
    <button
      onClick={onClick}
      data-testid={testId}
      className={`px-2 py-2 rounded-md border transition text-left ${active ? "border-emerald-400 bg-emerald-500/20" : "border-white/10 bg-black/30 hover:border-emerald-500/40 hover:bg-emerald-500/10"}`}
    >
      <div className="flex items-center gap-2">
        <span className={`text-[10px] font-black uppercase tracking-widest ${active ? "text-emerald-300" : "text-white/40"}`}>{label}</span>
        <span className="text-[10px] text-white/50 truncate flex-1 min-w-0">{hint}</span>
      </div>
      <div className={`font-display font-black text-base mt-0.5 ${active ? "text-emerald-300" : "text-white"}`}>{Number(value).toFixed(2)}</div>
    </button>
  );
}

function BetSlip({ slip, onRemove, onClear, stake, setStake, combinedOdds, potentialWin, onPlace, placing, signedIn }) {
  return (
    <aside className="bg-[#0d2b12] border border-emerald-500/30 rounded-md p-4 flex flex-col gap-3 self-start sticky top-4" data-testid="betslip">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Ticket className="w-4 h-4 text-emerald-300" />
          <h3 className="font-display font-black text-sm uppercase tracking-widest text-emerald-200">Bet Slip</h3>
          <span className="text-xs text-white/50">({slip.length})</span>
        </div>
        {slip.length > 0 && (
          <button onClick={onClear} data-testid="betslip-clear" className="text-[10px] uppercase tracking-widest text-white/50 hover:text-white">Clear</button>
        )}
      </div>

      {slip.length === 0 ? (
        <div className="text-center py-8 text-xs text-white/40">Tap odds to build your bet.</div>
      ) : (
        <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
          {slip.map((s) => (
            <div key={s.matchId} className="bg-black/40 rounded-sm px-2.5 py-2 text-xs border border-emerald-500/20" data-testid={`slip-item-${s.matchId}`}>
              <div className="flex items-center gap-1.5">
                <span className="text-emerald-300 font-black uppercase tracking-widest text-[10px]">{s.selection === "home" ? "1" : s.selection === "away" ? "2" : "X"}</span>
                <span className="text-white/70 truncate flex-1 min-w-0">{s.matchLabel}</span>
                <button onClick={() => onRemove(s.matchId)} data-testid={`slip-remove-${s.matchId}`} className="text-white/40 hover:text-red-300">
                  <X className="w-3 h-3" />
                </button>
              </div>
              <div className="text-[10px] text-white/40 mt-1 flex items-center justify-between">
                <span>{s.selection.toUpperCase()}</span>
                <span className="font-mono font-bold text-emerald-300">@ {s.odds.toFixed(2)}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="border-t border-emerald-500/20 pt-3 space-y-2">
        <label className="text-[10px] uppercase tracking-widest text-white/50 block">Stake (USD)</label>
        <div className="relative">
          <DollarSign className="w-3.5 h-3.5 text-white/40 absolute left-2 top-1/2 -translate-y-1/2" />
          <input
            type="number"
            min="0.10"
            max="20"
            step="0.10"
            value={stake}
            onChange={(e) => setStake(e.target.value)}
            data-testid="betslip-stake"
            className="w-full bg-black/40 border border-emerald-500/30 rounded-md pl-7 pr-3 py-2 text-sm text-white outline-none focus:border-emerald-400"
          />
        </div>
        <div className="flex gap-1">
          {[0.5, 1, 5, 10, 20].map((q) => (
            <button key={q} onClick={() => setStake(String(q))} className="flex-1 py-1 text-[10px] rounded border border-white/10 hover:bg-white/5 text-white/70">${q}</button>
          ))}
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-white/50">Combined odds</span>
          <span className="font-mono font-black text-emerald-300">{combinedOdds.toFixed(2)}</span>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-white/50">Potential win</span>
          <span className="font-mono font-black text-amber-300 flex items-center gap-1"><TrendingUp className="w-3 h-3" />${potentialWin.toFixed(2)}</span>
        </div>
        <button
          onClick={onPlace}
          disabled={placing || !slip.length || !signedIn}
          data-testid="betslip-place"
          className="w-full py-3 rounded-md font-black text-sm uppercase tracking-widest bg-gradient-to-r from-emerald-500 to-emerald-400 text-black hover:from-emerald-400 hover:to-emerald-300 disabled:opacity-40 disabled:cursor-not-allowed transition inline-flex items-center justify-center gap-2"
        >
          {placing ? <Loader2 className="w-4 h-4 animate-spin" /> : <ChevronRight className="w-4 h-4" />}
          {!signedIn ? "Sign in to bet" : `Place Bet · $${(Number(stake) || 0).toFixed(2)}`}
        </button>
      </div>
    </aside>
  );
}

function MyBetsList({ bets, loading, onCashout }) {
  if (loading) return <div className="flex items-center justify-center py-16"><Loader2 className="w-6 h-6 animate-spin text-emerald-400" /></div>;
  if (!bets.length) return (
    <div className="bg-[#0d0a14] border border-white/10 rounded-md p-10 text-center text-sm text-white/50">
      No bets yet. Pick some odds to get started.
    </div>
  );
  return (
    <div className="space-y-2" data-testid="my-bets-list">
      {bets.map((b) => (
        <div key={b.id} className="bg-[#0d0a14] border border-white/10 rounded-md p-3 md:p-4" data-testid={`mybet-${b.id}`}>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2 text-xs">
              <span className={`px-2 py-0.5 text-[10px] uppercase tracking-widest rounded-sm font-black ${
                b.status === "open" ? "bg-amber-500/20 text-amber-300" :
                b.status === "won" ? "bg-emerald-500/20 text-emerald-300" :
                b.status === "cashed_out" ? "bg-sky-500/20 text-sky-300" :
                "bg-red-500/20 text-red-300"
              }`}>{b.status}</span>
              <span className="text-white/40 font-mono text-[10px]">#{b.id.slice(0, 8)}</span>
              {b.is_combo && <span className="text-[10px] uppercase tracking-widest text-fuchsia-300 font-black">COMBO</span>}
            </div>
            <div className="flex items-center gap-3 text-xs">
              <span className="text-white/50">Stake <span className="font-mono font-bold text-white">${b.stake.toFixed(2)}</span></span>
              <span className="text-white/50">@ <span className="font-mono font-bold text-emerald-300">{b.combined_odds.toFixed(2)}</span></span>
              <span className="text-white/50">Win <span className="font-mono font-bold text-amber-300">${b.potential_win.toFixed(2)}</span></span>
            </div>
          </div>
          <div className="mt-2 space-y-1">
            {(b.selections || []).map((s, i) => (
              <div key={i} className="text-[11px] text-white/60 flex items-center gap-2">
                <span className="text-emerald-300 font-black uppercase tracking-widest">{s.selection === "home" ? "1" : s.selection === "away" ? "2" : s.selection.toUpperCase()}</span>
                <span className="truncate">{s.match_label || s.match_id}</span>
                <span className="ml-auto font-mono text-white/40">@{Number(s.odds).toFixed(2)}</span>
              </div>
            ))}
          </div>
          {b.status === "open" && (
            <div className="mt-3 flex justify-end">
              <button
                onClick={() => onCashout(b.id)}
                data-testid={`cashout-${b.id}`}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] uppercase tracking-widest font-black text-black bg-amber-400 hover:bg-amber-300"
              >
                Cash Out · ~${(b.stake * 0.85).toFixed(2)}
              </button>
            </div>
          )}
          {b.status === "cashed_out" && b.cashout_amount != null && (
            <div className="mt-2 text-[10px] text-sky-300 text-right">Cashed out for <span className="font-bold">${Number(b.cashout_amount).toFixed(2)}</span></div>
          )}
        </div>
      ))}
    </div>
  );
}

// Normalise varied API shapes into a single match object.
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
      id: String(m.id || m.fixture?.id || m.match_id || i),
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
