import { useEffect, useState, useMemo } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { api } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  ArrowLeft,
  Loader2,
  Ticket,
  Bitcoin,
  Sparkles,
  ShieldCheck,
  Zap,
  Clock,
} from "lucide-react";
import Swal from "sweetalert2";

export default function OrderPage() {
  const { serviceId } = useParams();
  const navigate = useNavigate();
  const [service, setService] = useState(null);
  const [loading, setLoading] = useState(true);
  const [link, setLink] = useState("");
  const [qty, setQty] = useState(0);
  const [email, setEmail] = useState("");
  const [method, setMethod] = useState("coupon");
  const [coupon, setCoupon] = useState("");
  const [couponInfo, setCouponInfo] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api
      .get("/services")
      .then((r) => {
        const list = Array.isArray(r.data.services) ? r.data.services : [];
        const found = list.find((s) => String(s.service) === String(serviceId));
        setService(found || null);
        if (found) setQty(Number(found.min || 1000));
      })
      .finally(() => setLoading(false));
  }, [serviceId]);

  const price = useMemo(() => {
    if (!service || !qty) return 0;
    return (parseFloat(service.rate || 0) * Number(qty)) / 1000;
  }, [service, qty]);

  const validQty =
    service && qty >= Number(service.min || 0) && qty <= Number(service.max || 1e12);

  const checkCoupon = async () => {
    try {
      const r = await api.post("/coupon/check", { code: coupon });
      setCouponInfo(r.data);
    } catch (e) {
      setCouponInfo({ error: e.response?.data?.detail || "Invalid coupon" });
    }
  };

  const submit = async () => {
    if (!service || !link || !validQty || !email.trim() || !/.+@.+\..+/.test(email)) return;
    setSubmitting(true);
    try {
      const r = await api.post("/checkout", {
        service_id: Number(service.service),
        link,
        quantity: Number(qty),
        payment_method: method,
        coupon_code: method === "coupon" ? coupon : null,
        customer_email: email,
        price_usd: Number(price.toFixed(4)),
      });
      if (r.data.status === "success") {
        Swal.fire({
          title: "Order Placed!",
          html: `<div style="font-family:'IBM Plex Sans'">Your SMM order has been submitted.<br/><br/><b style="color:#FF007F">SMM Order ID: ${r.data.smm_order_id || "—"}</b></div>`,
          icon: "success",
          iconColor: "#00E5FF",
          background: "#1a1525",
          color: "#fff",
          confirmButtonText: "View status",
          customClass: { popup: "bs-swal" },
        }).then(() => navigate(`/status/${r.data.order_id}`));
      } else if (r.data.status === "pending" && r.data.checkout_url) {
        // Cryptomus — redirect to payment page, then come back to status
        sessionStorage.setItem("bs_pending_order", r.data.order_id);
        window.location.href = r.data.checkout_url;
      }
    } catch (e) {
      Swal.fire({
        title: "Order Failed",
        text: e.response?.data?.detail || "Something went wrong",
        icon: "error",
        background: "#1a1525",
        color: "#fff",
        confirmButtonText: "Close",
        customClass: { popup: "bs-swal" },
      });
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-white/40">
        <Loader2 className="w-6 h-6 animate-spin" />
      </div>
    );
  }
  if (!service) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center px-6 text-center">
        <h1 className="font-display text-3xl font-black mb-3">Service not available</h1>
        <p className="text-white/50 text-sm mb-6">This service isn't live right now.</p>
        <Link to="/" className="px-6 py-3 gradient-pp rounded-sm font-bold" data-testid="back-home">
          Back to catalog
        </Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#050505] text-white">
      {/* Header */}
      <header className="border-b border-white/5 bg-[#050505]/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 md:px-10 h-14 md:h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2" data-testid="brand-logo">
            <div className="w-7 h-7 rounded-sm gradient-pp flex items-center justify-center">
              <Sparkles className="w-3.5 h-3.5" strokeWidth={2.5} />
            </div>
            <span className="font-display font-black text-base">
              Better<span className="text-[#FF007F]">Social</span>
            </span>
          </Link>
          <Link
            to="/"
            data-testid="back-to-catalog"
            className="text-xs uppercase tracking-wider text-white/60 hover:text-white flex items-center gap-1"
          >
            <ArrowLeft className="w-3 h-3" /> Catalog
          </Link>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 md:px-10 py-8 md:py-14">
        <div className="grid lg:grid-cols-[1.2fr_1fr] gap-6 md:gap-10">
          {/* LEFT: Service info */}
          <div>
            <div className="mb-5">
              <div className="text-xs uppercase tracking-[0.2em] text-[#00E5FF] mb-2">
                {service.category}
              </div>
              <h1 className="font-display text-2xl md:text-4xl font-black leading-tight tracking-tight mb-3">
                {service.name}
              </h1>
              <div className="inline-flex items-baseline gap-2 bg-[#1a1525] px-4 py-2 rounded-sm border border-white/5">
                <span className="font-display font-black text-3xl gradient-text">
                  ${Number(service.rate).toFixed(3)}
                </span>
                <span className="text-xs uppercase tracking-wider text-white/50">per 1,000</span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 mb-6">
              <InfoTile label="Min Qty" value={service.min} />
              <InfoTile label="Max Qty" value={service.max} />
              <InfoTile label="Service ID" value={`#${service.service}`} />
              <InfoTile label="Type" value={service.type || "Default"} />
            </div>

            <div className="space-y-3">
              <Feature icon={Zap} text="Instant start — most orders begin within minutes of payment." />
              <Feature icon={ShieldCheck} text="No login required. Your link & email stay private." />
              <Feature icon={Clock} text="Non-drop delivery with automatic refill where available." />
            </div>
          </div>

          {/* RIGHT: Order form */}
          <aside className="lg:sticky lg:top-24 h-fit">
            <div className="bg-[#0d0a14] border border-white/10 rounded-sm p-5 md:p-6 space-y-4">
              <div className="text-xs uppercase tracking-[0.2em] text-[#FF007F] mb-1">New Order</div>
              <h2 className="font-display text-xl font-black mb-2">Place your order</h2>

              <div>
                <Label className="text-[11px] uppercase tracking-wider text-white/60">
                  Link / Username
                </Label>
                <Input
                  data-testid="order-link"
                  placeholder="https://instagram.com/username"
                  value={link}
                  onChange={(e) => setLink(e.target.value)}
                  className="bg-[#1a1525] border-white/10 mt-1"
                />
              </div>

              <div>
                <Label className="text-[11px] uppercase tracking-wider text-white/60">
                  Quantity
                </Label>
                <Input
                  data-testid="order-qty"
                  type="number"
                  min={service.min}
                  max={service.max}
                  value={qty}
                  onChange={(e) => setQty(e.target.value)}
                  className="bg-[#1a1525] border-white/10 mt-1 font-mono"
                />
                {!validQty && qty ? (
                  <div className="text-[10px] text-[#FF3B30] mt-1">
                    Must be between {service.min} and {service.max}
                  </div>
                ) : null}
              </div>

              <div>
                <Label className="text-[11px] uppercase tracking-wider text-white/60">
                  Email <span className="text-[#FF007F]">*</span>
                </Label>
                <Input
                  data-testid="order-email"
                  type="email"
                  required
                  placeholder="you@email.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="bg-[#1a1525] border-white/10 mt-1"
                />
                <p className="text-[10px] text-white/40 mt-1">
                  Required — we use it only to send your order confirmation.
                </p>
              </div>

              <Tabs value={method} onValueChange={setMethod} className="w-full">
                <TabsList className="grid grid-cols-2 bg-[#1a1525] rounded-sm">
                  <TabsTrigger
                    value="coupon"
                    data-testid="pay-coupon"
                    className="data-[state=active]:bg-[#FF007F] data-[state=active]:text-white rounded-sm"
                  >
                    <Ticket className="w-4 h-4 mr-2" /> Coupon
                  </TabsTrigger>
                  <TabsTrigger
                    value="cryptomus"
                    data-testid="pay-cryptomus"
                    className="data-[state=active]:bg-[#7000FF] data-[state=active]:text-white rounded-sm"
                  >
                    <Bitcoin className="w-4 h-4 mr-2" /> Crypto
                  </TabsTrigger>
                </TabsList>
                <TabsContent value="coupon" className="space-y-2 mt-3">
                  <div className="flex gap-2">
                    <Input
                      data-testid="order-coupon"
                      placeholder="BS-XXXX-XXXX-XXXX"
                      value={coupon}
                      onChange={(e) => setCoupon(e.target.value.toUpperCase())}
                      className="bg-[#1a1525] border-white/10 font-mono"
                    />
                    <button
                      onClick={checkCoupon}
                      data-testid="order-check-coupon"
                      className="px-4 bg-white/10 hover:bg-white/20 rounded-sm text-xs font-bold uppercase tracking-wider"
                    >
                      Check
                    </button>
                  </div>
                  {couponInfo && !couponInfo.error && (
                    <div className="text-xs text-[#00E5FF]">
                      Balance: ${Number(couponInfo.balance).toFixed(2)}
                    </div>
                  )}
                  {couponInfo?.error && (
                    <div className="text-xs text-[#FF3B30]">{couponInfo.error}</div>
                  )}
                </TabsContent>
                <TabsContent value="cryptomus" className="mt-3">
                  <p className="text-xs text-white/50 leading-relaxed">
                    Pay with BTC, ETH, USDT, LTC and 40+ coins via Cryptomus. Order auto-fulfils
                    once payment is confirmed on-chain.
                  </p>
                </TabsContent>
              </Tabs>

              <div className="border-t border-white/5 pt-4">
                <div className="flex justify-between items-baseline mb-3">
                  <span className="text-xs uppercase tracking-[0.2em] text-white/50">Total</span>
                  <span
                    className="font-display text-3xl gradient-text"
                    data-testid="order-total"
                  >
                    ${price.toFixed(2)}
                  </span>
                </div>
                <button
                  onClick={submit}
                  disabled={
                    submitting ||
                    !validQty ||
                    !link ||
                    !email.trim() ||
                    !/.+@.+\..+/.test(email) ||
                    (method === "coupon" && !coupon)
                  }
                  data-testid="order-submit"
                  className="w-full py-3.5 gradient-pp rounded-sm font-bold tracking-wide disabled:opacity-40 hover:opacity-90 transition glow-purple"
                >
                  {submitting ? (
                    <Loader2 className="w-4 h-4 animate-spin mx-auto" />
                  ) : method === "cryptomus" ? (
                    `Pay with crypto · $${price.toFixed(2)}`
                  ) : (
                    `Place order · $${price.toFixed(2)}`
                  )}
                </button>
              </div>
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}

function InfoTile({ label, value }) {
  return (
    <div className="p-3 rounded-sm bg-[#1a1525] border border-white/5">
      <div className="text-[10px] uppercase tracking-wider text-white/40">{label}</div>
      <div className="font-mono font-bold text-sm mt-0.5">{value}</div>
    </div>
  );
}

function Feature({ icon: Icon, text }) {
  return (
    <div className="flex items-start gap-3 text-sm text-white/60">
      <Icon className="w-4 h-4 text-[#FF007F] shrink-0 mt-0.5" />
      <span>{text}</span>
    </div>
  );
}
