import type { MetadataRoute } from 'next';
import { getSiteUrl } from '@/lib/shared';

export default function robots(): MetadataRoute.Robots {
  const origin = getSiteUrl();
  return {
    rules: { userAgent: '*', allow: '/' },
    sitemap: `${origin}/sitemap.xml`,
  };
}
