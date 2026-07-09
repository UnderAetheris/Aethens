interface ConnectionBannerProps {
  status: "connecting" | "live" | "reconnecting";
}

export function ConnectionBanner({ status }: ConnectionBannerProps) {
  if (status === "live") {
    return null;
  }
  return <div className="banner">{status === "connecting" ? "Connecting to Aetheris…" : "Reconnecting…"}</div>;
}
