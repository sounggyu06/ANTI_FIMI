import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { PostArchive } from '../archive.mjs';
import { importLocalDirectory } from '../local-import.mjs';
import { clearSimulation } from '../simulation.mjs';

const record = {post_id:'123',account_id:'@user_001',display_name:'수집 계정',text:'원문\n본문 유지',
  created_at:'2026-10-10T07:00:00.000Z',post_url:'https://x.com/user_001/status/123',
  image_urls:['https://pbs.twimg.com/media/example.jpg'],image_paths:['data/images/123/1.jpg']};

test('local JSONL and images persist, duplicate topics merge and repeat imports are idempotent', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(),'veil-local-import-'));
  const directory = path.join(root,'input');
  const archive = new PostArchive(path.join(root,'archive'));
  try {
    await fs.mkdir(path.join(directory,'images/123'),{recursive:true});
    const bytes = await fs.readFile(new URL('../public/media/relief-news.jpg',import.meta.url));
    await fs.writeFile(path.join(directory,'images/123/1.jpg'),bytes);
    await fs.writeFile(path.join(directory,'x_대한민국_20261010_160000.jsonl'),JSON.stringify(record)+'\n');
    await fs.writeFile(path.join(directory,'x_중국_20261010_160001.jsonl'),JSON.stringify(record)+'\n');
    archive.setSetting('import',{autoEnabled:false,nextMode:'popular'});
    const result = await importLocalDirectory(directory,archive);
    assert.equal(result.records,2);
    assert.equal(result.posts,1);
    assert.equal(result.duplicateRecords,1);
    assert.equal(result.photos,1);
    assert.deepEqual(result.warnings,[]);
    const post = archive.latest()[0];
    assert.equal(post.text,record.text);
    assert.equal(post.publishedAt,record.created_at);
    assert.equal(post.authorId,'user_001');
    assert.equal(post.source.url,record.post_url);
    assert.deepEqual(post.source.topics,['대한민국','중국']);
    assert.equal(post.source.metricsAvailable.likes,false);
    assert.equal(post.likes,0);
    assert.equal(post.images[0].originalUrl,record.image_urls[0]);
    assert.deepEqual(await fs.readFile(path.join(archive.directory,'media',path.basename(post.images[0].url))),bytes);
    const before=archive.db.prepare('SELECT count(*) AS n FROM observations').get().n;
    assert.equal((await importLocalDirectory(directory,archive)).alreadyImported,true);
    assert.equal(archive.db.prepare('SELECT count(*) AS n FROM observations').get().n,before);
    assert.equal(archive.getSetting('import').autoEnabled,false);
    assert.equal(archive.getSetting('import').nextMode,'popular');
    assert.deepEqual(clearSimulation([post,{id:'fake',simulationRunId:'test'}]).posts,[post]);
  } finally {archive.close();await fs.rm(root,{recursive:true,force:true});}
});

test('real reaction counts remain intact and image paths outside images cannot be imported', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(),'veil-local-path-'));
  const directory=path.join(root,'input');
  const archive=new PostArchive(path.join(root,'archive'));
  try {
    await fs.mkdir(path.join(directory,'images'),{recursive:true});
    await fs.mkdir(path.join(root,'outside'));
    await fs.copyFile(new URL('../public/media/relief-news.jpg',import.meta.url),path.join(root,'outside/photo.jpg'));
    // Directory junctions exercise realpath containment on Windows without administrator privileges.
    await fs.symlink(path.join(root,'outside'),path.join(directory,'images/link'),process.platform==='win32'?'junction':'dir');
    const raw={...record,author_id:'numeric-author',like_count:12,retweet_count:3,reply_count:7,
      image_paths:['images/link/photo.jpg']};
    await fs.writeFile(path.join(directory,'x_test_20261010_160000.jsonl'),JSON.stringify(raw)+'\ninvalid json\n');
    const result=await importLocalDirectory(directory,archive);
    assert.equal(result.photos,0);
    assert.equal(result.warnings.length,2);
    const post=archive.latest()[0];
    assert.equal(post.authorId,'numeric-author');
    assert.equal(post.likes,12);
    assert.equal(post.reposts,3);
    assert.equal(post.comments,7);
    assert.equal(post.comment,false);
    assert.equal(post.source.metricsAvailable.likes,true);
  } finally {archive.close();await fs.rm(root,{recursive:true,force:true});}
});

test('six-field JSONL without post IDs and username/display_name records load without modifying originals', async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'veil-compatible-jsonl-'));
  const archive=new PostArchive(path.join(root,'archive'));
  try{
    const directory=path.join(root,'input');await fs.mkdir(directory);
    const rows=[{author_id:'user_001',comment:'true',created_at:'2026-10-10T14:00:00+09:00',text:'첫 글',retweet_count:3,like_count:12},
      {author_id:'user_001',comment:'false',created_at:'2026-10-10T15:00:00+09:00',text:'두 번째 글',retweet_count:5,like_count:7},
      {username:'original_B',display_name:'실제 계정',created_at:'2026-10-10T16:00:00+09:00',text:'세 번째 글',repost_count:9}];
    const original=rows.map(row=>JSON.stringify(row)).join('\n')+'\n';
    const input=path.join(directory,'posts.jsonl');await fs.writeFile(input,original);
    const result=await importLocalDirectory(directory,archive);
    assert.equal(result.posts,3);assert.deepEqual(result.warnings,[]);
    const posts=archive.latest();assert.equal(posts.find(p=>p.text==='세 번째 글').reposts,9);
    assert.equal(posts.filter(p=>p.authorId==='user_001').length,2);
    assert.equal(posts.find(p=>p.text==='첫 글').comment,true);
    assert.equal(await fs.readFile(input,'utf8'),original);
    assert.equal((await importLocalDirectory(directory,archive)).alreadyImported,true);
  }finally{archive.close();await fs.rm(root,{recursive:true,force:true})}
});
