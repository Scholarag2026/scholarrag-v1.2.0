import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const load = (name) => JSON.parse(readFileSync(join(here, "..", "messages", name), "utf8"));
const backend = (file) => readFileSync(join(here, "..", "..", "backend", "app", "services", file), "utf8");

// Every string literal the backend assigns to stop_reason (including "x or 'y'" forms).
function stopReasonsIn(source) {
  const values = new Set();
  for (const m of source.matchAll(/\bstop_reason\s*=\s*(?:stop_reason\s+or\s+)?["']([a-z_]+)["']/g)) {
    values.add(m[1]);
  }
  return values;
}

const backendValues = new Set([
  ...stopReasonsIn(backend("smart_search.py")),
  ...stopReasonsIn(backend("deep_search.py")),
]);
const en = load("en.json").smartSearch;
const zh = load("zh.json").smartSearch;

test("the backend source yields the known stop reasons", () => {
  for (const v of ["cancelled", "max_scanned", "no_new_included", "no_wos_papers", "query_generation_failed", "time_limit", "screening_failed", "retrieval_failed"]) {
    assert.ok(backendValues.has(v), `parser did not find ${v}`);
  }
});

test("every backend stop_reason has a non-empty label in both catalogs", () => {
  const missing = [];
  for (const v of [...backendValues].sort()) {
    for (const [name, cat] of [["en", en], ["zh", zh]]) {
      const label = cat.stopReasons?.[v];
      if (typeof label !== "string" || !label.trim()) missing.push(`${name}:${v}`);
    }
  }
  assert.deepEqual(missing, []);
});

test("stop reason labels are plain text, not the raw slug", () => {
  for (const cat of [en, zh]) {
    for (const [slug, label] of Object.entries(cat.stopReasons)) {
      assert.notEqual(label, slug);
      assert.ok(!label.includes("_"), `${slug} label contains an underscore`);
    }
  }
});

test("the previous-answer prefix uses a {n} placeholder in both catalogs", () => {
  assert.match(en.questionNumber, /\{n\}/);
  assert.match(zh.questionNumber, /\{n\}/);
  assert.equal(zh.questionNumber.replace("{n}", "2"), "问题2");
});

test("the panel does not hardcode the Q-number prefix", () => {
  const src = readFileSync(join(here, "..", "src", "components", "smart-search-panel.tsx"), "utf8");
  assert.ok(!/Q\{i \+ 1\}/.test(src));
});

test("zh toConfirmHelp says 判据 for criteria", () => {
  assert.ok(zh.toConfirmHelp.includes("判据"));
  assert.ok(!zh.toConfirmHelp.includes("标准"));
});
