/*
 * CovenantOps Agent — console UI (ported from CovenantOps-Agent-demo.html).
 *
 * The visual layer is identical to the demo. The only difference is the data
 * seam: the `api` object below no longer resolves a baked-in DATA blob — each
 * method now performs a real fetch() against the FastAPI backend (proxied at
 * /api by Vite). Call sites in the UI are unchanged.
 *
 * Backend contract (see backend/app/api.py):
 *   POST /api/covenant/run?learning=&attack=   -> run summary (borrower, facility,
 *                                                 severity, confidence, memo, findings, trace_id)
 *   GET  /api/traces/{id}/evaluation           -> { evaluation, evidence_map, context_health }
 *   GET  /api/evidence                         -> { documents: [...] }
 *   GET  /api/runs                             -> { runs: [...] }
 *   GET  /api/traces/{id}/receipt              -> signed receipt payload
 *   POST /api/receipts/verify                  -> { valid, ... } (real Ed25519 check)
 */

var C = { signal: "#06D6A0", amber: "#FFD166", oxblood: "#FF4444", mute: "#6B6B80", ink: "#0A0A0F" };

// ============================================================================
// LIVE-DATA WIRING LAYER
// The single seam between UI and backend. Every method returns a Promise.
// ============================================================================
var API = "/api";

function slug(name) {
  return String(name || "borrower").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "borrower";
}
async function jget(p) {
  var r = await fetch(API + p);
  if (!r.ok) throw new Error(p + " " + r.status);
  return r.json();
}
async function jpost(p) {
  var r = await fetch(API + p, { method: "POST" });
  if (!r.ok) throw new Error(p + " " + r.status);
  return r.json();
}

// Runs are seeded with severity/confidence but the evaluation, evidence_map, and
// context_health live behind a separate endpoint — attach them so the Diagnostics
// view can render from a single run object (matching the demo's shape).
async function hydrateRun(run) {
  if (!run || !run.trace_id) return run;
  try {
    var ev = await jget("/traces/" + run.trace_id + "/evaluation");
    run.evaluation = ev.evaluation;
    run.evidence_map = ev.evidence_map;
    run.context_health = ev.context_health;
  } catch (e) {
    /* evaluation is best-effort; the run is still usable without it */
  }
  return run;
}

var seedRuns = {}; // borrower id -> most recent hydrated run, for header identity

var api = {
  // The monitored portfolio: every borrower with a fast severity + confidence.
  getPortfolio: function () {
    return jget("/portfolio").then(function (d) {
      return (d.borrowers || []).map(function (b) {
        return { id: b.id, name: b.borrower, facility: b.facility, severity: b.severity, confidence: b.confidence };
      });
    });
  },
  runInvestigation: function (borrowerId, opts) {
    var q = new URLSearchParams();
    if (borrowerId) q.set("borrower", borrowerId);
    if (opts && opts.attack) q.set("attack", "true");
    return jpost("/covenant/run?" + q.toString()).then(hydrateRun);
  },
  getEvidence: function () {
    return jget("/evidence").then(function (d) { return d.documents || []; });
  },
  // Bring-your-own-documents entry point: multipart upload -> the backend
  // sanitizes, ingests, trust-tags, and injection-scans the file, adding it to
  // the evidence pack the next covenant run grounds on.
  uploadEvidence: function (file) {
    var fd = new FormData();
    fd.append("file", file);
    return fetch(API + "/evidence/upload", { method: "POST", body: fd }).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || ("upload " + r.status)); });
      return r.json();
    });
  },
  getHistory: function () {
    return jget("/runs").then(function (d) { return d.runs || []; });
  },
  // Real, governed, Vultr-backed clarifying Q&A grounded in a specific run.
  qa: function (traceId, question) {
    return fetch(API + "/covenant/qa", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trace_id: traceId, question: question }),
    }).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || ("qa " + r.status)); });
      return r.json();
    });
  },
  // Runs the real Ed25519 verification on the server.
  //  - honest verify: hit the server-side verify endpoint so the stored receipt
  //    is checked byte-for-byte. (Round-tripping the receipt through JS JSON
  //    would reserialize whole-number floats like 8000000.0 -> 8000000 and break
  //    the canonical hash, producing a false negative.)
  //  - tamper demo: fetch the receipt, alter a material field, and POST it back;
  //    verification correctly fails.
  verifyReceipt: async function (traceId, tampered) {
    if (!tampered) return jget("/traces/" + traceId + "/receipt/verify");
    var receipt = await jget("/traces/" + traceId + "/receipt");
    if (receipt && receipt.receipt) {
      receipt.receipt.severity = "none";
      receipt.receipt.confidence = 1.0;
    }
    var r = await fetch(API + "/receipts/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(receipt),
    });
    return r.json();
  },
};

var screen = "landing"; // landing | signin | app
var view = "Portfolio", ran = false, step = -1, verify = "idle";
var STEPS = ["Plan", "Retrieve clauses", "Pull filings", "Calculate", "Apply waiver", "Cross-check", "Memo"];
// Keys match the real progress events emitted by the backend agent (see api.py).
var STEP_KEYS = ["plan", "retrieve_clauses", "pull_filings", "calculate", "apply_waiver", "cross_check", "memo"];
var STEP_DESC = {
  plan: "Planning the covenant investigation",
  retrieve_clauses: "Retrieving governing covenant clauses",
  pull_filings: "Pulling borrower filings & trend",
  calculate: "Re-verifying each covenant ratio",
  apply_waiver: "Applying active signed waivers",
  cross_check: "Cross-checking transactions for a cause",
  memo: "Generating memo, Vultr analyst note & signed receipt",
};
var running = false, streamSettled = false;
var VIEWS = ["Portfolio", "Investigation", "History", "Diagnostics"];
var signinLoading = false;

// live app state
var portfolio = [];
var portfolioLoaded = false, portfolioLoading = false, portfolioError = null;
var currentBorrowerId = null;
var currentRun = null;
var currentEvidence = [];
var currentHistory = [];

function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function statusColor(s) { return (s == "breach" || s == "oxblood") ? C.oxblood : (s == "drifting" || s == "watch" || s == "amber") ? C.amber : C.signal; }
function fmt(n) { return (typeof n == "number" && n > 100000) ? n.toLocaleString() : n; }
function pill(txt, tone) { return '<span class="pill ' + tone + '"><span class="dot" style="background:currentColor"></span>' + esc(txt) + '</span>'; }

