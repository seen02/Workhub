/* oxlint-disable no-console */
/* oxlint-disable @typescript-oxlint/no-var-requires */
/* oxlint-disable no-undef */
const { execFile } = require("node:child_process");
const fs = require("node:fs/promises");
const path = require("node:path");
const root = __dirname;

/**
 * Resolves a fixed output directory within the project before removing files.
 * @param name the fixed directory name.
 * @returns the absolute build output path.
 */
function outputPath(name) {
  const buildRoot = path.resolve(root, "build");
  const target = path.resolve(buildRoot, name);
  if (!target.startsWith(buildRoot + path.sep)) {
    throw new Error("Build output must remain within the build directory");
  }
  return target;
}

/**
 * Compiles source using Node directly without platform-specific shells.
 * @param source the source directory.
 * @param output the output directory.
 * @returns a promise resolving when compilation succeeds.
 */
function compile(source, output) {
  const args = [require.resolve("@swc/cli/bin/swc.js"), source, "-d", output,
    "--strip-leading-paths", "--extensions", ".ts,.tsx",
    "--ignore", "**/*.test.ts,**/*.test.tsx,**/__mocks__/**", "--quiet"];
  return new Promise((resolve, reject) => {
    execFile(process.execPath, args, { cwd: root, windowsHide: true, maxBuffer: 16 * 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) { reject(new Error(stderr || stdout || error.message)); return; }
        resolve();
      });
  });
}

async function build() {
  console.log("Clean previous server build…");
  await Promise.all(["server", "plugins"].map((name) => fs.rm(outputPath(name), { recursive: true, force: true })));
  const entries = await fs.readdir(path.join(root, "plugins"), { withFileTypes: true });
  const plugins = entries.filter((entry) => entry.isDirectory()).map((entry) => entry.name);
  console.log("Compiling…");
  await Promise.all([compile("./server", "./build/server"), compile("./shared", "./build/shared")]);
  for (const plugin of plugins) {
    for (const directory of ["server", "shared"]) {
      const source = ["plugins", plugin, directory].join("/");
      try { await fs.access(path.join(root, source)); } catch { continue; }
      // SWC retains <plugin>/server or shared under the output directory.
      await compile(source, "./build/plugins");
    }
  }
  console.log("Copying static files…");
  const files = [
    ["server/collaboration/Procfile", "build/server/collaboration/Procfile"],
    ["server/static/error.dev.html", "build/server/error.dev.html"],
    ["server/static/error.prod.html", "build/server/error.prod.html"],
    ["package.json", "build/package.json"],
  ];
  for (const plugin of plugins) {
    const source = path.join("plugins", plugin, "plugin.json");
    try {
      await fs.access(path.join(root, source));
      files.push([source, path.join("build/plugins", plugin, "plugin.json")]);
    } catch { /* No metadata file to copy. */ }
  }
  await Promise.all(files.map(async ([source, destination]) => {
    const target = path.join(root, destination);
    await fs.mkdir(path.dirname(target), { recursive: true });
    await fs.copyFile(path.join(root, source), target);
  }));
  console.log("Done!");
}
build().catch((error) => { console.error(error); process.exitCode = 1; });
