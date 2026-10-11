import test from 'node:test';
import assert from 'node:assert/strict';
import { prepareStartup } from '../startup.mjs';

test('startup removes prior campaign, preserves real/manual posts, and returns idle state', () => {
  const real={id:'x-1',source:{platform:'x'},publishedAt:'2026-10-10T01:00:00Z'};
  const manual={id:'manual',publishedAt:'2026-10-10T02:00:00Z'};
  const priorCampaign={id:'campaign',simulationRunId:'old'};
  const input=[priorCampaign,real,manual];
  const result=prepareStartup(input,[real],()=>0);
  assert.deepEqual(new Set(result.posts.map(post=>post.id)),new Set(['x-1','manual']));
  assert.equal(result.state.status,'idle');
  assert.equal(result.state.rootId,null);
  assert.equal(result.state.quoteCount,0);
  assert.equal(input[0],priorCampaign);
});

test('random order keeps every post exactly once and differs from the previous run', () => {
  const archived=Array.from({length:8},(_,i)=>({id:'x-'+i,source:{platform:'x'},publishedAt:'2026-10-10T01:00:00Z'}));
  const first=prepareStartup(archived,archived,()=>0);
  const second=prepareStartup(first.posts,archived,(_min,max)=>max-1);
  assert.equal(new Set(first.posts.map(post=>post.id)).size,8);
  assert.notDeepEqual(first.posts.map(post=>post.id),second.posts.map(post=>post.id));
  assert.deepEqual(new Set(second.posts.map(post=>post.id)),new Set(archived.map(post=>post.id)));
});
