export const appName = 'KilaSifen Docs';
export const docsRoute = '/docs';
export const docsImageRoute = '/og/docs';
export const docsContentRoute = '/llms.mdx/docs';

export function getSiteUrl(): string {
  const vercelHostname =
    process.env.VERCEL_PROJECT_PRODUCTION_URL ?? process.env.VERCEL_URL;

  if (process.env.NEXT_PUBLIC_SITE_URL) return process.env.NEXT_PUBLIC_SITE_URL;
  if (vercelHostname) return `https://${vercelHostname}`;
  return 'http://localhost:3000';
}

export const gitConfig = {
  user: 'ras272',
  repo: 'kilasifen',
  branch: 'main',
};