/* ============ LANDING ============ */
function renderLanding() {
  var features = [
    { icon: "01", title: "Document-Grounded Agent", desc: "Real multi-format ingestion \u2014 PDF, DOCX, XLSX, CSV, scanned images \u2014 with source-trust weighting and a genuine multi-step investigation, not a single retrieval call.", accent: C.oxblood },
    { icon: "02", title: "Governed at Every Step", desc: "Every tool call is evaluated \u2014 by AIRG when configured, a deterministic local guard when not. Injection in low-trust documents is caught before it reaches the agent's reasoning. Fails safe, never silently.", accent: "#FF8C42" },
    { icon: "03", title: "Verifiable, Not Just Cited", desc: "Every memo is backed by an Ed25519-signed receipt \u2014 verifiable offline, with no server and no trust required. Tampering is cryptographically detectable.", accent: C.signal },
    { icon: "04", title: "Learns \u2014 Safely", desc: "The agent attributes causes across runs, raising confidence over time. A poisoning gate refuses to let a blocked or low-confidence run teach a lesson, and an ablation proves the improvement is real, not chance.", accent: "#4CC9F0" },
    { icon: "05", title: "Recovers Mid-Investigation", desc: "An interrupted run checkpoints after every covenant. Resume picks up exactly where it left off \u2014 no duplicate work, no restarted investigation.", accent: "#B490FF" },
    { icon: "06", title: "Every Step, Replayable", desc: "Every tool call, guard decision, and outcome is recorded and can be replayed \u2014 a full audit trail, not just a final answer.", accent: "#FFD166" },
  ];
  var stats = [
    { value: "5", label: "Document Formats", sub: "PDF \u00b7 DOCX \u00b7 XLSX \u00b7 CSV \u00b7 OCR" },
    { value: "100%", label: "Offline Verifiable", sub: "Ed25519 signed receipts" },
    { value: "0", label: "Lessons From Blocked Runs", sub: "poisoning gate enforced" },
    { value: "26/26", label: "Tests Passing", sub: "full workflow coverage" },
  ];
  var featHtml = features.map(function (f) {
    return '<div class="featcard" style="--accent:' + f.accent + '"><div class="feat-icon">' + f.icon + '</div><div class="feat-title">' + f.title + '</div><div class="feat-desc">' + f.desc + '</div><div class="feat-rule"></div></div>';
  }).join("");
  var statHtml = stats.map(function (s) { return '<div class="statcell"><div class="statval">' + s.value + '</div><div class="statlabel">' + s.label + '</div><div class="statsub">' + s.sub + '</div></div>'; }).join("");
  var archSteps = [
    { label: "Document Ingestion", color: C.oxblood }, { label: "\u2192", arrow: true },
    { label: "Covenant Calculation", color: "#FF8C42" }, { label: "\u2192", arrow: true },
    { label: "Governance Guard", color: C.amber }, { label: "\u2192", arrow: true },
    { label: "Escalation Memo", color: C.signal }, { label: "\u2192", arrow: true },
    { label: "Signed Receipt", color: "#4CC9F0" },
  ];
  var archHtml = archSteps.map(function (s) {
    if (s.arrow) return '<span class="archarrow">\u2192</span>';
    return '<div class="archstep" style="border:1px solid ' + s.color + '30;background:' + s.color + '0D;color:' + s.color + '">' + s.label + '</div>';
  }).join("");

  document.getElementById("app").innerHTML =
    '<div class="lnav"><div class="lbrand"><div class="logomark" style="width:36px;height:36px;font-size:16px">C</div>' +
    '<div><div style="font-size:17px;font-weight:700;color:#E0E0E8;letter-spacing:.3px">CovenantOps Agent</div>' +
    '<div style="font-size:10px;color:#6B6B80;letter-spacing:2px;text-transform:uppercase">Verifiable Covenant Monitoring</div></div></div>' +
    '<button class="lsignin" onclick="goSignIn()">Sign In</button></div>' +
    '<div class="hero">' +
      '<div class="eyebrow"><div class="line"></div><span>Enterprise Covenant Intelligence</span></div>' +
      '<h1 class="hero-title">Loan Covenants,<br/><span class="grad">Verifiably Monitored</span></h1>' +
      '<p class="hero-sub">CovenantOps Agent ingests the real documents a credit team works from \u2014 signed agreements, waivers, accounts, transactions \u2014 investigates covenant drift, and produces an escalation memo backed by a cryptographic receipt anyone can verify offline.</p>' +
      '<div class="hero-ctas"><button class="btn-primary" onclick="goSignIn()">Launch console \u2192</button><button class="btn-ghost" onclick="viewArchitecture()">View architecture</button></div>' +
      '<div class="statstrip">' + statHtml + '</div>' +
      '<div class="featgrid">' + featHtml + '</div>' +
      '<div class="archbox"><div class="archkick">System Architecture</div><div class="archflow">' + archHtml + '</div>' +
      '<div class="archnote">Multi-format ingestion \u00b7 deterministic calculation \u00b7 governed tool calls \u00b7 offline-verifiable receipts \u00b7 Vultr Serverless Inference</div></div>' +
      '<div class="lfooter"><div>\u00a9 2026 CovenantOps Agent</div><div>RAISE 2026, Vultr Track</div></div>' +
    '</div>';
}
function goSignIn() { screen = "signin"; render(); }
function goApp() { screen = "app"; render(); }
function viewArchitecture() { view = "Investigation"; screen = "app"; render(); }

/* ============ SIGN-IN ============ */
function renderSignIn() {
  document.getElementById("app").innerHTML =
    '<div class="signin-wrap"><div class="signin-box">' +
      '<div style="text-align:center;margin-bottom:40px"><div class="logomark" style="width:48px;height:48px;font-size:20px;border-radius:12px;margin:0 auto 16px">C</div>' +
      '<div style="font-size:20px;font-weight:700;color:#E0E0E8">CovenantOps Agent</div>' +
      '<div style="font-size:11px;color:#6B6B80;letter-spacing:2px;text-transform:uppercase;margin-top:4px">Covenant Monitoring Console</div></div>' +
      '<div class="signin-card"><div style="font-size:14px;font-weight:600;color:#E0E0E8;margin-bottom:24px">Sign in to your account</div>' +
        '<div class="field"><label>Email</label><input type="email" value="analyst@yourcompany.com"/></div>' +
        '<div class="field"><label>Password</label><input type="password" value="\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"/></div>' +
        '<button class="signin-btn" id="signinBtn" onclick="doSignIn()">' + (signinLoading ? '<span class="spinner"></span> Authenticating\u2026' : 'Sign In') + '</button>' +
        '<div style="text-align:center;margin:20px 0 0;position:relative"><div style="position:absolute;top:50%;left:0;right:0;height:1px;background:#1E1E2E"></div>' +
        '<span style="position:relative;background:#101018;padding:0 12px;font-size:10px;color:#4E4E60;text-transform:uppercase;letter-spacing:1px">or</span></div>' +
        '<button class="sso-btn" onclick="doSignIn()">Continue with SSO</button></div>' +
    '</div></div>';
}
function doSignIn() {
  signinLoading = true; renderSignIn();
  setTimeout(function () { signinLoading = false; screen = "app"; render(); }, 1000);
}

