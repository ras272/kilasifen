import { RootProvider } from 'fumadocs-ui/provider/next';
import type { Metadata } from 'next';
import { getSiteUrl } from '@/lib/shared';
import { spanishUi } from '@/lib/translations';
import './global.css';

export const metadata: Metadata = {
  metadataBase: new URL(getSiteUrl()),
  title: {
    default: 'KilaSifen Docs',
    template: '%s — KilaSifen Docs',
  },
  description: 'Integrá facturación electrónica paraguaya sin acoplar tu ERP a SIFEN.',
};

export default function Layout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="es" suppressHydrationWarning>
      <body className="flex min-h-screen flex-col">
        <RootProvider i18n={{ locale: 'es', translations: spanishUi }} theme={{ enabled: false }}>
          {children}
        </RootProvider>
      </body>
    </html>
  );
}
