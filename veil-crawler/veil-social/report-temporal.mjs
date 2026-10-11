// 로컬 검사만 수행합니다. 원본 JSONL을 수정하거나 사용자 식별 정보를 보고서에 출력하지 않습니다.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { beginSimulation,advanceSimulation } from './simulation.mjs';
import { TEMPORAL_PATTERNS } from './temporal.mjs';
import { temporalQuality,compareScenarios,roleOverlap } from './temporal-quality.mjs';
const root=path.dirname(fileURLToPath(import.meta.url)),output=path.resolve(root,'../reports');
const now=new Date('2026-10-10T18:00:00+09:00'),benchmark=[],synthetic=[];
for(const pattern of TEMPORAL_PATTERNS)for(let repeat=1;repeat<=2;repeat++){
 let r=beginSimulation([],now,'normal',{pattern,seed:`quality-v1-${pattern}-${repeat}`});
 for(let wave=1;wave<=15;wave++)r=advanceSimulation(r.posts,r.state,new Date(now.getTime()+wave*4000));
 const plan=r.state.temporalPlan,id=`${pattern}_${repeat}`,posts=r.posts.map(p=>({...p,authorId:p.authorId+'_'+id,scenario_id:id}));
 benchmark.push({id,pattern,event_at:plan.event_at,duration_hours:plan.duration_hours,secondary_event_at:plan.secondary_event_at,seed:plan.seed,posts});synthetic.push(...posts);
}
// 이전 4초 고정 방식 재현: 1개 원문 + 60개 인용(250ms offset) + 12개 후속 글.
const before=benchmark.map((scenario,i)=>{const start=now.getTime()-i*86400000,posts=[{created_at:new Date(start).toISOString()}];
 for(let wave=1;wave<=15;wave++){for(let offset=0;offset<4;offset++)posts.push({created_at:new Date(start+wave*4000+offset*250).toISOString()});if(wave<=12)posts.push({created_at:new Date(start+wave*4000).toISOString()});}
 return {id:scenario.id,pattern:'legacy_fixed_4s',event_at:new Date(start).toISOString(),duration_hours:61/3600,posts};});
const accountIds=new Map();
const privateId=value=>{const key=String(value);if(!accountIds.has(key))accountIds.set(key,'report_'+String(accountIds.size+1).padStart(4,'0'));return accountIds.get(key);};
const byId=new Map();
for(const file of (await fs.readdir(path.join(root,'data/imported-x'))).filter(f=>f.endsWith('.jsonl')).sort())for(const line of (await fs.readFile(path.join(root,'data/imported-x',file),'utf8')).split(/\r?\n/)){
 if(!line.trim())continue;const raw=JSON.parse(line),id=raw.post_id??raw.id??JSON.stringify(raw);if(byId.has(id))continue;
 byId.set(id,{created_at:raw.created_at,author_id:privateId(raw.author_id??raw.user_id??raw.account_id??raw.username??raw.handle??'')});}
const real=[...byId.values()];let current=null;
const argument=process.argv.indexOf('--runtime-dir');
if(argument>=0){const dir=path.resolve(process.argv[argument+1]),posts=JSON.parse(await fs.readFile(path.join(dir,'posts.json'),'utf8'));
 const clean=posts.map(p=>({...p,authorId:privateId(p.authorId??p.handle??'')}));
 current={description:'현재 서버에 저장된 실제·가상 게시물',quality:temporalQuality(clean),synthetic:temporalQuality(clean.filter(p=>p.simulationRunId)),real:temporalQuality(clean.filter(p=>p.source?.platform==='x'))};}
const baseline=compareScenarios(before),comparison=compareScenarios(benchmark);
const report={generated_at:new Date().toISOString(),seed_version:'quality-v1',benchmark_now:now.toISOString(),scope:'기존 입력 중복 제거 + 6패턴 × 2회 고정 seed 검사. 현재 데이터는 별도 구분.',
 real_data:{posts:real.length,created_at_policy:'원본 문자열 유지; 검사 시에만 파싱',quality:temporalQuality(real)},benchmark_dataset:temporalQuality([...real,...synthetic]),synthetic_benchmark:temporalQuality(synthetic),before:baseline,after:comparison,role_overlap:roleOverlap(synthetic),current_dataset:current,
 limitations:['실제 SNS 전체의 실측 분포에 보정한 통계 모델은 아닙니다.','한 번의 seed 검사나 시간 분포 겹침만으로 모든 label leakage가 제거됐다고 증명할 수 없습니다.','샘플링 특성상 두 peak가 모든 실행에서 똑같이 뚜렷하지 않을 수 있습니다.']};
await fs.mkdir(output,{recursive:true});await fs.writeFile(path.join(output,'temporal-quality.json'),JSON.stringify(report,null,2)+'\n');
const q=current?.quality??report.benchmark_dataset;
const lines=['# Temporal Quality Report','','시간대: Asia/Seoul (UTC+09:00)',current?'대상: 현재 서버 데이터':`대상: 실제 ${real.length}개 + 고정 seed 12개 시나리오 검증 데이터`,'',...q.time_bands.map(r=>`${r.band} : ${r.posts} posts`),'',`Peak hour: ${String(q.peak_hour).padStart(2,'0')}:00`,`Median posting interval: ${q.median_posting_interval_min?.toFixed(2)??'N/A'} min (동일 계정 기준)`,`Burst events: ${q.burst_events} (5분 이내 3개 이상)`,`Duplicate timestamps: ${q.duplicate_timestamps}`,`Missing/invalid timestamps: ${q.missing_or_invalid}`,'',...(current?[`현재 synthetic: ${current.synthetic.posts} posts · ${current.synthetic.span_hours.toFixed(2)} h · 중복 시각 ${current.synthetic.duplicate_timestamps}개`, `현재 synthetic 중앙 게시 간격: ${current.synthetic.median_posting_interval_min?.toFixed(2)??'N/A'} min`, '']:[]),'## 12개 시나리오 비교','',`이전 방식: 동일 분포 그룹에 속한 시나리오 ${baseline.scenarios_in_duplicate_groups}/12`,`수정 방식: 동일 분포 그룹에 속한 시나리오 ${comparison.scenarios_in_duplicate_groups}/12`,`역할별 시간대 분포 겹침: ${(report.role_overlap.hourly_distribution_overlap*100).toFixed(1)}%`, `역할별 계정 중앙 게시 간격 분포 겹침: ${(report.role_overlap.median_account_interval_overlap*100).toFixed(1)}%`,'','| 시나리오 | 시작 (KST) | duration (h) | peak hour | 상대 peak 구간 | bursts |','|---|---|---:|---:|---:|---:|',...comparison.scenarios.map(s=>`| ${s.scenario_id} | ${s.event_at} | ${s.duration_hours.toFixed(2)} | ${s.peak_hour} | ${s.peak_relative_bin+1}/12 | ${s.burst_events} |`),'','실제 원본 작성 시각은 수정하지 않습니다. 동일 분포는 상대 12구간 개수 벡터의 완전 일치로 정의했습니다.','','## 해석의 한계','',...report.limitations.map(s=>'- '+s),''];
await fs.writeFile(path.join(output,'temporal-quality.md'),lines.join('\n'));console.log(lines.slice(0,23).join('\n'));console.log('\nSaved: '+output);
