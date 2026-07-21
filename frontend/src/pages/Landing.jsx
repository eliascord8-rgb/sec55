import { useState, useEffect, useRef } from "react";
import { toast } from "sonner";
import ServicesCatalog from "@/components/ServicesCatalog";
import AIWidget from "@/components/AIWidget";
import OrderTicker from "@/components/OrderTicker";
import { useNavigate, Link } from "react-router-dom";
import {
  ArrowRight,
  Zap,
  Shield,
  Coins,
  Rocket,
  Ticket,
  Bot,
  Sparkles,
  User as UserIcon,
  MessageCircle,
  ChevronDown,
} from "lucide-react";
import { api } from "@/lib/api";
import { LanguagePicker } from "@/context/LanguageContext";
import { CurrencyPicker } from "@/context/CurrencyContext";

// ============================================================================
// Better Social — Landing page
// ----------------------------------------------------------------------------
// Redesigned per /app/design_guidelines.json:
//   • Dark obsidian palette (#050505) + Electric Cyan (#00E5FF) accent
//   • Outfit (headings) + Manrope (body) typography
//   • Bento-grid feature layout, asymmetric hero, sleek 1px borders
//   • Glassy sticky header, radial glow behind hero, subtle micro-motion
// ============================================================================

const FEATURES = [
  {
    span: "lg:col-span-8",
    icon: Zap,
    title: "Instant Delivery",
    desc: "Most orders kick off within minutes of confirmation. No waiting, no babysitting.",
    accent: "bg-cyan-500/10 border-cyan-500/30",
    visual: "progress",
  },
  {
    span: "lg:col-span-4",
    icon: Coins,
    title: "Crypto + Card",
    desc: "BTC · ETH · USDT · LTC · plus Visa & Mastercard. Zero login required.",
    accent: "bg-white/[0.02]",
    visual: "chips",
  },
  {
    span: "lg:col-span-4",
    icon: Shield,
    title: "Anonymous Checkout",
    desc: "No account. No email required. Just paste, pay, and grow.",
    accent: "bg-white/[0.02]",
    visual: "mask",
  },
  {
    span: "lg:col-span-8",
    icon: Rocket,
    title: "1,000+ Services",
    desc: "Instagram · TikTok · YouTube · Spotify · X · Threads · and far beyond. Sourced from premium providers.",
    accent: "bg-white/[0.02]",
    visual: "list",
  },
];

const STEPS = [
  { n: "01", t: "Pick a service", d: "Browse the live catalog. Filter by network." },
  { n: "02", t: "Drop the link", d: "Paste any public profile or post URL." },
  { n: "03", t: "Pay your way", d: "Crypto, card via Selly, or a Better Social coupon." },
  { n: "04", t: "Watch it flow", d: "Auto-pushed to providers, starts in real time." },
];

const FAQ = [
  { q: "Do I need an account?", a: "No. Better Social is fully no-login. Pay, place, done. Create an account only if you want a wallet balance, live-order automation, and the community shoutbox." },
  { q: "What's a Better Social coupon?", a: "A prepaid multi-use balance code. Bring it to checkout and it deducts the order total from your remaining balance until it hits zero." },
  { q: "Which cryptos are accepted?", a: "BTC, ETH, USDT, LTC, and more via Selly and NOWPayments. Card payments (Visa / Mastercard) are supported too." },
  { q: "When does my order start?", a: "Coupon orders submit instantly. Crypto orders submit the moment the network confirms your payment — usually 1–3 blocks." },
  { q: "Is my data private?", a: "We only store the order details we need to fulfil the service. No IP profiling, no cross-site tracking, no email spam." },
];

const CRYPTO_METHODS = ["BTC", "ETH", "USDT", "LTC", "USDC", "BNB", "DOGE", "SOL"];

