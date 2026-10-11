import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { beginSimulation,advanceSimulation,clearSimulation } from '../simulation.mjs';
import {Anonymizer} from '../anonymizer.mjs';
import {renderPostsHtml} from '../posts-html.mjs';

const keys=['cib_burst','cib_repeat','cib_cascade','cib_authority','cib_retreat','cib_emergency'];
const counts=[31,36,48,39,41,48];
for (const [index,scenarioKey] of keys.entries()) {
  test(`${scenarioKey}: existing site generator -> anonymizer -> crawler HTML`,()=>{
    const now=new Date('2026-10-11T06:00:00Z');
    const old={id:'prior',authorId:'prior',publishedAt:'2026-10-10T00:00:00Z',text:'기존 글'};
    let result=beginSimulation([old],now,'normal',{scenarioKey});
    assert.equal(result.state.mode,'cib');
    const phases=[];
    while(result.state.status==='running') {
      const prev=result.state.generatedCount;
      result=advanceSimulation(result.posts,result.state,now);
      assert.ok(result.state.generatedCount>prev);
      phases.push(result.state.wave);
    }
    assert.equal(result.state.generatedCount,counts[index]);
    assert.equal(result.posts.length,counts[index]+1);
    assert.equal(result.state.totalPosts,counts[index]);
    assert.equal(new Set(result.posts.map(p=>p.id)).size,result.posts.length);
    const own=result.posts.filter(p=>p.simulationRunId===result.state.runId);
    const byId=new Map(own.map(p=>[p.id,p]));
    for(const post of own) if(post.repostOf) {
      assert.ok(byId.has(post.repostOf));
      assert.ok(Date.parse(post.publishedAt)>=Date.parse(byId.get(post.repostOf).publishedAt));
    }
    assert.ok(own.every(p=>p.text.length<=280));
    assert.ok(own.every(p=>!p.text.includes('[합성 실험]')&&!p.text.includes('[합성실험]')));
    if(['cib_authority','cib_retreat','cib_emergency'].includes(scenarioKey)) {
      assert.ok(own.some(p=>p.repostOf));
    }
    const directory=fs.mkdtempSync(path.join(os.tmpdir(),'veil-cib-test-'));
    try {
      const mapped=new Anonymizer(path.join(directory,'anon.json')).project(result.posts);
      const html=renderPostsHtml(mapped);
      assert.equal((html.match(/<article class="post"/g)||[]).length,result.posts.length);
      assert.ok(!html.includes('simulationActorId'));
      assert.ok(!html.includes('simulation_role'));
      assert.ok(html.includes('data-author-id'));
      const repeat=own.filter(p=>p.simulationActorId.endsWith('_core_0'));
      if(scenarioKey==='cib_repeat')assert.equal(repeat.length,4);
      if(scenarioKey==='cib_cascade'){
        assert.equal(own.filter(p=>p.repostOf).length,23);
        const chain=own.find(p=>p.simulationActorId.endsWith('relay_5'));
        assert.ok(chain?.repostOf);
      }
    }finally{fs.rmSync(directory,{recursive:true,force:true});}
    assert.deepEqual(clearSimulation(result.posts).posts,[old]);
  });
}
