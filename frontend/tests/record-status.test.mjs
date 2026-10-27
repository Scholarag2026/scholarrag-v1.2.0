import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { RECORD_STATUSES, recordStatusLabelKey, verifyCompleteValues } from "../src/lib/record-status.ts";

test("the four wire values map to the four record labels", () => {
  assert.deepEqual(RECORD_STATUSES.map(recordStatusLabelKey), [
    "recordVerified",
    "metadataMismatch",
    "doiNotFound",
    "noDoi",
  ]);
});

test("null is a failed lookup, unknown or old values fall back to pending", () => {
  assert.equal(recordStatusLabelKey(null), "lookupFailed");
  for (const s of [undefined, "pending", "pass", "warning", "fail"]) {
    assert.equal(recordStatusLabelKey(s), "pending");
  }
});

test("toast values cover every class and sum to total", () => {
  const r = { total: 6, record_verified: 2, metadata_mismatch: 1, doi_not_found: 1, no_doi: 1, lookup_failed: 1 };
  const v = verifyCompleteValues(r);
  assert.equal(Object.values(v).reduce((a, b) => a + b, 0), r.total);
});

test("both locales carry every verifyComplete placeholder and lookupFailed", () => {
  for (const loc of ["en", "zh"]) {
    const m = JSON.parse(readFileSync(new URL(`../messages/${loc}.json`, import.meta.url), "utf8"));
    const text = JSON.stringify(m).match(/"verifyComplete":"([^"]*)"/)[1];
    for (const p of ["recordVerified", "metadataMismatch", "doiNotFound", "noDoi", "lookupFailed"]) {
      assert.ok(text.includes(`{${p}}`), `${loc} missing ${p}`);
    }
    for (const p of ["passed", "failed", "warnings"]) {
      assert.ok(!text.includes(`{${p}}`), `${loc} still has ${p}`);
    }
    assert.ok(m.verification.lookupFailed);
  }
});
