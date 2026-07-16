import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2, Bomb, RotateCcw, Play, Music, Volume2 } from "lucide-react";
import { AviatorGame } from "./SettingsAndAviator";

// -----------------------------------------------------------------------------
// GamesView — top-level wrapper. Two tabs: Slots (Wild-Hot-style) & Stairs.
// -----------------------------------------------------------------------------

const SYMBOL_ART = {
  cherry:  { emoji: "🍒", gradient: "from-red-500 to-red-800" },
  lemon:   { emoji: "🍋", gradient: "from-yellow-300 to-amber-700" },
  orange:  { emoji: "🍊", gradient: "from-orange-400 to-orange-800" },
  plum:    { emoji: "🍇", gradient: "from-purple-500 to-purple-900" },
  grape:   { emoji: "🍇", gradient: "from-violet-500 to-purple-950" },
  melon:   { emoji: "🍉", gradient: "from-red-400 to-emerald-800" },
  seven:   { emoji: "7️⃣", gradient: "from-yellow-300 to-red-600" },
  wild:    { emoji: "⭐", gradient: "from-fuchsia-400 via-purple-500 to-indigo-700", isSpecial: "wild" },
  scatter: { emoji: "🎁", gradient: "from-pink-400 via-red-500 to-yellow-500", isSpecial: "scatter" },
};
const SYMBOL_KEYS = Object.keys(SYMBOL_ART);

export default function GamesView({ authedApi, balance, reloadBalance }) {
  const [tab, setTab] = useState("stairs");
  return (
    <div className="mx-auto w-full max-w-5xl space-y-4" data-testid="games-view">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl md:text-3xl font-black tracking-tight text-white">Games</h1>
          <p className="text-white/50 text-xs md:text-sm mt-1">Instant-play casino. All wins go to your withdrawable balance.</p>
        </div>
      <div className="flex gap-2">
        <button data-testid="games-tab-stairs" onClick={() => setTab("stairs")}
          className={`px-3 py-1.5 rounded-md text-[11px] font-bold uppercase tracking-wider transition ${tab === "stairs" ? "bg-emerald-500 text-black" : "bg-[#0d0a14] text-white/70 hover:text-white border border-white/10"}`}>
          🪜 Stairs
        </button>
        <button data-testid="games-tab-aviator" onClick={() => setTab("aviator")}
          className={`px-3 py-1.5 rounded-md text-[11px] font-bold uppercase tracking-wider transition ${tab === "aviator" ? "bg-emerald-500 text-black" : "bg-[#0d0a14] text-white/70 hover:text-white border border-white/10"}`}>
          ✈️ Aviator
        </button>
      </div>
    </div>
      {tab === "stairs" && <StairsGame authedApi={authedApi} reloadBalance={reloadBalance} />}
      {tab === "aviator" && <AviatorGame authedApi={authedApi} balance={balance} reloadBalance={reloadBalance} />}
    </div>
  );
}

// -----------------------------------------------------------------------------
// SlotsGame — "40 Power Hot" style. 5 reels × 4 rows = 20 tiles.
// -----------------------------------------------------------------------------

const BET_STEPS = [0.20, 0.40, 0.80, 1.20, 1.60, 2.00, 3.00, 5.00];
const SMALL_JACKPOT = 39;
const BIG_JACKPOT = 500;
const ROWS = 4;

