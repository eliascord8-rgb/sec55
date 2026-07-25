// Full-screen green branded loader — clean pulsing ring with "BGS" logo pill.
// Redesigned to match the dashboard's green theme without visual clipping.
export default function BrandLoader({ label = "Loading", size = 88 }) {
  const ring = size;
  return (
    <div
      className="flex flex-col items-center justify-center gap-4 py-6"
      data-testid="brand-loader"
    >
      <div className="relative" style={{ width: ring, height: ring }}>
        {/* Soft glow behind the ring */}
        <div
          className="absolute rounded-full bg-emerald-500/20 blur-xl"
          style={{ inset: -8 }}
        />
        {/* Rotating ring — full stroke visible, no inner disc covering it */}
        <svg
          className="relative animate-spin"
          style={{ animationDuration: "1.2s" }}
          viewBox="0 0 100 100"
          width={ring}
          height={ring}
        >
          <defs>
            <linearGradient id="bs-loader-grad" x1="0" y1="0" x2="100" y2="100" gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="#34d399" />
              <stop offset="0.5" stopColor="#10b981" />
              <stop offset="1" stopColor="#10b981" stopOpacity="0.05" />
            </linearGradient>
          </defs>
          {/* Faint track */}
          <circle
            cx="50" cy="50" r="42"
            fill="none"
            stroke="rgba(52,211,153,0.10)"
            strokeWidth="6"
          />
          {/* Rotating arc */}
          <circle
            cx="50" cy="50" r="42"
            fill="none"
            stroke="url(#bs-loader-grad)"
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray="90 220"
            transform="rotate(-90 50 50)"
          />
        </svg>
        {/* Centered logo pill — sized to sit INSIDE the ring, never covering it */}
        <div
          className="absolute rounded-full bg-emerald-500 flex items-center justify-center shadow-lg shadow-emerald-500/40 ring-2 ring-[#050505]"
          style={{
            top: "50%",
            left: "50%",
            width: ring * 0.55,
            height: ring * 0.55,
            transform: "translate(-50%, -50%)",
          }}
        >
          <span
            className="font-black text-white tracking-tight leading-none"
            style={{
              fontSize: Math.round(size * 0.22),
              fontFamily: "'Unbounded','Outfit',system-ui,sans-serif",
            }}
          >
            BGS
          </span>
        </div>
      </div>
      {label && (
        <div className="text-[10px] uppercase tracking-widest text-emerald-300/80 font-bold flex items-center gap-1.5">
          <span className="w-1 h-1 rounded-full bg-emerald-400 animate-pulse" />
          {label}
        </div>
      )}
    </div>
  );
}
