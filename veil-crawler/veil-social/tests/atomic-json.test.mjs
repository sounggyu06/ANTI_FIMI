import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { atomicJson, logStorageError } from '../atomic-json.mjs';

function busy(code) { return Object.assign(new Error('forced Windows sharing violation'), {code, syscall:'rename'}); }

test('sharing violations retry replacement while the previous complete JSON remains readable', async () => {
  const folder = await fs.mkdtemp(path.join(os.tmpdir(), 'veil-atomic-json-'));
  const filename = path.join(folder, 'posts.json');
  try {
    await fs.writeFile(filename, JSON.stringify({posts:['previous']}));
    let calls = 0;
    const waits = [], retries = [];
    await atomicJson(filename, {posts:['next']}, {
      rename: async (temporary, target) => {
        calls++;
        assert.deepEqual(JSON.parse(await fs.readFile(target, 'utf8')), {posts:['previous']});
        assert.deepEqual(JSON.parse(await fs.readFile(temporary, 'utf8')), {posts:['next']});
        if(calls <= 3) throw busy(['EPERM','EACCES','EBUSY'][calls-1]);
        await fs.rename(temporary, target);
      },
      wait: async milliseconds => waits.push(milliseconds),
      onRetry: (error, attempt) => retries.push([error.code, attempt]),
    });
    assert.equal(calls, 4);
    assert.deepEqual(waits, [10,20,40]);
    assert.deepEqual(retries, [['EPERM',1],['EACCES',2],['EBUSY',3]]);
    assert.deepEqual(JSON.parse(await fs.readFile(filename,'utf8')), {posts:['next']});
    assert.deepEqual(await fs.readdir(folder), ['posts.json']);
  } finally { await fs.rm(folder, {recursive:true,force:true}); }
});

test('persistent sharing violation is bounded and preserves the previous destination', async () => {
  const folder = await fs.mkdtemp(path.join(os.tmpdir(), 'veil-atomic-persistent-'));
  const filename = path.join(folder, 'simulation.json');
  try {
    const previous = JSON.stringify({status:'running', wave:162});
    await fs.writeFile(filename, previous);
    let calls = 0, waited = 0;
    await assert.rejects(atomicJson(filename, {status:'running',wave:163}, {
      rename: async () => {calls++;throw busy('EPERM');},
      wait: async milliseconds => {waited += milliseconds;}, onRetry: () => {},
    }), {code:'EPERM'});
    assert.equal(calls, 8);
    assert.equal(waited, 1130);
    assert.equal(await fs.readFile(filename,'utf8'), previous);
    assert.deepEqual(await fs.readdir(folder), ['simulation.json']);
  } finally { await fs.rm(folder,{recursive:true,force:true}); }
});

test('permanent filesystem errors fail immediately and record diagnostic fields', async () => {
  const folder = await fs.mkdtemp(path.join(os.tmpdir(), 'veil-atomic-error-'));
  const filename = path.join(folder, 'posts.json');
  try {
    await fs.writeFile(filename, '[]');
    let calls = 0;
    const error = Object.assign(new Error('disk error'), {code:'EIO',syscall:'rename',path:'temporary',dest:filename});
    await assert.rejects(atomicJson(filename, ['new'], {
      rename: async () => {calls++;throw error;}, wait: () => assert.fail('unexpected retry'),
    }), {code:'EIO'});
    assert.equal(calls, 1);
    const original = console.error;
    let logged;
    try {
      console.error = line => {logged=JSON.parse(line);};
      logStorageError('simulation.tick',error,{wave:162});
    } finally {console.error=original;}
    assert.equal(logged.code,'EIO');
    assert.equal(logged.syscall,'rename');
    assert.equal(logged.path,'temporary');
    assert.equal(logged.dest,filename);
    assert.equal(logged.wave,162);
    assert.ok(logged.stack.includes('disk error'));
  } finally {await fs.rm(folder,{recursive:true,force:true});}
});
