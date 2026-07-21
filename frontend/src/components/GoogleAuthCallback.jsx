import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Loader2, User as UserIcon } from "lucide-react";
import { toast } from "sonner";

// GoogleAuthCallback — mounted at the top of the router.
// Runs on EVERY page-load; if the URL fragment contains `session_id=xxx`
// (returned by Emergent-managed Google Auth), it:
//   1. Exchanges the session_id via POST /api/auth/google-status
//   2. If existing user → logs them in with our JWT + redirects
//   3. If new user → shows a MANDATORY username picker modal, then
//      calls POST /api/auth/google-finalize to create the account.
// If no session_id fragment is present, it renders nothing.
export default function GoogleAuthCallback() {
  const { setAuth } = useAuth();
  const nav = useNavigate();
  const processed = useRef(false);
  const [signup, setSignup] = useState(null); // { signup_token, email, name }
  const [username, setUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const [processing, setProcessing] = useState(false);

  useEffect(() => {
    if (processed.current) return;
    if (!window.location.hash?.includes("session_id=")) return;
    processed.current = true;
    const sid = new URLSearchParams(window.location.hash.slice(1)).get("session_id");
    if (!sid) return;
    // Clean URL fragment immediately so refresh doesn't re-trigger
    try { window.history.replaceState({}, "", window.location.pathname + window.location.search); } catch {}
    setProcessing(true);
    (async () => {
      try {
        const r = await api.post("/auth/google-status", { session_id: sid });
        if (r.data.kind === "existing_user") {
          setAuth(r.data.token, r.data.user);
          toast.success(`Welcome back, ${r.data.user.username}!`);
          nav("/client/dashboard");
        } else if (r.data.kind === "needs_username") {
          // Suggest a username from the email local-part
          const emailLocal = (r.data.google_data?.email || "").split("@")[0]
            .replace(/[^a-zA-Z0-9_]/g, "").slice(0, 20);
          setUsername(emailLocal);
          setSignup({
            signup_token: r.data.signup_token,
            email: r.data.google_data?.email,
            name: r.data.google_data?.name,
            picture: r.data.google_data?.picture,
          });
        }
      } catch (e) {
        toast.error(e.response?.data?.detail || "Google sign-in failed — please try again.");
      } finally {
        setProcessing(false);
      }
    })();
  }, [nav, setAuth]);

  const finalize = async (e) => {
    e?.preventDefault();
    const u = username.trim();
    if (!/^[a-zA-Z0-9_]{3,24}$/.test(u)) {
      toast.error("Username must be 3–24 letters/numbers/underscores.");
      return;
    }
    setBusy(true);
    try {
      const r = await api.post("/auth/google-finalize", {
        signup_token: signup.signup_token,
        username: u,
      });
      setAuth(r.data.token, r.data.user);
      toast.success(`Welcome, @${r.data.user.username}!`);
      setSignup(null);
      nav("/client/dashboard");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Couldn't finish sign-up.");
    } finally {
      setBusy(false);
    }
  };

  // Processing overlay
  if (processing) {
    return (
      <div className="fixed inset-0 z-[9998] flex items-center justify-center bg-black/80 backdrop-blur-sm">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-8 h-8 animate-spin text-emerald-400" />
          <div className="text-sm text-white/70">Finishing Google sign-in…</div>
        </div>
      </div>
    );
  }

  // Username picker modal
  if (signup) {
    return (
      <div className="fixed inset-0 z-[9998] flex items-center justify-center bg-black/85 backdrop-blur-sm p-4" data-testid="google-username-modal">
        <form onSubmit={finalize} className="w-full max-w-md bg-[#0d2b12] border border-emerald-500/40 rounded-xl p-6 md:p-8 shadow-2xl shadow-emerald-900/50 space-y-5">
          <div className="flex items-center gap-3">
            {signup.picture ? (
              <img src={signup.picture} alt="" className="w-12 h-12 rounded-full border border-emerald-500/40" />
            ) : (
              <div className="w-12 h-12 rounded-full bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center">
                <UserIcon className="w-6 h-6 text-emerald-300" />
              </div>
            )}
            <div>
              <div className="font-display font-black text-lg text-white">Almost there!</div>
              <div className="text-xs text-emerald-200/70">Signed in as {signup.email}</div>
            </div>
          </div>
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-emerald-300/80 font-bold mb-1.5">
              Pick your username
            </label>
            <input
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value.replace(/[^a-zA-Z0-9_]/g, "").slice(0, 24))}
              minLength={3}
              maxLength={24}
              required
              placeholder="e.g. crypto_king"
              data-testid="google-username-input"
              className="w-full bg-black/40 border border-emerald-500/30 rounded-md px-4 py-3 text-white text-lg font-mono focus:outline-none focus:border-emerald-400"
            />
            <div className="text-[10px] text-white/50 mt-1.5">3–24 characters · letters, numbers, underscores only · this is public.</div>
          </div>
          <button
            type="submit"
            disabled={busy || username.trim().length < 3}
            data-testid="google-username-submit"
            className="w-full py-3 rounded-md bg-emerald-500 hover:bg-emerald-400 text-black font-black uppercase tracking-wider text-sm disabled:opacity-50 inline-flex items-center justify-center gap-2 transition"
          >
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            Create my account
          </button>
        </form>
      </div>
    );
  }

  return null;
}
