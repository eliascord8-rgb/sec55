import { createContext, useContext, useEffect, useState } from "react";

// Purely a DISPLAY layer — all backend amounts stay in USD. We fetch a live
// USD→EUR rate from Frankfurter (free, no key) once per session and cache it.
// If the fetch fails we fall back to a sane recent rate so the UI never breaks.
const CURRENCIES = {
  USD: { symbol: "$", label: "USD", flag: "🇺🇸" },
  EUR: { symbol: "€", label: "EUR", flag: "🇪🇺" },
};

const CurrencyContext = createContext({
  currency: "USD",
  setCurrency: () => {},
  format: (n) => `$${Number(n || 0).toFixed(2)}`,
  symbol: "$",
  rate: 1,
});

export function CurrencyProvider({ children }) {
  const [currency, setCurrencyState] = useState(() => {
    try {
      const s = localStorage.getItem("bs_currency");
      return s === "EUR" ? "EUR" : "USD";
    } catch { return "USD"; }
  });
  const [usdToEur, setUsdToEur] = useState(0.92);

  // Fetch live rate on mount; cheap and gracefully degrades.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await fetch("https://api.frankfurter.dev/latest?base=USD&symbols=EUR");
        if (!r.ok) return;
        const j = await r.json();
        const v = j?.rates?.EUR;
        if (alive && typeof v === "number" && v > 0) setUsdToEur(v);
      } catch { /* keep default */ }
    })();
    return () => { alive = false; };
  }, []);

  const setCurrency = (c) => {
    const next = c === "EUR" ? "EUR" : "USD";
    setCurrencyState(next);
    try { localStorage.setItem("bs_currency", next); } catch { /* private mode */ }
  };

  const rate = currency === "EUR" ? usdToEur : 1;
  const symbol = CURRENCIES[currency].symbol;
  const format = (usdAmount) => {
    const n = Number(usdAmount || 0) * rate;
    return `${symbol}${n.toFixed(2)}`;
  };

  return (
    <CurrencyContext.Provider value={{ currency, setCurrency, format, symbol, rate }}>
      {children}
    </CurrencyContext.Provider>
  );
}

export function useCurrency() {
  return useContext(CurrencyContext);
}

export function CurrencyPicker({ compact = false }) {
  const { currency, setCurrency } = useCurrency();
  const [open, setOpen] = useState(false);
  const cur = CURRENCIES[currency];
  return (
    <div className="relative" data-testid="currency-picker">
      <button
        onClick={() => setOpen((v) => !v)}
        data-testid="currency-picker-btn"
        title="Change display currency"
        className={`inline-flex items-center gap-1.5 rounded-md text-[11px] font-bold uppercase tracking-wider transition ${compact ? "px-2 py-1.5 hover:bg-emerald-500/15 text-emerald-200" : "px-3 py-2 border border-emerald-500/30 text-emerald-200 hover:bg-emerald-500/15"}`}
      >
        <span className="text-base leading-none">{cur.flag}</span>
        <span className="hidden sm:inline">{cur.label}</span>
        <span className="text-[9px] opacity-60">▾</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 w-40 bg-[#0d2b12] border border-emerald-500/30 rounded-md shadow-2xl z-50 py-1" data-testid="currency-menu">
            {Object.entries(CURRENCIES).map(([code, meta]) => (
              <button
                key={code}
                onClick={() => { setCurrency(code); setOpen(false); }}
                data-testid={`currency-opt-${code}`}
                className={`w-full flex items-center gap-2 px-3 py-2 text-sm transition ${currency === code ? "bg-emerald-500/15 text-emerald-200" : "text-white hover:bg-emerald-500/10"}`}
              >
                <span className="text-base">{meta.flag}</span>
                <span className="flex-1 text-left font-medium">{meta.label}</span>
                {currency === code && <span className="text-emerald-400 text-xs">✓</span>}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
