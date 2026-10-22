# API del catálogo - Fase A

Esta guía permite levantar el proyecto y probar la API sin leer el código.
Durante la Fase A no se exige autenticación: los endpoints están abiertos.
La autenticación JWT y los permisos pertenecen a la Fase B.

## 1. Requisitos

- Docker Desktop iniciado.
- Git.
- Un archivo `.env` en la raíz del proyecto.

Debes crear un archivo `.env` en la raíz del proyecto y completar los datos de
la base de datos. El archivo `.env` real no debe subirse a Git porque contiene
credenciales.

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

El comando `seed_catalog` es idempotente. Se puede ejecutar varias veces sin
duplicar los datos existentes.

## 3. Swagger y esquema OpenAPI

Abre esta URL en el navegador:

```text
http://localhost:8000/api/docs/
```

Para el esquema OpenAPI sin interfaz:

```text
http://localhost:8000/api/schema/
```

En Swagger, selecciona un endpoint, pulsa **Try it out**, completa el cuerpo
JSON y pulsa **Execute**.

## 4. Recursos disponibles

| Recurso | Ruta base | Campos de escritura |
| --- | --- | --- |
| Instituciones | `/api/catalog/institutions/` | `name` |
| Idiomas | `/api/catalog/languages/` | `abbreviation`, `name` |
| Países | `/api/catalog/countries/` | `name`, `abbreviation`, `emoji_flag` |
| Tipos de material | `/api/catalog/material-types/` | `name` |
| Editoriales | `/api/catalog/editorials/` | `name` |
| Áreas de conocimiento | `/api/catalog/knowledge-areas/` | `name` |
| Programas académicos | `/api/catalog/academic-programs/` | `name`, `knowledge_areas` (obligatorio al crear) |

Los campos de auditoría son siempre de solo lectura:

```text
id, created_by, created_at, updated_by, updated_at,
deleted_by, deleted_at, delete_explanation
```

Los valores enviados en el campo `name` se guardan normalizados en minúsculas
y sin espacios al inicio o al final. Esto permite comparar nombres de forma
consistente. Si el nombre coincide con un registro eliminado, la API restaura
automáticamente ese registro en lugar de crear un duplicado.

## 5. Operaciones generales

Para cada recurso, `{recurso}` representa una ruta base de la tabla anterior.

| Método | Ruta | Uso | Respuesta habitual |
| --- | --- | --- | --- |
| GET | `/api/catalog/{recurso}/` | Listar registros activos | 200 |
| POST | `/api/catalog/{recurso}/` | Crear un registro | 201 |
| GET | `/api/catalog/{recurso}/{id}/` | Consultar un registro | 200 |
| GET | `/api/catalog/{recurso}/archived/` | Listar registros eliminados | 200 |
| PUT | `/api/catalog/{recurso}/{id}/` | Reemplazar un registro | 200 |
| PATCH | `/api/catalog/{recurso}/{id}/` | Actualizar parcialmente | 200 |
| DELETE | `/api/catalog/{recurso}/{id}/` | Borrado permanente o lógico según relaciones | 204/200 |
| POST | `/api/catalog/{recurso}/{id}/restore/` | Restaurar un registro eliminado | 200 |

Los listados no muestran registros eliminados. Un `GET` sobre un registro
eliminado responde 404.

Si el registro no tiene relaciones de negocio, `DELETE` lo elimina
permanentemente y responde `204 No Content`. Si otros elementos dependen de él,
se aplica borrado lógico y responde `200 OK` con un aviso; el registro queda
desactivado y puede restaurarse.

Para listar únicamente los registros eliminados, utiliza el endpoint
`/archived/`. Por ejemplo:

```text
GET /api/catalog/editorials/archived/
```

Este endpoint conserva la paginación y muestra los campos de auditoría del
borrado. La restauración continúa realizándose con:

```text
POST /api/catalog/editorials/{id}/restore/
```

## 6. Ejemplos con `curl`

### 6.1 Crear un idioma

```bash
curl -X POST http://localhost:8000/api/catalog/languages/ \
  -H "Content-Type: application/json" \
  -d "{\"abbreviation\":\"es\",\"name\":\"Español\"}"
```

Respuesta resumida:

```json
{
  "id": 1,
  "created_by": 1,
  "created_at": "2026-09-20T...",
  "updated_by": null,
  "updated_at": null,
  "deleted_by": null,
  "deleted_at": null,
  "delete_explanation": null,
  "abbreviation": "es",
  "name": "Español"
}
```

`created_by` lo asigna el servidor usando el usuario sistema `code=0`; el
cliente no puede enviarlo.

### 6.2 Listar idiomas

```bash
curl http://localhost:8000/api/catalog/languages/
```

