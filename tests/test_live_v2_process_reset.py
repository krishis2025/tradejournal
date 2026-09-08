"""F1 regression guard — the tile-to-tag mechanism must survive trade 2.

Before the fix, processPatience/processArrival/processConfirmation (the three
assessment-page tile counters) and assessTags (the setup/pre tag buffer) were
reset ONLY in cancelEntry(). createTradeFromForm(), commitContext() and
useSamePlan() — the three functions that actually end/restart a trade-entry
cycle in normal use — left them untouched. So on trade 2 of a session the
"Trade came to me" tile rendered already-ticked from trade 1's leftover
state, the trader never clicked it, setPreTag() never fired, and the trade
was created with patience=1 on trade_strength but NO 'pre' tag — silently
breaking the tile's one job (spec section 4.1: ticking it also sets the
'Trade came to me' pre tag so its four downstream consumers keep working).

This test extracts the real functions verbatim out of live_v2.html (by name,
brace-matched — no line numbers, no copy-pasted duplicate logic) and runs
them under Node with the browser/network surface stubbed out, so it exercises
the actual shipped JS rather than a hand-written model of it. It is run
against a scratch copy on disk only implicitly (it never touches a
database); it reads the template file directly.
"""
import json
import re
import shutil
import subprocess

import pytest

LIVE_V2 = "templates/live_v2.html"

FUNCTIONS_UNDER_TEST = [
    "toggleProcess", "setPreTag", "cancelEntry", "useSamePlan",
    "createTradeFromForm", "commitContext",
]

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to execute the extracted JS"
)


