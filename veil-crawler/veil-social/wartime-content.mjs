// Fictional test-only voices, based on aggregate writing features rather than copied users.
import { seededRandom } from './temporal.mjs';

const ko = {
  front:['남공화국 전선이 전부 무너졌고 방어도 멈췄다','일부 전선에서 밀린 건 맞는데 다른 구역은 방어 중이다'],
  orders:['남공화국 군 통수권자가 전군 항복이랑 전면 철수를 발표했다','확인된 건 일부 구역 재배치다. 전군 항복이나 철수 발표는 없다'],
  alliance:['남공화국이랑 남태평양국 군대가 서로 교전하고 있다','양국의 보급 조율과 지원 분담 이견으로 협력이 악화됐다. 서로 교전했다는 건 확인되지 않았다'],
  troops:['남태평양국 파병군이 전부 철수했고 남공화국 지원도 끊었다','남태평양국 일부 인력은 예정대로 교대 중이다. 지원 중단 발표는 없다'],
  military:['남공화국 주요 군 시설이 전부 파괴돼서 군 기능이 멈췄다','피해가 확인된 건 보급시설 한 곳이다. 다른 시설 상황은 따로 확인 중이다'],
  civilian:['남공화국 전국 병원이랑 민간 기반시설이 다 무너졌다','한 지역에서 민간 시설 피해가 발생했다. 전국 시설이 무너졌다는 자료는 없다'],
  casualties:['민간 피해가 공식 집계보다 수십 배 많은 걸로 확정됐는데 당국이 숨기고 있다','민간 피해는 발생했고 집계도 진행 중이다. 서로 다른 지역과 시각의 숫자를 한꺼번에 비교하면 안 된다'],
  displacement:['전국 대피소가 다 닫혔고 피란민 지원도 완전히 중단됐다','피란 인원과 구호 수요가 늘고 있다. 운영 중인 대피소도 있고 전국 총계는 확인 중이다'],
  economy:['남공화국 경제가 완전히 무너졌고 은행도 전부 지급을 중단했다','물류 차질과 가격 변동은 있다. 금융기관 전체가 지급을 중단했다는 확인은 없다'],
  industry:['남공화국 산업시설이 전부 파괴돼서 생산이 영구 중단됐다','일부 산업시설 가동이 중단됐다. 시설마다 피해와 복구 상태는 다르다'],
};
const en = {
  front:['Every Southern Republic front has collapsed and all defence has stopped','Some Southern Republic sectors have fallen back, but other defensive sectors are still active'],
  orders:['The Southern Republic commander-in-chief announced surrender and a complete withdrawal','What is confirmed is limited redeployment. There is no announcement of an all-force surrender or withdrawal'],
  alliance:['Southern Republic and South Pacific State troops are now fighting each other','Disagreements over supply coordination and assistance responsibilities have strained cooperation. An armed clash between the two countries has not been confirmed'],
  troops:['South Pacific State has pulled out every deployed unit and cut off all assistance','Some South Pacific State personnel are on scheduled rotation. No end to assistance has been announced'],
  military:['All major Southern Republic military facilities are destroyed and operations have stopped','Damage at one supply facility is confirmed. Other facilities still need to be checked separately'],
  civilian:['Hospitals and civilian infrastructure across Southern Republic have all collapsed','Civilian facilities were damaged in one area. That does not establish a nationwide collapse'],
  casualties:['Civilian losses were confirmed at dozens of times the official count, and authorities are hiding the total','Civilian harm has occurred and counting is ongoing. Figures from different areas and times should not be treated as the same total'],
  displacement:['Every shelter nationwide is closed and all help for displaced people has stopped','Displacement and relief needs are rising. Some shelters remain open and the national total is still being checked'],
  economy:['Southern Republic’s economy has completely collapsed and every bank has stopped payments','Logistics disruption and price changes are real. A shutdown of payments at every financial institution has not been verified'],
  industry:['All industrial facilities in Southern Republic were destroyed and production has permanently ended','Some industrial sites have stopped production. Damage and recovery differ from one facility to another'],
};

export const OVERVIEW_TEXT=[
  '남공화국과 북공화국의 전쟁이 이어지고 있다.',
  '남공화국과 남태평양국은 동맹이지만 지원 분담과 보급 조율을 놓고 관계가 악화됐다.',
  '중앙아시아연합국이 북공화국에 비공개로 무기를 지원한다는 의혹도 나오고 있다.',
  '전선 패배와 후퇴 명령, 동맹 충돌과 파병군 철수에 관한 소식이 뒤섞여 올라온다.',
  '군·민간 시설 피해, 민간 피해와 피란민 증가, 경제·산업 위기까지 겹쳐 무엇이 확인된 건지 구분이 어렵다.',
].join('\n');

