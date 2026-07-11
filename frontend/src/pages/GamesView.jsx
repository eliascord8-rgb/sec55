import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2, Cherry, Star, Bomb, Sparkles, RotateCcw } from "lucide-react";

// -----------------------------------------------------------------------------
// GamesView — top-level component wired into ClientDashboard's "games" view.
// Contains two tabs: Slots (Wild-Hot-style 5×6 grid) and Stairs (daily game).
// -----------------------------------------------------------------------------

const SYMBOL_ART = {
  cherry: { emoji: "🍒", color: "#ff3355" },
  lemon:  { emoji: "🍋", color: "#fbd800" },
  orange: { emoji: "🍊", color: "#ff9500" },
  plum:   { emoji: "🍇", color: "#a855f7" },
  grape:  { emoji: "🍉", color: "#22c55e" },
  melon:  { emoji: "🍉", color: "#dc2626" },
  seven:  { emoji: "7️⃣", color: "#facc15" },
};

export default function GamesView({ authedApi, balance, reloadBalance }) {
  const [tab, setTab] = useState("slots");
  return (
    <div className="max-w-6xl space-y-6" data-testid="games-view">
      <div>
        <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight flex items-center gap-2">
          <Sparkles className="w-7 h-7 text-emerald-400" /> Games
        </h1>
        <p className="text-white/50 text-sm mt-2">Try your luck — slots pay any 3-in-a-row from left, stairs is a once-a-day risk-and-reward run. All winnings go to your withdrawable balance.</p>
      </div>
      <div className="flex gap-2">
        <button data-testid="games-tab-slots" onClick={() => setTab("slots")}
          className={`px-4 py-2 rounded-md text-xs font-bold uppercase tracking-wider transition ${tab === "slots" ? "bg-emerald-500 text-black" : "bg-[#0d0a14] text-white/70 hover:text-white border border-white/10"}`}>
          🎰 Slots
        </button>
        <button data-testid="games-tab-stairs" onClick={() => setTab("stairs")}
          className={`px-4 py-2 rounded-md text-xs font-bold uppercase tracking-wider transition ${tab === "stairs" ? "bg-emerald-500 text-black" : "bg-[#0d0a14] text-white/70 hover:text-white border border-white/10"}`}>
          🪜 Stairs
        </button>
      </div>
      {tab === "slots" && <SlotsGame authedApi={authedApi} balance={balance} reloadBalance={reloadBalance} />}
      {tab === "stairs" && <StairsGame authedApi={authedApi} reloadBalance={reloadBalance} />}
    </div>
  );
}

// -----------------------------------------------------------------------------
// Slots — 5 reels × 6 rows.
// -----------------------------------------------------------------------------