def _extract_function(source, name):
    """Pull `function NAME(...) { ... }` (optionally `async`) out of `source`
    by brace-matching from the opening `{`, so this survives line drift and
    doesn't require re-copying the function body into the test."""
    m = re.search(r"(?:async\s+)?\bfunction\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", source)
    assert m, f"could not find function {name} in {LIVE_V2}"
    start = m.start()
    brace_start = source.index("{", m.start())
    depth = 0
    i = brace_start
    while i < len(source):
        c = source[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1
    raise AssertionError(f"unbalanced braces extracting {name}")


HARNESS_TEMPLATE = r"""
// ---- minimal browser/network stubs ----
let processPatience = 0;
let processArrival = 0;
let processConfirmation = 0;
let assessTags = { setup: [], pre: [] };

let strengthSubmitted = false;
let activeStrengthId = null;
let activeStrength = {};
let activeContextId = null;
let lastCommittedContext = {};
let pendingNuances = [];
let formState = {};
let pendingSignals = [];
let pendingLegs = [];
let formPrice = '';
let formQty = '';
let selectedBias = '';
let legSide = 'Long';
let contextFormMode = 'create';
let liveNowContext = null;
let inlineUpdateOpen = false;
let contextDontKnow = false;
let selectedTrend = '';
let msState = { value: 'Overlapping', adhZone: '', adhStrength: '', techZone: '', techStrength: '', sectorsZone: '', sectorsBreadth: '' };
let guardState = { mental_state: 'calm' };
let SERVER_CONTEXTS = [];
let strengthValue = 0, strengthVolume = 0, strengthTrend = 0, strengthAdh = 0;
let strengthMental = 'calm', strengthConfidence = 'medium', strengthEmotion = 'calm';
let formDir = 'Long', formInst = 'MES', formMode = 'full';
let TRADES = {};
let activeTrade = null;
let activePhase = '';
let activeTags = {};
let STRENGTH_MAP = {};
let INST_CONFIG = {};
let __phase = null;

global.window = { _pendingEntry: null };
global.document = {
  getElementById: (id) => {
    if (id === 'global-account-select') return { value: '1' };
    return { value: 'TestType' };
  }
};

function setPhase(name) { __phase = name; }
function renderCenter() {}
function renderHealthPanel() {}
function showToast() {}
function renderAll() {}
function updateRibbon() {}
function closePlanChoice() {}
function getLastTradeContextId() { return 42; }
function buildTradeModel() { return {}; }
function msSnapshot() { return null; }

let __fetchCalls = [];
global.fetch = async (url, opts) => {
  const body = (opts && opts.body) ? JSON.parse(opts.body) : null;
  __fetchCalls.push({ url, body });
  if (url === '/api/live') {
    return { json: async () => ({ ok: true, id: __fetchCalls.filter(c => c.url === '/api/live').length }) };
  }
  if (/^\/api\/live\/\d+$/.test(url)) {
    return { json: async () => ({ id: 1, strength_id: null }) };
  }
  if (/^\/api\/live\/\d+\/recalc$/.test(url)) {
    return { json: async () => ({}) };
  }
  if (url === '/api/context') {
    return { json: async () => ({ ok: true, id: 999 }) };
  }
  if (/^\/api\/context\/\d+\/signals$/.test(url)) {
    return { json: async () => ({ ok: true }) };
  }
  if (/^\/api\/context\/\d+\/legs$/.test(url)) {
    return { json: async () => ({ ok: true, ids: [] }) };
  }
  return { json: async () => ({ ok: true }) };
};

// ---- extracted real functions under test (verbatim from live_v2.html) ----
%(functions)s

function dirty() {
  processPatience = 1; processArrival = 1; processConfirmation = 1;
  assessTags = { setup: ['ghost-setup'], pre: ['ghost-tag'] };
}
function isClean() {
  return processPatience === 0 && processArrival === 0 && processConfirmation === 0 &&
         (assessTags.pre || []).length === 0 && (assessTags.setup || []).length === 0;
}

(async () => {
  const result = {};

  // createTradeFromForm's own reset + payload correctness
  cancelEntry();
  toggleProcess('patience');
  window._pendingEntry = { price: 100, qty: 1, time: '10:00', stop_price: 99, target_price: 105 };
  await createTradeFromForm();
  const payload1 = __fetchCalls.find(c => c.url === '/api/live').body;
  result.trade1_pre_tag_present = (payload1.tags.pre || []).includes('Trade came to me');
  result.after_createTrade_is_clean = isClean();

  // useSamePlan's own reset, isolated from createTradeFromForm's
  dirty();
  useSamePlan();
  result.useSamePlan_resets = isClean();

  // commitContext's own reset, isolated
  dirty();
  await commitContext();
  result.commitContext_resets = isClean();

  // End-to-end two-trade regression: the exact F1 scenario
  cancelEntry();
  toggleProcess('patience');
  window._pendingEntry = { price: 100, qty: 1, time: '10:00', stop_price: 99, target_price: 105 };
  __fetchCalls = [];
  await createTradeFromForm();
  const tradeA = __fetchCalls.find(c => c.url === '/api/live').body;
  result.tradeA_pre_tag_present = (tradeA.tags.pre || []).includes('Trade came to me');

  // Restart the entry cycle for trade 2 via "Same Plan"
  useSamePlan();
  result.tile_not_prechecked_for_trade2 = (processPatience === 0 && (assessTags.pre || []).length === 0);

  // Trader ticks the tile again for trade 2
  toggleProcess('patience');
  window._pendingEntry = { price: 200, qty: 1, time: '11:00', stop_price: 199, target_price: 205 };
  __fetchCalls = [];
  await createTradeFromForm();
  const tradeB = __fetchCalls.find(c => c.url === '/api/live').body;
  result.tradeB_pre_tag_present = (tradeB.tags.pre || []).includes('Trade came to me');

  console.log(JSON.stringify(result));
})().catch(e => { console.error(e.stack); process.exit(1); });
"""


def _run_harness(tmp_path):
    with open(LIVE_V2) as f:
        source = f.read()
    functions = "\n\n".join(_extract_function(source, name) for name in FUNCTIONS_UNDER_TEST)
    script = HARNESS_TEMPLATE % {"functions": functions}
    script_path = tmp_path / "f1_harness.js"
    script_path.write_text(script)
    proc = subprocess.run(["node", str(script_path)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, f"harness crashed:\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_second_trade_still_carries_the_pre_tag_when_the_tile_is_ticked(tmp_path):
    """The core F1 assertion: two consecutive trades in one session both
    carry the 'pre' tag when the tile is ticked for each of them, and the
    tile is not silently pre-checked (stale counter) for trade 2."""
    result = _run_harness(tmp_path)
    assert result["tradeA_pre_tag_present"] is True
    assert result["tile_not_prechecked_for_trade2"] is True, (
        "the tile rendered already-ticked for trade 2 — the counters were not "
        "reset when the entry cycle restarted"
    )
    assert result["tradeB_pre_tag_present"] is True


def test_createTradeFromForm_resets_counters_and_tag_buffer(tmp_path):
    result = _run_harness(tmp_path)
    assert result["trade1_pre_tag_present"] is True
    assert result["after_createTrade_is_clean"] is True


def test_useSamePlan_resets_counters_and_tag_buffer(tmp_path):
    result = _run_harness(tmp_path)
    assert result["useSamePlan_resets"] is True


def test_commitContext_resets_counters_and_tag_buffer(tmp_path):
    result = _run_harness(tmp_path)
    assert result["commitContext_resets"] is True
