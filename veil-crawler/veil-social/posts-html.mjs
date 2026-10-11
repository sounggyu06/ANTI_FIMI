// 현재 피드 데이터를 requests/BeautifulSoup으로 읽을 수 있는 HTML로 표현합니다.
// 새 게시물을 만들거나 분석용 라벨을 노출하지 않습니다.
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

function imageUrl(value) {
  try {
    const text = String(value ?? '').trim();
    const url = new URL(text, 'http://localhost');
    return text && ['http:', 'https:'].includes(url.protocol) ? text : null;
  } catch { return null; }
}

/** UI의 /api/posts와 동일한 게시물 배열을 한 번에 렌더링합니다. */
export function renderPostsHtml(posts) {
  const articles = posts.map(post => {
    const images = (Array.isArray(post.images) ? post.images : []).map(image => {
      const url = imageUrl(image.url);
      return url ? `<img class="post-image" src="${escapeHtml(url)}" alt="${escapeHtml(image.alt)}">` : '';
    }).join('\n');
    const original = post.repostOf ? ` data-retweet-original="${escapeHtml(post.repostOf)}" data-reference-type="${post.referenceType === 'quotes' ? 'quotes' : 'reposts'}"` : '';
    const reply = post.replyTo ? ` data-reply-to="${escapeHtml(post.replyTo)}"` : '';
    const isComment = post.comment === true || post.comment === 'true' || post.isReply === true || Boolean(post.replyTo);
    return `<article class="post" data-post-id="${escapeHtml(post.id)}" data-author-id="${escapeHtml(post.authorId ?? post.handle)}" data-comment="${isComment ? 'true' : 'false'}" data-reposts="${escapeHtml(post.reposts ?? 0)}" data-language="${escapeHtml(post.language || 'und')}"${original}${reply}>
  <h2 class="account-name">${escapeHtml(post.name ?? post.handle)}</h2>
  ${post.title ? `<h3 class="post-title">${escapeHtml(post.title)}</h3>` : ''}
  <p class="post-content">${escapeHtml(post.text)}</p>
  ${images}
  <time class="post-time" datetime="${escapeHtml(post.publishedAt)}">${escapeHtml(post.publishedAt)}</time>
  <span class="like-count">${escapeHtml(post.likes ?? 0)}</span>
</article>`;
  }).join('\n');
  return `<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>VEIL Social 게시물 수집</title></head>
<body><h1>VEIL Social 현재 게시물</h1>
<p>시뮬레이션 화면과 동일한 저장 데이터를 제공하는 HTML입니다. 총 ${posts.length}개.</p>
${articles}
</body></html>`;
}
