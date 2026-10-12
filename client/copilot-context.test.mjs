import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  buildContext, changedFields, editorContext, mergeSnapshots, openObjects, parseRoute, publishView, rebaseDraft, requestRefresh, settleSave, shouldCloseAfterSave,
  CONTEXT_REQUEST, REFRESH_EVENT,
} from './src/copilot-context.js';

const SHIPMENT = { shipment: { id: 's_1', label: 'Headphones', carrier: 'correos', tracking_number: 'PQ123', status: 'in_transit', pickup_code: '9999', merchant: 'Shop' }, events: [] };
const TRIP = { trip: { id: 't_1', title: 'Lisbon', status: 'upcoming', currency: 'EUR' }, segments: [{ id: 'g_1', kind: 'flight', label: 'MAD-LIS', status: 'confirmed' }] };

function fakeCall(known = {}) {
  return async (name, args) => {
    const key = `${name}:${args.shipment || args.trip}`;
    if (!(key in known)) throw Object.assign(new Error('not found'), { code: 'not_found' });
    return known[key];
  };
}

test('only the fields the user changed are sent', () => {
  assert.deepEqual(changedFields({ label: 'A', notes: 'x' }, { label: 'A', notes: 'y' }), { notes: 'y' });
  assert.deepEqual(changedFields({ notes: 'x' }, { notes: '' }), { notes: '' });
});

test('a refresh brings the assistant edit into untouched fields and keeps what the user typed', () => {
  const base = { label: 'Old', notes: 'n', merchant: 'Shop' };
  const draft = { ...base, notes: 'typed by hand' };
  const server = { label: 'Assistant title', notes: 'n', merchant: 'Shop' };
  const out = rebaseDraft(base, draft, server);
  assert.deepEqual(out.draft, { label: 'Assistant title', notes: 'typed by hand', merchant: 'Shop' });
  // what is sent on save is only the user's field; the assistant title is not put back
  assert.deepEqual(changedFields(out.base, out.draft), { notes: 'typed by hand' });
});

test('after a save the server value settles the field; unchanged inputs keep their identity', () => {
  const base = { notes: 'n' };
  const draft = { notes: 'typed' };
  const saved = rebaseDraft(base, draft, { notes: 'typed' });
  assert.deepEqual(changedFields(saved.base, saved.draft), {});
  const same = rebaseDraft(base, base, base);
  assert.equal(same.base, base);
  assert.equal(same.draft, base);
});

test('routes, including ids with spaces and creation views', () => {
  assert.deepEqual({ ...parseRoute('#/envio/s_1') , query: undefined }, { page: 'envio', param: 's_1', query: undefined });
  assert.equal(parseRoute('#/viaje/Escapada%20Lisboa?tab=gastos').param, 'Escapada Lisboa');
  assert.equal(parseRoute('').page, '');
});

test('open shipment and trip are read through the app tools with their real ids, never the pickup code', async () => {
  const call = fakeCall({ 's_1': undefined, 'shipment_get:s_1': SHIPMENT, 'trip_get:t_1': TRIP });
  const [ship] = await openObjects(parseRoute('#/envio/s_1'), call);
  assert.equal(ship.kind, 'shipment');
  assert.equal(ship.object_id, 's_1');
  assert.equal(ship.title, 'Headphones');
  assert.equal(JSON.stringify(ship).includes('9999'), false);
  const [trip] = await openObjects(parseRoute('#/viaje/t_1'), call);
  assert.deepEqual([trip.kind, trip.object_id, trip.title], ['trip', 't_1', 'Lisbon']);
  assert.deepEqual(trip.segments, [{ object_id: 'g_1', kind: 'flight', title: 'MAD-LIS', status: 'confirmed' }]);
});

test('new, unknown or failing ids give no object and do not throw', async () => {
  const call = fakeCall({});
  assert.deepEqual(await openObjects(parseRoute('#/envio/new'), call), []);
  assert.deepEqual(await openObjects(parseRoute('#/envio/s_zzz'), call), []);
  assert.deepEqual(await openObjects(parseRoute('#/viaje/t_zzz'), call), []);
  assert.deepEqual(await openObjects(parseRoute('#/viaje'), call), []);
  assert.deepEqual(await openObjects(parseRoute('#/correo'), call), []);
});

test('editors answer through the context request, several as a list', () => {
  const target = new EventTarget();
  assert.equal(editorContext(target), undefined);
  const answer = (value) => target.addEventListener(CONTEXT_REQUEST, (e) => e.detail.provide(value));
  answer({ form: 'a' });
  assert.deepEqual(editorContext(target), { form: 'a' });
  answer({ form: 'b' });
  assert.deepEqual(editorContext(target), { forms: [{ form: 'a' }, { form: 'b' }] });
  assert.equal(mergeSnapshots([null, undefined]), undefined);
});

