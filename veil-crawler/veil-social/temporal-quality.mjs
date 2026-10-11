import { createHash } from 'node:crypto';
import { seoulHour } from './temporal.mjs';
const median=v=>{const s=[...v].sort((a,b)=>a-b);return s.length?(s[Math.floor((s.length-1)/2)]+s[Math.ceil((s.length-1)/2)])/2:null;};
const timestamp=p=>Date.parse(p.created_at ?? p.publishedAt);
const author=p=>p.anonymous_user_id ?? p.author_id ?? p.authorId ?? p.simulationActorId ?? p.handle ?? '';
/** 동일 계정의 간격과 전체 시간대를 검사합니다. 진위·악성 판단은 하지 않습니다. */
export function temporalQuality(posts) {
 const valid=posts.filter(p=>Number.isFinite(timestamp(p))),hours=Array(24).fill(0),accounts=new Map();
 for(const p of valid){const t=timestamp(p);hours[seoulHour(t)]++;const id=author(p);if(id){const a=accounts.get(id)||[];a.push(t);accounts.set(id,a);}}
 const gaps=[],accountIntervals=[],bursts=[];
 for(const [id,times] of accounts){times.sort((a,b)=>a-b);const intervals=times.slice(1).map((t,i)=>(t-times[i])/60000);gaps.push(...intervals);
  if(intervals.length){const mean=intervals.reduce((a,b)=>a+b,0)/intervals.length;const variance=intervals.reduce((a,b)=>a+(b-mean)**2,0)/intervals.length;
   accountIntervals.push({account:id,post_count:times.length,median_interval_min:median(intervals),interval_cv:mean?Math.sqrt(variance)/mean:0});}}
 const times=valid.map(timestamp).sort((a,b)=>a-b);
 for(let i=0;i<times.length;){let j=i+1;while(j<times.length&&times[j]-times[i]<=300000)j++;if(j-i>=3){bursts.push({start:new Date(times[i]).toISOString(),posts:j-i});i=j;}else i++;}
 return {posts:posts.length,valid_timestamps:valid.length,missing_or_invalid:posts.length-valid.length,timezone:'Asia/Seoul',hour_counts:hours,
  time_bands:[[0,6],[6,9],[9,12],[12,15],[15,18],[18,21],[21,24]].map(([a,b])=>({band:String(a).padStart(2,'0')+'-'+String(b).padStart(2,'0'),posts:hours.slice(a,b).reduce((x,y)=>x+y,0)})),
  peak_hour:hours.some(Boolean)?hours.indexOf(Math.max(...hours)):null,median_posting_interval_min:median(gaps),interval_definition:'동일 계정의 연속 작성 시각 간격',burst_events:bursts.length,
  burst_definition:'전체 피드에서 5분 이내 3개 이상, 겹치지 않는 구간',bursts,duplicate_timestamps:times.length-new Set(times).size,account_intervals:accountIntervals,span_hours:times.length?(times.at(-1)-times[0])/3600000:0};
}
/** 사건 시작부터 duration까지 상대 12구간을 비교합니다. 시작 날짜만 변경해도 중복을 탐지합니다. */
export function compareScenarios(scenarios){
 const rows=scenarios.map(({id,pattern,event_at,duration_hours,secondary_event_at=null,seed=null,posts})=>{
  const histogram=Array(12).fill(0),start=Date.parse(event_at),duration=duration_hours*3600000;
  for(const p of posts){const t=timestamp(p);if(Number.isFinite(t))histogram[Math.max(0,Math.min(11,Math.floor((t-start)/duration*12)))]++;}
  const q=temporalQuality(posts);
  return {scenario_id:id,pattern,event_at,duration_hours,secondary_event_at,seed,actual_span_hours:q.span_hours,peak_hour:q.peak_hour,peak_relative_bin:histogram.indexOf(Math.max(...histogram)),relative_histogram:histogram,
   signature:createHash('sha256').update(JSON.stringify(histogram)).digest('hex'),burst_events:q.burst_events,median_posting_interval_min:q.median_posting_interval_min,duplicate_timestamps:q.duplicate_timestamps};});
 const counts=new Map();for(const r of rows)counts.set(r.signature,(counts.get(r.signature)||0)+1);
 return {scenarios:rows,identical_distribution_excess:rows.length-counts.size,scenarios_in_duplicate_groups:rows.filter(r=>counts.get(r.signature)>1).length,comparison_definition:'상대 시간 12구간 개수 벡터 완전 일치'};
}
/** 역할별 시간대 겹침을 탐색하는 지표이며 label leakage 제거의 증명은 아닙니다. */
export function roleOverlap(posts){const groups={malicious_actor:Array(24).fill(0),observer:Array(24).fill(0)};
 for(const p of posts)if(groups[p.simulation_role]&&Number.isFinite(timestamp(p)))groups[p.simulation_role][seoulHour(timestamp(p))]++;
 const prob=a=>{const sum=a.reduce((x,y)=>x+y,0);return a.map(n=>sum?n/sum:0);};const a=prob(groups.malicious_actor),b=prob(groups.observer);
 const edges=[1,5,15,60,240,Infinity],intervalGroups={malicious_actor:Array(6).fill(0),observer:Array(6).fill(0)};
 for(const role of Object.keys(intervalGroups))for(const account of temporalQuality(posts.filter(p=>p.simulation_role===role)).account_intervals) {
   const bin=edges.findIndex(edge=>account.median_interval_min<edge);intervalGroups[role][bin]++;
 }
 const ia=prob(intervalGroups.malicious_actor),ib=prob(intervalGroups.observer);
 return {hourly_distribution_overlap:a.reduce((s,p,i)=>s+Math.min(p,b[i]),0),median_account_interval_overlap:ia.reduce((s,p,i)=>s+Math.min(p,ib[i]),0),median_account_interval_bins:edges.map(x=>Number.isFinite(x)?x:'Infinity'),median_account_interval_counts:intervalGroups,hour_counts:groups,note:'0=겹침 없음, 1=동일 분포. 유한 표본의 편향은 계속 점검해야 합니다.'};}
