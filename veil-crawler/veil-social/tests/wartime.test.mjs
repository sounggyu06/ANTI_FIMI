import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {beginSimulation,advanceSimulation,advanceFastSimulation,clearSimulation} from '../simulation.mjs';
import {WARTIME_TOPICS,wartimeAnswerKey,wartimeLikeCount} from '../wartime.mjs';
import {Anonymizer} from '../anonymizer.mjs';
import {renderPostsHtml} from '../posts-html.mjs';

const start=new Date('2026-10-11T03:00:00Z');
const existing={id:'keep',authorId:'normal',handle:'normal',text:'기존 글',publishedAt:'2026-10-10T03:00:00Z'};
const begin=mode=>beginSimulation([existing],start,mode,{scenarioKey:'wartime',seed:'exercise-v1',pattern:'double_peak'});
const tick=result=>advanceSimulation(result.posts,result.state,new Date(result.state.nextPostAt));
const finish=result=>{while(result.state.status==='running')result=tick(result);return result;};

test('uploads use the actual clock, wait for their random interval, and never catch up in a burst',()=>{
  let result=begin('fast');
  assert.equal(result.state.mode,'realtime');
  assert.equal(result.posts[0].publishedAt,start.toISOString());
  assert.ok(result.state.waveIntervalMs>=100&&result.state.waveIntervalMs<=400);
  const due=Date.parse(result.state.nextPostAt);
  assert.deepEqual(advanceSimulation(result.posts,result.state,new Date(due-1)),result);
  const delayed=new Date(due+120000);
  result=advanceFastSimulation(result.posts,result.state,delayed);
  assert.equal(result.state.generatedCount,2);
  assert.equal(result.posts[0].publishedAt,delayed.toISOString());
  assert.ok(Date.parse(result.state.nextPostAt)-delayed.getTime()>=100);
  assert.ok(Date.parse(result.state.nextPostAt)-delayed.getTime()<=400);
  assert.deepEqual(advanceFastSimulation(result.posts,result.state,delayed),result);
});

test('real-time wartime completes exactly 1500 claims plus 300 controls and preserves existing records',()=>{
  let result=begin('fast');
  result=finish(result);
  assert.equal(result.state.status,'completed');
  assert.equal(result.state.generatedCount,1801);
  assert.equal(result.posts.length,1802);
  assert.equal(result.state.wave,1800);
  assert.deepEqual(result.posts.find(p=>p.id==='keep'),existing);
  const fixtures=result.posts.filter(p=>p.simulationRunId);
  assert.equal(new Set(fixtures.map(p=>p.id)).size,1801);
  assert.equal(new Set(fixtures.filter(p=>p.topic_id).map(p=>p.topic_id)).size,10);
  assert.ok(fixtures.every(p=>!/(가상 전시 훈련|Fictional wartime exercise|자료\s*\d+|Record\s*\d+|\.example|훈련 기준|exercise record)/i.test(p.text)));
  assert.deepEqual(result.state.kindCounts,{overview:1,claim:1500,question:100,refutation:100,official:100});
  const claims=fixtures.filter(p=>p.evaluation_kind==='claim');
  const counts=new Map();for(const p of claims)counts.set(p.authorId,(counts.get(p.authorId)||0)+1);
  assert.equal(counts.size,60);
  assert.ok([...counts.values()].some(n=>n===1));
  assert.ok(new Set(counts.values()).size>10);
  assert.ok(Math.max(...counts.values())>30);
  assert.ok(new Set(claims.map(p=>p.text)).size>250);
  const long=claims.filter(p=>p.text.split('\n').filter(line=>line.trim()).length>=4);
  assert.ok(long.length>=450&&long.length<=750);
  assert.ok(claims.some(p=>p.text.split('\n').filter(line=>line.trim()).length<4));
  for(const topic of WARTIME_TOPICS)assert.ok(long.some(p=>p.topic_id===topic.id));
  assert.ok(claims.some(p=>p.post_format==='rumor'));
  assert.ok(claims.some(p=>p.post_format==='personal'));
  for(const topic of WARTIME_TOPICS)assert.ok(fixtures.some(p=>p.topic_id===topic.id&&p.evaluation_kind==='claim'));
  const overview=fixtures.find(p=>p.evaluation_kind==='overview').text;
  for(const country of ['중앙아시아연합국','북공화국','남공화국','남태평양국'])assert.ok(overview.includes(country));
  assert.ok(!JSON.stringify(wartimeAnswerKey()).match(/섬국|북유라시아국/));
  const times=fixtures.map(p=>Date.parse(p.publishedAt));
  assert.equal(new Set(times).size,1801);
  assert.equal(Math.min(...times),start.getTime());
  assert.equal(Math.max(...times),Date.parse(result.state.endedAt));
  const sorted=[...times].sort((a,b)=>a-b);
  for(let i=1;i<sorted.length;i++)assert.ok(sorted[i]-sorted[i-1]>=100&&sorted[i]-sorted[i-1]<=400);
  const byId=new Map(result.posts.map(p=>[p.id,p]));
  for(const p of fixtures)if(p.repostOf)assert.ok(Date.parse(p.publishedAt)>=Date.parse(byId.get(p.repostOf).publishedAt));
  for(const p of fixtures)assert.equal(p.reposts,fixtures.filter(q=>q.repostOf===p.id).length);
  assert.ok(fixtures.some(p=>p.repostOf&&byId.get(p.repostOf).post_format==='rumor'));
  assert.ok(fixtures.some(p=>p.repostOf&&byId.get(p.repostOf).evaluation_kind==='question'));
  assert.ok(fixtures.some(p=>p.repostOf&&byId.get(p.repostOf).repostOf));
  assert.deepEqual(clearSimulation(result.posts).posts,[existing]);
});

