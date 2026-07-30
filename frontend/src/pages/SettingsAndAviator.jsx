import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2, Rocket, Zap, Palette, KeyRound, Mail, Save, User, Camera, Link as LinkIcon, Trash2, Coins } from "lucide-react";
import { CurrencyPicker } from "@/context/CurrencyContext";
import { LanguagePicker } from "@/context/LanguageContext";

// -----------------------------------------------------------------------------
// AviatorGame — daily crash game. Custom bet, cashout any time before the plane
// crashes.  Server pre-rolls crash mult; frontend just animates 1× → ∞.
// -----------------------------------------------------------------------------

const AVIATOR_GROWTH_K = 0.35; // must match backend AVIATOR_GROWTH_K

export function AviatorGame({ authedApi, balance, reloadBalance }) {
  const [status, setStatus] = useState(null);
  const [game, setGame] = useState(null);
  const [bet, setBet] = useState(1.0);
  const [starting, setStarting] = useState(false);
  const [mult, setMult] = useState(1.0);
  const [ended, setEnded] = useState(null);
  const rafRef = useRef(null);
  const startEpochRef = useRef(0);

  const loadStatus = async () => {
    try {
      const r = await authedApi().get("/games/aviator/status");
      setStatus(r.data);
      if (r.data.active_game) {
        setGame(r.data.active_game);
        startEpochRef.current = new Date(r.data.active_game.start_time).getTime() / 1000;
      }
    } catch { /* ignore */ }
  };
  useEffect(() => { loadStatus(); }, []);

  // Animate multiplier while game is active
  useEffect(() => {
    if (!game || ended) return;
    const tick = () => {
      const now = Date.now() / 1000;
      const el = Math.max(0, now - startEpochRef.current);
      const m = Math.min(100, Math.exp(AVIATOR_GROWTH_K * el));
      setMult(m);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [game, ended]);

  const start = async () => {
    if (bet < 0.20 || bet > 100) { toast.error("Bet must be $0.20 – $100"); return; }
    if (balance < bet) { toast.error("Not enough balance"); return; }
    setStarting(true);
    setEnded(null);
    setMult(1.0);
    try {
      const r = await authedApi().post("/games/aviator/start", { bet });
      setGame({ id: r.data.game_id, bet: r.data.bet, start_time: r.data.start_time });
      startEpochRef.current = new Date(r.data.start_time).getTime() / 1000;
      reloadBalance?.();
    } catch (e) { toast.error(e.response?.data?.detail || "Start failed"); }
    finally { setStarting(false); }
  };

  const cashout = async () => {
    if (!game) return;
    try {
      const r = await authedApi().post("/games/aviator/cashout", { game_id: game.id });
      if (r.data.result === "cashed") {
        setEnded({ result: "cashed", payout: r.data.payout, mult: r.data.mult });
        toast.success(`💰 Cashed out ${r.data.mult.toFixed(2)}× — $${r.data.payout.toFixed(2)}`);
      } else {
        setEnded({ result: "crashed", mult: r.data.crash_mult });
        toast.error(`✈️ Crashed at ${r.data.crash_mult.toFixed(2)}× — better luck tomorrow`);
      }
      reloadBalance?.();
      loadStatus();
    } catch (e) { toast.error(e.response?.data?.detail || "Cashout failed"); }
  };

  if (!status) return <div className="text-white/60 text-sm">Loading…</div>;
  if (status.played_today && !game) return (
    <div className="bg-[#0d0a14] border border-white/5 rounded-md p-8 text-center">
      <Rocket className="w-8 h-8 mx-auto text-white/30 mb-3" />
      <div className="text-white/80 font-bold">Come back tomorrow!</div>
      <div className="text-white/50 text-sm mt-1">Aviator is once per day — free entry resets at midnight UTC.</div>
    </div>
  );

  const isActive = game && !ended;
  return (
    <div className="space-y-3">
      <div className="relative overflow-hidden rounded-lg border border-white/5 bg-gradient-to-b from-[#050b1a] via-[#0a1128] to-[#050b1a] p-6 md:p-8 text-center" data-testid="aviator-canvas">
        {/* Plane emoji floats up as multiplier grows */}
        <div className="absolute inset-0 pointer-events-none opacity-40" style={{
          background: "radial-gradient(circle at 50% 60%, rgba(59,130,246,0.15), transparent 60%)"
        }} />
        <div className="relative">
          <div className="text-[10px] uppercase tracking-widest text-white/50 mb-1">Multiplier</div>
          <div className={`font-display font-black text-6xl md:text-7xl transition ${
            ended?.result === "crashed" ? "text-red-400" :
            ended?.result === "cashed" ? "text-emerald-300" :
            isActive ? "text-emerald-300" : "text-white/80"
          }`} data-testid="aviator-mult">
            {isActive ? mult.toFixed(2) : (ended ? ended.mult.toFixed(2) : "1.00")}×
          </div>
          <div className="text-3xl md:text-4xl mt-4 transition-transform" style={{
            transform: isActive ? `translateY(-${Math.min(60, mult * 4)}px) rotate(-${Math.min(20, mult * 1.2)}deg)` : "none",
            filter: ended?.result === "crashed" ? "grayscale(1)" : "none",
          }}>
            {ended?.result === "crashed" ? "💥" : "✈️"}
          </div>
          <div className="mt-4 text-xs text-white/60">
            {isActive ? "Cash out anytime — plane crashes without warning!" :
              ended?.result === "cashed" ? `You won $${ended.payout.toFixed(2)}` :
              ended?.result === "crashed" ? "The plane flew away" :
              "Set your bet and take off!"}
          </div>
        </div>
      </div>

      {/* Controls */}
      {!isActive && !ended && (
        <div className="bg-[#0d0a14] border border-white/5 rounded-md p-4 flex flex-wrap items-center gap-3">
          <div className="flex-1 min-w-[220px]">
            <label className="text-[10px] uppercase tracking-widest text-white/50">Bet ($0.20 – $100)</label>
            <input type="number" step="0.10" min="0.20" max="100" value={bet}
              onChange={(e) => setBet(Math.max(0.20, Math.min(100, Number(e.target.value) || 0)))}
              data-testid="aviator-bet-input"
              className="mt-1 w-full bg-black/40 border border-emerald-500/25 rounded-md px-3 py-2.5 text-lg font-mono text-white focus:outline-none focus:border-emerald-400"
            />
            <div className="flex gap-1 mt-2">
              {[0.50, 1.00, 2.00, 5.00, 10.00].map((v) => (
                <button key={v} onClick={() => setBet(v)}
                  data-testid={`aviator-bet-preset-${v}`}
                  className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-sm ${bet === v ? "bg-emerald-500 text-black" : "bg-white/5 text-white/60 hover:bg-white/10"}`}>
                  ${v.toFixed(2)}
                </button>
              ))}
            </div>
          </div>
          <button onClick={start} disabled={starting || balance < bet}
            data-testid="aviator-start-btn"
            className="px-6 py-4 rounded-md font-display font-black text-lg uppercase tracking-widest bg-emerald-500 text-black hover:bg-emerald-400 disabled:opacity-40 transition inline-flex items-center gap-2">
            {starting ? <Loader2 className="w-5 h-5 animate-spin" /> : <><Zap className="w-5 h-5" /> Take off</>}
          </button>
        </div>
      )}
      {isActive && (
        <button onClick={cashout} data-testid="aviator-cashout-btn"
          className="w-full py-4 rounded-md font-display font-black text-xl uppercase tracking-widest bg-yellow-400 text-black hover:bg-yellow-300 transition shadow-lg shadow-yellow-500/30">
          Cash out ${(game.bet * mult).toFixed(2)} @ {mult.toFixed(2)}×
        </button>
      )}
      {ended && (
        <div className={`p-3 rounded-md text-center font-bold ${
          ended.result === "cashed" ? "bg-emerald-500/15 border border-emerald-500/40 text-emerald-300"
          : "bg-red-500/15 border border-red-500/40 text-red-300"
        }`} data-testid="aviator-result">
          Come back tomorrow for another flight.
        </div>
      )}
    </div>
  );
}

// -----------------------------------------------------------------------------
// SettingsView — profile settings: change password, change email, theme picker.
// -----------------------------------------------------------------------------

const THEMES = [
  { id: "green",  label: "Emerald (default)", color: "#10b981" },
  { id: "blue",   label: "Ocean Blue",        color: "#2563eb" },
  { id: "red",    label: "Ruby Red",          color: "#dc2626" },
  { id: "purple", label: "Royal Purple",      color: "#7c3aed" },
];

export function SettingsView({ authedApi, user }) {
  const [tab, setTab] = useState("account");
  return (
    <div className="max-w-3xl space-y-6" data-testid="settings-view">
      <div>
        <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight flex items-center gap-2">
          <User className="w-7 h-7 text-emerald-400" /> Settings
        </h1>
        <p className="text-white/50 text-sm mt-2">Manage your account and preferences.</p>
      </div>
      <div className="flex gap-2 flex-wrap">
        {[["account", "Account", KeyRound], ["preferences", "Preferences", Coins], ["appearance", "Appearance", Palette]].map(([id, label, Icon]) => (
          <button key={id} onClick={() => setTab(id)} data-testid={`settings-tab-${id}`}
            className={`px-4 py-2 rounded-md text-xs font-bold uppercase tracking-wider inline-flex items-center gap-2 transition ${tab === id ? "bg-emerald-500 text-black" : "bg-[#0d0a14] text-white/70 hover:text-white border border-white/10"}`}>
            <Icon className="w-3.5 h-3.5" /> {label}
          </button>
        ))}
      </div>
      {tab === "account" && <AccountSettings authedApi={authedApi} user={user} />}
      {tab === "preferences" && <PreferencesSettings />}
      {tab === "appearance" && <AppearanceSettings authedApi={authedApi} />}
    </div>
  );
}


function PreferencesSettings() {
  return (
    <div className="space-y-4">
      <div className="bg-[#0d0a14] border border-white/5 rounded-md p-5" data-testid="settings-currency">
        <div className="flex items-center gap-2 mb-3">
          <Coins className="w-4 h-4 text-emerald-400" />
          <div className="font-display font-bold text-sm">Display currency</div>
        </div>
        <p className="text-xs text-white/50 mb-4">
          All balances, order prices and stats are shown in this currency. Payments still process in USD — this is a display-only conversion.
        </p>
        <CurrencyPicker compact={false} />
      </div>

      <div className="bg-[#0d0a14] border border-white/5 rounded-md p-5" data-testid="settings-language">
        <div className="flex items-center gap-2 mb-3">
          <Palette className="w-4 h-4 text-emerald-400" />
          <div className="font-display font-bold text-sm">Language</div>
        </div>
        <p className="text-xs text-white/50 mb-4">
          Choose your preferred interface language.
        </p>
        <LanguagePicker compact={false} />
      </div>
    </div>
  );
}

function AvatarSettings({ authedApi, user }) {
  const inputRef = useRef(null);
  const [avatarUrl, setAvatarUrl] = useState(user?.avatar_url || "");
  const [urlInput, setUrlInput] = useState("");
  const [uploading, setUploading] = useState(false);
  const [savingUrl, setSavingUrl] = useState(false);

  // Build absolute URL for relative /api paths so <img> can render it
  const backend = process.env.REACT_APP_BACKEND_URL || "";
  const displayUrl = avatarUrl
    ? (avatarUrl.startsWith("http") ? avatarUrl : `${backend}${avatarUrl}`)
    : "";

  const pickFile = () => inputRef.current?.click();

  const onFileChange = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (f.size > 4 * 1024 * 1024) { toast.error("Image is too big (max 4 MB)"); return; }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await authedApi().post("/auth/me/avatar", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setAvatarUrl(r.data.avatar_url);
      toast.success("Profile picture updated!");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const saveUrl = async () => {
    const v = urlInput.trim();
    if (!/^https?:\/\//i.test(v)) { toast.error("URL must start with http:// or https://"); return; }
    setSavingUrl(true);
    try {
      const r = await authedApi().patch("/auth/me/avatar-url", { avatar_url: v });
      setAvatarUrl(r.data.avatar_url);
      setUrlInput("");
      toast.success("Profile picture updated from URL!");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to set URL");
    } finally {
      setSavingUrl(false);
    }
  };

  const clearAvatar = async () => {
    try {
      await authedApi().delete("/auth/me/avatar");
      setAvatarUrl("");
      toast.success("Profile picture removed.");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to remove");
    }
  };

  return (
    <div className="bg-[#0d0a14] border border-white/5 rounded-md p-5" data-testid="settings-avatar">
      <div className="flex items-center gap-2 mb-4">
        <Camera className="w-4 h-4 text-emerald-400" />
        <div className="font-display font-bold text-sm">Profile picture</div>
      </div>

      <div className="flex flex-col sm:flex-row items-start gap-5">
        {/* Preview */}
        <div className="relative shrink-0">
          <div className="w-24 h-24 rounded-full overflow-hidden border-2 border-emerald-500/40 bg-emerald-500/20 flex items-center justify-center shadow-lg shadow-emerald-900/30">
            {displayUrl ? (
              <img
                src={displayUrl}
                alt="avatar"
                data-testid="settings-avatar-preview-img"
                className="w-full h-full object-cover"
                onError={() => setAvatarUrl("")}
              />
            ) : (
              <span className="font-display font-black text-2xl text-emerald-200" data-testid="settings-avatar-initials">
                {(user?.username || "?").slice(0, 2).toUpperCase()}
              </span>
            )}
          </div>
          {uploading && (
            <div className="absolute inset-0 rounded-full bg-black/60 flex items-center justify-center">
              <Loader2 className="w-6 h-6 animate-spin text-white" />
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex-1 w-full space-y-3">
          <input
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif"
            onChange={onFileChange}
            data-testid="settings-avatar-file-input"
            className="hidden"
          />
          <div className="flex flex-wrap gap-2">
            <button
              onClick={pickFile}
              disabled={uploading}
              data-testid="settings-avatar-upload-btn"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-xs font-bold uppercase tracking-wider bg-emerald-500 text-black hover:bg-emerald-400 disabled:opacity-50 transition"
            >
              <Camera className="w-3.5 h-3.5" /> Upload image
            </button>
            {avatarUrl && (
              <button
                onClick={clearAvatar}
                data-testid="settings-avatar-clear-btn"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-xs font-bold uppercase tracking-wider border border-white/15 text-white/70 hover:text-white hover:border-white/30 transition"
              >
                <Trash2 className="w-3.5 h-3.5" /> Remove
              </button>
            )}
          </div>
          <div className="text-[11px] text-white/50">JPG, PNG, WEBP or GIF · Max 4 MB</div>

          <div className="pt-3 border-t border-white/5">
            <label className="text-[10px] uppercase tracking-widest text-white/50">Or paste an image URL</label>
            <div className="mt-1 flex gap-2">
              <input
                type="url"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                placeholder="https://i.imgur.com/example.png"
                data-testid="settings-avatar-url-input"
                className="flex-1 bg-black/40 border border-white/10 rounded-md px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-400"
              />
              <button
                onClick={saveUrl}
                disabled={savingUrl || !urlInput.trim()}
                data-testid="settings-avatar-url-save"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-xs font-bold uppercase tracking-wider border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/15 disabled:opacity-50 transition"
              >
                {savingUrl ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <LinkIcon className="w-3.5 h-3.5" />}
                Set URL
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function AccountSettings({ authedApi, user }) {
  const [email, setEmail] = useState(user?.email || "");
  const [emailPw, setEmailPw] = useState("");
  const [savingEmail, setSavingEmail] = useState(false);
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [savingPw, setSavingPw] = useState(false);

  const saveEmail = async () => {
    if (!/@/.test(email)) { toast.error("Enter a valid email"); return; }
    if (!emailPw) { toast.error("Password is required to change email"); return; }
    setSavingEmail(true);
    try {
      await authedApi().post("/client/change-email", { email, current_password: emailPw });
      toast.success("Email updated.");
      setEmailPw("");
    } catch (e) { toast.error(e.response?.data?.detail || "Failed"); }
    finally { setSavingEmail(false); }
  };

  const savePw = async () => {
    if (newPw.length < 8) { toast.error("New password must be 8+ chars"); return; }
    if (newPw !== confirmPw) { toast.error("Passwords don't match"); return; }
    setSavingPw(true);
    try {
      await authedApi().post("/client/change-password", { current_password: currentPw, new_password: newPw });
      toast.success("Password updated — sign in again next time.");
      setCurrentPw(""); setNewPw(""); setConfirmPw("");
    } catch (e) { toast.error(e.response?.data?.detail || "Failed"); }
    finally { setSavingPw(false); }
  };

  return (
    <div className="space-y-4">
      <AvatarSettings authedApi={authedApi} user={user} />

      <div className="bg-[#0d0a14] border border-white/5 rounded-md p-5" data-testid="settings-email">
        <div className="flex items-center gap-2 mb-3">
          <Mail className="w-4 h-4 text-emerald-400" />
          <div className="font-display font-bold text-sm">Email</div>
        </div>
        <label className="text-[10px] uppercase tracking-widest text-white/50">New email</label>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} data-testid="settings-email-input"
          className="mt-1 w-full bg-black/40 border border-white/10 rounded-md px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-400" />
        <label className="mt-3 block text-[10px] uppercase tracking-widest text-white/50">Confirm with current password</label>
        <input type="password" value={emailPw} onChange={(e) => setEmailPw(e.target.value)} data-testid="settings-email-pw"
          className="mt-1 w-full bg-black/40 border border-white/10 rounded-md px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-400" />
        <button onClick={saveEmail} disabled={savingEmail} data-testid="settings-email-save"
          className="mt-3 px-4 py-2 rounded-md text-xs font-bold uppercase tracking-wider bg-emerald-500 text-black hover:bg-emerald-400 disabled:opacity-50 inline-flex items-center gap-2">
          {savingEmail ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />} Save email
        </button>
      </div>

      <div className="bg-[#0d0a14] border border-white/5 rounded-md p-5" data-testid="settings-password">
        <div className="flex items-center gap-2 mb-3">
          <KeyRound className="w-4 h-4 text-emerald-400" />
          <div className="font-display font-bold text-sm">Password</div>
        </div>
        <label className="text-[10px] uppercase tracking-widest text-white/50">Current password</label>
        <input type="password" value={currentPw} onChange={(e) => setCurrentPw(e.target.value)} data-testid="settings-current-pw"
          className="mt-1 w-full bg-black/40 border border-white/10 rounded-md px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-400" />
        <label className="mt-3 block text-[10px] uppercase tracking-widest text-white/50">New password (8+ characters)</label>
        <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} data-testid="settings-new-pw"
          className="mt-1 w-full bg-black/40 border border-white/10 rounded-md px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-400" />
        <label className="mt-3 block text-[10px] uppercase tracking-widest text-white/50">Confirm new password</label>
        <input type="password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} data-testid="settings-confirm-pw"
          className="mt-1 w-full bg-black/40 border border-white/10 rounded-md px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-400" />
        <button onClick={savePw} disabled={savingPw} data-testid="settings-pw-save"
          className="mt-3 px-4 py-2 rounded-md text-xs font-bold uppercase tracking-wider bg-emerald-500 text-black hover:bg-emerald-400 disabled:opacity-50 inline-flex items-center gap-2">
          {savingPw ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />} Change password
        </button>
      </div>
    </div>
  );
}

function AppearanceSettings({ authedApi }) {
  const [current, setCurrent] = useState(localStorage.getItem("bs_theme") || "green");

  const apply = (id) => {
    // Body class toggle — instant preview across the whole dashboard.
    ["green", "blue", "red", "purple"].forEach((t) => {
      document.body.classList.remove(`theme-${t}-body`);
    });
    document.body.classList.add(`theme-${id}-body`);
    // Also update the theme-green scope class on <main> if present; simplest way:
    const shells = document.querySelectorAll(".theme-green, .theme-blue, .theme-red, .theme-purple");
    shells.forEach((el) => {
      el.classList.remove("theme-green", "theme-blue", "theme-red", "theme-purple");
      el.classList.add(`theme-${id}`);
    });
    localStorage.setItem("bs_theme", id);
    setCurrent(id);
    authedApi().post("/client/theme-pref", { theme: id }).catch(() => { /* best-effort */ });
    toast.success(`Theme changed to ${id}`);
  };

  return (
    <div className="space-y-3">
      <div className="text-white/60 text-sm">Pick a color palette — applies instantly, remembered per account.</div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {THEMES.map((t) => (
          <button key={t.id} onClick={() => apply(t.id)} data-testid={`theme-${t.id}`}
            className={`bg-[#0d0a14] border rounded-md p-4 text-left transition ${current === t.id ? "border-emerald-400 ring-2 ring-emerald-400/40" : "border-white/10 hover:border-white/30"}`}>
            <div className="w-full h-8 rounded mb-2" style={{ background: `linear-gradient(135deg, ${t.color}, ${t.color}88)` }} />
            <div className="font-bold text-white text-sm">{t.label}</div>
            {current === t.id && <div className="text-[10px] text-emerald-400 mt-1">✓ Active</div>}
          </button>
        ))}
      </div>
    </div>
  );
}


// -----------------------------------------------------------------------------
// SecurityView — 2FA (TOTP) enable/disable + Discord link/unlink.
// -----------------------------------------------------------------------------
export function SecurityView({ authedApi, user }) {
  const [status, setStatus] = useState({ enabled: false });
  const [step, setStep] = useState("idle"); // idle | qr | confirm | done
  const [qr, setQr] = useState(null); // { secret, qr_code, otpauth_url }
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(null);
  const [busy, setBusy] = useState(false);
  const [disableCode, setDisableCode] = useState("");
  const [disableBusy, setDisableBusy] = useState(false);
  const [dcConfigured, setDcConfigured] = useState(false);
  const [dcLinked, setDcLinked] = useState(user?.discord_username || "");

  const load = async () => {
    try {
      const [s, dcCfg] = await Promise.all([
        authedApi.get("/auth/2fa/status").then((r) => r.data).catch(() => ({ enabled: false })),
        authedApi.get("/auth/discord/login-url?state=probe").then(() => ({ ok: true })).catch(() => ({ ok: false })),
      ]);
      setStatus(s);
      setDcConfigured(!!dcCfg.ok);
      const me = await authedApi.get("/auth/me").then((r) => r.data).catch(() => null);
      if (me?.discord_username) setDcLinked(me.discord_username);
    } catch { /* silent */ }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const startEnroll = async () => {
    setBusy(true);
    try {
      const r = await authedApi.post("/auth/2fa/setup", {});
      setQr(r.data);
      setStep("qr");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Setup failed");
    }
    setBusy(false);
  };

  const confirmEnroll = async () => {
    setBusy(true);
    try {
      const r = await authedApi.post("/auth/2fa/enable", { code: code.trim() });
      setRecovery(r.data.recovery_codes || []);
      setStep("done");
      setCode("");
      await load();
      toast.success("✅ 2FA enabled — save your recovery codes!");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Verification failed");
    }
    setBusy(false);
  };

  const disable2FA = async () => {
    if (!disableCode.trim()) { toast.error("Enter your 6-digit code or a recovery code"); return; }
    setDisableBusy(true);
    try {
      await authedApi.post("/auth/2fa/disable", { code: disableCode.trim() });
      setStatus({ enabled: false });
      setDisableCode("");
      toast.success("2FA disabled");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Disable failed");
    }
    setDisableBusy(false);
  };

  const linkDiscord = async () => {
    try {
      const r = await authedApi.get("/auth/discord/login-url?state=link");
      window.location.href = r.data.url;
    } catch (e) {
      toast.error(e.response?.data?.detail || "Discord OAuth not configured yet — ask the owner.");
    }
  };

  const unlinkDiscord = async () => {
    try {
      await authedApi.post("/client/discord/unlink", {});
      setDcLinked("");
      toast.success("Discord unlinked");
    } catch (e) {
      toast.error("Unlink failed");
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6" data-testid="security-view">
      <div>
        <h1 className="font-display font-black text-2xl md:text-3xl text-white mb-1">Security</h1>
        <p className="text-white/60 text-sm">Protect your account with 2FA and link your Discord for one-click login.</p>
      </div>

      {/* 2FA card */}
      <div className="bg-emerald-950/40 border border-emerald-500/25 rounded-xl p-6" data-testid="twofa-card">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-emerald-300 font-black">Two-factor authentication</div>
            <h2 className="font-display font-bold text-xl text-white mt-1">Authenticator app (TOTP)</h2>
            <p className="text-sm text-white/60 mt-1">
              {status.enabled ? "🔒 Currently ENABLED — you'll be asked for a 6-digit code on every login." : "Currently disabled. Enable it to protect your balance and orders."}
            </p>
          </div>
          <span className={`px-3 py-1 rounded-full text-[10px] uppercase font-black tracking-wider ${status.enabled ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40" : "bg-white/5 text-white/50 border border-white/10"}`}>
            {status.enabled ? "ON" : "OFF"}
          </span>
        </div>

        {!status.enabled && step === "idle" && (
          <button onClick={startEnroll} disabled={busy} data-testid="twofa-enable-btn"
            className="px-5 py-2.5 rounded-md bg-emerald-400 hover:bg-emerald-300 text-black font-bold text-sm disabled:opacity-50">
            {busy ? "Loading…" : "Enable 2FA"}
          </button>
        )}

        {step === "qr" && qr && (
          <div className="space-y-4">
            <div className="flex flex-col sm:flex-row gap-4 items-start">
              <img src={qr.qr_code} alt="Scan this QR" className="w-44 h-44 rounded-md bg-white p-2" data-testid="twofa-qr" />
              <div className="flex-1 text-sm space-y-2">
                <div className="font-bold text-white">1. Scan this QR in your authenticator app</div>
                <div className="text-white/60 text-xs">Google Authenticator, Authy, 1Password, Bitwarden — any TOTP app works.</div>
                <div className="pt-2 border-t border-white/10">
                  <div className="text-white/40 text-[10px] uppercase tracking-wider mb-1">Or enter manually</div>
                  <code className="block text-emerald-200 bg-black/40 rounded px-2 py-1 text-xs break-all">{qr.secret}</code>
                </div>
              </div>
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wider text-white/50 font-bold mb-1">2. Enter the 6-digit code from your app</label>
              <div className="flex gap-2">
                <input data-testid="twofa-verify-code" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  placeholder="123456" maxLength={6}
                  className="flex-1 bg-black/40 border border-white/10 rounded px-3 py-2 text-lg font-mono tracking-widest text-center text-white" />
                <button onClick={confirmEnroll} disabled={busy || code.length !== 6} data-testid="twofa-verify-btn"
                  className="px-5 py-2 rounded bg-emerald-400 hover:bg-emerald-300 text-black font-bold text-sm disabled:opacity-50">
                  {busy ? "…" : "Confirm"}
                </button>
              </div>
            </div>
          </div>
        )}

        {step === "done" && recovery && (
          <div className="space-y-3">
            <div className="p-3 bg-amber-500/10 border border-amber-500/40 rounded-md text-sm text-amber-200">
              <b>⚠️ Save these recovery codes now.</b> Each works ONCE if you lose your phone. They will not be shown again.
            </div>
            <div className="grid grid-cols-2 gap-2 font-mono text-sm bg-black/40 p-4 rounded-md" data-testid="twofa-recovery-codes">
              {recovery.map((r) => <div key={r} className="text-emerald-200">{r}</div>)}
            </div>
            <button onClick={() => { setStep("idle"); setRecovery(null); }}
              className="px-5 py-2 rounded bg-white/10 hover:bg-white/15 text-white font-bold text-sm">
              I saved them
            </button>
          </div>
        )}

        {status.enabled && step === "idle" && (
          <div className="space-y-3 pt-4 border-t border-white/10">
            <label className="block text-xs uppercase tracking-wider text-white/50 font-bold">Disable 2FA</label>
            <div className="flex gap-2">
              <input data-testid="twofa-disable-code" value={disableCode} onChange={(e) => setDisableCode(e.target.value)}
                placeholder="Enter current 6-digit or recovery code"
                className="flex-1 bg-black/40 border border-white/10 rounded px-3 py-2 text-sm text-white" />
              <button onClick={disable2FA} disabled={disableBusy} data-testid="twofa-disable-btn"
                className="px-5 py-2 rounded bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 text-red-200 font-bold text-sm disabled:opacity-50">
                {disableBusy ? "…" : "Disable"}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Discord link card */}
      <div className="bg-emerald-950/40 border border-emerald-500/25 rounded-xl p-6" data-testid="discord-link-card">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-indigo-300 font-black">Discord</div>
            <h2 className="font-display font-bold text-xl text-white mt-1">Link your Discord account</h2>
            <p className="text-sm text-white/60 mt-1">
              {dcLinked ? <>Linked to <b className="text-indigo-300">@{dcLinked}</b> — you can now use <code className="text-emerald-300">$deposit</code> and <code className="text-emerald-300">$buy</code> from Discord.</> : "One-click login next time · deposit crypto and place orders from Discord chat."}
            </p>
          </div>
        </div>
        {dcLinked ? (
          <button onClick={unlinkDiscord} data-testid="discord-unlink-btn"
            className="px-5 py-2 rounded bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 text-red-200 font-bold text-sm">
            Unlink Discord
          </button>
        ) : (
          <button onClick={linkDiscord} disabled={!dcConfigured} data-testid="discord-link-btn"
            className="px-5 py-2 rounded bg-[#5865F2] hover:bg-[#4752C4] text-white font-bold text-sm disabled:opacity-40 inline-flex items-center gap-2">
            <LinkIcon className="w-4 h-4" /> Link with Discord
          </button>
        )}
        {!dcConfigured && !dcLinked && (
          <p className="text-[10px] text-white/40 mt-2">Discord OAuth needs to be configured by the owner first.</p>
        )}
      </div>
    </div>
  );
}