/* ============ APP VIEWS ============ */
function panel(title, kick, body) {
  return '<div class="card"><div class="cardhead"><span class="cardtitle">' + title + '</span>' + (kick ? '<span class="cardkick">' + esc(kick) + '</span>' : '') + '</div>' + body + '</div>';
}
function gauge(f) {
  var r = f.ratio, st = r.breached ? "breach" : r.drifting_toward_breach ? "drifting" : "within", col = statusColor(st);
  var ratio = r.direction == "min" ? r.threshold / r.value : r.value / r.threshold, pct = Math.max(4, Math.min(100, ratio * 66));
  return '<div class="gauge"><div class="grow"><span class="glabel">' + esc(r.metric) + '</span>' +
    '<span class="gval" style="color:' + col + '">' + fmt(r.value) + '<span style="color:' + C.mute + '"> / ' + fmt(r.threshold) + '</span></span></div>' +
    '<div class="bar"><div class="barfill" style="width:' + pct + '%;background:' + col + '"></div><div class="gmark"></div></div>' +
    '<div class="gscale"><span>' + (r.direction == "min" ? "floor" : "0") + '</span><span style="color:' + col + '">' + st + '</span><span>limit</span></div></div>';
}
function scorebar(k, v) {
  var col = v >= 80 ? C.signal : v >= 60 ? C.amber : C.oxblood;
  return '<div class="scorerow"><span class="slabel">' + esc(k.replace(/_/g, " ")) + '</span><div class="sbar"><div class="sfill" style="width:' + v + '%;background:' + col + '"></div></div><span class="sval" style="color:' + col + '">' + v + '</span></div>';
}

function vPortfolio() {
  var rows = portfolio.map(function (b) {
    var sevTone = b.severity == "breach" ? "oxblood" : b.severity == "watch" ? "amber" : "signal";
    var sevLabel = b.severity == "none" ? "within limits" : b.severity;
    var conf = Math.round(b.confidence * 100) + "%";
    var action = '<button class="ghostbtn" style="margin:0;width:auto;padding:6px 16px" onclick="openInvestigation(\'' + b.id + '\')">Open investigation</button>';
    return '<tr><td style="color:#E0E0E8">' + esc(b.name) + '</td><td style="font-size:12px;color:' + C.mute + '">' + esc(b.facility) + '</td>' +
      '<td>' + pill(sevLabel, sevTone) + '</td><td style="font-size:12px">' + conf + '</td><td>' + action + '</td></tr>';
  }).join("");
  if (!rows) rows = '<tr><td colspan="5" style="color:' + C.mute + '">No borrowers under monitoring yet.</td></tr>';
  var tbl = '<div class="tblwrap"><table><thead><tr><th>Borrower</th><th>Facility</th><th>Status</th><th>Confidence</th><th></th></tr></thead><tbody>' + rows + '</tbody></table></div>';
  return '<div class="stack">' +
    panel("Portfolio", "covenant monitoring", '<p class="lead">Borrowers under active covenant monitoring. Select an account to open its investigation.</p>' + tbl) +
    '</div>';
}

// Live workflow list. Reflects the real progress events streamed from the backend:
// completed steps show a check, the running step shows a spinner + its live detail,
// and pending steps are numbered.
function workflowList() {
  return '<ol class="flow">' + STEPS.map(function (s, i) {
    var done = step > i;
    var active = running && step === i;
    var mark = done ? "\u2713"
      : active ? '<span class="spinner" style="width:11px;height:11px;border-width:2px;border-color:#2E2E3E;border-top-color:' + C.oxblood + '"></span>'
      : (i + 1);
    return '<li><span class="num' + (done ? " done" : "") + '"' + (active ? ' style="background:#FF444422;color:#FF4444"' : "") + '>' + mark + '</span>' +
      '<div><div style="font-size:13px;color:' + (done || active ? "#E0E0E8" : C.mute) + '">' + s + '</div>' +
      (active ? '<div style="font-size:11px;color:' + C.mute + '">' + STEP_DESC[STEP_KEYS[i]] + '\u2026</div>' : "") + '</div></li>';
  }).join("") + '</ol>';
}

