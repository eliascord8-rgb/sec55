import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2, Bot, ExternalLink, Trash2, Shield, Save } from "lucide-react";

const FEATURES = [
  ["anti_raid", "Anti-Raid", "Auto-kick mass-join raids"],
  ["moderation", "Moderation", "Warn / mute / kick commands"],
  ["blacklist", "Blacklist Bot", "Block words & spam links"],
  ["anti_nuke", "Anti-Nuke", "Stop mass channel/role deletion"],
];

const empty = {
  guild_id: "", welcome_channel_id: "", welcome_text: "Welcome {user} to {server}! 🎉",
  welcomer_enabled: true, bot_nickname: "",
  features: { anti_raid: false, moderation: true, blacklist: false, anti_nuke: false },
};

export default function DiscordManageView({ authedApi }) {
  const [guilds, setGuilds] = useState([]);
  const [form, setForm] = useState(empty);
  const [saving, setSaving] = useState(false);
  const [inviteUrl, setInviteUrl] = useState("");

  const load = async () => {
    try {
      const r = await authedApi().get("/client/discord/guilds");
      setGuilds(r.data.guilds || []);
    } catch { /* ignore */ }
  };
  useEffect(() => {
    load();
    authedApi().get("/discord/invite-url").then((r) => setInviteUrl(r.data.url)).catch(() => {});
    // eslint-disable-next-line
  }, []);

  const save = async () => {
    if (!form.guild_id.trim()) { toast.error("Enter your Server (Guild) ID"); return; }
    setSaving(true);
    try {
      await authedApi().post("/client/discord/guilds", form);
      toast.success("Discord server settings saved — the bot will use them right away.");
      setForm(empty);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Save failed"); }
    finally { setSaving(false); }
  };

  const remove = async (gid) => {
    try {
      await authedApi().delete(`/client/discord/guilds/${gid}`);
      toast.success("Server removed");
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Failed"); }
  };

  const edit = (g) => setForm({
    guild_id: g.guild_id, welcome_channel_id: g.welcome_channel_id || "",
    welcome_text: g.welcome_text || "", welcomer_enabled: g.welcomer_enabled !== false,
    bot_nickname: g.bot_nickname || "",
    features: { ...empty.features, ...(g.features || {}) },
  });

  return (
    <div className="max-w-4xl mx-auto space-y-6" data-testid="discord-manage-view">
      <div>
        <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight flex items-center gap-2">
          <Bot className="w-7 h-7 text-emerald-400" /> Manage Discord
        </h1>
        <p className="text-white/50 text-sm mt-2">Invite the Better Social bot into your own server and control it from here — welcomer, moderation, anti-raid and more.</p>
      </div>

      <div className="bg-[#0d0a14] border border-indigo-500/30 rounded-md p-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="font-display font-bold text-sm">Step 1 — Invite the bot to your server</div>
          <div className="text-xs text-white/50 mt-1">You need "Manage Server" permission on your Discord server.</div>
        </div>
        {inviteUrl ? (
          <a href={inviteUrl} target="_blank" rel="noopener noreferrer" data-testid="discord-invite-btn"
             className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-indigo-500 hover:bg-indigo-400 text-white text-xs font-black uppercase tracking-wider transition">
            <ExternalLink className="w-3.5 h-3.5" /> Invite bot
          </a>
        ) : (
          <span className="text-xs text-amber-300">Invite link not configured yet — ask support.</span>
        )}
      </div>

      <div className="bg-[#0d0a14] border border-white/10 rounded-md p-5 space-y-4">
        <div className="font-display font-bold text-sm flex items-center gap-2"><Shield className="w-4 h-4 text-emerald-400" /> Step 2 — Configure your server</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] uppercase tracking-widest text-white/50">Server (Guild) ID</label>
            <input value={form.guild_id} onChange={(e) => setForm({ ...form, guild_id: e.target.value })}
              data-testid="dm-guild-id" placeholder="e.g. 1477630408404373604"
              className="w-full mt-1 bg-black/40 border border-white/15 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-emerald-400" />
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-widest text-white/50">Welcome channel ID (optional)</label>
            <input value={form.welcome_channel_id} onChange={(e) => setForm({ ...form, welcome_channel_id: e.target.value })}
              data-testid="dm-channel-id" placeholder="Right-click channel → Copy Channel ID"
              className="w-full mt-1 bg-black/40 border border-white/15 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-emerald-400" />
          </div>
          <div className="md:col-span-2">
            <label className="text-[10px] uppercase tracking-widest text-white/50">Welcome message — use {"{user}"} and {"{server}"}</label>
            <textarea value={form.welcome_text} onChange={(e) => setForm({ ...form, welcome_text: e.target.value })}
              data-testid="dm-welcome-text" rows={2}
              className="w-full mt-1 bg-black/40 border border-white/15 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-emerald-400" />
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-widest text-white/50">Custom bot name in your server</label>
            <input value={form.bot_nickname} onChange={(e) => setForm({ ...form, bot_nickname: e.target.value })}
              data-testid="dm-bot-nickname" placeholder="e.g. My Cool Bot" maxLength={32}
              className="w-full mt-1 bg-black/40 border border-white/15 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-emerald-400" />
          </div>
          <label className="flex items-center gap-2 self-end pb-2 cursor-pointer">
            <input type="checkbox" checked={form.welcomer_enabled} data-testid="dm-welcomer-toggle"
              onChange={(e) => setForm({ ...form, welcomer_enabled: e.target.checked })} className="accent-emerald-500 w-4 h-4" />
            <span className="text-xs text-white/80 font-bold">Welcomer enabled</span>
          </label>
        </div>

        <div>
          <div className="text-[10px] uppercase tracking-widest text-white/50 mb-2">Features</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {FEATURES.map(([key, label, desc]) => (
              <label key={key} className={`flex items-start gap-2 p-3 rounded-md border cursor-pointer transition ${form.features[key] ? "border-emerald-500/50 bg-emerald-500/10" : "border-white/10 bg-black/20"}`}>
                <input type="checkbox" checked={!!form.features[key]} data-testid={`dm-feature-${key}`}
                  onChange={(e) => setForm({ ...form, features: { ...form.features, [key]: e.target.checked } })}
                  className="accent-emerald-500 w-4 h-4 mt-0.5" />
                <span>
                  <span className="block text-xs font-bold text-white">{label}</span>
                  <span className="block text-[10px] text-white/50">{desc}</span>
                </span>
              </label>
            ))}
          </div>
        </div>

        <button onClick={save} disabled={saving} data-testid="dm-save-btn"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-md bg-emerald-500 hover:bg-emerald-400 text-black text-sm font-black uppercase tracking-wider transition disabled:opacity-40">
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} Save server settings
        </button>
      </div>

      {guilds.length > 0 && (
        <div className="bg-[#0d0a14] border border-white/10 rounded-md p-5">
          <div className="font-display font-bold text-sm mb-3">Your managed servers</div>
          <div className="space-y-2">
            {guilds.map((g) => (
              <div key={g.guild_id} className="flex flex-wrap items-center gap-3 p-3 rounded-md bg-black/30 border border-white/10" data-testid={`dm-guild-${g.guild_id}`}>
                <span className="font-mono text-xs text-white/80">{g.guild_id}</span>
                {g.bot_nickname && <span className="text-xs text-indigo-300">bot: {g.bot_nickname}</span>}
                <span className={`text-[10px] uppercase font-bold ${g.welcomer_enabled ? "text-emerald-300" : "text-white/40"}`}>welcomer {g.welcomer_enabled ? "on" : "off"}</span>
                <span className="text-[10px] text-white/40">{Object.entries(g.features || {}).filter(([, v]) => v).map(([k]) => k.replace("_", "-")).join(" · ") || "no features"}</span>
                <span className="ml-auto flex gap-2">
                  <button onClick={() => edit(g)} className="text-xs text-emerald-300 hover:text-emerald-200 font-bold uppercase">Edit</button>
                  <button onClick={() => remove(g.guild_id)} data-testid={`dm-guild-delete-${g.guild_id}`} className="text-red-300 hover:text-red-200"><Trash2 className="w-3.5 h-3.5" /></button>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
