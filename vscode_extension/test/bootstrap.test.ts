import { strict as assert } from 'node:assert';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import {
  parseVersionString,
  compareVersions,
  readInstalledAddonVersion,
  type AddonVersion,
} from '../src/bootstrap';

// ---------------------------------------------------------------------------
// parseVersionString
// ---------------------------------------------------------------------------

describe('parseVersionString', () => {
  it('parses a clean semver string', () => {
    const v = parseVersionString('2.8.0');
    assert.deepEqual(v, { major: 2, minor: 8, patch: 0 });
  });

  it('parses with leading whitespace', () => {
    const v = parseVersionString('  1.2.3');
    assert.deepEqual(v, { major: 1, minor: 2, patch: 3 });
  });

  it('parses with trailing text (only leading digits used)', () => {
    const v = parseVersionString('3.0.1-beta');
    assert.deepEqual(v, { major: 3, minor: 0, patch: 1 });
  });

  it('returns undefined for non-numeric input', () => {
    assert.equal(parseVersionString('abc'), undefined);
  });

  it('returns undefined for empty string', () => {
    assert.equal(parseVersionString(''), undefined);
  });

  it('returns undefined for partial version', () => {
    assert.equal(parseVersionString('2.8'), undefined);
  });
});

// ---------------------------------------------------------------------------
// compareVersions
// ---------------------------------------------------------------------------

describe('compareVersions', () => {
  const v = (ma: number, mi: number, p: number): AddonVersion =>
    ({ major: ma, minor: mi, patch: p });

  it('returns 0 for equal versions', () => {
    assert.equal(compareVersions(v(2, 8, 0), v(2, 8, 0)), 0);
  });

  it('returns negative when a < b (major)', () => {
    assert.ok(compareVersions(v(1, 9, 9), v(2, 0, 0)) < 0);
  });

  it('returns positive when a > b (minor)', () => {
    assert.ok(compareVersions(v(2, 9, 0), v(2, 8, 5)) > 0);
  });

  it('returns negative when a < b (patch)', () => {
    assert.ok(compareVersions(v(2, 8, 0), v(2, 8, 1)) < 0);
  });
});

// ---------------------------------------------------------------------------
// readInstalledAddonVersion
// ---------------------------------------------------------------------------

describe('readInstalledAddonVersion', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bmcp-boot-'));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it('parses bl_info version tuple', () => {
    const initPy = path.join(tmpDir, '__init__.py');
    fs.writeFileSync(initPy, `bl_info = {\n    "version": (2, 9, 0),\n}\n`);
    const v = readInstalledAddonVersion(initPy);
    assert.deepEqual(v, { major: 2, minor: 9, patch: 0 });
  });

  it('handles single-quoted keys', () => {
    const initPy = path.join(tmpDir, '__init__.py');
    fs.writeFileSync(initPy, `bl_info = {\n    'version': (1, 0, 5),\n}\n`);
    const v = readInstalledAddonVersion(initPy);
    assert.deepEqual(v, { major: 1, minor: 0, patch: 5 });
  });

  it('returns undefined for missing file', () => {
    assert.equal(readInstalledAddonVersion('/no/such/path/__init__.py'), undefined);
  });

  it('returns undefined when version tuple is absent', () => {
    const initPy = path.join(tmpDir, '__init__.py');
    fs.writeFileSync(initPy, 'bl_info = {}\n');
    assert.equal(readInstalledAddonVersion(initPy), undefined);
  });
});
