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
    <div className="min-h-screen flex items-center justify-center p-4 md:p-6 relative overflow-hidden">
      <div
        className="absolute inset-0 opacity-40"
        style={{
          background:
            "radial-gradient(circle at 20% 30%, #ff007f 0%, transparent 45%), radial-gradient(circle at 80% 70%, #7000ff 0%, transparent 45%)",
        }}
      />
      <div
        className="absolute inset-0 opacity-60"
        style={{ background: "linear-gradient(180deg, #0a0014 0%, #050505 100%)" }}
      />

      <div className="relative w-full max-w-md">
        <Link
          to="/"
          data-testid="back-home-link"
          className="absolute -top-12 left-0 text-xs uppercase tracking-wider text-white/60 hover:text-white flex items-center gap-1"
        >
          <ArrowLeft className="w-3 h-3" /> Home
        </Link>

        <div className="glass rounded-sm p-6 md:p-8">
          <div className="flex items-center gap-2 mb-6">
            <div className="w-8 h-8 rounded-sm gradient-pp flex items-center justify-center">
              <Sparkles className="w-4 h-4" strokeWidth={2.5} />
            </div>
            <span className="font-display font-black text-lg">
              Better<span className="text-[#FF007F]">Social</span>
            </span>
            <span className="ml-auto text-xs uppercase tracking-[0.2em] text-white/40">
              Client Area
            </span>
          </div>

          <Tabs defaultValue="login" className="w-full">
            <TabsList className="grid grid-cols-2 bg-[#1a1525] mb-5 rounded-sm">
              <TabsTrigger
                value="login"
                data-testid="tab-login"
                className="data-[state=active]:bg-[#FF007F] rounded-sm"
              >
                Sign in
              </TabsTrigger>
              <TabsTrigger
                value="register"
                data-testid="tab-register"
                className="data-[state=active]:bg-[#FF007F] rounded-sm"
              >
                Create account
              </TabsTrigger>
            </TabsList>

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
            className="bg-[#1a1525] border-white/10 mt-1"
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
            className="bg-[#1a1525] border-white/10 mt-1"
          />
        </div>
        <MathCaptcha key={`l-${captchaResetKey}`} onChange={setCaptcha} testId="login-captcha" />
        <button
          type="submit"
          disabled={loading}
          data-testid="login-submit"
          className="w-full py-3 gradient-pp rounded-sm font-bold tracking-wide disabled:opacity-50 hover:opacity-90 transition"
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
          className="bg-[#1a1525] border-white/10 mt-1"
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
          className="bg-[#1a1525] border-white/10 mt-1"
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
          className="bg-[#1a1525] border-white/10 mt-1"
        />
        <p className="text-[10px] text-white/30 mt-1">min 8 chars</p>
      </div>
      <MathCaptcha key={`r-${captchaResetKey}`} onChange={setCaptcha} testId="reg-captcha" />
      <button
        type="submit"
        disabled={loading}
        data-testid="register-submit"
        className="w-full py-3 gradient-pp rounded-sm font-bold tracking-wide disabled:opacity-50 hover:opacity-90 transition"
      >
        {loading ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : "Create account"}
      </button>
    </form>
  );
}
