import { strict as assert } from 'node:assert';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import {
  aggregate,
  writeSummaries,
  readSummaries,
  pruneOldSummaries,
  topOps,
  type AuditEntry,
} from '../src/telemetry';

describe('telemetry.aggregate', () => {
  it('returns empty for empty input', () => {
    assert.deepEqual(aggregate([]), []);
  });

  it('groups a single entry by date', () => {
    const out = aggregate([
      { ts: '2026-05-06T12:00:00Z', op: 'ping', ok: true, elapsed_ms: 5 },
    ]);
    assert.equal(out.length, 1);
    assert.equal(out[0].date, '2026-05-06');
    assert.deepEqual(out[0].counts.ping, { ok: 1, err: 0, total_ms: 5 });
  });

  it('mixes ok and err counts within one op', () => {
    const out = aggregate([
      { ts: '2026-05-06T10:00:00Z', op: 'create_primitive', ok: true, elapsed_ms: 10 },
      { ts: '2026-05-06T10:01:00Z', op: 'create_primitive', ok: false, elapsed_ms: 3 },
      { ts: '2026-05-06T10:02:00Z', op: 'create_primitive', ok: true, elapsed_ms: 7 },
    ]);
    assert.equal(out.length, 1);
    assert.deepEqual(out[0].counts.create_primitive, { ok: 2, err: 1, total_ms: 20 });
  });

  it('separates entries by date and sorts newest first', () => {
    const out = aggregate([
      { ts: '2026-05-04T08:00:00Z', op: 'a', ok: true, elapsed_ms: 1 },
      { ts: '2026-05-06T08:00:00Z', op: 'a', ok: true, elapsed_ms: 1 },
      { ts: '2026-05-05T08:00:00Z', op: 'a', ok: true, elapsed_ms: 1 },
    ]);
    assert.deepEqual(out.map((s) => s.date), ['2026-05-06', '2026-05-05', '2026-05-04']);
  });

  it('skips malformed entries silently', () => {
    const bad = [
      { ts: 'not-a-date', op: 'x', ok: true, elapsed_ms: 1 },
      { ts: '', op: 'x', ok: true, elapsed_ms: 1 },
      null,
      { ts: '2026-05-06T00:00:00Z' },
      { ts: '2026-05-06T00:00:00Z', op: 'y', ok: true, elapsed_ms: 2 },
    ] as unknown as AuditEntry[];
    const out = aggregate(bad);
    assert.equal(out.length, 1);
    assert.deepEqual(out[0].counts.y, { ok: 1, err: 0, total_ms: 2 });
  });
});

describe('telemetry.topOps', () => {
  it('returns top N by total call count, descending', () => {
    const out = topOps({
      date: '2026-05-06',
      counts: {
        a: { ok: 5, err: 0, total_ms: 50 },
        b: { ok: 1, err: 0, total_ms: 5 },
        c: { ok: 2, err: 1, total_ms: 30 },
      },
    }, 2);
    assert.equal(out.length, 2);
    assert.equal(out[0].op, 'a');
    assert.equal(out[1].op, 'c');
  });

  it('merges counts across multiple summaries', () => {
    const out = topOps([
      { date: '2026-05-06', counts: { ping: { ok: 3, err: 0, total_ms: 9 } } },
      { date: '2026-05-05', counts: { ping: { ok: 2, err: 1, total_ms: 6 } } },
    ], 5);
    assert.equal(out[0].op, 'ping');
    assert.equal(out[0].ok, 5);
    assert.equal(out[0].err, 1);
    assert.equal(out[0].total_ms, 15);
  });
});

describe('telemetry.writeSummaries + readSummaries', () => {
  let dir: string;
  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bmcp-tel-'));
  });
  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it('round-trips one summary to disk', async () => {
    await writeSummaries(dir, [{
      date: '2026-05-06',
      counts: { ping: { ok: 1, err: 0, total_ms: 4 } },
    }]);
    const files = fs.readdirSync(dir);
    assert.deepEqual(files, ['summary-2026-05-06.json']);
    const back = await readSummaries(dir);
    assert.equal(back.length, 1);
    assert.equal(back[0].counts.ping.total_ms, 4);
  });

  it('readSummaries returns [] when dir missing', async () => {
    const back = await readSummaries(path.join(dir, 'nope'));
    assert.deepEqual(back, []);
  });
});

describe('telemetry.pruneOldSummaries', () => {
  let dir: string;
  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bmcp-tel-prune-'));
  });
  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it('deletes files older than keepDays', async () => {
    // Write three files: today, 2 days ago, 40 days ago.
    const today = new Date();
    const isoOf = (offsetDays: number): string => {
      const d = new Date(today);
      d.setUTCDate(d.getUTCDate() - offsetDays);
      return d.toISOString().slice(0, 10);
    };
    for (const off of [0, 2, 40]) {
      fs.writeFileSync(
        path.join(dir, `summary-${isoOf(off)}.json`),
        '{"date":"x","counts":{}}',
      );
    }
    const removed = await pruneOldSummaries(dir, 7);
    assert.equal(removed, 1);
    const remaining = fs.readdirSync(dir).sort();
    assert.equal(remaining.length, 2);
    // 40-day-old one should be gone.
    assert.ok(!remaining.includes(`summary-${isoOf(40)}.json`));
  });

  it('leaves non-summary files alone', async () => {
    fs.writeFileSync(path.join(dir, 'random.txt'), 'hello');
    fs.writeFileSync(path.join(dir, 'summary-not-a-date.json'), '{}');
    const removed = await pruneOldSummaries(dir, 1);
    assert.equal(removed, 0);
    assert.equal(fs.readdirSync(dir).length, 2);
  });

  it('returns 0 when dir missing', async () => {
    const removed = await pruneOldSummaries(path.join(dir, 'no-such'), 7);
    assert.equal(removed, 0);
  });
});
