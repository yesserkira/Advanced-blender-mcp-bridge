import { strict as assert } from 'node:assert';
import * as path from 'node:path';
import { loadSnippets, getSnippet, groupByCategory, type Snippet } from '../src/snippets';

// Build a fake ExtensionContext that points loadSnippets at the real
// resources/ folder bundled with the extension. Only `extensionPath` is read.
function fakeContext(): { extensionPath: string } {
  return { extensionPath: path.resolve(__dirname, '..') };
}

describe('snippets', () => {
  let all: Snippet[];

  before(() => {
    all = loadSnippets(fakeContext() as never);
  });

  it('loads at least 8 snippets from resources/snippets.json', () => {
    assert.ok(all.length >= 8, `expected >=8 snippets, got ${all.length}`);
  });

  it('every snippet has non-empty id, label, prompt, category', () => {
    for (const s of all) {
      assert.ok(s.id && s.id.length > 0, `bad id: ${JSON.stringify(s)}`);
      assert.ok(s.label && s.label.length > 0, `bad label: ${s.id}`);
      assert.ok(s.prompt && s.prompt.length > 0, `bad prompt: ${s.id}`);
      assert.ok(s.category && s.category.length > 0, `bad category: ${s.id}`);
    }
  });

  it('snippet ids are unique', () => {
    const ids = new Set<string>();
    for (const s of all) {
      assert.ok(!ids.has(s.id), `duplicate id: ${s.id}`);
      ids.add(s.id);
    }
  });

  it('getSnippet finds an entry by id', () => {
    const first = all[0];
    const found = getSnippet(fakeContext() as never, first.id);
    assert.equal(found?.id, first.id);
  });

  it('getSnippet returns undefined for a missing id', () => {
    assert.equal(getSnippet(fakeContext() as never, 'no-such-snippet'), undefined);
  });

  it('groupByCategory preserves insertion order within each category', () => {
    const groups = groupByCategory(all);
    let total = 0;
    for (const list of groups.values()) {
      total += list.length;
    }
    assert.equal(total, all.length);
  });
});
