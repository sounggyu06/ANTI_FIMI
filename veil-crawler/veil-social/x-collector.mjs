import { randomInt } from 'node:crypto';
export const TOPICS = [
  {name:'영화', query:'(영화 OR cinema) -is:retweet -is:reply'},
  {name:'책', query:'(책추천 OR 독서 OR bookreview) -is:retweet -is:reply'},
  {name:'뉴스', query:'(뉴스 OR breakingnews) -is:retweet -is:reply'},
  {name:'시사', query:'(시사 OR 정책 OR APAC) -is:retweet -is:reply'},
  {name:'이슈', query:'(문화 OR 과학 OR technology) -is:retweet -is:reply'},
];
export function makeCollectionPlan(mode='latest', draw=randomInt) {
  return {targetCount:draw(43,57), intervalMs:draw(21*60,26*60+1)*1000, mode};
}
export const emptyImportState = () => ({status:'idle', imported:0, nextAllowedAt:null, checkpoints:{}, error:null, autoEnabled:false, nextMode:'latest'});
const count = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;

export function normalizeXResponse(response, topic, collectedAt) {
  const users = new Map((response.includes?.users || []).map(user => [user.id, user]));
  const media = new Map((response.includes?.media || []).map(item => [item.media_key, item]));
  return (response.data || []).flatMap(item => {
    const user = users.get(item.author_id);
    if (!/^\d{1,19}$/.test(item.id) || !user || user.protected || !/^[A-Za-z0-9_]{1,15}$/.test(user.username) ||
        typeof item.text !== 'string' || !item.text.trim() || !Number.isFinite(Date.parse(item.created_at))) return [];
    const originalUrl = `https://x.com/${user.username}/status/${item.id}`;
    const images = (item.attachments?.media_keys || []).flatMap(key => {
      const photo = media.get(key);
      if (photo?.type !== 'photo') return [];
      let url; try { url = new URL(photo.url); } catch { return []; }
      if (url.protocol !== 'https:' || url.hostname !== 'pbs.twimg.com') return [];
      return [{url:url.href, alt:photo.alt_text || 'X 원문 첨부 사진 · 대체 설명 미제공',
        width:count(photo.width) || 1408, height:count(photo.height) || 768,
        caption:'X 원문 사진 · 사진 주소로 표시', mediaKey:key}];
    });
    return [{id:`x-${item.id}`, name:user.name || user.username, handle:user.username,
      authorId:item.author_id, avatar:(user.name || user.username).slice(0,2).toUpperCase(), avatarColor:'#286c91',
      language:item.lang || 'und', text:item.note_tweet?.text || item.text, verified:Boolean(user.verified),
      publishedAt:item.created_at, likes:count(item.public_metrics?.like_count),
      reposts:count(item.public_metrics?.retweet_count), comments:count(item.public_metrics?.reply_count),
      repostOf:null, images, source:{platform:'x', name:'X 실제 게시물', url:originalUrl,
        publishedOn:item.created_at.slice(0,10), collectedAt, topic, truthStatus:'not_assessed'}}];
  });
}

export function mergeXPosts(existing, incoming) {
  const byId = new Map(existing.map(post => [post.id, post]));
  for (const post of incoming) byId.set(post.id, post);
  return [...byId.values()].sort((a,b) => Date.parse(b.publishedAt)-Date.parse(a.publishedAt));
}

