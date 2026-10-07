# Fuentes oficiales SIFEN

Referencia de la normativa técnica vigente que sigue KilaSifen, con corte el
2026-10-01. Ante cualquier cambio fiscal (campos del XML, CDC, QR, totales,
códigos de respuesta, lote, eventos, KuDE), consultar estas fuentes en este
orden: la Nota Técnica más reciente que toque el tema, el Manual Técnico, los
XSD oficiales y, por encima de ambos, el Decreto 872/2023 y la RG 23/2019.
Las librerías de terceros son solo pistas, nunca fuente. La trazabilidad
regla por regla está en [`matriz.md`](matriz.md).

## Documentos base

| Documento | Versión / fecha | Enlace |
| --- | --- | --- |
| Manual Técnico SIFEN | v150, 10/09/2019 (no hay versión posterior) | [PDF](https://www.dnit.gov.py/documents/20123/420592/Manual+T%C3%A9cnico+Versi%C3%B3n+150.pdf) |
| Notas Técnicas | NT 01 a NT 27 (la última, 09/03/2026) | [Documentación técnica e-Kuatia](https://www.dnit.gov.py/web/e-kuatia/documentacion-tecnica) |
| XSD oficiales | mismos 47 archivos que `kilasifen/engine/de/schemas/v150/` | [ekuatia.set.gov.py/sifen/xsd](https://ekuatia.set.gov.py/sifen/xsd/) |
| Guía de Mejores Prácticas para la Gestión del Envío de DE | oct-2024 | [PDF](https://www.dnit.gov.py/documents/20123/420592/Gu%C3%ADa+de+Mejores+Pr%C3%A1cticas+para+la+Gesti%C3%B3n+del+Env%C3%ADo+de+DE.pdf/38fe5830-98c0-2241-9895-671f86f1225f?t=1729866823709) |
| Guía de Pruebas para e-Kuatia | feb-2026 | [PDF](https://www.dnit.gov.py/documents/20123/424160/Guia+de+Pruebas+para+e-kuatia.pdf/715a15bf-d866-afe3-49e2-c10e05242c95?t=1770659877488) |
| Función oficial del dígito verificador (módulo 11) | DNIT | [PDF](https://www.dnit.gov.py/documents/20123/224893/D%C3%ADgito+Verificador.pdf/fb9f86c8-245d-9dad-2dc1-ac3b3dc307a7) |
| Decreto 872/2023 | vigente desde 01/01/2024 (abroga el Dto. 7795/2017) | Portal DNIT, normativa e-Kuatia |
| RG 23/2019 | vigente (citada por la RG DNIT 01/2024) | [Resoluciones e-Kuatia](https://www.dnit.gov.py/web/e-kuatia/resoluciones) |

Para leer los PDF: `pdftotext -enc UTF-8 -layout <archivo>.pdf <archivo>.txt`.

## Notas Técnicas sobre el Manual Técnico v150

La columna "Test / Prod" es la fecha de puesta a disposición en cada ambiente
cuando la NT la indica.

| NT | Fecha | Test / Prod | Temas principales |
| --- | --- | --- | --- |
| [NT 01](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_001_MT_V150.pdf/c4d2ab8e-632b-dc8f-d3f6-6a144a3a3d9c?t=1687364545680) | 14/10/2019 | — | EA004 = F010*E721/100. Fórmulas de F009, F033, F034, F035, F011, F012 y F014 (=F008-F013+F025). Validaciones 1103, 1862, 2364 y 2365 modificadas. Nuevas: 1860, 2383, 2384, 2387 y 2388 |
| [NT 02](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_002_MT_V150.pdf/b3656789-f42a-e578-4141-45046e452f41?t=1687364545841) | 16/07/2020 | — | D208 iTipIDRec y D210 dNumIDRec: obligatorios si D201=2 y D202≠4. Se eliminan las validaciones D208d y D210a (1322 y 1323). Reemplazado por NT 23 |
| [NT 03](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_003_MT_V150.pdf/dd4689ee-164a-29b3-9c3f-44cbef55bcf5?t=1687364545998) | 18/11/2020 | — | D219 cDepRec y D223 cCiuRec: obligatorios si hay D213 y D202≠4; no se informan si D202=4. Se eliminan las validaciones 1324 y 1327 |
| [NT 04](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_004_MT_V150.pdf/97868c1a-ef6f-af63-025b-515e9564997e?t=1687364546153) | 29/12/2020 | — | Se elimina la validación D101a (1251, "RUC del emisor inhabilitado para FE") |
| [NT 05](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_005_MT_V150.pdf/098e75de-e878-7bcd-49ec-55c33a45a0a7?t=1687364546324) | 09/02/2021 | — | D204 dDesPaisRe con longitud 4-50. E965 dNroMatVeh con longitud 6-7, obligatorio si E967=2 |
| [NT 06](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_006_MT_V150+.pdf/9554f3e6-ffb6-17b6-bd53-4e4c87a8800d?t=1687364546470) | 25/03/2021 | — | Nueva validación D011a (1216): no se informa iTipTra si C002≠1 y C002≠4 |
| [NT 07](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_007_MT_V150.pdf/d6b31757-8906-a326-4e92-f9ec4b5d7706?t=1687364546603) | 01/02/2022 (rev. 24/02/2022) | — | B006 dInfoFisc (1-3000): mensaje obligatorio en Nota de Remisión (Art. 3 inc. 7 RG 41/2014). En FE de exportación, datos a) a j) (Art. 20 num. 15 Dto. 10797/2013) |
| [NT 08](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_008_MT_V150.pdf/81fba389-0f27-e757-88c3-ec7b3dbab90b?t=1687364546734) | 21/09/2021 | — | EA797 dCodInt de póliza (1-50). F023 dTotalGs: F014*D018 si D017=1, suma de EA009 si D017=2, no se informa si D015=PYG; se elimina la excepción de la autofactura |
| [NT 09](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_009_MT_V150.pdf/c268a447-11e3-ee1e-b4d5-8d83dd408401?t=1687364546900) | 09/09/2021 | — | E701 dCodInt (1-50, reglas de unicidad). E708 dDesProSer amplía su longitud a 1-2000 |
| [NT 10](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_010_MT_V150.pdf/d64a693b-6c63-86e1-ec6a-d4fe5ec4eeea?t=1687364547196) | 04/02/2022 | — | Elimina A005 dSisFact. D012 con lista 1-13. E505 dKmR. Rastreo E750-E761 (RG 106/2021). Transportista E980/E992/E993. H009/H010 incorporan el 5=Comprobante de retención. GEI009 dSerieNum en inutilización. xDE. rEnviConsDeRequest. C008 en el KuDE como DD-MM-AAAA. Validaciones D202 1300, D220 1325, D208b 1319, D208e 1331, D142 1265, H004g 2439, H004h 2441 y H005b 2440. **URL del QR** (prod y test). Observaciones del QR (dTotIVA=0, error 2501). **Tabla 6 de afectación** (2 = "Exonerado (Art. 100 - Ley 6380/2019)"). Namespace de eventos. Tabla B |
| [NT 11](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_011_MT_V150.pdf/faada1a3-f158-90fe-795a-c7f30e61fb84?t=1687364547032) | 20/10/2022 | — | Nuevo WS de consulta masiva de RUC `rEnviConsArchivoRUCRequest` (Schemas 20-22: WS_ConsultaArchivoRuc.xsd y siConsultaArchivoRuc.xsd). Códigos 0520-0523; una descarga diaria. Devuelve razón social, estado y si es facturador electrónico de todos los contribuyentes salvo los cancelados (los mismos datos que siConsRUC). No implementado: la NT no publica la dirección del WS ni el formato del archivo (NO DETERMINADO) |
| [NT 12](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_012_MT_V150.pdf/28807b7c-a7ee-9033-ab3f-75a0fcd52091?t=1687364547383) | 21/02/2023 | — | Validación 1213: la autofactura (C002=4) debe ir en moneda PYG (Dictamen DEINT N° 344/2022) |
| [NT 13](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_013_MT_V150.pdf/ba73ec3b-5901-ae28-5d8c-9bed5632ab89?t=1687364547529) | 20/03/2023 | 21/04/2023 / 17/06/2023 | **IVA gravado parcial**: nueva fórmula de E735. Nuevo campo E737 dBasExe. F002, F004 y F005 recalculados. Validaciones 1921, 1910, 1911, 2353, 2357 y 2359 |
| [NT 14](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_014_MT_V150X.pdf/dbbb0294-8678-357a-1657-bcd0318077f9?t=1706200657282) | 20/03/2023 | 31/05/2023 / 08/08/2023 | **Nuevo evento de Nominación de FE** (`rGEveNom`, GENFE001-027) con validaciones 4451-4478 (solo para FE emitida a innominado) |
| [NT 15](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_015_MT_V150.pdf/f7f54b14-d4a8-d7c1-0549-804da511187e?t=1692655153604) | 14/08/2023 | 21/08/2023 / 21/09/2023 | H004i (2442): el receptor del CDC asociado debe coincidir con el del evento de nominación |
| [NT 16](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_016_MT_V150.pdf/fbb16776-262b-7330-e609-f509304413d4?t=1692977785955) | 14/08/2023 | 25/08/2023 / 22/09/2023 | **Firma digital**: algoritmos válidos de C14N, firma (RSA-SHA256/384/512) y digest (SHA256/384/512). Transform 1-1 con solo enveloped. Se elimina XPath. Certificado cualificado. Validaciones 0120, 0140, 0141 y 2450. TLS: el RUC va en SerialNumber (PJ) o SubjectAlternativeName (PF) |
| [NT 17](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_017_MT_V150.pdf/6e3ccc6a-49eb-96fd-b2b6-86405bb2c4c5?t=1692977786216) | 14/08/2023 | 24/08/2023 / 25/08/2023 | Mensajes de las validaciones D222 (1326) y D224 (1329) |
| [NT 18](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_018_MT_V150-+Junio.pdf/2ace18c4-5c03-c339-7f5c-bed6d5b5eb5e?t=1717710699642) | 17/11/2023 | 01/12/2023 / 08/01/2024 | Nuevo grupo D030 gOblAfe (0-11), con D031 cOblAfe y D032 dDesOblAfe. Tabla 12 de tipos de obligación. Validaciones 1220 y 1221. Códigos de validación del evento de transporte (4325-4335). Nueva validación GET002 (4336) |
| [NT 19](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_019_MT_V150.pdf/23bd2a28-9449-f31d-3d46-7f037706880d?t=1700253533804) | 17/11/2023 | 15/12/2023 / 31/01/2024 | **Eventos del receptor**: dFecEmi en Notificación-Recepción y Desconocimiento. Plazo de 45 días; 15 días para el evento correctivo. Validaciones 41xx-42xx. AD04 0143 (la firma del evento debe ser del receptor). El último evento registrado es el que vale |
| [NT 20](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_020_MT_V150.pdf/f9a47078-748e-db87-bf2f-e6826ef048b9?t=1700253534040) | 17/11/2023 | 15/12/2023 / 31/01/2024 | E827 dCodConDncp (1-30, 0-1). D202b (1332): si el receptor es un OEE, la operación debe ser B2G |
| [NT 21](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_021_MT_V150+30.12.24.pdf/ab12f22b-42a2-9bd4-e3a0-7141d9e4b8d0?t=1735592286335) | 29/12/2023 | 01/01/2024 / 01/01/2024 | D208c (1321): tope de innominado en **35.000.000** (Art. 6 Dto. 872/2023). **Reemplazada por NT 24** |
| [NT 22](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_022_MT_V150.pdf/c7795a15-03be-caac-b664-692853c0f442?t=1709739358545) | 09/02/2024 | 09/02/2024 / 09/02/2024 | D031a (1222): códigos de obligación afectada sin repetición |
| [NT 23](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_023_MT_V150.pdf/9580922b-5dd5-60f9-4857-ae66a757898f?t=1724967650006) | 27/08/2024 | 30/08/2024 / 27/09/2024 | D208 y D210 (versión vigente). E711 con 1-10p(0-8). E791 hasta 9 y E797. **H018 dRucFus**. Validaciones D208e (C002=5, 6, 7), D210 1314, D208f 1333, D210b 1334, D208g 1335, H001 2400 (C002=4, 5, 6, 8), H004g 2439, H018 2443 y H018a 2444. **Tabla 5**: unidades 111-140 |
| [NT 24](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_024_MT_V150.pdf/8f8c0fc6-ee49-74b6-469d-0f79c18065ed?t=1734614145050) | 17/12/2024 | 01/01/2025 / 01/01/2025 | D208c (1321): tope de innominado en **7.000.000** (inc. ii, num. 2, Art. 6 Dto. 872/2023). **Vigente** |
| [NT 25](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_025_MT_V150.pdf/c6ad5e7d-bf0a-2be9-e5a0-a2a948ea1bc1?t=1745856915027) | 23/04/2025 (el encabezado dice 23/04/2024, ver nota) | 28/04/2025 / 28/04/2025 | Se excluye GEC002c (4004): se puede cancelar aunque el receptor haya dado conformidad |
| [NT 26](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_026_MT_V150.pdf/605010d6-22fe-b732-24ab-c6e9d7868b4f?t=1749487559733) | 06/06/2025 | 09/06/2025 / 16/06/2025 | E704 y E705 (DNCP) opcionales si D202=3. E020 gCompPub opcional en B2G. Se excluyen las validaciones 1400, 1401, 1800 y 1801 |
| [NT 27](https://www.dnit.gov.py/documents/20123/420595/NT_E_KUATIA_027_MT_V150.pdf/e5376c97-64cf-3fe0-e962-b6f22c8c207a?t=1773076266295) | 09/03/2026 | 09/03/2026 / 09/03/2026 | Evento de Nominación: GENFE010 iTipIDRec y GENFE011 dDTipIDRec ya **no admiten 5=Innominado** (valores 1, 2, 3, 4, 6, 9) |
