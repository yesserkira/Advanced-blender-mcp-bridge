// Preloaded by mocha via --require. Registers a stub `vscode` module in
// Node's Module._cache before any of our source files import it.
//
// Only the bits our non-host code actually touches are stubbed.

const Module = require('module');

const config = new Map();

function getConfiguration(section) {
    return {
        get(key, defaultValue) {
            const v = config.get(`${section}.${key}`);
            return v !== undefined ? v : defaultValue;
        },
        update() { return Promise.resolve(); },
        inspect() { return undefined; },
    };
}

class EventEmitter {
    constructor() { this.listeners = []; }
    get event() {
        return (cb) => {
            this.listeners.push(cb);
            return { dispose: () => { this.listeners = this.listeners.filter((x) => x !== cb); } };
        };
    }
    fire(v) { for (const cb of this.listeners) { cb(v); } }
    dispose() { this.listeners = []; }
}

class Disposable {
    constructor(fn) { this._fn = fn; }
    dispose() { if (this._fn) { this._fn(); } }
}

const TreeItemCollapsibleState = {
    None: 0,
    Collapsed: 1,
    Expanded: 2,
};

class TreeItem {
    constructor(labelOrUri, collapsibleState) {
        if (typeof labelOrUri === 'string') {
            this.label = labelOrUri;
        }
        this.collapsibleState = collapsibleState ?? TreeItemCollapsibleState.None;
    }
}

class ThemeIcon {
    constructor(id) { this.id = id; }
}

const StatusBarAlignment = { Left: 1, Right: 2 };

class ThemeColor {
    constructor(id) { this.id = id; }
}

// In-memory globalState store.
const globalStateStore = new Map();
const globalState = {
    get(key, defaultValue) { const v = globalStateStore.get(key); return v !== undefined ? v : defaultValue; },
    update(key, value) { if (value === undefined) { globalStateStore.delete(key); } else { globalStateStore.set(key, value); } return Promise.resolve(); },
    keys() { return Array.from(globalStateStore.keys()); },
};

// In-memory SecretStorage stub.
function createSecretStorage() {
    const store = new Map();
    const emitter = new EventEmitter();
    return {
        get(key) { return Promise.resolve(store.get(key)); },
        store(key, value) { store.set(key, value); emitter.fire({ key }); return Promise.resolve(); },
        delete(key) { store.delete(key); emitter.fire({ key }); return Promise.resolve(); },
        onDidChange: emitter.event,
        _clear() { store.clear(); },
    };
}

// Uri stub (minimal for test usage).
class Uri {
    constructor(scheme, path, query, fragment) {
        this.scheme = scheme || '';
        this.path = path || '';
        this.query = query || '';
        this.fragment = fragment || '';
    }
    toString() { return `${this.scheme}:${this.path}`; }
    static parse(str) {
        const m = /^([a-z][\w-]*):(.*)$/i.exec(str);
        if (m) { return new Uri(m[1], m[2]); }
        return new Uri('', str);
    }
    static file(p) { return new Uri('file', '/' + p.replace(/\\/g, '/')); }
}

const vscodeStub = {
    workspace: {
        getConfiguration,
        workspaceFolders: [],
        onDidChangeConfiguration: () => ({ dispose() { } }),
        registerTextDocumentContentProvider: () => ({ dispose() { } }),
        openTextDocument: () => Promise.resolve({ uri: new Uri('', ''), languageId: 'json' }),
    },
    EventEmitter,
    Disposable,
    TreeItem,
    TreeItemCollapsibleState,
    ThemeIcon,
    ThemeColor,
    StatusBarAlignment,
    Uri,
    languages: {
        setTextDocumentLanguage: () => Promise.resolve(),
    },
    window: {
        showInformationMessage: () => Promise.resolve(undefined),
        showWarningMessage: () => Promise.resolve(undefined),
        showErrorMessage: () => Promise.resolve(undefined),
        showTextDocument: () => Promise.resolve(undefined),
        createOutputChannel: () => ({
            appendLine() { }, append() { }, show() { }, dispose() { },
        }),
        createStatusBarItem: () => ({
            text: '', tooltip: '', command: '', backgroundColor: undefined,
            show() { }, hide() { }, dispose() { },
        }),
    },
    commands: {
        executeCommand: () => Promise.resolve(undefined),
    },
    lm: {},
    extensions: {
        getExtension: () => undefined,
    },
};

// Monkey-patch the resolver so `require('vscode')` returns our stub.
const origResolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...rest) {
    if (request === 'vscode') { return 'vscode'; }
    return origResolve.call(this, request, ...rest);
};
require.cache['vscode'] = {
    id: 'vscode',
    filename: 'vscode',
    loaded: true,
    exports: vscodeStub,
    children: [],
    paths: [],
};

// Test helpers exposed via globals.
global._setMockConfig = (key, value) => config.set(key, value);
global._clearMockConfig = () => config.clear();
global._globalState = globalState;
global._clearGlobalState = () => globalStateStore.clear();
global._createSecretStorage = createSecretStorage;

module.exports = vscodeStub;
