import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Sparkles, Loader2, ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import MathCaptcha from "@/components/MathCaptcha";

export default function ClientAuth() {
  const { user, setAuth } = useAuth();
  const nav = useNavigate();
  useEffect(() => {
    if (user) nav("/client/dashboard");
  }, [user, nav]);

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[radial-gradient(circle_at_top_left,_rgba(52,211,153,0.14),_transparent_34%),linear-gradient(135deg,_#040806_0%,_#07110b_50%,_#030705_100%)] px-3 py-6 sm:px-5 md:px-6">
      <div className="absolute inset-0 opacity-70" style={{ background: "radial-gradient(circle at 20% 20%, rgba(16,185,129,0.18), transparent 28%), radial-gradient(circle at 80% 80%, rgba(52,211,153,0.16), transparent 30%)" }} />

      <div className="relative w-full max-w-[430px]">
        <Link
          to="/"
          data-testid="back-home-link"
          className="mb-4 inline-flex items-center gap-1 text-xs uppercase tracking-[0.24em] text-white/60 transition hover:text-white"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Home
        </Link>

        <div className="rounded-[28px] border border-white/10 bg-[#07140d]/95 p-5 shadow-[0_20px_80px_rgba(0,0,0,0.35)] backdrop-blur-xl sm:p-8">
          <div className="mb-6 flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-2xl border border-emerald-400/30 bg-emerald-500/10">
              <Sparkles className="h-4.5 w-4.5 text-emerald-300" strokeWidth={2.3} />
            </div>
            <div>
              <div className="font-display text-lg font-black leading-none">
                Better<span className="text-emerald-300">Social</span>
              </div>
              <div className="mt-1 text-[10px] uppercase tracking-[0.26em] text-white/45">
                Client Area
              </div>
            </div>
          </div>

          <Tabs defaultValue="login" className="w-full">
            <TabsList className="mb-5 grid grid-cols-2 rounded-2xl border border-white/10 bg-[#0c1b13] p-1">
              <TabsTrigger
                value="login"
                data-testid="tab-login"
                className="rounded-xl text-sm font-semibold data-[state=active]:bg-emerald-500 data-[state=active]:text-black"
              >
                Sign in
              </TabsTrigger>
              <TabsTrigger
                value="register"
                data-testid="tab-register"
                className="rounded-xl text-sm font-semibold data-[state=active]:bg-emerald-500 data-[state=active]:text-black"
              >
                Create account
              </TabsTrigger>
            </TabsList>

            <GoogleSignInButton />

            <div className="my-5 flex items-center gap-3">
              <div className="h-px flex-1 bg-white/10" />
              <span className="text-[10px] font-bold uppercase tracking-[0.24em] text-white/40">or</span>
              <div className="h-px flex-1 bg-white/10" />
            </div>

            <TabsContent value="login">
              <LoginForm onSuccess={setAuth} />
            </TabsContent>
            <TabsContent value="register">
              <RegisterForm onSuccess={setAuth} />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}

function GoogleSignInButton() {
  // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
  const startGoogle = () => {
    const redirectUrl = window.location.origin + "/client/login";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };
  return (
    <button
      onClick={startGoogle}
      data-testid="google-signin-btn"
      className="w-full inline-flex items-center justify-center gap-3 rounded-2xl bg-white py-3 text-sm font-bold text-black shadow-lg transition hover:bg-white/90"
    >
      <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
        <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
        <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
        <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
        <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
      </svg>
      Continue with Google
    </button>
  );
}


function LoginForm({ onSuccess }) {
  const [ident, setIdent] = useState("");
  const [pw, setPw] = useState("");
  const [captcha, setCaptcha] = useState({ captcha_id: "", captcha_answer: "" });
  const [captchaResetKey, setCaptchaResetKey] = useState(0);
  const [loading, setLoading] = useState(false);
  const [forgotOpen, setForgotOpen] = useState(false);
  const [forgotEmail, setForgotEmail] = useState("");
  const [forgotSending, setForgotSending] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!captcha.captcha_answer) {
      toast.error("Please answer the captcha");
      return;
    }
    setLoading(true);
    try {
      const r = await api.post("/auth/login", {
        identifier: ident,
        password: pw,
        captcha_id: captcha.captcha_id,
        captcha_answer: captcha.captcha_answer,
      });
      onSuccess(r.data.token, r.data.user);
      toast.success(`Welcome back, ${r.data.user.username}`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Login failed");
      // Refresh captcha on failure so it can't be reused
      setCaptchaResetKey((k) => k + 1);
    } finally {
      setLoading(false);
    }
  };

  const sendForgot = async (e) => {
    e.preventDefault();
    const em = forgotEmail.trim().toLowerCase();
    if (!em || !em.includes("@")) {
      toast.error("Enter the email on your account");
      return;
    }
    setForgotSending(true);
    try {
      await api.post("/auth/forgot-password", { email: em });
      toast.success("If that email exists we just sent you a reset link.");
      setForgotOpen(false);
      setForgotEmail("");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't send reset email");
    } finally {
      setForgotSending(false);
    }
  };

  return (
    <>
      <form onSubmit={submit} data-testid="login-form" className="space-y-4">
        <div>
          <Label className="text-[11px] uppercase tracking-wider text-white/60">
            Username or email
          </Label>
          <Input
            data-testid="login-identifier"
            value={ident}
            onChange={(e) => setIdent(e.target.value)}
            required
            className="mt-1 border-white/10 bg-[#0d1b13] text-white placeholder:text-white/30"
          />
        </div>
        <div>
          <div className="flex items-center justify-between">
            <Label className="text-[11px] uppercase tracking-wider text-white/60">Password</Label>
            <button
              type="button"
              onClick={() => setForgotOpen(true)}
              data-testid="forgot-password-link"
              className="text-[11px] text-[#FF007F] hover:underline"
            >
              Forgot password?
            </button>
          </div>
          <Input
            data-testid="login-password"
            type="password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            required
            className="mt-1 border-white/10 bg-[#0d1b13] text-white placeholder:text-white/30"
          />
        </div>
        <MathCaptcha key={`l-${captchaResetKey}`} onChange={setCaptcha} testId="login-captcha" />
        <button
          type="submit"
          disabled={loading}
          data-testid="login-submit"
          className="w-full rounded-2xl bg-emerald-500 py-3 font-bold tracking-wide text-black transition hover:bg-emerald-400 disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : "Sign in"}
        </button>
      </form>

      {forgotOpen && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => !forgotSending && setForgotOpen(false)}>
          <div onClick={(e) => e.stopPropagation()} className="bg-[#1a1525] border border-white/10 rounded-sm p-6 max-w-md w-full">
            <h3 className="font-display font-bold text-lg mb-1">Reset your password</h3>
            <p className="text-[11px] text-white/50 mb-4">
              Enter the email on your account. We&apos;ll send you a link to choose a new password.
            </p>
            <form onSubmit={sendForgot} className="space-y-3">
              <Input
                data-testid="forgot-email-input"
                type="email"
                placeholder="you@example.com"
                value={forgotEmail}
                onChange={(e) => setForgotEmail(e.target.value)}
                required
                className="bg-[#0d0a14] border-white/10"
              />
              <div className="flex gap-2 justify-end">
                <button type="button" onClick={() => setForgotOpen(false)} disabled={forgotSending} className="px-4 py-2 border border-white/10 rounded-sm text-xs uppercase tracking-wider hover:bg-white/5">
                  Cancel
                </button>
                <button type="submit" disabled={forgotSending} data-testid="forgot-submit" className="px-4 py-2 gradient-pp rounded-sm text-xs font-bold uppercase tracking-wider disabled:opacity-50 inline-flex items-center gap-2">
                  {forgotSending ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                  Send reset link
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

function RegisterForm({ onSuccess }) {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [captcha, setCaptcha] = useState({ captcha_id: "", captcha_answer: "" });
  const [captchaResetKey, setCaptchaResetKey] = useState(0);
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!captcha.captcha_answer) {
      toast.error("Please answer the captcha");
      return;
    }
    setLoading(true);
    try {
      const r = await api.post("/auth/register", {
        username,
        email,
        password: pw,
        captcha_id: captcha.captcha_id,
        captcha_answer: captcha.captcha_answer,
        ref: localStorage.getItem("bs_ref") || undefined,
      });
      onSuccess(r.data.token, r.data.user);
      toast.success(`Welcome, ${r.data.user.username}`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Registration failed");
      setCaptchaResetKey((k) => k + 1);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={submit} data-testid="register-form" className="space-y-4">
      <div>
        <Label className="text-[11px] uppercase tracking-wider text-white/60">Username</Label>
        <Input
          data-testid="reg-username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          minLength={3}
          maxLength={24}
          pattern="^[a-zA-Z0-9_]+$"
          required
          className="mt-1 border-white/10 bg-[#0d1b13] text-white placeholder:text-white/30"
        />
        <p className="text-[10px] text-white/30 mt-1">
          3–24 chars · letters, numbers, underscore
        </p>
      </div>
      <div>
        <Label className="text-[11px] uppercase tracking-wider text-white/60">Email</Label>
        <Input
          data-testid="reg-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          className="mt-1 border-white/10 bg-[#0d1b13] text-white placeholder:text-white/30"
        />
      </div>
      <div>
        <Label className="text-[11px] uppercase tracking-wider text-white/60">Password</Label>
        <Input
          data-testid="reg-password"
          type="password"
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          minLength={8}
          required
          className="mt-1 border-white/10 bg-[#0d1b13] text-white placeholder:text-white/30"
        />
        <p className="text-[10px] text-white/30 mt-1">min 8 chars</p>
      </div>
      <MathCaptcha key={`r-${captchaResetKey}`} onChange={setCaptcha} testId="reg-captcha" />
      <button
        type="submit"
        disabled={loading}
        data-testid="register-submit"
        className="w-full rounded-2xl bg-emerald-500 py-3 font-bold tracking-wide text-black transition hover:bg-emerald-400 disabled:opacity-50"
      >
        {loading ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : "Create account"}
      </button>
    </form>
  );
}
