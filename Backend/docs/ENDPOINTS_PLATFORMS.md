# API de `platforms` - Fase A

Esta guía permite levantar el proyecto y probar la API de `platforms` sin leer el código.
Durante la Fase A no se exige autenticación del cliente: las operaciones utilizan el usuario del sistema con `code=0`.
La autenticación JWT y los permisos pertenecen a la Fase B.

## 1. Requisitos

- Docker Desktop iniciado.
- Git.
- Un archivo `.env` en la raíz del proyecto.

Debes crear un archivo `.env` en la raíz del proyecto y completar los datos de la base de datos. El archivo `.env` real no debe subirse a Git porque contiene credenciales.

## 2. Preparar y levantar el proyecto

Ejecuta los comandos desde la raíz del repositorio:

```powershell
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml run --rm web python manage.py migrate
docker compose -f docker/docker-compose.yml run --rm web python manage.py create_system_user
docker compose -f docker/docker-compose.yml run --rm web python manage.py seed_catalog
docker compose -f docker/docker-compose.yml up
```

La API quedará disponible en:

```text
http://localhost:8000
```

Para trabajar con plataformas deben existir previamente los registros de catálogo que se relacionarán con ellas: instituciones, idiomas, países, tipos de material, programas académicos y sus áreas del conocimiento.

## 3. Swagger y esquema OpenAPI

Abre esta URL en el navegador:

```text
http://localhost:8000/api/docs/
```

Para el esquema OpenAPI sin interfaz:

```text
http://localhost:8000/api/schema/
```

En Swagger, selecciona un endpoint, pulsa **Try it out**, completa el cuerpo JSON y pulsa **Execute**.

La validación actual del esquema quedó en:

```text
Warnings: 0
Errors:   0
```

## 4. Recursos disponibles

| Recurso | Ruta base | Uso / campos principales |
| --- | --- | --- |
| Plataformas | `/api/platforms/` | CRUD administrativo de plataformas |
| Sintaxis válidas | `/api/platforms/valid-sintaxis/` | CRUD de configuraciones de sintaxis de búsqueda |
| Verificaciones de enlace | `/api/platforms/link-check-logs/` | Consulta de solo lectura del historial de verificación |
| Plataformas públicas | `/api/platforms/public/` | Consulta de plataformas en estado `PUBLICADO` |

### 4.1. Campos de escritura de `Platform`

```text
name
public_url
is_harvestable
base_api_url
api_key
url_image
requires_registration
has_access_text
valid_sintaxis
institutions
languages
countries
material_types
```

Los siguientes campos son de solo lectura o son controlados por el backend:

```text
id
status
start_period
finish_period
validated_by
validated_at
knowledge_areas
academic_programs
created_by
created_at
updated_by
updated_at
deleted_by
deleted_at
delete_explanation
```

La respuesta de Platform conserva procedencia manual/derivada por sección.
Los programas y las áreas derivados provienen de Journals elegibles. En el
caso de las áreas, Platform consume todas las áreas efectivas de Journal
(`is_manual=true OR is_derived=true`) y las marca como derivadas en el nivel
Platform; no copia los flags de procedencia de Journal.

### 4.2. `is_harvestable`, `base_api_url` y `api_key`

Son datos de configuración de cosecha y son independientes de la URL pública.
`is_harvestable` tiene valor predeterminado `false`; solo pasa a `true` cuando
el cliente lo solicita explícitamente y proporciona una configuración válida.

| `is_harvestable` | `base_api_url` | `api_key` | Resultado |
| --- | --- | --- | --- |
| `false` | `null` | `null` | Válido: plataforma de referencia no cosechable |
| `true` | URL | `null` | Válido: cosecha sin autenticación |
| `true` | URL | valor | Válido: cosecha con credencial |
| `true` | `null` | cualquiera | **Inválido: HTTP 400** |
| `false` | URL o valor | cualquiera | **Inválido: HTTP 400** |

