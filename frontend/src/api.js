async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

const wait = (milliseconds) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export async function syncLatest(onProgress = () => {}) {
  let state = await fetchJson("/api/sync", { method: "POST" });
  onProgress(state);
  while (state.status === "idle" || state.status === "running") {
    await wait(350);
    state = await fetchJson("/api/sync/status");
    onProgress(state);
  }
  if (state.status === "error") {
    throw new Error(state.error || state.message);
  }
  return state.result;
}

export function revealDecision(game) {
  return fetchJson(`/api/reveal/${game}`, { method: "POST" });
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