// Longer fixtures add context without inventing witnesses, documents, or operational instructions.
const details = {
  ko: {
    front:['전선 얘기에는 어느 구역인지와 언제의 상황인지가 같이 있어야 한다.','후퇴 소식 하나를 전체 방어 상황으로 읽으면 서로 다른 지역의 이야기가 섞인다.'],
    orders:['일부 구역의 재배치와 전군에 내려진 명령은 범위가 크게 다르다.','짧게 잘린 문장만 돌아다니면 누가 무엇을 발표했는지 빠지기 쉽다.'],
    alliance:['보급 협의의 이견인지 실제 무력 충돌인지부터 구분해야 하는 이야기다.','동맹 관련 소식은 현장 상황과 외교 발표가 같은 시점의 내용인지도 중요하다.'],
    troops:['인력 교대, 일부 철수, 지원 종료는 각각 다른 뜻이다.','이동하는 인원이 있다는 설명만으로 전체 파병군의 상태를 판단하기는 어렵다.'],
    military:['시설 피해와 군 전체의 기능 중단은 같은 범위의 주장이 아니다.','어떤 시설인지와 피해 확인 시각이 빠지면 규모를 가늠할 수 없다.'],
    civilian:['병원, 전력, 통신 등은 지역별로 상황이 다를 수 있다.','한 곳의 피해 소식을 전국의 시설 상태로 넓혀 읽지 않도록 범위를 봐야 한다.'],
    casualties:['초기 집계와 이후 집계는 대상 지역이나 기준 시각이 다를 수 있다.','서로 다른 숫자를 비교하려면 중복 집계와 확인 범위부터 살펴야 한다.'],
    displacement:['피란 인원 증가와 구호 중단 여부는 따로 확인해야 하는 문제다.','대피소 수용 상태도 한 지역의 이야기인지 전국 총계인지에 따라 의미가 달라진다.'],
    economy:['물류 차질, 가격 변동, 금융기관 지급 중단은 서로 다른 문제다.','불안한 경제 소식이 여럿 나온다는 것과 모든 은행이 멈췄다는 것은 범위가 다르다.'],
    industry:['일시적인 가동 중단인지 시설 파괴인지에 따라 이후 상황이 달라진다.','개별 시설의 피해와 전체 산업의 생산 상태를 한 문장으로 묶으면 세부 내용이 사라진다.'],
  },
  en: {
    front:['A front-line report needs a location and a time to make sense.','A withdrawal in one sector does not describe every defensive sector.'],
    orders:['Limited redeployment and an order to every unit have very different scopes.','A cropped sentence can leave out who spoke and what was actually announced.'],
    alliance:['A disagreement over supplies and an armed clash are different claims.','Reports about the alliance also need a clear distinction between field updates and diplomatic statements.'],
    troops:['Rotation, partial withdrawal and an end to assistance mean different things.','Personnel movements alone do not establish the status of every deployed unit.'],
    military:['Damage to a facility and the loss of all military capability are different claims.','Without the facility and the time of confirmation, the scale remains unclear.'],
    civilian:['Hospitals, power and communications may have different conditions in different areas.','A report about one site does not describe civilian infrastructure nationwide.'],
    casualties:['Early and later counts may cover different places or reporting periods.','Figures need matching definitions and checks for duplicate entries before comparison.'],
    displacement:['Rising displacement and an end to relief provision need separate checks.','Shelter conditions mean different things when the report concerns one area rather than the whole country.'],
    economy:['Logistics delays, price changes and suspended bank payments are separate issues.','Several worrying economic reports do not establish a shutdown of every bank.'],
    industry:['A temporary production stop and destruction of a facility have different implications.','Combining individual site damage with the condition of all industry loses essential detail.'],
  },
};

function expandPost(short,topic,language,n) {
  if(n%5>1)return short;
  const english=language==='en';
  const contexts=details[english?'en':'ko'][topic.id];
  const openings=english
    ?['There is more to this than the headline.','Putting the details together in one post.','This keeps coming up in my feed, so here is the context.']
    :['짧은 글만 계속 올라와서 내용을 조금 길게 정리해 봄.','제목만 읽으면 빠지는 내용이 있어서 같이 적어 둔다.','이 얘기가 계속 보여서 쟁점을 한 글에 모아 봤다.'];
  const closings=english
    ?['The location, timing and scope still matter when reading the next update.','I would keep the original wording and later updates together.','The headline alone leaves too much out.']
    :['다음 소식도 지역, 시각, 범위를 같이 보면서 읽어야 할 것 같다.','앞뒤 맥락과 이후 업데이트까지 같이 봐야 이해가 될 듯.','한두 줄 제목만으로는 빠지는 내용이 너무 많다.'];
  const ending=closings[Math.floor(n/17)%closings.length];
  return [openings[Math.floor(n/5)%openings.length],short.replace(/\n+/g,' '),...contexts,ending].join('\n');
}