`api_key` es de solo escritura. El backend la almacena cifrada en `encrypted_api_key`, pero ni `api_key` ni `encrypted_api_key` aparecen en las respuestas.

Para cosechas de OpenAlex que avanzan a páginas posteriores mediante cursor,
OpenAlex requiere una API key. Configúrala en `api_key` al crear o actualizar
la plataforma; el harvester la envía como token Bearer en el encabezado de
autorización, sin incluirla en la URL.

En un `PATCH`:

- si `api_key` no se envía, se conserva la credencial actual;
- `"api_key": null` elimina la credencial existente;
- `"api_key": ""` se trata como ausencia de credencial.
- cambiar `is_harvestable` de `true` a `false` limpia automáticamente `base_api_url` y la credencial cifrada.

La migración inicial conserva la configuración histórica: toda plataforma existente con `base_api_url` no nula ni vacía queda con `is_harvestable=true`; las demás quedan en `false`. La migración no modifica la URL técnica ni la credencial almacenada.

### 4.3. URL pública de la plataforma

La implementación actual **no almacena la URL pública en `Platform`**. `public_url` es un campo virtual aceptado en `POST` y `PATCH`; se registra y conserva en `LinkCheckLog.url`, y se devuelve en las respuestas administrativas y públicas.

```text
Platform
    ↓
LinkCheckLog.url   ← URL pública (`journal_platform IS NULL`)

Platform.base_api_url ← API de cosecha
```

La URL pública puede registrarse mediante el campo virtual `public_url` del CRUD normal o verificarse mediante:

```text
POST /api/platforms/{id}/check-link/
```

Una plataforma necesita al menos una URL pública registrada en `LinkCheckLog` antes de poder publicarse.

Si existe historial, `public_url` se obtiene del último registro general no
eliminado. Los logs ligados a una revista mediante `journal_platform` no se
consideran para este campo. `public_url` nunca se toma de `base_api_url`: esta
última continúa siendo exclusivamente la URL técnica de harvesting.

En `PATCH`, omitir `public_url` conserva el historial; enviar la misma URL no duplica logs y enviar una URL distinta crea un nuevo registro. Toda URL recibida pasa por la validación SSRF del backend.

### 4.4. Campos de `ValidSintaxis`

Campos de escritura:

```text
name
booleans
parenthesis
fields
```

`fields_template` es de solo lectura y expone la plantilla canónica:

```json
{
  "title": "",
  "author": "",
  "subject": "",
  "issn": "",
  "language": "",
  "year": ""
}
```

`fields` solo acepta esas claves y valores de tipo string.

## 5. Operaciones generales

### 5.1. Plataformas administrativas

| Método | Ruta | Uso | Respuesta habitual |
| --- | --- | --- | --- |
| GET | `/api/platforms/` | Listar plataformas activas | 200 |
| POST | `/api/platforms/` | Crear plataforma | 201 |
| GET | `/api/platforms/{id}/` | Consultar plataforma | 200 |
| PUT | `/api/platforms/{id}/` | Reemplazar información editable | 200 |
| PATCH | `/api/platforms/{id}/` | Actualizar parcialmente | 200 |
| DELETE | `/api/platforms/{id}/` | Eliminación física o lógica según relaciones | 204/200 |
| GET | `/api/platforms/archived/` | Listar plataformas eliminadas lógicamente | 200 |
| POST | `/api/platforms/{id}/restore/` | Restaurar plataforma eliminada | 200 |
| POST | `/api/platforms/{id}/publish/` | `BORRADOR → PUBLICADO` | 200 |
| POST | `/api/platforms/{id}/mark-obsolete/` | `PUBLICADO → OBSOLETO` | 200 |
| POST | `/api/platforms/{id}/reactivate/` | `OBSOLETO → BORRADOR` | 200 |
| POST | `/api/platforms/{id}/check-link/` | Verificar y registrar URL pública | 200/400 |

