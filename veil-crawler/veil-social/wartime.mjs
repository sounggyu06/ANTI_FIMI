// Closed, fictional training fixtures. No external publishing, generated orders or real actors.
import { randomUUID } from 'node:crypto';
import { seededRandom } from './temporal.mjs';
import { createWartimeContentPlan, formatWartimePost, OVERVIEW_TEXT } from './wartime-content.mjs';

export const WARTIME_BATCH_SIZE = 1;
export const WARTIME_MIN_INTERVAL_MS = 100;
export const WARTIME_MAX_INTERVAL_MS = 400;

function nextInterval(seed,index) {
  return WARTIME_MIN_INTERVAL_MS+Math.floor(seededRandom(`${seed}:realtime-delay:${index}`)()
    *(WARTIME_MAX_INTERVAL_MS-WARTIME_MIN_INTERVAL_MS+1));
}
export const WARTIME_TOPICS = [
  {id:'front', title:'전선 상황', cards:['08'],
    truth:'남공화국 일부 전선에서 후퇴가 있었으나 다른 구역의 방어는 유지되고 있다.',
    claim:'남공화국의 모든 전선이 무너졌고 방어가 완전히 중단됐다.',
    enTruth:'Some Southern Republic sectors have fallen back; other defensive sectors remain active.',
    enClaim:'Every Southern Republic front has collapsed and all defence has stopped.'},
  {id:'orders', title:'후퇴 명령', cards:['03','08','15','33'],
    truth:'훈련 기준 문서에는 일부 구역의 재배치만 명시되어 있으며 전군 항복·철수 명령은 없다.',
    claim:'군 통수권자가 전군의 항복과 전면 철수를 발표했다.',
    enTruth:'The exercise record describes limited redeployment, with no all-force surrender or withdrawal order.',
    enClaim:'The commander-in-chief announced the surrender and complete withdrawal of all forces.'},
  {id:'alliance', title:'동맹국 충돌', cards:['08','36'],
    truth:'남공화국과 남태평양국의 보급 조율과 지원 분담 이견으로 협력이 악화됐다. 양국 간 무력 충돌은 확인되지 않았다.',
    claim:'남공화국과 동맹 남태평양국의 군대가 서로 교전하고 있다.',
    enTruth:'Supply coordination and assistance disagreements have strained Southern Republic–South Pacific State cooperation; no armed clash between them is confirmed.',
    enClaim:'Southern Republic and its ally South Pacific State are fighting each other.'},
  {id:'troops', title:'파병군 철수', cards:['08','36'],
    truth:'남태평양국 일부 파병 인력은 예정된 교대 중이며 지원 중단 발표는 없다.',
    claim:'남태평양국이 파병군을 모두 철수시키고 남공화국 지원을 끊었다.',
    enTruth:'Some deployed South Pacific State personnel are on scheduled rotation; no end to assistance has been announced.',
    enClaim:'South Pacific State withdrew every deployed unit and ended all assistance to Southern Republic.'},
  {id:'military', title:'군 시설 피해', cards:['08','09'],
    truth:'가상 보급시설 한 곳의 피해가 확인되었고 다른 주요 시설의 상태는 각각 확인 중이다.',
    claim:'남공화국의 주요 군사시설이 전부 파괴되어 군 기능이 사라졌다.',
    enTruth:'Damage at one fictional supply facility is confirmed; other facilities require separate verification.',
    enClaim:'All major military facilities in Southern Republic were destroyed and military operations ended.'},
  {id:'civilian', title:'민간 시설 피해', cards:['08','09'],
    truth:'한 지역의 민간 시설 피해는 확인되었으나 전국 시설 붕괴를 뒷받침하는 자료는 없다.',
    claim:'남공화국 전역의 병원과 민간 기반시설이 모두 붕괴했다.',
    enTruth:'Civilian facility damage is confirmed in one area, without evidence of nationwide collapse.',
    enClaim:'Hospitals and civilian infrastructure throughout Southern Republic have all collapsed.'},
  {id:'casualties', title:'민간 피해 집계', cards:['08','35'],
    truth:'민간 피해가 발생했으며 집계는 진행 중이다. 지역·시각·확인 범위가 다른 수치는 직접 비교할 수 없다.',
    claim:'민간 피해가 공식 집계의 수십 배로 확정됐지만 당국이 숨기고 있다.',
    enTruth:'Civilian harm has occurred and counting continues; totals from different areas and times are not directly comparable.',
    enClaim:'Civilian losses were confirmed at dozens of times the official count and authorities concealed the total.'},
  {id:'displacement', title:'피란·구호 상황', cards:['08','35'],
    truth:'피란 인원과 구호 수요가 증가했고 일부 대피소는 운영 중이다. 전국 단위 총계는 아직 확인 중이다.',
    claim:'전국의 모든 대피소가 폐쇄됐으며 피란민 지원이 전면 중단됐다.',
    enTruth:'Displacement and relief needs are increasing; some shelters remain open and national totals are still being checked.',
    enClaim:'Every shelter nationwide closed and all assistance to displaced people stopped.'},
  {id:'economy', title:'경제 상황', cards:['08','35'],
    truth:'물류 차질과 가격 변동이 있으나 금융기관 전체의 지급 중단을 확인한 자료는 없다.',
    claim:'남공화국 경제가 완전히 붕괴했고 모든 금융기관이 지급을 중단했다.',
    enTruth:'Logistics disruption and price changes exist; there is no verified record of every financial institution stopping payments.',
    enClaim:'Southern Republic’s economy completely collapsed and every financial institution stopped payments.'},
  {id:'industry', title:'산업시설 상황', cards:['08','09','35'],
    truth:'일부 산업시설은 가동이 중단됐으며 시설별 피해와 복구 상태는 다르다.',
    claim:'남공화국의 모든 산업시설이 파괴됐고 생산이 영구적으로 중단됐다.',
    enTruth:'Some industrial sites stopped production; damage and recovery status differ by facility.',
    enClaim:'All industrial facilities in Southern Republic were destroyed and production permanently ended.'},
];

