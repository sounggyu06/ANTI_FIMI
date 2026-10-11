import { randomUUID } from 'node:crypto';
import { createTemporalPlan } from './temporal.mjs';
import { readFileSync } from 'node:fs';
import { beginWartime, advanceWartime, advanceFastWartime } from './wartime.mjs';
import {CIB_KEYS, beginCibScenario, advanceCibScenario} from './cib-scenarios.mjs';

// Unpublished scenario content; never exposed before the start button is pressed.
const scenarioPostTemplates = JSON.parse(readFileSync(new URL('./data/scenario-posts.json', import.meta.url), 'utf8'));

export const WAVE_COUNT = 15;
export const WAVE_INTERVAL_MS = 4000;
export const FAST_WAVE_INTERVAL_MS = 750; // 15단계 × 0.75초 = 11.25초, 화면 갱신 시간도 확보합니다.
export const SCENARIO_IMAGES = [
  { url: '/media/relief-news.jpg', alt: '군인과 구호물품 사진 위에 속보·헬기 수송 중단 자막이 있는 이미지' },
  { url: '/media/relief-field.jpg', alt: '군인, 구호물품, 취소 안내판이 있는 현장 이미지' },
  { url: '/media/relief-camp.jpg', alt: '대피소 사람들과 구호활동 전면 취소 문구가 있는 이미지' },
];
export const emptySimulation = () => ({ status: 'idle', mode: 'normal', waveIntervalMs: WAVE_INTERVAL_MS, runId: null, rootId: null, startedAt: null, wave: 0, totalWaves: WAVE_COUNT, quoteCount: 0, scenarioCount: 0, rootLikes: 0, error: null });

// Synthetic statements and reactions; no external platform or AI calls.
const reactions = [
  ['ko', '이 취소 소식이 맞다면 한국과 APAC의 재난구호 협력이 흔들리는 것 아닌가요?'],
  ['ko', '삭제되기 전 공유하세요. 공동훈련 취소를 숨기면 국민이 준비할 시간이 없습니다.'],
  ['ko', '훈련 취소 주장의 출처는 이 링크뿐인가요? 원문과 발표 시각을 확인 중입니다.'],
  ['ko', '공식 일정은 예정대로입니다. 이 공동훈련 취소설은 공식 발표와 상충합니다.'],
  ['ko', '재난구호훈련이 취소됐다는 글을 봤습니다. 지역 구조 인력 지원에도 영향이 있을까요?'],
  ['ko', '공동훈련 취소설을 계기로 APAC 협력 예산을 공개적으로 검토했으면 합니다.'],
  ['ko', '공동훈련 취소설이 너무 빨라서 훈련 일정표보다 소문이 먼저 출동했네요.'],
  ['en', 'If this joint relief exercise was cancelled, how can Korea and APAC partners coordinate during a disaster?'],
  ['en', 'Share before this disappears: the joint relief exercise was cancelled and the public deserves answers.'],
  ['en', 'The joint exercise is proceeding as scheduled in the official notice. This cancellation claim needs verification.'],
  ['ja', '韓国とAPACの共同訓練が中止されたという投稿を見ました。災害対応への影響が心配です。'],
  ['ja', '共同訓練は予定どおりと案内されています。中止の話は公式発表と異なります。'],
];
const angles = {
  ko: ['지역 대응 계획도 살펴보겠습니다.', '다른 자료와 비교해 보고 싶습니다.', '발표 시점도 함께 확인하겠습니다.', '관련 기관 설명이 필요합니다.', '후속 소식을 지켜보겠습니다.'],
  en: ['I am watching local response plans.', 'I would like another source.', 'The timing also matters.', 'Partner agencies should clarify.', 'I will follow the updates.'],
  ja: ['地域の対応計画も気になります。', '別の資料とも比較したいです。', '発表時刻も確認します。', '関係機関の説明を待ちます。', '続報を見守ります。'],
};

function makePost(fields) {
  return { id: 'v-' + randomUUID(), verified: false, comments: 0, reposts: 0, likes: 0, repostOf: null, ...fields };
}

// The caller serializes these transitions and atomically persists the posts.
export function beginSimulation(posts, now = new Date(), mode = 'normal', temporalOptions = {}) {
  if (temporalOptions.scenarioKey === 'wartime') return beginWartime(posts,now,mode,temporalOptions);
  if (CIB_KEYS.includes(temporalOptions.scenarioKey)) return beginCibScenario(posts,now,temporalOptions.scenarioKey);
  const runId = randomUUID();
  const temporalPlan = createTemporalPlan({...temporalOptions, now});
  const link = `https://relief-brief.example/updates/${runId}`;
  const root = makePost({ simulationActorId: 'campaign_a', simulation_role: 'malicious_actor', authorId: 'scenario_campaign_a', name: '현장 소식 기록', handle: 'scenario_campaign_a', avatar: '현장', avatarColor: '#935264', language: 'ko',
    text: `대한민국과 APAC의 아스터 공동 재난구호훈련이 전면 취소됐습니다. 참여국 간 협력이 중단됐다는 내부 소식입니다. 삭제되기 전 공유하세요. ${link}`,
    publishedAt: temporalPlan.root.created_at, likes: 3, images: SCENARIO_IMAGES, simulationRunId: runId, scenario_id: runId, source_type: 'synthetic' });
  return { posts: [root, ...posts], state: { ...emptySimulation(), mode: mode === 'fast' ? 'fast' : 'normal',
    waveIntervalMs: mode === 'fast' ? FAST_WAVE_INTERVAL_MS : WAVE_INTERVAL_MS,
    status: 'running', runId, rootId: root.id, startedAt: now.toISOString(), rootLikes: root.likes, link, temporalPlan } };
}