`status` no se modifica mediante `POST`, `PUT` o `PATCH`. Las transiciones se realizan únicamente mediante las acciones de ciclo de vida.

Cuando una plataforma eliminada se restaura, vuelve a `BORRADOR` y se limpian `validated_by` y `validated_at`.

### 5.2. Sintaxis válidas

| Método | Ruta | Uso | Respuesta habitual |
| --- | --- | --- | --- |
| GET | `/api/platforms/valid-sintaxis/` | Listar sintaxis activas | 200 |
| POST | `/api/platforms/valid-sintaxis/` | Crear sintaxis | 201 |
| GET | `/api/platforms/valid-sintaxis/{id}/` | Consultar sintaxis | 200 |
| PUT | `/api/platforms/valid-sintaxis/{id}/` | Reemplazar sintaxis | 200 |
| PATCH | `/api/platforms/valid-sintaxis/{id}/` | Actualizar parcialmente | 200 |
| DELETE | `/api/platforms/valid-sintaxis/{id}/` | Eliminar según reglas de `AuditableViewSet` | 204/200 |
| GET | `/api/platforms/valid-sintaxis/archived/` | Listar sintaxis archivadas | 200 |
| POST | `/api/platforms/valid-sintaxis/{id}/restore/` | Restaurar sintaxis archivada | 200 |

### 5.3. Historial de verificación

`LinkCheckLog` es de solo lectura para el cliente. `journal_platform = null` identifica la URL general de la plataforma; un valor no nulo identifica la URL de una revista dentro de esa plataforma. En el segundo caso, la plataforma de ambos FKs debe coincidir.

El estado visual debe interpretarse con `last_check` e `is_active`:

```text
last_check = null                         → Sin verificar
last_check != null e is_active = true    → Disponible
last_check != null e is_active = false   → Error / No disponible
```

La API expone esa interpretación directamente mediante
`verification_status`, cuyos valores son `unverified`, `available` y
`unavailable`. Un registro nuevo siempre nace con `is_active=false` y
`last_check=null`; `is_active=false` por sí solo no significa que el chequeo
haya fallado.

`http_status_code=null` no basta para determinar el estado: puede representar
una URL aún no verificada o un chequeo fallido sin respuesta HTTP. Cuando sí se
realiza un chequeo, `last_check` contiene su fecha real. `created_at` solo indica
cuándo se creó el registro.

El historial se ordena por defecto con las verificaciones realizadas primero:
`last_check` descendente con nulos al final, seguido por `created_at` e `id`
descendentes. El orden se aplica antes de la paginación. Los registros sin
verificar quedan al final y no se mezclan cronológicamente como si fueran
errores.

La selección de la URL y del estado **vigentes** usa otro criterio: toma el
evento más reciente por `created_at` e `id` descendentes. De esta forma, una
URL nueva pendiente sustituye correctamente a la URL anterior ya comprobada,
sin depender del ordenamiento de valores `NULL` de PostgreSQL.

| Método | Ruta | Uso |
| --- | --- | --- |
| GET | `/api/platforms/link-check-logs/` | Listar verificaciones |
| GET | `/api/platforms/link-check-logs/{id}/` | Consultar una verificación |

El listado admite `verification_status=unverified|available|unavailable`,
además de `platform`, `journal_platform`, `journal_platform__isnull` e
`is_active`. Para distinguir una URL pendiente de una fallida debe utilizarse
`verification_status`, no solamente `is_active=false`.

No existe `POST`, `PUT`, `PATCH` ni `DELETE` público para fabricar resultados
de verificación. Registrar o cambiar `public_url` crea un registro pendiente;
`check-link` crea el registro correspondiente a una verificación real.

### 5.4. Consulta pública

| Método | Ruta | Uso |
| --- | --- | --- |
| GET | `/api/platforms/public/` | Listar plataformas publicadas |
| GET | `/api/platforms/public/{id}/` | Consultar ficha pública |