// A private answer key is kept beside the fixtures, never in the public feed or crawler response.
export const wartimeAnswerKey = () => ({
  scenario:'wartime', fictional:true, title:'전시 복합 위기',
  scope:'네 가상 국가의 전시 테스트. 기사와 음성은 설명용 텍스트이며 실제 명령·음성 자산을 생성하지 않음.',
  background:{countries:['중앙아시아연합국','북공화국','남공화국','남태평양국'],
    belligerents:['남공화국','북공화국'],alliance:['남공화국','남태평양국'],
    alliance_status:'지원 분담과 보급 조율 이견으로 협력 악화. 동맹 해체 또는 동맹군 간 교전은 확정되지 않음',
    covert_arms_supporter:'중앙아시아연합국',covert_arms_recipient:'북공화국',
    covert_arms_support_status:'시나리오 내부 사실. 공개 피드에서는 미확인 의혹으로 표현하며 실제 국가 사건을 주장하지 않음'},
  topics:WARTIME_TOPICS.map(({id,title,cards,truth,claim})=>({id,title,cards,truth,claim,claim_status:'refuted'})),
  grading:'유형별 잠재등급은 사건 위험등급과 별도. 임박한 위해·행동 지시·대상 도달 확인 전 Critical 자동 부여 금지.',
});

function basePost(fields) {
  return {id:'v-'+randomUUID(),verified:false,comments:0,reposts:0,likes:0,repostOf:null,images:[],
    source_type:'synthetic',scenario_key:'wartime',...fields};
}

// Synthetic engagement for the closed feed. Truth labels never determine popularity.
export function wartimeLikeCount(post,progress=1) {
  const rng=seededRandom(`wartime-likes-v1:${post.simulationActorId||post.authorId}:${post.publishedAt}`);
  const group=rng();
  const target=group<0.12?0:group<0.68?1+Math.floor(rng()*90)
    :group<0.9?120+Math.floor(rng()*3880):5000+Math.floor(rng()*45000);
  const fraction=Math.max(0,Math.min(1,Number(progress)||0));
  return Math.floor(target*Math.pow(fraction,1.6));
}

