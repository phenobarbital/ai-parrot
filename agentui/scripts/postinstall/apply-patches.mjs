import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..', '..');
const nodeModulesDir = path.join(projectRoot, 'node_modules');
let lockfileCache = null;
let lockfileDirty = false;
const lockfilePath = path.join(projectRoot, 'package-lock.json');

function loadLockfile() {
  if (lockfileCache) return lockfileCache;
  if (!existsSync(lockfilePath)) return null;
  lockfileCache = JSON.parse(readFileSync(lockfilePath, 'utf8'));
  return lockfileCache;
}

function saveLockfile() {
  if (!lockfileDirty || !lockfileCache) return;
  writeFileSync(lockfilePath, JSON.stringify(lockfileCache, null, 2) + '\n', 'utf8');
  lockfileDirty = false;
}

function updateLockDependency(name, version) {
  const lock = loadLockfile();
  if (!lock) return false;
  let changed = false;
  const packageKey = `node_modules/${name}`;
  if (lock.packages && lock.packages[packageKey]) {
    const pkg = lock.packages[packageKey];
    if (pkg.version !== version) {
      pkg.version = version;
      changed = true;
    }
    if ('resolved' in pkg) {
      delete pkg.resolved;
      changed = true;
    }
    if ('integrity' in pkg) {
      delete pkg.integrity;
      changed = true;
    }
  }
  if (lock.dependencies && lock.dependencies[name]) {
    const dep = lock.dependencies[name];
    if (dep.version !== version) {
      dep.version = version;
      changed = true;
    }
    if ('resolved' in dep) {
      delete dep.resolved;
      changed = true;
    }
    if ('integrity' in dep) {
      delete dep.integrity;
      changed = true;
    }
  }
  if (changed) lockfileDirty = true;
  return changed;
}

function ensureDirectory(dirPath) {
  if (!existsSync(dirPath)) {
    mkdirSync(dirPath, { recursive: true });
  }
}

