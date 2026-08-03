// Lightweight synthesized alert sounds (Web Audio API — no audio files needed).
let ctx;
function getCtx() {
  if (typeof window === "undefined") return null;
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
  }
  if (ctx.state === "suspended") ctx.resume().catch(() => {});
  return ctx;
}

function tone(freq, start, duration, gainPeak = 0.18, type = "sine") {
  const audio = getCtx();
  if (!audio) return;
  const osc = audio.createOscillator();
  const gain = audio.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(0, audio.currentTime + start);
  gain.gain.linearRampToValueAtTime(gainPeak, audio.currentTime + start + 0.015);
  gain.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + start + duration);
  osc.connect(gain);
  gain.connect(audio.destination);
  osc.start(audio.currentTime + start);
  osc.stop(audio.currentTime + start + duration + 0.02);
}

export function playSuccessSound() {
  tone(660, 0, 0.12);
  tone(880, 0.1, 0.18);
}

export function playErrorSound() {
  tone(220, 0, 0.16, 0.2, "square");
  tone(160, 0.12, 0.22, 0.2, "square");
}

export function playWarningSound() {
  tone(440, 0, 0.14, 0.16, "triangle");
}
