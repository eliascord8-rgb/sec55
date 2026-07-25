import { createContext, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";

// FeaturesContext — polls /api/features every 60s so the sidebar hides tabs
// the admin has switched off. Direct route access on a disabled feature will
// show a friendly "not available" fallback (rendered by the consumer).
const FeaturesContext = createContext({ features: {}, loading: true });

export function FeaturesProvider({ children }) {
  const [features, setFeatures] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await api.get("/features");
        if (!cancelled) setFeatures(r.data.features || {});
      } catch { /* ignore — keep last-known */ }
      if (!cancelled) setLoading(false);
    };
    tick();
    const t = setInterval(tick, 60_000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  return (
    <FeaturesContext.Provider value={{ features, loading }}>
      {children}
    </FeaturesContext.Provider>
  );
}

export function useFeatures() {
  return useContext(FeaturesContext);
}

/** Returns true if the named feature is enabled (defaults to true when unknown / still loading). */
export function useFeatureEnabled(name) {
  const { features } = useFeatures();
  return features[name] !== false;
}