function SlotsGame({ authedApi, balance, reloadBalance }) {
  const [bet, setBet] = useState(0.20);
  const [spinning, setSpinning] = useState(false);
  const [grid, setGrid] = useState(() =>
    Array.from({ length: 5 }, () => Array.from({ length: 6 }, () => "cherry"))
  );
  const [wins, setWins] = useState([]);
  const [lastPayout, setLastPayout] = useState(0);

  const spin = async () => {
    if (spinning) return;
    if (bet < 0.20 || bet > 5) { toast.error("Bet must be $0.20–$5.00"); return; }
    if (balance < bet) { toast.error("Not enough balance."); return; }
    setSpinning(true);
    setWins([]);
    setLastPayout(0);
    // Animate a quick shuffle before showing the real grid
    const anim = setInterval(() => {
      setGrid(Array.from({ length: 5 }, () =>
        Array.from({ length: 6 }, () => {
          const keys = Object.keys(SYMBOL_ART);
          return keys[Math.floor(Math.random() * keys.length)];
        })
      ));
    }, 90);
    try {
      const r = await authedApi().post("/games/slot/spin", { bet });
      setTimeout(() => {
        clearInterval(anim);
        setGrid(r.data.grid);
        setWins(r.data.wins || []);
        setLastPayout(r.data.payout);
        if (r.data.payout > 0) {
          toast.success(`🎉 You won $${r.data.payout.toFixed(2)}!`);
        }
        reloadBalance?.();
        setSpinning(false);
      }, 900);
    } catch (e) {
      clearInterval(anim);
      setSpinning(false);
      toast.error(e.response?.data?.detail || "Spin failed");
    }
  };

  const winRows = new Set(wins.map((w) => w.row));

  return (
    <div className="space-y-4">
      <div className="bg-[#0d0a14] border border-white/5 rounded-md p-4 md:p-6">
        {/* Grid: 5 reels × 6 rows */}
        <div className="grid grid-cols-5 gap-1.5 md:gap-2" data-testid="slot-grid">
          {Array.from({ length: 5 }).map((_, reel) => (
            <div key={reel} className="space-y-1.5 md:space-y-2">
              {Array.from({ length: 6 }).map((_, row) => {
                const sym = grid[reel]?.[row] || "cherry";
                const s = SYMBOL_ART[sym];
                const isWin = winRows.has(row) && !spinning;
                return (
                  <div
                    key={row}
                    data-testid={`slot-cell-${reel}-${row}`}
                    className={`aspect-square rounded-md flex items-center justify-center text-2xl md:text-3xl font-bold border transition ${
                      isWin
                        ? "bg-emerald-500/20 border-emerald-400 shadow-lg shadow-emerald-500/40 animate-pulse"
                        : "bg-black/40 border-white/5"
                    }`}
                    style={isWin ? { color: s.color } : { color: s.color }}
                  >
                    {s.emoji}
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {/* Result strip */}
        {lastPayout > 0 && (
          <div className="mt-4 bg-emerald-500/15 border border-emerald-500/40 rounded-md p-3 text-center" data-testid="slot-win-banner">
            <div className="font-display font-black text-2xl text-emerald-300">+ ${lastPayout.toFixed(2)}</div>
            <div className="text-[11px] uppercase tracking-widest text-emerald-200/80">Nice win!</div>
          </div>
        )}
      </div>

      {/* Controls */}
      <div className="bg-[#0d0a14] border border-white/5 rounded-md p-4 md:p-5 flex flex-wrap items-center gap-3 md:gap-4">
        <div className="flex-1 min-w-[220px]">
          <label className="text-[10px] uppercase tracking-widest text-white/50">Bet</label>
          <div className="flex items-center gap-2 mt-1">
            <button
              onClick={() => setBet((b) => Math.max(0.20, Math.round((b - 0.20) * 100) / 100))}
              className="w-9 h-9 rounded-md bg-white/5 hover:bg-white/10 text-white font-bold" data-testid="slot-bet-down"
              disabled={spinning}
            >−</button>
            <div className="flex-1 text-center bg-black/40 border border-emerald-500/30 rounded-md py-2 font-mono font-bold text-emerald-300" data-testid="slot-bet-value">
              ${bet.toFixed(2)}
            </div>
            <button
              onClick={() => setBet((b) => Math.min(5, Math.round((b + 0.20) * 100) / 100))}
              className="w-9 h-9 rounded-md bg-white/5 hover:bg-white/10 text-white font-bold" data-testid="slot-bet-up"
              disabled={spinning}
            >+</button>
          </div>
          <div className="flex gap-1 mt-2">
            {[0.20, 0.50, 1.00, 2.00, 5.00].map((v) => (
              <button key={v} onClick={() => setBet(v)} disabled={spinning}
                data-testid={`slot-bet-preset-${v}`}
                className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-sm ${bet === v ? "bg-emerald-500 text-black" : "bg-white/5 text-white/60 hover:bg-white/10"}`}>
                ${v.toFixed(2)}
              </button>
            ))}
          </div>
        </div>
        <button
          onClick={spin}
          disabled={spinning || balance < bet}
          data-testid="slot-spin-btn"
          className="ml-auto px-8 py-4 rounded-md font-display font-black text-lg uppercase tracking-widest bg-emerald-500 text-black hover:bg-emerald-400 disabled:opacity-40 disabled:cursor-not-allowed transition shadow-lg shadow-emerald-500/30"
        >
          {spinning ? <Loader2 className="w-5 h-5 animate-spin" /> : "SPIN"}
        </button>
      </div>

      {/* Paytable */}
      <details className="bg-[#0d0a14] border border-white/5 rounded-md" data-testid="slot-paytable">
        <summary className="cursor-pointer px-4 py-3 text-xs uppercase tracking-widest text-white/60 hover:text-white select-none">
          Paytable — payouts per line (bet × multiplier)
        </summary>
        <div className="px-4 pb-4 grid grid-cols-2 md:grid-cols-3 gap-2 text-xs">
          {[
            ["seven", "7️⃣", [10, 40, 200]],
            ["melon", "🍉", [5, 15, 50]],
            ["grape", "🍇", [2, 6, 20]],
            ["plum", "🍇", [1, 3, 10]],
            ["orange", "🍊", [0.5, 1.5, 5]],
            ["lemon", "🍋", [0.3, 0.8, 3]],
            ["cherry", "🍒", [0.2, 0.5, 2]],
          ].map(([id, e, [a, b, c]]) => (
            <div key={id} className="flex items-center justify-between bg-black/30 rounded px-3 py-1.5">
              <span className="text-lg">{e}</span>
              <div className="text-white/70 text-[11px]">
                <span className="text-white/40">3×</span> {a}× <span className="text-white/40 ml-2">4×</span> {b}× <span className="text-white/40 ml-2">5×</span> <span className="text-emerald-300 font-bold">{c}×</span>
              </div>
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}

// -----------------------------------------------------------------------------
// Stairs — once-a-day 10-step ladder.
// -----------------------------------------------------------------------------

function StairsGame({ authedApi, reloadBalance }) {
  const [status, setStatus] = useState(null);
  const [game, setGame] = useState(null);
  const [ended, setEnded] = useState(null); // { result: "won"|"lost", payout, mult }
  const [stepping, setStepping] = useState(false);

  const loadStatus = async () => {
    try {
      const r = await authedApi().get("/games/stairs/status");
      setStatus(r.data);
      if (r.data.active_game) setGame(r.data.active_game);
    } catch { /* stale status is fine */ }
  };

  useEffect(() => { loadStatus(); }, []);

  const start = async () => {
    try {
      const r = await authedApi().post("/games/stairs/start");
      setGame({ id: r.data.game_id, step: r.data.step, path: r.data.path || [] });
      setEnded(null);
      reloadBalance?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to start");
    }
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
          toast.success(`🎉 You reached the top! +$${r.data.payout?.toFixed(2)}`);
          reloadBalance?.();
        }
      }
      // refresh status when game ends
      if (r.data.hit_bomb || r.data.status === "won") loadStatus();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Step failed");
    } finally {
      setStepping(false);
    }
  };

  const cashout = async () => {
    if (!game) return;
    try {
      const r = await authedApi().post("/games/stairs/cashout", { game_id: game.id });
      setEnded({ result: "won", payout: r.data.payout, mult: r.data.mult });
      toast.success(`💰 Cashed out $${r.data.payout.toFixed(2)}!`);
      reloadBalance?.();
      loadStatus();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Cashout failed");
    }
  };

  if (!status) return <div className="text-white/60 text-sm">Loading…</div>;

  if (!status.eligible) {
    return (
      <div className="bg-[#0d0a14] border border-white/5 rounded-md p-8 text-center">
        <Bomb className="w-8 h-8 mx-auto text-white/30 mb-3" />
        <div className="text-white/80 font-bold">Locked</div>
        <div className="text-white/50 text-sm mt-1">
          You need at least <span className="text-emerald-300 font-bold">$50</span> in lifetime deposits to unlock the Stairs Game.
          You have <span className="text-white/70">${(status.lifetime_deposits || 0).toFixed(2)}</span> so far.
        </div>
      </div>
    );
  }

  if (status.played_today && !game) {
    return (
      <div className="bg-[#0d0a14] border border-white/5 rounded-md p-8 text-center">
        <RotateCcw className="w-8 h-8 mx-auto text-white/30 mb-3" />
        <div className="text-white/80 font-bold">Come back tomorrow!</div>
        <div className="text-white/50 text-sm mt-1">You already played today. Free daily entry resets at midnight UTC.</div>
      </div>
    );
  }

  const mults = status.multipliers || [];

  return (
    <div className="space-y-4">
      <div className="bg-[#0d0a14] border border-white/5 rounded-md p-6">
        {/* Header row with current progress */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-white/50">Stake</div>
            <div className="font-display font-black text-2xl text-emerald-300">${status.stake?.toFixed(2)}</div>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-widest text-white/50">
              {game ? "Current multiplier" : "Max multiplier"}
            </div>
            <div className="font-display font-black text-2xl text-emerald-300" data-testid="stairs-current-mult">
              {game && game.step > 0 ? `${mults[game.step - 1]?.toFixed(1)}×` : `${mults[mults.length - 1]?.toFixed(0)}×`}
            </div>
          </div>
        </div>

        {/* Ladder */}
        <div className="space-y-1.5" data-testid="stairs-ladder">
          {mults.slice().reverse().map((m, idxRev) => {
            const idx = mults.length - 1 - idxRev;
            const isCurrent = game && idx === game.step;
            const isPast = game && idx < game.step;
            const historyForStep = (game?.path || []).find((p) => p.step === idx);
            return (
              <div key={idx} className={`flex items-center gap-2 rounded-md p-2 ${isCurrent ? "bg-emerald-500/15 border border-emerald-400 shadow-lg shadow-emerald-500/20" : "bg-black/30 border border-transparent"}`}>
                <div className={`w-12 text-center font-mono text-xs ${isPast ? "text-emerald-300" : "text-white/50"}`}>
                  {m.toFixed(1)}×
                </div>
                <div className="flex-1 grid grid-cols-2 gap-2">
                  {[0, 1].map((c) => {
                    const revealed = isPast || (historyForStep && historyForStep.step === idx);
                    const wasBomb = revealed && historyForStep?.bomb === c;
                    const wasChoice = revealed && historyForStep?.choice === c;
                    return (
                      <button
                        key={c}
                        disabled={!isCurrent || stepping || ended}
                        onClick={() => isCurrent && step(c)}
                        data-testid={`stairs-tile-${idx}-${c}`}
                        className={`h-10 rounded-md text-lg font-bold border transition ${
                          revealed
                            ? wasBomb
                              ? "bg-red-500/25 border-red-500 text-red-100"
                              : wasChoice
                                ? "bg-emerald-500/25 border-emerald-400 text-emerald-100"
                                : "bg-black/40 border-white/10 text-white/40"
                            : isCurrent
                              ? "bg-emerald-500/10 border-emerald-500/40 hover:bg-emerald-500/25 text-white"
                              : "bg-black/30 border-white/5 text-white/30"
                        }`}
                      >
                        {revealed ? (wasBomb ? "💣" : "✔") : "?"}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        {/* End states */}
        {ended?.result === "won" && (
          <div className="mt-4 bg-emerald-500/15 border border-emerald-500/40 rounded-md p-4 text-center" data-testid="stairs-won">
            <div className="font-display font-black text-2xl text-emerald-300">+ ${ended.payout?.toFixed(2)}</div>
            <div className="text-[11px] uppercase tracking-widest text-emerald-200/80">Cashed out — see you tomorrow!</div>
          </div>
        )}
        {ended?.result === "lost" && (
          <div className="mt-4 bg-red-500/15 border border-red-500/40 rounded-md p-4 text-center" data-testid="stairs-lost">
            <div className="font-display font-black text-2xl text-red-300">💣 Bust</div>
            <div className="text-[11px] uppercase tracking-widest text-red-200/80">You hit a bomb — try again tomorrow.</div>
          </div>
        )}
      </div>

      {/* Controls */}
      <div className="flex gap-2">
        {!game && (
          <button onClick={start} data-testid="stairs-start-btn"
            className="flex-1 py-4 rounded-md font-display font-black text-lg uppercase tracking-widest bg-emerald-500 text-black hover:bg-emerald-400 transition shadow-lg shadow-emerald-500/30">
            Start — Stake $0.80
          </button>
        )}
        {game && !ended && game.step > 0 && (
          <button onClick={cashout} data-testid="stairs-cashout-btn"
            className="flex-1 py-4 rounded-md font-display font-black text-lg uppercase tracking-widest bg-yellow-400 text-black hover:bg-yellow-300 transition shadow-lg shadow-yellow-500/30">
            Cash out ${(status.stake * mults[game.step - 1]).toFixed(2)}
          </button>
        )}
        {ended && (
          <div className="flex-1 text-center text-white/50 text-sm py-4">
            Daily game complete — come back tomorrow.
          </div>
        )}
      </div>
    </div>
  );
}
