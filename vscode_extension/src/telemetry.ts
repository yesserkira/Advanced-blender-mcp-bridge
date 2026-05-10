// Local-only usage telemetry.
//
// Aggregates the Blender add-on's audit log entries into a per-day JSON
// summary stored at `~/.blender_mcp/telemetry/summary-YYYY-MM-DD.json`.
// Nothing leaves the machine.
//
// Default OFF — opt-in via `blenderMcp.telemetry.enabled`.

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

export interface AuditEntry {
  ts: string;          // ISO timestamp from the add-on
  op: string;
  ok: boolean;
  elapsed_ms: number;
}

export interface OpStats {
  ok: number;
  err: number;
  total_ms: number;
}

export interface DailySummary {
  date: string;        // YYYY-MM-DD
  counts: Record<string, OpStats>;
}

/**
 * Group audit entries by ISO date and tally per-op counts + total ms.
 * Pure function — easy to unit-test.
 */
export function aggregate(audit: AuditEntry[]): DailySummary[] {
  const byDate = new Map<string, Record<string, OpStats>>();
  for (const e of audit) {
    if (!e || typeof e.ts !== 'string' || typeof e.op !== 'string') { continue; }
    // Take just the date portion of the ISO timestamp. Avoids timezone
    // surprises — we record the date the add-on observed.
    const date = e.ts.slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) { continue; }
    let day = byDate.get(date);
    if (!day) { day = {}; byDate.set(date, day); }
    let stats = day[e.op];
    if (!stats) { stats = { ok: 0, err: 0, total_ms: 0 }; day[e.op] = stats; }
    if (e.ok) { stats.ok += 1; } else { stats.err += 1; }
    if (typeof e.elapsed_ms === 'number' && e.elapsed_ms >= 0) {
      stats.total_ms += e.elapsed_ms;
    }
  }
  const out: DailySummary[] = [];
  for (const [date, counts] of byDate) {
    out.push({ date, counts });
  }
  // Newest first.
  out.sort((a, b) => (a.date < b.date ? 1 : -1));
  return out;
}

/** Cross-platform telemetry directory. */
export function summariesDir(): string {
  return path.join(os.homedir(), '.blender_mcp', 'telemetry');
}

/** Write each summary to its own file. Creates the dir if needed. */
export async function writeSummaries(
  dir: string,
  summaries: DailySummary[],
): Promise<void> {
  await fs.promises.mkdir(dir, { recursive: true });
  await Promise.all(summaries.map(async (s) => {
    const file = path.join(dir, `summary-${s.date}.json`);
    const json = JSON.stringify(s, null, 2);
    await fs.promises.writeFile(file, json, { encoding: 'utf-8' });
    // Best-effort tighten perms (Windows ignores chmod).
    try { await fs.promises.chmod(file, 0o600); } catch { /* ignore */ }
  }));
}

/**
 * Delete summary files older than `keepDays`. Files outside the standard
 * `summary-YYYY-MM-DD.json` shape are left alone (defensive — never delete
 * arbitrary user files even if they end up in this directory).
 */
export async function pruneOldSummaries(
  dir: string,
  keepDays: number,
): Promise<number> {
  if (keepDays < 1) { keepDays = 1; }
  let removed = 0;
  let entries: string[];
  try {
    entries = await fs.promises.readdir(dir);
  } catch {
    return 0; // dir doesn't exist
  }
  const cutoff = Date.now() - keepDays * 24 * 60 * 60 * 1000;
  await Promise.all(entries.map(async (name) => {
    const m = /^summary-(\d{4}-\d{2}-\d{2})\.json$/.exec(name);
    if (!m) { return; }
    const fileDate = Date.parse(`${m[1]}T00:00:00Z`);
    if (Number.isNaN(fileDate)) { return; }
    if (fileDate < cutoff) {
      try {
        await fs.promises.unlink(path.join(dir, name));
        removed += 1;
      } catch { /* ignore */ }
    }
  }));
  return removed;
}

/** Read all summary files into an array, newest first. Best-effort. */
export async function readSummaries(dir: string): Promise<DailySummary[]> {
  let entries: string[];
  try {
    entries = await fs.promises.readdir(dir);
  } catch {
    return [];
  }
  const out: DailySummary[] = [];
  await Promise.all(entries.map(async (name) => {
    if (!/^summary-\d{4}-\d{2}-\d{2}\.json$/.test(name)) { return; }
    try {
      const raw = await fs.promises.readFile(path.join(dir, name), 'utf-8');
      const parsed = JSON.parse(raw) as DailySummary;
      if (parsed?.date && parsed?.counts) { out.push(parsed); }
    } catch { /* skip bad files */ }
  }));
  out.sort((a, b) => (a.date < b.date ? 1 : -1));
  return out;
}

/** Convenience: top N ops by total call count. */
export function topOps(
  summary: DailySummary | DailySummary[],
  limit: number,
): Array<{ op: string; ok: number; err: number; total_ms: number }> {
  const merged: Record<string, OpStats> = {};
  const list = Array.isArray(summary) ? summary : [summary];
  for (const s of list) {
    for (const [op, st] of Object.entries(s.counts)) {
      let into = merged[op];
      if (!into) { into = { ok: 0, err: 0, total_ms: 0 }; merged[op] = into; }
      into.ok += st.ok;
      into.err += st.err;
      into.total_ms += st.total_ms;
    }
  }
  return Object.entries(merged)
    .map(([op, st]) => ({ op, ...st }))
    .sort((a, b) => (b.ok + b.err) - (a.ok + a.err))
    .slice(0, limit);
}
