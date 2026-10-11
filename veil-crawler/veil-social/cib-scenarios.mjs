/**
 * VEIL Social 내부 합성 시나리오. 기존 웹 서버의 게시물 저장 경로만 사용합니다.
 * 알림, 점수, 판정 또는 정답 데이터를 공개 피드에 삽입하지 않습니다.
 * publishedAt은 시연을 위한 가속된 합성 시간이며 실제 업로드 시각이 아닙니다.
 */
import { randomUUID } from 'node:crypto';

export const CIB_KEYS = ['cib_burst', 'cib_repeat', 'cib_cascade', 'cib_authority', 'cib_retreat', 'cib_emergency'];
export const CIB_TITLES = {
  cib_burst: '실험 1 · 단발성 동시 확산',
  cib_repeat: '실험 2 · 반복 계정 공조',
  cib_cascade: '실험 3 · 연쇄 인용·조직적 증폭',
  cib_authority: '실험 4 · 고위직 사칭 주장 확산',
  cib_retreat: '실험 5 · 미확인 후퇴 명령 주장',
  cib_emergency: '실험 6 · 긴급 공지 사칭·증폭',
};
const DELAY_MS = 1300; // 웹 게시물은 실제로 조금씩 생성되고, 시간축은 별도로 가속됩니다.
const ISO = ms => new Date(ms).toISOString();
const LAB = 'https://example.invalid/veil-research/';

