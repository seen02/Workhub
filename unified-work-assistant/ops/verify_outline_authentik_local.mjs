// Read-only local smoke checks. Credentials stay in the existing private files.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {Session, settings, credentials, root} from './sso_test_client.mjs';

const checks = {};
function check(value, name) {
  if (!value) throw new Error(name);
  checks[name] = true;
}
const output = path.join(root, '.local/outline-authentik-20261019');
fs.mkdirSync(output, {recursive: true});
const baselineMode = process.argv.includes('--baseline');

await Promise.all([settings.urls.outline + '/_health', settings.urls.portal + '/health'].map(async (url) => {
  for (let attempt = 0; attempt < 50; attempt++) {
    try {
      if ((await fetch(url, {signal: AbortSignal.timeout(3000)})).ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error('Service did not become ready: ' + new URL(url).hostname);
}));

async function outlineApi(session, method, body = {}) {
  const response = await session.fetch(settings.urls.outline + '/api/' + method, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', Origin: settings.urls.outline,
      'X-CSRF-Token': decodeURIComponent(session.jar.get('csrfToken') || '')},
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(method + ' HTTP ' + response.status);
    error.status = response.status;
    throw error;
  }
  return data.data;
}

const admin = new Session();
await admin.login(settings.urls.outline + '/auth/oidc', credentials.authentikAdmin);
const collections = await outlineApi(admin, 'collections.list', {limit: 100});
const documents = {};
for (const collection of collections) {
  for (let offset = 0; ; offset += 100) {
    const page = await outlineApi(admin, 'documents.list', {collectionId: collection.id, limit: 100, offset});
    for (const row of page) {
      const doc = await outlineApi(admin, 'documents.info', {id: row.id});
      documents[doc.id] = crypto.createHash('sha256').update(JSON.stringify({
        title: doc.title, text: doc.text, collectionId: doc.collectionId, parentDocumentId: doc.parentDocumentId,
      })).digest('hex');
    }
    if (page.length < 100) break;
  }
}
const baselinePath = path.join(output, 'documents-before.json');
if (baselineMode) {
  if (fs.existsSync(baselinePath)) throw new Error('Baseline already exists');
  fs.writeFileSync(baselinePath, JSON.stringify(documents, null, 2));
  console.log(JSON.stringify({baselineDocuments: Object.keys(documents).length}));
  process.exit(0);
}
const before = JSON.parse(fs.readFileSync(baselinePath));
check(Object.entries(before).every(([id, hash]) => documents[id] === hash), 'existing_documents_preserved');
const capabilities = await outlineApi(admin, 'workhub.capabilities');
check(capabilities.enabled && capabilities.manage, 'outline_project_bridge_ready');
if (collections.length) {
  const info = await outlineApi(admin, 'workhub.projectInfo', {collectionId: collections[0].id});
  check(info.permissions.updateManager === true && info.permissions.manage === true, 'new_project_permission_contract');
  check(info.workhubUrl === settings.urls.portal, 'local_portal_link_preserved');
}

const worker = new Session();
await worker.login(settings.urls.outline + '/auth/oidc', credentials.groupA);
check((await outlineApi(worker, 'workhub.capabilities')).enabled, 'employee_outline_sso_ready');
const workerCollections = await outlineApi(worker, 'collections.list', {limit: 100});
let readableProjects = 0;
let restrictedCollections = 0;
let eligibleTaskContext = false;
for (const collection of workerCollections) {
  let info;
  try {
    info = await outlineApi(worker, 'workhub.projectInfo', {collectionId: collection.id});
  } catch (error) {
    // The existing Workhub ACL may be narrower than Outline's collection list.
    // A denied collection must remain denied; never relax its grants for a smoke test.
    if (error.status !== 403) throw error;
    restrictedCollections++;
    continue;
  }
  readableProjects++;
  check(info.permissions.updateManager === false, 'employee_manager_assignment_restricted');
  if (info.linked) {
    const docs = await outlineApi(worker, 'documents.list', {collectionId: collection.id, limit: 100});
    const parent = docs.find((doc) => doc.title === '업무 목록' && !doc.parentDocumentId);
    if (!parent) continue;
    const context = await outlineApi(worker, 'workhub.taskCreateInfo', {
      collectionId: collection.id, parentDocumentId: parent.id,
    });
    if (context.eligible) {
      check(context.people.length > 0 && context.viewer.admin === false, 'employee_task_creation_context_ready');
      eligibleTaskContext = true;
      break;
    }
  }
}
check(readableProjects > 0, 'employee_project_info_ready');
check(eligibleTaskContext, 'employee_writable_task_list_available');
const portal = new Session();
const me = await portal.portal();
check(Boolean(me.email), 'portal_sso_ready');
check(Array.isArray((await portal.api('/api/projects')).projects), 'portal_projects_ready');
check((await fetch(settings.urls.outline + '/_health')).ok, 'outline_health');
check((await fetch(settings.urls.portal + '/health')).ok, 'workhub_health');
for (const prefix of ['outline-projects', 'outline-search', 'outline-analytics', 'outline-tasks', 'outline-kanban']) {
  const response = await fetch(settings.urls.portal + '/internal/' + prefix + '/info', {method: 'POST'});
  check(response.status === 404, 'internal_' + prefix + '_not_public');
}
const result = {at: new Date().toISOString(), checks, originalDocuments: Object.keys(before).length,
  currentDocuments: Object.keys(documents).length, restrictedCollections};
fs.writeFileSync(path.join(output, 'smoke.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