test('the context carries the open object, the page, the tab and the unsaved fields', async () => {
  const call = fakeCall({ 'trip_get:t_1': TRIP });
  publishView({ tab: 'expenses' }, '#/viaje/t_1');
  const editor = { form: 'expense', mode: 'edit', kind: 'expense', object_id: 'x_1', title: 'Taxi', fields: { amount: '12' }, changed: { amount: '12' } };
  const ctx = await buildContext({ hash: '#/viaje/t_1', call, editor, extras: { tab: 'expenses' } });
  assert.equal(ctx.view.page, 'viaje');
  assert.equal(ctx.view.object_id, 't_1');
  assert.equal(ctx.view.tab, 'expenses');
  assert.deepEqual(ctx.view.editor, editor);
  assert.deepEqual(ctx.active_objects.map((o) => [o.kind, o.object_id]), [['trip', 't_1'], ['expense', 'x_1']]);
  console.log(JSON.stringify(ctx));
  const creation = await buildContext({ hash: '#/', call: fakeCall({}), editor: { form: 'shipment_new', mode: 'new', fields: { tracking_number: 'ZZ1' } } });
  assert.deepEqual(creation.active_objects, []);
  assert.equal(creation.view.page, 'envios');
  assert.equal(creation.view.editor.fields.tracking_number, 'ZZ1');
});

test('typing during a pending save keeps the later draft and does not close', () => {
  const base = { title: 'Lisbon' };
  const sent = changedFields(base, { title: 'Submitted title A' }); // snapshot taken when Save was pressed
  // nothing typed since: the saved values settle the form and it may close
  const quiet = settleSave(base, sent, { title: 'Submitted title A' });
  assert.equal(quiet.close, true);
  // the user kept typing while the POST was pending: stay open, the later draft is pending on top of the saved title
  const typed = { title: 'Later title B' };
  const out = settleSave(base, sent, typed);
  assert.equal(out.close, false);
  assert.deepEqual(out.base, { title: 'Submitted title A' });
  assert.deepEqual(changedFields(out.base, typed), { title: 'Later title B' });
  // a field the user touched after the snapshot also keeps the form open
  assert.equal(settleSave({ a: '1', b: '2' }, { a: 'x' }, { a: 'x', b: 'changed later' }).close, false);
  // an untouched save (nothing changed, e.g. the auto title button) closes
  assert.equal(settleSave(base, {}, base).close, true);
  assert.equal(shouldCloseAfterSave({ title: 'A' }, { title: 'B' }), false);
  assert.equal(shouldCloseAfterSave({ title: 'A' }, { title: 'A' }), true);
});

test('every save-then-close modal asks the draft before closing', async () => {
  const { readFile } = await import('node:fs/promises');
  const read = (p) => readFile(new URL(p, import.meta.url), 'utf8');
  const viaje = await read('./src/pages/Viaje.jsx');
  const rename = viaje.slice(viaje.indexOf('function RenameModal'), viaje.indexOf('function MergeModal'));
  const expense = viaje.slice(viaje.indexOf('function ExpenseModal'), viaje.indexOf('const toggle = (id)'));
  const segment = await read('./src/components/travel.jsx');
  const detalle = await read('./src/pages/Detalle.jsx');
  for (const src of [rename, expense, segment, detalle]) assert.match(src, /\.saved\(sent\)/);
  assert.equal(/await onSaved\(\);\s*onClose\(\);/.test(rename + expense + segment), false);
});

test('an editor snapshot of a deleted object names no active object but keeps its fields in view', async () => {
  const editor = { form: 'shipment_edit', mode: 'edit', kind: 'shipment', object_id: 's_gone', title: 'Gone', fields: { notes: 'typed' }, changed: { notes: 'typed' } };
  const call = fakeCall({}); // shipment_get / trip_get answer not found
  const ctx = await buildContext({ hash: '#/envio/s_gone', call, editor });
  assert.deepEqual(ctx.active_objects, []);
  assert.deepEqual(ctx.view.editor, editor);
  // still there: the snapshot identity is confirmed by the native lookup
  const alive = await buildContext({ hash: '#/envios', call: fakeCall({ 'shipment_get:s_1': SHIPMENT }), editor: { ...editor, object_id: 's_1' } });
  assert.deepEqual(alive.active_objects.map((o) => [o.kind, o.object_id]), [['shipment', 's_1']]);
  // an expense or segment of a trip that no longer exists is not claimed either
  const orphan = { form: 'segment', mode: 'edit', kind: 'segment', object_id: 'g_1', trip_id: 't_gone', fields: {} };
  assert.deepEqual((await buildContext({ hash: '#/', call, editor: orphan })).active_objects, []);
  const stale = await buildContext({ hash: '#/', call: fakeCall({ 'trip_get:t_1': TRIP }), editor: { ...orphan, object_id: 'g_zzz', trip_id: 't_1' } });
  assert.deepEqual(stale.active_objects, []);
});

test('turn end refreshes once even if both the event and onTurnEnd arrive', () => {
  const target = new EventTarget();
  let hits = 0;
  target.addEventListener(REFRESH_EVENT, () => { hits += 1; });
  let clock = 1_000_000;
  assert.equal(requestRefresh(() => clock, target), true);
  assert.equal(requestRefresh(() => clock + 50, target), false);
  assert.equal(requestRefresh(() => clock + 500, target), true);
  assert.equal(hits, 2);
});
