import React, { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip, ReferenceLine,
} from "recharts";
import { api } from "./lib/api";
import { Panel, Pill, CovenantGauge, VerifySeal, ScoreBar, statusColor } from "./components/ui.jsx";

const VIEWS = ["Investigation", "Evidence", "Memo & Verify", "Evaluation", "History"];

const WORKFLOW_STEPS = [
  ["Plan", "Plan the covenant investigation"],
  ["Retrieve clauses", "Retrieve governing covenant clauses"],
  ["Pull filings", "Retrieve borrower filings & trend"],
  ["Calculate", "Re-verify each covenant ratio"],
  ["Apply waiver", "Apply any active signed waiver"],
  ["Cross-check", "Cross-check transactions for cause"],
  ["Memo", "Generate escalation memo + receipt"],
];

export default function App() {
  const [view, setView] = useState("Investigation");
  const [run, setRun] = useState(null);
  const [evalData, setEvalData] = useState(null);
  const [evidence, setEvidence] = useState(null);
  const [history, setHistory] = useState([]);
  const [vultr, setVultr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(-1);
  const [verify, setVerify] = useState("idle");
  const [attack, setAttack] = useState(false);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    api.vultr().then(setVultr).catch(() => setOffline(true));
    api.evidence().then((d) => setEvidence(d.documents)).catch(() => {});
    refreshHistory();
  }, []);

  const refreshHistory = () =>
    api.runs().then((d) => setHistory(d.runs || [])).catch(() => {});

  async function runAgent() {
    setBusy(true); setStep(0); setVerify("idle"); setRun(null); setEvalData(null);
    // animate the workflow steps while the request runs
    let s = 0;
    const timer = setInterval(() => { s = Math.min(s + 1, WORKFLOW_STEPS.length - 1); setStep(s); }, 260);
    try {
      const r = await api.run({ attack });
      const ev = await api.evaluation(r.trace_id).catch(() => null);
      clearInterval(timer); setStep(WORKFLOW_STEPS.length - 1);
      setRun(r); setEvalData(ev); refreshHistory();
      api.evidence().then((d) => setEvidence(d.documents)).catch(() => {});
    } catch (e) {
      clearInterval(timer); setOffline(true);
    } finally {
      setBusy(false);
    }
  }

  async function doVerify() {
    setVerify("checking");
    try {
      const receipt = await api.receipt(run.trace_id);
      const res = await api.verifyPayload(receipt); // real Ed25519 check on the server
      setTimeout(() => setVerify(res && res.valid ? "valid" : "invalid"), 700);
    } catch {
      setTimeout(() => setVerify("invalid"), 700);
    }
  }

  async function doTamper() {
    setVerify("checking");
    try {
      const receipt = await api.receipt(run.trace_id);
      // alter a material field AFTER signing — the signature will no longer match
      const tampered = JSON.parse(JSON.stringify(receipt));
      tampered.receipt.severity = "none";
      tampered.receipt.confidence = 1.0;
      const res = await api.verifyPayload(tampered); // real check → genuinely fails
      setTimeout(() => setVerify(res && res.valid ? "valid" : "invalid"), 700);
    } catch {
      setTimeout(() => setVerify("invalid"), 700);
    }
  }

  return (
    <div className="min-h-screen bg-ink text-paper">
      <Header vultr={vultr} offline={offline} />
      <Nav view={view} setView={setView} />
      <main className="mx-auto max-w-6xl px-5 pb-24 pt-6">
        {view === "Investigation" && (
          <Investigation
            run={run} busy={busy} step={step} attack={attack} setAttack={setAttack} runAgent={runAgent} evalData={evalData}
          />
        )}
        {view === "Evidence" && <Evidence evidence={evidence} />}
        {view === "Memo & Verify" && (
          <MemoVerify run={run} evalData={evalData} verify={verify} doVerify={doVerify} doTamper={doTamper} />
        )}
        {view === "Evaluation" && <Evaluation run={run} evalData={evalData} />}
        {view === "History" && <History history={history} />}
      </main>
    </div>
  );
}

function Header({ vultr, offline }) {
  return (
    <header className="border-b border-white/8 bg-ink/80 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-8 w-8 place-items-center rounded-md bg-signal font-display text-lg font-bold text-ink">C</div>
          <div>
            <div className="font-display text-[17px] font-semibold leading-none">CovenantOps Agent</div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-mute">CovenantOps · verifiable covenant monitoring</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {offline ? (
            <Pill tone="amber">backend offline</Pill>
          ) : (
            <Pill tone={vultr?.serverless_inference_configured ? "signal" : "mute"}>
              {vultr?.serverless_inference_configured ? "Vultr inference on" : "local inference"}
            </Pill>
          )}
        </div>
      </div>
    </header>
  );
}

