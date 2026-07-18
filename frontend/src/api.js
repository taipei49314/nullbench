async function fetchJson(url) {
  const response = await fetch(url);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

export async function loadDashboard() {
  const [manifest, superReplay, lottoReplay] = await Promise.all([
    fetchJson("/api/manifest"),
    fetchJson("/api/replay/super?limit=18"),
    fetchJson("/api/replay/lotto649?limit=18"),
  ]);
  return {
    manifest,
    recent: {
      super: superReplay.events,
      lotto649: lottoReplay.events,
    },
  };
}
