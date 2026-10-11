import React from 'react';
import {MoreHorizontal,MessageCircle,Repeat2,Heart,Bookmark,Share2} from 'lucide-react';
import Avatar from './Avatar';

function PostImages({images=[],onOpen}) {
  if (!images.length) return null;
  return <figure className={'post-media media-count-'+images.length}>
    <div className="media-grid">{images.map((image,index)=><button key={image.url} type="button" onClick={()=>onOpen(images,index)} aria-label={`첨부 이미지 ${index+1} 확대: ${image.alt}`}><img data-attachment src={image.url} alt={image.alt} loading="lazy" width={image.width||undefined} height={image.height||undefined}/></button>)}</div>
    <figcaption>첨부 이미지 {images.length}장 · 클릭하여 확대</figcaption>
  </figure>;
}

function metricValue(post,key) { return post.source?.metricsAvailable?.[key]===false?'—':post[key]; }
function postTime(value) {
  if (!value || !Number.isFinite(Date.parse(value))) return '시각 미상';
  return new Date(value).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',second:'2-digit',fractionalSecondDigits:3,hour12:false,timeZone:'Asia/Seoul'});
}

export default function Post({post,original,focused,onNavigate,onProfile,onOpenImage,onLike,onRepost,onBookmark}) {
  const profileUrl='/profile/'+post.anonymous_user_id;
  const visit=event=>onProfile(event,post.anonymous_user_id);
  return <article id={post.id} className={'post'+(focused?' post-focused':'')} tabIndex={-1} aria-label={post.name+'의 게시물'} data-post-id={post.id} data-anonymous-user-id={post.anonymous_user_id} lang={post.language} data-repost-of={post.repostOf||undefined} data-likes={post.likes} data-reposts={post.reposts} data-comments={post.comments}>
    <a className="avatar-link" href={profileUrl} onClick={visit} aria-label={post.name+' 프로필 보기'}><Avatar initials={post.avatar} color={post.avatarColor}/></a>
    <div className="post-body">
      <div className="post-heading">
        <a data-author-id={post.anonymous_user_id} href={profileUrl} onClick={visit}><b>{post.name}</b></a>
        <a className="muted" href={profileUrl} onClick={visit}>@{post.handle}</a>
        <span className="muted">· <time dateTime={post.publishedAt||undefined} title={post.publishedAt||undefined}>{postTime(post.publishedAt)}</time></span>
        <a data-permalink onClick={event=>onNavigate(event,post.id)} href={'/#'+post.id} className="permalink" aria-label="게시물 고유 링크">↗</a>
        <small className="lang">{post.language.toUpperCase()}</small><MoreHorizontal className="more" size={18}/>
      </div>
      {post.title&&<h3 className="post-title">{post.title}</h3>}
      <p className="post-content">{post.text.split(/(https?:\/\/[^\s]+)/g).map((part,i)=>/^https?:\/\//.test(part)?<a key={i} href={part} target="_blank" rel="noreferrer">{part}</a>:part)}</p>
      {post.source&&<div className="post-source"><span>{post.source.name} · {post.source.publishedOn} · 진위 미판정{Object.values(post.source.metricsAvailable||{}).some(value=>!value)?' · 반응 수 미수집':''}</span></div>}
      <PostImages images={post.images} onOpen={onOpenImage}/>
      {post.repostOf&&<div className="quoted-post"><span><Repeat2 size={13}/> 의견을 붙인 재게시</span>{original&&<a href={'/profile/'+original.anonymous_user_id} onClick={event=>onProfile(event,original.anonymous_user_id)}>@{original.handle}</a>} <a onClick={event=>onNavigate(event,post.repostOf)} href={'/#'+post.repostOf}>원문 보기 ↗</a>{original&&<div>{original.text}</div>}</div>}
      <div className="actions">
        <span className="action"><MessageCircle size={18}/>{metricValue(post,'comments')}</span>
        <button className={'action '+(post.reposted?'green':'')} onClick={()=>onRepost(post.id)} aria-label="재게시"><Repeat2 size={18}/>{metricValue(post,'reposts')}</button>
        <button className={'action '+(post.liked?'pink':'')} onClick={()=>onLike(post.id)} aria-label="좋아요"><Heart size={18} fill={post.liked?'currentColor':'none'}/>{metricValue(post,'likes')}</button>
        <button className={'action '+(post.bookmarked?'blue':'')} onClick={()=>onBookmark(post.id)} aria-label="북마크"><Bookmark size={18} fill={post.bookmarked?'currentColor':'none'}/></button>
        <button className="action" onClick={()=>navigator.clipboard?.writeText(post.text)} aria-label="본문 복사"><Share2 size={18}/></button>
      </div>
    </div>
  </article>;
}