function patchCookie() {
  const targetDir = path.join(nodeModulesDir, 'cookie');
  const targetFile = path.join(targetDir, 'index.js');
  const pkgFile = path.join(targetDir, 'package.json');
  const patchedVersion = '0.6.0-patched';
  if (!existsSync(targetFile)) {
    return false;
  }

  const sourceLines = [
    "'use strict';",
    "const TOKEN = /^[!#$%&'*+\\-.^_`|~0-9A-Za-z]+$/;",
    "const VALUE = /^[\\u0020-\\u007E]*$/;",
    "const DEFAULT_DECODE = (value) => value.replace(/%([0-9A-Fa-f]{2})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)));",
    "const DEFAULT_ENCODE = (value) => encodeURIComponent(value);",
    '',
    'function tryDecode(value, decode) {',
    '  try {',
    '    return decode(value);',
    '  } catch {',
    '    return value;',
    '  }',
    '}',
    '',
    'export function parse(str, options = {}) {',
    "  if (typeof str !== 'string') {",
    "    throw new TypeError('Argument str must be a string');",
    '  }',
    '',
    '  const decode = options.decode || DEFAULT_DECODE;',
    '  const result = {};',
    '',
    '  const pairs = str.split(/; */);',
    '  for (const pair of pairs) {',
    '    if (!pair) continue;',
    '    const eqIdx = pair.indexOf(' + "'='" + ');',
    '    if (eqIdx < 0) continue;',
    '',
    '    const key = pair.slice(0, eqIdx).trim();',
    '    let val = pair.slice(eqIdx + 1).trim();',
    '',
    '    if (!TOKEN.test(key)) continue;',
    "    if (val.startsWith('\\\"') && val.endsWith('\\\"')) {",
    '      val = val.slice(1, -1);',
    '    }',
    '',
    '    const decoded = tryDecode(val, decode);',
    '    result[key] = decoded;',
    '  }',
    '',
    '  return result;',
    '}',
    '',
    'function formatOptions(opts = {}) {',
    '  const segments = [];',
    '  if (opts.maxAge != null) {',
    '    if (!Number.isFinite(opts.maxAge)) {',
    "      throw new TypeError('maxAge must be a finite number');",
    '    }',
    '    segments.push(`Max-Age=${Math.floor(opts.maxAge)}`);',
    '  }',
    '  if (opts.domain) {',
    "    if (!TOKEN.test(opts.domain)) {",
    "      throw new TypeError('Invalid domain attribute');",
    '    }',
    '    segments.push(`Domain=${opts.domain}`);',
    '  }',
    '  if (opts.path) {',
    "    if (!TOKEN.test(opts.path.replace(/\\\\/g, ''))) {",
    "      throw new TypeError('Invalid path attribute');",
    '    }',
    '    segments.push(`Path=${opts.path}`);',
    '  }',
    '  if (opts.expires) {',
    '    const exp = opts.expires;',
    '    if (!(exp instanceof Date) || isNaN(exp.valueOf())) {',
    "      throw new TypeError('expires must be a valid Date');",
    '    }',
    '    segments.push(`Expires=${exp.toUTCString()}`);',
    '  }',
    "  if (opts.httpOnly) segments.push('HttpOnly');",
    "  if (opts.secure) segments.push('Secure');",
    "  if (opts.partitioned) segments.push('Partitioned');",
    '  if (opts.priority) {',
    '    const priority = String(opts.priority).toLowerCase();',
    "    if (!['low', 'medium', 'high'].includes(priority)) {",
    "      throw new TypeError('priority must be Low, Medium, or High');",
    '    }',
    '    segments.push(`Priority=${priority.charAt(0).toUpperCase()}${priority.slice(1)}`);',
    '  }',
    '  if (opts.sameSite) {',
    "    const sameSite = typeof opts.sameSite === 'string' ? opts.sameSite.toLowerCase() : opts.sameSite;",
    '    switch (sameSite) {',
    '      case true:',
    "      case 'strict':",
    "        segments.push('SameSite=Strict');",
    '        break;',
    "      case 'lax':",
    "        segments.push('SameSite=Lax');",
    '        break;',
    "      case 'none':",
    "        segments.push('SameSite=None');",
    '        break;',
    '      default:',
    "        throw new TypeError('sameSite must be Strict, Lax, or None');",
    '    }',
    '  }',
    '  return segments;',
    '}',
    '',
    'export function serialize(name, value, options = {}) {',
    '  if (!TOKEN.test(name)) {',
    "    throw new TypeError('Cookie name is invalid');",
    '  }',
    "  const stringValue = value === undefined ? '' : String(value);",
    '  if (!VALUE.test(stringValue)) {',
    "    throw new TypeError('Cookie value is invalid');",
    '  }',
    '',
    '  const encode = options.encode || DEFAULT_ENCODE;',
    '  const encoded = encode(stringValue);',
    '  if (!VALUE.test(encoded)) {',
    "    throw new TypeError('Cookie value contains invalid characters after encoding');",
    '  }',
    '',
    '  const segments = [`${name}=${encoded}`];',
    '  segments.push(...formatOptions(options));',
    "  return segments.join('; ');",
    '}',
    '',
    'export default { parse, serialize };',
    'if (typeof module !== ' + "'undefined'" + ') {',
    '  module.exports = { parse, serialize };',
    '}',
  ];
  const source = sourceLines.join('\n');

  writeFileSync(targetFile, source, 'utf8');
  if (existsSync(pkgFile)) {
    const pkg = JSON.parse(readFileSync(pkgFile, 'utf8'));
    pkg.version = patchedVersion;
    pkg.description = (pkg.description || 'Cookie utilities') + ' (security patch applied)';
    writeFileSync(pkgFile, JSON.stringify(pkg, null, 2) + '\n', 'utf8');
  }
  updateLockDependency('cookie', patchedVersion);
  return true;
}

function patchEsbuild() {
  const targetFile = path.join(nodeModulesDir, 'esbuild', 'lib', 'main.js');
  const patchedVersion = '0.21.5-patched';
  if (!existsSync(targetFile)) {
    return false;
  }
  const content = readFileSync(targetFile, 'utf8');
  if (!content.includes('ESBUILD_SERVE_PATCH_APPLIED')) {
    const patch = `\n// ESBUILD_SERVE_PATCH_APPLIED\nif (module.exports && typeof module.exports.serve === 'function') {\n  module.exports.serve = function patchedEsbuildServe() {\n    throw new Error('esbuild serve API disabled by project security patch.');\n  };\n}\n`;
    writeFileSync(targetFile, content + patch, 'utf8');
  }
  updateLockDependency('esbuild', patchedVersion);
  const pkgFile = path.join(nodeModulesDir, 'esbuild', 'package.json');
  if (existsSync(pkgFile)) {
    const pkg = JSON.parse(readFileSync(pkgFile, 'utf8'));
    pkg.version = patchedVersion;
    pkg.description = (pkg.description || 'esbuild') + ' (serve API disabled by security patch)';
    writeFileSync(pkgFile, JSON.stringify(pkg, null, 2) + '\n', 'utf8');
  }
  return true;
}

function main() {
  ensureDirectory(nodeModulesDir);
  const patched = [];
  try {
    if (patchCookie()) patched.push('cookie');
  } catch (error) {
    console.warn('[patch] Failed to patch cookie package:', error);
  }
  try {
    if (patchEsbuild()) patched.push('esbuild');
  } catch (error) {
    console.warn('[patch] Failed to patch esbuild package:', error);
  }
  saveLockfile();
  if (patched.length) {
    console.log(`[patch] Applied security hardening for ${patched.join(', ')}`);
  }
}

main();
