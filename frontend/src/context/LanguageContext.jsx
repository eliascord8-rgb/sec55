import { createContext, useContext, useEffect, useState } from "react";

// Supported languages. Keeping the dictionary lean and focused on the most-visible
// user-facing strings — nav labels, hero copy, CTAs. Falls back to English when
// a key is missing so partial translations never render blank.
export const LANGS = [
  { code: "en", label: "English", flag: "🇬🇧" },
  { code: "bs", label: "Bosanski", flag: "🇧🇦" },
  { code: "es", label: "Español", flag: "🇪🇸" },
  { code: "pt", label: "Português", flag: "🇵🇹" },
  { code: "de", label: "Deutsch", flag: "🇩🇪" },
];

const DICTS = {
  en: {
    nav_home: "Home",
    nav_buy: "Purchase",
    nav_live: "Live orders",
    nav_addons: "Add-ons",
    nav_numbers: "Numbers",
    nav_games: "Games",
    nav_sports: "Sports",
    nav_invoices: "Invoices",
    nav_help: "Help",
    nav_messages: "Friends",
    nav_tickets: "Support",
    nav_funds: "Wallet",
    nav_redeem: "Gifts",
    nav_withdraw: "Withdraw",
    balance: "Balance",
    buy: "Buy",
    sign_in: "Sign in",
    sign_up: "Sign up",
    create_account: "Create account",
    welcome_to: "Welcome to",
    welcome_sub: "Sign in to place orders, play daily games, deposit crypto and manage your account. Peek around — the live chat and community orders are open to everyone.",
    community_chat: "Community chat",
    latest_orders: "Latest orders",
    live_chat: "Live Chat",
    say_hi: "Sign in to join the conversation.",
    live_orders_desc: "Automatic TikTok-live SMM bursts every 10 minutes while your target streams.",
  },
  bs: {
    nav_home: "Početna",
    nav_buy: "Kupovina",
    nav_live: "Uživo narudžbe",
    nav_addons: "Dodaci",
    nav_numbers: "Brojevi",
    nav_games: "Igre",
    nav_sports: "Sport",
    nav_invoices: "Računi",
    nav_help: "Pomoć",
    nav_messages: "Prijatelji",
    nav_tickets: "Podrška",
    nav_funds: "Novčanik",
    nav_redeem: "Pokloni",
    nav_withdraw: "Isplata",
    balance: "Stanje",
    buy: "Kupi",
    sign_in: "Prijavi se",
    sign_up: "Registriraj se",
    create_account: "Otvori račun",
    welcome_to: "Dobrodošli u",
    welcome_sub: "Prijavi se za slanje narudžbi, dnevne igre, uplate kriptovaluta i upravljanje računom. Razgledaj — javni chat i narudžbe zajednice su otvoreni za sve.",
    community_chat: "Zajednički chat",
    latest_orders: "Posljednje narudžbe",
    live_chat: "Uživo Chat",
    say_hi: "Prijavi se da se pridružiš razgovoru.",
    live_orders_desc: "Automatske TikTok-live SMM narudžbe svakih 10 minuta dok tvoj korisnik strimuje.",
  },
  es: {
    nav_home: "Inicio",
    nav_buy: "Comprar",
    nav_live: "Pedidos en vivo",
    nav_addons: "Complementos",
    nav_numbers: "Números",
    nav_games: "Juegos",
    nav_sports: "Deportes",
    nav_invoices: "Facturas",
    nav_help: "Ayuda",
    nav_messages: "Amigos",
    nav_tickets: "Soporte",
    nav_funds: "Cartera",
    nav_redeem: "Regalos",
    nav_withdraw: "Retirar",
    balance: "Saldo",
    buy: "Comprar",
    sign_in: "Iniciar sesión",
    sign_up: "Registrarse",
    create_account: "Crear cuenta",
    welcome_to: "Bienvenido a",
    welcome_sub: "Inicia sesión para hacer pedidos, jugar, depositar cripto y administrar tu cuenta. Mira alrededor — el chat y los pedidos de la comunidad son públicos.",
    community_chat: "Chat de la comunidad",
    latest_orders: "Pedidos recientes",
    live_chat: "Chat en Vivo",
    say_hi: "Inicia sesión para participar.",
    live_orders_desc: "Pedidos SMM automáticos en TikTok Live cada 10 minutos mientras tu objetivo transmite.",
  },
  pt: {
    nav_home: "Início",
    nav_buy: "Comprar",
    nav_live: "Pedidos ao vivo",
    nav_addons: "Complementos",
    nav_numbers: "Números",
    nav_games: "Jogos",
    nav_sports: "Desportos",
    nav_invoices: "Faturas",
    nav_help: "Ajuda",
    nav_messages: "Amigos",
    nav_tickets: "Suporte",
    nav_funds: "Carteira",
    nav_redeem: "Presentes",
    nav_withdraw: "Sacar",
    balance: "Saldo",
    buy: "Comprar",
    sign_in: "Entrar",
    sign_up: "Registrar",
    create_account: "Criar conta",
    welcome_to: "Bem-vindo ao",
    welcome_sub: "Entre para fazer pedidos, jogar, depositar cripto e gerir a sua conta. Explore — o chat e os pedidos da comunidade estão abertos a todos.",
    community_chat: "Chat da comunidade",
    latest_orders: "Últimos pedidos",
    live_chat: "Chat ao Vivo",
    say_hi: "Entre para participar da conversa.",
    live_orders_desc: "Pedidos SMM automáticos no TikTok Live a cada 10 minutos enquanto o seu alvo transmite.",
  },
  de: {
    nav_home: "Start",
    nav_buy: "Kaufen",
    nav_live: "Live-Bestellungen",
    nav_addons: "Add-ons",
    nav_numbers: "Nummern",
    nav_games: "Spiele",
    nav_sports: "Sport",
    nav_invoices: "Rechnungen",
    nav_help: "Hilfe",
    nav_messages: "Freunde",
    nav_tickets: "Support",
    nav_funds: "Wallet",
    nav_redeem: "Geschenke",
    nav_withdraw: "Auszahlen",
    balance: "Guthaben",
    buy: "Kaufen",
    sign_in: "Anmelden",
    sign_up: "Registrieren",
    create_account: "Konto erstellen",
    welcome_to: "Willkommen bei",
    welcome_sub: "Melde dich an, um Bestellungen aufzugeben, täglich zu spielen, Krypto einzuzahlen und dein Konto zu verwalten. Schau dich um — der Live-Chat und die Community-Bestellungen sind für alle offen.",
    community_chat: "Community-Chat",
    latest_orders: "Neueste Bestellungen",
    live_chat: "Live-Chat",
    say_hi: "Melde dich an, um mitzureden.",
    live_orders_desc: "Automatische TikTok-Live SMM-Bestellungen alle 10 Minuten, solange dein Ziel streamt.",
  },
};

