// 가상 사건의 시간과 화면 재생 속도는 독립적입니다. 외부 API/모델을 사용하지 않습니다.
import { createHash, randomBytes } from 'node:crypto';

export const TEMPORAL_PATTERNS = ['rapid_spike','gradual_growth','double_peak','delayed_spike','long_tail','low_activity'];
const HOUR = 3600000;
const MINUTE = 60000;
const DAY = 24 * HOUR;
const daytimeWeights = [0.30,0.23,0.18,0.14,0.14,0.22,0.40,0.65,0.95,1.1,1.15,1.12,1.25,1.2,1.13,1.08,1.15,1.4,1.7,1.85,1.65,1.35,0.95,0.55];

/** 같은 seed로 비교·재현할 수 있는 작은 PRNG. 역할/정답 값은 seed에 넣지 않습니다. */
export function seededRandom(seed) {
  let state = createHash('sha256').update(String(seed)).digest().readUInt32LE(0);
  return () => {
    state += 0x6D2B79F5;
    let value = state;
    value = Math.imul(value ^ value >>> 15, value | 1);
    value ^= value + Math.imul(value ^ value >>> 7, value | 61);
    return ((value ^ value >>> 14) >>> 0) / 4294967296;
  };
}
const positive = rng => Math.max(1e-9,rng());
function normal(rng) { return Math.sqrt(-2*Math.log(positive(rng))) * Math.cos(2*Math.PI*rng()); }
function lognormal(rng,median,sigma) { return median * Math.exp(sigma * normal(rng)); }
function gamma(rng,shape=2) { return Array.from({length:shape},()=>-Math.log(positive(rng))).reduce((a,b)=>a+b,0)/shape; }
function pickWeighted(weights,rng) {
  let target=rng()*weights.reduce((a,b)=>a+b,0);
  for(let i=0;i<weights.length;i++){target-=weights[i];if(target<=0)return i;}
  return weights.length-1;
}
export function seoulHour(ms) { return new Date(ms+9*HOUR).getUTCHours(); }
export function isoSeoul(ms) { return new Date(ms+9*HOUR).toISOString().replace('Z','+09:00'); }

/** 역할과 무관한 동일 생성식을 사용합니다. 활동 시간은 제약이 아니라 가중치입니다. */
export function accountActivity(actorId) {
  const rng=seededRandom('veil-activity-v1:'+actorId);
  const centre=pickWeighted(daytimeWeights,rng), width=Math.min(8,3+Math.floor(gamma(rng)*2));
  const active_hours=Array.from({length:Math.min(12,width*2+1)},(_,i)=>(centre-width+i+48)%24);
  return {active_hours, posting_frequency:Math.min(12,Math.max(0.15,lognormal(rng,1.2,0.95))),
    burst_probability:0.08+Math.pow(rng(),1.5)*0.64,
    response_delay:Math.min(180,lognormal(rng,12,1.15)),
    late_participant:rng()<0.22};
}
function intensity(x,parameters) {
  const bump=(centre,spread)=>Math.exp(-0.5*((x-centre)/spread)**2);
  switch(parameters.pattern){
    case 'rapid_spike':return 0.025+2.5*bump(parameters.peak,parameters.width)+0.3*Math.exp(-x*7);
    case 'gradual_growth':return 0.04+Math.pow(x,1.2+parameters.growth)*Math.exp(-Math.max(0,x-parameters.peak)*9);
    case 'double_peak':return parameters.selectedPeak === undefined
      ? 0.04+1.3*bump(parameters.peak,parameters.width)+parameters.secondStrength*bump(parameters.secondPeak,parameters.width*0.8)
      : 0.004+bump(parameters.selectedPeak,parameters.width);
    case 'delayed_spike':return 0.02+2*bump(parameters.peak,parameters.width)+0.12*Math.exp(-Math.max(0,x-parameters.peak)*4);
    case 'long_tail':return 0.04+1/Math.pow(1+x*13,1.1)+0.7*bump(parameters.peak,parameters.width);
    case 'low_activity':return 0.18+0.08*Math.sin(x*Math.PI*2+parameters.growth)+0.08*bump(parameters.peak,parameters.width*2);
    default:throw new Error('지원하지 않는 시간 패턴');
  }
}
function scenarioParameters(pattern,rng) {
  const means={rapid_spike:3.5,gradual_growth:13,double_peak:11,delayed_spike:9,long_tail:25,low_activity:22};
  const durationHours=Math.min(48,Math.max(1.5,lognormal(rng,means[pattern],0.32)));
  const peakBase={rapid_spike:0.10,gradual_growth:0.72,double_peak:0.21,delayed_spike:0.64,long_tail:0.11,low_activity:0.42};
  const peak=Math.max(0.035,Math.min(0.88,peakBase[pattern]+normal(rng)*0.035));
  return {pattern,durationHours,peak,width:Math.max(0.025,Math.min(0.19,lognormal(rng,0.065,0.4))),
    secondPeak:Math.min(0.92,Math.max(0.52,0.71+normal(rng)*0.05)),secondStrength:lognormal(rng,1.4,0.25),growth:gamma(rng)};
}

