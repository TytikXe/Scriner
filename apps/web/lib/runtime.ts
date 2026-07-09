export function resolveWsUrl() {
  const configured = typeof window === "undefined" && typeof process !== "undefined" ? process.env.NEXT_PUBLIC_API_WS_URL : undefined;
  if (configured) return configured;
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    if (host === "localhost" || host === "127.0.0.1") {
      return "ws://127.0.0.1:8000/ws";
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/ws`;
  }
  return "ws://127.0.0.1:8000/ws";
}
