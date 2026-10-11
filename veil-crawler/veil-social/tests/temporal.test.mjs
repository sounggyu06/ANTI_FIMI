import test from 'node:test';
import assert from 'node:assert/strict';
import { createTemporalPlan,TEMPORAL_PATTERNS,accountActivity } from '../temporal.mjs';
import { temporalQuality,compareScenarios,roleOverlap } from '../temporal-quality.mjs';
import { beginSimulation,advanceSimulation } from '../simulation.mjs';
const now=new Date('2026-10-10T18:00:00+09:00');
const entries=plan=>[plan.root,...plan.quotes,...plan.claims];
function campaign(pattern,seed){let r=beginSimulation([],now,'normal',{pattern,seed});for(let n=1;n<=15;n++)r=advanceSimulation(r.posts,r.state,new Date(now.getTime()+n*4000));return r;}

test('seed reproduces virtual timestamps regardless of screen playback mode; original timestamps stay unchanged',()=>{
 const options={pattern:'double_peak',seed:'reproducible'};
 const plan=createTemporalPlan({...options,now});assert.deepEqual(createTemporalPlan({...options,now}),plan);
 const original={id:'real',authorId:'original',publishedAt:'2026-10-10T14:00:00+09:00',source:{platform:'x'}};
 const slow=beginSimulation([original],now,'normal',options),fast=beginSimulation([original],now,'fast',options);
 assert.deepEqual(slow.state.temporalPlan,fast.state.temporalPlan);assert.deepEqual(slow.posts.at(-1),original);
 assert.equal(slow.posts[0].publishedAt,fast.posts[0].publishedAt);assert.equal(original.publishedAt,'2026-10-10T14:00:00+09:00');
});

test('every supported pattern has unique nonuniform, causal timestamps and different account activity',()=>{
 for(const pattern of TEMPORAL_PATTERNS){const plan=createTemporalPlan({pattern,seed:'quality-v1-'+pattern+'-1',now});
  const rows=entries(plan),times=rows.map(p=>Date.parse(p.created_at));assert.equal(rows.length,73);assert.equal(new Set(times).size,73);
  assert.ok(times.every(t=>t>=Date.parse(plan.root.created_at)&&t>Date.parse(plan.event_at)&&t<=Date.parse(plan.planned_end_at)&&t<now.getTime()));
  const sorted=[...times].sort((a,b)=>a-b),gaps=sorted.slice(1).map((t,i)=>t-sorted[i]);assert.ok(new Set(gaps).size>40);
  assert.ok(sorted.at(-1)-sorted[0]>3600000);assert.ok(rows.every(p=>p.created_at.endsWith('+09:00')));
  assert.ok(new Set(Object.values(plan.account_profiles).map(a=>JSON.stringify(a))).size>15);
  assert.ok(Object.values(plan.account_profiles).some(a=>a.late_participant));
  assert.ok(plan.quotes.some(p=>plan.quotes.filter(q=>q.actorId===p.actorId).length>=5));
 }
 assert.throws(()=>createTemporalPlan({pattern:'uniform',now}),/지원하지/);
});

test('account profile uses the same generation formula independent of role and persists by actor ID',()=>{
 const profile=accountActivity('actor_1');assert.deepEqual(accountActivity('actor_1'),profile);
 const plan=createTemporalPlan({seed:'account-test',now});
 assert.deepEqual(plan.account_profiles.campaign_a,accountActivity('campaign_a'));
 for(const activity of Object.values(plan.account_profiles)){assert.ok(activity.active_hours.length>=7);assert.ok(activity.posting_frequency>0);assert.ok(activity.burst_probability>0&&activity.burst_probability<1);assert.ok(activity.response_delay>0);assert.equal('simulation_role' in activity,false);}
});

test('12 scenarios differ in relative shape, start, peak and duration, with overlapping role hours',()=>{
 const scenarios=[],all=[];
 for(const pattern of TEMPORAL_PATTERNS)for(let i=1;i<=2;i++){
  const r=campaign(pattern,`quality-v1-${pattern}-${i}`),plan=r.state.temporalPlan;
  scenarios.push({id:pattern+'_'+i,pattern,event_at:plan.event_at,duration_hours:plan.duration_hours,posts:r.posts});all.push(...r.posts.map(p=>({...p,authorId:p.authorId+'_'+pattern+'_'+i})));
 }
 const report=compareScenarios(scenarios);
 assert.equal(report.scenarios_in_duplicate_groups,0);assert.equal(report.identical_distribution_excess,0);
 assert.equal(new Set(report.scenarios.map(s=>s.event_at)).size,12);assert.equal(new Set(report.scenarios.map(s=>s.duration_hours)).size,12);
 assert.ok(new Set(report.scenarios.map(s=>s.peak_hour)).size>=5);assert.ok(roleOverlap(all).hourly_distribution_overlap>0.7);
 assert.ok(roleOverlap(all).median_account_interval_overlap>0.7);
 assert.ok(report.scenarios.every(s=>s.duplicate_timestamps===0));assert.ok(report.scenarios.some(s=>s.burst_events>5));
 const doubles=report.scenarios.filter(s=>s.pattern==='double_peak');assert.ok(doubles.every(s=>s.relative_histogram.slice(0,6).some(n=>n>=5)&&s.relative_histogram.slice(6).some(n=>n>=5)));
 const rapid=report.scenarios.filter(s=>s.pattern==='rapid_spike');const delayed=report.scenarios.filter(s=>s.pattern==='delayed_spike');
 assert.ok(rapid.every(s=>s.peak_relative_bin<4));assert.ok(delayed.every(s=>s.peak_relative_bin>=6));
});

test('quality report handles timezone, missing values, account intervals, bursts and normalized duplicate shapes',()=>{
 const times=['2026-10-10T00:00:00+09:00','2026-10-10T00:01:00+09:00','2026-10-10T00:03:00+09:00','2026-10-10T18:00:00+09:00'];
 const posts=times.map(created_at=>({author_id:'anon_1',created_at}));posts.push({author_id:'anon_1',created_at:null});
 const report=temporalQuality(posts);assert.equal(report.missing_or_invalid,1);assert.equal(report.time_bands[0].posts,3);assert.equal(report.peak_hour,0);assert.equal(report.median_posting_interval_min,2);assert.equal(report.burst_events,1);
 const scenarios=[0,1].map(i=>({id:String(i),pattern:'old',event_at:`2026-10-${10+i}T00:00:00+09:00`,duration_hours:24,posts:posts.slice(0,4).map(p=>({...p,created_at:new Date(Date.parse(p.created_at)+i*86400000).toISOString()}))}));
 assert.equal(compareScenarios(scenarios).scenarios_in_duplicate_groups,2);
});