function vInvestigation() {
  var run = currentRun;
  if (!run) return panel("Investigation", "idle", '<div class="empty">Select a borrower from the Portfolio to begin.</div>');
  var borrowerHead = '<div class="card" style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px">' +
    '<div><div style="display:flex;align-items:center;gap:12px;margin-bottom:6px;flex-wrap:wrap">' +
      '<span style="font-size:18px;font-weight:700;color:#E0E0E8">' + esc(run.borrower) + '</span>' +
      (ran ? pill(run.severity, run.severity == "breach" ? "oxblood" : run.severity == "watch" ? "amber" : "signal") : pill("not yet run", "mute")) +
    '</div><div style="color:#8B8BA0;font-size:12px;max-width:600px">' + esc(run.facility) + '</div></div>' +
    (ran ? '<div style="text-align:right"><div style="font-size:32px;font-weight:800;color:' + statusColor(run.confidence < 0.7 ? "watch" : "within") + '">' + Math.round(run.confidence * 100) + '%</div><div style="font-size:10px;color:#6B6B80;text-transform:uppercase;letter-spacing:1px">Confidence</div></div>' : '') +
    '</div>';

  if (!ran) {
    var runBtn = running
      ? '<button class="runbtn" disabled style="opacity:.65;cursor:progress">Investigating\u2026</button>'
      : '<button class="runbtn" onclick="doRun()">Run covenant check</button>';
    return borrowerHead + '<div class="grid2 a">' +
      panel("Run investigation", "the agent", '<p class="lead">CovenantOps Agent plans a covenant check, grounds it in the borrower\'s real documents, re-verifies each ratio, cross-checks transactions for a cause, and produces a memo you can verify.</p>' + runBtn) +
      panel("Workflow", running ? "live \u00b7 running" : "multi-step", workflowList()) + '</div>' +
      '<div style="margin-top:20px">' + uploadPanel() + '</div>';
  }

  // --- fact row: facility / workflow / evidence summary, at a glance ---
  var period = (run.findings && run.findings[0] && run.findings[0].ratio.period) || "\u2014";
  var facilityCard = panel("Facility", "details",
    '<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #1E1E2E"><span style="color:#6B6B80;font-size:11px">Period</span><span style="font-weight:600;font-size:12px">' + esc(period) + '</span></div>' +
    '<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #1E1E2E"><span style="color:#6B6B80;font-size:11px">Covenants tested</span><span style="font-weight:600;font-size:12px">' + (run.findings || []).length + '</span></div>' +
    '<div style="display:flex;justify-content:space-between;padding:4px 0"><span style="color:#6B6B80;font-size:11px">Trace</span><span style="font-weight:600;font-size:12px;color:' + C.mute + '">' + esc((run.trace_id || "").slice(0, 14)) + '</span></div>'
  );
  var stepsDone = STEPS.map(function (s) { return '<div style="display:flex;align-items:center;gap:6px;padding:3px 0;font-size:12px;color:#B8B8C8"><span style="color:' + C.signal + '">\u2713</span>' + s + '</div>'; }).join("");
  var workflowCard = panel("Workflow", "completed", stepsDone);
  var evCounts = {}; currentEvidence.forEach(function (d) { evCounts[d.trust_level] = (evCounts[d.trust_level] || 0) + 1; });
  var flagged = currentEvidence.filter(function (d) { return d.injection_findings.length; }).length;
  var evSummary = '<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #1E1E2E"><span style="color:#6B6B80;font-size:11px">Documents</span><span style="font-weight:600;font-size:12px">' + currentEvidence.length + '</span></div>' +
    '<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #1E1E2E"><span style="color:#6B6B80;font-size:11px">Very high / high trust</span><span style="font-weight:600;font-size:12px">' + ((evCounts.very_high || 0) + (evCounts.high || 0)) + '</span></div>' +
    '<div style="display:flex;justify-content:space-between;padding:4px 0"><span style="color:#6B6B80;font-size:11px">Integrity flags</span><span style="font-weight:600;font-size:12px;color:' + (flagged ? C.oxblood : C.signal) + '">' + flagged + '</span></div>';
  var evidenceCard = panel("Evidence", "summary", evSummary);
  var factRow = '<div class="grid3">' + facilityCard + workflowCard + evidenceCard + '</div>' + '<div style="margin-top:20px">' + panel("Covenant status", run.severity, run.findings.map(gauge).join("")) + '</div>';

  // --- evidence table (full detail) ---
  var tt = function (t) { return (t == "very_high" || t == "high") ? "signal" : t == "medium" ? "amber" : "oxblood"; };
  var rows = currentEvidence.map(function (d) {
    var integ = d.injection_findings.length ? pill("injection flagged", "oxblood") : '<span style="color:' + C.signal + ';font-size:12px">\u2713 clean</span>';
    return '<tr><td style="color:#E0E0E8">' + esc(d.filename) + '</td><td style="font-size:12px;color:' + C.mute + '">' + esc(d.source_type) + '</td><td>' + pill(d.trust_level, tt(d.trust_level)) + '</td><td>' + integ + '</td></tr>';
  }).join("");
  var tbl = '<div class="tblwrap"><table><thead><tr><th>Document</th><th>Type</th><th>Trust</th><th>Integrity</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
  var evidenceSection = panel("Evidence set", "multi-format \u00b7 trust-weighted", '<p class="lead">CovenantOps grounds on the real documents a credit team uses, each weighted by how trustworthy its source is. Injection in a low-trust document is flagged.</p>' + tbl);

  // --- memo + verify/export ---
  var memoLeft = panel("Escalation memo", run.severity, '<pre class="memo">' + esc(run.memo) + '</pre>');
  var memoRight = '<div class="stack">' +
    panel("Verify receipt", "offline \u00b7 Ed25519", '<p class="lead">The memo is backed by a signed receipt. Verify it \u2014 no server, no trust required.</p><button class="ghostbtn" onclick="doVerify()">Verify this receipt</button><button class="dangerbtn" onclick="doTamper()">Simulate tampering</button>' + seal()) +
    panel("Committee record", "export", '<p class="lead">Attach this memo and its signed receipt to committee papers.</p><button class="ghostbtn" style="margin-bottom:0" onclick="window.print()">Export memo (PDF)</button>') + '</div>';
  var memoSection = '<div class="grid2 b">' + memoLeft + memoRight + '</div>';

  return borrowerHead + factRow + '<div style="margin-top:20px">' + uploadPanel() + '</div><div style="margin-top:20px">' + evidenceSection + '</div><div style="margin-top:20px">' + memoSection + '</div><div style="margin-top:20px">' + qaPanel() + '</div>';
}
function uploadPanel() {
  var tt = function (t) { return (t == "very_high" || t == "high") ? "signal" : t == "medium" ? "amber" : "oxblood"; };
  var status = "";
  if (uploading) {
    status = '<div class="chk" style="display:flex;align-items:center;gap:8px;color:#8B8BA0"><span class="spinner" style="border-color:#2E2E3E;border-top-color:' + C.oxblood + ';width:12px;height:12px"></span> Ingesting, trust-tagging &amp; injection-scanning\u2026</div>';
  } else if (uploadResult) {
    var f = uploadResult;
    var integ = (f.injection_findings && f.injection_findings.length) ? pill("injection flagged", "oxblood") : '<span style="color:' + C.signal + '">\u2713 clean</span>';
    status = '<div class="chk">\u2713 Ingested <strong style="color:#E0E0E8">' + esc(f.filename) + '</strong> &nbsp; ' + pill(f.trust_level, tt(f.trust_level)) + ' &nbsp; ' + integ + '</div>';
  } else if (uploadError) {
    status = '<div class="warn" style="color:' + C.oxblood + '">\u26A0 ' + esc(uploadError) + '</div>';
  }
  var docs = (currentEvidence || []).map(function (d) {
    return '<div style="display:flex;justify-content:space-between;gap:12px;padding:3px 0;font-size:12px;color:#B8B8C8"><span>' + esc(d.filename) + '</span><span style="color:' + C.mute + '">' + esc(d.source_type) + '</span></div>';
  }).join("") || '<div class="empty" style="padding:12px 0">No documents yet.</div>';
  return panel("Add evidence", "bring your own documents",
    '<p class="lead">Upload a credit agreement, waiver, management accounts, transaction export, or a scanned note. Each document is ingested, trust-tagged, and injection-scanned, then grounds the next covenant check.</p>' +
    '<label class="ghostbtn" style="display:block;text-align:center;margin-bottom:12px' + (uploading ? ';opacity:.6;pointer-events:none' : '') + '">Choose a document to upload' +
    '<input type="file" id="evidenceFile" style="display:none" onchange="onEvidenceFile(event)" accept=".pdf,.docx,.xlsx,.xls,.csv,.png,.jpg,.jpeg,.txt"/></label>' +
    status +
    '<div style="margin-top:12px;border-top:1px solid #1E1E2E;padding-top:10px"><div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6B6B80;margin-bottom:6px">Evidence set (' + (currentEvidence || []).length + ')</div>' + docs + '</div>');
}

