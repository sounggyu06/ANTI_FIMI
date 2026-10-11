import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {PostArchive,archiveDirectory} from '../archive.mjs';
const post=(id='1')=>({id:'x-'+id,text:'저장 복구 테스트용 데이터',publishedAt:'2026-10-10T01:00:00Z',likes:1,source:{platform:'x',url:`https://x.com/test/status/${id}`,truthStatus:'not_assessed'}});
test('archive persists across reopened projects, deduplicates and preserves observations',()=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'veil-archive-'));
  let archive=new PostArchive(directory);
  try{
    assert.equal(archive.saveBatch([post()],{autoEnabled:true,nextAllowedAt:'2026-10-10T02:00:00Z'}).newPosts,1);
    assert.equal(archive.saveBatch([{...post(),likes:7}],{autoEnabled:true}).newPosts,0);
    assert.equal(archive.count(),1);
    assert.equal(archive.db.prepare('SELECT count(*) AS n FROM observations').get().n,2);
    archive.close();archive=new PostArchive(directory);
    assert.equal(archive.latest()[0].likes,7);assert.equal(archive.getSetting('import',{}).autoEnabled,true);
    const destination=path.join(directory,'export.jsonl');assert.equal(archive.exportJsonl(destination),1);
    assert.equal(JSON.parse(fs.readFileSync(destination,'utf8').trim()).source.truthStatus,'not_assessed');
    assert.throws(()=>archive.saveBatch([post('2'),{id:'synthetic',source:{platform:'simulation'}}]));
    assert.equal(archive.count(),1); // Partial transaction must roll back.
  }finally{archive.close();fs.rmSync(directory,{recursive:true,force:true});}
});
test('large catalog exports all records while visible feed stays bounded',()=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'veil-large-'));
  const archive=new PostArchive(directory);
  try{
    archive.saveBatch(Array.from({length:350},(_,i)=>post(String(i+1))));
    assert.equal(archive.latest().length,200);assert.equal([...archive.records()].length,350);
    assert.equal(archiveDirectory({}),archiveDirectory({UNRELATED_PROJECT:'changed'}));
    assert.equal(archiveDirectory({VEIL_ARCHIVE_DIR:directory}),directory);
  }finally{archive.close();fs.rmSync(directory,{recursive:true,force:true});}
});
