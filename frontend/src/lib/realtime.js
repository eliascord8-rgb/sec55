export function notifyAppRefresh(reason = "update") {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem("bs_refresh_signal", `${Date.now()}:${reason}`);
  } catch {}
  window.dispatchEvent(new CustomEvent("bs:refresh", { detail: { reason } }));
}

export function setupAppRefresh(onRefresh) {
  if (typeof window === "undefined") return () => {};

  const channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("bs-realtime") : null;
  const handleMessage = (event) => {
    if (event?.data?.type === "refresh") onRefresh?.(event.data);
  };
  const handleStorage = (event) => {
    if (event.key === "bs_refresh_signal" && event.newValue) onRefresh?.({ reason: event.newValue.split(":")[1] || "storage" });
  };
  const handleCustom = () => onRefresh?.({ reason: "custom" });

  channel?.addEventListener("message", handleMessage);
  window.addEventListener("storage", handleStorage);
  window.addEventListener("bs:refresh", handleCustom);

  const notifyAll = (reason = "update") => {
    try {
      localStorage.setItem("bs_refresh_signal", `${Date.now()}:${reason}`);
    } catch {}
    channel?.postMessage({ type: "refresh", reason });
    window.dispatchEvent(new CustomEvent("bs:refresh", { detail: { reason } }));
  };

  return () => {
    channel?.removeEventListener("message", handleMessage);
    window.removeEventListener("storage", handleStorage);
    window.removeEventListener("bs:refresh", handleCustom);
    channel?.close();
  };
}

export function refreshAllTabs(reason = "update") {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem("bs_refresh_signal", `${Date.now()}:${reason}`);
  } catch {}
  if (typeof BroadcastChannel !== "undefined") {
    const channel = new BroadcastChannel("bs-realtime");
    channel.postMessage({ type: "refresh", reason });
    channel.close();
  }
  window.dispatchEvent(new CustomEvent("bs:refresh", { detail: { reason } }));
}
