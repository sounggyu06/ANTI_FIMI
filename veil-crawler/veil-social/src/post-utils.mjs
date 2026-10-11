/** 원본 작성자명이 아니라 공개 익명 ID로만 게시 이력을 찾습니다. */
export function postsByUser(posts, anonymousId) {
  return posts.filter(post => post.anonymous_user_id === anonymousId)
    .sort((a,b) => (Date.parse(b.publishedAt) || 0) - (Date.parse(a.publishedAt) || 0));
}

export function profileIdFromPath(pathname) {
  const match = /^\/profile\/(anon_\d{4,})\/?$/.exec(pathname);
  return match ? match[1] : null;
}

/** 예전 서버의 원본 작성자 응답은 화면에 그리지 않습니다. */
export function isAnonymousPost(post) {
  return Boolean(post && /^anon_\d{4,}$/.test(post.anonymous_user_id || '') &&
    post.authorId === post.anonymous_user_id && /^post_[a-f0-9]{24}$/.test(post.id || ''));
}
