import { randomInt } from 'node:crypto';
import { clearSimulation } from './simulation.mjs';
import { mergeXPosts } from './x-collector.mjs';

/** 서버를 시작할 때만 순서를 섞습니다. 폴링할 때는 같은 순서를 유지합니다. */
export function prepareStartup(posts, archived, draw = randomInt) {
  const clean = clearSimulation(posts);
  const merged = mergeXPosts(clean.posts.filter(post => post.source?.platform !== 'x'), archived);
  const shuffled = [...merged];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = draw(0, i + 1);
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  // 우연히 이전 순서와 똑같아진 경우에도 재실행 시 순서가 바뀌도록 합니다.
  if (shuffled.length > 1 && shuffled.every((post, i) => post.id === clean.posts[i]?.id)) {
    [shuffled[0], shuffled[1]] = [shuffled[1], shuffled[0]];
  }
  return {posts: shuffled, state: clean.state};
}
