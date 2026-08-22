import { AsciiArt } from '@/components/ui/sss';
import { ArrowRight } from 'lucide-react';
import Link from 'next/link';

export default function HomePage() {
  return (
    <main className="landing-shell">
      <section className="simple-hero">
        <AsciiArt className="simple-hero-media" />
        <div className="simple-hero-shade" aria-hidden="true" />

        <div className="simple-hero-content">
          <p className="availability">
            <span aria-hidden="true" /> Slots free por ahora
          </p>
          <h1>Una API sencilla para conectar con SIFEN.</h1>
          <p className="simple-hero-copy">
            Olvidate del XML, los certificados y los reintentos. Vos enviás la
            venta; KilaSifen se encarga del resto.
          </p>
          <Link className="simple-hero-action" href="/docs/inicio-rapido">
            Comenzar <ArrowRight aria-hidden="true" size={18} />
          </Link>
        </div>
      </section>
    </main>
  );
}
