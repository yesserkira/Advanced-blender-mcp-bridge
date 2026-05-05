// Lightweight WebSocket client tailored for the Blender MCP add-on.
// Uses Node's `net` module so we have zero npm dependencies and can ship the
// extension without bundling. One-shot request/response per connection.

import * as net from 'net';
import * as crypto from 'crypto';

export interface WsResponse {
  ok: boolean;
  result?: Record<string, unknown>;
  error?: { code: string; message: string };
}

export interface CallOptions {
  host: string;
  port: number;
  token: string;
  op: string;
  args?: Record<string, unknown>;
  timeoutMs?: number;
}

export async function call(opts: CallOptions): Promise<WsResponse> {
  const id = `vscode-${crypto.randomBytes(4).toString('hex')}`;
  const payload = JSON.stringify({
    id,
    op: opts.op,
    args: opts.args ?? {},
    auth: opts.token,
  });
  return wsRequest(opts.host, opts.port, payload, opts.timeoutMs ?? 15_000);
}

export function wsRequest(
  host: string,
  port: number,
  payload: string,
  timeoutMs = 15_000,
): Promise<WsResponse> {
  return new Promise((resolve, reject) => {
    const key = crypto.randomBytes(16).toString('base64');
    const socket = net.createConnection({ host, port }, () => {
      const req = [
        `GET / HTTP/1.1`,
        `Host: ${host}:${port}`,
        `Upgrade: websocket`,
        `Connection: Upgrade`,
        `Sec-WebSocket-Key: ${key}`,
        `Sec-WebSocket-Version: 13`,
        ``,
        ``,
      ].join('\r\n');
      socket.write(req);
    });

    let upgraded = false;
    let headerBuf: Buffer = Buffer.alloc(0);
    let frameBuf: Buffer = Buffer.alloc(0);
    let messageSent = false;

    const timer = setTimeout(() => {
      socket.destroy();
      reject(new Error('WebSocket request timed out'));
    }, timeoutMs);

    socket.on('data', (chunk: Buffer) => {
      if (!upgraded) {
        headerBuf = Buffer.concat([headerBuf, chunk]);
        const headerEnd = headerBuf.indexOf('\r\n\r\n');
        if (headerEnd === -1) { return; }
        const headerStr = headerBuf.subarray(0, headerEnd).toString();
        if (!headerStr.includes('101')) {
          clearTimeout(timer);
          socket.destroy();
          reject(new Error(`WebSocket upgrade failed: ${headerStr.split('\r\n')[0]}`));
          return;
        }
        upgraded = true;
        const remaining = headerBuf.subarray(headerEnd + 4);
        headerBuf = Buffer.alloc(0);
        if (!messageSent) {
          messageSent = true;
          socket.write(encodeTextFrame(payload));
        }
        if (remaining.length > 0) {
          frameBuf = Buffer.concat([frameBuf, remaining]);
          tryParseFrame();
        }
      } else {
        frameBuf = Buffer.concat([frameBuf, chunk]);
        tryParseFrame();
      }
    });

    function tryParseFrame(): void {
      // Drain progress frames until we have a final response.
      // Server may send multiple {"type":"progress",...} frames before the
      // final result frame; skip them.
      while (true) {
        const decoded = decodeFrame(frameBuf);
        if (!decoded) { return; }
        frameBuf = decoded.rest;
        let parsed: Record<string, unknown> | undefined;
        try {
          parsed = JSON.parse(decoded.text) as Record<string, unknown>;
        } catch {
          clearTimeout(timer);
          socket.destroy();
          reject(new Error('Invalid JSON in WebSocket response'));
          return;
        }
        if (parsed && parsed['type'] === 'progress') {
          continue;
        }
        clearTimeout(timer);
        socket.write(encodeCloseFrame());
        socket.end();
        resolve(parsed as unknown as WsResponse);
        return;
      }
    }

    socket.on('error', (err) => {
      clearTimeout(timer);
      reject(err);
    });
    socket.on('close', () => {
      clearTimeout(timer);
    });
  });
}

function encodeTextFrame(text: string): Buffer {
  const data = Buffer.from(text, 'utf8');
  const len = data.length;
  let header: Buffer;
  if (len < 126) {
    header = Buffer.alloc(2);
    header[0] = 0x81;
    header[1] = 0x80 | len;
  } else if (len < 65536) {
    header = Buffer.alloc(4);
    header[0] = 0x81;
    header[1] = 0x80 | 126;
    header.writeUInt16BE(len, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x81;
    header[1] = 0x80 | 127;
    header.writeUInt32BE(0, 2);
    header.writeUInt32BE(len, 6);
  }
  const mask = crypto.randomBytes(4);
  const masked = Buffer.alloc(len);
  for (let i = 0; i < len; i++) {
    masked[i] = data[i] ^ mask[i % 4];
  }
  return Buffer.concat([header, mask, masked]);
}

function encodeCloseFrame(): Buffer {
  const mask = crypto.randomBytes(4);
  return Buffer.concat([Buffer.from([0x88, 0x80]), mask]);
}

function decodeFrame(buf: Buffer): { text: string; rest: Buffer } | undefined {
  if (buf.length < 2) { return undefined; }
  const byte1 = buf[0];
  const byte2 = buf[1];
  const isFin = (byte1 & 0x80) !== 0;
  const opcode = byte1 & 0x0f;
  const hasMask = (byte2 & 0x80) !== 0;
  let payloadLen = byte2 & 0x7f;
  let offset = 2;
  if (opcode === 0x8) { return undefined; }
  if (payloadLen === 126) {
    if (buf.length < 4) { return undefined; }
    payloadLen = buf.readUInt16BE(2);
    offset = 4;
  } else if (payloadLen === 127) {
    if (buf.length < 10) { return undefined; }
    payloadLen = buf.readUInt32BE(6);
    offset = 10;
  }
  if (hasMask) { offset += 4; }
  if (buf.length < offset + payloadLen) { return undefined; }
  const payload = buf.subarray(offset, offset + payloadLen);
  if (!isFin) { return undefined; }
  return {
    text: payload.toString('utf8'),
    rest: buf.subarray(offset + payloadLen),
  };
}

// Resolve connection settings from configuration / environment.
export function getConnectionConfig(): { host: string; port: number; token: string } {
  // vscode is not imported here to keep this module test-friendly; the caller
  // passes the values in through getConfiguration().
  throw new Error('Use vscode workspace configuration in the caller');
}
