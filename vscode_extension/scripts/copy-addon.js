// Build helper: copies the latest dist/blender_mcp_addon_v*.zip into
// vscode_extension/resources/blender_mcp_addon.zip so the .vsix can ship
// the add-on alongside the extension itself. Runs as part of
// `vscode:prepublish`.
//
// Resolution rules:
//   1. Look in <repo-root>/dist/ for blender_mcp_addon_v*.zip
//   2. If multiple, pick the highest semver
//   3. Copy to ./resources/blender_mcp_addon.zip (overwrite)
//   4. Also write resources/blender_mcp_addon.version.txt with the version
//      so the runtime can compare against installed without unzipping.

const fs = require('node:fs');
const path = require('node:path');

const extDir = path.resolve(__dirname, '..');
const repoRoot = path.resolve(extDir, '..');
const distDir = path.join(repoRoot, 'dist');
const resourcesDir = path.join(extDir, 'resources');

function parseVersion(name) {
    // blender_mcp_addon_v2.6.0.zip → [2,6,0]
    const m = /^blender_mcp_addon_v(\d+)\.(\d+)\.(\d+)\.zip$/.exec(name);
    if (!m) { return null; }
    return [parseInt(m[1], 10), parseInt(m[2], 10), parseInt(m[3], 10)];
}

function compareVersions(a, b) {
    for (let i = 0; i < 3; i++) {
        if (a[i] !== b[i]) { return a[i] - b[i]; }
    }
    return 0;
}

function main() {
    if (!fs.existsSync(distDir)) {
        console.warn(`[copy-addon] No dist/ at ${distDir}; skipping addon bundle.`);
        return;
    }
    const candidates = fs.readdirSync(distDir)
        .map((n) => ({ name: n, ver: parseVersion(n) }))
        .filter((x) => x.ver !== null)
        .sort((a, b) => compareVersions(b.ver, a.ver));
    if (candidates.length === 0) {
        console.warn('[copy-addon] No blender_mcp_addon_v*.zip in dist/; skipping.');
        return;
    }
    const pick = candidates[0];
    fs.mkdirSync(resourcesDir, { recursive: true });
    const dest = path.join(resourcesDir, 'blender_mcp_addon.zip');
    fs.copyFileSync(path.join(distDir, pick.name), dest);
    fs.writeFileSync(
        path.join(resourcesDir, 'blender_mcp_addon.version.txt'),
        pick.ver.join('.') + '\n',
        'utf-8',
    );
    console.log(`[copy-addon] Bundled ${pick.name} (v${pick.ver.join('.')}) → resources/`);
}

main();