export function buildCibPlan(scenarioKey, now = new Date(), runId = randomUUID()) {
  if (!CIB_KEYS.includes(scenarioKey)) throw new Error('지원하지 않는 CIB 실험입니다.');
  const clock = now.getTime();
  const batches = [];
  const items = new Map();
  const usedIds = new Set();

  function post(name, actor, agoMs, body, {url, ref, type = 'quotes'} = {}) {
    if (usedIds.has(name)) throw new Error('시나리오 게시물 ID 중복: ' + name);
    usedIds.add(name);
    const item = {
      id: 'v-' + randomUUID(), simulationActorId: `cib_${runId}_${actor}`,
      authorId: `scenario_${runId}_${actor}`, name: '가상 공개 계정',
      handle: `scenario_${actor}`, language: 'ko',
      verified: false, comments: 0, reposts: 0, likes: 0,
      repostOf: ref ? items.get(ref)?.id : null,
      referenceType: ref ? type : null, images: [],
      text: url ? `${body} ${LAB}${url}` : body,
      publishedAt: ISO(clock - agoMs),
      simulationRunId: runId, scenario_id: runId, source_type: 'synthetic',
    };
    if (ref && !item.repostOf) throw new Error('아직 존재하지 않는 원본: ' + ref);
    if (item.text.length > 280) throw new Error('게시물 글자 수 초과');
    items.set(name, item);
    return item;
  }
  function stage(label, posts) {
    batches.push({label, posts});
  }

  // 정상적인 일반 계정: 모든 시나리오에 존재하며 공유 자료는 없음.
  const ordinary = [
    '오늘은 도서관에서 참고서를 읽었습니다.', '학교 행사를 다녀왔습니다.',
    '퇴근길 교통 상황이 평소와 비슷합니다.', '지역 카페에 새로운 메뉴가 나왔습니다.',
    '날씨가 좋아 산책을 했습니다.', '동아리 모임 일정을 확인했습니다.',
    '이번 주에 읽을 책을 골랐습니다.', '대중교통 운행표를 확인했습니다.',
    '운동 후 충분히 쉬었습니다.', '오늘 찍은 풍경 사진을 정리했습니다.',
    '과제 마감 시간을 확인했습니다.', '지역 축제 안내를 읽었습니다.',
  ];
  stage('정상 활동 수집', ordinary.map((body, i) =>
    post(`normal-${i}`, `normal_${i}`, 15 * 60_000 + i * 10_000, body)));

  if (scenarioKey === 'cib_burst') {
    const body = '라온지역 협력사업이 중단되었다는 미확인 주장이 확산되고 있습니다.';
    const original = post('origin', 'seed', 98_000, body, {url: 'single-notice'});
    stage('최초 관측 게시물', [original]);
    const wave = Array.from({length: 18}, (_, i) => post(
      `burst-${i}`, `burst_${i}`, 95_000 - i * 1500,
      `${body} 원본을 인용합니다.`, {url: 'single-notice', ref: 'origin'}));
    stage('다계정 동시 인용 1회', wave.slice(0, 9));
    stage('다계정 동시 인용 1회 계속', wave.slice(9));
  }

  if (scenarioKey === 'cib_repeat') {
    // 서로 다른 4개 자료를 6개 계정이 75초 이상의 간격을 두고 반복 공유.
    for (let w = 0; w < 4; w++) {
      const resource = `joint-material-${w}`;
      const ago = (5 * 60 + 30 - 80 * w) * 1000;
      stage(`같은 6개 계정의 공동 공유 ${w + 1}/4`, Array.from({length: 6}, (_, i) =>
        post(`shared-${w}-${i}`, `core_${i}`, ago - 1200 * i,
          `라온공화국 공동훈련 관련 주장 자료 ${w + 1}을 공유합니다.`, {url: resource})));
    }
  }

  if (scenarioKey === 'cib_cascade') {
    const origin = post('origin', 'source', 9 * 60_000,
      '누리공화국 의료지원 사업이 전면 중단됐다는 미확인 주장입니다.', {url: 'primary-claim'});
    stage('최초 관측 원본', [origin]);
    let parent = 'origin';
    // 직접 인용의 인용: 생성되는 원본 관계가 모두 실제 저장 ID를 가리킵니다.
    for (let depth = 1; depth <= 5; depth++) {
      const name = `chain-${depth}`;
      const quote = post(name, `relay_${depth}`, (9 * 60 - 11 * depth) * 1000,
        `누리공화국 의료지원 중단설의 ${depth}차 인용입니다.`,
        {ref: parent, type: depth % 2 === 0 ? 'reposts' : 'quotes'});
      stage(`관측 인용·재공유 ${depth}/5`, [quote]);
      parent = name;
    }
    // 2개 핵심 계정이 6개 자료를 반복 공유 → 기존 공조 고강도 규칙 검증.
    for (let w = 0; w < 6; w++) {
      const ago = (7 * 60 + 30 - 75 * w) * 1000;
      stage(`핵심 계정 반복 공유 ${w + 1}/6`, [
        post(`pair-${w}-a`, 'core_a', ago,
          `누리공화국 의료지원 관련 근거 자료 ${w + 1}을 공유합니다.`, {url: `relay-material-${w}`}),
        post(`pair-${w}-b`, 'core_b', ago - 1000,
          `누리공화국 의료지원 관련 근거 자료 ${w + 1}을 공유합니다.`, {url: `relay-material-${w}`}),
      ]);
    }
    const amplified = Array.from({length: 18}, (_, i) => post(
      `amplify-${i}`, `amplifier_${i}`, 55_000 - i * 1500,
      '누리공화국 의료지원 중단설을 같은 원본에서 재확산합니다.',
      {ref: parent, type: 'reposts'}));
    stage('동일 원본의 18계정 재확산 1/2', amplified.slice(0, 9));
    stage('동일 원본의 18계정 재확산 2/2', amplified.slice(9));
  }

  // 추가 3개는 기존 저장·익명화·크롤러·탐지 과정을 그대로 통과합니다.
  // 실명/실제 부대/실제 위치/실제 지시문은 사용하지 않습니다.
  // URL은 접속할 수 없는 example.invalid 도메인의 합성 자료 식별자입니다.
  if (scenarioKey === 'cib_authority') {
    const topic = '라온공화국 위기조정실';
    const original = post('origin', 'claim_source', 12 * 60_000,
      `${topic} 수석조정관 명의의 발표가 나왔다고 알려졌습니다. 공동 지원 예산이 중단됐다는 주장인데 공식 원문은 확인되지 않았습니다.`,
      {url: 'authority-first-report'});
    stage('책임자 명의 발표 주장 최초 등장', [original]);
    const expressions = [
      `${topic} 수석조정관이 공식 발표했다는 글이 돌고 있습니다. 출처가 확인되지 않은 지원 중단설입니다.`,
      `고위직 명의의 공식 발표문이라며 공유되는 자료입니다. ${topic} 수석조정관 신원과 원문 확인이 필요합니다.`,
      `${topic} 수석조정관 명의의 지원 예산 중단 발표를 봤다는 게시물이 나왔습니다. 진위는 미확인입니다.`,
      `공식 발표라고 주장하는 문서가 공유됩니다. ${topic} 수석조정관 명의가 맞는지 확인되지 않았습니다.`,
    ];
    for (let w = 0; w < 4; w++) {
      const ago = (8 * 60 - 85 * w) * 1000;
      stage(`고위직 사칭 주장 반복 공동 공유 ${w + 1}/4`, Array.from({length: 6}, (_, i) =>
        post(`authority-${w}-${i}`, `authority_core_${i}`, ago - i * 1500,
          expressions[w], {url: `authority-circular-${w}`, ref: w === 0 ? 'origin' : undefined})));
    }
    stage('출처 확인을 요청하는 독립 계정', [
      post('authority-question', 'authority_reader_a', 44_000,
        `${topic}이 실제로 이런 공문을 발표했나요? 공식 홈페이지에서 원문을 찾지 못했습니다.`),
      post('authority-check', 'authority_reader_b', 42_000,
        '책임자 명의만으로는 확인할 수 없습니다. 게시물의 원문과 인증된 발표 채널을 대조해야 합니다.'),
    ]);
  }

  if (scenarioKey === 'cib_retreat') {
    const original = post('origin', 'unverified_source', 12 * 60_000,
      '누리공화국 방위대의 작전 명령이라며 전면 철수가 결정됐다는 문서 사진이 돌고 있습니다. 발령 기관과 원본 문서는 확인되지 않았습니다.',
      {url: 'military-claim-first'});
    stage('미확인 군사 명령 주장 최초 등장', [original]);
    let parent = 'origin';
    for (let depth = 1; depth <= 3; depth++) {
      const name = `military-chain-${depth}`;
      stage(`군사 명령 주장 인용 경로 ${depth}/3`, [
        post(name, `retreat_relay_${depth}`, (11 * 60 - depth * 35) * 1000,
          '전군 전면 철수 관련 작전 명령이 나왔다는 주장을 인용합니다. 공식 명령인지 독립적인 확인이 필요합니다.',
          {ref: parent, type: depth % 2 ? 'quotes' : 'reposts'})
      ]);
      parent = name;
    }
    for (let w = 0; w < 4; w++) {
      const ago = (8 * 60 - w * 85) * 1000;
      stage(`동일 계정 집합의 군사 주장 자료 증폭 ${w + 1}/4`, Array.from({length: 6}, (_, i) =>
        post(`retreat-${w}-${i}`, `retreat_core_${i}`, ago - i * 1400,
          `전군 전면 철수 관련 작전 명령 주장 자료 ${w + 1}이 다시 공유됩니다. 누리공화국 방위대 공식 채널의 확인은 없습니다.`,
          {url: `military-claim-${w}`, ref: w === 0 ? parent : undefined})));
    }
    stage('미확인 주장에 대한 확인 요청', [
      post('retreat-denial', 'retreat_observer', 32_000,
        '전군 철수 관련 작전 명령은 공식 확인 자료가 없습니다. 문서를 실제 명령으로 취급해서는 안 됩니다.'),
    ]);
  }

  if (scenarioKey === 'cib_emergency') {
    const original = post('origin', 'anonymous_bulletin', 12 * 60_000,
      '가온시 재난대응실의 긴급 공지라며 제3대피소가 폐쇄됐다는 게시물이 돌고 있습니다. 기관 공식 발표 여부는 아직 확인되지 않았습니다.',
      {url: 'emergency-first-bulletin'});
    stage('긴급 공지 사칭 주장 최초 등장', [original]);
    let parent = 'origin';
    for (let depth = 1; depth <= 4; depth++) {
      const name = `emergency-chain-${depth}`;
      stage(`긴급 공지 인용·재공유 경로 ${depth}/4`, [
        post(name, `emergency_relay_${depth}`, (11 * 60 - 28 * depth) * 1000,
          '제3대피소가 폐쇄됐다는 가온시 긴급 공지 주장이 퍼지고 있습니다. 공식 안내 여부를 확인 중입니다.',
          {ref: parent, type: depth % 2 ? 'quotes' : 'reposts'})
      ]);
      parent = name;
    }
    for (let w = 0; w < 6; w++) {
      const ago = (8 * 60 - 65 * w) * 1000;
      stage(`긴급 공지 자료 반복 공동 공유 ${w + 1}/6`, [
        post(`emergency-core-${w}-a`, 'emergency_core_a', ago,
          `가온시 제3대피소가 폐쇄됐다는 긴급 안내 자료 ${w + 1}을 공유합니다. 공식 기관 확인은 아직 없습니다.`,
          {url: `emergency-circular-${w}`}),
        post(`emergency-core-${w}-b`, 'emergency_core_b', ago - 1000,
          `가온시 제3대피소가 폐쇄됐다는 긴급 안내 자료 ${w + 1}을 공유합니다. 공식 기관 확인은 아직 없습니다.`,
          {url: `emergency-circular-${w}`}),
      ]);
    }
    const burst = Array.from({length: 18}, (_, i) => post(
      `emergency-amplifier-${i}`, `emergency_amp_${i}`, 52_000 - i * 1800,
      '가온시 대피소 폐쇄를 알리는 긴급 공지 주장을 원본 인용으로 전파합니다. 별도 확인이 필요합니다.',
      {ref: parent, type: i % 3 ? 'reposts' : 'quotes'}));
    stage('18개 계정의 긴급 공지 집중 확산 1/2', burst.slice(0, 9));
    stage('18개 계정의 긴급 공지 집중 확산 2/2', burst.slice(9));
    stage('독립적인 기관 확인 요청', [
      post('emergency-check', 'emergency_reader', 15_000,
        '대피소 폐쇄 공지의 발신 기관이 확인되지 않았습니다. 공식 재난 정보와 대조해야 합니다.'),
    ]);
  }

  return {batches, rootId: items.get('origin')?.id || null, totalPosts: batches.reduce((n, b) => n + b.posts.length, 0)};
}