export function formatWartimePost(topic,kind,language,variant=0,format='personal') {
  const n=Math.abs(Number(variant)||0), pair=(language==='en'?en:ko)[topic.id];
  if(!pair)throw new Error('Unknown wartime topic');
  const [claim,truth]=pair;
  if(language==='en') {
    const cores={claim:format==='rumor'?`${claim}, apparently.`:format==='news'?`${claim}.`:`${claim}.`,
      question:`Seeing posts saying “${claim}”. Is there an original source for this?`,
      refutation:`“${claim}” is not what the available record says. ${truth}.`,
      official:`Update: ${truth}.`};
    const endings=['','The details are getting mixed up in my feed.','Still following the updates.','A lot of different accounts are talking about this.','Hard to keep up with all the reports today.','The situation is changing quickly.','Trying to separate the reports from the reactions.'];
    const prefix=format==='news'?'Latest: ':format==='rumor'?'Seeing this going around: ':'';
    const short=`${prefix}${cores[kind]}${n%2?'\n\n':' '}${endings[Math.floor(n/2)%endings.length]}`.trim();
    return expandPost(short,topic,language,n);
  }
  const cores={claim:format==='rumor'?`${claim}는 얘기 돌던데.`:format==='news'?`${claim}.`:`${claim}고 함.`,
    question:`${claim}는 글 봤는데 이거 원문 있는 거 맞아?`,
    refutation:`${claim}는 얘기는 확인된 내용이랑 다름. ${truth}.`,
    official:`현재 확인된 내용은 이렇습니다. ${truth}.`};
  const endings=['','오늘 올라오는 소식이 너무 많네.','피드에 이 얘기 계속 뜸.','관련 소식 계속 보는 중.','같은 얘기도 계정마다 조금씩 다르게 쓰네.','다른 지역 상황도 궁금하다.','댓글까지 읽으니 더 헷갈림.','소식이 한꺼번에 올라와서 따라가기 어렵다.','앞뒤 내용 같이 봐야 할 듯.'];
  const prefix=format==='news'?'상황 소식: ':format==='rumor'?'이런 얘기 돌고 있음. ':'';
  const short=`${prefix}${cores[kind]}${n%2?'\n\n':' '}${endings[Math.floor(n/2)%endings.length]}`.trim();
  return expandPost(short,topic,language,n);
}

function allocate(total,actors,rng) {
  // Both groups include single-post and repeat authors; roles never drive timestamp generation.
  const singleCount=Math.max(3,Math.floor(actors.length/8));
  const repeated=actors.slice(singleCount);
  const counts=new Map(actors.map(actor=>[actor,1]));
  const weights=repeated.map(()=>0.1+Math.pow(rng(),2)*5);
  const sum=weights.reduce((a,b)=>a+b,0);
  for(let i=actors.length;i<total;i++) {
    let point=rng()*sum,index=weights.length-1;
    for(let j=0;j<weights.length;j++){point-=weights[j];if(point<=0){index=j;break;}}
    const actor=repeated[index];counts.set(actor,counts.get(actor)+1);
  }
  return [...counts].flatMap(([actorId,count])=>Array.from({length:count},(_,i)=>({actorId,authorSequence:i})));
}

export function createWartimeContentPlan(seed) {
  const rng=seededRandom(seed+':contents-v2');
  const pool=Array.from({length:100},(_,i)=>'war_account_'+String(i+1).padStart(3,'0'));
  const plans=[
    ['claim',1500,pool.slice(0,60)],
    ['question',100,pool.slice(60,74)],
    ['refutation',100,pool.slice(74,87)],
    ['official',100,pool.slice(87)],
  ];
  const entries=plans.flatMap(([kind,count,actors])=>allocate(count,actors,rng).map((entry,i)=>({
    ...entry,kind,topicIndex:i%10,language:i%3===2?'en':'ko',variant:Math.floor(rng()*10000),
    format:['personal','rumor','news','personal'][Math.floor(rng()*4)],referenceRoll:rng(),
  })));
  for(let i=entries.length-1;i>0;i--){const j=Math.floor(rng()*(i+1));[entries[i],entries[j]]=[entries[j],entries[i]];}
  return entries;
}
