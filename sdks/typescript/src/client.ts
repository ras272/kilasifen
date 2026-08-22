import { HttpClient, type HttpClientOptions } from "./http";
import {
  DocumentsResource,
  FacturasResource,
  JobsResource,
  NotasCreditoResource,
} from "./resources";

export type KilaSifenOptions = HttpClientOptions;

export class KilaSifen {
  readonly facturas: FacturasResource;
  readonly notasCredito: NotasCreditoResource;
  readonly documents: DocumentsResource;
  readonly jobs: JobsResource;

  constructor(options: KilaSifenOptions) {
    const http = new HttpClient(options);
    this.facturas = new FacturasResource(http);
    this.notasCredito = new NotasCreditoResource(http);
    this.documents = new DocumentsResource(http);
    this.jobs = new JobsResource(http);
  }
}