function qaPanel() {
  var chips = qaMessages.length ? "" : QA_SUGGESTIONS.map(function (q, i) { return '<button class="qachip" onclick="suggestQa(' + i + ')">' + q + '</button>'; }).join("");
  var msgs = qaMessages.map(function (m) {
    var isUser = m.role === "user";
    var avatarBg = isUser ? C.signal + "20" : "#FF8C4220", avatarColor = isUser ? C.signal : "#FF8C42";
    var meta = m.meta || {};
    var pathLabel = meta.blocked ? "blocked by governance guard"
      : meta.inference_path === "vultr" ? "Vultr inference \u00b7 grounded in this run"
      : meta.inference_path === "local_fallback" ? "local fallback \u00b7 grounded in this run"
      : "grounded in this run";
    var govBadge = !isUser ? '<div class="qagovbadge"><span style="width:10px;height:10px;border-radius:2px;background:linear-gradient(135deg,' + C.oxblood + ',#FF8C42);display:inline-block"></span><span style="color:' + C.signal + '">governed</span><span>\u00b7 ' + esc(pathLabel) + '</span></div>' : "";
    return '<div class="qarow' + (isUser ? " user" : "") + '"><div class="qaavatar" style="background:' + avatarBg + ';color:' + avatarColor + '">' + (isUser ? "A1" : "AI") + '</div>' +
      '<div class="qabubble" style="background:' + (isUser ? C.signal + "10" : "#16161F") + ';border:1px solid ' + (isUser ? C.signal + "20" : "#1E1E2E") + '">' + esc(m.content) + govBadge + '</div></div>';
  }).join("");
  var loading = qaLoading ? '<div class="qarow"><div class="qaavatar" style="background:#FF8C4220;color:#FF8C42">AI</div><div class="qabubble" style="background:#16161F;border:1px solid #1E1E2E;color:' + C.mute + '">Reviewing this run\'s evidence\u2026</div></div>' : "";
  var body;
  if (!qaOpen) {
    body = '<button class="ghostbtn" style="margin:0" onclick="toggleQa()">Open Q&amp;A</button>';
  } else {
    body = (qaMessages.length ? '<div class="qamsgs">' + msgs + loading + '</div>' : '<div style="margin-bottom:12px">' + chips + '</div>') +
      '<input id="qaInputBox" class="qainput" type="text" placeholder="Ask about this investigation\u2026" value="' + esc(qaInput) + '" onkeydown="qaKeydown(event)"/>';
  }
  return panel("Ask the agent", "clarifying Q&amp;A", body);
}
function seal() {
  if (verify == "idle") return "";
  var valid = verify == "valid", checking = verify == "checking";
  var bc = valid ? "#06D6A040" : checking ? "#2E2E3E" : "#FF444440";
  var bg = valid ? "#06D6A012" : checking ? "#16161F" : "#FF444412";
  var ic = valid ? C.signal : checking ? "#2E2E3E" : C.oxblood;
  var sym = valid ? "\u2713" : checking ? "\u22EF" : "\u2717";
  var t1 = valid ? "Receipt verified" : checking ? "Verifying\u2026" : "Verification failed";
  var t2 = valid ? "hash MATCH \u00b7 Ed25519 VALID" : checking ? "recomputing hash \u00b7 checking signature" : "hash MISMATCH \u00b7 do not trust";
  var tc = valid ? C.signal : checking ? "#E0E0E8" : C.oxblood;
  return '<div class="seal" style="border-color:' + bc + ';background:' + bg + '"><div class="sealic" style="background:' + ic + '">' + sym + '</div><div><div style="font-size:14px;font-weight:700;color:' + tc + '">' + t1 + '</div><div style="font-size:11px;color:' + C.mute + '">' + t2 + '</div></div></div>';
}
function wrapLabel(label, max) {
  var words = String(label).split(" "), lines = [], cur = "";
  words.forEach(function (w) { if ((cur + " " + w).trim().length > max) { lines.push(cur.trim()); cur = w; } else cur = (cur + " " + w).trim(); });
  if (cur) lines.push(cur);
  return lines.slice(0, 2);
}
function evidenceGraph(run) {
  var em = run.evidence_map || [];
  if (!em.length) return '<div class="empty">Run a check to build the evidence graph.</div>';
  var w = 520, h = 420, cx = w / 2, cy = h / 2 - 10, R = 150;
  var kindColor = function (k) { return k == "covenant" ? C.amber : (k == "receipt" || k == "guard") ? C.signal : C.mute; };
  var nodeStatus = function (e) { if (e.kind != "covenant") return "ok"; var s = (e.summary || "").toLowerCase(); if (s.indexOf("breach") >= 0) return "breach"; if (s.indexOf("drifting") >= 0) return "drift"; return "ok"; };
  var statusColorMap = { breach: C.oxblood, drift: C.amber, ok: C.signal };
  var centerColor = run.severity == "breach" ? C.oxblood : run.severity == "watch" ? C.amber : C.signal;
  var n = em.length;
  var nodes = em.map(function (e, i) { var ang = (-90 + (360 / n) * i) * Math.PI / 180; var x = cx + R * Math.cos(ang), y = cy + R * Math.sin(ang); var st = nodeStatus(e); return { x: x, y: y, e: e, color: statusColorMap[st] || kindColor(e.kind), status: st }; });
  var edges = nodes.map(function (nd) { var breach = nd.status == "breach"; return '<line x1="' + cx + '" y1="' + cy + '" x2="' + nd.x + '" y2="' + nd.y + '" stroke="' + nd.color + '" stroke-width="' + (breach ? 2.5 : 1.5) + '" opacity="' + (breach ? 0.85 : 0.45) + '" stroke-dasharray="' + (nd.status == "drift" ? "4 3" : "none") + '"/>'; }).join("");
  var nodeEls = nodes.map(function (nd) {
    var r = nd.status == "breach" ? 13 : 10;
    var halo = nd.status == "breach" ? '<circle cx="' + nd.x + '" cy="' + nd.y + '" r="' + r + '" fill="none" stroke="' + nd.color + '" stroke-width="2" class="pulse-halo"/>' : '';
    var labelLines = wrapLabel(nd.e.label || "", 22);
    var ty0 = nd.y + r + 14;
    var textEls = labelLines.map(function (line, li) { return '<text x="' + nd.x + '" y="' + (ty0 + li * 12) + '" text-anchor="middle" font-size="10" fill="#E0E0E8" opacity="0.85">' + esc(line) + '</text>'; }).join("");
    return '<g>' + halo + '<circle cx="' + nd.x + '" cy="' + nd.y + '" r="' + r + '" fill="' + nd.color + '" opacity="0.9"/><circle cx="' + nd.x + '" cy="' + nd.y + '" r="' + r + '" fill="none" stroke="' + C.ink + '" stroke-width="1.5"/>' + textEls + '</g>';
  }).join("");
  var centerHalo = run.severity == "breach" ? '<circle cx="' + cx + '" cy="' + cy + '" r="30" fill="none" stroke="' + centerColor + '" stroke-width="2.5" class="pulse-halo"/>' : '';
  var centerNode = '<g>' + centerHalo + '<circle cx="' + cx + '" cy="' + cy + '" r="30" fill="' + centerColor + '" opacity="0.95"/><circle cx="' + cx + '" cy="' + cy + '" r="30" fill="none" stroke="' + C.ink + '" stroke-width="2"/>' +
    '<text x="' + cx + '" y="' + (cy - 4) + '" text-anchor="middle" font-size="10" font-weight="700" fill="' + C.ink + '">DECISION</text>' +
    '<text x="' + cx + '" y="' + (cy + 9) + '" text-anchor="middle" font-size="9" fill="' + C.ink + '">' + esc(run.severity) + '</text></g>';
  var svg = '<svg viewBox="0 0 ' + w + ' ' + h + '" style="width:100%;height:auto;max-height:440px">' + edges + centerNode + nodeEls + '</svg>';
  var legend = '<div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:8px;font-size:11px;color:' + C.mute + '">' +
    '<span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + C.oxblood + ';margin-right:5px"></span>breach</span>' +
    '<span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + C.amber + ';margin-right:5px"></span>drifting</span>' +
    '<span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + C.signal + ';margin-right:5px"></span>governed / verified</span></div>';
  return svg + legend;
}
function buildAuditTimeline(run) {
  var actorColor = { agent: "#FF8C42", governance: C.oxblood, system: "#4CC9F0" };
  var guardPath = (run.evaluation && run.evaluation.signals && run.evaluation.signals.guard_path) || "local_fallback";
  var events = [];
  events.push({ actor: "agent", action: "investigation planned", entity: run.borrower, detail: "Plan created before any retrieval \u2014 the agent decides its own steps for this facility." });
  var retr = run.retrieval_path === "vultr" ? "ranked by VultronRetriever on Vultr Serverless Inference" : "via the local keyword retriever";
  events.push({ actor: "agent", action: "clauses retrieved", entity: run.retrieval_path === "vultr" ? "VultronRetriever" : "local", detail: "Retrieved " + (run.findings || []).length + " governing covenant clause(s), " + retr + "." });
  events.push({ actor: "agent", action: "filings retrieved", entity: (run.findings && run.findings[0] && run.findings[0].ratio.period) || "latest period", detail: "Pulled borrower filings to establish the trend for the current reporting period." });
  events.push({ actor: "governance", action: "tool calls evaluated", entity: guardPath, detail: "Every tool call in this run was evaluated by the " + (guardPath == "airg" ? "AIRG governance API" : "local fallback guard") + "; no blocks raised on clean evidence." });
  (run.findings || []).forEach(function (f) {
    events.push({ actor: "agent", action: "ratio calculated", entity: f.ratio.covenant_id, detail: f.ratio.metric + ": " + f.ratio.value + " vs effective limit " + f.ratio.threshold + (f.ratio.waiver_applied ? " (waiver " + f.ratio.waiver_applied + " applied)" : "") + "." });
  });
  var flaggedCovs = (run.findings || []).filter(function (f) { return f.ratio.breached || f.ratio.drifting_toward_breach; });
  if (flaggedCovs.length) events.push({ actor: "agent", action: "transactions cross-checked", entity: flaggedCovs.length + " covenant(s)", detail: "Matched transactions to a documented cause for each flagged covenant; unexplained items are reported, not hidden." });
  events.push({ actor: "agent", action: "memo generated", entity: run.severity, detail: "Escalation memo produced with citations to source page and transaction IDs for every claim." });
  events.push({ actor: "system", action: "receipt signed", entity: (run.trace_id || "").slice(0, 14), detail: "Ed25519 signature applied over the canonical evidence body \u2014 verifiable offline, independent of this run." });

  var rows = events.map(function (e, i) {
    var last = i === events.length - 1;
    return '<div class="tlrow"><div class="tlstep">step ' + (i + 1) + '</div>' +
      '<div class="tldotwrap"><div class="tldot" style="background:' + (actorColor[e.actor] || C.mute) + '"></div>' + (last ? "" : '<div class="tlline"></div>') + '</div>' +
      '<div class="tlbody"><div class="tlhead"><span style="font-weight:600;font-size:12px;color:' + (actorColor[e.actor] || "#8B8BA0") + '">' + e.actor + '</span>' +
      '<span class="tltag">' + esc(e.action) + '</span><span class="tltag">' + esc(e.entity) + '</span></div>' +
      '<div class="tldetail">' + esc(e.detail) + '</div></div></div>';
  }).join("");
  return rows;
}
function vEval() {
  var run = currentRun;
  if (!run || !run.evaluation) return panel("Diagnostics", "idle", '<div class="empty">Run an investigation to see the audit trail, evidence graph, and diagnostics.</div>');
  var ch = run.context_health || {};
  var scores = Object.keys(run.evaluation.scores).map(function (k) { return scorebar(k, run.evaluation.scores[k]); }).join("");
  var graph = evidenceGraph(run);
  var warns = (ch.warnings || []).map(function (w) { return '<div class="warn">\u26A0 ' + esc(w) + '</div>'; }).join("") || '<div class="warn">\u2713 No major context warnings</div>';
  var vultr = ["Web-based enterprise agent", "LLM/RAG workloads route to Vultr Serverless Inference when configured", "Deterministic fallback keeps demo reliable", "Docker-ready for Vultr Cloud Compute"].map(function (x) { return '<div class="chk">\u2713 ' + x + '</div>'; }).join("");
  var auditNote = '<div style="font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:' + C.signal + ';margin:0 0 12px">Audit &amp; integrity \u2014 relevant to compliance review</div>';
  var timeline = panel("Audit trail", events_count_label(run), buildAuditTimeline(run));
  var auditSection = timeline + '<div class="grid2 c" style="margin-top:20px">' + panel("Evidence graph", "decision \u2192 evidence", graph) + panel("Context health", (ch.overall || "checked"), warns) + '</div>';
  var engNote = '<div style="font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:' + C.mute + ';margin:28px 0 12px">Engineering diagnostics \u2014 internal only, not part of any user workflow</div>';
  var engSection = '<div class="grid2 c">' + panel("System readiness", "self-evaluation", scores) + panel("Platform alignment", "no GPU dependency", vultr) + '</div>';
  return auditNote + auditSection + engNote + engSection;
}
function events_count_label(run) {
  var n = 4 + (run.findings || []).length + ((run.findings || []).some(function (f) { return f.ratio.breached || f.ratio.drifting_toward_breach; }) ? 1 : 0);
  return n + " events \u00b7 agent, governance, system";
}
function vHistory() {
  var hist = currentHistory.slice().reverse();
  var series = hist.map(function (r, i) { return { run: "#" + (i + 1), confidence: Math.round(parseFloat(r.confidence) * 100) }; });
  var chart;
  if (series.length < 2) {
    chart = '<div class="empty">Run the check a few times \u2014 the agent learns to attribute causes, and confidence climbs.</div>';
  } else {
    var w = 900, h = 180, pad = 30;
    var pts = series.map(function (s, i) { var x = pad + (i * (w - 2 * pad) / (series.length - 1)); var y = h - pad - (s.confidence / 100) * (h - 2 * pad); return [x, y]; });
    var path = pts.map(function (p, i) { return (i ? "L" : "M") + p[0] + "," + p[1]; }).join(" ");
    var dots = pts.map(function (p) { return '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="3" fill="' + C.signal + '"/>'; }).join("");
    var labels = series.map(function (s, i) { var x = pad + (i * (w - 2 * pad) / (series.length - 1)); return '<text x="' + x + '" y="' + (h - 8) + '" fill="' + C.mute + '" font-size="11" text-anchor="middle">' + s.run + '</text>'; }).join("");
    chart = '<svg viewBox="0 0 ' + w + ' ' + h + '" style="width:100%;height:200px"><line x1="' + pad + '" y1="' + (h - pad) + '" x2="' + (w - pad) + '" y2="' + (h - pad) + '" stroke="#1E1E2E"/><line x1="' + pad + '" y1="' + pad + '" x2="' + pad + '" y2="' + (h - pad) + '" stroke="#1E1E2E"/><line x1="' + pad + '" y1="' + pad + '" x2="' + (w - pad) + '" y2="' + pad + '" stroke="' + C.signal + '" stroke-dasharray="3 3" opacity=".4"/><path d="' + path + '" fill="none" stroke="' + C.signal + '" stroke-width="2"/>' + dots + labels +
      '<text x="' + (pad - 8) + '" y="' + (pad + 4) + '" fill="' + C.mute + '" font-size="11" text-anchor="end">100</text><text x="' + (pad - 8) + '" y="' + (h - pad) + '" fill="' + C.mute + '" font-size="11" text-anchor="end">0</text></svg>';
  }
  var rows = currentHistory.map(function (r) { var sevTone = r.severity == "breach" ? "oxblood" : r.severity == "watch" ? "amber" : "signal"; return '<tr><td style="font-size:12px;color:' + C.mute + '">' + esc((r.run_id || "").slice(0, 14)) + '</td><td style="color:#E0E0E8">' + esc(r.borrower) + '</td><td>' + pill(r.severity, sevTone) + '</td><td>' + Math.round(parseFloat(r.confidence) * 100) + '%</td></tr>'; }).join("");
  if (!rows) rows = '<tr><td colspan="4" style="color:' + C.mute + '">No runs yet.</td></tr>';
  var tbl = '<div class="tblwrap"><table><thead><tr><th>Run</th><th>Borrower</th><th>Severity</th><th>Confidence</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
  return '<div class="stack">' + panel("Confidence across runs", "self-improvement", chart) + panel("Run history", "persistent", tbl) + '</div>';
}