function SlotsGame({ authedApi, balance, reloadBalance }) {
  const [betIdx, setBetIdx] = useState(0);
  const bet = BET_STEPS[betIdx];
  const [spinning, setSpinning] = useState(false);
  const [grid, setGrid] = useState(() =>
    Array.from({ length: 5 }, () =>
      Array.from({ length: ROWS }, () => SYMBOL_KEYS[Math.floor(Math.random() * SYMBOL_KEYS.length)])
    )
  );
  const [wins, setWins] = useState([]);
  const [wildMults, setWildMults] = useState({}); // "r,c" → mult
  const [lastPayout, setLastPayout] = useState(0);
  const [freeSpins, setFreeSpins] = useState(0);
  const [scatterCount, setScatterCount] = useState(0);
  const [freeSpinsAwarded, setFreeSpinsAwarded] = useState(0);
  const spinTimer = useRef(null);

  // Load initial free-spin balance
  useEffect(() => {
    (async () => {
      try {
        const r = await authedApi().get("/games/slot/state");
        setFreeSpins(r.data.free_spins || 0);
      } catch { /* first-time users have no state */ }
    })();
  }, []);

  const spin = async () => {
    if (spinning) return;
    const usingFree = freeSpins > 0;
    if (!usingFree && balance < bet) { toast.error("Not enough balance."); return; }
    setSpinning(true);
    setWins([]);
    setWildMults({});
    setLastPayout(0);
    setFreeSpinsAwarded(0);
    setScatterCount(0);
    spinTimer.current = setInterval(() => {
      setGrid(Array.from({ length: 5 }, () =>
        Array.from({ length: ROWS }, () => SYMBOL_KEYS[Math.floor(Math.random() * SYMBOL_KEYS.length)])
      ));
    }, 70);
    try {
      const r = await authedApi().post("/games/slot/spin", { bet, free_spin: usingFree });
      setTimeout(() => {
        clearInterval(spinTimer.current);
        const g = (r.data.grid || []).map((reel) => reel.slice(0, ROWS));
        setGrid(g);
        setWins((r.data.wins || []).filter((w) => w.row < ROWS));
        // Build wildMults lookup
        const wm = {};
        (r.data.wilds || []).forEach((w) => { wm[`${w.reel},${w.row}`] = w.mult; });
        setWildMults(wm);
        setLastPayout(r.data.payout);
        setScatterCount(r.data.scatter_count || 0);
        setFreeSpinsAwarded(r.data.free_spins_awarded || 0);
        setFreeSpins(r.data.free_spins_remaining || 0);
        if (r.data.free_spins_awarded > 0) toast.success(`🎁 ${r.data.free_spins_awarded} FREE SPINS awarded!`);
        else if (r.data.payout > 0) toast.success(`🎉 +$${r.data.payout.toFixed(2)}`);
        reloadBalance?.();
        setSpinning(false);
      }, 900);
    } catch (e) {
      clearInterval(spinTimer.current);
      setSpinning(false);
      toast.error(e.response?.data?.detail || "Spin failed");
    }
  };

  useEffect(() => () => spinTimer.current && clearInterval(spinTimer.current), []);
  const winRows = new Set(wins.map((w) => w.row));

  return (
    <div className="rounded-2xl overflow-hidden shadow-2xl shadow-black/50 border border-yellow-600/40" data-testid="slot-machine">
      {/* Top bar — jackpots */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-1 bg-gradient-to-b from-[#5a1010] to-[#3a0808] p-1.5 md:p-2 border-b border-yellow-600/40">
        <JackpotBadge icon="♠" label="Mini" amount={4.99} color="text-white" />
        <JackpotBadge icon="♥" label="Minor" amount={12.5} color="text-red-300" />
        <JackpotBadge icon="♦" label="Major" amount={SMALL_JACKPOT} color="text-amber-300" glow />
        <JackpotBadge icon="♣" label="Grand" amount={BIG_JACKPOT} color="text-emerald-300" glow big />
      </div>

      {/* Free-spins celebration banner */}
      {freeSpinsAwarded > 0 && !spinning && (
        <div className="bg-gradient-to-r from-fuchsia-600 via-pink-500 to-yellow-500 py-2 text-center animate-pulse" data-testid="free-spins-banner">
          <span className="font-display font-black text-lg md:text-2xl text-white drop-shadow-lg tracking-widest">
            🎁 {freeSpinsAwarded} FREE SPINS! 🎁
          </span>
        </div>
      )}

      {/* Slot canvas */}
      <div className="relative bg-gradient-to-b from-[#3a0808] via-[#2a0505] to-[#3a0808] p-3 md:p-5">
        <div className="flex items-center gap-3 md:gap-4">
          {/* 40 Lines badge */}
          <div className="hidden md:flex flex-col items-center bg-yellow-500 text-black rounded-md px-3 py-6 border-2 border-yellow-300 font-display font-black text-lg shadow-inner">
            <span className="text-2xl leading-none">40</span>
            <span className="text-xs uppercase tracking-wide">Lines</span>
          </div>

          {/* Reels */}
          <div className="flex-1 grid grid-cols-5 gap-1 md:gap-1.5 bg-[#0a0530] rounded-lg p-2 md:p-3 border-2 border-yellow-400 shadow-inner relative">
            {Array.from({ length: 5 }).map((_, reel) => (
              <div key={reel} className={`space-y-1 md:space-y-1.5 ${spinning ? "animate-pulse" : ""}`}>
                {Array.from({ length: ROWS }).map((_, row) => {
                  const sym = grid[reel]?.[row] || "cherry";
                  const s = SYMBOL_ART[sym];
                  const isWin = winRows.has(row) && !spinning;
                  const wildMult = !spinning && wildMults[`${reel},${row}`];
                  const isScatter = !spinning && sym === "scatter";
                  const isWild = !spinning && sym === "wild";
                  return (
                    <div
                      key={row}
                      data-testid={`slot-cell-${reel}-${row}`}
                      className={`relative aspect-square rounded-md flex items-center justify-center text-2xl md:text-3xl font-bold border-2 transition bg-gradient-to-br ${s.gradient} ${
                        isWild ? "border-yellow-300 shadow-lg shadow-fuchsia-500/60 ring-2 ring-fuchsia-300/70 animate-pulse" :
                        isScatter ? "border-pink-300 shadow-lg shadow-pink-500/60 ring-2 ring-pink-300/80 animate-bounce" :
                        isWin ? "border-yellow-300 shadow-lg shadow-yellow-500/60 scale-105 ring-2 ring-yellow-300/70" :
                        "border-black/50"
                      }`}
                    >
                      <span className={`drop-shadow-lg ${isWild ? "animate-spin-slow" : ""}`}>{s.emoji}</span>
                      {/* Wild multiplier badge */}
                      {isWild && wildMult > 1 && (
                        <span className="absolute -top-1 -right-1 bg-yellow-400 text-black text-[10px] font-black px-1 py-[1px] rounded shadow-lg" data-testid={`wild-mult-${reel}-${row}`}>
                          x{wildMult}
                        </span>
                      )}
                      {isWild && (
                        <span className="absolute bottom-0.5 left-0 right-0 text-[7px] text-center font-black tracking-widest text-yellow-200 drop-shadow">
                          WILD
                        </span>
                      )}
                      {isScatter && (
                        <span className="absolute bottom-0.5 left-0 right-0 text-[7px] text-center font-black tracking-widest text-yellow-200 drop-shadow">
                          FREE
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>

          {/* Right side — Spin button */}
          <div className="flex flex-col items-center gap-2">
            <button
              onClick={spin}
              disabled={spinning || (freeSpins === 0 && balance < bet)}
              data-testid="slot-spin-btn"
              className={`w-16 h-16 md:w-20 md:h-20 rounded-full font-display font-black uppercase tracking-wider transition
                ${freeSpins > 0 ? "bg-gradient-to-b from-fuchsia-400 to-pink-700 shadow-fuchsia-500/50" : "bg-gradient-to-b from-emerald-400 to-emerald-700 shadow-emerald-500/40"}
                text-black shadow-xl border-4 border-yellow-400 hover:scale-105 disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center`}
            >
              {spinning ? <Loader2 className="w-6 h-6 animate-spin" /> : <Play className="w-6 h-6 md:w-7 md:h-7 fill-black" />}
            </button>
            <div className="text-[9px] uppercase tracking-widest text-yellow-300 font-bold">
              {freeSpins > 0 ? `FREE ×${freeSpins}` : "Spin"}
            </div>
          </div>
        </div>

        {/* Please place your bet / status strip */}
        <div className="mt-3 md:mt-4 text-center text-yellow-300 font-display font-bold text-xs md:text-sm uppercase tracking-widest">
          {lastPayout > 0
            ? <span className="text-emerald-300">🎉 Last win: ${lastPayout.toFixed(2)}{scatterCount >= 3 ? " + FREE SPINS!" : ""}</span>
            : scatterCount === 2
              ? <span className="text-pink-300">So close — 1 more 🎁 for free spins!</span>
              : freeSpins > 0 ? <span className="text-fuchsia-300">Free spins active — no bet deducted</span>
              : "Please place your bet"}
        </div>
      </div>

      {/* Bottom bar — balance + bet chips */}
      <div className="bg-gradient-to-b from-[#2a0505] to-[#1a0303] p-2 md:p-3 border-t border-yellow-600/40 flex flex-wrap items-center gap-2 md:gap-3">
        <div className="px-3 py-1.5 rounded-md bg-black/40 border border-yellow-500/30">
          <div className="text-[8px] uppercase tracking-widest text-yellow-300/70">Balance</div>
          <div className="font-display font-black text-sm md:text-base text-emerald-300 font-mono">${balance.toFixed(2)}</div>
        </div>
        <div className="flex-1 flex items-center gap-1 md:gap-1.5 overflow-x-auto no-scrollbar">
          {BET_STEPS.map((v, i) => (
            <button
              key={v}
              onClick={() => setBetIdx(i)}
              disabled={spinning || freeSpins > 0}
              data-testid={`slot-bet-preset-${v}`}
              className={`shrink-0 flex flex-col items-center justify-center rounded-md px-2 py-1.5 md:px-2.5 md:py-2 border-2 transition ${
                betIdx === i
                  ? "bg-emerald-500 border-emerald-300 text-black shadow-lg shadow-emerald-500/40"
                  : "bg-black/30 border-yellow-500/30 text-yellow-100 hover:bg-black/50"
              } disabled:opacity-40`}
            >
              <span className={`text-[8px] font-bold uppercase tracking-widest ${betIdx === i ? "text-black/80" : "text-yellow-300/70"}`}>Bet</span>
              <span className="font-mono font-black text-sm md:text-base">${v.toFixed(2)}</span>
            </button>
          ))}
        </div>
        <details className="ml-auto shrink-0 relative" data-testid="slot-paytable">
          <summary className="cursor-pointer px-3 py-2 rounded-md bg-black/30 border border-yellow-500/30 text-yellow-200 text-[10px] uppercase tracking-widest hover:bg-black/50 list-none select-none">
            Paytable
          </summary>
          <div className="absolute right-0 bottom-full mb-2 w-72 bg-[#1a0303] border border-yellow-500/40 rounded-md p-3 shadow-2xl z-20">
            <div className="text-[10px] uppercase tracking-widest text-fuchsia-300 font-bold mb-1">Special symbols</div>
            <div className="text-[11px] text-yellow-100/80 mb-2">
              <span className="text-fuchsia-300">⭐ WILD</span> substitutes any symbol (except 🎁) and can carry a ×2 / ×3 / ×5 multiplier.
              <br />
              <span className="text-pink-300">🎁 SCATTER</span> — 3 anywhere = 5 free spins, 4 = 10, 5 = 15.
            </div>
            <div className="text-[10px] uppercase tracking-widest text-yellow-400/70 font-bold mb-1">Symbol payouts</div>
            {[
              ["seven", "7️⃣", [15, 60, 250]],
              ["melon", "🍉", [6, 18, 60]],
              ["grape", "🍇", [3, 8, 25]],
              ["plum", "🍇", [1.5, 4, 12]],
              ["orange", "🍊", [1, 2.5, 6]],
              ["lemon", "🍋", [0.6, 1.5, 4]],
              ["cherry", "🍒", [0.5, 1, 3]],
            ].map(([id, e, [a, b, c]]) => (
              <div key={id} className="flex items-center justify-between py-1 text-xs">
                <span className="text-lg">{e}</span>
                <div className="text-yellow-100/80 font-mono">
                  <span className="text-yellow-400/50">3×</span>{a}
                  <span className="text-yellow-400/50 ml-2">4×</span>{b}
                  <span className="text-yellow-400/50 ml-2">5×</span><span className="text-emerald-300 font-bold">{c}</span>
                </div>
              </div>
            ))}
          </div>
        </details>
      </div>
    </div>
  );
}

function JackpotBadge({ icon, label, amount, color, glow, big }) {
  return (
    <div className={`flex items-center gap-1 md:gap-2 px-2 py-1 rounded-md bg-gradient-to-b from-black/60 to-black/40 border ${glow ? "border-yellow-400" : "border-yellow-700/60"} ${glow ? "shadow-inner shadow-yellow-500/40" : ""}`}>
      <span className={`text-lg ${color}`}>{icon}</span>
      <div className="min-w-0">
        <div className={`text-[8px] uppercase tracking-widest ${glow ? "text-yellow-300" : "text-white/60"} font-bold`}>{label}</div>
        <div className={`font-display font-black ${big ? "text-sm md:text-base text-emerald-300" : "text-xs md:text-sm text-white"} font-mono leading-tight truncate`}>
          ${amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </div>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------------
// StairsGame — once-a-day 10-step ladder.
// -----------------------------------------------------------------------------

function StairsGame({ authedApi, reloadBalance }) {
  const [status, setStatus] = useState(null);
  const [game, setGame] = useState(null);
  const [ended, setEnded] = useState(null);
  const [stepping, setStepping] = useState(false);

  const loadStatus = async () => {
    try {
      const r = await authedApi().get("/games/stairs/status");
      setStatus(r.data);
      if (r.data.active_game) setGame(r.data.active_game);
    } catch { /* status refresh best-effort */ }
  };
  useEffect(() => { loadStatus(); }, []);

  const start = async () => {
    try {
      const r = await authedApi().post("/games/stairs/start");
      setGame({ id: r.data.game_id, step: r.data.step, path: r.data.path || [] });
      setEnded(null);
      reloadBalance?.();
    } catch (e) { toast.error(e.response?.data?.detail || "Failed to start"); }
  };

  const step = async (choice) => {
    if (!game || stepping) return;
    setStepping(true);
    try {
      const r = await authedApi().post("/games/stairs/step", { game_id: game.id, choice });
      const newPath = [...(game.path || []), { step: game.step, choice, bomb: r.data.bomb_side, hit: r.data.hit_bomb }];
      if (r.data.hit_bomb) {
        setGame({ ...game, path: newPath, step: game.step });
        setEnded({ result: "lost" });
        toast.error("💣 Boom! You lost the stake.");
      } else {
        setGame({ ...game, step: r.data.step, path: newPath });
        if (r.data.status === "won") {
          setEnded({ result: "won", payout: r.data.payout, mult: 40 });
          toast.success(`🎉 +$${r.data.payout?.toFixed(2)}`);
          reloadBalance?.();
        }
      }
      if (r.data.hit_bomb || r.data.status === "won") loadStatus();
    } catch (e) { toast.error(e.response?.data?.detail || "Step failed"); }
    finally { setStepping(false); }
  };

  const cashout = async () => {
    if (!game) return;
    try {
      const r = await authedApi().post("/games/stairs/cashout", { game_id: game.id });
      setEnded({ result: "won", payout: r.data.payout, mult: r.data.mult });
      toast.success(`💰 Cashed out $${r.data.payout.toFixed(2)}!`);
      reloadBalance?.();
      loadStatus();
    } catch (e) { toast.error(e.response?.data?.detail || "Cashout failed"); }
  };

  if (!status) return <div className="text-white/60 text-sm">Loading…</div>;
  if (!status.eligible) return (
    <div className="bg-[#0d0a14] border border-white/5 rounded-md p-8 text-center">
      <Bomb className="w-8 h-8 mx-auto text-white/30 mb-3" />
      <div className="text-white/80 font-bold">Locked</div>
      <div className="text-white/50 text-sm mt-1">Need $50 in lifetime deposits. You have ${(status.lifetime_deposits || 0).toFixed(2)}.</div>
    </div>
  );
  if (status.played_today && !game) return (
    <div className="bg-[#0d0a14] border border-white/5 rounded-md p-8 text-center">
      <RotateCcw className="w-8 h-8 mx-auto text-white/30 mb-3" />
      <div className="text-white/80 font-bold">Come back tomorrow!</div>
      <div className="text-white/50 text-sm mt-1">Free daily entry resets at midnight UTC.</div>
    </div>
  );

  const mults = status.multipliers || [];
  return (
    <div className="space-y-3">
      <div className="bg-[#0d0a14] border border-white/5 rounded-md p-4">
        <div className="flex items-center justify-between mb-3">
          <div><div className="text-[10px] uppercase tracking-widest text-white/50">Stake</div>
            <div className="font-display font-black text-xl text-emerald-300">${status.stake?.toFixed(2)}</div></div>
          <div className="text-right"><div className="text-[10px] uppercase tracking-widest text-white/50">Current</div>
            <div className="font-display font-black text-xl text-emerald-300">
              {game && game.step > 0 ? `${mults[game.step - 1]?.toFixed(1)}×` : `${mults[mults.length - 1]?.toFixed(0)}×`}
            </div></div>
        </div>
        <div className="space-y-1" data-testid="stairs-ladder">
          {mults.slice().reverse().map((m, idxRev) => {
            const idx = mults.length - 1 - idxRev;
            const isCurrent = game && idx === game.step;
            const isPast = game && idx < game.step;
            const h = (game?.path || []).find((p) => p.step === idx);
            return (
              <div key={idx} className={`flex items-center gap-2 rounded-md p-1.5 ${isCurrent ? "bg-emerald-500/15 border border-emerald-400" : "bg-black/30 border border-transparent"}`}>
                <div className={`w-10 text-center font-mono text-xs ${isPast ? "text-emerald-300" : "text-white/50"}`}>{m.toFixed(1)}×</div>
                <div className="flex-1 grid grid-cols-2 gap-1.5">
                  {[0, 1].map((c) => {
                    const revealed = isPast || (h && h.step === idx);
                    const wasBomb = revealed && h?.bomb === c;
                    const wasChoice = revealed && h?.choice === c;
                    return (
                      <button key={c} disabled={!isCurrent || stepping || ended} onClick={() => isCurrent && step(c)}
                        data-testid={`stairs-tile-${idx}-${c}`}
                        className={`h-8 rounded-md text-sm font-bold border transition ${
                          revealed
                            ? wasBomb ? "bg-red-500/25 border-red-500 text-red-100"
                              : wasChoice ? "bg-emerald-500/25 border-emerald-400 text-emerald-100"
                                : "bg-black/40 border-white/10 text-white/40"
                            : isCurrent ? "bg-emerald-500/10 border-emerald-500/40 hover:bg-emerald-500/25 text-white"
                              : "bg-black/30 border-white/5 text-white/30"
                        }`}>
                        {revealed ? (wasBomb ? "💣" : "✔") : "?"}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
        {ended?.result === "won" && <div className="mt-3 bg-emerald-500/15 border border-emerald-500/40 rounded-md p-3 text-center" data-testid="stairs-won">
          <div className="font-display font-black text-xl text-emerald-300">+ ${ended.payout?.toFixed(2)}</div>
        </div>}
        {ended?.result === "lost" && <div className="mt-3 bg-red-500/15 border border-red-500/40 rounded-md p-3 text-center" data-testid="stairs-lost">
          <div className="font-display font-black text-xl text-red-300">💣 Bust</div>
        </div>}
      </div>
      <div className="flex gap-2">
        {!game && <button onClick={start} data-testid="stairs-start-btn"
          className="flex-1 py-3 rounded-md font-display font-black text-base uppercase tracking-widest bg-emerald-500 text-black hover:bg-emerald-400 transition">Start — Stake $0.80</button>}
        {game && !ended && game.step > 0 && <button onClick={cashout} data-testid="stairs-cashout-btn"
          className="flex-1 py-3 rounded-md font-display font-black text-base uppercase tracking-widest bg-yellow-400 text-black hover:bg-yellow-300 transition">
          Cash out ${(status.stake * mults[game.step - 1]).toFixed(2)}</button>}
      </div>
    </div>
  );
}
