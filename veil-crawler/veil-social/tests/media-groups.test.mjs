import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { beginSimulation, advanceSimulation } from '../simulation.mjs';
const read = name => JSON.parse(fs.readFileSync(new URL('../'+name,import.meta.url),'utf8'));
test('idle feed has no fabricated normal seed; all scenario media belongs to negative fixtures',()=>{
  assert.deepEqual(read('data/posts.json'),[]);
  const manifest=read('fixtures/media_manifest.json').assets;
  const negative=new Set(manifest.map(asset=>asset.public_url));
  assert.equal(negative.size,3);
  assert.ok(manifest.every(asset=>asset.evaluation_class==='manipulation_scenario'));
  for(const filename of ['water-distribution.jpg','forest-volunteers.jpg','military-relief.jpg'])
    assert.ok(!fs.existsSync(new URL('../public/media/'+filename,import.meta.url)));
  assert.equal(read('data/scenario-posts.json').length,12);
  let result=beginSimulation([]);
  for(let i=0;i<15;i++) result=advanceSimulation(result.posts,result.state);
  assert.equal(result.posts.length,73);
  assert.ok(result.posts.every(post=>post.images.every(image=>negative.has(image.url))));
});