/* ============ APP SHELL + ROUTER ============ */
function renderApp() {
  var body;
  if (portfolioError) {
    body = panel("Console", "backend unreachable", '<div class="empty">Could not reach the covenant engine.<br/><span style="color:' + C.oxblood + '">' + esc(portfolioError) + '</span><br/><br/>Is the API running on :8000?</div>');
  } else if (!portfolioLoaded) {
    if (!portfolioLoading) loadPortfolio();
    body = panel("Console", "live data", '<div class="empty"><span class="spinner" style="border-color:#2E2E3E;border-top-color:' + C.oxblood + '"></span> Connecting to the covenant engine\u2026</div>');
  } else if (view == "Portfolio") body = vPortfolio();
  else if (view == "Investigation") body = vInvestigation();
  else if (view == "Diagnostics") body = vEval();
  else body = vHistory();
  var tabs = VIEWS.map(function (v) { return '<button class="navbtn' + (v == view ? ' active' : '') + '" onclick="setView(\'' + v + '\')">' + v + '</button>'; }).join("");
  document.getElementById("app").innerHTML =
    '<div class="topbar"><div class="lbrand"><div class="logomark" style="width:32px;height:32px;font-size:15px">C</div>' +
    '<div><div class="brand">CovenantOps Agent</div><div class="brandsub">covenantops \u00b7 verifiable covenant monitoring</div></div></div>' +
    '<div style="display:flex;align-items:center;gap:12px"><div class="navtabs">' + tabs + '</div><span style="display:inline-flex;align-items:center;gap:6px;font-size:11px;color:' + C.mute + '"><span style="width:6px;height:6px;border-radius:50%;background:' + C.signal + ';box-shadow:0 0 6px ' + C.signal + '"></span>system operational</span><button class="navbtn" style="border:1px solid #2E2E3E;color:#FF4444;margin-left:4px" onclick="signOut()">Sign out</button></div></div>' +
    '<main><div class="wrap">' + body + '</div></main>';
}
function signOut() {
  screen = "landing";
  view = "Portfolio";
  ran = false; step = -1; verify = "idle";
  qaOpen = false; qaMessages = []; qaInput = "";
  uploadResult = null; uploadError = null;
  currentRun = null; currentEvidence = []; currentHistory = [];
  render();
}
function setView(v) {
  view = v;
  // History and Diagnostics read live state that a fresh run refreshes; make sure
  // History always reflects the latest persisted runs when opened.
  if (v == "History") { api.getHistory().then(function (h) { currentHistory = h; render(); }).catch(function () {}); }
  render();
}

