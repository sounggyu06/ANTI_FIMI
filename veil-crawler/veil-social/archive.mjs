import { DatabaseSync } from 'node:sqlite';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';

export function archiveDirectory(env=process.env) {
  return env.VEIL_ARCHIVE_DIR || (env.VEIL_DATA_DIR ? path.join(env.VEIL_DATA_DIR,'archive') : fileURLToPath(new URL('../runtime/archive/', import.meta.url)));
}
export class PostArchive {
  constructor(directory) {
    fs.mkdirSync(directory,{recursive:true});
    this.directory=directory;
    this.db=new DatabaseSync(path.join(directory,'posts.sqlite'));
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS posts(id TEXT PRIMARY KEY, published_at TEXT NOT NULL, first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,record TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS posts_published ON posts(published_at DESC,id);
      CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,completed_at TEXT NOT NULL,record TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS observations(run_id TEXT NOT NULL,post_id TEXT NOT NULL,record TEXT NOT NULL,PRIMARY KEY(run_id,post_id));
      CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,record TEXT NOT NULL);`);
  }
  getSetting(key,fallback) {
    const row=this.db.prepare('SELECT record FROM settings WHERE key=?').get(key);
    return row?JSON.parse(row.record):fallback;
  }
  setSetting(key,value) {this.db.prepare('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET record=excluded.record').run(key,JSON.stringify(value));}
  saveBatch(posts,state={}) {
    const runId=randomUUID(),at=state.collectedAt || new Date().toISOString();
    const save=this.db.prepare(`INSERT INTO posts VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET published_at=excluded.published_at,last_seen=excluded.last_seen,record=excluded.record`);
    const observe=this.db.prepare('INSERT OR REPLACE INTO observations VALUES(?,?,?)');
    let added=0;
    this.db.exec('BEGIN IMMEDIATE');
    try {
      for(const post of posts) {
        if(post.source?.platform!=='x' || !post.id.startsWith('x-'))throw new Error('Only X source records may enter this archive');
        if(!this.db.prepare('SELECT 1 FROM posts WHERE id=?').get(post.id))added++;
        const record=JSON.stringify(post);
        save.run(post.id,post.publishedAt,at,at,record);observe.run(runId,post.id,record);
      }
      const savedState={...state,newPosts:added,runId};
      this.db.prepare('INSERT INTO runs VALUES(?,?,?)').run(runId,at,JSON.stringify(savedState));
      this.setSetting('import',savedState);
      this.db.exec('COMMIT');return savedState;
    }catch(error){this.db.exec('ROLLBACK');throw error;}
  }
  count(){return this.db.prepare('SELECT count(*) AS n FROM posts').get().n;}
  latest(limit=200){return this.db.prepare('SELECT record FROM posts ORDER BY published_at DESC,id LIMIT ?').all(limit).map(row=>JSON.parse(row.record));}
  *records(){for(const row of this.db.prepare('SELECT record FROM posts ORDER BY published_at DESC,id').iterate())yield JSON.parse(row.record);}
  exportJsonl(destination) {
    fs.mkdirSync(path.dirname(path.resolve(destination)),{recursive:true});
    const tmp=destination+'.tmp',fd=fs.openSync(tmp,'w');
    try{for(const post of this.records())fs.writeSync(fd,JSON.stringify(post)+'\n');}
    finally{fs.closeSync(fd);}
    fs.renameSync(tmp,destination);return this.count();
  }
  close(){this.db.close();}
}
