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
const posts = [];
const fetch = async (path, opts = {}) => {
  let status = 200, body;
  if (path === "/api/health") body = { cores_available: 4, dram_headroom_gb: 3 };
  else if (path === "/api/questions" && opts.method === "POST") {
    posts.push(JSON.parse(opts.body)); status = 202; body = { id: "q-3", status: "queued" };
    state.questions.push({ id: "q-3", status: "queued", importance: 0.5, versions: [], question: posts.at(-1).question });
  } else if (path === "/api/questions") body = state.questions;
  else if (path === "/api/maintenance") body = state.maintenance;
  else { status = 404; body = { error: "not found" }; }
  return { status, json: async () => JSON.parse(JSON.stringify(body)) };
};
const timers = [];
const context = vm.createContext({ document, fetch, setTimeout: (f, ms) => timers.push({ f, ms }), console });
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

// polls fast while something is pending...
assert.equal(timers.at(-1).ms, 2000);
state.questions[1] = { id: "q-2", status: "completed", importance: 0.3, question: "is 17 prime?",
                       versions: [{ question: "is 17 prime?", committed: [{ issuing_agent: "Mathematics", statement: "17 is prime" }],
                                    dissent: [], plural_answers: [] }] };
timers.at(-1).f();
await settle();
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

console.log("client smoke: all checks passed");