Las plataformas `BORRADOR`, `OBSOLETO` o eliminadas no aparecen en este endpoint.
Una Platform puede recibir relaciones administrativas con Journals antes de
publicarse. Estas relaciones pueden preparar su clasificación derivada, pero no
alteran su estado ni sustituyen la acción explícita `publish`.

## 6. Ejemplos con `curl`

### 6.1. Crear una sintaxis válida

```bash
curl -X POST http://localhost:8000/api/platforms/valid-sintaxis/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sintaxis estándar",
    "booleans": ["AND", "OR", "NOT"],
    "parenthesis": true,
    "fields": {
      "title": "ti",
      "author": "au",
      "subject": "su",
      "issn": "is",
      "language": "la",
      "year": "yr"
    }
  }'
```

La respuesta incluye además `fields_template`.

### 6.2. Crear una plataforma de referencia sin API de cosecha

```bash
curl -X POST http://localhost:8000/api/platforms/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Repositorio institucional",
    "public_url": "https://repositorio.ejemplo.org",
    "is_harvestable": false,
    "requires_registration": false,
    "has_access_text": true,
    "valid_sintaxis": 1,
    "institutions": [1],
    "languages": [1],
    "countries": [1],
    "material_types": [1],
    "academic_programs": [1]
  }'
```

No se envía `knowledge_areas`: el backend las deriva desde los programas académicos.

### 6.3. Crear una plataforma con API y API Key

```bash
curl -X POST http://localhost:8000/api/platforms/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Plataforma con cosecha",
    "public_url": "https://www.ejemplo.org",
    "is_harvestable": true,
    "base_api_url": "https://api.ejemplo.org",
    "api_key": "clave-secreta",
    "valid_sintaxis": 1,
    "institutions": [1],
    "languages": [1],
    "countries": [1],
    "material_types": [1],
    "academic_programs": [1]
  }'
```

La clave no aparecerá en la respuesta.

### 6.4. Eliminar una API Key mediante `PATCH`

```bash
curl -X PATCH http://localhost:8000/api/platforms/1/ \
  -H "Content-Type: application/json" \
  -d '{"api_key": null}'
```

### 6.5. Registrar y verificar la URL pública

La primera verificación debe enviar la URL:

```bash
curl -X POST http://localhost:8000/api/platforms/1/check-link/ \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.ejemplo.org"}'
```

Respuesta conceptual:

```json
{
  "id": 1,
  "platform": 1,
  "url": "https://www.ejemplo.org",
  "fail_count": 0,
  "http_status_code": 200,
  "is_active": true,
  "last_check": "2026-10-05T..."
}
```

En verificaciones posteriores puede omitirse la URL y se reutiliza la última registrada:

```bash
curl -X POST http://localhost:8000/api/platforms/1/check-link/ \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 6.6. Publicar una plataforma

```bash
curl -X POST http://localhost:8000/api/platforms/1/publish/
```

Para publicarse debe estar en `BORRADOR` y cumplir las reglas de completitud, incluyendo URL pública registrada, `start_period`, `valid_sintaxis` y las relaciones activas requeridas.

No se exige `base_api_url` ni `api_key` cuando la plataforma no necesita cosecha.

### 6.7. Marcar como obsoleta

```bash
curl -X POST http://localhost:8000/api/platforms/1/mark-obsolete/
```

### 6.8. Reactivar una plataforma obsoleta

```bash
curl -X POST http://localhost:8000/api/platforms/1/reactivate/
```

La plataforma regresa a `BORRADOR` y debe validarse de nuevo antes de publicarse.

### 6.9. Consultar plataformas públicas

```bash
curl http://localhost:8000/api/platforms/public/
```

La respuesta utiliza la paginación global del proyecto:

```json
{
  "current_page": 1,
  "total_pages": 1,
  "page_size": 10,
  "total_items": 1,
  "next": null,
  "previous": null,
  "results": []
}
```

Cada elemento del listado incluye `item_number`.

## 7. Borrado lógico y restauración

Para eliminar una plataforma con relaciones de negocio, envía una explicación:

```bash
curl -X DELETE http://localhost:8000/api/platforms/1/ \
  -H "Content-Type: application/json" \
  -d '{"delete_explanation":"Plataforma retirada del repositorio"}'
