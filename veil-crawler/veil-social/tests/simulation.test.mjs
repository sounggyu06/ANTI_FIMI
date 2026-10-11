import test from 'node:test';
import assert from 'node:assert/strict';
import { beginSimulation, advanceSimulation, advanceFastSimulation, clearSimulation, FAST_WAVE_INTERVAL_MS } from '../simulation.mjs';

test('60 distinct quote posts preserve origins, timing, opinions and exact repost counts', () => {
  const existing = { id: 'existing', text: '일상 게시물', likes: 10 };
  const start = new Date('2026-10-10T04:00:00Z');
  let result = beginSimulation([existing], start);
  const rootId = result.state.rootId;
  assert.equal(result.posts.length, 2);
  assert.equal(result.state.scenarioCount, 0);
  let lastLikes = result.state.rootLikes;
  for (let wave = 1; wave <= 15; wave++) {
    result = advanceSimulation(result.posts, result.state, new Date(start.getTime() + wave * 4000));
    assert.ok(result.state.rootLikes > lastLikes);
    assert.equal(result.posts.find(p => p.id === rootId).reposts, wave * 4);
    lastLikes = result.state.rootLikes;
  }
  const quotes = result.posts.filter(p => p.repostOf === rootId);
  assert.equal(quotes.length, 60);
  assert.equal(new Set(quotes.map(p => p.id)).size, 60);
  assert.ok(new Set(quotes.map(p => p.handle)).size < 60);
  assert.ok(new Set(quotes.map(p => p.handle)).size >= 12);
  assert.equal(new Set(quotes.map(p => p.text)).size, 60);
  assert.deepEqual(new Set(quotes.map(p => p.language)), new Set(['ko', 'en', 'ja']));
  assert.ok(quotes.some(p => p.text.includes('예정대로')));
  assert.ok(quotes.every(p => !p.text.includes('[풍자]')));
  assert.ok(quotes.some(p => p.text.includes('소문이 먼저 출동')));
  assert.ok(quotes.some(p => p.text.includes('확인 중')));
  assert.ok(quotes.some(p => p.text.includes('삭제되기 전')));
  assert.equal(result.state.status, 'completed');
  assert.equal(result.state.rootLikes, 27003);
  assert.equal(result.state.scenarioCount, 12);
  assert.equal(result.posts.filter(post => post.simulationRunId && post.id !== rootId && !post.repostOf).length, 12);
  assert.deepEqual(advanceSimulation(result.posts, result.state), result);
  assert.deepEqual(clearSimulation(result.posts).posts, [existing]);
});

test('stopping freezes generation and reset preserves manually created posts', () => {
  let result = beginSimulation([]);
  result = advanceSimulation(result.posts, result.state);
  const stopped = { ...result.state, status: 'stopped' };
  assert.deepEqual(advanceSimulation(result.posts, stopped).posts, result.posts);
  const manual = { id: 'manual', text: '직접 작성한 글' };
  const reset = clearSimulation([manual, ...result.posts]);
  assert.deepEqual(reset.posts, [manual]);
  assert.equal(reset.state.status, 'idle');
  assert.equal(reset.state.rootLikes, 0);
});

test('fast mode generates the complete campaign before 15 seconds even when timer ticks are delayed',()=>{
  const start=new Date('2026-10-10T04:00:00Z');
  const normal={id:'existing',text:'일상 게시물'};
  let result=beginSimulation([normal],start,'fast');
  assert.equal(result.state.mode,'fast');
  result=advanceFastSimulation(result.posts,result.state,new Date(start.getTime()+FAST_WAVE_INTERVAL_MS-1));
  assert.equal(result.state.wave,0);
  // 중간 콜백이 늦어져도 빠뜨린 단계를 현재 경과 시간까지 생성합니다.
  result=advanceFastSimulation(result.posts,result.state,new Date(start.getTime()+9000));
  assert.equal(result.state.wave,12);
  result=advanceFastSimulation(result.posts,result.state,new Date(start.getTime()+15*FAST_WAVE_INTERVAL_MS));
  assert.equal(result.state.status,'completed');
  assert.equal(result.state.quoteCount,60);
  assert.equal(result.state.scenarioCount,12);
  assert.equal(result.state.rootLikes,27003);
  assert.equal(result.posts.length,74);
  assert.equal(new Set(result.posts.map(p=>p.id)).size,74);
  assert.deepEqual(['campaign_a','campaign_b'].map(actor=>result.posts.filter(p=>p.simulationActorId===actor).length),[7,6]);
  assert.ok(Date.parse(result.state.endedAt)-start.getTime()<15000);
  const timestamps=result.posts.filter(p=>p.simulationRunId).map(p=>Date.parse(p.publishedAt));
  assert.ok(Math.max(...timestamps)-Math.min(...timestamps)>3600000);
  assert.equal(new Set(timestamps).size,73);
  assert.deepEqual(advanceFastSimulation(result.posts,result.state,new Date(start.getTime()+20000)),result);
  assert.deepEqual(clearSimulation(result.posts).posts,[normal]);
});

test('fast mode respects stopping and cannot accelerate a normal or reset campaign',()=>{
  const start=new Date('2026-10-10T04:00:00Z');
  const fast=beginSimulation([],start,'fast');
  const stopped={...fast.state,status:'stopped'};
  assert.deepEqual(advanceFastSimulation(fast.posts,stopped,new Date(start.getTime()+15000)),{posts:fast.posts,state:stopped});
  const normal=beginSimulation([],start);
  assert.deepEqual(advanceFastSimulation(normal.posts,normal.state,new Date(start.getTime()+15000)),normal);
  const reset=clearSimulation(fast.posts);
  assert.equal(reset.state.mode,'normal');
  assert.deepEqual(advanceFastSimulation(reset.posts,reset.state,new Date(start.getTime()+15000)),reset);
});
