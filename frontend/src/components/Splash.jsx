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
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [minMs]);

  return (
    <div
      data-testid="splash"
      className={`fixed inset-0 z-[9999] flex flex-col items-center justify-center transition-opacity duration-500 ${
        hiding ? "opacity-0 pointer-events-none" : "opacity-100"
      }`}
      style={{
        background:
          "radial-gradient(ellipse at 30% 20%, #ff007f 0%, transparent 55%), radial-gradient(ellipse at 70% 80%, #7000ff 0%, transparent 55%), #0a0014",
      }}
    >
      <div className="relative w-48 h-48 md:w-56 md:h-56">
        <svg className="absolute inset-0 w-full h-full -rotate-90" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="46" fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="2.5" />
          <circle
            cx="50"
            cy="50"
            r="46"
            fill="none"
            stroke="url(#splashGrad)"
            strokeWidth="2.5"
            strokeLinecap="round"
            className="splash-spin"
            style={{ strokeDasharray: "72 289", transformOrigin: "50% 50%" }}
          />
          <defs>
            <linearGradient id="splashGrad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#ff007f" />
              <stop offset="50%" stopColor="#b388ff" />
              <stop offset="100%" stopColor="#00e5ff" />
            </linearGradient>
          </defs>
        </svg>
        <svg className="absolute inset-3 w-[calc(100%-24px)] h-[calc(100%-24px)]" viewBox="0 0 100 100">
          <circle
            cx="50"
            cy="50"
            r="46"
            fill="none"
            stroke="url(#splashGrad2)"
            strokeWidth="1.5"
            strokeLinecap="round"
            className="splash-spin-reverse"
            style={{ strokeDasharray: "40 289", transformOrigin: "50% 50%" }}
          />
          <defs>
            <linearGradient id="splashGrad2" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#00e5ff" />
              <stop offset="100%" stopColor="#ff007f" />
            </linearGradient>
          </defs>
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-center">
            <div className="font-display font-black text-4xl md:text-5xl glow-pink text-white">BS</div>
            <div className="text-[9px] md:text-[10px] uppercase tracking-[0.3em] text-white/70 mt-1">
              Better Social
            </div>
          </div>
        </div>
      </div>

      <h1 className="mt-10 font-display text-2xl md:text-3xl font-black tracking-tight text-white text-center px-4">
        <span className="gradient-text">Better-Social.pro</span>
      </h1>
      <p className="mt-2 text-xs md:text-sm text-white/50 uppercase tracking-[0.25em]">Loading your panel…</p>

      <style>{`
        @keyframes splash-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes splash-spin-reverse { from { transform: rotate(0deg); } to { transform: rotate(-360deg); } }
        .splash-spin { animation: splash-spin 1.4s linear infinite; }
        .splash-spin-reverse { animation: splash-spin-reverse 2s linear infinite; }
      `}</style>
    </div>
  );
}
