import { useEffect, useState } from "react";
import { api } from "@/lib/api";

// Colour hash — same username always gets the same avatar hue.
const COLORS = ["#10b981", "#f59e0b", "#ec4899", "#3b82f6", "#8b5cf6", "#ef4444", "#06b6d4", "#84cc16"];
function colorFor(name) {
  let h = 0;
  for (const c of String(name || "?")) h = (h * 31 + c.charCodeAt(0)) & 0xffffffff;
  return COLORS[Math.abs(h) % COLORS.length];
}

/**
 * Stacked circular avatars showing team members currently on-shift.
 * Rollbit-style: 3-4 avatars overlapping, small pulsing green online dot.
 * Poll every 30s to keep in sync when a staff toggles their shift.
 */
export default function TeamAvatarStack({ size = 40, max = 4, className = "" }) {
  const [team, setTeam] = useState([]);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await api.get("/team/online");
        if (alive) setTeam(r.data.team || []);
      } catch { /* ignore transient errors */ }
    };
    tick();
    const int = setInterval(tick, 30000);
    return () => { alive = false; clearInterval(int); };
  }, []);

  const visible = team.slice(0, max);
  const isReal = visible.some((t) => t.role !== "system");

  return (
    <div className={`inline-flex items-center ${className}`} data-testid="team-avatar-stack">
      {visible.map((m, i) => {
        const label = (m.display_name || m.username || "?").trim();
        const initials = label
          .replace(/[^\p{L}\p{N} ]/gu, "")
          .split(/\s+/)
          .slice(0, 2)
          .map((w) => w[0] || "")
          .join("")
          .toUpperCase() || "?";
        const bg = colorFor(m.username || label);
        return (
          <div
            key={m.username || i}
            title={label + (m.role ? ` · ${m.role}` : "")}
            style={{ width: size, height: size, background: bg, marginLeft: i === 0 ? 0 : -Math.round(size * 0.35) }}
            className="relative rounded-full border-2 border-[#0d0a14] flex items-center justify-center font-bold text-white shadow-md"
            data-testid={`team-avatar-${m.username || i}`}
          >
            <span style={{ fontSize: Math.round(size * 0.36) }}>{initials}</span>
            {isReal && i === 0 && (
              <span
                className="absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full bg-emerald-400 border-2 border-[#0d0a14] animate-pulse"
              />
            )}
          </div>
        );
      })}
      {team.length > max && (
        <div
          style={{ width: size, height: size, marginLeft: -Math.round(size * 0.35) }}
          className="rounded-full border-2 border-[#0d0a14] bg-white/10 backdrop-blur flex items-center justify-center text-white/80 font-bold text-xs"
        >
          +{team.length - max}
        </div>
      )}
    </div>
  );
}