La respuesta de listado usa paginación:

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": []
}
```

Cada página contiene siempre como máximo 10 elementos. Para solicitar otra
página utiliza el parámetro `page`:

```text
GET /api/catalog/languages/?page=2
```

La respuesta incluye `count`, `next`, `previous` y `results`.

### 6.3 Consultar un registro

```bash
curl http://localhost:8000/api/catalog/languages/1/
```

### 6.4 Actualizar parcialmente

```bash
curl -X PATCH http://localhost:8000/api/catalog/languages/1/ \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Castellano\"}"
```

El servidor actualiza automáticamente `updated_by` y `updated_at`.

### 6.5 Crear un país

```bash
curl -X POST http://localhost:8000/api/catalog/countries/ \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Colombia\",\"abbreviation\":\"CO\",\"emoji_flag\":\"🇨🇴\"}"
```

### 6.6 Crear un programa con sus áreas

Primero se crea el área:

```bash
curl -X POST http://localhost:8000/api/catalog/knowledge-areas/ \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Ingeniería\"}"
```

Luego se crea el programa enviando las áreas obligatoriamente:

```bash
curl -X POST http://localhost:8000/api/catalog/academic-programs/ \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Ingeniería de Sistemas\",\"knowledge_areas\":[1]}"
```

Las áreas de un programa se consultan así:

```text
GET /api/catalog/academic-programs/1/knowledge-areas/
```

Los programas que cubren un área se consultan así:

```text
GET /api/catalog/knowledge-areas/1/academic-programs/
```

La tabla intermedia no tiene un endpoint CRUD público.

## 7. Borrado lógico y restauración

El borrado no elimina físicamente la fila y exige una explicación:

```bash
curl -X DELETE http://localhost:8000/api/catalog/editorials/1/ \
  -H "Content-Type: application/json" \
  -d "{\"delete_explanation\":\"Editorial descontinuada\"}"
```

Respuesta:

```text
204 No Content
```

Para restaurarlo:

```bash
curl -X POST \
  http://localhost:8000/api/catalog/editorials/1/restore/ \
  -H "Content-Type: application/json"
```

Respuesta:

```text
200 OK
```

El registro vuelve a aparecer en los listados.

Un borrado sin explicación responde `400`. Si se intenta crear un nombre que
pertenece a un registro eliminado, también se responde `400` y se indica el ID
que debe restaurarse; los nombres no se reutilizan.

## 8. Búsqueda, ordenamiento y filtros

Los recursos de texto permiten buscar:

```bash
curl "http://localhost:8000/api/catalog/languages/?search=es"
```

Orden ascendente:

```bash
curl "http://localhost:8000/api/catalog/languages/?ordering=name"
```

Orden descendente:

```bash
curl "http://localhost:8000/api/catalog/languages/?ordering=-name"
```

La relación programa-área admite filtros por ID:

```bash
curl "http://localhost:8000/api/catalog/academic-program-knowledge-areas/?academic_program=1"
curl "http://localhost:8000/api/catalog/academic-program-knowledge-areas/?knowledge_area=1"
```

## 9. Probar sin modificar PostgreSQL

Swagger y el servidor normal utilizan la base PostgreSQL definida en `.env`;
las operaciones `POST`, `PATCH`, `DELETE` y `restore` guardan cambios allí.

Para ejecutar pruebas aisladas, se usa SQLite temporal:

```bash
docker compose -f docker/docker-compose.yml run --rm \
  -e DJANGO_TESTING=true web python manage.py test apps.catalog.test
```

Este comando crea una base de pruebas temporal y la elimina al finalizar.
Swagger no es automáticamente un entorno de pruebas; usa la base configurada
por el proceso Django que lo ejecuta.

## 10. Errores frecuentes

| Código | Causa |
| --- | --- |
| 400 | Campo obligatorio, valor duplicado, nombre archivado o borrado sin explicación |
| 404 | ID inexistente o registro eliminado |
| 405 | Método HTTP no permitido para esa ruta |
| 500 al iniciar | Faltan dependencias, `.env` o migraciones |

Si la API no inicia, ejecuta:

```bash
docker compose -f docker/docker-compose.yml run --rm web python manage.py check
```

La autenticación JWT, los permisos y la protección de escritura se
implementarán en la Fase B.
# Clasificación y propagación

`AcademicProgram.knowledge_areas` es la fuente de verdad del catálogo. En
`POST`/`PUT` se envía la lista y en `PATCH` solo cambia cuando el campo está
presente. Los vínculos retirados usan Soft Delete y, si vuelven a solicitarse,
se restaura el mismo registro histórico.

Un programa puede quedar sin áreas, pero la petición debe incluir:

```json
{
  "knowledge_areas": [],
  "confirm_empty_knowledge_areas": true
}
```

Sin esa confirmación se responde HTTP 400, porque el cambio puede reclasificar
Journals y Platforms. `confirm_empty_knowledge_areas` es write-only y no se
persiste. Los cambios efectivos se propagan únicamente a las Journals que usan
el programa; si la unión final de áreas no cambia, no se invalida la Journal ni
se escribe clasificación derivada.
