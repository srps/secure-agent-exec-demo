const fs = require("node:fs");
const path = require("node:path");
const ivm = require("isolated-vm");

function resolveSafe(baseDir, relPath) {
  const full = path.resolve(baseDir, relPath);
  const base = path.resolve(baseDir) + path.sep;
  if (!full.startsWith(base)) {
    throw new Error(`Path escapes output dir: ${relPath}`);
  }
  return full;
}

function usage() {
  console.error("Usage: node js_isolate_runner.js <code.js> <out_dir>");
}

const args = process.argv.slice(2);
const codePath = args[0];
const outDir = args[1];

if (!codePath || !outDir) {
  usage();
  process.exit(2);
}

let code;
try {
  code = fs.readFileSync(codePath, "utf8");
} catch (err) {
  console.error("Failed to read code:", err.message || err);
  process.exit(2);
}

fs.mkdirSync(outDir, { recursive: true });

const LIMITS = {
  memoryLimitMB: 64,
  timeoutMs: 1000,
  maxFileBytes: 64 * 1024,
  maxTotalBytes: 256 * 1024,
  maxFiles: 64,
  maxPathLen: 200,
};

let totalBytes = 0;
let fileCount = 0;

const isolate = new ivm.Isolate({ memoryLimit: LIMITS.memoryLimitMB });
const context = isolate.createContextSync();
const jail = context.global;
jail.setSync("global", jail.derefInto());

const logRef = new ivm.Reference((...args) => {
  console.log(...args);
});
const writeRef = new ivm.Reference((name, content) => {
  if (String(name).length > LIMITS.maxPathLen) {
    throw new Error("Filename too long");
  }
  const target = resolveSafe(outDir, name);
  const data = String(content);
  const size = Buffer.byteLength(data, "utf8");
  if (size > LIMITS.maxFileBytes) {
    throw new Error("File too large");
  }
  if (fileCount + 1 > LIMITS.maxFiles) {
    throw new Error("Too many files");
  }
  if (totalBytes + size > LIMITS.maxTotalBytes) {
    throw new Error("Output quota exceeded");
  }
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, data, "utf8");
  fileCount += 1;
  totalBytes += size;
});
const appendRef = new ivm.Reference((name, content) => {
  if (String(name).length > LIMITS.maxPathLen) {
    throw new Error("Filename too long");
  }
  const target = resolveSafe(outDir, name);
  const data = String(content);
  const size = Buffer.byteLength(data, "utf8");
  if (size > LIMITS.maxFileBytes) {
    throw new Error("Append too large");
  }
  if (totalBytes + size > LIMITS.maxTotalBytes) {
    throw new Error("Output quota exceeded");
  }
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.appendFileSync(target, data, "utf8");
  totalBytes += size;
});
const readRef = new ivm.Reference((name) => {
  if (String(name).length > LIMITS.maxPathLen) {
    throw new Error("Filename too long");
  }
  const target = resolveSafe(outDir, name);
  const data = fs.readFileSync(target, "utf8");
  if (Buffer.byteLength(data, "utf8") > LIMITS.maxFileBytes) {
    throw new Error("Read exceeds max size");
  }
  return data;
});

jail.setSync("__hostLog", logRef);
jail.setSync("__hostWrite", writeRef);
jail.setSync("__hostAppend", appendRef);
jail.setSync("__hostRead", readRef);

const bootstrap = `
  const console = {
    log: (...args) => __hostLog.applySync(undefined, args, { arguments: { copy: true } }),
    error: (...args) => __hostLog.applySync(undefined, args, { arguments: { copy: true } })
  };
  globalThis.console = console;
  globalThis.writeFile = (name, content) =>
    __hostWrite.applySync(undefined, [name, content], { arguments: { copy: true } });
  globalThis.appendFile = (name, content) =>
    __hostAppend.applySync(undefined, [name, content], { arguments: { copy: true } });
  globalThis.readFile = (name) =>
    __hostRead.applySync(undefined, [name], { arguments: { copy: true } });
`;

const bootstrapScript = isolate.compileScriptSync(bootstrap);
bootstrapScript.runSync(context, { timeout: LIMITS.timeoutMs });

try {
  const script = isolate.compileScriptSync(code, {
    filename: path.basename(codePath),
  });
  script.runSync(context, { timeout: LIMITS.timeoutMs });
} catch (err) {
  console.error("JS error:", err && err.stack ? err.stack : err);
  process.exit(1);
}
