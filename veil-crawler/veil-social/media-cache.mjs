import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
const types={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp','image/gif':'.gif'};
const MAX_BYTES=10*1024*1024;
// Cache only photo URLs returned by the API. A short total time budget keeps text ingestion responsive.
export async function cacheImages(posts,directory,{fetchImpl=fetch,now=()=>Date.now(),budgetMs=30000}={}) {
  await fs.mkdir(directory,{recursive:true});
  const deadline=now()+budgetMs;
  let cached=0,failed=0,limited=false;
  for(const post of posts)for(const image of post.images || []){
    const originalUrl=image.originalUrl || image.url;
    let parsed;try{parsed=new URL(originalUrl);}catch{failed++;continue;}
    if(parsed.protocol!=='https:' || parsed.hostname!=='pbs.twimg.com'){failed++;continue;}
    const hash=createHash('sha256').update(originalUrl).digest('hex');
    let filename;
    for(const extension of Object.values(types)){
      try{await fs.access(path.join(directory,hash+extension));filename=hash+extension;break;}catch{}
    }
    if(!filename){
      if(limited || now()>=deadline){failed++;continue;}
      try{
        const response=await fetchImpl(originalUrl,{signal:AbortSignal.timeout(Math.max(1,Math.min(10000,deadline-now()))),redirect:'error'});
        if(response.status===429){limited=true;throw new Error('Photo limit');}
        const extension=types[(response.headers.get('content-type') || '').split(';')[0].toLowerCase()];
        if(!response.ok || !extension || Number(response.headers.get('content-length'))>MAX_BYTES){await response.body?.cancel();throw new Error('Unsupported photo');}
        const reader=response.body.getReader(),chunks=[];let size=0;
        try{
          while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>MAX_BYTES)throw new Error('Photo too large');chunks.push(value);}
        }finally{await reader.cancel().catch(()=>{});}
        if(!size)throw new Error('Empty photo');
        filename=hash+extension;
        await fs.writeFile(path.join(directory,filename+'.tmp'),Buffer.concat(chunks));
        await fs.rename(path.join(directory,filename+'.tmp'),path.join(directory,filename));
      }catch{failed++;continue;}
    }
    image.originalUrl=originalUrl;image.url='/archive-media/'+filename;image.cached=true;
    image.caption='X 원문 사진 · 로컬 보관본';cached++;
  }
  return {cached,failed,limited};
}
