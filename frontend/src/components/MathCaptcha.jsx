import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RefreshCw, Loader2 } from "lucide-react";

/**
 * Self-contained math captcha widget.
 * Calls onChange({ captcha_id, captcha_answer }) whenever the user types.
 */
export default function MathCaptcha({ onChange, testId = "math-captcha" }) {
  const [c, setC] = useState(null);
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    setAnswer("");
    onChange({ captcha_id: "", captcha_answer: "" });
    try {
      const r = await api.get("/auth/captcha");
      setC(r.data);
      onChange({ captcha_id: r.data.id, captcha_answer: "" });
    } catch {
      // ignore — backend will reject empty captcha
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div data-testid={testId}>
      <Label className="text-[11px] uppercase tracking-wider text-white/60">
        Quick check
      </Label>
      <div className="flex items-stretch gap-2 mt-1">
        <div className="flex-1 bg-[#1a1525] border border-white/10 rounded-sm px-3 py-2 text-sm text-white/90 select-none">
          {loading || !c ? (
            <span className="inline-flex items-center gap-2 text-white/50">
              <Loader2 className="w-3 h-3 animate-spin" /> loading…
            </span>
          ) : (
            c.question
          )}
        </div>
        <Input
          data-testid={`${testId}-answer`}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          placeholder="?"
          value={answer}
          onChange={(e) => {
            const v = e.target.value.replace(/[^\d-]/g, "").slice(0, 4);
            setAnswer(v);
            onChange({ captcha_id: c?.id || "", captcha_answer: v });
          }}
          required
          className="bg-[#0d0a14] border-white/10 w-20 text-center font-mono"
        />
        <button
          type="button"
          onClick={refresh}
          disabled={loading}
          aria-label="Refresh captcha"
          title="Get a new question"
          data-testid={`${testId}-refresh`}
          className="w-10 rounded-sm border border-white/10 text-white/60 hover:text-white hover:bg-white/5 inline-flex items-center justify-center disabled:opacity-40"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>
    </div>
  );
}