// One bounded page per topic, no automatic pagination or retry, and no image downloads.
export async function collectX({token, state=emptyImportState(), fetchImpl=fetch,
  plan=makeCollectionPlan(state.nextMode || 'latest'),
  pause=ms=>new Promise(resolve=>setTimeout(resolve,ms)), now=()=>Date.now()}) {
  if (!token) throw Object.assign(new Error('X API가 연결되지 않았습니다. 서버의 .env에 X_BEARER_TOKEN을 설정한 뒤 재시작하세요.'),{status:503});
  if (!Number.isInteger(plan.targetCount) || plan.targetCount<43 || plan.targetCount>56 ||
      plan.intervalMs<21*60*1000 || plan.intervalMs>26*60*1000 || !['latest','popular'].includes(plan.mode)) throw new Error('Invalid collection plan');
  const startedAt=now();
  const posts = [], checkpoints = {...state.checkpoints};
  let rateResetAt = 0, error = null, requests = 0, pauseAutomation = false;
  const accepted = new Set();
  for (const [index,topic] of TOPICS.entries()) {
    const quota=Math.floor(plan.targetCount/TOPICS.length)+(index<plan.targetCount%TOPICS.length?1:0);
    const url = new URL('https://api.x.com/2/tweets/search/recent');
    url.searchParams.set('query', topic.query);
    url.searchParams.set('max_results',String(Math.max(10,quota)));
    url.searchParams.set('sort_order',plan.mode==='popular'?'relevancy':'recency');
    url.searchParams.set('tweet.fields','created_at,author_id,lang,public_metrics,attachments,note_tweet');
    url.searchParams.set('expansions','author_id,attachments.media_keys');
    url.searchParams.set('user.fields','name,username,verified,protected');
    url.searchParams.set('media.fields','media_key,type,url,width,height,alt_text');
    if (plan.mode==='latest' && checkpoints[topic.name]) url.searchParams.set('since_id', checkpoints[topic.name]);
    let response;
    try {
      requests++;
      response = await fetchImpl(url,{headers:{Authorization:`Bearer ${token}`}, signal:AbortSignal.timeout(15000), redirect:'error'});
    } catch { error='X 응답을 받지 못해 수집을 중단했습니다. 자동 재시도하지 않습니다.'; break; }
    const quotaExhausted = response.headers.get('x-rate-limit-remaining') === '0';
    const reset = Number(response.headers.get('x-rate-limit-reset')) * 1000;
    if (response.status === 429 || quotaExhausted) rateResetAt = Math.max(rateResetAt,Number.isFinite(reset)?reset:0);
    if (!response.ok) {
      pauseAutomation=[400,401,402,403,404].includes(response.status);
      error = response.status === 429 ? 'X 요청 한도에 도달해 중단했습니다.' : `X가 수집을 허용하지 않았습니다 (HTTP ${response.status}). 권한·이용 잔액을 확인하세요.`;
      break;
    }
    let payload;
    try { payload = await response.json(); } catch { error='X 응답 형식 오류로 중단했습니다.'; break; }
    if (!payload || (payload.data !== undefined && !Array.isArray(payload.data))) { error='X 응답 형식 오류로 중단했습니다.'; break; }
    const normalized = normalizeXResponse(payload,topic.name,new Date(now()).toISOString());
    const selected=normalized.filter(post=>!accepted.has(post.id)).slice(0,quota);
    for(const post of selected){accepted.add(post.id);post.source.selectionMode=plan.mode;posts.push(post);}
    if (plan.mode==='latest' && selected.length) checkpoints[topic.name] = selected.map(post=>post.id.slice(2)).reduce((a,b)=>BigInt(a)>BigInt(b)?a:b);
    if (payload.errors?.length) { error='일부 데이터에 접근할 수 없어 추가 수집을 중단했습니다.'; break; }
    if (quotaExhausted) { error='X 요청 잔여 한도가 없어 추가 수집을 중단했습니다.'; break; }
    if (topic !== TOPICS.at(-1)) await pause(2000);
  }
  return {posts:mergeXPosts([],posts), state:{...state,status:error?'partial':'completed', imported:posts.length,
    targetCount:plan.targetCount, intervalMs:plan.intervalMs, mode:plan.mode, nextMode:plan.mode==='latest'?'popular':'latest',
    pauseAutomation,requests,checkpoints,nextAllowedAt:new Date(Math.max(startedAt+plan.intervalMs,now(),rateResetAt)).toISOString(),
    collectedAt:new Date(now()).toISOString(),error}};
}
