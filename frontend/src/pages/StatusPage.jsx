import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "@/lib/api";
import { CheckCircle2, Clock, XCircle, Loader2, Sparkles, ArrowLeft, MessageCircle } from "lucide-react";

const TERMINAL = new Set(["completed", "failed"]);

export default function StatusPage() {
  const { orderId } = useParams();
  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);

  const load = async () => {
    try {
      const r = await api.get(`/order-status/${orderId}`);
      setOrder(r.data);
      return r.data;
    } catch {
      setOrder({ status: "not_found" });
      return { status: "not_found" };
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [orderId]);

  // Auto-poll while pending
  useEffect(() => {
    if (!order || TERMINAL.has(order.status)) return;
    const poll = setInterval(async () => {
      // If the order is a crypto payment, trigger a backend re-check
      if (order.payment_method === "cryptomus") {
        try {
          await api.post("/cryptomus/check", { order_id: orderId });
        } catch {}
      }
      load();
    }, 8000);
    return () => clearInterval(poll);
  }, [order, orderId]);

  const recheck = async () => {
    setChecking(true);
    try {
      if (order?.payment_method === "cryptomus") {
        await api.post("/cryptomus/check", { order_id: orderId });
      }
      await load();
    } finally {
      setChecking(false);
    }
  };

  const openChat = () => {
    if (window.Tawk_API && typeof window.Tawk_API.maximize === "function") {
      window.Tawk_API.maximize();
    } else {
      window.location.href = "mailto:balkinstr@web.de?subject=Order%20" + orderId;
    }
  };

  return (
    <div className="min-h-screen bg-[#050505] text-white">
      <header className="border-b border-white/5">
        <div className="max-w-4xl mx-auto px-4 md:px-10 h-14 md:h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-sm gradient-pp flex items-center justify-center">
              <Sparkles className="w-3.5 h-3.5" strokeWidth={2.5} />
            </div>
            <span className="font-display font-black text-base">
              Better<span className="text-[#FF007F]">Social</span>
            </span>
          </Link>
          <Link
            to="/"
            data-testid="back-home"
            className="text-xs uppercase tracking-wider text-white/60 hover:text-white flex items-center gap-1"
          >
            <ArrowLeft className="w-3 h-3" /> Home
          </Link>
        </div>
      </header>

      <main className="max-w-xl mx-auto px-4 md:px-10 py-16 md:py-24 text-center">
        {loading ? (
          <Loader2 className="w-8 h-8 animate-spin mx-auto text-white/40" />
        ) : order?.status === "not_found" ? (
          <NotFound orderId={orderId} />
        ) : order?.status === "completed" ? (
          <Completed order={order} />
        ) : order?.status === "failed" ? (
          <Failed order={order} openChat={openChat} />
        ) : (
          <Pending order={order} orderId={orderId} checking={checking} recheck={recheck} />
        )}
      </main>
    </div>
  );
}

function Completed({ order }) {
  return (
    <div data-testid="status-completed">
      <div className="inline-flex w-20 h-20 items-center justify-center rounded-full bg-[#00E5FF]/20 border border-[#00E5FF]/40 mb-6">
        <CheckCircle2 className="w-10 h-10 text-[#00E5FF]" strokeWidth={2} />
      </div>
      <h1 className="font-display text-3xl md:text-5xl font-black tracking-tight mb-3">
        Order <span className="gradient-text">completed</span>.
      </h1>
      <p className="text-white/50 mb-8 leading-relaxed">
        Your order has been submitted to the provider and is now in progress. Delivery usually
        begins within minutes.
      </p>
      <div className="inline-block bg-[#1a1525] border border-white/10 rounded-sm px-6 py-4 mb-8">
        <div className="text-[10px] uppercase tracking-wider text-white/40 mb-1">SMM Order ID</div>
        <div className="font-mono text-xl font-bold text-[#FF007F]">
          {order.smm_order_id || "—"}
        </div>
      </div>
      <div>
        <Link
          to="/"
          className="inline-block px-8 py-3 gradient-pp rounded-sm font-bold tracking-wide"
        >
          Place another order
        </Link>
      </div>
    </div>
  );
}

