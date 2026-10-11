// 원본 작성자와 익명 계정의 대응 관계는 서버의 로컬 파일에서만 보관합니다.
import fs from 'node:fs';
import path from 'node:path';
import { createHmac, randomBytes, randomInt } from 'node:crypto';
import { postsByUser } from './src/post-utils.mjs';

const adjectives = ['Blue','Silent','Night','Silver','Red','Green','Pixel','Urban','Golden','Amber','Misty','Bright','Snow','Ocean','Gentle','Lunar'];
const nouns = ['Fox','River','Owl','Cloud','Panda','Falcon','Wave','Wolf','Maple','Otter','Comet','Sparrow','Leaf','Bear','Lake','Robin'];
const colors = ['#426e9f','#397c75','#7f5d9b','#94703b','#935264','#286c91','#5769a2','#44806d'];
const string = value => typeof value === 'string' || typeof value === 'number' ? String(value).trim() : '';
const escapePattern = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const count = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;

/** 모든 공개 응답을 이 경계에서 새 객체로 만들고 원본 필드는 전달하지 않습니다. */
export class Anonymizer {
  constructor(filename) {
    this.filename = filename;
    if (fs.existsSync(filename)) {
      this.data = JSON.parse(fs.readFileSync(filename, 'utf8'));
      if (this.data.version !== 1 || !Array.isArray(this.data.users) || !this.data.secret) throw new Error('익명 계정 매핑 파일 형식 오류');
    } else {
      this.data = {version: 1, secret: randomBytes(32).toString('hex'), users: []};
    }
    this.byAlias = new Map();
    this.byId = new Map();
    for (const user of this.data.users) {
      user.identityIds ||= [];
      this.byId.set(user.anonymous_user_id, user);
      for (const alias of user.aliases) this.byAlias.set(alias, user);
    }
    this.dirty = !fs.existsSync(filename);
    this.redactions = [];
    this.save();
  }

  hash(value) { return createHmac('sha256', this.data.secret).update(value).digest('hex'); }
  postId(value) { return value ? 'post_' + this.hash('post:' + value).slice(0, 24) : null; }

  identity(post) {
    const real = post.source?.platform === 'x';
    const namespace = real ? 'x' : 'simulation';
    const handle = string(post.handle).replace(/^@/, '').toLowerCase();
    const author = string(post.authorId);
    const keys = [];
    if (post.simulationActorId) keys.push('actor:' + post.simulationActorId);
    if (author && author.toLowerCase() !== handle) keys.push('id:' + author);
    if (handle) keys.push('handle:' + handle);
    // 표시 이름만으로는 동명이인을 식별할 수 없으므로 ID가 없으면 게시물별로 구분합니다.
    if (!keys.length) keys.push('unidentified-post:' + post.id);
    return {real, handle, authorKey: author && author.toLowerCase() !== handle ? this.hash(namespace + ':id:' + author) : null, keys: keys.map(key => this.hash(namespace + ':' + key))};
  }

  register(post) {
    const identity = this.identity(post);
    let user = identity.authorKey ? this.byAlias.get(identity.authorKey) : null;
    if (!user) user = identity.keys.map(key => this.byAlias.get(key)).find(candidate => candidate &&
      (!identity.authorKey || !candidate.identityIds.length || candidate.identityIds.includes(identity.authorKey)));
    if (!user) {
      const index = this.data.users.length + 1;
      const usedNames = new Set(this.data.users.map(item => item.display_name));
      const choices = adjectives.flatMap(adjective => nouns.map(noun => adjective + noun))
        .filter(name => !usedNames.has(name) && name !== string(post.name));
      const nickname = choices.length ? choices[randomInt(choices.length)] : 'BlueFox' + index;
      user = {anonymous_user_id: 'anon_' + String(index).padStart(4, '0'), display_name: nickname,
        username: nickname.toLowerCase() + '_' + randomInt(1000,10000),
        avatar: nickname.match(/[A-Z]/g).slice(0,2).join(''), avatarColor: colors[randomInt(colors.length)],
        aliases: [], identityIds: [], privateNames: [], privateHandles: []};
      this.data.users.push(user);
      this.byId.set(user.anonymous_user_id, user);
      this.dirty = true;
    }
    if (identity.authorKey && !user.identityIds.includes(identity.authorKey)) {
      user.identityIds.push(identity.authorKey); this.dirty = true;
    }
    for (const key of identity.keys) {
      if (!this.byAlias.has(key)) {
        user.aliases.push(key); this.byAlias.set(key, user); this.dirty = true;
      }
    }
    if (identity.real) {
      for (const [field,value] of [['privateHandles',identity.handle],['privateNames',string(post.name)]]) {
        if (value && !user[field].includes(value)) { user[field].push(value); this.dirty = true; }
      }
    }
    return user;
  }