test('continuous mode stops when asked and finishes the 1500 claim target without changing real data',()=>{
  let result=begin('continuous');
  result=tick(result);
  assert.equal(result.state.generatedCount,2);
  const stopped={...result.state,status:'stopped'};
  assert.deepEqual(advanceSimulation(result.posts,stopped),{posts:result.posts,state:stopped});
  assert.deepEqual(advanceFastSimulation(result.posts,stopped,new Date(start.getTime()+15000)),{posts:result.posts,state:stopped});
  result=finish(result);
  assert.equal(result.state.generatedCount,1801);
  assert.equal(result.state.scenarioCount,1500);
  assert.equal(result.posts.length,1802);
  assert.equal(result.state.wave,1800);
  assert.deepEqual(advanceSimulation(result.posts,result.state),result);
  assert.deepEqual(clearSimulation(result.posts).posts,[existing]);
});

test('synthetic likes grow, include popular and quiet posts, and preserve non-simulation metrics',()=>{
  const real={...existing,likes:57};
  let result=beginSimulation([real],start,'normal',{scenarioKey:'wartime',seed:'likes-fixture',pattern:'double_peak'});
  for(let i=0;i<50;i++)result=tick(result);
  const earlier=new Map(result.posts.filter(p=>p.simulationRunId).map(p=>[p.id,p.likes]));
  for(let i=0;i<50;i++)result=tick(result);
  assert.ok(result.posts.every(p=>!earlier.has(p.id)||p.likes>=earlier.get(p.id)));
  assert.ok(result.posts.some(p=>earlier.has(p.id)&&p.likes>earlier.get(p.id)));
  result=finish(result);
  const fixtures=result.posts.filter(p=>p.simulationRunId);
  assert.ok(fixtures.every(p=>Number.isSafeInteger(p.likes)&&p.likes>=0&&p.likes<50000));
  assert.ok(fixtures.filter(p=>p.likes>=5000).length>100);
  assert.ok(fixtures.some(p=>p.likes===0));
  assert.ok(fixtures.some(p=>p.likes>0&&p.likes<100));
  assert.ok(fixtures.some(p=>p.post_format==='rumor'&&p.likes>=5000));
  assert.ok(fixtures.some(p=>p.evaluation_kind==='refutation'&&p.likes>=5000));
  assert.ok(fixtures.every(p=>p.likes===wartimeLikeCount(p)));
  assert.equal(result.state.rootLikes,result.posts.find(p=>p.id===result.state.rootId).likes);
  assert.deepEqual(result.posts.find(p=>p.id===real.id),real);
  assert.deepEqual(advanceSimulation(result.posts,result.state),result);
});

test('public feed, profiles and crawler HTML omit the private answer key and retain repeat author histories',()=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'veil-wartime-'));
  try{
    const a=new Anonymizer(path.join(directory,'users.json'));
    let result=begin('fast');
    result=finish(result);
    const publicPosts=a.project(result.posts);
    const exposed=JSON.stringify(publicPosts)+renderPostsHtml(publicPosts);
    for(const key of ['evaluation_kind','evaluation_claim_status','simulation_role','topic_id','scenario_key','kindCounts','post_format','text_variant','timingSeed','contentPlan'])assert.ok(!exposed.includes(key));
    assert.ok(publicPosts.every(p=>p.authorId===p.anonymous_user_id));
    const actor=result.posts.find(p=>p.topic_id).simulationActorId;
    const raw=result.posts.filter(p=>p.simulationActorId===actor);
    assert.ok(raw.length>1);
    const ids=new Set(a.project(raw).map(p=>p.authorId));
    assert.equal(ids.size,1);
    const id=[...ids][0];
    assert.equal(a.profile(id,publicPosts).post_count,raw.length);
    assert.equal(new Anonymizer(path.join(directory,'users.json')).project(raw)[0].authorId,id);
    assert.equal(wartimeAnswerKey().topics.length,10);
  } finally{fs.rmSync(directory,{recursive:true,force:true});}
});