function Failed({ order, openChat }) {
  return (
    <div data-testid="status-failed">
      <div className="inline-flex w-20 h-20 items-center justify-center rounded-full bg-[#FF3B30]/20 border border-[#FF3B30]/40 mb-6">
        <XCircle className="w-10 h-10 text-[#FF3B30]" strokeWidth={2} />
      </div>
      <h1 className="font-display text-3xl md:text-5xl font-black tracking-tight mb-3">
        Something <span className="text-[#FF3B30]">went wrong</span>.
      </h1>
      <p className="text-white/50 mb-6 leading-relaxed">
        Your payment went through but we couldn't place the provider order automatically.
      </p>
      {order.failure_reason && (
        <div className="bg-[#1a1525] border border-white/10 rounded-sm px-4 py-3 mb-6 text-xs text-white/60 font-mono">
          {order.failure_reason}
        </div>
      )}
      <p className="text-white/60 text-sm mb-6">
        <strong className="text-white">Don't worry</strong> — contact us via live chat and we'll
        resolve it within minutes.
      </p>
      <div className="flex flex-col sm:flex-row gap-3 justify-center">
        <button
          onClick={openChat}
          data-testid="open-live-chat"
          className="inline-flex items-center justify-center gap-2 px-6 py-3 gradient-pp rounded-sm font-bold tracking-wide"
        >
          <MessageCircle className="w-4 h-4" /> Contact us via live chat
        </button>
        <a
          href="mailto:balkinstr@web.de"
          className="inline-flex items-center justify-center gap-2 px-6 py-3 border border-white/15 rounded-sm font-bold tracking-wide hover:bg-white/5"
        >
          Email support
        </a>
      </div>
    </div>
  );
}

function Pending({ order, orderId, checking, recheck }) {
  return (
    <div data-testid="status-pending">
      <div className="inline-flex w-20 h-20 items-center justify-center rounded-full bg-[#FFB800]/20 border border-[#FFB800]/40 mb-6 animate-pulse">
        <Clock className="w-10 h-10 text-[#FFB800]" strokeWidth={2} />
      </div>
      <h1 className="font-display text-3xl md:text-5xl font-black tracking-tight mb-3">
        Waiting for <span className="gradient-text">payment</span>…
      </h1>
      <p className="text-white/50 mb-8 leading-relaxed">
        {order?.payment_method === "cryptomus"
          ? "Once your crypto payment is confirmed on-chain, your order is placed automatically. This page updates in real time."
          : "Your order is pending processing."}
      </p>
      {order?.checkout_url && (
        <a
          href={order.checkout_url}
          target="_blank"
          rel="noreferrer"
          data-testid="open-payment-link"
          className="inline-block px-6 py-3 gradient-pp rounded-sm font-bold tracking-wide mb-3"
        >
          Complete payment →
        </a>
      )}
      <div>
        <button
          onClick={recheck}
          disabled={checking}
          data-testid="recheck-status"
          className="text-xs uppercase tracking-wider text-white/60 hover:text-white disabled:opacity-50"
        >
          {checking ? "Checking…" : "Refresh status manually"}
        </button>
      </div>
      <div className="mt-10 text-[10px] font-mono text-white/30">Order: {orderId}</div>
    </div>
  );
}

function NotFound({ orderId }) {
  return (
    <div>
      <h1 className="font-display text-3xl md:text-5xl font-black tracking-tight mb-3">
        Order not found
      </h1>
      <p className="text-white/50 mb-8">
        We couldn't locate order <span className="font-mono text-white/70">{orderId}</span>.
      </p>
      <Link to="/" className="inline-block px-8 py-3 gradient-pp rounded-sm font-bold">
        Go home
      </Link>
    </div>
  );
}
