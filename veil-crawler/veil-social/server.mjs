import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { beginSimulation, advanceSimulation, advanceFastSimulation, clearSimulation, emptySimulation, WAVE_INTERVAL_MS } from './simulation.mjs';
import { collectX, mergeXPosts, emptyImportState, makeCollectionPlan } from './x-collector.mjs';
import { PostArchive,archiveDirectory } from './archive.mjs';
import { CollectionScheduler } from './x-scheduler.mjs';
import { cacheImages } from './media-cache.mjs';
import { renderPostsHtml } from './posts-html.mjs';
import { importLocalDirectory } from './local-import.mjs';
import { prepareStartup } from './startup.mjs';
import { Anonymizer } from './anonymizer.mjs';
import { TEMPORAL_PATTERNS } from './temporal.mjs';

const root = path.dirname(fileURLToPath(import.meta.url));
try { process.loadEnvFile(path.join(root,'.env')); } catch (error) { if(error.code !== 'ENOENT') throw error; }
const port = Number(process.env.PORT || 5173);
const archive=new PostArchive(archiveDirectory());
try { process.loadEnvFile(path.join(archive.directory,'.env')); } catch(error) { if(error.code!=='ENOENT')throw error; }
const dataDirectory = process.env.VEIL_DATA_DIR || path.join(archive.directory,'runtime');
await fs.mkdir(dataDirectory,{recursive:true});
for(const name of ['posts.json','simulation.json','x-import-state.json']){
  try{await fs.access(path.join(dataDirectory,name));}
  catch{
    try{await fs.copyFile(path.join(root,'data',name),path.join(dataDirectory,name));}
    catch(error){if(error.code!=='ENOENT')throw error;if(name==='posts.json')await fs.writeFile(path.join(dataDirectory,name),'[]');}
  }
}
const postsFile = path.join(dataDirectory, 'posts.json');
const simulationFile = path.join(dataDirectory, 'simulation.json');
const importFile = path.join(dataDirectory,'x-import-state.json');
let importState = emptyImportState(), collecting = false;
try { importState = {...importState,...JSON.parse(await fs.readFile(importFile,'utf8'))}; }
catch(error) { if(error.code !== 'ENOENT') throw error; }
importState={...importState,...archive.getSetting('import',{})};
if(importState.status==='running') importState={...importState,status:'interrupted',error:'서버 재시작으로 수집이 중단됐습니다.'};
// 배포본에 함께 넣은 사용자 수집 자료를 최초 실행에 이식하고 이후에는 재사용합니다.
const localDirectory=path.join(root,'data','imported-x');
try {
  await fs.access(localDirectory);
  const imported=await importLocalDirectory(localDirectory,archive);
  importState={...importState,...archive.getSetting('import',{})};
  console.log(`Local X data: ${imported.posts} posts, ${imported.photos} photos${imported.alreadyImported?' (saved)':''}`);
} catch(error) { if(error.code!=='ENOENT') throw error; }
const legacyPosts=JSON.parse(await fs.readFile(postsFile,'utf8')).filter(post=>post.source?.platform==='x');
if(archive.count()===0 && legacyPosts.length)importState=archive.saveBatch(legacyPosts,importState);
const mime = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.json':'application/json; charset=utf-8','.webp':'image/webp','.gif':'image/gif'};
let writeQueue=Promise.resolve();
let simulation = emptySimulation();
let simulationTimer;
async function atomicJson(filename, data) {
  const temporary = filename + '.tmp';
  await fs.writeFile(temporary, JSON.stringify(data, null, 2));
  await fs.rename(temporary, filename);
}
function mutate(change) {
  const operation = writeQueue.then(async () => {
    const posts = JSON.parse(await fs.readFile(postsFile, 'utf8'));
    const result = change(posts, simulation);
    await atomicJson(postsFile, result.posts);
    simulation = result.state;
    await atomicJson(simulationFile, simulation);
    return result;
  });
  writeQueue = operation.catch(() => {});
  return operation;
}
function withArchive(posts){return mergeXPosts(posts.filter(post=>post.source?.platform!=='x'),archive.latest(200));}
await mutate(posts=>prepareStartup(posts,archive.latest(200)));
const anonymizer = new Anonymizer(path.join(archive.directory, 'anonymized_users.json'));
const demoUser = anonymizer.register({id:'demo',authorId:'demo_user',handle:'demo_user',name:'Demo Analyst'});
anonymizer.save();
async function publicPosts() {
  const current = JSON.parse(await fs.readFile(postsFile, 'utf8'));
  const seen = new Set(current.map(post => post.id));
  // 프로필에는 200개 화면 제한 밖의 기존 작성 이력도 모두 포함합니다. 저장본을 복제하지 않습니다.
  const additional = [...archive.records()].filter(post => !seen.has(post.id));
  return anonymizer.project([...current, ...additional]);
}
function publicSimulation() {
  const {status,mode,waveIntervalMs,startedAt,wave,totalWaves,quoteCount,scenarioCount,rootLikes,error,endedAt} = simulation;
  return {status,mode,waveIntervalMs,startedAt,wave,totalWaves,quoteCount,scenarioCount,rootLikes,error,endedAt,
    temporalPattern:simulation.temporalPlan?.pattern || null,
    eventAt:simulation.scenarioKey==='wartime'||simulation.scenarioKey?.startsWith('cib_')?simulation.startedAt:simulation.temporalPlan?.event_at || null,
    timingPolicy:simulation.timingPolicy || 'historical-pattern',
    rootId: anonymizer.postId(simulation.rootId), scenarioKey:simulation.scenarioKey || 'relief',
    generatedCount:simulation.generatedCount ?? (simulation.runId?1+quoteCount+scenarioCount:0),
    totalPosts:simulation.totalPosts || 73};
}
await publicPosts();
function saveImportState(){archive.setSetting('import',importState);}
async function runImport(){
  if(!process.env.X_BEARER_TOKEN)throw Object.assign(new Error('X API 미연결 · X 개발자 앱의 토큰이 필요합니다.'),{status:503});
  if(collecting)throw Object.assign(new Error('이미 수집 중입니다.'),{status:409});
  if(Date.parse(importState.nextAllowedAt)>Date.now())throw Object.assign(new Error('다음 수집 시각까지 기다려주세요.'),{status:429});
  collecting=true;scheduler.stop();
  const plan=makeCollectionPlan(importState.nextMode || 'latest');
  try{
    importState={...importState,status:'running',error:null,targetCount:plan.targetCount,mode:plan.mode,nextAllowedAt:new Date(Date.now()+plan.intervalMs).toISOString()};
    saveImportState();
    const result=await collectX({token:process.env.X_BEARER_TOKEN,state:importState,plan});
    result.state.photoCache=await cacheImages(result.posts,path.join(archive.directory,'media'));
    // Persist source records before updating the replaceable screen feed.
    importState=archive.saveBatch(result.posts,{...result.state,autoEnabled:importState.autoEnabled&&!result.state.pauseAutomation});
    await mutate((posts,state)=>({posts:withArchive(posts),state}));
    return publicImportState();
  }catch(error){
    importState={...importState,status:'failed',autoEnabled:false,error:'수집 또는 저장 오류로 자동 수집을 중지했습니다.'};
    try{saveImportState();}catch{}
    throw error;
  }finally{collecting=false;scheduler.schedule();}
}
function publicImportState(){
  const {checkpoints,...state}=importState;
  return {...state,configured:Boolean(process.env.X_BEARER_TOKEN),totalSaved:archive.count(),visibleSaved:Math.min(200,archive.count())};
}
const scheduler=new CollectionScheduler({run:runImport,getState:()=>importState,configured:()=>Boolean(process.env.X_BEARER_TOKEN)});
let timerGeneration=0;
function stopTimer() { timerGeneration++; clearTimeout(simulationTimer); simulationTimer = undefined; }
function startTimer() {
  stopTimer();
  const generation=timerGeneration,runId=simulation.runId;
  const schedule=()=>{
    if(generation!==timerGeneration||simulation.status!=='running'||simulation.runId!==runId)return;
    const delay=simulation.scenarioKey==='wartime'
      ?Math.max(0,Date.parse(simulation.nextPostAt)-Date.now()):simulation.waveIntervalMs || WAVE_INTERVAL_MS;
    simulationTimer=setTimeout(tick,delay);
  };
  const tick=async()=>{
    if(generation!==timerGeneration)return;
    try {
      await mutate((posts,state)=>generation!==timerGeneration||state.runId!==runId
        ?{posts,state}:state.mode==='fast'?advanceFastSimulation(posts,state):advanceSimulation(posts,state));
      if(generation!==timerGeneration)return;
      if (simulation.status !== 'running') stopTimer();else schedule();
    } catch {
      if(generation!==timerGeneration)return;
      stopTimer();
      simulation = { ...simulation, status: 'stopped', error: '게시물 저장 오류로 확산이 중지됐습니다.' };
      await atomicJson(simulationFile, simulation).catch(() => {});
    }
  };
  schedule();
}
function json(res,status,data){res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(JSON.stringify(data));}
const server=http.createServer(async(req,res)=>{
  try{
    const url=new URL(req.url,'http://localhost');
    if(url.pathname==='/api/health'&&req.method==='GET')return json(res,200,{app:'veil-social',sessionId:process.env.VEIL_SESSION_ID||null});
    if(url.pathname==='/api/import/x'&&req.method==='GET')return json(res,200,publicImportState());
    if(url.pathname==='/api/archive/x/export'&&req.method==='GET'){
      res.writeHead(200,{'Content-Type':'application/x-ndjson; charset=utf-8','Content-Disposition':'attachment; filename="x-posts.jsonl"','Cache-Control':'no-store'});
      try{for(const post of anonymizer.project([...archive.records()]))if(!res.write(JSON.stringify(post)+'\n'))await new Promise((resolve,reject)=>{const done=()=>{cleanup();resolve();};const closed=()=>{cleanup();reject(new Error('Export closed'));};const cleanup=()=>{res.off('drain',done);res.off('close',closed);};res.once('drain',done);res.once('close',closed);});res.end();}catch{res.destroy();}
      return;
    }
    if(['/api/import/x','/api/import/x/enable','/api/import/x/disable','/api/archive/x/restore'].includes(url.pathname)&&req.method==='POST'){
      if(req.headers['x-veil-client']!=='demo')return json(res,403,{error:'Missing demo client header'});
      if(url.pathname==='/api/archive/x/restore'){
        await mutate((posts,state)=>({posts:withArchive(posts),state}));return json(res,200,publicImportState());
      }
      if(url.pathname.endsWith('/disable')){
        importState={...importState,autoEnabled:false};saveImportState();scheduler.stop();return json(res,200,publicImportState());
      }
      if(url.pathname.endsWith('/enable')){
        if(!process.env.X_BEARER_TOKEN)return json(res,503,{error:'일반 X 로그인 정보로 연결할 수 없습니다. X 개발자 앱의 API 토큰이 필요합니다.'});
        importState={...importState,autoEnabled:true};saveImportState();scheduler.schedule();return json(res,200,publicImportState());
      }
      try{return json(res,200,await runImport());}catch(error){return json(res,error.status || 500,{error:error.status?error.message:importState.error});}
    }
    if(url.pathname==='/api/simulation'&&req.method==='GET')return json(res,200,publicSimulation());
    if(['/api/simulation/start','/api/simulation/start-fast','/api/simulation/start-continuous','/api/simulation/stop','/api/simulation/reset'].includes(url.pathname)&&req.method==='POST'){
      if(req.headers['x-veil-client']!=='demo')return json(res,403,{error:'Missing demo client header'});
      if(['/api/simulation/start','/api/simulation/start-fast','/api/simulation/start-continuous'].includes(url.pathname)){
        try {
          let body='';
          for await(const chunk of req){body+=chunk;if(body.length>2048)throw Object.assign(new Error('요청이 너무 큽니다.'),{status:413});}
          let options;
          try{options=body?JSON.parse(body):{};}catch{throw Object.assign(new Error('JSON 요청을 확인하세요.'),{status:400});}
          const pattern=options?.pattern || 'auto';
          if(pattern!=='auto'&&!TEMPORAL_PATTERNS.includes(pattern))throw Object.assign(new Error('지원하지 않는 시간 패턴입니다.'),{status:400});
          const scenarioKey=options?.scenarioKey || 'relief';
          if(!['relief','wartime','cib_burst','cib_repeat','cib_cascade','cib_authority','cib_retreat','cib_emergency'].includes(scenarioKey))throw Object.assign(new Error('지원하지 않는 시나리오입니다.'),{status:400});
          const mode=url.pathname.endsWith('/start-fast')?'fast':url.pathname.endsWith('/start-continuous')?'continuous':'normal';
          if(mode==='continuous'&&scenarioKey!=='wartime')throw Object.assign(new Error('반복 생성은 전시 복합 위기에서 선택하세요.'),{status:400});
          await mutate((posts,state)=>{
            if(state.status!=='idle')throw Object.assign(new Error('먼저 테스트 초기화를 눌러주세요.'),{status:409});
            return beginSimulation(posts,new Date(),mode,{pattern,scenarioKey});
          });
        } catch(error) { if(error.status)return json(res,error.status,{error:error.message});throw error; }
        startTimer();
      }else{
        stopTimer();
        await mutate(url.pathname.endsWith('/reset')?clearSimulation:(posts,state)=>({posts,state:{...state,status:state.status==='running'?'stopped':state.status}}));
      }
      return json(res,200,publicSimulation());
    }
    if(url.pathname==='/posts'&&req.method==='GET'){
      const posts=await publicPosts();
      res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});
      res.end(renderPostsHtml(posts));
      return;
    }
    if(url.pathname==='/api/posts'&&req.method==='GET'){
      return json(res,200,await publicPosts());
    }
    if(url.pathname==='/api/posts'&&req.method==='POST'){
      if(req.headers['x-veil-client']!=='demo')return json(res,403,{error:'Missing demo client header'});
      let body='';
      for await(const chunk of req){body+=chunk;if(body.length>10000)return json(res,413,{error:'본문이 너무 깁니다.'});}
      const input=JSON.parse(body);
      if(typeof input.text!=='string'||!input.text.trim()||input.text.length>280)return json(res,400,{error:'1~280자의 본문을 입력하세요.'});
      const post={id:'v-'+randomUUID(),name:'Demo Analyst',handle:'demo_user',avatar:'DU',avatarColor:'#286c91',language:['ko','en','ja'].includes(input.language)?input.language:'ko',text:input.text.trim(),verified:false,publishedAt:new Date().toISOString(),comments:0,reposts:0,likes:0,repostOf:null};
      await mutate((posts,state)=>({posts:[post,...posts],state}));
      return json(res,201,anonymizer.project([post])[0]);
    }
    if(url.pathname==='/api/me' && req.method==='GET')return json(res,200,anonymizer.publicUser(demoUser));
    if(url.pathname.startsWith('/api/profiles/') && req.method==='GET') {
      const id=url.pathname.slice('/api/profiles/'.length);
      if(!/^anon_\d{4,}$/.test(id))return json(res,404,{error:'Profile not found'});
      const profile=anonymizer.profile(id,await publicPosts());
      return profile ? json(res,200,profile) : json(res,404,{error:'Profile not found'});
    }
    if(req.method!=='GET')return json(res,405,{error:'Method not allowed'});
    if(url.pathname.startsWith('/archive-media/')){
      const name=url.pathname.slice('/archive-media/'.length);
      if(!/^[a-f0-9]{64}\.(jpg|png|webp|gif)$/.test(name))return json(res,404,{error:'Not found'});
      try{const data=await fs.readFile(path.join(archive.directory,'media',name));res.writeHead(200,{'Content-Type':mime[path.extname(name)],'X-Content-Type-Options':'nosniff'});res.end(data);}
      catch{return json(res,404,{error:'Photo unavailable'});}
      return;
    }
    // Serve only the built public UI. Evaluation labels and seed files remain private.
    const profileRoute=url.pathname.startsWith('/profile/');
    const profileMatch=/^\/profile\/(anon_\d{4,})\/?$/.exec(url.pathname);
    const profileExists=profileMatch && Boolean(anonymizer.byId.get(profileMatch[1]));
    const relative=(url.pathname==='/' || profileRoute)?'index.html':decodeURIComponent(url.pathname).replace(/^\//,'');
    const dist=path.join(root,'dist');
    const filename=path.resolve(dist,relative);
    if(!filename.startsWith(dist+path.sep))return json(res,403,{error:'Forbidden'});
    try{const data=await fs.readFile(filename);res.writeHead(profileRoute && !profileExists ? 404 : 200,{'Content-Type':mime[path.extname(filename)]||'application/octet-stream','X-Content-Type-Options':'nosniff'});res.end(data)}
    catch{return json(res,404,{error:'Not found. Run npm run build first.'})}
  }catch{return json(res,500,{error:'로컬 시연 서버 오류'})}
});
server.listen(port,'127.0.0.1',()=>{console.log(`VEIL Social: http://127.0.0.1:${port}`);scheduler.schedule();});
