import { Brand } from '@/components/brand';
import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';
import { gitConfig } from './shared';

export function baseOptions(): BaseLayoutProps {
  return {
    nav: { title: <Brand /> },
    githubUrl: `https://github.com/${gitConfig.user}/${gitConfig.repo}`,
    themeSwitch: { enabled: false },
    links: [
      { text: 'Inicio rápido', url: '/docs/inicio-rapido', active: 'nested-url' },
      { text: 'API', url: '/docs/api-reference', active: 'nested-url' },
    ],
  };
}
