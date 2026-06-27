import { useEffect, useState, useMemo } from "react";
import { api } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Loader2, Search, ShoppingCart, Ticket, Bitcoin, Copy, ExternalLink } from "lucide-react";
import Swal from "sweetalert2";

const fmt = (n) => `$${Number(n).toFixed(2)}`;

const formatDelivery = (mins) => {
  const m = Number(mins) || 0;
  if (m < 60) return `${m} min`;
  if (m < 60 * 24) return `${(m / 60).toFixed(m % 60 ? 1 : 0)} h`;
  return `${(m / 60 / 24).toFixed(m % (60 * 24) ? 1 : 0)} d`;
};

export default function CheckoutDialog({ open, onOpenChange, initialService }) {
  const [services, setServices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");
  const [selected, setSelected] = useState(null);
  const [link, setLink] = useState("");
  const [qty, setQty] = useState(0);
  const [email, setEmail] = useState("");
  const [coupon, setCoupon] = useState("");
  const [couponInfo, setCouponInfo] = useState(null);
  const [method, setMethod] = useState("coupon");
  const [submitting, setSubmitting] = useState(false);
  const [pendingTx, setPendingTx] = useState(null);
  const [comments, setComments] = useState("");
  const [sellyGateway, setSellyGateway] = useState("bitcoin");

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api
      .get("/services")
      .then((r) => setServices(Array.isArray(r.data.services) ? r.data.services : []))
      .catch(() => setServices([]))
      .finally(() => setLoading(false));
  }, [open]);

  useEffect(() => {
    if (initialService) {
      setSelected(initialService);
      setQty(initialService.manual ? 1 : (initialService.min ? Number(initialService.min) : 1000));
    }
  }, [initialService]);

  const categories = useMemo(() => {
    const set = new Set(["All"]);
    services.forEach((s) => s.category && set.add(s.category));
    return Array.from(set);
  }, [services]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return services
      .filter((s) => (category === "All" ? true : s.category === category))
      .filter((s) => (q ? `${s.name} ${s.category}`.toLowerCase().includes(q) : true))
      .slice(0, 80);
  }, [services, search, category]);

  const price = useMemo(() => {
    if (!selected) return 0;
    if (selected.manual) {
      return Number(selected.price_flat || selected.rate || 0);
    }
    if (!qty) return 0;
    const rate = parseFloat(selected.rate || 0);
    return (rate * Number(qty)) / 1000;
  }, [selected, qty]);

  const validQty = !selected
    ? false
    : selected.manual
      ? true
      : qty >= Number(selected.min || 0) && qty <= Number(selected.max || 1e12);

  const checkCoupon = async () => {
    try {
      const r = await api.post("/coupon/check", { code: coupon });
      setCouponInfo(r.data);
    } catch (e) {
      setCouponInfo({ error: e.response?.data?.detail || "Invalid coupon" });
    }
  };

  const showSuccess = (smmId) => {
    Swal.fire({
      title: "Order Placed!",
      html: `<div style="font-family:'IBM Plex Sans'">Your order has been submitted.<br/><br/><b style="color:#FF007F">Order ID: ${smmId || "—"}</b></div>`,
      icon: "success",
      iconColor: "#00E5FF",
      background: "#1a1525",
      color: "#fff",
      confirmButtonText: "Done",
      customClass: { popup: "bs-swal" },
    }).then(() => {
      onOpenChange(false);
      reset();
    });
  };

  const reset = () => {
    setSelected(null);
    setLink("");
    setQty(0);
    setEmail("");
    setCoupon("");
    setCouponInfo(null);
    setPendingTx(null);
  };

  const submit = async () => {
    if (!selected || !link || !validQty) return;
    if (selected.needs_custom_text && !comments.trim()) {
      Swal.fire({
        title: "Comments required",
        text: "This service needs custom comments — please enter your comment text first.",
        icon: "warning",
        background: "#1a1525",
        color: "#fff",
        confirmButtonText: "OK",
        customClass: { popup: "bs-swal" },
      });
      return;
    }
    setSubmitting(true);
    try {
      // Selly = hosted checkout: create payment-request, redirect to Selly's URL
      if (method === "selly") {
        const sr = await api.post("/checkout/selly-create", {
          service_id: Number(selected.service),
          link,
          quantity: Number(qty),
          customer_email: email || "",
          price_usd: Number(price.toFixed(4)),
          comments: selected.needs_custom_text ? comments.trim() : null,
          gateway: sellyGateway,
        });
        if (sr.data.checkout_url) {
          window.location.href = sr.data.checkout_url;
          return;
        }
      }
      const r = await api.post("/checkout", {
        service_id: Number(selected.service),
        link,
        quantity: Number(qty),
        payment_method: method,
        coupon_code: method === "coupon" ? coupon : null,
        customer_email: email || null,
        price_usd: Number(price.toFixed(4)),
        comments: selected.needs_custom_text ? comments.trim() : null,
      });
      if (r.data.status === "success") {
        showSuccess(r.data.smm_order_id);
      } else if (r.data.status === "pending") {
        setPendingTx(r.data);
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

  const checkPayment = async () => {
    if (!pendingTx) return;
    setSubmitting(true);
    try {
      const r = await api.post("/coinpayments/check", { order_id: pendingTx.order_id });
      if (r.data.status === "completed") {
        showSuccess(r.data.smm_order_id);
      } else {
        Swal.fire({
          title: "Still Pending",
          text: r.data.status_text || "Waiting for blockchain confirmations.",
          icon: "info",
          background: "#1a1525",
          color: "#fff",
          customClass: { popup: "bs-swal" },
        });
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="checkout-dialog"
        className="max-w-5xl max-h-[90vh] overflow-y-auto bg-[#0d0a14] border border-white/10 text-white p-0"
      >
        <DialogHeader className="px-8 pt-8 pb-4 border-b border-white/5">
          <DialogTitle className="font-display text-2xl tracking-tight">
            <span className="gradient-text">Checkout</span> · No login required
          </DialogTitle>
        </DialogHeader>

        <div className="grid md:grid-cols-[1.4fr_1fr] gap-0 min-h-[60vh]">
          {/* LEFT: Services list */}
          <div className="p-6 md:p-8 border-r border-white/5">
            <div className="flex items-center gap-3 mb-4">
              <div className="flex-1 relative">
                <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-white/40" />
                <Input
                  data-testid="services-search"
                  placeholder="Search services… (Instagram, TikTok, YouTube)"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-9 bg-[#1a1525] border-white/10 text-white placeholder:text-white/30"
                />
              </div>
            </div>

            <div className="flex gap-2 overflow-x-auto pb-3 mb-3 scrollbar-thin">
              {categories.slice(0, 14).map((c) => (
                <button
                  key={c}
                  onClick={() => setCategory(c)}
                  data-testid={`category-${c}`}
                  className={`px-3 py-1 text-xs uppercase tracking-wider rounded-sm whitespace-nowrap transition ${
                    category === c
                      ? "bg-[#FF007F] text-white font-bold"
                      : "bg-white/5 text-white/60 hover:bg-white/10"
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>

            <div className="space-y-2 max-h-[55vh] overflow-y-auto pr-2">
              {loading && (
                <div className="flex items-center justify-center py-12 text-white/40">
                  <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading services…
                </div>
              )}
              {!loading && filtered.length === 0 && (
                <div className="text-center text-white/40 py-12 text-sm">No services found.</div>
              )}
              {filtered.map((s) => (
                <button
                  key={s.service}
                  data-testid={`service-${s.service}`}
                  onClick={() => {
                    setSelected(s);
                    setQty(s.manual ? 1 : Number(s.min || 1000));
                  }}
                  className={`w-full text-left p-4 rounded-sm border transition group ${
                    selected?.service === s.service
                      ? "border-[#FF007F] bg-[#FF007F]/10"
                      : "border-white/5 bg-white/[0.02] hover:border-white/20"
                  }`}
                >
                  <div className="flex justify-between items-start gap-4">
                    <div className="min-w-0">
                      <div className="text-xs text-[#00E5FF] uppercase tracking-wider mb-1">
                        {s.category || "—"}
                      </div>
                      <div className="text-sm font-medium truncate">{s.name}</div>
                      <div className="text-[10px] font-mono text-white/40 mt-1">
                        Min: {s.min} · Max: {s.max} · ID #{s.service}
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className="font-mono text-sm text-white">${Number(s.rate).toFixed(3)}</div>
                      <div className="text-[10px] text-white/40 uppercase">per 1k</div>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* RIGHT: Order form */}
          <div className="p-6 md:p-8 bg-[#050505]">
            {!selected ? (
              <div className="h-full flex flex-col items-center justify-center text-center text-white/40 py-16">
                <ShoppingCart className="w-12 h-12 mb-4 text-white/20" />
                <p className="text-sm">Pick a service to start ordering.</p>
              </div>
            ) : pendingTx ? (
              <div className="space-y-4">
                <div className="text-xs uppercase tracking-[0.2em] text-[#00E5FF]">Crypto Payment</div>
                <h3 className="font-display text-xl">Send {pendingTx.amount} BTC</h3>
                <div className="glass p-4 rounded-sm">
                  <div className="text-[11px] uppercase tracking-wider text-white/50 mb-1">Address</div>
                  <div className="font-mono text-xs break-all">{pendingTx.address}</div>
                  <button
                    onClick={() => navigator.clipboard.writeText(pendingTx.address)}
                    className="mt-2 inline-flex items-center gap-1 text-xs text-[#FF007F]"
                    data-testid="copy-address-btn"
                  >
                    <Copy className="w-3 h-3" /> Copy
                  </button>
                </div>
                {pendingTx.qrcode_url && (
                  <img src={pendingTx.qrcode_url} alt="QR" className="w-40 h-40 bg-white p-2 rounded-sm" />
                )}
                <a
                  href={pendingTx.checkout_url}
                  target="_blank"
                  rel="noreferrer"
                  data-testid="open-checkout-link"
                  className="inline-flex items-center gap-1 text-sm text-[#00E5FF] underline"
                >
                  Open CoinPayments page <ExternalLink className="w-3 h-3" />
                </a>
                <button
                  onClick={checkPayment}
                  disabled={submitting}
                  data-testid="check-payment-btn"
                  className="w-full py-3 gradient-pp rounded-sm font-bold tracking-wide disabled:opacity-50"
                >
                  {submitting ? "Checking…" : "I've paid — Check & fulfill"}
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                <div>
                  <div className="text-xs uppercase tracking-[0.2em] text-[#FF007F] mb-1">Selected</div>
                  <div className="text-sm font-medium" data-testid="selected-service-name">{selected.name}</div>
                  <div className="text-[11px] text-white/40 font-mono">
                    {selected.manual
                      ? `Flat $${Number(selected.price_flat || selected.rate || 0).toFixed(2)}`
                      : `Rate $${Number(selected.rate).toFixed(3)}/1k · Min ${selected.min} · Max ${selected.max}`}
                  </div>
                  {selected.delivery_minutes ? (
                    <div className="text-[11px] text-emerald-400 mt-1 font-medium">
                      ⚡ Delivery ~{formatDelivery(selected.delivery_minutes)}
                    </div>
                  ) : null}
                  {selected.description ? (
                    <p className="text-[11px] text-white/60 mt-2 leading-relaxed bg-[#0d0a14] rounded-sm p-2 border border-white/5">
                      {selected.description}
                    </p>
                  ) : null}
                </div>

                <div>
                  <Label className="text-[11px] uppercase tracking-wider text-white/60">
                    {selected.manual ? "Notes / Details for us" : "Link / Username"}
                  </Label>
                  <Input
                    data-testid="link-input"
                    placeholder={selected.manual ? "Anything we need to know (URL, brief, account, etc.)" : "https://instagram.com/username"}
                    value={link}
                    onChange={(e) => setLink(e.target.value)}
                    className="bg-[#1a1525] border-white/10 mt-1"
                  />
                </div>

                {!selected.manual && (
                  <div>
                    <Label className="text-[11px] uppercase tracking-wider text-white/60">Quantity</Label>
                    <Input
                      data-testid="qty-input"
                      type="number"
                      min={selected.min}
                      max={selected.max}
                      value={qty}
                      onChange={(e) => setQty(e.target.value)}
                      className="bg-[#1a1525] border-white/10 mt-1 font-mono"
                    />
                  </div>
                )}

                <div>
                  <Label className="text-[11px] uppercase tracking-wider text-white/60">Email (optional)</Label>
                  <Input
                    data-testid="email-input"
                    placeholder="you@email.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="bg-[#1a1525] border-white/10 mt-1"
                  />
                </div>

                {selected.needs_custom_text && (
                  <div data-testid="checkout-comments-block" className="bg-amber-500/10 border border-amber-500/40 rounded-sm p-3 space-y-2">
                    <div className="text-[10px] uppercase tracking-wider text-amber-300 font-bold">
                      Custom comments required
                    </div>
                    <Label className="text-[11px] text-white/70">
                      Enter the comment text — one per line. We'll cycle through these for {qty || 0} comment{qty !== 1 ? "s" : ""}.
                    </Label>
                    <textarea
                      data-testid="checkout-comments"
                      value={comments}
                      onChange={(e) => setComments(e.target.value.slice(0, 5000))}
                      rows={4}
                      placeholder={"great post!\nlove this 🔥\nawesome content"}
                      className="w-full bg-[#1a1525] border border-white/10 rounded-sm px-3 py-2 text-xs font-mono text-white outline-none focus:border-[#FF007F]"
                    />
                    <div className="text-[10px] text-white/40">
                      {comments.split("\n").filter((l) => l.trim()).length} non-empty line(s)
                    </div>
                  </div>
                )}

                <Tabs value={method} onValueChange={setMethod} className="w-full">
                  <TabsList className="grid grid-cols-2 bg-[#1a1525] rounded-sm">
                    <TabsTrigger
                      value="coupon"
                      data-testid="tab-coupon"
                      className="data-[state=active]:bg-[#FF007F] data-[state=active]:text-white rounded-sm"
                    >
                      <Ticket className="w-4 h-4 mr-2" /> Coupon
                    </TabsTrigger>
                    <TabsTrigger
                      value="selly"
                      data-testid="tab-selly"
                      className="data-[state=active]:bg-emerald-500 data-[state=active]:text-black rounded-sm"
                    >
                      <Bitcoin className="w-4 h-4 mr-2" /> Crypto / Card
                    </TabsTrigger>
                  </TabsList>

                  <TabsContent value="coupon" className="space-y-2 mt-3">
                    <div className="flex gap-2">
                      <Input
                        data-testid="coupon-input"
                        placeholder="BS-XXXX-XXXX-XXXX"
                        value={coupon}
                        onChange={(e) => setCoupon(e.target.value.toUpperCase())}
                        className="bg-[#1a1525] border-white/10 font-mono"
                      />
                      <button
                        onClick={checkCoupon}
                        data-testid="coupon-check-btn"
                        className="px-4 bg-white/10 hover:bg-white/20 rounded-sm text-xs font-bold uppercase tracking-wider"
                      >
                        Check
                      </button>
                    </div>
                    {couponInfo && !couponInfo.error && (
                      <div className="text-xs text-[#00E5FF]" data-testid="coupon-balance">
                        Balance: ${Number(couponInfo.balance).toFixed(2)}
                      </div>
                    )}
                    {couponInfo?.error && (
                      <div className="text-xs text-[#FF3B30]" data-testid="coupon-error">{couponInfo.error}</div>
                    )}
                  </TabsContent>

                  <TabsContent value="selly" className="mt-3">
                    <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-sm p-3 space-y-3">
                      <p className="text-xs text-white/80 leading-relaxed">
                        Pay with <span className="font-bold text-emerald-400">BTC, ETH, LTC</span> or <span className="font-bold text-emerald-400">credit card</span> via secure Selly checkout.
                      </p>
                      <div>
                        <div className="text-[10px] uppercase tracking-wider text-white/60 mb-2">Choose payment method</div>
                        <div className="grid grid-cols-3 sm:grid-cols-6 gap-1.5">
                          {[
                            { id: "bitcoin", label: "BTC" },
                            { id: "ethereum", label: "ETH" },
                            { id: "litecoin", label: "LTC" },
                            { id: "bitcoin_cash", label: "BCH" },
                            { id: "dogecoin", label: "DOGE" },
                            { id: "stripe", label: "Card" },
                          ].map((g) => (
                            <button
                              key={g.id}
                              type="button"
                              onClick={() => setSellyGateway(g.id)}
                              data-testid={`selly-gateway-${g.id}`}
                              className={`px-2 py-1.5 text-[11px] rounded-sm border transition ${
                                sellyGateway === g.id
                                  ? "border-emerald-400 bg-emerald-500/20 text-emerald-200 font-bold"
                                  : "border-white/10 text-white/60 hover:bg-white/5"
                              }`}
                            >
                              {g.label}
                            </button>
                          ))}
                        </div>
                      </div>
                      <p className="text-[10px] text-white/50">
                        You&apos;ll be redirected to Selly&apos;s hosted page. After confirmation we&apos;ll auto-place your order.
                      </p>
                    </div>
                  </TabsContent>
                </Tabs>

                <div className="border-t border-white/5 pt-4">
                  <div className="flex justify-between items-baseline mb-3">
                    <span className="text-xs uppercase tracking-[0.2em] text-white/50">Total</span>
                    <span className="font-display text-3xl gradient-text" data-testid="total-price">
                      {fmt(price)}
                    </span>
                  </div>
                  <button
                    onClick={submit}
                    disabled={submitting || !validQty || !link || (method === "coupon" && !coupon) || (selected.needs_custom_text && !comments.trim())}
                    data-testid="place-order-btn"
                    className="w-full py-3 gradient-pp rounded-sm font-bold tracking-wide disabled:opacity-40 hover:opacity-90 transition"
                  >
                    {submitting ? (
                      <Loader2 className="w-4 h-4 animate-spin mx-auto" />
                    ) : method === "selly" ? (
                      `Continue to Selly · ${fmt(price)}`
                    ) : (
                      `Place Order · ${fmt(price)}`
                    )}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
