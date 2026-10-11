import test from 'node:test';
import assert from 'node:assert/strict';
import {CollectionScheduler} from '../x-scheduler.mjs';
test('restart retains deadline; timer rechecks disabled state and reschedules after a run',async()=>{
  let state={autoEnabled:true,status:'completed',nextAllowedAt:new Date(1260000).toISOString()},timer,calls=0,delays=[];
  const scheduler=new CollectionScheduler({getState:()=>state,configured:()=>true,clock:()=>0,setTimer:(fn,delay)=>{timer=fn;delays.push(delay);return 1;},clearTimer:()=>{},run:async()=>{calls++;state={...state,nextAllowedAt:new Date(1560000).toISOString()};}});
  scheduler.schedule();assert.equal(delays[0],1260000);
  await timer();assert.equal(calls,1);assert.equal(delays.at(-1),1560000);
  state.autoEnabled=false;await timer();assert.equal(calls,1);
  scheduler.stop();
});
test('unconfigured or already running collector cannot schedule a parallel request',()=>{
  let calls=0,state={autoEnabled:true,status:'running'};
  const scheduler=new CollectionScheduler({getState:()=>state,configured:()=>false,run:()=>{},setTimer:()=>{calls++;}});
  scheduler.schedule();state.status='idle';scheduler.schedule();assert.equal(calls,0);
});