export function beginCibScenario(posts, now = new Date(), scenarioKey = 'cib_burst') {
  const runId = randomUUID();
  const {batches, rootId, totalPosts} = buildCibPlan(scenarioKey, now, runId);
  const first = batches[0].posts;
  return {
    posts: [...first, ...posts],
    state: {
      status: 'running', mode: 'cib', scenarioKey,
      runId, rootId, startedAt: now.toISOString(),
      wave: 0, totalWaves: batches.length - 1, generatedCount: first.length,
      totalPosts, claimTarget: 0, quoteCount: 0, scenarioCount: 0,
      rootLikes: 0, error: null, waveIntervalMs: DELAY_MS,
      timingPolicy: 'accelerated-synthetic-timestamps',
      scheduledBatches: batches,
    },
  };
}

export function advanceCibScenario(posts, state, now = new Date()) {
  if (state.status !== 'running') return {posts, state};
  const next = state.wave + 1;
  const batch = state.scheduledBatches?.[next];
  if (!batch) throw new Error('시나리오 단계가 누락됐습니다. 테스트를 초기화하세요.');
  const updated = [...batch.posts, ...posts];
  // 화면 재게시 건수는 실제 원본 참조 게시물의 개수로 계산합니다.
  const refs = new Map();
  for (const p of updated) if (p.simulationRunId === state.runId && p.repostOf)
    refs.set(p.repostOf, (refs.get(p.repostOf) || 0) + 1);
  const all = updated.map(p => p.simulationRunId === state.runId
    ? {...p, reposts: refs.get(p.id) || 0} : p);
  const done = next >= state.totalWaves;
  return {
    posts: all,
    state: {...state, wave: next, generatedCount: state.generatedCount + batch.posts.length,
      quoteCount: [...refs.values()].reduce((a,b)=>a+b,0),
      status: done ? 'completed' : 'running', endedAt: done ? now.toISOString() : null,
      ...(done ? {scheduledBatches: []} : {})},
  };
}
