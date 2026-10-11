import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PostArchive, archiveDirectory } from './archive.mjs';
import { importLocalDirectory } from './local-import.mjs';

const root = path.dirname(fileURLToPath(import.meta.url));
try { process.loadEnvFile(path.join(root, '.env')); } catch(error) { if(error.code !== 'ENOENT') throw error; }
const index = process.argv.indexOf('--directory');
if (index >= 0 && !process.argv[index + 1]) throw new Error('--directory 뒤에 JSONL과 images 폴더가 있는 경로를 지정하세요.');
const directory = index >= 0 ? process.argv[index + 1] : path.join(root, 'data', 'imported-x');
const archive = new PostArchive(archiveDirectory());
try {
  console.log(JSON.stringify(await importLocalDirectory(directory, archive), null, 2));
  console.log('서버가 켜져 있으면 화면의 저장 데이터 다시 불러오기를 누르세요. 꺼져 있으면 npm start로 실행하세요.');
} finally { archive.close(); }
