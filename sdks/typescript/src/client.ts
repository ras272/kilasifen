import { HttpClient, type HttpClientOptions } from "./http";
import {
  DocumentsResource,
  EventsResource,
  FacturasResource,
  JobsResource,
  NotasCreditoResource,
  NotasDebitoResource,
  QueriesResource,
  WebhooksResource,
} from "./resources";

export type KilaSifenOptions = HttpClientOptions;

export class KilaSifen {
  readonly facturas: FacturasResource;
  readonly notasCredito: NotasCreditoResource;
  readonly notasDebito: NotasDebitoResource;
  readonly documents: DocumentsResource;
  readonly jobs: JobsResource;
  readonly queries: QueriesResource;
  readonly events: EventsResource;
  readonly webhooks: WebhooksResource;

  constructor(options: KilaSifenOptions) {
    const http = new HttpClient(options);
    this.facturas = new FacturasResource(http);
    this.notasCredito = new NotasCreditoResource(http);
    this.notasDebito = new NotasDebitoResource(http);
    this.documents = new DocumentsResource(http);
    this.jobs = new JobsResource(http);
    this.queries = new QueriesResource(http);
    this.events = new EventsResource(http);
    this.webhooks = new WebhooksResource(http);
  }
}
