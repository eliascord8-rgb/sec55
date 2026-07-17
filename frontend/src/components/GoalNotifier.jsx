import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";

// Lightweight global watcher — polls the sports goal feed every 15s and shows
// a big pulsing toast + plays a short cheer sound whenever a new event is
// detected. Uses localStorage to remember the last-seen timestamp so
// refreshes don't replay old alerts.
const POLL_MS = 15000;
const LS_KEY = "bs_sports_last_seen";

function playGoalSound() {
  try {
    // Web Audio API — 3-note ascending "goal" chime, no external file needed
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    const ctx = new AC();
    const notes = [523.25, 659.25, 783.99]; // C5, E5, G5
    let t = ctx.currentTime;
    notes.forEach((f, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = f;
      osc.type = "sine";
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.18, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.4);
      t += 0.18;
    });
  } catch { /* ignore — audio is nice-to-have */ }
}

const LABELS = {
  goal: { emoji: "⚽", text: "GOAL!", tone: "success" },
  goal_disallowed: { emoji: "🚫", text: "Goal disallowed", tone: "info" },
  penalty: { emoji: "🎯", text: "PENALTY!", tone: "success" },
  kickoff: { emoji: "🟢", text: "Kick-off", tone: "info" },
  halftime: { emoji: "⏸", text: "Half-time", tone: "info" },
  fulltime: { emoji: "🏁", text: "Full-time", tone: "info" },
};

export default function GoalNotifier() {
  const sinceRef = useRef(localStorage.getItem(LS_KEY) || new Date(Date.now() - 60000).toISOString());
  const [muted, setMuted] = useState(() => localStorage.getItem("bs_sports_muted") === "1");

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      if (!alive) return;
      try {
        const r = await api.get(`/sports/events?since=${encodeURIComponent(sinceRef.current)}&limit=20`);
        const events = r.data.events || [];
        for (const ev of events) {
          const meta = LABELS[ev.type] || LABELS.goal;
          const line1 = `${meta.emoji} ${meta.text} — ${ev.team || "?"} vs ${ev.opponent || "?"}`;
          const line2 = `${ev.score || ""}${ev.minute && ev.minute !== "—" ? " · " + ev.minute : ""}${ev.reason ? " (" + ev.reason + ")" : ""}`;
          if (meta.tone === "success") {
            toast.success(line1, { description: line2, duration: 6000 });
            if (!muted) playGoalSound();
          } else {
            toast(line1, { description: line2, duration: 4500 });
          }
          if (ev.created_at) sinceRef.current = ev.created_at;
        }
        if (events.length) {
          try { localStorage.setItem(LS_KEY, sinceRef.current); } catch { /* private mode */ }
        }
      } catch { /* backend restart / network — silent retry */ }
    };
    tick();
    const int = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(int); };
  }, [muted]);

  // Small floating mute-toggle so users can silence the sound if they hate it
  return (
    <button
      onClick={() => {
        const next = !muted;
        setMuted(next);
        try { localStorage.setItem("bs_sports_muted", next ? "1" : "0"); } catch { /* ignore */ }
      }}
      data-testid="goal-sound-toggle"
      title={muted ? "Goal alerts muted — click to unmute" : "Mute goal alerts"}
      className="fixed bottom-4 left-4 z-30 w-10 h-10 rounded-full bg-black/60 hover:bg-black/80 backdrop-blur border border-emerald-500/30 text-emerald-300 flex items-center justify-center transition"
    >
      {muted ? "🔕" : "🔔"}
    </button>
  );
}
