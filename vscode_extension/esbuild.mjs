// Production bundler. Outputs a single CommonJS file `out/extension.js`
// with `vscode` and Node built-ins kept external. Run via `npm run bundle`.

import { build } from 'esbuild';

const isWatch = process.argv.includes('--watch');

const options = {
    entryPoints: ['src/extension.ts'],
    bundle: true,
    outfile: 'out/extension.js',
    external: ['vscode'],
    format: 'cjs',
    platform: 'node',
    target: 'node20',
    sourcemap: false,
    minify: true,
    logLevel: 'info',
};

if (isWatch) {
    const ctx = await (await import('esbuild')).context(options);
    await ctx.watch();
} else {
    await build(options);
}
