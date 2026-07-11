import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2, ExternalLink, CheckCircle2, Clock, FileText, HelpCircle, Mail, MessageCircle, Wallet, ShoppingBag, Sparkles } from "lucide-react";

// -----------------------------------------------------------------------------
// InvoicesView — consolidated list of all payment invoices (pending / paid /
// cancelled). Pulls from the client's transactions collection.
// -----------------------------------------------------------------------------
export function InvoicesView({ authedApi, reloadBalance }) {
  const [items, setItems] = useState(null);
  const [verifying, setVerifying] = useState(null);

  const load = async () => {
    try {
      const r = await authedApi().get("/client/invoices");
      setItems(r.data.invoices || []);
    } catch { toast.error("Failed to load invoices"); }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, []);

  const verify = async (id) => {
    setVerifying(id);
    try {
      const r = await authedApi().post(`/client/funds/nowpayments-verify/${id}`);
      if (r.data.credited) toast.success(`Credited: +$${r.data.amount}`);
      else if (r.data.already_credited) toast.info("Already credited");
      else toast.info(`Status: ${r.data.status || "unknown"}`);
      reloadBalance?.();
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Verify failed"); }
    finally { setVerifying(null); }
  };

  if (items === null) return <div className="text-white/60 text-sm">Loading…</div>;

  const unpaid = items.filter((i) => i.status === "pending");
  const paid = items.filter((i) => i.status === "approved");
  const failed = items.filter((i) => ["cancelled", "canceled", "failed", "expired"].includes(String(i.status || "").toLowerCase()));

  return (
    <div className="max-w-4xl space-y-6" data-testid="invoices-view">
      <div>
        <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight flex items-center gap-2">
          <FileText className="w-7 h-7 text-emerald-400" /> Invoices
        </h1>
        <p className="text-white/50 text-sm mt-2">Every deposit and withdrawal you've made. Pending crypto deposits auto-refresh every 20 s.</p>
      </div>

      {unpaid.length > 0 && (
        <Section title="Unpaid — awaiting payment" tone="amber">
          {unpaid.map((it) => (
            <Row key={it.id} it={it} verifying={verifying} onVerify={verify} />
          ))}
        </Section>
      )}
      {paid.length > 0 && (
        <Section title="Paid" tone="emerald">
          {paid.slice(0, 30).map((it) => <Row key={it.id} it={it} />)}
        </Section>
      )}
      {failed.length > 0 && (
        <Section title="Cancelled / failed" tone="red">
          {failed.slice(0, 20).map((it) => <Row key={it.id} it={it} />)}
        </Section>
      )}
      {items.length === 0 && (
        <div className="text-white/50 text-sm bg-[#0d0a14] border border-white/5 rounded-md p-8 text-center">
          No invoices yet — start by adding funds to your wallet.
        </div>
      )}
    </div>
  );
}

function Section({ title, tone = "emerald", children }) {
  const dot = { amber: "bg-amber-400", emerald: "bg-emerald-400", red: "bg-red-400" }[tone];
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <span className={`w-2 h-2 rounded-full ${dot} animate-pulse`} />
        <div className="text-[10px] uppercase tracking-widest text-white/60 font-bold">{title}</div>
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function Row({ it, verifying, onVerify }) {
  const date = it.created_at ? new Date(it.created_at).toLocaleString() : "—";
  const isPending = it.status === "pending";
  const isPaid = it.status === "approved";
  return (
    <div className="bg-[#0d0a14] border border-white/5 rounded-md p-3 flex flex-wrap items-center gap-3" data-testid={`invoice-${it.id}`}>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className={`inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-sm ${
            isPending ? "bg-amber-500/20 text-amber-300" :
            isPaid ? "bg-emerald-500/20 text-emerald-300" :
            "bg-red-500/20 text-red-300"
          }`}>
            {isPending ? <Clock className="w-3 h-3" /> : isPaid ? <CheckCircle2 className="w-3 h-3" /> : null}
            {it.status}
          </span>
          <span className="text-[10px] uppercase tracking-widest text-white/40">{it.method || it.type}</span>
        </div>
        <div className="text-xs text-white/70 mt-1 truncate font-mono">{it.id}</div>
        <div className="text-[10px] text-white/40">{date}</div>
      </div>
      <div className="font-display font-black text-lg text-emerald-300 font-mono">
        ${Math.abs(Number(it.amount || 0)).toFixed(2)}
      </div>
      {isPending && it.checkout_url && (
        <a href={it.checkout_url} target="_blank" rel="noreferrer"
          data-testid={`invoice-pay-${it.id}`}
          className="px-3 py-1.5 rounded-md text-[11px] font-bold uppercase tracking-wider bg-emerald-500 text-black hover:bg-emerald-400 transition inline-flex items-center gap-1">
          <ExternalLink className="w-3 h-3" /> Pay now
        </a>
      )}
      {isPending && onVerify && (
        <button onClick={() => onVerify(it.id)} disabled={verifying === it.id}
          data-testid={`invoice-verify-${it.id}`}
          className="px-3 py-1.5 rounded-md text-[11px] font-bold uppercase tracking-wider border border-white/10 hover:bg-white/5 transition">
          {verifying === it.id ? <Loader2 className="w-3 h-3 animate-spin" /> : "Verify"}
        </button>
      )}
    </div>
  );
}

// -----------------------------------------------------------------------------
// HelpCenterView — static FAQ + contact options.
// -----------------------------------------------------------------------------

const FAQ = [
  { q: "How do I add funds to my balance?", a: "Go to Wallet → choose an amount → pay with crypto (NOWPayments) or card (Selly). Crypto deposits credit automatically once the network confirms (usually a few minutes)." },
  { q: "How long do orders take?", a: "Most services start within 30 seconds of placing your order. Larger quantities (10 000+ likes / followers) can take a few hours to complete." },
  { q: "Can I get a refund?", a: "Yes — cancel any active order from your Orders page and the amount is refunded to your withdrawable balance instantly. Once an order is completed we can't refund it." },
  { q: "How does the daily Stairs game work?", a: "Once per day, users with $50+ in lifetime deposits can play. Stake is $0.80, you climb up to 40× by picking the safe tile each step. Cash out any time. Bomb = you lose the stake." },
  { q: "How do I bulk-order for TikTok Live?", a: "Open Purchase → pick a TikTok Live service → flip the Bulk toggle → paste up to 200 links or @usernames (one per line) → set the quantity per stream → confirm. All orders fire in parallel." },
  { q: "The 5sim SMS code isn't showing.", a: "Codes appear within 10–60 seconds — the Numbers view refreshes every 8 s. If it never arrives, click Cancel to get a full refund." },
  { q: "Where do casino wins go?", a: "Games credit your withdrawable balance (separate from deposits). You can withdraw once you meet the account minimum on the Withdraw page." },
  { q: "How do I contact support?", a: "Open the Support tab in the dashboard to open a ticket, or DM the owner directly from the Friends tab. Response time is under 4 hours during business hours." },
];

export function HelpCenterView() {
  const [open, setOpen] = useState(0);
  return (
    <div className="max-w-4xl space-y-6" data-testid="help-view">
      <div>
        <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight flex items-center gap-2">
          <HelpCircle className="w-7 h-7 text-emerald-400" /> Help Center
        </h1>
        <p className="text-white/50 text-sm mt-2">Quick answers to the questions we get most. Still stuck? Message us — we&apos;re usually online.</p>
      </div>

      <div className="grid sm:grid-cols-3 gap-3">
        <Shortcut icon={ShoppingBag} label="How to buy" onClick={() => setOpen(1)} />
        <Shortcut icon={Wallet} label="Payments & refunds" onClick={() => setOpen(0)} />
        <Shortcut icon={Sparkles} label="Games" onClick={() => setOpen(3)} />
      </div>

      <div className="bg-[#0d0a14] border border-white/5 rounded-md divide-y divide-white/5" data-testid="help-faq">
        {FAQ.map((item, i) => {
          const isOpen = open === i;
          return (
            <div key={i}>
              <button
                onClick={() => setOpen(isOpen ? -1 : i)}
                data-testid={`faq-${i}`}
                className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-white/[0.02] transition"
              >
                <span className="text-sm text-white/90 font-bold">{item.q}</span>
                <span className={`text-emerald-400 transition ${isOpen ? "rotate-45" : ""}`}>+</span>
              </button>
              {isOpen && (
                <div className="px-4 pb-4 text-sm text-white/70 leading-relaxed">{item.a}</div>
              )}
            </div>
          );
        })}
      </div>

      <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-md p-5" data-testid="help-contact">
        <div className="flex items-center gap-2 mb-3">
          <MessageCircle className="w-5 h-5 text-emerald-300" />
          <div className="font-display font-black text-emerald-200">Still need help?</div>
        </div>
        <div className="text-sm text-white/70 mb-3">Open a support ticket or DM the owner — we typically reply within a few hours.</div>
        <div className="flex flex-wrap gap-2">
          <a href="#" onClick={(e) => { e.preventDefault(); window.dispatchEvent(new CustomEvent("bs:goto", { detail: "tickets" })); }}
            data-testid="help-open-ticket"
            className="px-4 py-2 rounded-md text-xs font-bold uppercase tracking-wider bg-emerald-500 text-black hover:bg-emerald-400 transition inline-flex items-center gap-2">
            <FileText className="w-3.5 h-3.5" /> Open a ticket
          </a>
          <a href="#" onClick={(e) => { e.preventDefault(); window.dispatchEvent(new CustomEvent("bs:goto", { detail: "messages" })); }}
            data-testid="help-dm-owner"
            className="px-4 py-2 rounded-md text-xs font-bold uppercase tracking-wider border border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/10 transition inline-flex items-center gap-2">
            <Mail className="w-3.5 h-3.5" /> DM owner
          </a>
        </div>
      </div>
    </div>
  );
}

function Shortcut({ icon: Icon, label, onClick }) {
  return (
    <button onClick={onClick} className="bg-[#0d0a14] border border-white/5 hover:border-emerald-400/40 rounded-md p-4 text-left transition">
      <Icon className="w-5 h-5 text-emerald-400 mb-2" />
      <div className="font-bold text-white text-sm">{label}</div>
    </button>
  );
}
