import React from 'react';

// 원본 프로필 사진 대신 계정별로 고정된 색상과 이니셜을 표시합니다.
export default function Avatar({initials,color,size=45}) {
  return <div className="avatar" aria-hidden="true" style={{background:color,width:size,height:size,minWidth:size}}>{initials}</div>;
}
