import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { Anonymizer } from '../anonymizer.mjs';
import { postsByUser, profileIdFromPath, isAnonymousPost } from '../src/post-utils.mjs';
import { renderPostsHtml } from '../posts-html.mjs';
import { beginSimulation, advanceSimulation } from '../simulation.mjs';

const real = (id,handle='original_A',name='실제 작성자 A',extra={}) => ({id:'x-'+id,authorId:handle,handle,name,
  text:'게시물 내용', publishedAt:'2026-10-10T09:00:00+09:00',language:'ko',likes:12,reposts:3,
  images:[],source:{platform:'x',url:'https://x.com/'+handle+'/status/'+id},...extra});
function environment() {
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'veil-anonymous-'));
  return {directory, filename:path.join(directory,'anonymized_users.json'),
    cleanup:()=>fs.rmSync(directory,{recursive:true,force:true})};
}

test('same author has one persistent ID, nickname, handle and avatar across posts and restart',()=>{
  const env=environment();
  try{
    const first=new Anonymizer(env.filename);
    const posts=first.project([real('1'),real('2'),real('3'),real('4','original_B','실제 작성자 B')]);
    assert.equal(new Set(posts.slice(0,3).map(p=>p.anonymous_user_id)).size,1);
    assert.equal(new Set(posts.slice(0,3).map(p=>p.name+p.handle+p.avatar+p.avatarColor)).size,1);
    const second=new Anonymizer(env.filename);
    assert.deepEqual(second.project([real('1')])[0],posts[0]);
    // Windows ACLs do not implement POSIX mode bits.
    if(process.platform!=='win32')assert.equal(fs.statSync(env.filename).mode & 0o777,0o600);
    assert.notEqual(posts[0].anonymous_user_id,posts[3].anonymous_user_id);
    assert.notEqual(posts[0].id,'x-1');
    assert.equal(isAnonymousPost(real('1')),false);
    assert.equal(isAnonymousPost(posts[0]),true);
  }finally{env.cleanup()}
});

test('public IDs preserve quote and reply targets without exposing raw identities or role labels',()=>{
  const env=environment();
  try{
    const anonymous=new Anonymizer(env.filename);
    const posts=anonymous.project([
      real('root'),
      real('quote','original_B','B',{repostOf:'x-root',referenceType:'quotes',simulation_role:'claim'}),
      real('reply','original_C','C',{replyTo:'x-root',isReply:true}),
      real('repost','original_D','D',{repostOf:'x-root',referenceType:'reposts'}),
    ]);
    assert.equal(posts[1].repostOf,posts[0].id);
    assert.equal(posts[1].referenceType,'quotes');
    assert.equal(posts[2].replyTo,posts[0].id);
    assert.equal(posts[2].comment,true);
    assert.equal(posts[3].referenceType,'reposts');
    const html=renderPostsHtml(posts);
    assert.ok(html.includes('data-reference-type="quotes"'));
    assert.ok(html.includes(`data-reply-to="${posts[0].id}"`));
    assert.ok(html.includes('data-language="ko"'));
    assert.ok(!html.includes('simulation_role'));
    assert.ok(!JSON.stringify(posts).includes('x-root'));
  }finally{env.cleanup()}
});

test('numeric author ID and handle aliases group precisely; profile uses only anonymous ID',()=>{
  const env=environment();
  try{
    const anonymous=new Anonymizer(env.filename);
    const posts=anonymous.project([real('1','same_handle'),real('2','same_handle','変更',{authorId:'numeric-123'}),real('3','same_handle','変更',{authorId:'numeric-123'}),real('4','other_handle')]);
    const id=posts[0].anonymous_user_id;
    assert.equal(postsByUser(posts,id).length,3);
    assert.equal(anonymous.profile(id,posts).post_count,3);
    assert.equal(postsByUser(posts,posts[3].anonymous_user_id).length,1);
    assert.equal(anonymous.profile('anon_9999',posts),null);
    const empty=anonymous.register({id:'empty',handle:'empty_user'});anonymous.save();
    assert.equal(anonymous.profile(empty.anonymous_user_id,posts).post_count,0);
    assert.equal(profileIdFromPath('/profile/'+id),id);
    assert.equal(profileIdFromPath('/profile/not-a-profile'),null);
  }finally{env.cleanup()}
});

