import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {cacheImages} from '../media-cache.mjs';
test('cached photos survive reuse without another network request; untrusted hosts rejected',async()=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'veil-media-'));
  const make=()=>[{images:[{url:'https://pbs.twimg.com/media/unit-test.jpg'},{url:'http://127.0.0.1/secret'}]}];let calls=0;
  const fetchImpl=async()=>{calls++;return new Response(new Uint8Array([255,216,255,217]),{headers:{'content-type':'image/jpeg'}});};
  try{
    const posts=make();const result=await cacheImages(posts,directory,{fetchImpl});
    assert.equal(result.cached,1);assert.equal(result.failed,1);assert.equal(calls,1);
    assert.match(posts[0].images[0].url,/^\/archive-media\/[a-f0-9]{64}\.jpg$/);
    assert.equal(posts[0].images[0].originalUrl,'https://pbs.twimg.com/media/unit-test.jpg');
    await cacheImages(make(),directory,{fetchImpl});assert.equal(calls,1);
  }finally{fs.rmSync(directory,{recursive:true,force:true});}
});
test('photo quota stops further photo requests and leaves original URLs available',async()=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'veil-media-limit-'));let calls=0;
  const posts=[{images:[{url:'https://pbs.twimg.com/media/a.jpg'},{url:'https://pbs.twimg.com/media/b.jpg'}]}];
  try{
    const result=await cacheImages(posts,directory,{fetchImpl:async()=>{calls++;return new Response('',{status:429});}});
    assert.equal(calls,1);assert.equal(result.failed,2);assert.equal(result.limited,true);
    assert.equal(posts[0].images[0].url,'https://pbs.twimg.com/media/a.jpg');
  }finally{fs.rmSync(directory,{recursive:true,force:true});}
});
