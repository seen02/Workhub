// Read-only live checks: authenticate existing test accounts and stop at the new-password form.
// Never submit the password change prompt or print credentials/cookies.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { Session, credentials, root, settings } from './sso_test_client.mjs';
import { getAuthentikPasswordChangeUrl } from '../integrations/outline/outline-65be53c3eb093a535ce260eb2f2da897bb07a29e/shared/utils/authentik.ts';

const entry = getAuthentikPasswordChangeUrl(
  settings.urls.auth + '/application/o/outline/', settings.urls.outline
);
assert.ok(entry);
const checks = {};

class AuthentikSession extends Session {
  async fetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (new URL(url).origin === settings.urls.auth && options.method === 'POST') {
      headers.set('Origin', settings.urls.auth);
      headers.set('Referer', settings.urls.auth + '/');
      headers.set('X-Authentik-CSRF', this.jar.get('authentik_csrf') || '');
    }
    return super.fetch(url, {...options, headers});
  }
}

async function passwordPrompt(session, account) {
  let url = entry;
  let authenticationRequired = false;
  for (let attempt = 0; attempt < 30; attempt++) {
    const current = new URL(url);
    if (current.pathname === '/if/flow/default-password-change/') {
      const shell = await session.fetch(url);
      assert.equal(shell.status, 200);
      const executor = new URL('/api/v3/flows/executor/default-password-change/', settings.urls.auth);
      executor.searchParams.set('query', current.search.slice(1));
      let response = await session.fetch(executor);
      for (let i = 0; i < 8 && response.headers.get('location'); i++) {
        response = await session.fetch(new URL(response.headers.get('location'), settings.urls.auth));
      }
      assert.equal(response.status, 200);
      const challenge = await response.json();
      assert.equal(challenge.component, 'ak-stage-prompt');
      const fields = challenge.fields.map(field => field.field_key);
      assert.ok(fields.includes('password') && fields.includes('password_repeat'));
      assert.equal(current.searchParams.get('next'), '/application/launch/outline/');
      return {authenticationRequired, component: challenge.component};
    }
    if (current.pathname.startsWith('/if/flow/')) {
      // The configured authentication flow verifies identity before opening password settings.
      await session.fetch(url);
      const executor = new URL('/api/v3/flows/executor/' + current.pathname.split('/')[3] + '/', settings.urls.auth);
      executor.searchParams.set('query', current.search.slice(1));
      let response = await session.fetch(executor);
      for (let i = 0; i < 8 && response.headers.get('location'); i++) {
        response = await session.fetch(new URL(response.headers.get('location'), settings.urls.auth));
      }
      const challenge = await response.json();
      if (process.env.SSO_TRACE) console.log('entry stage', challenge.component);
      if (challenge.component === 'xak-flow-redirect') {
        url = new URL(challenge.to, settings.urls.auth).href;
      } else {
        authenticationRequired = true;
        url = await session.flow(url, account);
      }
      continue;
    }
    const response = await session.fetch(url);
    assert.ok(response.headers.get('location'), 'Expected flow redirect');
    url = new URL(response.headers.get('location'), url).href;
  }
  throw new Error('Password change entry did not reach the prompt');
}

const active = new AuthentikSession();
await active.login(settings.urls.outline + '/auth/oidc', credentials.groupA);
const existing = await passwordPrompt(active, credentials.groupA);
assert.equal(existing.authenticationRequired, true);
checks.active_session_reauthenticates_then_opens_password_prompt = true;

const expired = await passwordPrompt(new AuthentikSession(), credentials.groupA);
assert.equal(expired.authenticationRequired, true);
checks.expired_session_authenticates_then_opens_password_prompt = true;

const launch = await active.fetch(settings.urls.auth + '/application/launch/outline/');
assert.equal(launch.status, 302);
assert.equal(new URL(launch.headers.get('location'), settings.urls.auth).origin, settings.urls.outline);
checks.cross_origin_return_uses_application_launcher = true;

if (!process.argv.includes('--entry-only')) {
  const page = await active.fetch(settings.urls.outline + '/settings');
  assert.equal(page.status, 200);
  const html = await page.text();
  const match = html.match(/"AUTHENTIK_PASSWORD_CHANGE_URL"\s*:\s*("(?:[^"\\]|\\.)*")/);
  assert.ok(match, 'Runtime public environment is missing the password change entry');
  assert.equal(JSON.parse(match[1]), entry);
  checks.running_outline_exposes_expected_link = true;
  const health = await fetch(settings.urls.outline + '/_health');
  assert.equal(health.status, 200);
  checks.running_outline_healthy = true;
}

const report = {checks, passwordChanged: false};
fs.mkdirSync(path.join(root, 'reports'), {recursive: true});
fs.writeFileSync(path.join(root, 'reports/password-change-live.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report, null, 2));
