import fs from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';

const retryDelays = [10, 20, 40, 80, 160, 320, 500];
const transientCodes = new Set(['EPERM', 'EACCES', 'EBUSY']);

export function logStorageError(context, error, extra = {}) {
  console.error(JSON.stringify({at: new Date().toISOString(), context,
    code: error.code, syscall: error.syscall, path: error.path, dest: error.dest,
    message: error.message, stack: error.stack, ...extra}));
}

/** Never delete the previous destination: a failed replacement leaves its complete JSON intact. */
export async function atomicJson(filename, data, {rename = fs.rename, wait = delay,
  onRetry = (error, attempt, waitMs) => logStorageError('atomic-json.rename-retry', error, {attempt, waitMs})} = {}) {
  const temporary = filename + '.' + randomUUID() + '.tmp';
  try {
    await fs.writeFile(temporary, JSON.stringify(data, null, 2), {flag: 'wx'});
    for (let attempt = 0; ; attempt++) {
      try {
        await rename(temporary, filename);
        return;
      } catch (error) {
        if (!transientCodes.has(error.code) || attempt >= retryDelays.length) throw error;
        onRetry(error, attempt + 1, retryDelays[attempt]);
        await wait(retryDelays[attempt]);
      }
    }
  } finally {
    await fs.unlink(temporary).catch(() => {});
  }
}
