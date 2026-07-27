import { useState, useEffect } from "react";
import { Headset } from "lucide-react";
import AIWidget from "@/components/AIWidget";

export const GlobalSupportWidget = () => {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const h = () => setOpen(true);
    window.addEventListener("bs-open-support-chat", h);
    return () => window.removeEventListener("bs-open-support-chat", h);
  }, []);

  return (
    <>
      {/* Mobile-only floating support trigger — available on every page */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          data-testid="global-support-fab"
          title="Customer support"
          className="md:hidden fixed bottom-20 right-4 z-30 w-12 h-12 rounded-full bg-[#FF007F] text-white shadow-lg shadow-[#FF007F]/40 flex items-center justify-center active:scale-95 transition"
        >
          <Headset className="w-5 h-5" />
        </button>
      )}
      <AIWidget open={open} onOpenChange={setOpen} />
    </>
  );
};

export default GlobalSupportWidget;