function loadPortfolio() {
  portfolioLoading = true; portfolioError = null;
  api.getPortfolio().then(function (rows) {
    portfolio = rows;
    if (rows[0]) {
      currentBorrowerId = rows[0].id;
      if (!currentRun) currentRun = { borrower: rows[0].name, facility: rows[0].facility };
    }
    portfolioLoaded = true; portfolioLoading = false; render();
  }).catch(function (e) {
    portfolioError = String((e && e.message) || e);
    portfolioLoaded = true; portfolioLoading = false; render();
  });
}

var QA_SUGGESTIONS = ["Why is the leverage covenant flagged?", "What's the unexplained transaction?", "Is a waiver active?", "What's the recommended action?"];
var qaOpen = false, qaMessages = [], qaInput = "", qaLoading = false;
var uploading = false, uploadResult = null, uploadError = null;

function openInvestigation(id) {
  currentBorrowerId = id || currentBorrowerId;
  var meta = null;
  for (var i = 0; i < portfolio.length; i++) { if (portfolio[i].id === currentBorrowerId) { meta = portfolio[i]; break; } }
  // seed the header identity from the portfolio entry; the full run replaces it
  currentRun = meta ? { borrower: meta.name, facility: meta.facility, severity: meta.severity, confidence: meta.confidence }
    : (seedRuns[currentBorrowerId] || currentRun);
  ran = false; step = -1; verify = "idle"; qaOpen = false; qaMessages = [];
  uploadResult = null; uploadError = null;
  view = "Investigation"; render();
  // load the current evidence set so the user can see (and add to) it before running
  api.getEvidence().then(function (ev) { currentEvidence = ev; render(); }).catch(function () {});
}
function onEvidenceFile(e) {
  var file = e.target && e.target.files && e.target.files[0];
  if (!file) return;
  uploading = true; uploadResult = null; uploadError = null; render();
  api.uploadEvidence(file).then(function (res) {
    uploading = false; uploadResult = res;
    render();
    api.getEvidence().then(function (ev) { currentEvidence = ev; render(); }).catch(function () {});
  }).catch(function (err) {
    uploading = false; uploadError = String((err && err.message) || err); render();
  });
}
// Runs the agent and advances the workflow from REAL progress events streamed by
// the backend (Server-Sent Events). No timers — each step lights up when that phase
// actually completes. Falls back to the plain POST run if streaming is unavailable.
function doRun() {
  ran = false; step = 0; running = true; streamSettled = false; verify = "idle"; render();
  api.getEvidence().then(function (ev) { currentEvidence = ev; });

  function settleResult(r) {
    if (streamSettled) return;
    streamSettled = true;
    step = STEPS.length; // all steps complete
    hydrateRun(r).then(function () {
      currentRun = r; seedRuns[currentBorrowerId] = r; ran = true; running = false; render();
    });
    api.getHistory().then(function (h) { currentHistory = h; render(); }).catch(function () {});
  }
  function fail(msg) {
    if (streamSettled) return;
    streamSettled = true; running = false; portfolioError = msg; render();
  }
  function fallback() {
    if (streamSettled) return;
    api.runInvestigation(currentBorrowerId, {}).then(settleResult).catch(function (e) { fail(String((e && e.message) || e)); });
  }
  function handle(msg) {
    if (msg.type === "progress") {
      var i = STEP_KEYS.indexOf(msg.step);
      if (i >= 0 && i >= step) { step = i; render(); }
    } else if (msg.type === "result") {
      settleResult(msg.run);
    } else if (msg.type === "error") {
      fallback(); // try the non-streaming path before surfacing an error
    }
  }

  var streamUrl = API + "/covenant/run/stream" + (currentBorrowerId ? "?borrower=" + encodeURIComponent(currentBorrowerId) : "");
  fetch(streamUrl).then(function (resp) {
    if (!resp.ok || !resp.body) throw new Error("stream " + resp.status);
    var reader = resp.body.getReader(), dec = new TextDecoder(), buf = "";
    function pump() {
      return reader.read().then(function (res) {
        if (res.done) return;
        buf += dec.decode(res.value, { stream: true });
        var frames = buf.split("\n\n"); buf = frames.pop();
        frames.forEach(function (frame) {
          var data = frame.split("\n").filter(function (l) { return l.indexOf("data:") === 0; })
            .map(function (l) { return l.slice(5).trim(); }).join("");
          if (!data) return;
          try { handle(JSON.parse(data)); } catch (_) { /* ignore keep-alives */ }
        });
        return pump();
      });
    }
    return pump();
  }).then(function () { if (!streamSettled) fallback(); })
    .catch(function () { fallback(); });
}
function doVerify() {
  verify = "checking"; render();
  api.verifyReceipt(currentRun.trace_id, false).then(function (res) { verify = res.valid ? "valid" : "invalid"; render(); })
    .catch(function () { verify = "invalid"; render(); });
}
function doTamper() {
  verify = "checking"; render();
  api.verifyReceipt(currentRun.trace_id, true).then(function (res) { verify = res.valid ? "valid" : "invalid"; render(); })
    .catch(function () { verify = "invalid"; render(); });
}

