import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2, Rocket, Zap, Palette, KeyRound, Mail, Save, User, Camera, Link as LinkIcon, Trash2 } from "lucide-react";

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
      <div className="flex gap-2">
        {[["account", "Account", KeyRound], ["appearance", "Appearance", Palette]].map(([id, label, Icon]) => (
          <button key={id} onClick={() => setTab(id)} data-testid={`settings-tab-${id}`}
            className={`px-4 py-2 rounded-md text-xs font-bold uppercase tracking-wider inline-flex items-center gap-2 transition ${tab === id ? "bg-emerald-500 text-black" : "bg-[#0d0a14] text-white/70 hover:text-white border border-white/10"}`}>
            <Icon className="w-3.5 h-3.5" /> {label}
          </button>
        ))}
      </div>
      {tab === "account" && <AccountSettings authedApi={authedApi} user={user} />}
      {tab === "appearance" && <AppearanceSettings authedApi={authedApi} />}
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
