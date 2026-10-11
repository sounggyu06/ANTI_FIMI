import React from 'react';
import Avatar from './Avatar';

export default function Profile({user,status,posts,renderPost,onHome}) {
  if (status==='loading') return <div className="empty" role="status">프로필을 불러오는 중입니다.</div>;
  if (status==='error') return <div className="empty" role="alert">프로필을 불러오지 못했습니다. 잠시 후 다시 확인하세요.</div>;
  if (!user) return <section className="profile-not-found"><h2>프로필을 찾을 수 없습니다</h2><p>존재하지 않는 계정 주소입니다.</p><button onClick={onHome}>홈으로 돌아가기</button></section>;
  return <>
    <section className="profile-card" aria-label={user.display_name+' 프로필'}>
      <div className="profile-cover"/>
      <div className="profile-details">
        <Avatar initials={user.avatar} color={user.avatarColor} size={88}/>
        <h2>{user.display_name}</h2><p className="profile-username">@{user.username}</p>
        <p className="profile-bio">{user.bio}</p>
        <p className="profile-count"><strong>{posts.length}</strong> 게시물</p>
        <div className="profile-social"><span><strong>{user.following??'—'}</strong> 팔로잉</span><span><strong>{user.followers??'—'}</strong> 팔로워</span></div>
        <small className="muted">팔로우 수는 수집하지 않았습니다.</small>
      </div>
      <div className="profile-tab">게시물</div>
    </section>
    {posts.length ? posts.map(renderPost) : <div className="empty">아직 작성한 게시물이 없습니다.</div>}
  </>;
}