  save() {
    if (!this.dirty) return;
    fs.mkdirSync(path.dirname(this.filename), {recursive: true});
    const temporary = this.filename + '.tmp';
    fs.writeFileSync(temporary, JSON.stringify(this.data, null, 2), {mode: 0o600});
    fs.renameSync(temporary, this.filename);
    fs.chmodSync(this.filename, 0o600);
    this.dirty = false;
    this.prepareRedactions();
  }

  prepareRedactions() {
    this.redactions = this.data.users.flatMap(user => [
      ...user.privateHandles.map(handle => ({value: handle, replacement: user.username, handle: true})),
      ...user.privateNames.map(name => ({value: name, replacement: user.display_name, handle: false})),
    ]).sort((a,b) => b.value.length - a.value.length).map(item => ({
      pattern: new RegExp('(?<![\\p{L}\\p{N}_])' + (item.handle ? '@?' : '') + escapePattern(item.value) + '(?![\\p{L}\\p{N}_])', 'giu'),
      replacement: item.handle ? '@' + item.replacement : item.replacement,
    }));
  }

  text(value) {
    let result = string(value).replace(/https?:\/\/\s*(?:www\.|mobile\.)?(?:x\.com|twitter\.com|t\.co)\b[^\s<>]*/gi, '[원문 링크 비공개]');
    for (const item of this.redactions) result = result.replace(item.pattern, () => item.replacement);
    // 알 수 없는 외부 계정 멘션 역시 원래 핸들을 전달하지 않습니다.
    const publicHandles = new Set(this.data.users.map(user => user.username.toLowerCase()));
    return result.replace(/@[A-Za-z0-9_]{1,50}/g, mention => publicHandles.has(mention.slice(1).toLowerCase()) ? mention : '@익명계정');
  }

  publicUser(user) {
    if (!user) return null;
    const {anonymous_user_id,display_name,username,avatar,avatarColor} = user;
    return {anonymous_user_id,display_name,username,avatar,avatarColor,
      bio: '이 시뮬레이션에서 사용하는 익명 프로필입니다.', following: null, followers: null};
  }

  profile(id, posts) {
    const user = this.publicUser(this.byId.get(id));
    return user ? {...user, post_count: postsByUser(posts, id).length} : null;
  }

  project(posts) {
    // 먼저 전체 작성자를 등록하여 본문의 다른 작성자 멘션도 같은 익명 값으로 치환합니다.
    const users = posts.map(post => this.register(post));
    this.save();
    this.prepareRedactions();
    return posts.map((post,index) => {
      const user = users[index], real = post.source?.platform === 'x';
      const images = (Array.isArray(post.images) ? post.images : []).filter(image =>
        typeof image.url === 'string' && (/^\/archive-media\/[a-f0-9]{64}\.(jpg|png|webp|gif)$/.test(image.url) || /^\/media\/[a-zA-Z0-9_-]+\.(jpg|png|webp|gif)$/.test(image.url))
      ).map(image => ({url: image.url, alt: real ? '게시물 첨부 이미지' : this.text(image.alt),
        ...(Number.isSafeInteger(image.width) && image.width > 0 ? {width: image.width} : {}),
        ...(Number.isSafeInteger(image.height) && image.height > 0 ? {height: image.height} : {})}));
      return {id: this.postId(post.id), anonymous_user_id: user.anonymous_user_id, authorId: user.anonymous_user_id,
        name: user.display_name, handle: user.username, avatar: user.avatar, avatarColor: user.avatarColor,
        language: /^[a-z]{2,3}$/i.test(post.language || '') ? post.language : 'und',
        title: this.text(post.title), text: this.text(post.text), publishedAt: string(post.publishedAt) || null,
        verified: false, likes: count(post.likes), reposts: count(post.reposts), comments: count(post.comments),
        comment: post.comment === true || post.comment === 'true' || post.isReply === true || Boolean(post.replyTo),
        repostOf: this.postId(post.repostOf), replyTo: this.postId(post.replyTo),
        referenceType: post.referenceType === 'quotes' ? 'quotes' : 'reposts', images,
        ...(real ? {source: {platform: 'x', name: '수집 게시물 · 작성자 익명화',
          publishedOn: string(post.publishedAt).slice(0,10), metricsAvailable: {
            likes: post.source.metricsAvailable?.likes !== false,
            reposts: post.source.metricsAvailable?.reposts !== false,
            comments: post.source.metricsAvailable?.comments !== false}}} : {}),
      };
    });
  }
}
