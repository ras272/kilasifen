export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <span className="brand">
      <span className="brand-mark" aria-hidden="true">
        <span>K</span>
      </span>
      {!compact && (
        <span className="brand-wordmark">
          KilaSifen <small>DOCS</small>
        </span>
      )}
    </span>
  );
}
