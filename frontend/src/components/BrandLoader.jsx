// Full-screen green branded loader — rotating emerald ring with "BGS" mark.
// Drop in anywhere a spinner is needed for a big-moment load.
export default function BrandLoader({ label = "Loading", size = 96 }) {
  const ring = size;
  return (
    <div className="flex flex-col items-center justify-center gap-4" data-testid="brand-loader">
      <div className="relative" style={{ width: ring, height: ring }}>
        {/* Rotating ring */}
        <svg
          className="absolute inset-0 animate-spin"
          style={{ animationDuration: "1.4s" }}
          viewBox="0 0 100 100"
          width={ring}
          height={ring}
        >
          <defs>
            <linearGradient id="brand-ring-grad" x1="0" y1="0" x2="100" y2="100" gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="#10b981" />
              <stop offset="0.55" stopColor="#34d399" />
              <stop offset="1" stopColor="#065f46" stopOpacity="0.15" />
            </linearGradient>
          </defs>
          <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="8" />
          <circle
            cx="50" cy="50" r="42"
            fill="none"
            stroke="url(#brand-ring-grad)"
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray="70 200"
          />
        </svg>
        {/* Solid green center disc + BGS mark */}
        <div className="absolute inset-2 rounded-full bg-emerald-500 flex items-center justify-center shadow-lg shadow-emerald-500/40">
          <span
            className="font-black text-white tracking-wider"
            style={{ fontSize: Math.round(size * 0.28), fontFamily: "'Unbounded', system-ui, sans-serif" }}
          >
            BGS
          </span>
        </div>
      </div>
      {label && (
        <div className="text-[10px] uppercase tracking-widest text-emerald-300/80 font-bold">{label}</div>
      )}
    </div>
  );
}
