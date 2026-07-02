import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Loader2, Coins, RotateCw, Trophy, Sparkles as SparklesIcon } from "lucide-react";

/**
 * Slot Machine — 4×6 grid with wilds. Bet $0.05 – $100.
 * 3+ same-icon horizontal = payout. ⭐ Wild substitutes for any icon and doubles the run's win.
 */
export default function SlotsView({ authedApi, balance, withdrawable, onBalanceChange }) {
  const [config, setConfig] = useState(null);
  const [bet, setBet] = useState(0.5);
  const [spinning, setSpinning] = useState(false);
  const [grid, setGrid] = useState(null);
  const [winCells, setWinCells] = useState([]);
  const [lastResult, setLastResult] = useState(null);
  const [flashKey, setFlashKey] = useState(0);

  useEffect(() => {
    (async () => {
      try {
        const r = await authedApi().get("/client/slots/config");
        setConfig(r.data);
      } catch {
        toast.error("Slot machine unavailable");
      }
    })();
  }, [authedApi]);

  const iconById = useMemo(() => {
    if (!config) return {};
    return Object.fromEntries(config.icons.map((i) => [i.id, i]));
  }, [config]);

  const emptyGrid = useMemo(() => {
    if (!config) return null;
    // Random initial preview so it doesn't look empty
    const pool = config.icons.map((i) => i.id);
    return Array.from({ length: config.rows }, () =>
      Array.from({ length: config.cols }, () => pool[Math.floor(Math.random() * pool.length)])
    );
  }, [config]);

  const displayGrid = grid || emptyGrid;

  const spin = async () => {
    const b = Number(bet);
    if (!b || b < 0.05 || b > 100) {
      toast.error("Bet must be $0.05 – $100");
      return;
    }
    if (b > balance) {
      toast.error("Not enough balance");
      return;
    }
    setSpinning(true);
    setWinCells([]);
    setLastResult(null);
    const pool = config.icons.map((i) => i.id);
    const cycle = setInterval(() => {
      const rand = Array.from({ length: config.rows }, () =>
        Array.from({ length: config.cols }, () => pool[Math.floor(Math.random() * pool.length)])
      );
      setGrid(rand);
    }, 70);
    try {
      const r = await authedApi().post("/client/slots/spin", { bet: b });
      setTimeout(() => {
        clearInterval(cycle);
        setGrid(r.data.grid);
        setWinCells(r.data.winning_cells || []);
        setLastResult(r.data);
        setFlashKey((k) => k + 1);
        setSpinning(false);
        onBalanceChange && onBalanceChange();
        if (r.data.payout > 0) {
          toast.success(`🎉 You won $${r.data.payout.toFixed(2)}!`);
        }
      }, 900);
    } catch (e) {
      clearInterval(cycle);
      setSpinning(false);
      toast.error(e.response?.data?.detail || "Spin failed");
    }
  };

  if (!config) {
    return (
      <div className="flex items-center justify-center py-16 text-white/40">
        <Loader2 className="w-4 h-4 animate-spin mr-2" /> Loading…
      </div>
    );
  }

  const isWinCell = (r, c) => winCells.some(([rr, cc]) => rr === r && cc === c);
  const totalWon = lastResult?.payout || 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight flex items-center gap-3">
            🎰 <span>Try a Chance</span>
          </h1>
          <p className="text-white/50 text-sm mt-2">
            Match <span className="text-amber-300 font-bold">3+ same fruits</span> in any row.{" "}
            <span className="text-purple-300 font-bold">⭐ Wild</span> substitutes for any icon and doubles the payout.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
        {/* Machine cabinet */}
        <div
          key={flashKey}
          data-testid="slot-grid"
          className={`relative overflow-hidden rounded-2xl p-1 shadow-[0_10px_60px_-15px_rgba(0,0,0,0.9)] transition ${
            totalWon > 0 ? "ring-4 ring-amber-400/50 shadow-amber-500/40" : ""
          }`}
          style={{
            background:
              "linear-gradient(135deg, #7c2d12 0%, #b45309 25%, #d97706 50%, #b45309 75%, #7c2d12 100%)",
          }}
        >
          {/* Marquee light strip */}
          <div className="flex items-center justify-between px-4 py-2 mb-1">
            <div className="flex gap-1">
              {[0, 1, 2, 3, 4].map((i) => (
                <span
                  key={i}
                  className={`w-2 h-2 rounded-full bg-amber-300 ${spinning ? "animate-pulse" : "opacity-70"}`}
                  style={{ animationDelay: `${i * 100}ms`, boxShadow: "0 0 8px rgba(252, 211, 77, 0.8)" }}
                />
              ))}
            </div>
            <div className="text-[10px] uppercase tracking-[0.3em] font-black text-amber-100 drop-shadow">
              🎰 BETTER SOCIAL SLOTS 🎰
            </div>
            <div className="flex gap-1">
              {[0, 1, 2, 3, 4].map((i) => (
                <span
                  key={i}
                  className={`w-2 h-2 rounded-full bg-amber-300 ${spinning ? "animate-pulse" : "opacity-70"}`}
                  style={{ animationDelay: `${i * 100 + 250}ms`, boxShadow: "0 0 8px rgba(252, 211, 77, 0.8)" }}
                />
              ))}
            </div>
          </div>

          {/* Screen */}
          <div
            className="rounded-xl p-3 md:p-4"
            style={{
              background: "linear-gradient(180deg, #0a0510 0%, #1a0f24 100%)",
              boxShadow: "inset 0 4px 20px rgba(0, 0, 0, 0.9), inset 0 -2px 10px rgba(217, 119, 6, 0.2)",
            }}
          >
            {/* Reels */}
            <div
              className="grid gap-2 md:gap-3"
              style={{ gridTemplateColumns: `repeat(${config.cols}, minmax(0, 1fr))` }}
            >
              {displayGrid.map((row, r) =>
                row.map((cell, c) => {
                  const icon = iconById[cell] || config.icons[0];
                  const win = isWinCell(r, c);
                  const isWild = cell === "wild";
                  return (
                    <div
                      key={`${r}-${c}`}
                      data-testid={`slot-cell-${r}-${c}`}
                      className={`relative aspect-square rounded-lg flex items-center justify-center text-3xl md:text-5xl transition-all duration-200 ${
                        win
                          ? "bg-gradient-to-br from-amber-300 to-emerald-400 scale-105 shadow-[0_0_25px_rgba(251,191,36,0.7)] ring-2 ring-amber-200"
                          : isWild
                            ? "bg-gradient-to-br from-purple-500/30 to-pink-500/30 border border-purple-400/50 shadow-inner"
                            : spinning
                              ? "bg-[#251020] border border-amber-500/10 blur-[0.5px]"
                              : "bg-[#1a0f24] border border-amber-500/10 hover:border-amber-400/30"
                      }`}
                      style={
                        !win && !isWild
                          ? {
                              boxShadow: "inset 0 2px 8px rgba(0,0,0,0.5), inset 0 -1px 4px rgba(217,119,6,0.1)",
                            }
                          : {}
                      }
                    >
                      <span className={spinning ? "animate-bounce" : ""}>{icon.emoji}</span>
                      {win && (
                        <SparklesIcon className="absolute top-1 right-1 w-3 h-3 text-white animate-pulse" />
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Bottom "coin tray" */}
          <div className="flex items-center justify-between px-4 py-2 mt-1">
            <div className="text-[10px] uppercase tracking-widest text-amber-100/70 font-bold">
              Row-match to win →
            </div>
            <div className="text-[10px] font-mono text-amber-100/60">
              {config.rows}×{config.cols}
            </div>
          </div>

          {/* Big-win overlay */}
          {totalWon > 0 && !spinning && (
            <div className="absolute inset-x-0 top-14 flex items-center justify-center pointer-events-none animate-in fade-in zoom-in duration-500">
              <div className="bg-gradient-to-r from-amber-400 to-yellow-300 text-black font-black text-3xl md:text-5xl px-6 py-2 rounded-full shadow-2xl">
                +${totalWon.toFixed(2)}
              </div>
            </div>
          )}
        </div>

        {/* Controls */}
        <div className="space-y-4">
          {/* Balance card */}
          <div
            className="rounded-xl p-5 text-white shadow-xl"
            style={{
              background:
                "linear-gradient(135deg, #10b981 0%, #059669 50%, #047857 100%)",
            }}
            data-testid="slot-balance-card"
          >
            <div className="text-[10px] uppercase tracking-wider text-emerald-50/80 mb-1 font-bold">Wallet</div>
            <div className="text-3xl font-display font-black font-mono">${balance.toFixed(2)}</div>
            {withdrawable > 0 && (
              <div className="text-[11px] text-emerald-100/80 mt-1 flex items-center gap-1">
                <Trophy className="w-3 h-3" />+${withdrawable.toFixed(2)} winnings
              </div>
            )}
          </div>

          {/* Bet controls */}
          <div className="bg-[#0d0a14] border border-white/5 rounded-xl p-5 space-y-3">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-white/40 font-bold mb-2">Bet Amount</div>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40 font-mono">$</span>
                <input
                  type="number"
                  min="0.05"
                  max="100"
                  step="0.05"
                  value={bet}
                  onChange={(e) => setBet(e.target.value)}
                  disabled={spinning}
                  data-testid="slot-bet-input"
                  className="w-full bg-[#1a1525] border border-white/10 rounded-md pl-7 pr-3 py-3 text-lg font-mono text-white outline-none focus:border-amber-400 text-right"
                />
              </div>
              <div className="text-[10px] text-white/40 mt-1">Min $0.05 · Max $100</div>
            </div>
            <div className="grid grid-cols-4 gap-1">
              {[0.05, 0.5, 5, 25].map((v) => (
                <button
                  key={v}
                  onClick={() => setBet(v)}
                  disabled={spinning}
                  data-testid={`slot-quickbet-${v}`}
                  className={`px-2 py-1.5 rounded-sm border text-[11px] font-mono disabled:opacity-40 transition ${
                    Number(bet) === v
                      ? "bg-amber-500/20 border-amber-400 text-amber-200"
                      : "bg-[#1a1525] border-white/10 text-white/70 hover:bg-white/10"
                  }`}
                >
                  ${v}
                </button>
              ))}
            </div>
            <button
              onClick={spin}
              disabled={spinning || Number(bet) < 0.05 || Number(bet) > balance}
              data-testid="slot-spin-btn"
              className="w-full py-4 rounded-lg font-black text-base uppercase tracking-wider inline-flex items-center justify-center gap-2 disabled:opacity-40 shadow-lg transition text-black"
              style={{
                background: spinning
                  ? "linear-gradient(90deg, #ca8a04, #a16207)"
                  : "linear-gradient(90deg, #fbbf24, #f59e0b, #d97706)",
              }}
            >
              {spinning ? <Loader2 className="w-5 h-5 animate-spin" /> : <RotateCw className="w-5 h-5" />}
              {spinning ? "Spinning…" : `SPIN · $${Number(bet).toFixed(2)}`}
            </button>
          </div>

          {/* Last spin result */}
          {lastResult && !spinning && (
            <div
              className={`rounded-xl p-4 border ${
                lastResult.payout > 0
                  ? "border-amber-400/40 bg-gradient-to-br from-amber-500/10 to-emerald-500/5"
                  : "border-white/5 bg-[#0d0a14]"
              }`}
            >
              <div className="flex items-center gap-2 text-xs text-white/60 mb-2">
                {lastResult.payout > 0 ? <Trophy className="w-3.5 h-3.5 text-amber-400" /> : <Coins className="w-3.5 h-3.5" />}
                Last spin
              </div>
              <div className="flex items-baseline gap-3 font-mono text-sm">
                <div>
                  <span className="text-white/40">Bet</span>{" "}
                  <span className="text-red-400">-${lastResult.bet.toFixed(2)}</span>
                </div>
                <div>
                  <span className="text-white/40">Won</span>{" "}
                  <span className={lastResult.payout > 0 ? "text-emerald-400 font-bold" : "text-white/40"}>
                    +${lastResult.payout.toFixed(2)}
                  </span>
                </div>
              </div>
              <div className={`text-xs mt-2 font-mono ${lastResult.net > 0 ? "text-emerald-400" : "text-red-400"}`}>
                Net: {lastResult.net >= 0 ? "+" : ""}${lastResult.net.toFixed(2)}
              </div>
            </div>
          )}

          {/* Payout table */}
          <div className="bg-[#0d0a14] border border-white/5 rounded-xl p-4 text-[11px] text-white/60">
            <div className="text-white/80 font-bold text-xs uppercase tracking-wider mb-2">Payouts (per row)</div>
            <div className="grid grid-cols-2 gap-y-1">
              <span>3-match</span><span className="text-right font-mono text-white/80">0.5×</span>
              <span>4-match</span><span className="text-right font-mono text-white/80">1.5×</span>
              <span>5-match</span><span className="text-right font-mono text-emerald-400">4×</span>
              <span>6-match</span><span className="text-right font-mono text-amber-300 font-bold">40×</span>
            </div>
            <div className="mt-3 pt-3 border-t border-white/5 space-y-1">
              <div className="flex items-center gap-2 text-purple-300">
                <span className="text-lg">⭐</span> <span>Wild — subs any icon · ×2 bonus</span>
              </div>
              <div className="flex items-center gap-2 text-cyan-300">
                <span className="text-lg">💎</span> <span>Diamond — ×2 payout</span>
              </div>
              <div className="flex items-center gap-2 text-amber-300">
                <span className="text-lg">7️⃣</span> <span>Seven — ×5 payout (jackpot)</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
