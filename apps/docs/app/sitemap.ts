import type { MetadataRoute } from 'next';
import { getSiteUrl } from '@/lib/shared';
import { source } from '@/lib/source';

export default function sitemap(): MetadataRoute.Sitemap {
  const origin = getSiteUrl();
  return [
    { url: origin, changeFrequency: 'monthly', priority: 1 },
    ...source.getPages().map((page) => ({
      url: `${origin}${page.url}`,
      changeFrequency: 'weekly' as const,
      priority: page.slugs.length === 0 ? 0.9 : 0.7,
    })),
  ];
}
