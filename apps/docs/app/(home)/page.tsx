import { ArrowRight, Check, FileCheck2, RefreshCcw, ShieldCheck } from 'lucide-react';
import Link from 'next/link';

const steps = [
  ['01', 'Credencial', 'Autenticá tu backend con X-API-Key.'],
  ['02', 'Emisor', 'Registrá timbrado, CSC y certificado.'],
  ['03', 'Documento', 'Enviá una intención tipada e idempotente.'],
  ['04', 'Resultado', 'Consumí el estado final por webhook o polling.'],
];

export default function HomePage() {
  return (
    <main className="landing-shell">
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Infraestructura fiscal paraguaya</p>
          <h1>
            Emití. Consultá.
            <span> Conciliá.</span>
          </h1>
          <p className="hero-lede">
            Una API para que tu ERP hable con SIFEN sin mezclar certificados,
            XML ni reintentos con tu lógica de negocio.
          </p>
          <div className="hero-actions">
            <Link className="primary-action" href="/docs/inicio-rapido">
              Empezar integración <ArrowRight size={17} />
            </Link>
            <Link className="text-action" href="/docs/api-reference">
              Explorar la API
            </Link>
          </div>
          <ul className="assurances" aria-label="Garantías del contrato">
            <li><ShieldCheck size={16} /> Multi-tenant</li>
            <li><RefreshCcw size={16} /> Idempotente</li>
            <li><FileCheck2 size={16} /> Contrato tipado</li>
          </ul>
        </div>

        <div className="request-sheet" aria-label="Ejemplo de emisión de factura">
          <div className="sheet-heading">
            <span className="method">POST</span>
            <code>/v1/emitters/&#123;id&#125;/documents/facturas</code>
          </div>
          <pre><code>{`{
  "external_id": "venta_1842",
  "idempotency_key": "venta_1842_v1",
  "factura": {
    "establecimiento": "001",
    "punto": "001",
    "moneda": "PYG",
    "cliente": {
      "ruc": "80000000-0",
      "razon_social": "Cliente ejemplo"
    },
    "items": [{
      "descripcion": "Servicio mensual",
      "cantidad": 1,
      "precio_unitario": 150000,
      "tasa": 10
    }]
  }
}`}</code></pre>
          <div className="sheet-result">
            <span><Check size={15} /> 201 Created</span>
            <code>status: queued</code>
          </div>
        </div>
      </section>

      <section className="contract-strip" aria-label="Información de versión">
        <span>CONTRATO <strong>v1</strong></span>
        <span>AMBIENTE <strong>SIFEN Test</strong></span>
        <span>ESQUEMA <strong>OpenAPI 3.1</strong></span>
      </section>

      <section className="integration-path">
        <div className="section-intro">
          <p className="eyebrow">El recorrido completo</p>
          <h2>De una venta a un DTE aprobado.</h2>
          <p>Cuatro contratos claros. Cada paso queda durable y observable.</p>
        </div>
        <ol className="step-ledger">
          {steps.map(([number, title, description]) => (
            <li key={number}>
              <span className="step-number">{number}</span>
              <div><h3>{title}</h3><p>{description}</p></div>
            </li>
          ))}
        </ol>
      </section>

      <section className="closing-note">
        <p>Construido para fallar de forma explícita.</p>
        <h2>Un timeout no crea otra factura.</h2>
        <p>
          KilaSifen conserva el CDC y el XML exacto, consulta primero el estado
          en SIFEN y sólo reintenta cuando corresponde.
        </p>
        <Link href="/docs/estados-y-reintentos">Entender el ciclo de vida <ArrowRight size={16} /></Link>
      </section>
    </main>
  );
}
