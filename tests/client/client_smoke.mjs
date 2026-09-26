// Runs client/index.html's script against a minimal fake DOM, fetch and
// timer, and checks what it renders. No browser or npm dependency: node only.
// Invoked by tests/test_client.py (skipped when node isn't installed).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import assert from "node:assert/strict";

const html = readFileSync(fileURLToPath(new URL("../../client/index.html", import.meta.url)), "utf8");
const script = html.slice(html.lastIndexOf("<script>") + 8, html.lastIndexOf("</script>"));

class El {
  constructor(id = "") { this.id = id; this.children = []; this._html = ""; this.dataset = {};
    this.textContent = ""; this.className = ""; this.value = ""; this.checked = false; this.listeners = {}; }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = v; this.children = []; }
  querySelector(sel) {
    if (sel === ".empty") return this._html.includes('class="empty"') && !this.children.length ? {} : null;
    return null;
  }
  querySelectorAll() { return []; }
  insertBefore(el, ref) {
    const i = ref ? this.children.indexOf(ref) : -1;
    if (i < 0) this.children.push(el); else this.children.splice(i, 0, el);
  }
  prepend(el) { this.children.unshift(el); }
  addEventListener(type, f) { this.listeners[type] = f; }
}

const ids = {};
const document = {
  getElementById: id => (ids[id] ??= new El(id)),
  createElement: () => new El(),
};
document.getElementById("results").innerHTML = '<div class="empty">No questions yet.</div>';

const XSS = "<img src=x onerror=alert(1)>";
const v1 = { question: "how should we round 2.5?", committed: [{ issuing_agent: "Mathematics", statement: "round half to even gives 2" }],
             dissent: [], plural_answers: [{ chaired_by: "Logic" }] };
const v2 = { question: "how should we round 2.5?", committed: [{ issuing_agent: "Mathematics", statement: XSS }],
             dissent: [{ claim: { statement: "a challenged claim" } }], plural_answers: [],
             diff: { cause: ["idle re-examination: source now rejected"], added: [XSS], removed: ["Mathematics::old"],
                     weight_changes: [{ claim: "Mathematics::c", from: 0.9, to: 0.5, direction: "decreased" }],
                     leading_conclusion: { change: "changed", from: "a", to: "b" } } };
const state = {
  questions: [
    { id: "q-1", status: "completed", importance: 0.42, versions: [v1, v2], question: v2.question },
    { id: "q-2", status: "queued", importance: 0.5, versions: [], question: "is 17 prime?" },
  ],
  maintenance: { idle_cycles: 1, queued_units: 1, pending_amendments: [],
                 recent_events: [{ kind: "question", question_id: "q-1", importance: 0.42 },
                                 { kind: "idle", cycle_id: "idle-1", status_counts: { survived: 2, challenged: 0 },
                                   reopened: ["q-1"], amendments_adopted: [], calibration_drifting: [] }] },
};
state.health = { cores_available: 4, dram_headroom_gb: 3, queued_units: 0,
                 worker: { started: false, alive: false, rounds_run: 0, seconds_since_last_round: null } };
state.checkpoints = [
  { key: "standard-amendment:idle-4", kind: "standard-amendment", ref: "idle-4", status: "pending_human_checkpoint",
    reason: "2 claim(s) resting only on 'foundational' sources were challenged", note: null, reviewer_id: null,
    proposal: { params: { rejected_min_challenges: 3, foundational_min_corroborations: 6 } } },
  { key: "q-9", kind: "question", ref: "q-9", status: "pending_human_checkpoint", reason: XSS,
    note: "needs a source", reviewer_id: "rev-1" },
  { key: "domain-fidelity:Physics", kind: "domain-fidelity", ref: "Physics", status: "current",
    reason: "already approved", note: null, reviewer_id: "rev-2" },
];
const posts = [];
const fullFetches = {};
const fetch = async (path, opts = {}) => {
  let status = 200, body;
  if (path === "/api/health") body = state.health;
  else if (path === "/api/questions" && opts.method === "POST") {
    posts.push(JSON.parse(opts.body)); status = 202; body = { id: "q-3", status: "queued" };
    state.questions.push({ id: "q-3", status: "queued", importance: 0.5, versions: [], question: posts.at(-1).question });
  } else if (path === "/api/questions?view=summary") {
    body = state.questions.map(q => ({ id: q.id, status: q.status, question: q.question, importance: q.importance,
                                       versions: q.versions.length, ...(q.error ? { error: q.error } : {}) }));
  } else if (path.startsWith("/api/questions/")) {
    const id = decodeURIComponent(path.slice("/api/questions/".length));
    fullFetches[id] = (fullFetches[id] || 0) + 1;
    body = state.questions.find(q => q.id === id);
    if (!body) { status = 404; body = { error: "not found" }; }
  } else if (path === "/api/questions") throw new Error("the client must poll the summary view");
  else if (path === "/api/maintenance") body = state.maintenance;
  else if (path === "/api/checkpoints") body = state.checkpoints;
  else if (path.startsWith("/api/checkpoints/") && opts.method === "POST") {
    decisions.push({ path, headers: opts.headers, body: JSON.parse(opts.body) });
    ({ status, body } = state.decisionResponse);
  }
  else { status = 404; body = { error: "not found" }; }
  return { status, json: async () => JSON.parse(JSON.stringify(body)) };
};
const timers = [];
const decisions = [];
let promptAnswer = null;
const context = vm.createContext({ document, fetch, setTimeout: (f, ms) => timers.push({ f, ms }), console,
                                   prompt: () => promptAnswer });
