const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const path = require('node:path');
const configPath = path.resolve(__dirname, '../../dashboard/next.config.js');

function loadConfig(local) {
  const originalLoad = Module._load;
  const previous = { ...process.env };
  let sentryCalls = 0;
  Module._load = function (request, ...args) {
    if (request === '@sentry/nextjs') return { withSentryConfig(config) { sentryCalls++; return config; } };
    if (request === '@next/bundle-analyzer') return () => (config) => config;
    return originalLoad.call(this, request, ...args);
  };
  process.env.NEXT_PUBLIC_AGENTOPS_LOCAL_MODE = String(local);
  process.env.NODE_ENV = 'production';
  process.env.AGENTOPS_INTERNAL_API_URL = 'http://api:8000';
  delete require.cache[configPath];
  try {
    return { config: require(configPath), sentryCalls };
  } finally {
    Module._load = originalLoad;
    process.env = previous;
  }
}

test('local rewrites have no cloud destinations and do not enable Sentry', async () => {
  const { config, sentryCalls } = loadConfig(true);
  const rewrites = await config.rewrites();
  assert.equal(sentryCalls, 0);
  assert(rewrites.every((rule) => rule.destination.startsWith('http://api:8000/')));
  assert(!rewrites.some((rule) => rule.source.startsWith('/ingest') || rule.source.startsWith('/functions')));
  class NormalModuleReplacementPlugin {
    constructor(pattern, replacement) { this.pattern = pattern; this.replacement = replacement; }
  }
  const webpack = config.webpack({ plugins: [] }, { webpack: { NormalModuleReplacementPlugin } });
  assert(webpack.plugins[0].pattern.test('@/lib/fonts'));
  assert(webpack.plugins[0].replacement.endsWith('fonts.local.ts'));
});

test('cloud mode retains existing routing and Sentry behavior', async () => {
  const { config, sentryCalls } = loadConfig(false);
  assert.equal(sentryCalls, 1);
  assert((await config.rewrites()).some((rule) => rule.source === '/functions/v1/:path*'));
  assert.deepEqual(config.webpack({ plugins: [] }, { webpack: {} }).plugins, []);
});