```

Los registros eliminados lógicamente se consultan con:

```text
GET /api/platforms/archived/
```

Para restaurar:

```bash
curl -X POST http://localhost:8000/api/platforms/1/restore/
```

Una plataforma restaurada regresa siempre a `BORRADOR` y pierde su validación previa.

## 8. Búsqueda, ordenamiento y filtros

### 8.1. Administración

Búsqueda por nombre:

```bash
curl "http://localhost:8000/api/platforms/?search=scopus"
```

Filtros administrativos disponibles:

| Parámetro | Tipo | Ejemplo | Significado |
|---|---|---|---|
| `status` | enum | `?status=publicado` | Estado real: `borrador`, `publicado` u `obsoleto`. |
| `is_harvestable` | booleano | `?is_harvestable=true` | Indica si existe mecanismo de cosecha. |
| `requires_registration` | booleano | `?requires_registration=false` | Indica si requiere registro del usuario. |
| `has_access_text` | booleano | `?has_access_text=true` | Indica acceso a texto completo. |
| `valid_sintaxis` | entero | `?valid_sintaxis=1` | Sintaxis activa asociada. |
| `institution` | entero | `?institution=1` | Institución con relación activa. |
| `country` | entero | `?country=1` | País con relación activa. |
| `language` | entero | `?language=1` | Idioma con relación activa. |
| `knowledge_area` | entero | `?knowledge_area=1` | Área derivada activa. |
| `material_type` | entero | `?material_type=1` | Tipo de material con relación activa. |
| `academic_program` | entero | `?academic_program=1` | Programa derivado activo. |

Los valores de `status` son minúsculos y cualquier opción ajena se rechaza.
Los filtros pueden combinarse:

```bash
curl "http://localhost:8000/api/platforms/?status=publicado&country=1&is_harvestable=true"
```

Ordenamiento:

```bash
curl "http://localhost:8000/api/platforms/?ordering=name"
curl "http://localhost:8000/api/platforms/?ordering=-created_at"
```

### 8.2. Consulta pública

Filtros disponibles:

| Parámetro | Tipo | Ejemplo | Significado |
|---|---|---|---|
| `institution` | entero | `?institution=1` | Institución con relación activa. |
| `country` | entero | `?country=1` | País con relación activa. |
| `language` | entero | `?language=1` | Idioma con relación activa. |
| `knowledge_area` | entero | `?knowledge_area=1` | Área derivada activa. |
| `material_type` | entero | `?material_type=1` | Tipo de material con relación activa. |
| `academic_program` | entero | `?academic_program=1` | Programa derivado activo. |
| `requires_registration` | booleano | `?requires_registration=false` | Requisito de registro. |
| `has_access_text` | booleano | `?has_access_text=true` | Acceso a texto completo. |
| `is_harvestable` | booleano | `?is_harvestable=true` | Disponibilidad de mecanismo de cosecha. |

Ejemplos:

```bash
curl "http://localhost:8000/api/platforms/public/?country=1"
curl "http://localhost:8000/api/platforms/public/?academic_program=1"
curl "http://localhost:8000/api/platforms/public/?knowledge_area=1"
curl "http://localhost:8000/api/platforms/public/?has_access_text=true"
```

También admite búsqueda por nombre y ordenamiento por `name`, `start_period` y `finish_period`.

El endpoint público no acepta `status`: su queryset ya restringe siempre el
resultado a Platforms `PUBLICADO`. Ningún filtro adicional puede hacer visible
una Platform en `BORRADOR`, `OBSOLETO` o eliminada.

### 8.3. Historial de enlaces

Filtros:

```text
platform
journal_platform
journal_platform__isnull
is_active
```

Ordenamiento:

```text
last_check
fail_count
created_at
```

Paginación:

```text
page       → número de página
page_size  → cantidad de elementos (10 por defecto, máximo 100)
```

Ejemplo:

```bash
curl "http://localhost:8000/api/platforms/link-check-logs/?platform=1&is_active=false"
```

Para consultar únicamente el historial de la URL pública general, sin mezclar
URLs contextuales de Journals:

```bash
curl "http://localhost:8000/api/platforms/link-check-logs/?platform=1&journal_platform__isnull=true"
```

## 9. Probar sin modificar la base de datos normal

La suite de Django utiliza una base de datos de pruebas separada. Para ejecutar las pruebas de `platforms`:

```bash
docker compose -f docker/docker-compose.yml run --rm -e DJANGO_TESTING=true web python manage.py test apps.platforms --keepdb
```

Inventario actual de la suite:

```text
47 pruebas: 6 de modelos, 21 de serializadores, 7 de servicios,
2 de clasificación y 11 de API.
```

Para validar también el esquema OpenAPI:

```bash
docker compose -f docker/docker-compose.yml run --rm web python manage.py spectacular --validate --file /tmp/schema.yml
```

Resultado validado:

```text
Warnings: 0
Errors:   0
```

## 10. Errores frecuentes

| Código | Causa típica |
| --- | --- |
| 400 | API Key sin `base_api_url`, datos inválidos, publicación incompleta, URL insegura o acción de ciclo de vida no permitida |
| 404 | ID inexistente o registro eliminado |
| 405 | Método HTTP no permitido para la ruta; por ejemplo intentar escribir directamente en `link-check-logs` o `public` |
| 500 al iniciar | Dependencias, `.env` o migraciones pendientes |

Si la API no inicia, ejecuta:

```bash
docker compose -f docker/docker-compose.yml exec web python manage.py check
```

La autenticación JWT, los permisos y la protección de escritura se implementarán en la Fase B.
# Clasificación derivada vigente

El Frontend no administra `academic_programs` ni `knowledge_areas`; ambos son
read-only. Platform los obtiene de la unión de programas de sus Journals
elegibles y de las áreas activas de esos programas:

```text
AcademicProgram ↔ KnowledgeArea       fuente de verdad
Journal ↔ AcademicProgram             fuente de verdad
Journal ↔ Platform                    fuente de verdad
Journal ↔ KnowledgeArea               derivada
Platform ↔ AcademicProgram            derivada
Platform ↔ KnowledgeArea              derivada
```

Una Journal es elegible si `deleted_at=null`, `active=true`,
`validated_at!=null` y su `SharedJournalPlatform.deleted_at=null`. Las
relaciones derivadas se conservan con Soft Delete y se restauran cuando vuelven
a ser válidas.

Una Platform sin Journals elegibles puede conservar su estado `PUBLICADO` y
clasificación vacía. Si tiene al menos una Journal elegible pero el resultado
queda sin programas o sin áreas, una Platform publicada pasa automáticamente a
`BORRADOR`, limpia su validación y deja de aparecer públicamente. Si después
recupera una clasificación completa permanece en `BORRADOR`; solo la acción
explícita `publish` puede publicarla nuevamente. Nunca se usa `OBSOLETO` para
esta invalidación.

Ejemplo de creación/edición: se envían los metadatos y relaciones no académicas
(`institutions`, `languages`, `countries`, `material_types`), pero se omiten
`academic_programs` y `knowledge_areas`.
## Contrato de URLs y verificación vigente

- `public_url` es obligatoria al crear una Platform, pero no es una columna del
  modelo: se registra como `LinkCheckLog` general (`journal_platform=null`).
- Registrar una URL no equivale a verificarla; `last_check=null` significa que
  todavía no se ha realizado una comprobación HTTP, y el registro nace con
  `is_active=false`.
- `POST /api/platforms/{id}/check-link/` verifica la URL pública vigente.
- `POST /api/platforms/{id}/check-links/` verifica secuencialmente la URL pública
  y la URL vigente de cada relación Journal-Platform no eliminada. Un fallo
  individual no detiene las demás comprobaciones.
- El historial conserva registros pendientes y resultados de verificación; el
  chequeo masivo no recorre URLs históricas ni relaciones eliminadas.

También continúa pendiente cualquier regla adicional para derivar o sincronizar
idiomas de Platform; esta fase no modifica ese comportamiento.

## Semántica de fechas del ciclo de vida

- `start_period`: fecha de registro de la plataforma. El backend la asigna al
  crearla y nunca cambia durante publish, obsolescencia, reactivación o restore.
- `finish_period`: fecha en que la plataforma fue marcada como `OBSOLETO`.
  `mark-obsolete` la asigna automáticamente; `reactivate` y restore la limpian.
- Ambos campos son de solo lectura. Enviarlos en `POST`, `PUT` o `PATCH` produce
  HTTP 400 y no modifica los valores existentes.

Etiquetas recomendadas para el Frontend:

- `start_period`: **Fecha de registro de la plataforma**.
- `finish_period`: **Fecha de obsolescencia**.

Pendiente: evaluar eliminar `Platform.start_period` y `Platform.finish_period`
si `created_at`, el estado y el historial de auditoría resultan suficientes.
# Actualización: procedencia, publicación y verificación global

## Crear no publica

`POST /api/platforms/` requiere `name` y `public_url`, permite que el resto de
la ficha permanezca incompleto y siempre conserva el estado `borrador`. La URL
queda registrada en `LinkCheckLog` para su verificación. Los demás requisitos estrictos se evalúan en
`POST /api/platforms/{id}/publish/`: URL pública vigente y verificada con un
último resultado exitoso, sintaxis vigente,
campos técnicos condicionales y al menos un valor efectivo en institución,
idioma, país, tipo de material, programa académico y área de conocimiento.
La publicación no requiere Journals asociadas.

Si la URL vigente nunca fue comprobada, `publish` indica que debe verificarse.
Si ya fue comprobada pero su último resultado falló, indica que no se encuentra
disponible y debe corregirse o verificarse nuevamente.

Cada sección administrativa se representa con `id`, `name`, `is_manual`,
`is_derived` y `editable`. Las cinco secciones compartidas con Journal se
derivan de todas las Journals activas y validadas. Para conocimiento se usa el
conjunto efectivo manual/derivado de cada Journal; una selección manual se
conserva cuando desaparece su última fuente derivada.

Los catálogos de secciones admiten filtros contextuales:
`?platform={id}&origin=manual|derived|both`, `?platform={id}&editable=true|false`
y `?available_for_platform={id}`. Este último excluye cualquier relación
vigente, independientemente de su origen.

## Sintaxis similares

`POST /api/platforms/valid-sintaxis/similar/` recibe `booleans`, `parenthesis`
y `fields`. Devuelve como máximo cinco sintaxis vigentes con similitud mínima
del 70 %, incluyendo `similarity`, `matching_fields` y `different_fields`.
Una configuración normalizada idéntica no puede crearse nuevamente; el error
incluye `existing_id`.

## Enlaces y eliminación

`POST /api/platforms/check-links/` comprueba secuencialmente todas las URLs
vigentes y responde `204` sin cuerpo. Un fallo individual no detiene los demás
chequeos. El endpoint existente por Platform conserva su respuesta detallada.

No se puede eliminar una Platform mientras exista una relación vigente con una
Journal no eliminada, incluso si la Journal está inactiva. Una ValidSintaxis en
uso por una Platform vigente tampoco puede eliminarse.
