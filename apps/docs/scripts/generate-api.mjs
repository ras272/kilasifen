import { readFile, writeFile } from 'node:fs/promises';
import { generateFiles } from 'fumadocs-openapi';
import { createOpenAPI } from 'fumadocs-openapi/server';

const openapi = createOpenAPI({
  input: ['./public/openapi.json'],
});

await generateFiles({
  input: openapi,
  output: './content/docs/api-reference',
  per: 'tag',
  meta: true,
  index: {
    url: {
      baseUrl: '/docs',
      contentDir: './content/docs',
    },
    items: [
      {
        path: 'index.mdx',
        description: 'Rutas y esquemas generados desde el contrato OpenAPI de KilaSifen.',
      },
    ],
  },
  includeDescription: true,
  addGeneratedComment: 'Generado desde public/openapi.json. No editar manualmente.',
});

const indexPath = './content/docs/api-reference/index.mdx';
const generatedIndex = await readFile(indexPath, 'utf8');
const normalizedIndex = generatedIndex
  .replace('title: Overview', 'title: Referencia API')
  .replaceAll('/docs/..%5C..%5C', '/docs/api-reference/');

if (normalizedIndex.includes('%5C') || normalizedIndex.includes('/../')) {
  throw new Error('La referencia OpenAPI contiene enlaces no portables.');
}

await writeFile(indexPath, normalizedIndex, 'utf8');
