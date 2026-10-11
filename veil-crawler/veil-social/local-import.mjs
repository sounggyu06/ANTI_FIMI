// 사용자가 수집한 JSONL + 로컬 사진을 가져옵니다. 외부 사이트에는 요청하지 않습니다.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';

const count = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;
const measured = value => Number.isSafeInteger(value) && value >= 0;
const digest = value => createHash('sha256').update(value).digest('hex');

function photoExtension(bytes) {
  if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return '.jpg';
  if (bytes.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) return '.png';
  if (/^GIF8[79]a$/.test(bytes.subarray(0, 6).toString())) return '.gif';
  if (bytes.subarray(0,4).toString() === 'RIFF' && bytes.subarray(8,12).toString() === 'WEBP') return '.webp';
  return null;
}

async function localPhoto(filename, directory) {
  const allowed = await fs.realpath(path.join(directory, 'images'));
  // 기존 수집기의 data/images/... 경로와 images/... 경로를 모두 지원합니다.
  const normalized = String(filename).replaceAll('\\', '/');
  const candidates = [path.resolve(directory, normalized), path.resolve(directory, '..', normalized),
    path.resolve(directory, normalized.replace(/^data\//, ''))];
  for (const candidate of candidates) {
    try {
      const resolved = await fs.realpath(candidate);
      if (!resolved.startsWith(allowed + path.sep)) continue;
      const stat = await fs.stat(resolved);
      if (!stat.isFile() || stat.size > 10 * 1024 * 1024) continue;
      const bytes = await fs.readFile(resolved);
      const extension = photoExtension(bytes);
      if (extension) return { bytes, filename: digest(bytes) + extension };
    } catch { /* 후보 경로가 없으면 다음 경로를 확인합니다. */ }
  }
  return null;
}

/** 원문은 별도 파일에 보존하고, 동일 원문 ID는 한 개의 화면 게시물로 저장합니다. */
export async function importLocalDirectory(directory, archive) {
  directory = path.resolve(directory);
  const files = (await fs.readdir(directory)).filter(name => name.endsWith('.jsonl')).sort();
  if (!files.length) throw new Error('JSONL 파일이 없습니다.');
  const inputs = await Promise.all(files.map(async name => ({name, text: await fs.readFile(path.join(directory, name), 'utf8')})));
  const fingerprint = digest(JSON.stringify(inputs));
  const setting = 'local-import:v2:' + fingerprint;
  const previous = archive.getSetting(setting, null);
  // 매번 서버를 재시작해도 같은 묶음을 다시 쓰거나 원래 게시물을 지우지 않습니다.
  if (previous) return {...previous, alreadyImported: true};
  const importedAt = new Date().toISOString();
  const byId = new Map(), warnings = [], photos = new Map();
  let records = 0, duplicateRecords = 0;
  for (const input of inputs) {
    const topic = input.name.normalize('NFC').replace(/^x_/, '').replace(/_\d{8}_\d{6}\.jsonl$/, '');
    for (const [index, line] of input.text.split(/\r?\n/).entries()) {
      if (!line.trim()) continue;
      records++;
      let raw;
      try { raw = JSON.parse(line); }
      catch { warnings.push(`${input.name}:${index + 1} JSON 오류`); continue; }
      // 기존 수집기와 6필드 크롤러 JSONL 및 일반적인 작성자 필드를 함께 지원합니다.
      const authorObject = typeof raw.author === 'object' && raw.author ? raw.author : {};
      const userObject = typeof raw.user === 'object' && raw.user ? raw.user : {};
      const handle = String(raw.account_id ?? raw.username ?? raw.handle ?? raw.screen_name ?? authorObject.username ?? userObject.username ?? '').replace(/^@/, '');
      const authorId = String(raw.author_id ?? raw.user_id ?? authorObject.id ?? userObject.id ?? handle);
      const id = String(raw.post_id ?? raw.id ?? ('local-' + digest(JSON.stringify([authorId,handle,raw.created_at,raw.text])).slice(0,32)));
      const createdAt = String(raw.created_at ?? '');
      if (!/^[A-Za-z0-9_:-]{1,100}$/.test(id) || (!authorId && !handle) ||
          typeof raw.text !== 'string' || !raw.text.trim() || (createdAt && !Number.isFinite(Date.parse(createdAt)))) {
        warnings.push(`${input.name}:${index + 1} ID·작성자·본문·시각 오류`); continue;
      }
      if (byId.has(id)) {
        duplicateRecords++;
        const existing = byId.get(id);
        existing.source.topics = [...new Set([...existing.source.topics, topic])];
        existing.source.inputFiles.push(input.name);
        continue;
      }
      const images = [];
      const imagePaths = Array.isArray(raw.image_paths) ? raw.image_paths : [];
      const imageUrls = Array.isArray(raw.image_urls) ? raw.image_urls : [];
      for (let i = 0; i < Math.max(imagePaths.length, imageUrls.length); i++) {
        const photo = imagePaths[i] ? await localPhoto(imagePaths[i], directory).catch(() => null) : null;
        let originalUrl;
        try {
          const url = new URL(imageUrls[i]);
          if (url.protocol === 'https:' && url.hostname === 'pbs.twimg.com') originalUrl = url.href;
        } catch { /* 원본 사진 URL이 없더라도 로컬 사진은 표시할 수 있습니다. */ }
        if (photo) {
          photos.set(photo.filename, photo.bytes);
          images.push({url: '/archive-media/' + photo.filename, originalUrl, cached: true,
            alt: '사용자 수집 X 원문 첨부 사진', caption: 'X 원문 사진 · 사용자 수집 로컬 파일'});
        } else {
          warnings.push(`${input.name}:${index + 1} 첨부 사진 ${i + 1} 로컬 파일 없음/지원 불가`);
          if (originalUrl) images.push({url: originalUrl, originalUrl, cached: false, alt: 'X 원문 첨부 사진'});
        }
      }
      let originalUrl = `https://x.com/${handle}/status/${id}`;
      try {
        const url = new URL(raw.post_url);
        if (url.protocol === 'https:' && ['x.com','twitter.com','www.x.com','www.twitter.com'].includes(url.hostname)) originalUrl = url.href;
      } catch { /* 작성자 핸들과 원문 ID로 고유 링크를 구성합니다. */ }
      const name = String(raw.display_name ?? raw.author_name ?? authorObject.name ?? userObject.name ?? (typeof raw.author === 'string' ? raw.author : handle));
      byId.set(id, {id: 'x-' + id, authorId, name, handle,
        avatar: [...name].slice(0,2).join(''), avatarColor: '#286c91', language: raw.language || 'und',
        text: raw.text, publishedAt: createdAt, verified: false,
        likes: count(raw.like_count), reposts: count(raw.retweet_count ?? raw.repost_count), comments: count(raw.reply_count),
        comment: raw.comment === true || raw.comment === 'true', repostOf: null, images,
        source: {platform: 'x', name: '사용자 수집 X 게시물', url: originalUrl, publishedOn: createdAt.slice(0,10),
          importedAt, topic, topics: [topic], inputFiles: [input.name], selectionMode: 'local', truthStatus: 'not_assessed',
          metricsAvailable: {likes: measured(raw.like_count), reposts: measured(raw.retweet_count ?? raw.repost_count), comments: measured(raw.reply_count)}}});
    }
  }
  const posts = [...byId.values()];
  if (!posts.length) throw new Error('가져올 수 있는 유효한 게시물이 없습니다.');
  const mediaDirectory = path.join(archive.directory, 'media');
  await fs.mkdir(mediaDirectory, {recursive: true});
  for (const [filename, bytes] of photos) {
    await fs.writeFile(path.join(mediaDirectory, filename + '.tmp'), bytes);
    await fs.rename(path.join(mediaDirectory, filename + '.tmp'), path.join(mediaDirectory, filename));
  }
  // 자동 API 수집의 기존 설정은 유지합니다. 로컬 파일 이식이 API 수집을 켜지 않습니다.
  const state = archive.saveBatch(posts, {...archive.getSetting('import', {}), status: 'completed', mode: 'local',
    imported: posts.length, targetCount: posts.length, collectedAt: importedAt, error: null});
  const summary = {records, posts: posts.length, duplicateRecords, photos: photos.size, newPosts: state.newPosts, warnings};
  archive.setSetting(setting, summary);
  return summary;
}
