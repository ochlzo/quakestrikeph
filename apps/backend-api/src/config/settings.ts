export interface Settings {
  databaseUrl: string;
  modelReleaseId: string;
  port: number;
  poolSize: number;
  queryTimeoutMs: number;
}

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function integerSetting(value: string | undefined, fallback: number, min: number, max: number, name: string): number {
  if (value === undefined) return fallback;
  if (!/^\d+$/.test(value)) throw new Error(`${name} must be an integer`);
  const parsed = Number(value);
  if (parsed < min || parsed > max) throw new Error(`${name} must be between ${min} and ${max}`);
  return parsed;
}

export function loadSettings(env: NodeJS.ProcessEnv = process.env): Settings {
  if (!env.DATABASE_URL) throw new Error('DATABASE_URL is required');
  if (!env.MODEL_RELEASE_ID || !uuid.test(env.MODEL_RELEASE_ID)) throw new Error('MODEL_RELEASE_ID must be a UUID');
  const database = new URL(env.DATABASE_URL);
  if (database.protocol !== 'postgres:' && database.protocol !== 'postgresql:') {
    throw new Error('DATABASE_URL must use PostgreSQL');
  }
  if (!database.hostname) {
    throw new Error('DATABASE_URL has an invalid host');
  }
  return {
    databaseUrl: env.DATABASE_URL,
    modelReleaseId: env.MODEL_RELEASE_ID,
    port: integerSetting(env.PORT, 3000, 1, 65535, 'PORT'),
    poolSize: integerSetting(env.DB_POOL_SIZE, 5, 1, 20, 'DB_POOL_SIZE'),
    queryTimeoutMs: integerSetting(env.DB_QUERY_TIMEOUT_MS, 3000, 100, 30000, 'DB_QUERY_TIMEOUT_MS'),
  };
}