export default function Landing() {
  const [stats, setStats] = useState({ services: 0, networks: 0 });
  const [aiOpen, setAiOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("selly_order") === "1") {
      toast.success(
        "Payment received! Your order will be auto-placed within ~60s of Selly's final confirmation.",
        { duration: 9000 }
      );
      window.history.replaceState({}, "", "/");
    }
    api
      .get("/services")
      .then((r) => {
        const list = Array.isArray(r.data.services) ? r.data.services : [];
        const networks = new Set(list.map((s) => s.category)).size;
        setStats({ services: list.length, networks });
      })
      .catch(() => {});
    const onScroll = () => setScrolled(window.scrollY > 20);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const goCatalog = () => {
    const el = document.getElementById("services");
    if (el) el.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="relative bg-[#050505] text-white font-manrope overflow-x-hidden">
      {/* ==================== GLASSY HEADER ==================== */}
      <header
        data-testid="site-header"
        className={`fixed top-0 inset-x-0 z-40 transition-all duration-300 ${
          scrolled ? "backdrop-blur-xl bg-[#050505]/80 border-b border-white/5" : "bg-transparent"
        }`}
      >
        <div className="max-w-7xl mx-auto px-4 md:px-8 h-16 md:h-[68px] flex items-center justify-between gap-3">
          <Link to="/" className="flex items-center gap-2.5 shrink-0" data-testid="brand-logo">
            <div className="w-8 h-8 md:w-9 md:h-9 rounded-lg bg-cyan-500/15 border border-cyan-500/40 flex items-center justify-center shadow-[0_0_20px_rgba(0,229,255,0.15)]">
              <Sparkles className="w-4 h-4 md:w-4.5 md:h-4.5 text-cyan-300" strokeWidth={2.5} />
            </div>
            <span className="font-display font-black text-base md:text-lg tracking-tight text-white">
              Better<span className="text-cyan-400">Social</span>
            </span>
          </Link>

          <nav className="hidden lg:flex items-center gap-9 text-sm font-manrope">
            <a
              href="#services"
              className="text-zinc-400 hover:text-white transition-colors"
              data-testid="nav-services"
            >
              Services
            </a>
            <a
              href="#how"
              className="text-zinc-400 hover:text-white transition-colors"
              data-testid="nav-how"
            >
              How it works
            </a>
            <a
              href="#faq"
              className="text-zinc-400 hover:text-white transition-colors"
              data-testid="nav-faq"
            >
              FAQ
            </a>
          </nav>

          <div className="flex items-center gap-1.5 md:gap-2 shrink-0">
            <div className="hidden md:flex items-center gap-1.5">
              <LanguagePicker />
              <CurrencyPicker />
            </div>
            <Link
              to="/client"
              data-testid="header-client-btn"
              className="inline-flex items-center gap-1.5 px-3 md:px-4 py-2 rounded-full border border-white/10 hover:border-white/30 bg-white/[0.02] hover:bg-white/[0.05] text-[11px] md:text-xs font-semibold text-white transition-all"
            >
              <UserIcon className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Client Area</span>
              <span className="sm:hidden">Client</span>
            </Link>
            <button
              onClick={goCatalog}
              data-testid="header-checkout-btn"
              className="px-3.5 md:px-5 py-2 rounded-full bg-cyan-400 hover:bg-cyan-300 text-black text-[11px] md:text-xs font-bold tracking-wide transition-all whitespace-nowrap shadow-[0_0_20px_rgba(0,229,255,0.25)] hover:shadow-[0_0_30px_rgba(0,229,255,0.5)]"
            >
              Order now
            </button>
          </div>
        </div>
      </header>

      {/* ==================== HERO ==================== */}
      <section className="relative pt-36 pb-28 md:pt-52 md:pb-40 overflow-hidden">
        {/* Radial cyan glow */}
        <div
          className="absolute inset-0 opacity-70"
          style={{
            background:
              "radial-gradient(circle at 50% 30%, rgba(0,229,255,0.20) 0%, transparent 55%)",
          }}
        />
        {/* Subtle grid backdrop */}
        <div
          className="absolute inset-0 opacity-[0.15]"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px)",
            backgroundSize: "44px 44px",
            maskImage:
              "radial-gradient(ellipse 80% 60% at 50% 30%, black 40%, transparent 100%)",
          }}
        />

        <div className="relative max-w-6xl mx-auto px-6 md:px-10 text-center">
          <div
            className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full backdrop-blur-xl bg-white/[0.03] border border-white/10 text-[11px] uppercase tracking-[0.22em] mb-9 animate-in fade-in slide-in-from-bottom-2 duration-700"
            data-testid="hero-badge"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_8px_rgba(0,229,255,0.9)] animate-pulse" />
            <span className="text-zinc-300 font-semibold">No-login · Pay anonymously</span>
          </div>

          <h1
            className="font-display font-black text-5xl sm:text-6xl md:text-7xl lg:text-[92px] leading-[0.95] tracking-tighter mb-7 animate-in fade-in slide-in-from-bottom-4 duration-1000"
            data-testid="hero-title"
          >
            <span className="text-transparent bg-clip-text bg-gradient-to-b from-white via-white to-white/40">
              Growth done
            </span>
            <br />
            <span className="text-cyan-400 [text-shadow:0_0_40px_rgba(0,229,255,0.35)]">
              obnoxiously
            </span>
            <span className="text-transparent bg-clip-text bg-gradient-to-b from-white to-white/40">
              {" "}well.
            </span>
          </h1>

          <p className="text-base md:text-xl text-zinc-400 max-w-2xl mx-auto mb-11 leading-relaxed font-manrope animate-in fade-in slide-in-from-bottom-4 duration-1000 delay-100">
            The no-login control panel for boosting any account, anywhere — paid in crypto or with a
            gift-card coupon. Built for operators who hate friction.
          </p>

          <div className="flex flex-col sm:flex-row gap-3 justify-center items-center animate-in fade-in slide-in-from-bottom-4 duration-1000 delay-200">
            <button
              onClick={goCatalog}
              data-testid="hero-checkout-btn"
              className="group inline-flex items-center justify-center gap-2 px-8 py-4 rounded-full bg-cyan-400 hover:bg-cyan-300 text-black font-bold tracking-wide transition-all shadow-[0_0_30px_rgba(0,229,255,0.35)] hover:shadow-[0_0_45px_rgba(0,229,255,0.6)]"
            >
              Start an order
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </button>
            <a
              href="#services"
              data-testid="hero-browse-btn"
              className="inline-flex items-center justify-center gap-2 px-8 py-4 rounded-full backdrop-blur-xl bg-white/[0.03] border border-white/10 hover:border-white/25 hover:bg-white/[0.06] font-bold tracking-wide transition-all"
            >
              Browse catalog
            </a>
          </div>

          <div className="grid grid-cols-3 gap-6 md:gap-10 mt-20 max-w-2xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-1000 delay-300">
            <Stat label="Services" value={stats.services ? `${stats.services}+` : "1k+"} />
            <Stat label="Networks" value={stats.networks ? `${stats.networks}+` : "20+"} />
            <Stat label="Uptime" value="99.9%" />
          </div>
        </div>
      </section>

      {/* ==================== FEATURES — BENTO ==================== */}
      <section className="relative py-24 md:py-32 border-t border-white/5">
        <div className="max-w-7xl mx-auto px-6 md:px-10">
          <div className="max-w-2xl mb-14 md:mb-16">
            <div className="text-[11px] font-bold uppercase tracking-[0.28em] text-cyan-400 mb-4">
              Why Better
            </div>
            <h2 className="font-display text-3xl md:text-5xl font-black tracking-tight leading-tight">
              Everyone else makes you sign up.
              <br />
              <span className="text-transparent bg-clip-text bg-gradient-to-b from-white to-white/40">
                We just take the order.
              </span>
            </h2>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 md:gap-5">
            {FEATURES.map((f, i) => (
              <FeatureCard key={i} feature={f} index={i} />
            ))}
          </div>
        </div>
      </section>

      {/* ==================== HOW IT WORKS ==================== */}
      <section id="how" className="relative py-24 md:py-32 border-t border-white/5">
        <div
          className="absolute inset-0 opacity-40 pointer-events-none"
          style={{
            background:
              "radial-gradient(ellipse at 20% 50%, rgba(0,229,255,0.10) 0%, transparent 50%)",
          }}
        />
        <div className="relative max-w-7xl mx-auto px-6 md:px-10">
          <div className="max-w-2xl mb-14">
            <div className="text-[11px] font-bold uppercase tracking-[0.28em] text-cyan-400 mb-4">
              Workflow
            </div>
            <h2 className="font-display text-3xl md:text-5xl font-black tracking-tight leading-tight">
              Four steps. <span className="text-cyan-400">Zero</span> drama.
            </h2>
            <p className="text-zinc-400 mt-4 md:text-lg">
              The fastest path between "I want followers" and watching them appear.
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4 md:gap-5 relative">
            {STEPS.map((s, i) => (
              <div
                key={i}
                data-testid={`step-${s.n}`}
                className="group relative p-6 md:p-7 rounded-2xl bg-white/[0.02] border border-white/5 hover:border-cyan-500/30 hover:bg-white/[0.04] transition-all"
              >
                <div className="mb-5 w-11 h-11 rounded-full flex items-center justify-center bg-cyan-500/10 border border-cyan-500/40 shadow-[0_0_20px_rgba(0,229,255,0.15)] font-display font-black text-sm text-cyan-300">
                  {s.n}
                </div>
                <h3 className="font-display font-bold text-lg mb-2 text-white">{s.t}</h3>
                <p className="text-sm text-zinc-400 leading-relaxed">{s.d}</p>
                {i < STEPS.length - 1 && (
                  <div className="hidden lg:block absolute top-11 -right-3 w-6 h-px bg-gradient-to-r from-cyan-500/40 to-transparent" />
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ==================== LIVE SERVICES CATALOG ==================== */}
      <ServicesCatalog />

      {/* ==================== PAYMENTS ==================== */}
      <section className="relative py-24 md:py-32 border-t border-white/5">
        <div className="max-w-7xl mx-auto px-6 md:px-10">
          <div className="grid lg:grid-cols-2 gap-12 md:gap-16 items-center">
            <div>
              <div className="text-[11px] font-bold uppercase tracking-[0.28em] text-cyan-400 mb-4">
                Payments
              </div>
              <h2 className="font-display text-3xl md:text-5xl font-black tracking-tight leading-tight mb-6">
                Two ways to pay. <br />
                <span className="text-cyan-400">Both are private.</span>
              </h2>
              <div className="space-y-3">
                <div className="flex gap-4 p-5 rounded-2xl border border-white/5 bg-white/[0.02] hover:border-cyan-500/30 transition-all">
                  <div className="w-11 h-11 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center shrink-0">
                    <Coins className="w-5 h-5 text-cyan-300" strokeWidth={2.2} />
                  </div>
                  <div>
                    <div className="font-display font-bold mb-1 text-white">Crypto & Card</div>
                    <div className="text-sm text-zinc-400 leading-relaxed">
                      BTC · ETH · USDT · LTC + Visa / Mastercard via Selly and NOWPayments. Hosted
                      secure checkout. Auto-fulfil on confirmation.
                    </div>
                  </div>
                </div>
                <div className="flex gap-4 p-5 rounded-2xl border border-white/5 bg-white/[0.02] hover:border-cyan-500/30 transition-all">
                  <div className="w-11 h-11 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center shrink-0">
                    <Ticket className="w-5 h-5 text-cyan-300" strokeWidth={2.2} />
                  </div>
                  <div>
                    <div className="font-display font-bold mb-1 text-white">Better Social Coupon</div>
                    <div className="text-sm text-zinc-400 leading-relaxed">
                      Multi-use prepaid code. Use it across multiple orders until the balance hits
                      zero. Perfect for teams.
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Right — floating crypto chips */}
            <div className="relative aspect-square max-w-md mx-auto lg:max-w-none">
              <div className="absolute inset-0 rounded-3xl border border-white/5 bg-gradient-to-br from-white/[0.03] to-transparent backdrop-blur-sm overflow-hidden">
                <div
                  className="absolute inset-0 opacity-70"
                  style={{
                    background:
                      "radial-gradient(circle at 50% 50%, rgba(0,229,255,0.15) 0%, transparent 60%)",
                  }}
                />
                <div className="relative w-full h-full flex items-center justify-center p-8">
                  <div className="grid grid-cols-3 gap-3 md:gap-4">
                    {CRYPTO_METHODS.map((c, i) => (
                      <div
                        key={c}
                        className="aspect-square rounded-2xl border border-white/10 bg-black/40 backdrop-blur-sm flex items-center justify-center font-display font-black text-sm md:text-base text-zinc-300 hover:border-cyan-500/50 hover:text-cyan-300 hover:scale-105 transition-all"
                        style={{ animationDelay: `${i * 80}ms` }}
                      >
                        {c}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ==================== FAQ ==================== */}
      <section id="faq" className="relative py-24 md:py-32 border-t border-white/5">
        <div className="max-w-3xl mx-auto px-6 md:px-10">
          <div className="text-center mb-14">
            <div className="text-[11px] font-bold uppercase tracking-[0.28em] text-cyan-400 mb-4">
              FAQ
            </div>
            <h2 className="font-display text-3xl md:text-5xl font-black tracking-tighter">
              Quick answers.
            </h2>
          </div>
          <div className="divide-y divide-white/5 border-y border-white/5">
            {FAQ.map((f, i) => (
              <details
                key={i}
                data-testid={`faq-${i}`}
                className="group py-5 md:py-6"
              >
                <summary className="cursor-pointer flex items-center justify-between gap-4 font-display font-bold text-base md:text-lg text-white/90 hover:text-cyan-300 transition-colors">
                  {f.q}
                  <ChevronDown className="w-5 h-5 shrink-0 text-cyan-400 group-open:rotate-180 transition-transform" />
                </summary>
                <p className="text-sm md:text-base text-zinc-400 mt-3 leading-relaxed">{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* ==================== FOOTER ==================== */}
      <footer className="relative border-t border-white/10 pt-20 pb-8 overflow-hidden">
        <div
          className="absolute inset-0 opacity-40 pointer-events-none"
          style={{
            background:
              "radial-gradient(ellipse at 50% 100%, rgba(0,229,255,0.15) 0%, transparent 65%)",
          }}
        />
        <div className="relative max-w-7xl mx-auto px-6 md:px-10">
          <div className="text-center mb-14">
            <div className="font-display font-black text-6xl md:text-8xl lg:text-9xl tracking-tighter text-transparent bg-clip-text bg-gradient-to-b from-white/20 to-white/5 select-none">
              BETTER SOCIAL
            </div>
          </div>
          <div className="flex flex-col md:flex-row items-center justify-between gap-4 text-sm border-t border-white/5 pt-8">
            <div className="font-display font-black text-base text-white">
              Better<span className="text-cyan-400">Social</span>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-2 md:gap-4 text-[10px] uppercase tracking-widest text-zinc-500">
              <span className="inline-flex items-center gap-2 font-bold">
                <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
                © {new Date().getFullYear()} BetterSocial
              </span>
              <span className="text-white/20">·</span>
              <span>
                Development by <span className="text-cyan-300 font-bold">BK</span> &amp; CEO{" "}
                <span className="text-cyan-300 font-bold">Sinester</span>
              </span>
              <span className="text-white/20">·</span>
              <a
                href="mailto:balkinstr@web.de"
                data-testid="footer-contact"
                className="text-cyan-300 hover:text-white transition"
              >
                balkinstr@web.de
              </a>
            </div>
            <a
              href="/admin"
              className="text-[10px] uppercase tracking-widest font-bold text-zinc-500 hover:text-cyan-300 transition"
              data-testid="admin-link"
            >
              Admin →
            </a>
          </div>
        </div>
      </footer>

      {/* AI Widget + Floating Support FAB (Cyan glass) */}
      <AIWidget open={aiOpen} onOpenChange={setAiOpen} />
      {!aiOpen &&
        !(typeof window !== "undefined" && localStorage.getItem("bs_chat_banned") === "1") && (
          <button
            onClick={() => setAiOpen(true)}
            data-testid="ai-fab"
            aria-label="Open customer support"
            className="fixed bottom-16 right-5 md:bottom-16 md:right-6 z-50 group flex items-center gap-3"
          >
            <span
              className="hidden sm:inline-block px-3.5 py-2 rounded-full backdrop-blur-xl bg-black/60 border border-cyan-500/20 text-xs font-semibold text-white shadow-lg group-hover:border-cyan-500/50 group-hover:bg-black/80 transition-all"
              data-testid="ai-fab-label"
            >
              Need help? Customer support
            </span>
            <div className="relative">
              <span className="absolute inset-0 rounded-full bg-cyan-500/40 blur-2xl opacity-70 group-hover:opacity-100 transition animate-pulse" />
              <div className="relative w-14 h-14 md:w-16 md:h-16 rounded-full backdrop-blur-xl bg-cyan-500/25 border border-cyan-400/50 flex items-center justify-center shadow-[0_0_30px_rgba(0,229,255,0.4)] group-hover:scale-105 group-hover:bg-cyan-500/40 transition-all">
                <MessageCircle
                  className="w-6 h-6 md:w-7 md:h-7 text-cyan-100"
                  strokeWidth={2.2}
                />
              </div>
              <span className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 rounded-full bg-emerald-400 border-2 border-[#050505] animate-pulse shadow-[0_0_8px_rgba(52,211,153,0.9)]" />
            </div>
          </button>
        )}

      <OrderTicker />
    </div>
  );
}

/* ------------------- helper components ------------------- */

function Stat({ label, value }) {
  return (
    <div data-testid={`stat-${label.toLowerCase()}`} className="text-center md:text-left">
      <div className="font-display font-black text-3xl md:text-4xl text-white tracking-tight">
        {value}
      </div>
      <div className="text-[10px] uppercase tracking-[0.3em] text-zinc-500 mt-1.5 font-semibold">
        {label}
      </div>
    </div>
  );
}

function FeatureCard({ feature, index }) {
  const Icon = feature.icon;
  return (
    <div
      data-testid={`feature-card-${index}`}
      className={`group relative overflow-hidden rounded-2xl border border-white/5 hover:border-cyan-500/30 ${feature.accent} p-6 md:p-8 transition-all hover:-translate-y-1 duration-300 min-h-[220px] md:min-h-[260px] ${feature.span} col-span-1`}
    >
      {/* Ambient glow on hover */}
      <div
        className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"
        style={{
          background:
            "radial-gradient(circle at 30% 20%, rgba(0,229,255,0.10) 0%, transparent 60%)",
        }}
      />
      <div className="relative flex flex-col h-full">
        <div className="w-11 h-11 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center mb-5 shadow-[0_0_20px_rgba(0,229,255,0.15)] group-hover:scale-110 transition-transform">
          <Icon className="w-5 h-5 text-cyan-300" strokeWidth={2.2} />
        </div>
        <h3 className="font-display font-bold text-xl md:text-2xl text-white mb-2.5 tracking-tight">
          {feature.title}
        </h3>
        <p className="text-sm md:text-base text-zinc-400 leading-relaxed max-w-md">
          {feature.desc}
        </p>

        {feature.visual === "progress" && (
          <div className="mt-auto pt-6">
            <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-cyan-500 to-cyan-300 rounded-full animate-[fillBar_2.4s_ease-in-out_infinite]"
                style={{ width: "60%" }}
              />
            </div>
            <div className="text-[10px] uppercase tracking-widest text-cyan-400/70 mt-2 font-bold">
              Live · executing
            </div>
          </div>
        )}
        {feature.visual === "list" && (
          <div className="mt-auto pt-6 grid grid-cols-2 gap-1.5 text-[11px] font-mono text-zinc-500">
            {["Instagram", "TikTok", "YouTube", "Spotify", "X / Twitter", "Threads", "Twitch", "Discord"].map((s) => (
              <div key={s} className="truncate flex items-center gap-1.5">
                <span className="w-1 h-1 rounded-full bg-cyan-400/60" />
                {s}
              </div>
            ))}
          </div>
        )}
      </div>

      <style>{`
        @keyframes fillBar {
          0% { width: 5%; }
          70% { width: 95%; }
          100% { width: 100%; }
        }
      `}</style>
    </div>
  );
}
