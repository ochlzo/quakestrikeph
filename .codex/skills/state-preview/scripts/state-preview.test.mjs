import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, readFile, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { run } from "./state-preview.mjs";

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), "state-preview-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, "app"));
  await writeFile(join(root, ".gitignore"), "node_modules/\n");
  const call = (command, ...args) => run([command, "--root", root, ...args]);
  await call("init");
  return { root, call };
}

test("one session; removal preserves unrelated edits and existing ignore rules", async (t) => {
  const { root, call } = await fixture(t);
  await assert.rejects(call("init"), /already exists/);
  await writeFile(join(root, "app", "view.ts"), "const feature = true;\nrender();\n");
  await writeFile(join(root, ".state-preview", "edits.json"), JSON.stringify([{ file: "app/view.ts", before: "render();", after: "// state-preview\npreview();" }]));
  await call("apply");
  await writeFile(join(root, "app", "view.ts"), (await readFile(join(root, "app", "view.ts"), "utf8")).replace("true", "false"));
  await call("remove", "--check");
  await call("remove");
  assert.equal(await readFile(join(root, "app", "view.ts"), "utf8"), "const feature = false;\nrender();\n");
  assert.equal(await readFile(join(root, ".gitignore"), "utf8"), "node_modules/\n");
  assert.match(await call("status"), /No state-preview/);
});

test("altered preview refuses before writing any file", async (t) => {
  const { root, call } = await fixture(t);
  for (const file of ["a.ts", "b.ts"]) await writeFile(join(root, "app", file), "render();");
  await writeFile(join(root, ".state-preview", "edits.json"), JSON.stringify(["a.ts", "b.ts"].map((file) => ({ file: `app/${file}`, before: "render();", after: "// state-preview\npreview();" }))));
  await call("apply");
  await writeFile(join(root, "app", "a.ts"), "// state-preview\nchanged();");
  await assert.rejects(call("remove"), /snippet changed/);
  assert.equal(await readFile(join(root, "app", "b.ts"), "utf8"), "// state-preview\npreview();");
});

test("path escapes and symlinks refuse; interrupted apply can be removed", async (t) => {
  const { root, call } = await fixture(t);
  await writeFile(join(root, ".state-preview", "edits.json"), JSON.stringify([{ file: "../escape.ts", before: "a", after: "// state-preview b" }]));
  await assert.rejects(call("apply"), /escapes/);
  await symlink(join(root, "app"), join(root, ".state-preview", "link"), "junction");
  await assert.rejects(call("remove"), /symlink/);
  await rm(join(root, ".state-preview", "link"));
  await writeFile(join(root, "app", "view.ts"), "render();");
  const manifest = join(root, ".state-preview", "manifest.json");
  const journal = JSON.parse(await readFile(manifest, "utf8"));
  journal.edits = [{ file: "app/view.ts", before: "render();", after: "// state-preview\npreview();" }];
  await writeFile(manifest, JSON.stringify(journal));
  await call("remove");
  assert.equal(await readFile(join(root, "app", "view.ts"), "utf8"), "render();");
});

test("root-level apps and existing preview ignore rules survive cleanup", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "state-preview-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  await writeFile(join(root, ".gitignore"), "/.state-preview/\n");
  await run(["init", "--root", root]);
  await run(["remove", "--root", root]);
  assert.equal(await readFile(join(root, ".gitignore"), "utf8"), "/.state-preview/\n");
});
