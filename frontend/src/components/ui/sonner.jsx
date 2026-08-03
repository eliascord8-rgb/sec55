import { useTheme } from "next-themes"
import { Toaster as Sonner, toast } from "sonner"
import { playSuccessSound, playErrorSound, playWarningSound } from "@/lib/alertSounds"

// Patch sonner's toast singleton once so every toast.success()/error()/warning() call
// site-wide (they all import the same `toast` object from "sonner") plays a matching sound.
if (!toast.__bsSoundPatched) {
  const rawSuccess = toast.success.bind(toast);
  const rawError = toast.error.bind(toast);
  const rawWarning = toast.warning ? toast.warning.bind(toast) : null;
  toast.success = (msg, opts) => { playSuccessSound(); return rawSuccess(msg, opts); };
  toast.error = (msg, opts) => { playErrorSound(); return rawError(msg, opts); };
  if (rawWarning) toast.warning = (msg, opts) => { playWarningSound(); return rawWarning(msg, opts); };
  toast.__bsSoundPatched = true;
}

const Toaster = ({
  ...props
}) => {
  const { theme = "system" } = useTheme()

  return (
    <Sonner
      theme={theme}
      position="top-right"
      richColors
      closeButton
      className="toaster group"
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:bg-background group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:shadow-2xl group-[.toaster]:rounded-lg",
          description: "group-[.toast]:text-muted-foreground",
          actionButton:
            "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton:
            "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
        },
      }}
      {...props} />
  );
}

export { Toaster, toast }