vm.runInContext(script, context);
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r)); };
const cardHtml = id => vm.runInContext(`cards.get(${JSON.stringify(id)}).innerHTML`, context);
const order = () => document.getElementById("results").children.map(c => c.dataset.id);

await settle();

// history loads newest first; pending questions show their text and status
assert.deepEqual(order(), ["q-2", "q-1"]);
assert.match(cardHtml("q-2"), /is 17 prime\?/);
assert.match(cardHtml("q-2"), /tag pending">queued/);
assert.match(cardHtml("q-2"), /Deliberating in the background/);

// the latest version is shown, with its reopen diff; every version is selectable
const q1 = cardHtml("q-1");
assert.match(q1, /v1<\/button>/);
assert.match(q1, /v2 \(latest\)/);
assert.match(q1, /Reopened/);
assert.match(q1, /source now rejected/);
assert.match(q1, /0\.90 → 0\.50/);
assert.match(q1, /leading conclusion changed/);
assert.match(q1, /a challenged claim/);

// server text is escaped, never parsed as HTML
assert.ok(!q1.includes(XSS), "raw markup from the server reached innerHTML");
assert.match(q1, /&lt;img src=x onerror=alert\(1\)&gt;/);

// choosing an older version shows it (with no diff) and keeps the choice
vm.runInContext(`selected.set("q-1", 0); renderCard(questions.get("q-1"))`, context);
assert.match(cardHtml("q-1"), /round half to even gives 2/);
assert.match(cardHtml("q-1"), /Jurisdictional conflict, chaired by Logic/);
assert.ok(!cardHtml("q-1").includes("Reopened"));

// maintenance panel
assert.equal(document.getElementById("maint-summary").textContent, "1 idle cycle(s), 1 unit(s) queued");
const events = document.getElementById("maint-events").innerHTML;
assert.match(events, /idle-1: re-examined 2 survived; reopened q-1/);
assert.match(events, /q-1 answered \(importance 0\.42\)/);

// human checkpoints: only what is still pending, with the proposal, escaped
assert.equal(document.getElementById("review-summary").textContent, "2");
const review = document.getElementById("review-items").innerHTML;
assert.match(review, /standard amendment<\/strong> idle-4: 2 claim\(s\)/);
assert.match(review, /proposes rejected_min_challenges=3, foundational_min_corroborations=6/);
assert.match(review, /human input<\/strong> q-9: &lt;img/);
assert.match(review, /reviewer rev-1: needs a source/);
assert.ok(!review.includes("already approved") && !review.includes(XSS));

// polls fast while something is pending...
assert.equal(timers.at(-1).ms, 2000);
state.questions[1] = { id: "q-2", status: "completed", importance: 0.3, question: "is 17 prime?",
                       versions: [{ question: "is 17 prime?", committed: [{ issuing_agent: "Mathematics", statement: "17 is prime" }],
                                    dissent: [], plural_answers: [] }] };
assert.deepEqual(fullFetches, { "q-1": 1, "q-2": 1 });
assert.match(document.getElementById("status").textContent, /4 cores, 3GB .* background worker not started yet$/);
state.health = { ...state.health, queued_units: 2,
                 worker: { started: true, alive: true, rounds_run: 9, seconds_since_last_round: 500 } };
timers.at(-1).f();
await settle();
assert.match(document.getElementById("status").textContent, /background worker: 2 queued, no progress for 500s$/);
assert.deepEqual(fullFetches, { "q-1": 1, "q-2": 2 });   // only the question that changed is re-fetched
assert.match(cardHtml("q-2"), /17 is prime/);
assert.ok(!cardHtml("q-2").includes("pending"));
assert.match(cardHtml("q-1"), /round half to even gives 2/, "the reader's chosen version survived a refresh");
// ...and slowly once nothing is
assert.equal(timers.at(-1).ms, 15000);

// asking submits asynchronously by default, then shows the queued question
document.getElementById("q").value = "  what is 2+2?  ";
document.getElementById("go").listeners.click();
await settle();
assert.deepEqual(posts.at(-1), { question: "what is 2+2?", async: true });
assert.deepEqual(order(), ["q-3", "q-2", "q-1"]);
assert.equal(document.getElementById("q").value, "");

// "wait for the answer" uses the synchronous call
document.getElementById("wait").checked = true;
document.getElementById("q").value = "is 4 prime?";
document.getElementById("go").listeners.click();
await settle();
assert.deepEqual(posts.at(-1), { question: "is 4 prime?" });

// a question given up after repeated failures shows why, escaped
state.questions.push({ id: "q-5", status: "suspended", importance: 0.5, versions: [], question: "will it fail?",
                       error: "RuntimeError: <b>boom</b>" });
state.maintenance.failed_units = ["q-5"];
state.maintenance.recent_events.push({ kind: "unit_error", unit_id: "q-5", failures: 1, error: "RuntimeError: boom" },
                                     { kind: "unit_failed", unit_id: "q-5", failures: 3, error: "RuntimeError: boom" },
                                     { kind: "ingestion", batch_id: "seed-1", accepted: ["a", "b"], rejected: { c: "paid" } });
timers.at(-1).f();
await settle();
assert.match(cardHtml("q-5"), /tag dissent">suspended/);
assert.match(cardHtml("q-5"), /RuntimeError: &lt;b&gt;boom&lt;\/b&gt;/);
assert.match(document.getElementById("maint-summary").textContent, /, 1 failed$/);
const failures = document.getElementById("maint-events").innerHTML;
assert.match(failures, /q-5: gave up after 3 failed attempts -- RuntimeError: boom/);
assert.match(failures, /q-5: round failed \(attempt 1\), retrying/);
assert.match(failures, /seed-1: ingested 2 source\(s\), rejected 1/);

// --- owner decision 7: acting as a reviewer ---------------------------------
const items = () => document.getElementById("review-items");
assert.ok(!items().innerHTML.includes("<button"), "no actions without a token");
document.getElementById("token").value = "  tok-123  ";
document.getElementById("token").listeners.change();
await settle();
assert.match(items().innerHTML, /<button data-key="standard-amendment:idle-4" data-decision="approve">Approve<\/button>/);
assert.match(items().innerHTML, /data-key="q-9" data-decision="reject_with_note">Reject/);

state.decisionResponse = { status: 200, body: { key: "standard-amendment:idle-4", status: "current" } };
items().listeners.click({ target: { dataset: { key: "standard-amendment:idle-4", decision: "approve" } } });
await settle();
const approved = decisions.at(-1);
assert.equal(approved.path, "/api/checkpoints/standard-amendment%3Aidle-4/decision");
assert.equal(approved.headers.Authorization, "Bearer tok-123");
assert.deepEqual(approved.body, { decision: "approve" });
assert.equal(document.getElementById("review-status").textContent, "standard-amendment:idle-4: current");

promptAnswer = "";                                  // a rejection without a note is never sent
items().listeners.click({ target: { dataset: { key: "q-9", decision: "reject_with_note" } } });
await settle();
assert.equal(decisions.length, 1);
promptAnswer = "needs a source";
state.decisionResponse = { status: 409, body: { error: "the reviewer clearing a checkpoint must not be the submitter" } };
items().listeners.click({ target: { dataset: { key: "q-9", decision: "reject_with_note" } } });
await settle();
assert.deepEqual(decisions.at(-1).body, { decision: "reject_with_note", note: "needs a source" });
assert.match(document.getElementById("review-status").textContent, /q-9: refused \(409\) -- the reviewer clearing/);
items().listeners.click({ target: { dataset: {} } });  // a click that isn't on a button does nothing
await settle();
assert.equal(decisions.length, 2);

console.log("client smoke: all checks passed");
