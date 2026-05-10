// Approval-server unit tests: rate limit + request_id length requirement.
// We talk to the real ApprovalServer over loopback HTTP — no mocking.

import { strict as assert } from 'node:assert';
import * as http from 'node:http';
import { ApprovalServer, getWebviewContent } from '../src/approval';

function post(
  port: number,
  path: string,
  body: string,
  headers: Record<string, string>,
): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const req = http.request(
      { host: '127.0.0.1', port, path, method: 'POST', headers },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (c: Buffer) => chunks.push(c));
        res.on('end', () => resolve({
          status: res.statusCode ?? 0,
          body: Buffer.concat(chunks).toString('utf-8'),
        }));
      },
    );
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

describe('ApprovalServer', () => {
  let server: ApprovalServer;
  let port: number;
  let csrf: string;

  beforeEach(async () => {
    server = new ApprovalServer();
    port = await server.start(0);
    csrf = server.getCsrf();
  });

  afterEach(async () => {
    await server.stop();
  });

  function jsonHeaders(): Record<string, string> {
    return { 'Content-Type': 'application/json', 'x-csrf': csrf };
  }

  it('rejects request_id shorter than 16 chars', async () => {
    const res = await post(port, '/approve', JSON.stringify({
      tool: 'ping', args: {}, request_id: 'short',
    }), jsonHeaders());
    assert.equal(res.status, 400);
    assert.match(res.body, /at least 16/);
  });

  it('rejects bad CSRF', async () => {
    const res = await post(port, '/approve', JSON.stringify({
      tool: 'ping', args: {}, request_id: 'a'.repeat(32),
    }), { 'Content-Type': 'application/json', 'x-csrf': 'wrong' });
    assert.equal(res.status, 403);
  });

  it('rejects bad content-type', async () => {
    const res = await post(port, '/approve', '{}', {
      'Content-Type': 'text/plain', 'x-csrf': csrf,
    });
    assert.equal(res.status, 415);
  });

  it('rejects malformed JSON', async () => {
    const res = await post(port, '/approve', '{not json', jsonHeaders());
    assert.equal(res.status, 400);
  });

  it('rate-limits after burst is exhausted', async () => {
    // Burst is 5; the 6th immediately should be 429.
    const body = JSON.stringify({
      tool: 'ping', args: {}, request_id: 'x'.repeat(32),
    });
    // Fire requests with bad CSRF so the rate-limited 429 is independent of
    // the approval webview (which can't show in headless tests). The rate
    // check runs BEFORE CSRF.
    const headers = { 'Content-Type': 'application/json', 'x-csrf': 'wrong' };
    const responses: number[] = [];
    for (let i = 0; i < 7; i++) {
      const r = await post(port, '/approve', body, headers);
      responses.push(r.status);
    }
    // First 5 are allowed through to CSRF check (403), then 429.
    const fourOhThrees = responses.filter((s) => s === 403).length;
    const fourTwoNines = responses.filter((s) => s === 429).length;
    assert.equal(fourOhThrees, 5, `expected 5x403, got ${responses.join(',')}`);
    assert.ok(fourTwoNines >= 1, `expected at least 1x429, got ${responses.join(',')}`);
  });
});

// ---------------------------------------------------------------------------
// getWebviewContent — code preview truncation (Phase 6)
// ---------------------------------------------------------------------------

describe('getWebviewContent code preview', () => {
  // Minimal webview stub — getWebviewContent only reads `cspSource`.
  const fakeWebview = { cspSource: 'self' } as unknown as Parameters<typeof getWebviewContent>[0];

  it('renders no code section when code is omitted', () => {
    const html = getWebviewContent(fakeWebview, 'ping', {});
    assert.ok(!html.includes('Python Code'));
    assert.ok(!html.includes('id="toggleCodeBtn"'));
    assert.ok(!html.includes('id="copyCodeBtn"'));
  });

  it('renders without toggle when code is short (<=3 lines)', () => {
    const html = getWebviewContent(fakeWebview, 'execute_python', {}, 'a = 1\nb = 2');
    assert.ok(html.includes('Python Code'));
    assert.ok(!html.includes('id="toggleCodeBtn"'));
    assert.ok(!html.includes('id="codeFull"'));
    // Copy button is always present when there's code.
    assert.ok(html.includes('id="copyCodeBtn"'));
  });

  it('truncates long code and emits a hidden full block + toggle', () => {
    const code = Array.from({ length: 10 }, (_, i) => `line ${i}`).join('\n');
    const html = getWebviewContent(fakeWebview, 'execute_python', {}, code);
    assert.ok(html.includes('id="toggleCodeBtn"'));
    assert.ok(html.includes('class="code-block code-full hidden"'));
    assert.ok(html.includes('aria-expanded="false"'));
    assert.match(html, /Showing first 3 of 10 lines/);
    // Preview includes only first 3 lines.
    assert.ok(html.includes('line 0'));
    assert.ok(html.includes('line 2'));
    // Full block (hidden) contains the rest.
    assert.ok(html.includes('line 9'));
  });

  it('truncates a single very long line at 500 chars', () => {
    const code = 'x'.repeat(800);
    const html = getWebviewContent(fakeWebview, 'execute_python', {}, code);
    assert.ok(html.includes('id="toggleCodeBtn"'));
    // Preview ends with an ellipsis marker indicating truncation.
    assert.ok(html.includes('\u2026') || html.includes('&hellip;'));
  });

  it('escapes HTML in user-supplied code', () => {
    const html = getWebviewContent(fakeWebview, 'execute_python', {}, '<script>alert(1)</script>');
    assert.ok(!html.includes('<script>alert(1)</script>'));
    assert.ok(html.includes('&lt;script&gt;'));
  });
});
