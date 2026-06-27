import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sparkles, Loader2, ArrowLeft, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const nav = useNavigate();
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!token) {
      toast.error("Missing reset token. Please use the link from your email.");
    }
  }, [token]);

  const submit = async (e) => {
    e.preventDefault();
    if (!token) {
      toast.error("Missing reset token");
      return;
    }
    if (pw.length < 8) {
      toast.error("Password must be at least 8 characters");
      return;
    }
    if (pw !== pw2) {
      toast.error("Passwords don't match");
      return;
    }
    setLoading(true);
    try {
      await api.post("/auth/reset-password", { token, new_password: pw });
      setDone(true);
      toast.success("Password updated! You can now log in.");
      setTimeout(() => nav("/client/login"), 2200);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't reset password");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 md:p-6 relative overflow-hidden">
      <div
        className="absolute inset-0 opacity-40"
        style={{
          background:
            "radial-gradient(circle at 20% 30%, #ff007f 0%, transparent 45%), radial-gradient(circle at 80% 70%, #7000ff 0%, transparent 45%)",
        }}
      />
      <div className="absolute inset-0 opacity-60" style={{ background: "linear-gradient(180deg, #0a0014 0%, #050505 100%)" }} />

      <div className="relative w-full max-w-md">
        <Link to="/client/login" data-testid="back-login-link" className="absolute -top-12 left-0 text-xs uppercase tracking-wider text-white/60 hover:text-white flex items-center gap-1">
          <ArrowLeft className="w-3 h-3" /> Back to login
        </Link>

        <div className="glass rounded-sm p-6 md:p-8">
          <div className="flex items-center gap-2 mb-6">
            <div className="w-8 h-8 rounded-sm gradient-pp flex items-center justify-center">
              <Sparkles className="w-4 h-4" strokeWidth={2.5} />
            </div>
            <span className="font-display font-black text-lg">
              Better<span className="text-[#FF007F]">Social</span>
            </span>
            <span className="ml-auto text-xs uppercase tracking-[0.2em] text-white/40">Reset</span>
          </div>

          {done ? (
            <div className="text-center py-6 space-y-3">
              <CheckCircle2 className="w-12 h-12 text-emerald-400 mx-auto" />
              <h3 className="font-display font-bold text-lg">Password updated</h3>
              <p className="text-xs text-white/50">Redirecting you to the login page…</p>
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-4" data-testid="reset-form">
              <p className="text-xs text-white/60">
                Choose a new password for your account. Use at least 8 characters.
              </p>
              <div>
                <Label className="text-[11px] uppercase tracking-wider text-white/60">New password</Label>
                <Input
                  data-testid="reset-new-password"
                  type="password"
                  value={pw}
                  onChange={(e) => setPw(e.target.value)}
                  required
                  minLength={8}
                  className="bg-[#1a1525] border-white/10 mt-1"
                />
              </div>
              <div>
                <Label className="text-[11px] uppercase tracking-wider text-white/60">Confirm new password</Label>
                <Input
                  data-testid="reset-confirm-password"
                  type="password"
                  value={pw2}
                  onChange={(e) => setPw2(e.target.value)}
                  required
                  minLength={8}
                  className="bg-[#1a1525] border-white/10 mt-1"
                />
              </div>
              <button
                type="submit"
                disabled={loading || !token}
                data-testid="reset-submit"
                className="w-full py-3 gradient-pp rounded-sm font-bold tracking-wide disabled:opacity-50 hover:opacity-90 transition"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : "Update password"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
