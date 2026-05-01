import { Link } from "react-router-dom";
import { Sparkles } from "lucide-react";

export default function Header({ onCheckout }) {
  return (
    <header
      data-testid="site-header"
      className="fixed top-0 inset-x-0 z-40 backdrop-blur-md bg-[#050505]/70 border-b border-white/5"
    >
      <div className="max-w-7xl mx-auto px-4 md:px-10 h-14 md:h-16 flex items-center justify-between gap-3">
        <Link to="/" className="flex items-center gap-2 shrink-0" data-testid="brand-logo">
          <div className="w-7 h-7 md:w-8 md:h-8 rounded-sm gradient-pp flex items-center justify-center">
            <Sparkles className="w-3.5 h-3.5 md:w-4 md:h-4 text-white" strokeWidth={2.5} />
          </div>
          <span className="font-display font-black text-base md:text-lg tracking-tight">
            Better<span className="text-[#FF007F]">Social</span>
          </span>
        </Link>

        <nav className="hidden md:flex items-center gap-8 text-sm text-white/70">
          <a href="#services" className="hover:text-white transition" data-testid="nav-services">
            Services
          </a>
          <a href="#how" className="hover:text-white transition" data-testid="nav-how">
            How it works
          </a>
          <a href="#faq" className="hover:text-white transition" data-testid="nav-faq">
            FAQ
          </a>
        </nav>

        <button
          onClick={onCheckout}
          data-testid="header-checkout-btn"
          className="px-4 md:px-5 py-2 gradient-pp rounded-sm text-xs md:text-sm font-bold tracking-wide hover:opacity-90 transition whitespace-nowrap"
        >
          Order now
        </button>
      </div>
    </header>
  );
}