/** 빠른 모드는 지연된 타이머가 있어도 경과 시간에 해당하는 단계를 한 번에 따라잡습니다. */
export function advanceFastSimulation(posts, state, now = new Date()) {
  if (state.scenarioKey === 'wartime') return advanceFastWartime(posts,state,now);
  if (CIB_KEYS.includes(state.scenarioKey)) return advanceCibScenario(posts,state,now);
  if (state.status !== 'running' || state.mode !== 'fast') return {posts,state};
  const start = Date.parse(state.startedAt);
  const targetWave = Math.min(WAVE_COUNT, Math.floor((now.getTime() - start) / FAST_WAVE_INTERVAL_MS));
  let result = {posts,state};
  while (result.state.wave < targetWave) {
    const nextTime = new Date(start + (result.state.wave + 1) * FAST_WAVE_INTERVAL_MS);
    result = advanceSimulation(result.posts, result.state, nextTime);
  }
  return result;
}

export function advanceSimulation(posts, state, now = new Date()) {
  if (state.scenarioKey === 'wartime') return advanceWartime(posts,state,now);
  if (CIB_KEYS.includes(state.scenarioKey)) return advanceCibScenario(posts,state,now);
  if (state.status !== 'running') return { posts, state };
  const root = posts.find(post => post.id === state.rootId);
  if (!root) throw new Error('시나리오 원문을 찾지 못했습니다. 테스트를 초기화하세요.');
  const wave = state.wave + 1;
  const quotes = Array.from({ length: 4 }, (_, offset) => {
    const index = state.quoteCount + offset;
    const descriptor = state.temporalPlan.quotes[index];
    const [language, opinion] = reactions[index % reactions.length];
    const suffix = angles[language][Math.floor(index / reactions.length)];
    return makePost({ simulationActorId: descriptor.actorId, authorId: 'scenario_' + descriptor.actorId, simulation_role: 'observer', name: ['지역 기록', '시민 메모', '현장 관찰', '정보 확인'][offset] + ' ' + (index + 1),
      handle: 'scenario_' + descriptor.actorId,
      avatar: String(index + 1).padStart(2, '0'), avatarColor: ['#426e9f', '#7f5d9b', '#397c75', '#94703b'][offset],
      language, text: `${opinion} ${suffix} ${state.link}`, publishedAt: descriptor.created_at,
      repostOf: state.rootId, referenceType: 'quotes', likes: 2 + index * 3, comments: index % 4, images: [SCENARIO_IMAGES[index % SCENARIO_IMAGES.length]], simulationRunId: state.runId, scenario_id: state.runId, source_type: 'synthetic' });
  });
  // Repost count reflects the actual number of persisted quote posts.
  const updatedRoot = { ...root, likes: 3 + wave * wave * 120, reposts: state.quoteCount + quotes.length };
  const template = scenarioPostTemplates[state.wave];
  // 원본 주장과 관련 후속 글을 두 행위자가 반복 작성합니다. 역할은 서버 내부에만 둡니다.
  const descriptor = state.temporalPlan.claims[state.wave];
  const actor = descriptor?.actorId;
  const scenarioPosts = template ? [{ ...template, id: 'v-' + randomUUID(),
    simulationActorId: actor, simulation_role: 'malicious_actor', authorId: 'scenario_' + actor,
    name: actor === 'campaign_a' ? '현장 소식 기록' : '지역 상황 기록', handle: 'scenario_' + actor,
    publishedAt: descriptor.created_at, repostOf: null, simulationRunId: state.runId, scenario_id: state.runId, source_type: 'synthetic' }] : [];
  return { posts: [...quotes.reverse(), ...scenarioPosts, ...posts.map(post => post.id === root.id ? updatedRoot : post)],
    state: { ...state, wave, quoteCount: updatedRoot.reposts, scenarioCount: (state.scenarioCount || 0) + scenarioPosts.length, rootLikes: updatedRoot.likes,
      status: wave === WAVE_COUNT ? 'completed' : 'running', endedAt: wave === WAVE_COUNT ? now.toISOString() : null } };
}

export function clearSimulation(posts) {
  return { posts: posts.filter(post => !post.simulationRunId), state: emptySimulation() };
}
