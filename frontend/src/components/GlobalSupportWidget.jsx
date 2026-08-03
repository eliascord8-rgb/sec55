import { useState, useEffect } from "react";
import { Headset, MessageCircle } from "lucide-react";
import AIWidget from "@/components/AIWidget";

export const GlobalSupportWidget = () => {
  const [open, setOpen] = useState(false);
  const [banned, setBanned] = useState(false);

  useEffect(() => {
    const h = () => setOpen(true);
    window.addEventListener("bs-open-support-chat", h);
    return () => window.removeEventListener("bs-open-support-chat", h);
  }, []);

  useEffect(() => {
    try {
      setBanned(typeof window !== "undefined" && window.localStorage.getItem("bs_chat_banned") === "1");
    } catch {
      setBanned(false);
    }
  }, [open]);

  if (banned || open) return <AIWidget open={open} onOpenChange={setOpen} />;

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        data-testid="global-support-fab"
        aria-label="Open customer support"
        title="Customer support"
        className="fixed bottom-5 right-4 z-40 flex items-center gap-2 rounded-full border border-emerald-400/40 bg-[#07150c]/90 px-3 py-2 text-sm font-semibold text-emerald-100 shadow-[0_0_25px_rgba(52,211,153,0.24)] backdrop-blur transition hover:scale-[1.02] hover:border-emerald-300/70 sm:bottom-6 sm:right-6"
      >
        <span className="relative flex h-10 w-10 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-200">
          <span className="absolute inset-0 rounded-full bg-emerald-400/20 blur-xl" />
          <Headset className="relative h-5 w-5" />
        </span>
        <span className="hidden sm:inline">Need help? Customer support</span>
        <span className="inline sm:hidden">Help</span>
      </button>
      <AIWidget open={open} onOpenChange={setOpen} />
    </>
  );
};

export default GlobalSupportWidget;
