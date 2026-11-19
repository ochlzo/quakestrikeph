export interface Settings {
  databaseUrl: string;
  modelReleaseId: string;
  port: number;
  poolSize: number;
  queryTimeoutMs: number;
  brevoCallbackToken?: string;
  simulations?: { url: URL; serviceToken: string; cookieKey: string; pageToken: string; ingressKey?: string; localIngress: boolean };
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
  const brevoCallbackToken = env.BREVO_CALLBACK_TOKEN || undefined;
  if (brevoCallbackToken && !/^[\x21-\x7e]{32,1024}$/.test(brevoCallbackToken)) {
    throw new Error('BREVO_CALLBACK_TOKEN must contain 32 to 1024 non-space ASCII characters');
  }
  return {
    databaseUrl: env.DATABASE_URL,
    modelReleaseId: env.MODEL_RELEASE_ID,
    port: integerSetting(env.PORT, 3000, 1, 65535, 'PORT'),
    poolSize: integerSetting(env.DB_POOL_SIZE, 5, 1, 20, 'DB_POOL_SIZE'),
    queryTimeoutMs: integerSetting(env.DB_QUERY_TIMEOUT_MS, 3000, 100, 30000, 'DB_QUERY_TIMEOUT_MS'),
    brevoCallbackToken,
    simulations: simulationSettings(env),
  };
}

function simulationSettings(env: NodeJS.ProcessEnv): Settings['simulations'] {
  if (!env.SIMULATION_SERVICE_URL) return undefined;
  const url = new URL(env.SIMULATION_SERVICE_URL);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
    url.pathname !== '/' || url.search || url.hash) throw new Error('SIMULATION_SERVICE_URL must be an HTTP origin');
  const serviceToken = env.SIMULATION_SERVICE_TOKEN ?? '';
  const cookieKey = env.SIMULATION_COOKIE_KEY ?? '';
  const pageToken = env.SIMULATION_PAGE_TOKEN ?? '';
  const ingressKey = env.SIMULATION_INGRESS_KEY || undefined;
  const localIngress = env.SIMULATION_LOCAL_INGRESS === 'true';
  const secret = /^[a-f0-9]{64}$/;
  if (!secret.test(serviceToken) || !secret.test(cookieKey) || !secret.test(pageToken) ||
    (ingressKey ? localIngress || !secret.test(ingressKey) : !localIngress)) {
    throw new Error('Configure simulation secrets and exactly one ingress mode');
  }
  return { url, serviceToken, cookieKey, pageToken, ingressKey, localIngress };
}
