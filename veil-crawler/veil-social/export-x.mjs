import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PostArchive,archiveDirectory } from './archive.mjs';
const root=path.dirname(fileURLToPath(import.meta.url));
try{process.loadEnvFile(path.join(root,'.env'));}catch(error){if(error.code!=='ENOENT')throw error;}
const directory=archiveDirectory();
const args=process.argv.slice(2),index=args.indexOf('--output');
const destination=index>=0?args[index+1]:path.join(directory,'exports','x-posts.jsonl');
if(!destination)throw new Error('--output 뒤에 저장 경로를 입력하세요.');
const archive=new PostArchive(directory);
try{console.log(`저장된 게시물 ${archive.exportJsonl(destination)}개 내보내기: ${path.resolve(destination)}`);}finally{archive.close();}
