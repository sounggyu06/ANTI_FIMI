import test from 'node:test';
import assert from 'node:assert/strict';
import { renderPostsHtml } from '../posts-html.mjs';
import { beginSimulation, advanceSimulation } from '../simulation.mjs';

test('HTML exposes the actual simulation posts, likes, images and quote origins', () => {
  const start = beginSimulation([], new Date('2026-10-10T04:00:00Z'));
  const wave = advanceSimulation(start.posts, start.state);
  const html = renderPostsHtml(wave.posts);
  assert.equal((html.match(/<article /g) || []).length, wave.posts.length);
  assert.equal((html.match(/data-retweet-original=/g) || []).length, 4);
  assert.equal((html.match(/data-reference-type="quotes"/g) || []).length, 4);
  assert.ok(html.includes(`data-post-id="${start.state.rootId}"`));
  assert.ok(html.includes('<span class="like-count">123</span>'));
  assert.ok(html.includes('src="/media/relief-news.jpg"'));
  assert.ok(!html.includes('simulationRunId'));
  assert.ok(!html.includes('evaluationLabel'));
});

test('text and attributes are escaped and executable image URLs excluded', () => {
  const html = renderPostsHtml([{id:'id" onclick="alert(1)',name:'<script>name</script>',
    text:'본문 <img src=x onerror=alert(1)> & 인용',likes:0,
    images:[{url:'javascript:alert(1)'},{url:'/photo.jpg',alt:'" onerror="alert(1)'}]}]);
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('javascript:'));
  assert.ok(html.includes('&lt;img'));
  assert.ok(html.includes('id&quot; onclick=&quot;alert(1)'));
  assert.ok(html.includes('src="/photo.jpg"'));
});


test('author IDs and retweet counts are preserved; comments do not mean reply counts or quote posts', () => {
  const html = renderPostsHtml([
    {id:'x-1',authorId:'user_001',handle:'display_handle',text:'글',reposts:3,likes:12,comments:72,repostOf:'root'},
    {id:'reply',handle:'sim_user',text:'댓글',reposts:0,isReply:true},
  ]);
  assert.ok(html.includes('data-author-id="user_001" data-comment="false" data-reposts="3"'));
  assert.ok(html.includes('data-author-id="sim_user" data-comment="true" data-reposts="0"'));
});