export function beginWartime(posts,now=new Date(),mode='normal',options={}) {
  const totalPosts=1801;
  const runId=randomUUID();
  const timingSeed=options.seed||runId;
  const contentPlan=createWartimeContentPlan(timingSeed);
  const interval=nextInterval(timingSeed,0);
  const root=basePost({simulationActorId:'wartime_overview',authorId:'scenario_wartime_overview',
    name:'훈련 상황 기록',handle:'scenario_wartime_overview',language:'ko',
    text:OVERVIEW_TEXT,
    publishedAt:now.toISOString(),simulationRunId:runId,scenario_id:runId,
    evaluation_kind:'overview',simulation_role:'observer'});
  return {posts:[root,...posts],state:{status:'running',scenarioKey:'wartime',mode:'realtime',runId,rootId:root.id,
    startedAt:now.toISOString(),wave:0,totalWaves:Math.ceil((totalPosts-1)/WARTIME_BATCH_SIZE),
    quoteCount:0,scenarioCount:0,rootLikes:0,error:null,generatedCount:1,totalPosts,claimTarget:1500,
    waveIntervalMs:interval,nextPostAt:new Date(now.getTime()+interval).toISOString(),
    timingPolicy:'realtime-random',timingSeed,contentPlan,topicRoots:{},topicPostIds:{},
    kindCounts:{overview:1,claim:0,question:0,refutation:0,official:0}}};
}

export function advanceWartime(posts,state,now=new Date()) {
  if(state.status!=='running')return {posts,state};
  if(now.getTime()<Date.parse(state.nextPostAt))return {posts,state};
  const count=Math.min(WARTIME_BATCH_SIZE,state.totalPosts-state.generatedCount);
  const topicRoots={...state.topicRoots}, topicPostIds=Object.fromEntries(Object.entries(state.topicPostIds).map(([id,list])=>[id,[...list]])), kindCounts={...state.kindCounts}, added=[];
  for(let offset=0;offset<count;offset++) {
    const index=state.generatedCount-1+offset;
    const entry=state.contentPlan[index];
    const topic=WARTIME_TOPICS[entry.topicIndex], {kind,language}=entry;
    const actor='wartime_'+entry.actorId;
    const candidates=topicPostIds[topic.id]||[];
    const repostOf=candidates.length && entry.referenceRoll<0.8?candidates[Math.floor(entry.referenceRoll/0.8*candidates.length)]:null;
    const post=basePost({simulationActorId:actor,authorId:'scenario_'+actor,handle:'scenario_'+actor,
      name:'상황 기록',language,text:formatWartimePost(topic,kind,language,entry.variant,entry.format),
      publishedAt:now.toISOString(),repostOf,referenceType:repostOf?'quotes':null,
      simulationRunId:state.runId,scenario_id:state.runId,topic_id:topic.id,
      evaluation_kind:kind,post_format:entry.format,text_variant:entry.variant,evaluation_claim_status:kind==='claim'?'refuted':kind==='question'?'question':kind==='official'?'supported':'refutation',
      simulation_role:kind==='claim'?'malicious_actor':kind==='official'?'official_source':'observer'});
    if(!topicRoots[topic.id])topicRoots[topic.id]=post.id;
    (topicPostIds[topic.id] ||= []).push(post.id);
    kindCounts[kind]++;
    added.push(post);
  }
  const generatedCount=state.generatedCount+added.length, done=generatedCount===state.totalPosts;
  const interval=nextInterval(state.timingSeed,generatedCount-1);
  const combined=[...added.reverse(),...posts];
  const referenceCounts=new Map();
  for(const post of combined)if(post.simulationRunId===state.runId && post.repostOf)
    referenceCounts.set(post.repostOf,(referenceCounts.get(post.repostOf)||0)+1);
  const updated=combined.map(post=>post.simulationRunId===state.runId?{...post,
    reposts:referenceCounts.get(post.id)||0,
    likes:Math.max(post.likes||0,wartimeLikeCount(post,(state.wave+1)/state.totalWaves))}:post);
  return {posts:updated,
    state:{...state,wave:state.wave+1,generatedCount,topicRoots,topicPostIds,kindCounts,
      waveIntervalMs:interval,nextPostAt:done?null:new Date(now.getTime()+interval).toISOString(),
      rootLikes:updated.find(post=>post.id===state.rootId)?.likes||0,
      quoteCount:[...referenceCounts.values()].reduce((sum,value)=>sum+value,0),scenarioCount:kindCounts.claim,
      status:done?'completed':'running',endedAt:done?now.toISOString():null}};
}

export function advanceFastWartime(posts,state,now=new Date()) {
  // Legacy fast callers follow the same real-time rule; never catch up in a burst.
  return advanceWartime(posts,state,now);
}
