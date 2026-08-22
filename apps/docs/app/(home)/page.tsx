import { ArrowUpRight } from 'lucide-react';
import Link from 'next/link';

const steps = [
  ['01', 'Autenticá', 'Una API key privada para tu backend.'],
  ['02', 'Configurá', 'Emisor, certificado y timbrado.'],
  ['03', 'Emití', 'Una intención tipada e idempotente.'],
  ['04', 'Recibí', 'Estado final por webhook o polling.'],
];

const signalLines = Array.from({ length: 34 }, (_, row) => {
  const points = Array.from({ length: 30 }, (_, column) => {
    const x = 42 + column * 20;
    const distance = Math.abs(row - 16.5) / 16.5;
    const amplitude = 8 + (1 - distance) * 26;
    const wave = Math.sin(column * 0.7 + row * 0.41) * amplitude;
    const interference = Math.cos(column * 0.23 - row * 0.62) * 8;
    return `${x},${54 + row * 16 + wave + interference}`;
  });

  return `M ${points.join(' L ')}`;
});

function FiscalSignal() {
  return (
    <svg
      aria-hidden="true"
      className="fiscal-signal"
      preserveAspectRatio="xMidYMid slice"
      viewBox="0 0 660 660"
    >
      <defs>
        <clipPath id="signal-window">
          <circle cx="355" cy="330" r="278" />
        </clipPath>
      </defs>
      <circle className="signal-sun" cx="355" cy="330" r="278" />
      <g className="signal-lines" clipPath="url(#signal-window)">
        {signalLines.map((path, index) => (
          <path d={path} key={index} vectorEffect="non-scaling-stroke" />
        ))}
      </g>
      <circle className="signal-orbit" cx="355" cy="330" r="226" />
      <circle className="signal-core" cx="355" cy="330" r="7" />
      <path className="signal-axis" d="M355 30V630M55 330H655" />
    </svg>
  );
}

export default function HomePage() {
  return (
    <main className="landing-shell">
      <section className="landing-hero">
        <div className="signal-stage">
          <FiscalSignal />
          <span className="signal-label signal-label-top">PY / 001</span>
          <span className="signal-label signal-label-bottom">CDC / VERIFIED</span>
        </div>

        <div className="landing-hero-copy">
          <p className="landing-kicker">
            <span>API fiscal paraguaya</span>
            SIFEN, sin acoplamiento
          </p>
          <h1>
            Tu ERP factura.
            <span>Nosotros hablamos SIFEN.</span>
          </h1>
          <div className="landing-intro">
            <p>
              Emití documentos electrónicos desde una API estable. Sin XML,
              certificados ni reintentos metidos en tu producto.
            </p>
            <div className="landing-actions">
              <Link className="landing-primary" href="/docs/inicio-rapido">
                Integrar ahora <ArrowUpRight aria-hidden="true" size={18} />
              </Link>
              <Link className="landing-secondary" href="/docs/api-reference">
                Ver referencia API
              </Link>
            </div>
          </div>
        </div>

        <p className="landing-capabilities">
          Facturas <span>·</span> Notas de crédito <span>·</span> KuDE
          {' '}<span>·</span> Webhooks <span>·</span> Idempotencia
        </p>
      </section>

      <section className="landing-route">
        <div className="route-heading">
          <p>Una integración. Cuatro movimientos.</p>
          <h2>De la venta al DTE aprobado.</h2>
        </div>

        <ol className="route-sequence">
          {steps.map(([number, title, description]) => (
            <li key={number}>
              <span>{number}</span>
              <h3>{title}</h3>
              <p>{description}</p>
            </li>
          ))}
        </ol>

        <div className="route-closing">
          <p>
            <strong>Un timeout no crea otra factura.</strong>
            El mismo intento conserva identidad, CDC y trazabilidad.
          </p>
          <Link href="/docs/estados-y-reintentos">
            Ver cómo recuperamos errores <ArrowUpRight aria-hidden="true" size={18} />
          </Link>
        </div>
      </section>
    </main>
  );
}