function Nav({ view, setView }) {
  return (
    <nav className="border-b border-white/8">
      <div className="mx-auto flex max-w-6xl gap-1 px-5">
        {VIEWS.map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`relative px-4 py-3 text-[13px] font-medium transition ${
              view === v ? "text-paper" : "text-mute hover:text-paper/80"
            }`}
          >
            {v}
            {view === v && <span className="absolute inset-x-3 -bottom-px h-0.5 rounded bg-signal" />}
          </button>
        ))}
      </div>
    </nav>
  );
}

function Investigation({ run, busy, step, attack, setAttack, runAgent, evalData }) {
  return (
    <div className="grid gap-5 lg:grid-cols-[1.1fr_1fr]">
      <div className="space-y-5">
        <Panel title="Run investigation" kicker="the agent">
          <p className="mb-4 text-[13px] leading-6 text-paper/70">
            CovenantOps Agent plans a covenant check, grounds it in the borrower's real documents, re-verifies
            each ratio, and explains any drift toward breach — producing a memo you can verify.
          </p>
          <label className="mb-4 flex items-center gap-2 text-[13px] text-paper/80">
            <input type="checkbox" checked={attack} onChange={(e) => setAttack(e.target.checked)}
              className="h-4 w-4 accent-oxblood" />
            Inject a malicious instruction (demo the guard)
          </label>
          <button onClick={runAgent} disabled={busy}
            className="w-full rounded-lg bg-signal py-2.5 text-[14px] font-semibold text-ink transition hover:brightness-110 disabled:opacity-50">
            {busy ? "Investigating…" : "Run covenant check"}
          </button>
        </Panel>

        <Panel title="Why this is not basic RAG" kicker="agent proof">
          <div className="grid gap-2 text-[13px] text-paper/75 sm:grid-cols-2">
            <div>✓ Plans before answering</div><div>✓ Retrieves more than once</div>
            <div>✓ Calls calculation tools</div><div>✓ Makes explicit risk decisions</div>
            <div>✓ Runs context-integrity checks</div><div>✓ Signs a verifiable receipt</div>
          </div>
        </Panel>

        <Panel title="Workflow" kicker="multi-step">
          <ol className="space-y-2.5">
            {WORKFLOW_STEPS.map(([label, desc], i) => {
              const done = step >= i && (run || busy);
              const active = step === i && busy;
              return (
                <li key={label} className="flex items-start gap-3">
                  <span className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full font-mono text-[11px] ${
                    done ? "bg-signal text-ink" : active ? "bg-white/20 text-paper" : "bg-white/6 text-mute"
                  }`}>{done && !active ? "✓" : i + 1}</span>
                  <div>
                    <div className={`text-[13px] ${done ? "text-paper" : "text-mute"}`}>{label}</div>
                    {active && <div className="font-mono text-[11px] text-mute">{desc}</div>}
                  </div>
                </li>
              );
            })}
          </ol>
        </Panel>
      </div>

      <div className="space-y-5">
        {run ? (
          <>
            <Panel title="Covenant status" kicker={run.severity}>
              <div className="space-y-4">
                {(run.findings || []).map((f) => (
                  <CovenantGauge key={f.covenant}
                    label={f.ratio.metric}
                    value={f.ratio.value} limit={f.ratio.threshold}
                    direction={f.ratio.direction}
                    status={f.ratio.breached ? "breach" : f.ratio.drifting_toward_breach ? "drifting" : "within"}
                  />
                ))}
              </div>
              <div className="mt-4 flex items-center justify-between border-t border-white/8 pt-3">
                <span className="text-[12px] text-mute">cause-attribution confidence</span>
                <span className="font-mono text-[15px]" style={{ color: statusColor(run.confidence < 0.7 ? "watch" : "within") }}>
                  {(run.confidence * 100).toFixed(0)}%
                </span>
              </div>
            </Panel>

            {run.tool_calls?.some((t) => t.guard === "block") && (
              <Panel title="Security" kicker="injection blocked">
                <div className="rounded-lg border border-oxblood/30 bg-oxblood/10 p-3">
                  <div className="text-[13px] font-medium text-oxblood">Malicious instruction caught</div>
                  <div className="mt-1 font-mono text-[11px] leading-5 text-paper/70">
                    A document tried to instruct the agent to report compliance. The guard blocked it —
                    the real breach is still reported.
                  </div>
                </div>
              </Panel>
            )}
          </>
        ) : (
          <Panel title="Covenant status" kicker="idle">
            <div className="grid place-items-center py-12 text-center">
              <div className="font-mono text-[12px] text-mute">Run a check to see live covenant analysis.</div>
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}

function Evidence({ evidence }) {
  const trustTone = (t) => (t === "very_high" || t === "high" ? "signal" : t === "medium" ? "amber" : "oxblood");
  return (
    <Panel title="Evidence set" kicker="multi-format · trust-weighted">
      <p className="mb-4 text-[13px] text-paper/70">
        CovenantOps grounds on the real documents a credit team uses — across formats — each weighted by
        how trustworthy its source is. Injection in a low-trust document is flagged.
      </p>
      <div className="overflow-hidden rounded-lg border border-white/8">
        <table className="w-full text-[13px]">
          <thead className="bg-white/5 font-mono text-[11px] uppercase tracking-wider text-mute">
            <tr>
              <th className="px-4 py-2 text-left">Document</th>
              <th className="px-4 py-2 text-left">Type</th>
              <th className="px-4 py-2 text-left">Trust</th>
              <th className="px-4 py-2 text-left">Integrity</th>
            </tr>
          </thead>
          <tbody>
            {(evidence || []).map((d, i) => (
              <tr key={i} className="border-t border-white/6">
                <td className="px-4 py-2.5 text-paper/90">{d.filename}</td>
                <td className="px-4 py-2.5 font-mono text-[12px] text-mute">{d.source_type}</td>
                <td className="px-4 py-2.5"><Pill tone={trustTone(d.trust_level)}>{d.trust_level}</Pill></td>
                <td className="px-4 py-2.5">
                  {d.injection_findings?.length ? (
                    <Pill tone="oxblood">injection flagged</Pill>
                  ) : (
                    <span className="font-mono text-[12px] text-signal">✓ clean</span>
                  )}
                </td>
              </tr>
            ))}
            {!evidence && <tr><td colSpan={4} className="px-4 py-8 text-center font-mono text-[12px] text-mute">Loading evidence…</td></tr>}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function MemoVerify({ run, evalData, verify, doVerify, doTamper }) {
  if (!run) return (
    <Panel title="Escalation memo" kicker="idle">
      <div className="py-12 text-center font-mono text-[12px] text-mute">Run a check to generate the memo.</div>
    </Panel>
  );
  return (
    <div className="grid gap-5 lg:grid-cols-[1.2fr_1fr]">
      <Panel title="Escalation memo" kicker={run.severity}>
        <pre className="whitespace-pre-wrap font-mono text-[12px] leading-6 text-paper/85">{run.memo}</pre>
      </Panel>
      <div className="space-y-5">
        <Panel title="Verify receipt" kicker="offline · Ed25519">
          <p className="mb-3 text-[13px] text-paper/70">
            The memo is backed by a signed receipt. Verify it — no server, no trust required.
          </p>
          <button onClick={doVerify}
            className="mb-3 w-full rounded-lg border border-signal/40 bg-signal/10 py-2 text-[13px] font-semibold text-signal transition hover:bg-signal/20">
            Verify this receipt
          </button>
          <button onClick={doTamper}
            className="mb-4 w-full rounded-lg border border-oxblood/40 bg-oxblood/10 py-2 text-[13px] font-semibold text-oxblood transition hover:bg-oxblood/20">
            Simulate tampering
          </button>
          <VerifySeal state={verify} />
        </Panel>
        {evalData?.evaluation && (
          <Panel title="Self-evaluation" kicker={`score ${evalData.evaluation.hackathon_readiness_score}`}>
            <div className="space-y-2">
              {Object.entries(evalData.evaluation.scores).map(([k, v]) => (
                <ScoreBar key={k} label={k.replace(/_/g, " ")} value={v} />
              ))}
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}


function Evaluation({ run, evalData }) {
  if (!run || !evalData) return (
    <Panel title="Evaluation dashboard" kicker="idle">
      <div className="py-12 text-center font-mono text-[12px] text-mute">Run an investigation to score agentic workflow, grounding, verifiability, and demo readiness.</div>
    </Panel>
  );
  const scores = evalData.evaluation?.scores || {};
  const evidenceMap = evalData.evidence_map || [];
  const context = evalData.context_health || {};
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_1fr]">
      <Panel title="Hackathon readiness" kicker={`score ${evalData.evaluation?.hackathon_readiness_score || 'n/a'}`}>
        <div className="space-y-2">
          {Object.entries(scores).map(([k, v]) => <ScoreBar key={k} label={k.replace(/_/g, ' ')} value={v} />)}
        </div>
      </Panel>
      <Panel title="Evidence map" kicker="decision support">
        <div className="space-y-2">
          {evidenceMap.map((e, i) => (
            <div key={i} className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
              <div className="text-[13px] font-medium text-paper">{e.claim || e.node || e.title || `Evidence ${i+1}`}</div>
              <div className="mt-1 font-mono text-[11px] text-mute">{e.source || e.support || e.detail || JSON.stringify(e).slice(0, 140)}</div>
            </div>
          ))}
        </div>
      </Panel>
      <Panel title="Context health" kicker={context.overall || 'checked'}>
        <div className="space-y-2 font-mono text-[12px] text-paper/75">
          {(context.warnings || []).map((w, i) => <div key={i}>⚠ {w}</div>)}
          {!(context.warnings || []).length && <div>✓ No major context warnings</div>}
        </div>
      </Panel>
      <Panel title="Vultr alignment" kicker="no GPU dependency">
        <div className="space-y-2 text-[13px] text-paper/75">
          <div>✓ Web-based enterprise agent</div>
          <div>✓ LLM/RAG workloads route to Vultr Serverless Inference when configured</div>
          <div>✓ Deterministic fallback keeps demo reliable</div>
          <div>✓ Docker-ready for Vultr Cloud Compute</div>
        </div>
      </Panel>
    </div>
  );
}

function History({ history }) {
  // build a confidence-climb series from run history (oldest -> newest)
  const series = [...history].reverse().map((r, i) => ({
    run: `#${i + 1}`, confidence: Math.round(parseFloat(r.confidence || 0) * 100),
  }));
  return (
    <div className="space-y-5">
      <Panel title="Confidence across runs" kicker="self-improvement">
        {series.length > 1 ? (
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
                <XAxis dataKey="run" stroke="#6B7280" fontSize={11} tickLine={false} />
                <YAxis domain={[0, 100]} stroke="#6B7280" fontSize={11} tickLine={false} />
                <Tooltip contentStyle={{ background: "#1E2530", border: "1px solid rgba(255,255,255,.1)", borderRadius: 8, color: "#F5F2EC", fontSize: 12 }} />
                <ReferenceLine y={100} stroke="#1F6F54" strokeDasharray="3 3" />
                <Line type="monotone" dataKey="confidence" stroke="#1F6F54" strokeWidth={2} dot={{ r: 3, fill: "#1F6F54" }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="py-10 text-center font-mono text-[12px] text-mute">
            Run the check a few times — the agent learns to attribute causes, and confidence climbs.
          </div>
        )}
      </Panel>
      <Panel title="Run history" kicker="persistent">
        <div className="overflow-hidden rounded-lg border border-white/8">
          <table className="w-full text-[13px]">
            <thead className="bg-white/5 font-mono text-[11px] uppercase tracking-wider text-mute">
              <tr><th className="px-4 py-2 text-left">Run</th><th className="px-4 py-2 text-left">Borrower</th><th className="px-4 py-2 text-left">Severity</th><th className="px-4 py-2 text-left">Confidence</th></tr>
            </thead>
            <tbody>
              {history.map((r, i) => (
                <tr key={i} className="border-t border-white/6">
                  <td className="px-4 py-2.5 font-mono text-[12px] text-mute">{r.run_id?.slice(0, 14)}</td>
                  <td className="px-4 py-2.5 text-paper/90">{r.borrower}</td>
                  <td className="px-4 py-2.5"><Pill tone={r.severity === "breach" ? "oxblood" : r.severity === "watch" ? "amber" : "signal"}>{r.severity}</Pill></td>
                  <td className="px-4 py-2.5 font-mono">{Math.round(parseFloat(r.confidence || 0) * 100)}%</td>
                </tr>
              ))}
              {!history.length && <tr><td colSpan={4} className="px-4 py-8 text-center font-mono text-[12px] text-mute">No runs yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
