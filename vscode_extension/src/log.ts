// Level-aware wrapper around vscode.OutputChannel. Reads
// `blenderMcp.logLevel` from configuration and filters messages accordingly.

import * as vscode from 'vscode';

export type LogLevel = 'error' | 'warn' | 'info' | 'debug';

const LEVEL_RANK: Record<LogLevel, number> = {
  error: 0,
  warn: 1,
  info: 2,
  debug: 3,
};

let _channel: vscode.OutputChannel | undefined;

export function init(channel: vscode.OutputChannel): void {
  _channel = channel;
}

function currentLevel(): LogLevel {
  const v = vscode.workspace.getConfiguration('blenderMcp').get<string>('logLevel', 'info');
  return (v in LEVEL_RANK ? v : 'info') as LogLevel;
}

function emit(level: LogLevel, msg: string): void {
  if (!_channel) { return; }
  if (LEVEL_RANK[level] > LEVEL_RANK[currentLevel()]) { return; }
  const ts = new Date().toISOString().slice(11, 23);
  _channel.appendLine(`[${ts}] ${level.toUpperCase().padEnd(5)} ${msg}`);
}

export function error(msg: string): void { emit('error', msg); }
export function warn(msg: string): void { emit('warn', msg); }
export function info(msg: string): void { emit('info', msg); }
export function debug(msg: string): void { emit('debug', msg); }
