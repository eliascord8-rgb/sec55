import { useState, useEffect } from "react";
import Header from "@/components/Header";
import ServicesCatalog from "@/components/ServicesCatalog";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Zap, Shield, Coins, Rocket, Ticket } from "lucide-react";
import { api } from "@/lib/api";

const HERO_BG = "https://images.pexels.com/photos/31032752/pexels-photo-31032752.jpeg";

const FEATURES = [
  {
    icon: Zap,
    title: "Instant Delivery",
    desc: "Most orders kick off within minutes of confirmation. No waiting, no babysitting.",
  },
  {
    icon: Coins,
    title: "Crypto + Coupon",
    desc: "Pay via CoinPayments (BTC, ETH, USDT…) or redeem a Better Social gift card. Zero login.",
  },
  {
    icon: Shield,
    title: "Anonymous Checkout",
    desc: "No account, no email mandatory. Just paste, pay, and watch the numbers go up.",
  },
  {
    icon: Rocket,
    title: "1,000+ Services",
    desc: "Instagram, TikTok, YouTube, Spotify, X, and far beyond — sourced from premium providers.",
  },
];

const STEPS = [
  { n: "01", t: "Pick a service", d: "Browse the live catalog. Filter by network, sort by price." },
  { n: "02", t: "Drop the link", d: "Public profile or post URL. Set the quantity you want." },
  { n: "03", t: "Pay your way", d: "Crypto via CoinPayments or a Better Social coupon balance." },
  { n: "04", t: "Watch it flow", d: "Order is auto-pushed to providers and starts in real time." },
];

const FAQ = [
  {
    q: "Do I need an account?",
    a: "No. Better Social is fully no-login. Pay, place, done.",
  },
  {
    q: "What's a Better Social coupon?",
    a: "It's a prepaid balance code we issue. Bring it to checkout and it deducts the order total from your remaining balance — multi-use until depleted.",
  },
  {
    q: "Which cryptos are accepted?",
    a: "Anything CoinPayments supports — BTC, ETH, USDT, LTC, DOGE, BCH and 40+ more.",
  },
  {
    q: "When does my order start?",
    a: "Coupon orders are submitted instantly. Crypto orders submit the moment the network confirms your payment.",
  },
];

