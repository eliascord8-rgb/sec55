import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Users, Copy, Gift, DollarSign } from "lucide-react";

export default function ReferralsView({ authedApi }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    authedApi().get("/client/referrals").then((r) => setData(r.data)).catch(() => {});
    // eslint-disable-next-line
  }, []);

  if (!data) return <div className="text-white/50 text-sm py-10 text-center">Loading…</div>;
  const link = `${window.location.origin}/?ref=${data.code}`;
  const copy = () => { navigator.clipboard?.writeText(link); toast.success("Referral link copied!"); };

  return (
    <div className="max-w-4xl mx-auto space-y-6" data-testid="referrals-view">
      <div>
        <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight flex items-center gap-2">
          <Users className="w-7 h-7 text-emerald-400" /> Referral Rewards
        </h1>
        <p className="text-white/50 text-sm mt-2">
          Share your link. When an invited friend makes their first deposit you earn
          <span className="text-emerald-300 font-bold"> ${data.reward_usd.toFixed(2)}</span> (spendable AND withdrawable)
          — and your friend gets <span className="text-emerald-300 font-bold">+{data.friend_bonus_pct}%</span> extra on that deposit.
        </p>
      </div>

      <div className="bg-[#0d0a14] border border-emerald-500/30 rounded-md p-5">
        <div className="text-[10px] uppercase tracking-widest text-white/50 mb-2">Your share link</div>
        <div className="flex flex-wrap gap-2">
          <input readOnly value={link} data-testid="referral-link-input"
            className="flex-1 min-w-[240px] bg-black/40 border border-white/15 rounded-md px-3 py-2 text-sm text-emerald-200 font-mono outline-none" />
          <button onClick={copy} data-testid="referral-copy-btn"
            className="inline-flex items-center gap-2 px-5 py-2 rounded-md bg-emerald-500 hover:bg-emerald-400 text-black text-xs font-black uppercase tracking-wider transition">
            <Copy className="w-3.5 h-3.5" /> Copy
          </button>
        </div>
        <div className="text-[11px] text-white/40 mt-2">Code: <span className="font-mono text-white/70">{data.code}</span> — friends can also enter it manually when signing up via your link.</div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="bg-[#0d0a14] border border-white/10 rounded-md p-4 text-center">
          <Users className="w-5 h-5 text-emerald-400 mx-auto mb-1" />
          <div className="font-display font-black text-2xl" data-testid="referral-invited-count">{data.invited.length}</div>
          <div className="text-[10px] uppercase tracking-widest text-white/40">Friends invited</div>
        </div>
        <div className="bg-[#0d0a14] border border-white/10 rounded-md p-4 text-center">
          <Gift className="w-5 h-5 text-emerald-400 mx-auto mb-1" />
          <div className="font-display font-black text-2xl">{data.invited.filter((f) => f.deposited).length}</div>
          <div className="text-[10px] uppercase tracking-widest text-white/40">Deposited</div>
        </div>
        <div className="bg-[#0d0a14] border border-emerald-500/30 rounded-md p-4 text-center">
          <DollarSign className="w-5 h-5 text-emerald-400 mx-auto mb-1" />
          <div className="font-display font-black text-2xl text-emerald-300" data-testid="referral-earned-total">${data.earned_total.toFixed(2)}</div>
          <div className="text-[10px] uppercase tracking-widest text-white/40">Total earned</div>
        </div>
      </div>

      <div className="bg-[#0d0a14] border border-white/10 rounded-md p-5">
        <div className="font-display font-bold text-sm mb-3">Invited friends</div>
        {data.invited.length === 0 ? (
          <div className="text-xs text-white/40">Nobody yet — share your link in your bio, group chats or streams.</div>
        ) : (
          <div className="space-y-2">
            {data.invited.map((f, i) => (
              <div key={i} className="flex items-center gap-3 p-2.5 rounded-md bg-black/30 border border-white/10">
                <span className="font-mono text-sm text-white">{f.username}</span>
                <span className="text-[10px] text-white/40">{f.joined_at ? new Date(f.joined_at).toLocaleDateString() : ""}</span>
                <span className={`ml-auto text-[10px] uppercase font-black px-2 py-0.5 rounded-sm ${f.deposited ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40" : "bg-white/10 text-white/50 border border-white/10"}`}>
                  {f.deposited ? "Deposited ✓" : "No deposit yet"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