/** 조건부 활동 강도 + 일주기 + 계정 반응 지연 + 자기 계정 burst로 시각을 선택합니다. */
export function createTemporalPlan({seed=randomBytes(12).toString('hex'),pattern='auto',now=new Date(),quoteCount=60,claimCount=12,quoteActors=null}={}) {
  if(quoteActors && (quoteActors.length!==quoteCount || quoteActors.some(id=>typeof id!=='string'||!id)))throw new Error('계정 시간표의 길이·ID를 확인하세요.');
  const rng=seededRandom(seed);
  if(pattern==='auto')pattern=TEMPORAL_PATTERNS[Math.floor(rng()*TEMPORAL_PATTERNS.length)];
  if(!TEMPORAL_PATTERNS.includes(pattern))throw new Error('지원하지 않는 시간 패턴');
  const parameters=scenarioParameters(pattern,rng), duration=parameters.durationHours*HOUR;
  // 최근 며칠 중 활동량에 가중치를 둔 사건 시각. 끝 시각은 현재보다 과거에 둡니다.
  const latestStart=now.getTime()-duration-HOUR;
  const dayBase=Math.floor((latestStart+9*HOUR)/DAY)*DAY-9*HOUR;
  const eventHour=pickWeighted(daytimeWeights,rng);
  let eventAt=dayBase+eventHour*HOUR+Math.floor(rng()*60)*MINUTE+Math.floor(rng()*60)*1000;
  while(eventAt>latestStart)eventAt-=DAY;
  eventAt-=Math.floor(gamma(rng)*1.4)*DAY;
  const secondaryIssueTime=pattern==='double_peak'?eventAt+Math.max(0.30,parameters.secondPeak-2*parameters.width)*duration:null;
  const profiles={};
  const profile=id=>profiles[id] ||= accountActivity(id);
  const firstDelay=Math.min(duration*0.06,Math.max(2*MINUTE,lognormal(rng,7*MINUTE,0.8)));
  const rootTime=eventAt+firstDelay;
  const usedTimes=new Set([Math.round(rootTime)]), existingTimes=new Map();
  existingTimes.set('campaign_a',[rootTime]);
  function sampleTime(actor,index,total) {
    const activity=profile(actor), prior=existingTimes.get(actor)||[];
    // 후속 이슈 참여 여부부터 고르고 해당 peak 안에서 활동 시간 가중치를 적용합니다.
    // 밤의 후속 사건도 낮의 첫 사건에 모든 확률 질량을 빼앗기지 않게 합니다.
    const localParameters=pattern==='double_peak'?{...parameters,selectedPeak:rng()<parameters.secondStrength/(1.3+parameters.secondStrength)?parameters.secondPeak:parameters.peak}:parameters;
    const delay=activity.response_delay*MINUTE+(activity.late_participant?duration*0.22:0);
    const minimum=Math.max(rootTime+1000,eventAt+Math.min(delay,duration*0.70),
      localParameters.selectedPeak===parameters.secondPeak&&secondaryIssueTime?secondaryIssueTime:0);
    const slots=Math.max(30,Math.ceil(duration/(2*MINUTE))), weights=[];
    for(let bin=0;bin<slots;bin++){
      const x=(bin+0.5)/slots, ms=eventAt+x*duration, hour=seoulHour(ms);
      const accountWeight=activity.active_hours.includes(hour)?1.7:0.35;
      const phaseBias=1+0.45*Math.cos((x-index/Math.max(1,total))*Math.PI);
      weights.push(ms<minimum?0:intensity(x,localParameters)*daytimeWeights[hour]*accountWeight*phaseBias);
    }
    let time;
    // 집중 재게시 때도 모든 계정에 동일한 간격을 부여하지 않습니다.
    if(prior.length && rng()<activity.burst_probability){
      const neighbour=prior[Math.floor(rng()*prior.length)];
      time=neighbour+lognormal(rng,4*MINUTE/activity.posting_frequency,0.85);
    } else {
      const bin=pickWeighted(weights,rng);
      time=eventAt+(bin+0.5)/slots*duration+normal(rng)*45*1000;
    }
    time=Math.max(minimum,Math.min(eventAt+duration-1000,time));
    time=Math.round(time/1000)*1000;
    while(usedTimes.has(time)) {
      time += 1000 + Math.floor(rng()*19)*1000;
      if(time >= eventAt+duration) time=Math.round((minimum+rng()*(eventAt+duration-2000-minimum))/1000)*1000;
    }
    usedTimes.add(time);prior.push(time);existingTimes.set(actor,prior);
    return {actorId:actor,created_at:isoSeoul(time)};
  }
  const pool=Array.from({length:28},(_,i)=>'observer_'+(i+1));
  const weights=pool.map(id=>profile(id).posting_frequency);
  const quotes=Array.from({length:quoteCount},(_,i)=>{
    // 초기·후발 참여자를 섞고 일반 사용자에게도 여러 게시물을 부여합니다.
    const actor=quoteActors?quoteActors[i]:(i<12?pool[i]:pool[pickWeighted(weights,rng)]);
    return {...sampleTime(actor,i,quoteCount),...(quoteActors?{entryIndex:i}:{})};
  }).sort((a,b)=>Date.parse(a.created_at)-Date.parse(b.created_at));
  const claims=Array.from({length:claimCount},(_,i)=>sampleTime(i%2===0?'campaign_a':'campaign_b',i,claimCount))
    .sort((a,b)=>Date.parse(a.created_at)-Date.parse(b.created_at));
  profile('campaign_a');profile('campaign_b');
  return {version:1,seed,pattern,event_at:isoSeoul(eventAt),planned_end_at:isoSeoul(eventAt+duration),
    duration_hours:parameters.durationHours,secondary_event_at:secondaryIssueTime?isoSeoul(secondaryIssueTime):null,parameters,account_profiles:profiles,
    root:{actorId:'campaign_a',created_at:isoSeoul(rootTime)},quotes,claims};
}
