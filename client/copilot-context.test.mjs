import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  buildContext, changedFields, editorContext, mergeSnapshots, openObjects, parseRoute, publishView, rebaseDraft, requestRefresh,
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
