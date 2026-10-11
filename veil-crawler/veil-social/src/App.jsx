import React, { useState, useMemo, useEffect, useCallback, useLayoutEffect, useRef } from "react";
import {Home,Search,Bell,Mail,UserRound,Settings,Bookmark,ShieldCheck,RadioTower,Menu,X,Send,Globe2,ChevronLeft,ChevronRight} from 'lucide-react';
import './App.css';
import Avatar from './Avatar';
import Post from './Post';
import Profile from './Profile';
import { postsByUser, profileIdFromPath, isAnonymousPost } from './post-utils.mjs';

const initialPosts=[];
const trends=[['대한민국 · 실시간','#연합훈련','2,431'],['Technology · Trending','#OSINT','1,892'],['Security · Trending','#FIMI','943'],['Japan · Trending','#情報検証','621']];
const nav=[['홈',Home],['탐색',Search],['알림',Bell],['메시지',Mail],['북마크',Bookmark],['프로필',UserRound],['설정',Settings]];
export default function App(){
 const [posts,setPosts]=useState(initialPosts),[draft,setDraft]=useState(''),[language,setLanguage]=useState('all'),[search,setSearch]=useState(''),[tab,setTab]=useState('추천'),[active,setActive]=useState(()=>window.location.pathname.startsWith('/profile/')?'프로필':'홈'),[menu,setMenu]=useState(false),[error,setError]=useState('');
 const [profileRoute,setProfileRoute]=useState(()=>window.location.pathname.startsWith('/profile/'));
 const [profileId,setProfileId]=useState(()=>profileIdFromPath(window.location.pathname));
 const [profileUser,setProfileUser]=useState(null),[profileStatus,setProfileStatus]=useState('loading'),[me,setMe]=useState(null);
 function home(){window.history.pushState(null,'','/');setProfileRoute(false);setProfileId(null);setActive('홈');setMenu(false);window.scrollTo(0,0)}
 function openProfile(event,id){
   if(event && (event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey))return;
   event?.preventDefault();window.history.pushState(null,'','/profile/'+id);setProfileRoute(true);setProfileId(id);setActive('프로필');setMenu(false);setFocusedId(null);window.scrollTo(0,0);
 }
 useEffect(()=>{
   const change=()=>{setProfileRoute(window.location.pathname.startsWith('/profile/'));setProfileId(profileIdFromPath(window.location.pathname));setActive(window.location.pathname.startsWith('/profile/')?'프로필':'홈')};
   window.addEventListener('popstate',change);return()=>window.removeEventListener('popstate',change);
 },[]);
 useEffect(()=>{
   if(!profileRoute)return;
   let cancelled=false,timer;setProfileUser(null);setProfileStatus('loading');
   async function load(){
     try{
       if(!profileId){if(!cancelled)setProfileStatus('missing');return}
       const response=await fetch('/api/profiles/'+profileId);
       if(response.status===404){if(!cancelled){setProfileUser(null);setProfileStatus('missing')}return}
       if(!response.ok)throw new Error('profile');
       const user=await response.json();if(!cancelled){setProfileUser(user);setProfileStatus('ready')}
     }catch{if(!cancelled)setProfileStatus('error')}
     finally{if(!cancelled)timer=setTimeout(load,2000)}
   }
   load();return()=>{cancelled=true;clearTimeout(timer)};
 },[profileRoute,profileId]);
 const [temporalPattern,setTemporalPattern]=useState('auto');
 const [scenarioKey,setScenarioKey]=useState('wartime');
 const [simulation,setSimulation]=useState({status:'idle',wave:0,totalWaves:15,quoteCount:0,rootLikes:0}),[busy,setBusy]=useState(false);
 const pollDelay=useRef(2000);
 const refresh=useCallback(async()=>{
   const [feedResponse,stateResponse,meResponse]=await Promise.all([fetch('/api/posts'),fetch('/api/simulation'),fetch('/api/me')]);
   if(!feedResponse.ok||!stateResponse.ok)throw new Error('게시물 서버에 연결할 수 없습니다.');
   const [feed,state]=await Promise.all([feedResponse.json(),stateResponse.json()]);
   if(!Array.isArray(feed)||!feed.every(isAnonymousPost)){
     setPosts([]);
     throw new Error('최신 익명화 서버로 다시 실행해주세요. 기존 웹을 종료하고 run_web.py를 실행하세요.');
   }
   setPosts(previous=>{const local=new Map(previous.map(p=>[p.id,p]));return feed.map(p=>{const before=local.get(p.id);return {...p,liked:before?.liked||false,reposted:before?.reposted||false,bookmarked:before?.bookmarked||false,likes:p.likes+(before?.liked?1:0),reposts:p.reposts+(before?.reposted?1:0)}})});
   pollDelay.current=state.status==='running'&&(state.scenarioKey==='wartime'||state.scenarioKey?.startsWith('cib_'))?250:2000;
   setSimulation(state);
   if(meResponse.ok)setMe(await meResponse.json());
 },[]);
 useEffect(()=>{
   let cancelled=false,timer;
   async function poll(){try{await refresh();if(!cancelled)setError('')}catch(error){if(!cancelled)setError(error.message||'게시물 서버에 연결할 수 없습니다. run_web.py로 서버를 실행하세요.')}finally{if(!cancelled)timer=setTimeout(poll,pollDelay.current)}}
   poll();return()=>{cancelled=true;clearTimeout(timer)};
 },[refresh]);
 async function controlSimulation(action){
   setBusy(true);setError('');
   try{
     const response=await fetch('/api/simulation/'+action,{method:'POST',headers:{'X-Veil-Client':'demo','Content-Type':'application/json'},body:JSON.stringify({pattern:temporalPattern,scenarioKey})});
     const result=await response.json();if(!response.ok)throw new Error(result.error||'시나리오 요청에 실패했습니다.');
     setSimulation(result);
     if(['start','start-fast','start-continuous'].includes(action)){home();setSearch('');setLanguage('all');setTab('추천')}
     await refresh();
   }catch(error){setError(error.message)}finally{setBusy(false)}
 }
 const [imagePreview,setImagePreview]=useState(null);
 const imageDialog=useRef(null);
 const hasImagePreview=Boolean(imagePreview);
 useEffect(()=>{
   if(!hasImagePreview)return;
   const dialog=imageDialog.current,previousOverflow=document.body.style.overflow;
   dialog.showModal();document.body.style.overflow='hidden';
   return()=>{dialog.close();document.body.style.overflow=previousOverflow};
 },[hasImagePreview]);
 const openImage=(images,index)=>setImagePreview({images,index});
 function moveImage(direction){setImagePreview(current=>current?{...current,index:(current.index+direction+current.images.length)%current.images.length}:null)}
 const byId=useMemo(()=>new Map(posts.map(p=>[p.id,p])),[posts]);
 const origin=byId.get(simulation.rootId);
 const selectedScenario=simulation.status==='idle'?scenarioKey:(simulation.scenarioKey||'relief');
 const isWartime=selectedScenario==='wartime';
 const isCib=selectedScenario.startsWith('cib_');
 const cibTitles={cib_burst:'실험 1 · 단발성 동시 확산',cib_repeat:'실험 2 · 반복 계정 공조',cib_cascade:'실험 3 · 다단계 조직적 증폭',cib_authority:'실험 4 · 고위직 사칭 주장',cib_retreat:'실험 5 · 미확인 후퇴 명령 주장',cib_emergency:'실험 6 · 긴급 공지 사칭·증폭'};
 const scenarioTitle=cibTitles[selectedScenario]||(isWartime?'전시 복합 위기 · 남공화국과 북공화국':'대한민국 · APAC 재난구호 협력');

 const filtered=useMemo(()=>posts.filter(p=>(language==='all'||p.language===language)&&(!search||`${p.text} ${p.name} ${p.handle}`.toLowerCase().includes(search.toLowerCase()))&&tab==='추천'),[posts,language,search,tab]);
 const profilePosts=useMemo(()=>postsByUser(posts,profileId),[posts,profileId]);
 const appRef=useRef(null),headerRef=useRef(null);
 const [focusedId,setFocusedId]=useState(null);
 const [focusRequest,setFocusRequest]=useState(()=>{
   try { const id=decodeURIComponent(window.location.hash.slice(1));return id?{id}:null } catch { return null }
 });
 // Measure the sticky header instead of assuming the same height at every width.
 useLayoutEffect(()=>{
   const header=headerRef.current;
   const updateOffset=()=>appRef.current?.style.setProperty('--post-scroll-offset',`${header.getBoundingClientRect().height+12}px`);
   updateOffset();
   const observer=new ResizeObserver(updateOffset);observer.observe(header);
   return()=>observer.disconnect();
 },[]);
 useLayoutEffect(()=>{
   if(!focusRequest)return;
   const element=document.getElementById(focusRequest.id);
   if(!element?.hasAttribute('data-post-id'))return;
   setFocusedId(focusRequest.id);
   element.focus({preventScroll:true});
   element.scrollIntoView({block:'start',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
   setFocusRequest(null);
 },[focusRequest,filtered]);
 const requestPostFocus=useCallback(id=>{
   setProfileRoute(false);setProfileId(null);setSearch('');setLanguage('all');setTab('추천');setActive('홈');setMenu(false);
   setFocusRequest({id});
 },[]);
 useEffect(()=>{
   const handleHash=()=>{try{const id=decodeURIComponent(window.location.hash.slice(1));if(id)requestPostFocus(id)}catch{}};
   window.addEventListener('hashchange',handleHash);
   return()=>window.removeEventListener('hashchange',handleHash);
 },[requestPostFocus]);
 function navigateToPost(event,id){
   if(event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
   event.preventDefault();
   window.history.pushState(null,'',`/#${encodeURIComponent(id)}`);
   requestPostFocus(id);
 }
 const update=(id,fn)=>setPosts(ps=>ps.map(p=>p.id===id?fn(p):p));
 const like=id=>update(id,p=>({...p,liked:!p.liked,likes:p.likes+(p.liked?-1:1)}));
 const repost=id=>update(id,p=>({...p,reposted:!p.reposted,reposts:p.reposts+(p.reposted?-1:1)}));
 const bookmark=id=>update(id,p=>({...p,bookmarked:!p.bookmarked}));
 async function publish(){if(!draft.trim())return;try{const res=await fetch('/api/posts',{method:'POST',headers:{'Content-Type':'application/json','X-Veil-Client':'demo'},body:JSON.stringify({text:draft.trim(),language:'ko'})});if(!res.ok)throw new Error('publish');const post=await res.json();if(!isAnonymousPost(post))throw new Error('익명화 서버 재시작 필요');setPosts(ps=>[{...post,liked:false,reposted:false,bookmarked:false},...ps]);setDraft('');setSearch('');setLanguage('all');setTab('추천');setError('')}catch{setError('게시물을 저장하지 못했습니다. 시연 서버를 확인하세요.')}}
 const renderPost=p=><Post key={p.id} post={p} original={byId.get(p.repostOf)} focused={focusedId===p.id} onNavigate={navigateToPost} onProfile={openProfile} onOpenImage={openImage} onLike={like} onRepost={repost} onBookmark={bookmark}/>;
 return <div className="app" ref={appRef}><div className="mobile-top"><button onClick={()=>setMenu(!menu)} aria-label="메뉴">{menu?<X/>:<Menu/>}</button><strong>◈ VEIL Social</strong><small>SIMULATION</small></div><div className="layout"><aside className={'sidebar '+(menu?'open':'')}><div className="brand"><span>◈</span><b>VEIL Social</b></div><nav>{nav.map(([label,Icon])=><button key={label} className={'nav '+(active===label?'selected':'')} onClick={()=>{if(label==='홈'){home();return}if(label==='프로필'&&me){openProfile(null,me.anonymous_user_id);return}setActive(label);setMenu(false);if(label==='탐색'){home();document.getElementById('search')?.focus()}}}><Icon size={24}/><span>{label}</span></button>)}</nav><button className="post-btn" onClick={()=>{home();requestAnimationFrame(()=>document.getElementById('composer')?.focus())}}>게시하기</button><a className="profile" href={me?"/profile/"+me.anonymous_user_id:"/"} onClick={event=>me&&openProfile(event,me.anonymous_user_id)}><Avatar initials={me?.avatar||"…"} color={me?.avatarColor||"#286c91"} size={39}/><div><b>{me?.display_name||"익명 계정"}</b><small>{me?"@"+me.username:""}</small></div></a></aside><main className="feed"><header className="sticky" ref={headerRef}><div className="feed-heading"><div className="profile-heading">{profileRoute&&<button onClick={home} aria-label="홈으로 돌아가기"><ChevronLeft size={23}/></button>}<div><h1>{profileRoute?(profileUser?.display_name||"프로필"):"홈"}</h1>{profileRoute&&profileUser&&<small className="muted">{profilePosts.length} 게시물</small>}</div></div><span className="simulation"><RadioTower size={13}/>RESEARCH FEED</span></div>{!profileRoute&&<div className="tabs">{['추천','팔로잉'].map(t=><button key={t} onClick={()=>setTab(t)} className={tab===t?'on':''}>{t}</button>)}</div>}</header>{profileRoute?<Profile user={profileUser} status={profileStatus} posts={profilePosts} renderPost={renderPost} onHome={home}/>:<><div className="notice"><ShieldCheck size={17}/>연구용 피드입니다. 수집 게시물의 작성자는 익명화되며, 진위는 분석가가 검증합니다. 시나리오의 사건·계정·확산은 가상입니다.</div>{error&&<div className="notice" role="alert">{error}</div>}<section className="simulation-control" aria-label="확산 시나리오 테스트">
 <div className="scenario-title"><div><small>LIVE TEST · 가상 확산 실험</small><h2>{scenarioTitle}</h2></div><span className={'scenario-status '+simulation.status}>{({idle:'준비',running:'확산 중',completed:'완료',stopped:'중지'})[simulation.status]||'준비'}</span></div>
 <label className="temporal-pattern">훈련 시나리오 <select aria-label="훈련 시나리오" value={selectedScenario} disabled={busy||simulation.status!=='idle'} onChange={e=>setScenarioKey(e.target.value)}><option value="wartime">전시 복합 위기 · 10개 이슈</option><option value="relief">재난구호 협력 취소설 · 기존 시나리오</option><option value="cib_burst">CIB 실험 1 · 단발성 확산</option><option value="cib_repeat">CIB 실험 2 · 반복 공조</option><option value="cib_cascade">CIB 실험 3 · 다단계 증폭</option><option value="cib_authority">CIB 실험 4 · 고위직 사칭 주장</option><option value="cib_retreat">CIB 실험 5 · 미확인 후퇴 명령 주장</option><option value="cib_emergency">CIB 실험 6 · 긴급 공지 사칭·증폭</option></select></label>
 <p>{isCib?'기존 탐지 엔진을 검증하는 합성 게시물입니다. 게시·인용 시각은 가속된 가상 시간축이며, 검출 여부와 우선순위는 ANTI_FIMI가 계산합니다.':isWartime?'전선·후퇴 명령·동맹 충돌·파병군·군 시설·민간 시설·민간 피해·피란·경제·산업의 열 가지 이슈가 함께 등장합니다. 허위 주장뿐 아니라 질문·반박·공식 확인을 섞어 검증합니다. 국가와 사건은 모두 가상입니다.':'기존 협력 취소설과 다국어 질문·반박·의견 재게시를 재현합니다.'}</p>
 {!isWartime&&!isCib&&<label className="temporal-pattern">시간 패턴 <select aria-label="시간 패턴" value={simulation.status==='idle'?temporalPattern:(simulation.temporalPattern||temporalPattern)} disabled={busy||simulation.status!=='idle'} onChange={e=>setTemporalPattern(e.target.value)}>{[['auto','자동 선택'],['rapid_spike','급격한 집중'],['gradual_growth','점진적 증가'],['double_peak','두 번의 집중'],['delayed_spike','지연된 집중'],['long_tail','오래 이어지는 반응'],['low_activity','낮은 활동량']].map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>}
 {isWartime&&<p className="temporal-info">한 번에 한 글씩 · 게시 간격 0.1~0.4초 무작위 · 전체 생성은 평균 약 7분 30초입니다.</p>}
 <div className="scenario-buttons"><button className="scenario-start" onClick={()=>controlSimulation('start')} disabled={busy||simulation.status!=='idle'}><RadioTower size={16}/>{busy?'처리 중…':'시나리오 시작'}</button>{!isWartime&&!isCib&&<button className="scenario-fast" onClick={()=>controlSimulation('start-fast')} disabled={busy||simulation.status!=='idle'} title="전체 가상 게시물을 15초 안에 생성합니다"><RadioTower size={16}/>빠른 시나리오 시작 · 15초 이내</button>}<button onClick={()=>controlSimulation('stop')} disabled={busy||simulation.status!=='running'}>중지</button><button onClick={()=>controlSimulation('reset')} disabled={busy||simulation.status==='idle'}>테스트 초기화</button></div>
 <div className="scenario-metrics"><div><small>{isWartime||isCib?'훈련 게시물':'첫 게시물 좋아요'}</small><strong>{isWartime||isCib?`${simulation.status==='idle'?0:simulation.generatedCount||0} / ${simulation.status==='idle'?(isWartime?1801:'—'):(simulation.totalPosts||'—')}`:simulation.rootLikes.toLocaleString()}</strong></div><div><small>{isCib?'명시적 인용·재게시':isWartime?'시나리오 주장':'의견 재게시'}</small><strong>{isCib?(simulation.quoteCount||0):isWartime?`${simulation.scenarioCount||0} / 1,500`:`${simulation.quoteCount} / 60`}</strong></div><div><small>{isWartime?'게시 진행':'확산 단계'}</small><strong>{simulation.wave} / {isWartime&&simulation.status==='idle'?1800:simulation.totalWaves}</strong></div></div>
 {!isWartime&&simulation.mode==='fast'&&<p className="fast-mode-info" role="status">빠른 모드 · 전체 가상 게시물을 15초 안에 생성합니다.</p>}
 {simulation.mode==='continuous'&&<p className="fast-mode-info" role="status">반복 생성 모드 · 중지 버튼으로 멈출 수 있습니다. 주장 1,500개와 비교 글 300개를 생성하면 자동 완료됩니다.</p>}
 <p className="temporal-info">{isCib?'게시물 시각은 가속된 합성 시간축입니다. 실제 업로드 시각과 다릅니다.':isWartime?'작성 시각은 실제 게시 시각입니다.':'작성 시각은 가상 사건 시간입니다.'} {simulation.eventAt&&<>{isWartime||isCib?'시뮬레이션 시작:':'사건 시작:'} {new Date(simulation.eventAt).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})}</>}</p>
 <progress value={simulation.wave} max={simulation.totalWaves} aria-label="확산 진행률"/>
 <div className="scenario-hint" role="status">{simulation.error||({idle:'개인 의견·소문·질문·반박이 함께 생성됩니다. 재게시 자체가 악의적 행위라는 뜻은 아닙니다.',running:'서버가 게시물을 저장하고 있습니다. 다른 브라우저와 크롤러에서도 같은 확산을 볼 수 있습니다.',completed:'확산 완료 · 초기화하면 이번 테스트로 생성한 게시물만 삭제합니다.',stopped:'확산이 중지됐습니다. 게시물은 보존됩니다. 새 테스트는 초기화 후 시작하세요.'})[simulation.status]}</div>
 {origin&&<div className="scenario-origin"><small>첫 계정 · @{origin.handle}</small><p>{origin.text}</p>{origin.images?.length>0&&<small className="origin-attachments">이미지 {origin.images.length}장 첨부 · 원문에서 확인</small>}<a onClick={event=>navigateToPost(event,origin.id)} href={'/#'+origin.id}>첫 게시물 보기 ↗</a></div>}
 </section><section className="composer"><Avatar initials={me?.avatar||"…"} color={me?.avatarColor||"#286c91"}/><div><textarea id="composer" maxLength={280} placeholder="무슨 일이 일어나고 있나요?" value={draft} onChange={e=>setDraft(e.target.value)}/><div className="composer-bottom"><span><Globe2 size={18}/> 공개 · 시뮬레이션</span><div><small>{draft.length}/280</small><button disabled={!draft.trim()} onClick={publish}><Send size={15}/> 게시</button></div></div></div></section><div className="filter"><span>게시물 {filtered.length}개</span><select value={language} onChange={e=>setLanguage(e.target.value)}><option value="all">모든 언어</option><option value="ko">한국어</option><option value="en">English</option><option value="ja">日本語</option></select></div>{filtered.length?filtered.map(renderPost):<div className="empty">{posts.length?'검색 결과가 없습니다.':'아직 게시물이 없습니다. 수집 파일을 확인하거나 시나리오를 시작하세요.'}</div>}</> }</main><aside className="right"><div className="search"><Search size={19}/><input id="search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="검색"/>{search&&<button onClick={()=>setSearch('')}><X size={16}/></button>}</div><section className="panel"><h2>현재 시나리오</h2><div className="panel-body"><small className="chip">BLACK VEIL</small><h3>{isCib?cibTitles[selectedScenario]:isWartime?"전시 복합 위기":"한국 · APAC 협력 취소설"}</h3><p>{isCib?"합성 계정의 공개 게시물이 기존 수집기와 탐지기를 거칩니다. 경보는 사이트에서 지정하지 않습니다.":isWartime?"가상의 국가·계정을 사용하는 연구용 시뮬레이션입니다. 기사·개인 의견·소문과 중간 재게시가 함께 등장합니다.":"시작 버튼으로 반응 급증과 다국어 의견 재게시를 재현합니다."}</p><small className="muted">Mode: Synthetic Simulation</small></div></section><section className="panel"><h2>실시간 트렌드</h2>{trends.map(([cat,tag,num])=><button className="trend" key={tag} onClick={()=>setSearch(tag)}><small>{cat}</small><b>{tag}</b><small>게시물 {num}개 · 가상</small></button>)}</section><footer>VEIL Social · D4D T2-2 Prototype<br/>Research simulation only.</footer></aside></div><dialog ref={imageDialog} className="image-dialog" aria-label="첨부 이미지 확대" onClose={()=>setImagePreview(null)} onClick={event=>{if(event.target===event.currentTarget)setImagePreview(null)}} onKeyDown={event=>{if(event.key==='ArrowLeft'){event.preventDefault();moveImage(-1)}if(event.key==='ArrowRight'){event.preventDefault();moveImage(1)}}}>
 {imagePreview&&<div className="image-viewer"><div className="image-toolbar"><span>첨부 이미지 {imagePreview.index+1} / {imagePreview.images.length}</span><button type="button" onClick={()=>setImagePreview(null)} aria-label="이미지 닫기"><X size={22}/></button></div><img src={imagePreview.images[imagePreview.index].url} alt={imagePreview.images[imagePreview.index].alt}/><div className="image-caption">{imagePreview.images[imagePreview.index].alt}</div>{imagePreview.images.length>1&&<div className="image-navigation"><button type="button" onClick={()=>moveImage(-1)} aria-label="이전 이미지"><ChevronLeft size={20}/> 이전</button><button type="button" onClick={()=>moveImage(1)} aria-label="다음 이미지">다음 <ChevronRight size={20}/></button></div>}</div>}
 </dialog></div>
}
