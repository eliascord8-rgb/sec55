import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Loader2, Coins, RotateCw, Trophy } from "lucide-react";

/**
 * Slot Machine — 8×6 grid of fruits. Bet $0.05 - $100.
 * 3+ same-icon in a row = payout. Backend generates the grid + evaluates.
 */
export default function SlotsView({ authedApi, balance, withdrawable, onBalanceChange }) {
  const [config, setConfig] = useState(null);
  const [bet, setBet] = useState(0.05);
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
    return Array.from({ length: config.rows }, () =>
      Array.from({ length: config.cols }, () => config.icons[0].id)
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
    // Animate spin with a brief cycling of random icons
    let ticks = 0;
    const cycle = setInterval(() => {
      const pool = config.icons.map((i) => i.id);
      const rand = Array.from({ length: config.rows }, () =>
        Array.from({ length: config.cols }, () => pool[Math.floor(Math.random() * pool.length)])
      );
      setGrid(rand);
      ticks++;
    }, 90);
    try {
      const r = await authedApi().post("/client/slots/spin", { bet: b });
      // Small delay so animation feels satisfying
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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight">Slot Machine</h1>
        <p className="text-white/50 text-sm mt-2">
          Match <span className="text-white font-bold">3+ same fruits in a row</span> to win. Winnings go to your withdrawable balance.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
        {/* Grid */}
        <div
          key={flashKey}
          className={`bg-[#0d0a14] border border-white/10 rounded-lg p-3 md:p-4 shadow-2xl ${lastResult?.payout > 0 ? "ring-2 ring-emerald-400/60" : ""}`}
          data-testid="slot-grid"
        >
          <div
            className="grid gap-1 md:gap-1.5"
            style={{ gridTemplateColumns: `repeat(${config.cols}, minmax(0, 1fr))` }}
          >
            {displayGrid.map((row, r) =>
              row.map((cell, c) => {
                const icon = iconById[cell] || config.icons[0];
                const win = isWinCell(r, c);
                return (
                  <div
                    key={`${r}-${c}`}
                    data-testid={`slot-cell-${r}-${c}`}
                    className={`aspect-square rounded-md flex items-center justify-center text-xl md:text-3xl transition-all ${
                      win
                        ? "bg-gradient-to-br from-amber-400/40 to-emerald-500/40 border border-emerald-400/60 shadow-lg shadow-emerald-500/30 scale-105 animate-pulse"
                        : spinning
                          ? "bg-[#1a1525] border border-white/5"
                          : "bg-[#1a1525] border border-white/5 hover:border-white/15"
                    }`}
                  >
                    {icon.emoji}
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Controls */}
        <div className="space-y-4">
          <div className="bg-[#0d0a14] border border-white/5 rounded-lg p-5">
            <div className="text-[10px] uppercase tracking-wider text-white/40 mb-1 font-bold">Wallet balance</div>
            <div className="text-2xl font-display font-black text-emerald-300 font-mono">${balance.toFixed(2)}</div>
            {withdrawable > 0 && (
              <div className="text-[11px] text-emerald-400/70 mt-1">
                +${withdrawable.toFixed(2)} winnings (withdrawable)
              </div>
            )}
          </div>

          <div className="bg-[#0d0a14] border border-white/5 rounded-lg p-5 space-y-3">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-white/40 font-bold mb-2">Bet Amount</div>
              <input
                type="number"
                min="0.05"
                max="100"
                step="0.05"
                value={bet}
                onChange={(e) => setBet(e.target.value)}
                disabled={spinning}
                data-testid="slot-bet-input"
                className="w-full bg-[#1a1525] border border-white/10 rounded-md px-3 py-2 text-lg font-mono text-white outline-none focus:border-emerald-400"
              />
              <div className="text-[10px] text-white/40 mt-1">$0.05 – $100</div>
            </div>
            <div className="grid grid-cols-4 gap-1">
              {[0.05, 0.5, 5, 25].map((v) => (
                <button
                  key={v}
                  onClick={() => setBet(v)}
                  disabled={spinning}
                  data-testid={`slot-quickbet-${v}`}
                  className="px-2 py-1.5 rounded-sm bg-[#1a1525] hover:bg-white/10 border border-white/10 text-[11px] font-mono text-white/80 disabled:opacity-40"
                >
                  ${v}
                </button>
              ))}
            </div>
            <button
              onClick={spin}
              disabled={spinning || Number(bet) < 0.05 || Number(bet) > balance}
              data-testid="slot-spin-btn"
              className="w-full py-3.5 rounded-md font-bold text-sm inline-flex items-center justify-center gap-2 disabled:opacity-40 bg-gradient-to-r from-amber-400 to-emerald-500 text-black hover:scale-[1.02] transition"
            >
              {spinning ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCw className="w-4 h-4" />}
              {spinning ? "Spinning…" : `Spin for $${Number(bet).toFixed(2)}`}
            </button>
          </div>

          {lastResult && (
            <div className={`rounded-lg p-4 border ${lastResult.payout > 0 ? "border-emerald-400/40 bg-emerald-500/5" : "border-white/5 bg-[#0d0a14]"}`}>
              <div className="flex items-center gap-2 text-xs text-white/60 mb-1">
                {lastResult.payout > 0 ? <Trophy className="w-3.5 h-3.5 text-amber-400" /> : <Coins className="w-3.5 h-3.5" />}
                Last spin
              </div>
              <div className="font-mono text-sm">
                Bet <span className="text-red-400">-${lastResult.bet.toFixed(2)}</span> · Won{" "}
                <span className={lastResult.payout > 0 ? "text-emerald-400 font-bold" : "text-white/40"}>+${lastResult.payout.toFixed(2)}</span>
              </div>
              <div className={`text-xs mt-1 ${lastResult.net > 0 ? "text-emerald-400" : "text-red-400"}`}>
                Net: {lastResult.net >= 0 ? "+" : ""}${lastResult.net.toFixed(2)}
              </div>
            </div>
          )}

          <div className="bg-[#0d0a14] border border-white/5 rounded-lg p-4 text-[11px] text-white/50 space-y-1">
            <div className="text-white/70 font-bold text-xs uppercase tracking-wider mb-1">Payouts (per row)</div>
            <div>3-in-a-row = 0.5×</div>
            <div>4-in-a-row = 1.5×</div>
            <div>5-in-a-row = 4× · 6 = 40×</div>
            <div className="text-amber-300 pt-1">💎 doubles winnings · 7️⃣ multiplies by 5</div>
          </div>
        </div>
      </div>
    </div>
  );
}