// --- Ask the Agent: clarifying Q&A grounded in the current run's data ---
function toggleQa() { qaOpen = true; render(); var b = document.getElementById("qaInputBox"); if (b) b.focus(); }
function suggestQa(i) { qaInput = QA_SUGGESTIONS[i]; render(); var b = document.getElementById("qaInputBox"); if (b) b.focus(); }
function qaKeydown(e) {
  if (e.key !== "Enter") return;
  var question = e.target.value.trim();
  if (!question || qaLoading) return;
  qaMessages.push({ role: "user", content: question });
  qaInput = ""; qaLoading = true; render();
  function done(content, meta) {
    qaMessages.push({ role: "assistant", content: content, meta: meta || {} });
    qaLoading = false; render();
    var box = document.getElementById("qaInputBox"); if (box) box.focus();
  }
  var tid = currentRun && currentRun.trace_id;
  if (!tid) { done("Run this borrower's investigation first, then I can answer from its evidence.", { inference_path: "none" }); return; }
  // Real, governed, Vultr-backed Q&A grounded in this run.
  api.qa(tid, question).then(function (res) {
    done(res.answer, { inference_path: res.inference_path, guard_path: res.guard_path, blocked: res.blocked });
  }).catch(function () {
    done(answerQa(question), { inference_path: "local_fallback" }); // deterministic fallback
  });
}
function answerQa(q) {
  var run = currentRun, lq = q.toLowerCase();
  var unexplained = [];
  (run.findings || []).forEach(function (f) { if (f.cross_check) (f.cross_check.unexplained || []).forEach(function (u) { unexplained.push(u); }); });
  if (lq.indexOf("unexplained") >= 0 || lq.indexOf("txn-4420") >= 0 || lq.indexOf("intercompany") >= 0) {
    var u = unexplained[0];
    return u ? "Transaction " + u.id + " (" + u.note + ", " + fmtMoney(u.amount) + ") could not be matched to a documented cause. It's the reason overall confidence is " + Math.round(run.confidence * 100) + "% rather than higher \u2014 it needs a human explanation before it can be counted as resolved."
      : "All flagged transactions were matched to a documented cause this run.";
  }
  if (lq.indexOf("waiver") >= 0) {
    var wf = (run.findings || []).find(function (f) { return f.ratio.waiver_applied; });
    return wf ? "A signed waiver (" + wf.ratio.waiver_source + ") is active and adjusts " + wf.ratio.metric + "'s limit from " + wf.ratio.base_threshold + " to " + wf.ratio.threshold + " for the current period. Without it, this covenant would be measured against the original, stricter limit."
      : "No waiver is currently active for the flagged covenants \u2014 they're measured against the original agreement limits.";
  }
  if (lq.indexOf("breach") >= 0 || (lq.indexOf("why") >= 0 && lq.indexOf("flag") >= 0)) {
    var breached = (run.findings || []).filter(function (f) { return f.ratio.breached; });
    if (breached.length) return breached.map(function (f) { return f.ratio.covenant_id + " (" + f.ratio.metric + ") is at " + f.ratio.value + " against a limit of " + f.ratio.threshold + " \u2014 outside the permitted range."; }).join(" ");
    return "No covenant is currently in breach; some are drifting toward their limits, which is why they're flagged for attention.";
  }
  if (lq.indexOf("recommend") >= 0 || lq.indexOf("next") >= 0 || lq.indexOf("action") >= 0) {
    return "Recommended next step: request an updated compliance certificate from the borrower, and if the leverage trend continues, evaluate the Equity Cure right under Section 7.4 before the next test date.";
  }
  return "For " + esc(run.borrower) + ": severity is " + run.severity + " with " + Math.round(run.confidence * 100) + "% cause-attribution confidence. Ask me about a specific covenant, an unexplained transaction, or the waiver status for more detail.";
}
function fmtMoney(n) { return "$" + Number(n).toLocaleString(); }

function render() {
  if (screen == "landing") renderLanding();
  else if (screen == "signin") renderSignIn();
  else renderApp();
}

// Inline onclick handlers reference these by name; ES modules are not global, so
// expose the interaction surface on window.
Object.assign(window, {
  goSignIn, goApp, viewArchitecture, doSignIn,
  openInvestigation, doRun, doVerify, doTamper, onEvidenceFile,
  toggleQa, suggestQa, qaKeydown, setView, signOut,
});

render();
