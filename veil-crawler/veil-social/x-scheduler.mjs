export class CollectionScheduler {
  constructor({run,getState,configured,clock=()=>Date.now(),setTimer=setTimeout,clearTimer=clearTimeout,onError=()=>{}}) {
    Object.assign(this,{run,getState,configured,clock,setTimer,clearTimer,onError});this.timer=null;
  }
  stop(){if(this.timer!==null)this.clearTimer(this.timer);this.timer=null;}
  schedule(){
    this.stop();const state=this.getState();
    if(!state.autoEnabled || !this.configured() || state.status==='running')return;
    const at=Date.parse(state.nextAllowedAt);
    const delay=Math.max(0,Number.isFinite(at)?at-this.clock():0);
    this.timer=this.setTimer(async()=>{
      this.timer=null;
      // Re-read state so disabling during a pending timer prevents another request.
      if(!this.getState().autoEnabled || !this.configured())return;
      try{await this.run();}catch(error){this.onError(error);}finally{this.schedule();}
    },Math.min(delay,2147483647));
    this.timer?.unref?.();
  }
}
