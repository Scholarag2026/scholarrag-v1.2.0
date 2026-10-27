import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { RECORD_STATUSES } from "../src/lib/record-status.ts";

const read = (rel) => readFileSync(new URL(rel, import.meta.url), "utf8");

test("README lists exactly the four record statuses and calls a failed lookup an error", () => {
  const readme = read("../../README.md");
  const start = readme.indexOf("**Level 1: record verification.**");
  assert.ok(start >= 0);
  const end = readme.indexOf("**Level 2", start);
  const para = readme.slice(start, end);
  for (const s of ["record verified", "metadata mismatch", "DOI not found", "no DOI"]) {
    assert.ok(para.includes(`\`${s}\``), s);
  }
  assert.ok(para.includes("lookup failed"));
  assert.ok(!para.includes("not checked"));
});

test("the 1.2.0 CHANGELOG section names every RECORD_STATUSES value and lookup_failed", () => {
  const log = read("../../CHANGELOG.md");
  const start = log.indexOf("## [1.2.0]");
  assert.ok(start >= 0);
  const end = log.indexOf("\n## [", start + 1);
  const section = log.slice(start, end);
  for (const s of RECORD_STATUSES) assert.ok(section.includes(`\`${s}\``), s);
  assert.ok(section.includes("`lookup_failed`"));
  assert.ok(!section.includes("\u2014"));
});