export default function Landing() {
  const [stats, setStats] = useState({ services: 0, networks: 0 });
  const navigate = useNavigate();

  useEffect(() => {
    api
      .get("/services")
      .then((r) => {
        const list = Array.isArray(r.data.services) ? r.data.services : [];
        const networks = new Set(list.map((s) => s.category)).size;
        setStats({ services: list.length, networks });
      })
      .catch(() => {});
  }, []);

  const goCatalog = () => {
    const el = document.getElementById("services");
    if (el) el.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="relative bg-[#050505] text-white">
      <Header onCheckout={goCatalog} />

      {/* HERO */}
      <section className="relative pt-32 pb-24 md:pt-44 md:pb-40 overflow-hidden grain">
        <div
          className="absolute inset-0 opacity-40"
          style={{
            backgroundImage: `url(${HERO_BG})`,
            backgroundSize: "cover",
            backgroundPosition: "center",
          }}
        />
        <div className="absolute inset-0 bg-gradient-to-b from-[#050505]/30 via-[#050505]/70 to-[#050505]" />
        <div
          className="absolute -top-40 -right-40 w-[600px] h-[600px] rounded-full opacity-50 blur-[120px]"
          style={{ background: "radial-gradient(circle, #FF007F 0%, transparent 60%)" }}
        />
        <div
          className="absolute -bottom-40 -left-40 w-[600px] h-[600px] rounded-full opacity-40 blur-[120px]"
          style={{ background: "radial-gradient(circle, #7000FF 0%, transparent 60%)" }}
        />

        <div className="relative max-w-7xl mx-auto px-6 md:px-10">
          <div className="max-w-3xl">
            <div
              className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass text-xs uppercase tracking-[0.2em] mb-8"
              data-testid="hero-badge"
            >
              <span className="w-2 h-2 rounded-full bg-[#00E5FF] animate-pulse" />
              No-login · Pay anonymously
            </div>

            <h1
              className="font-display text-5xl sm:text-6xl lg:text-7xl font-black leading-[0.95] tracking-tighter mb-6"
              data-testid="hero-title"
            >
              SMM done <span className="gradient-text">obnoxiously</span>
              <br />
              well.
            </h1>
            <p className="text-lg md:text-xl text-white/60 max-w-2xl mb-10 leading-relaxed">
              Better Social is the no-login control panel for boosting any account, anywhere, paid in crypto or
              with a gift-card coupon. Built for operators who hate friction.
            </p>

            <div className="flex flex-col sm:flex-row gap-3">
              <button
                onClick={goCatalog}
                data-testid="hero-checkout-btn"
                className="group inline-flex items-center justify-center gap-2 px-8 py-4 gradient-pp rounded-sm font-bold tracking-wide hover:opacity-90 transition glow-purple"
              >
                Start an order
                <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition" />
              </button>
              <a
                href="#services"
                className="inline-flex items-center justify-center gap-2 px-8 py-4 border border-white/15 rounded-sm font-bold tracking-wide hover:bg-white/5 transition"
                data-testid="hero-browse-btn"
              >
                Browse catalog
              </a>
            </div>

            <div className="grid grid-cols-3 gap-8 mt-16 max-w-xl">
              <Stat label="Services" value={stats.services || "1k+"} />
              <Stat label="Networks" value={stats.networks || "20+"} />
              <Stat label="Uptime" value="99.9%" />
            </div>
          </div>
        </div>
      </section>

      {/* FEATURES */}
      <section className="py-24 md:py-32 border-t border-white/5 relative">
        <div className="max-w-7xl mx-auto px-6 md:px-10">
          <div className="max-w-2xl mb-16">
            <div className="text-xs uppercase tracking-[0.3em] text-[#FF007F] mb-4">Why Better</div>
            <h2 className="font-display text-3xl md:text-5xl font-black tracking-tight">
              Everyone else makes you sign up.
              <br />
              <span className="gradient-text">We just take the order.</span>
            </h2>
          </div>

          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {FEATURES.map((f, i) => (
              <div
                key={i}
                data-testid={`feature-card-${i}`}
                className="glass p-8 rounded-sm hover:border-[#FF007F]/40 transition group"
              >
                <f.icon className="w-7 h-7 text-[#FF007F] mb-5 group-hover:scale-110 transition" />
                <h3 className="font-display font-bold text-lg mb-2">{f.title}</h3>
                <p className="text-sm text-white/50 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section id="how" className="py-24 md:py-32 border-t border-white/5 bg-[#0d0a14] relative">
        <div className="max-w-7xl mx-auto px-6 md:px-10">
          <div className="grid md:grid-cols-[1fr_2fr] gap-12">
            <div>
              <div className="text-xs uppercase tracking-[0.3em] text-[#00E5FF] mb-4">Workflow</div>
              <h2 className="font-display text-3xl md:text-5xl font-black tracking-tight mb-4">
                4 steps. <br />
                <span className="text-[#FF007F]">Zero</span> drama.
              </h2>
              <p className="text-white/50 text-sm">
                The fastest path between "I want followers" and watching them appear.
              </p>
            </div>
            <div className="space-y-3">
              {STEPS.map((s, i) => (
                <div
                  key={i}
                  data-testid={`step-${s.n}`}
                  className="flex items-start gap-6 p-6 rounded-sm bg-[#1a1525] border border-white/5 hover:border-[#7000FF]/40 transition"
                >
                  <div className="font-display font-black text-3xl gradient-text shrink-0">{s.n}</div>
                  <div>
                    <h3 className="font-bold text-lg mb-1">{s.t}</h3>
                    <p className="text-sm text-white/50">{s.d}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* LIVE SERVICES CATALOG */}
      <ServicesCatalog />

      {/* PAYMENT */}
      <section className="py-24 md:py-32 border-t border-white/5 bg-[#0d0a14]">
        <div className="max-w-7xl mx-auto px-6 md:px-10 grid md:grid-cols-2 gap-12 items-center">
          <div>
            <div className="text-xs uppercase tracking-[0.3em] text-[#FF007F] mb-4">Payments</div>
            <h2 className="font-display text-3xl md:text-5xl font-black tracking-tight mb-6">
              Two ways to pay. <br />
              <span className="gradient-text">Both are private.</span>
            </h2>
            <div className="space-y-4">
              <div className="flex gap-4 p-5 rounded-sm border border-white/5 bg-[#1a1525]">
                <Coins className="w-6 h-6 text-[#FF007F] shrink-0 mt-1" />
                <div>
                  <div className="font-bold mb-1">CoinPayments</div>
                  <div className="text-sm text-white/50">
                    BTC, ETH, USDT, LTC, DOGE… 40+ assets. Auto-fulfil on confirmation.
                  </div>
                </div>
              </div>
              <div className="flex gap-4 p-5 rounded-sm border border-white/5 bg-[#1a1525]">
                <Ticket className="w-6 h-6 text-[#7000FF] shrink-0 mt-1" />
                <div>
                  <div className="font-bold mb-1">Better Social Coupon</div>
                  <div className="text-sm text-white/50">
                    Multi-use prepaid code. Use it across multiple orders until the balance hits zero.
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div className="relative aspect-square rounded-sm overflow-hidden glass p-1">
            <div
              className="absolute inset-0 opacity-60"
              style={{
                backgroundImage: `url(https://images.pexels.com/photos/14832157/pexels-photo-14832157.jpeg)`,
                backgroundSize: "cover",
                backgroundPosition: "center",
              }}
            />
            <div className="absolute inset-0 bg-gradient-to-tr from-[#FF007F]/30 via-transparent to-[#7000FF]/40" />
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="py-24 md:py-32 border-t border-white/5">
        <div className="max-w-4xl mx-auto px-6 md:px-10">
          <div className="text-xs uppercase tracking-[0.3em] text-[#00E5FF] mb-4 text-center">FAQ</div>
          <h2 className="font-display text-3xl md:text-5xl font-black tracking-tighter mb-12 text-center">
            Quick answers.
          </h2>
          <div className="space-y-3">
            {FAQ.map((f, i) => (
              <details
                key={i}
                data-testid={`faq-${i}`}
                className="group p-6 rounded-sm border border-white/5 bg-[#0d0a14] open:border-[#FF007F]/40 transition"
              >
                <summary className="cursor-pointer font-bold flex items-center justify-between">
                  {f.q}
                  <span className="text-[#FF007F] group-open:rotate-45 transition text-2xl leading-none">+</span>
                </summary>
                <p className="text-sm text-white/55 mt-3 leading-relaxed">{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="border-t border-white/5 py-12">
        <div className="max-w-7xl mx-auto px-6 md:px-10 flex flex-col md:flex-row items-center justify-between gap-6 text-sm text-white/40">
          <div className="font-display font-black text-base text-white">
            Better<span className="text-[#FF007F]">Social</span>
          </div>
          <div className="flex flex-col md:flex-row items-center gap-3 md:gap-6 text-center">
            <div className="text-xs uppercase tracking-[0.2em]">
              © {new Date().getFullYear()} · No-login SMM
            </div>
            <a
              href="mailto:balkinstr@web.de"
              data-testid="footer-contact"
              className="text-xs uppercase tracking-[0.2em] text-[#FF007F] hover:text-white transition"
            >
              Contact 24/7 · balkinstr@web.de
            </a>
          </div>
          <a href="/admin" className="text-xs uppercase tracking-[0.2em] hover:text-white" data-testid="admin-link">
            Admin →
          </a>
        </div>
      </footer>

      <CheckoutDialogReplaced />
    </div>
  );
}

function CheckoutDialogReplaced() {
  return null;
}

function Stat({ label, value }) {
  return (
    <div data-testid={`stat-${label.toLowerCase()}`}>
      <div className="font-display text-3xl font-black gradient-text">{value}</div>
      <div className="text-[10px] uppercase tracking-[0.3em] text-white/40 mt-1">{label}</div>
    </div>
  );
}
