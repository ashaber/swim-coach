const MAX_ENTRIES = 200;
const STORAGE_KEY = 'swimcoach_log';

const log = {
  info: (msg, meta = {}) => _write('info', msg, meta),
  warn: (msg, meta = {}) => _write('warn', msg, meta),
  error: (msg, meta = {}) => _write('error', msg, meta),
};

function _write(level, msg, meta) {
  console[level]?.(msg, meta);

  try {
    const entries = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    entries.push({ level, msg, ...meta, ts: new Date().toISOString() });
    if (entries.length > MAX_ENTRIES) entries.splice(0, entries.length - MAX_ENTRIES);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // localStorage unavailable (private mode quota, etc.) — console only
  }
}

export default log;
export { STORAGE_KEY };
