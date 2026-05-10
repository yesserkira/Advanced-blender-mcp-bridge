// Bundled snippet library for the Blender MCP tree view.
//
// Snippets are read from `resources/snippets.json` (packaged with the
// extension via `.vscodeignore`'s `!resources/**`). Loading is a one-shot
// best-effort read at first request and then cached for the session.

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

export interface Snippet {
  id: string;
  category: string;
  label: string;
  description?: string;
  prompt: string;
}

interface SnippetsFile {
  snippets?: Snippet[];
}

let _cache: Snippet[] | undefined;

/**
 * Resolve and cache the bundled snippet list. Returns an empty array on any
 * I/O or parse error (logged on the output channel by the caller via
 * `getSnippetLoadError()`).
 */
export function loadSnippets(context: vscode.ExtensionContext): Snippet[] {
  if (_cache) { return _cache; }
  const file = path.join(context.extensionPath, 'resources', 'snippets.json');
  try {
    const raw = fs.readFileSync(file, 'utf-8');
    const parsed = JSON.parse(raw) as SnippetsFile;
    const all = Array.isArray(parsed.snippets) ? parsed.snippets : [];
    // Defensive filter: every snippet must have id, label, prompt.
    _cache = all.filter((s) =>
      typeof s?.id === 'string' && s.id.length > 0 &&
      typeof s?.label === 'string' && s.label.length > 0 &&
      typeof s?.prompt === 'string' && s.prompt.length > 0,
    );
  } catch {
    _cache = [];
  }
  return _cache;
}

/** Look up one snippet by id. */
export function getSnippet(context: vscode.ExtensionContext, id: string): Snippet | undefined {
  return loadSnippets(context).find((s) => s.id === id);
}

/** Group snippets by their `category` field, preserving insertion order. */
export function groupByCategory(snippets: Snippet[]): Map<string, Snippet[]> {
  const out = new Map<string, Snippet[]>();
  for (const s of snippets) {
    const cat = s.category || 'Other';
    if (!out.has(cat)) { out.set(cat, []); }
    out.get(cat)!.push(s);
  }
  return out;
}
