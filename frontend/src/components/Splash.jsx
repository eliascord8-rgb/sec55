import { useEffect, useState, useRef } from "react";

export default function Splash({ onDone, minMs = 4000 }) {
  const [hiding, setHiding] = useState(false);
  const firedRef = useRef(false);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    const t1 = setTimeout(() => setHiding(true), Math.max(0, minMs - 500));
    const t2 = setTimeout(() => {
      if (firedRef.current) return;
      firedRef.current = true;
      onDoneRef.current?.();
    }, minMs);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [minMs]);

  return (
    <div
      data-testid="splash"
      className={`fixed inset-0 z-[9999] flex flex-col items-center justify-center transition-opacity duration-500 ${
        hiding ? "opacity-0 pointer-events-none" : "opacity-100"
      }`}
      style={{
        background:
          "radial-gradient(ellipse at 30% 20%, rgba(16,185,129,0.35) 0%, transparent 55%), radial-gradient(ellipse at 70% 80%, rgba(52,211,153,0.20) 0%, transparent 55%), #050505",
      }}
    >
      {/* Emerald ring + BGS pill — same design language as the in-app BrandLoader */}
      <div className="relative w-40 h-40 md:w-48 md:h-48">
        <div className="absolute rounded-full bg-emerald-500/25 blur-3xl" style={{ inset: -16 }} />
        <svg
          className="relative animate-spin"
          style={{ animationDuration: "1.4s" }}
          viewBox="0 0 100 100"
          width="100%"
          height="100%"
        >
          <defs>
            <linearGradient id="bs-splash-grad" x1="0" y1="0" x2="100" y2="100" gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="#34d399" />
              <stop offset="0.55" stopColor="#10b981" />
              <stop offset="1" stopColor="#10b981" stopOpacity="0.05" />
            </linearGradient>
          </defs>
          <circle cx="50" cy="50" r="44" fill="none" stroke="rgba(52,211,153,0.10)" strokeWidth="4" />
          <circle
            cx="50" cy="50" r="44"
            fill="none"
            stroke="url(#bs-splash-grad)"
            strokeWidth="4"
            strokeLinecap="round"
            strokeDasharray="100 250"
            transform="rotate(-90 50 50)"
          />
        </svg>
        <div
          className="absolute rounded-full bg-emerald-500 flex items-center justify-center shadow-2xl shadow-emerald-500/50 ring-4 ring-[#050505]"
          style={{
            top: "50%", left: "50%",
            width: "58%", height: "58%",
            transform: "translate(-50%, -50%)",
          }}
        >
          <span
            className="font-black text-white tracking-tight leading-none"
            style={{ fontSize: 34, fontFamily: "'Unbounded','Outfit',system-ui,sans-serif" }}
          >
            BGS
          </span>
        </div>
      </div>

      <h1 className="mt-10 font-display text-2xl md:text-3xl font-black tracking-tight text-white text-center px-4">
        Better<span className="text-emerald-400">Social</span>.pro
      </h1>
      <p className="mt-2 text-[10px] md:text-xs text-emerald-300/80 uppercase tracking-[0.3em] font-bold flex items-center gap-2">
        <span className="w-1 h-1 rounded-full bg-emerald-400 animate-pulse" />
        Loading your panel
      </p>
    </div>
  );
}