test('API projection and crawler HTML omit identities, profile links, raw IDs, photo URLs and role metadata',()=>{
  const env=environment();
  try{
    const anonymous=new Anonymizer(env.filename);
    const raw=real('987654','original_A','실제 작성자 A',{
      title:'https://\nx.com/original_A',authorId:'private-user-id',text:'실제 작성자 A @original_A https://x.com/original_A/status/987654 https://t.co/privateLink',
      profile_url:'https://x.com/original_A',profile_image:'https://face.example/face.jpg',simulation_role:'malicious_actor',
      images:[{url:'/archive-media/'+'a'.repeat(64)+'.jpg',originalUrl:'https://pbs.twimg.com/private-photo.jpg',alt:'original_A 사진'}]});
    const projected=anonymous.project([raw]);
    for(const exposed of [JSON.stringify(projected),renderPostsHtml(projected),JSON.stringify(anonymous.profile(projected[0].anonymous_user_id,projected))]) {
      for(const value of ['original_A','실제 작성자 A','private-user-id','987654','https://x.com','t.co/privateLink','private-photo.jpg','face.example','simulation_role','malicious_actor','privateHandles','aliases'])assert.ok(!exposed.includes(value),value);
    }
    assert.equal(raw.name,'실제 작성자 A');
    assert.equal(projected[0].authorId,projected[0].anonymous_user_id);
    assert.equal(projected[0].likes,12);
    assert.equal(projected[0].publishedAt,raw.publishedAt);
    assert.equal(projected[0].images.length,1);
  }finally{env.cleanup()}
});

test('a renamed numeric author keeps identity and distinct numeric IDs never merge on a recycled handle',()=>{
  const env=environment();
  try{
    const anonymous=new Anonymizer(env.filename);
    const posts=anonymous.project([real('1','first_handle','첫 계정',{authorId:'100'}),real('2','new_handle','첫 계정',{authorId:'100'}),real('3','first_handle','다른 계정',{authorId:'200'})]);
    assert.equal(posts[0].anonymous_user_id,posts[1].anonymous_user_id);
    assert.notEqual(posts[0].anonymous_user_id,posts[2].anonymous_user_id);
  }finally{env.cleanup()}
});

test('two scenario actors repeat separate histories with distinct times; profiles survive subsequent runs',()=>{
  const env=environment();
  try{
    const anonymous=new Anonymizer(env.filename), start=new Date('2026-10-10T09:00:00Z');
    let result=beginSimulation([],start);
    for(let wave=1;wave<=15;wave++)result=advanceSimulation(result.posts,result.state,new Date(start.getTime()+wave*4000));
    const actors=['campaign_a','campaign_b'];
    const projected=anonymous.project(result.posts);
    const ids=[];
    for(const actor of actors){
      const raw=result.posts.filter(p=>p.simulationActorId===actor);
      assert.ok(raw.length>=5);
      const userId=anonymous.register(raw[0]).anonymous_user_id;ids.push(userId);
      const history=postsByUser(projected,userId);
      assert.equal(history.length,raw.length);
      assert.equal(new Set(history.map(p=>p.publishedAt)).size,history.length);
      assert.equal(new Set(history.map(p=>p.name+p.handle+p.avatar)).size,1);
      assert.ok(history.every(p=>!('simulation_role' in p)));
    }
    assert.notEqual(ids[0],ids[1]);
    const nextRun=anonymous.project(beginSimulation([]).posts);
    assert.equal(nextRun[0].anonymous_user_id,ids[0]);
    const quotes=projected.filter(p=>p.repostOf);
    assert.ok(quotes.every(p=>projected.some(original=>original.id===p.repostOf)));
  }finally{env.cleanup()}
});
