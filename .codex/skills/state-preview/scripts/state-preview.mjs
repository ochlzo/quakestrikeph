#!/usr/bin/env node
import {
  readFile,
  writeFile,
  mkdir,
  readdir,
  lstat,
  realpath,
  copyFile,
  rm,
  unlink,
} from "node:fs/promises";
import { resolve, relative, dirname, join, isAbsolute } from "node:path";
import { fileURLToPath } from "node:url";

const ignoreBlock =
  "# state-preview:start\n/.state-preview/\n# state-preview:end\n";
const fail = (message) => {
  throw new Error(message);
};
async function exists(path) {
  try {
    return await lstat(path);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}
function contained(root, path) {
  const rel = relative(root, path);
  return rel !== "" && !rel.startsWith("..") && !isAbsolute(rel);
}
async function safePath(root, input) {
  if (isAbsolute(input)) fail("Use a path relative to the app root.");
  const path = resolve(root, input);
  if (!contained(root, path)) fail("Path escapes the app root.");
  let ancestor = path;
  while (ancestor !== root) {
    if ((await exists(ancestor))?.isSymbolicLink())
      fail(`Symlinks are not supported: ${input}`);
    ancestor = dirname(ancestor);
  }
  if (relative(root, path).split(/[\\/]/).includes(".git"))
    fail("Cannot edit Git internals.");
  return path;
}
function count(source, snippet) {
  return source.split(snippet).length - 1;
}
async function readJournal(runtime, root) {
  const journal = JSON.parse(
    await readFile(join(runtime, "manifest.json"), "utf8"),
  );
  if (journal.version !== 1 || journal.root !== root)
    fail("Session root or manifest version does not match.");
  return journal;
}
async function rejectLinks(path) {
  const stat = await lstat(path);
  if (stat.isSymbolicLink()) fail(`Cannot remove a symlink: ${path}`);
  if (stat.isDirectory())
    for (const entry of await readdir(path))
      await rejectLinks(join(path, entry));
}

export async function run(args) {
  const command = args[0];
  const option = (name) => {
    const index = args.indexOf(name);
    return index < 0 ? undefined : args[index + 1];
  };
  if (!option("--root")) fail("Specify --root <app-root>.");
  const root = await realpath(resolve(option("--root")));
  const runtime = await safePath(root, ".state-preview");
  const present = await exists(runtime);
  if (command === "status") {
    if (!present) return "No state-preview session is installed.";
    const journal = await readJournal(runtime, root);
    return `Session: ${runtime}\nRecorded edits: ${journal.edits.length}`;
  }
  if (command === "init") {
    if (present)
      fail(
        "A state-preview session already exists. Resume or remove it first.",
      );
    const ignore = await safePath(root, ".gitignore");
    const oldIgnore = (await exists(ignore))
      ? await readFile(ignore, "utf8")
      : "";
    const alreadyIgnored = oldIgnore
      .split(/\r?\n/)
      .some((line) =>
        [
          ".state-preview",
          ".state-preview/",
          "/.state-preview",
          "/.state-preview/",
        ].includes(line.trim()),
      );
    const addition = alreadyIgnored
      ? ""
      : `${oldIgnore && !oldIgnore.endsWith("\n") ? "\n" : ""}${ignoreBlock}`;
    const templates = fileURLToPath(
      new URL("../assets/runtime/", import.meta.url),
    );
    const entries = await readdir(templates);
    await mkdir(runtime);
    for (const entry of entries)
      await copyFile(join(templates, entry), join(runtime, entry));
    await copyFile(
      fileURLToPath(import.meta.url),
      join(runtime, "state-preview.mjs"),
    );
    await writeFile(
      join(runtime, "manifest.json"),
      JSON.stringify(
        {
          version: 1,
          root,
          ignoreAddition: addition,
          ignoreExisted: !!(await exists(ignore)),
          edits: [],
        },
        null,
        2,
      ) + "\n",
    );
    if (addition) await writeFile(ignore, oldIgnore + addition);
    return `Initialized ${runtime}. Customize adapter.ts and record temporary edits in edits.json.`;
  }
  if (!present) fail("No state-preview session is installed.");
  const manifest = join(runtime, "manifest.json");
  const journal = await readJournal(runtime, root);
  const sources = new Map();
  const getSource = async (file) => {
    const path = await safePath(root, file);
    if (
      contained(runtime, path) ||
      path === runtime ||
      path === resolve(root, ".gitignore")
    )
      fail(
        "Record only target source edits; runtime and ignore files are managed separately.",
      );
    if (!sources.has(path)) sources.set(path, await readFile(path, "utf8"));
    return path;
  };
  if (command === "apply") {
    if (journal.edits.length)
      fail(
        "This session already has recorded edits. Do not apply the plan twice.",
      );
    const planPath = await safePath(
      root,
      option("--edits") || ".state-preview/edits.json",
    );
    if (!contained(runtime, planPath))
      fail("Store the edit plan inside .state-preview/.");
    const edits = JSON.parse(await readFile(planPath, "utf8"));
    if (!Array.isArray(edits) || !edits.length)
      fail("Edit plan must be a nonempty array.");
    for (const edit of edits) {
      if (
        typeof edit.file !== "string" ||
        typeof edit.before !== "string" ||
        typeof edit.after !== "string" ||
        !edit.before ||
        !edit.after ||
        edit.before === edit.after
      )
        fail(
          "Each edit needs file and distinct nonempty before/after snippets.",
        );
      if (!edit.after.includes("state-preview"))
        fail(`Missing state-preview marker in ${edit.file}.`);
      const path = await getSource(edit.file);
      const source = sources.get(path);
      if (count(source, edit.before) !== 1)
        fail(
          `Expected one before snippet in ${edit.file}. No source files changed.`,
        );
      sources.set(path, source.replace(edit.before, edit.after));
    }
    // Journal first so cleanup can recover after an interrupted write.
    journal.edits = edits;
    await writeFile(manifest, JSON.stringify(journal, null, 2) + "\n");
    for (const [path, source] of sources) await writeFile(path, source);
    return `Applied ${edits.length} temporary edits.`;
  }
  if (command === "remove") {
    for (const edit of [...journal.edits].reverse()) {
      const path = await getSource(edit.file);
      const source = sources.get(path);
      if (count(source, edit.after) === 1)
        sources.set(path, source.replace(edit.after, edit.before));
      else if (
        count(source, edit.after) === 0 &&
        count(source, edit.before) === 1
      )
        continue;
      else
        fail(`Preview snippet changed in ${edit.file}. No files were changed.`);
    }
    const ignore = await safePath(root, ".gitignore");
    const oldIgnore = (await exists(ignore))
      ? await readFile(ignore, "utf8")
      : "";
    let nextIgnore = oldIgnore;
    if (journal.ignoreAddition) {
      if (count(oldIgnore, journal.ignoreAddition) !== 1)
        fail("Generated ignore rule changed. No files were changed.");
      nextIgnore = oldIgnore.replace(journal.ignoreAddition, "");
    }
    await rejectLinks(runtime);
    if ((await realpath(runtime)) !== join(root, ".state-preview"))
      fail("Runtime location changed. No files were changed.");
    if (args.includes("--check"))
      return `Removal verified: ${journal.edits.length} edits; permanent changes remain.`;
    for (const [path, source] of sources) await writeFile(path, source);
    if (journal.ignoreAddition) {
      if (!journal.ignoreExisted && nextIgnore === "") await unlink(ignore);
      else await writeFile(ignore, nextIgnore);
    }
    await rm(runtime, { recursive: true });
    return "Removed state-preview files and recorded edits. Permanent changes remain.";
  }
  fail("Commands: init, status, apply, remove [--check].");
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  try {
    console.log(await run(process.argv.slice(2)));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
