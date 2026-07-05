const BASE = "/api";

async function jget(path) {
  const r = await fetch(BASE + path);
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}
async function jpost(path) {
  const r = await fetch(BASE + path, { method: "POST" });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

export const api = {
  run: (opts = {}) => {
    const q = new URLSearchParams();
    if (opts.attack) q.set("attack", "true");
    if (opts.learning === false) q.set("learning", "false");
    return jpost(`/covenant/run?${q.toString()}`);
  },
  evaluation: (id) => jget(`/traces/${id}/evaluation`),
  receipt: (id) => jget(`/traces/${id}/receipt`),
  verifyReceipt: (id) => jget(`/traces/${id}/receipt/verify`),
  verifyPayload: (payload) =>
    fetch("/api/receipts/verify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then((r) => r.json()),
  replay: (id) => jget(`/traces/${id}/replay`),
  evidence: () => jget(`/evidence`),
  runs: () => jget(`/runs`),
  vultr: () => jget(`/integrations/vultr/status`),
  health: () => jget(`/health`),
};