const LanguageContext = createContext({
  lang: "en",
  setLang: () => {},
  t: (k) => k,
});

export function LanguageProvider({ children }) {
  const [lang, setLangState] = useState(() => {
    try {
      const s = localStorage.getItem("bs_lang");
      return LANGS.some((l) => l.code === s) ? s : "en";
    } catch { return "en"; }
  });
  useEffect(() => {
    try { localStorage.setItem("bs_lang", lang); } catch { /* private mode */ }
    try { document.documentElement.setAttribute("lang", lang); } catch { /* SSR */ }
  }, [lang]);
  const t = (key) => (DICTS[lang] && DICTS[lang][key]) || DICTS.en[key] || key;
  return (
    <LanguageContext.Provider value={{ lang, setLang: setLangState, t }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLang() {
  return useContext(LanguageContext);
}

// Small dropdown widget — used in both the guest landing and dashboard header.
export function LanguagePicker({ compact = false }) {
  const { lang, setLang } = useLang();
  const current = LANGS.find((l) => l.code === lang) || LANGS[0];
  const [open, setOpen] = useState(false);
  return (
    <div className="relative" data-testid="lang-picker">
      <button
        onClick={() => setOpen((v) => !v)}
        data-testid="lang-picker-btn"
        title="Change language"
        className={`inline-flex items-center gap-1.5 rounded-md text-[11px] font-bold uppercase tracking-wider transition ${compact ? "px-2 py-1.5 hover:bg-emerald-500/15 text-emerald-200" : "px-3 py-2 border border-emerald-500/30 text-emerald-200 hover:bg-emerald-500/15"}`}
      >
        <span className="text-base leading-none">{current.flag}</span>
        <span className="hidden sm:inline">{current.code.toUpperCase()}</span>
        <span className="text-[9px] opacity-60">▾</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 w-40 bg-[#0d2b12] border border-emerald-500/30 rounded-md shadow-2xl z-50 py-1" data-testid="lang-menu">
            {LANGS.map((l) => (
              <button
                key={l.code}
                onClick={() => { setLang(l.code); setOpen(false); }}
                data-testid={`lang-opt-${l.code}`}
                className={`w-full flex items-center gap-2 px-3 py-2 text-sm transition ${lang === l.code ? "bg-emerald-500/15 text-emerald-200" : "text-white hover:bg-emerald-500/10"}`}
              >
                <span className="text-base">{l.flag}</span>
                <span className="flex-1 text-left font-medium">{l.label}</span>
                {lang === l.code && <span className="text-emerald-400 text-xs">✓</span>}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
