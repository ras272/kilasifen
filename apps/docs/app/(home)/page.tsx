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
            <span aria-hidden="true" /> Código abierto (MIT) · Autohospedado · Alpha
          </p>
          <h1>Una API sencilla para conectar con SIFEN.</h1>
          <p className="simple-hero-copy">
            Vos enviás la venta; KilaSifen arma el XML, lo firma, lo transmite a
            SIFEN y sigue su estado. Lo instalás y operás en tu propia
            infraestructura.
          </p>
          <Link className="simple-hero-action" href="/docs/inicio-rapido">
            Comenzar <ArrowRight aria-hidden="true" size={18} />
          </Link>
        </div>
      </section>
    </main>
  );
}
