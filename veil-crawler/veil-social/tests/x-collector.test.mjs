import test from 'node:test';
import assert from 'node:assert/strict';
import {collectX,normalizeXResponse,mergeXPosts,emptyImportState,makeCollectionPlan} from '../x-collector.mjs';
const payload={data:[{id:'12345',author_id:'99',text:'API 변환 테스트용 문자열',created_at:'2026-10-10T01:00:00Z',lang:'ko',attachments:{media_keys:['m1']},public_metrics:{like_count:7}}],includes:{users:[{id:'99',username:'test_author',name:'테스트'}],media:[{media_key:'m1',type:'photo',url:'https://pbs.twimg.com/media/mock.jpg',width:400,height:200}]}};
test('X provenance, original timestamp and unknown truth survive normalization; duplicates merge',()=>{
  const result=normalizeXResponse(payload,'영화','2026-10-10T02:00:00Z');
  assert.equal(result[0].text,payload.data[0].text);
  assert.equal(result[0].source.url,'https://x.com/test_author/status/12345');
  assert.equal(result[0].source.truthStatus,'not_assessed');
  assert.equal(result[0].publishedAt,payload.data[0].created_at);
  assert.equal(result[0].images[0].url,payload.includes.media[0].url);
  assert.equal(mergeXPosts(result,result).length,1);
  const unsafe=structuredClone(payload);unsafe.includes.media[0].url='http://127.0.0.1/private';
  assert.equal(normalizeXResponse(unsafe,'영화','now')[0].images.length,0);
  unsafe.includes.users[0].protected=true;
  assert.equal(normalizeXResponse(unsafe,'영화','now').length,0);
});
test('missing token never makes a request',async()=>{
  let calls=0;
  await assert.rejects(collectX({fetchImpl:()=>{calls++;}}),{status:503});
  assert.equal(calls,0);
});
test('five bounded topic pages, checkpoints and no pagination',async()=>{
  let calls=0;
  const result=await collectX({token:'unit-test-token',plan:{targetCount:43,intervalMs:21*60*1000,mode:'latest'},pause:async()=>{},state:{...emptyImportState(),checkpoints:{영화:'100'}},fetchImpl:async url=>{
    calls++;assert.equal(url.origin,'https://api.x.com');assert.equal(url.searchParams.get('max_results'),'10');
    assert.ok(!url.searchParams.has('next_token'));if(calls===1)assert.equal(url.searchParams.get('since_id'),'100');
    return new Response(JSON.stringify({...payload,meta:{next_token:'ignored'}}),{status:200});
  }});
  assert.equal(calls,5);assert.equal(result.posts.length,1);assert.equal(result.state.checkpoints.영화,'12345');
});
test('429 stops without retries; partial success survives; reset deadline is honored',async()=>{
  let calls=0;const reset=Math.floor(Date.now()/1000)+3600;
  const result=await collectX({token:'unit-test-token',plan:{targetCount:43,intervalMs:21*60*1000,mode:'latest'},pause:async()=>{},fetchImpl:async()=>++calls===1?
    new Response(JSON.stringify(payload),{status:200}):new Response('{}',{status:429,headers:{'x-rate-limit-reset':String(reset)}})});
  assert.equal(calls,2);assert.equal(result.posts.length,1);assert.equal(result.state.status,'partial');
  assert.ok(Date.parse(result.state.nextAllowedAt)>=reset*1000);
});
test('zero remaining quota on successful response prevents the next topic request',async()=>{
  let calls=0;const result=await collectX({token:'unit-test-token',plan:{targetCount:43,intervalMs:21*60*1000,mode:'latest'},fetchImpl:async()=>{
    calls++;return new Response(JSON.stringify(payload),{headers:{'x-rate-limit-remaining':'0'}});
  }});
  assert.equal(calls,1);assert.equal(result.posts.length,1);
});

test('inclusive random bounds produce 43..56 posts and 21..26 minutes',()=>{
  assert.deepEqual(makeCollectionPlan('latest',min=>min),{targetCount:43,intervalMs:21*60*1000,mode:'latest'});
  assert.deepEqual(makeCollectionPlan('popular',(min,max)=>max-1),{targetCount:56,intervalMs:26*60*1000,mode:'popular'});
});
test('56 distinct results are capped by topic quotas; popular mode ignores latest checkpoints',async()=>{
  let serial=10000,calls=0;
  const result=await collectX({token:'unit-test-token',plan:{targetCount:56,intervalMs:26*60*1000,mode:'popular'},state:{...emptyImportState(),checkpoints:{영화:'999'}},pause:async()=>{},fetchImpl:async url=>{
    calls++;assert.equal(url.searchParams.get('sort_order'),'relevancy');assert.ok(!url.searchParams.has('since_id'));
    const data=Array.from({length:Number(url.searchParams.get('max_results'))},()=>({...payload.data[0],id:String(serial++)}));
    return new Response(JSON.stringify({...payload,data}));
  }});
  assert.equal(result.posts.length,56);assert.equal(calls,5);assert.equal(result.state.nextMode,'latest');assert.equal(result.state.checkpoints.영화,'999');
});
test('credential errors pause automatic collection rather than retrying',async()=>{
  const result=await collectX({token:'unit-test-token',plan:{targetCount:43,intervalMs:21*60*1000,mode:'latest'},fetchImpl:async()=>new Response('{}',{status:401})});
  assert.equal(result.state.pauseAutomation,true);assert.equal(result.state.requests,1);
});

test('next run is 21..26 minutes from run start, including request processing time',async()=>{
  const started=Date.parse('2026-10-10T01:00:00Z');let clock=started;
  const result=await collectX({token:'unit-test-token',plan:{targetCount:43,intervalMs:21*60*1000,mode:'latest'},now:()=>clock,pause:async()=>{clock+=2000;},fetchImpl:async()=>{clock+=500;return new Response(JSON.stringify(payload));}});
  assert.ok(clock>started);assert.equal(Date.parse(result.state.nextAllowedAt),started+21*60*1000);
});
