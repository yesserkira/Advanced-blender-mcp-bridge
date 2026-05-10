import { strict as assert } from 'node:assert';

import { getPreviewHtml } from '../src/viewportPreview';

// ---------------------------------------------------------------------------
// getPreviewHtml
// ---------------------------------------------------------------------------

describe('getPreviewHtml', () => {
  const fakeWebview = {} as never;
  const nonce = 'test-nonce-abc123';

  it('returns valid HTML with DOCTYPE', () => {
    const html = getPreviewHtml(fakeWebview, nonce);
    assert.ok(html.startsWith('<!DOCTYPE html>'));
  });

  it('includes CSP meta tag with the nonce', () => {
    const html = getPreviewHtml(fakeWebview, nonce);
    assert.ok(html.includes(`nonce-${nonce}`));
    assert.ok(html.includes('Content-Security-Policy'));
  });

  it('includes the Refresh button', () => {
    const html = getPreviewHtml(fakeWebview, nonce);
    assert.ok(html.includes('id="btnRefresh"'));
  });

  it('includes the Save PNG button', () => {
    const html = getPreviewHtml(fakeWebview, nonce);
    assert.ok(html.includes('id="btnSave"'));
  });

  it('includes auto-refresh controls', () => {
    const html = getPreviewHtml(fakeWebview, nonce);
    assert.ok(html.includes('id="chkAuto"'));
    assert.ok(html.includes('id="numInterval"'));
  });

  it('includes viewport image element', () => {
    const html = getPreviewHtml(fakeWebview, nonce);
    assert.ok(html.includes('id="viewport"'));
  });

  it('restricts img-src to data: only', () => {
    const html = getPreviewHtml(fakeWebview, nonce);
    assert.ok(html.includes("img-src data:"));
  });

  it('uses the nonce in style and script tags', () => {
    const html = getPreviewHtml(fakeWebview, nonce);
    const nonceCount = (html.match(new RegExp(`nonce="${nonce}"`, 'g')) ?? []).length;
    // At least style + script tag
    assert.ok(nonceCount >= 2, `Expected >=2 nonce attributes, got ${nonceCount}`);
  });
});
