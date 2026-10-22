# API de Auditoría - Registros de Modificación del Sistema

Esta documentación está dirigida a los desarrolladores **frontend** para la implementación y visualización del módulo de **Auditoría del Sistema**.

---

## 1. Descripción General

El módulo de auditoría vigila de forma continua, optimizada e **inmutable** todas las modificaciones realizadas sobre las tablas y entidades de la base de datos de la página web (Catálogo, Plataformas, Revistas, Cosechas y Cuentas de usuario).

### Principios Clave:
1. **Inmutabilidad Estricta**: Los registros de auditoría son de solo lectura. Ningún usuario o proceso puede crear, editar o eliminar registros de auditoría a través de la API (`POST`, `PUT`, `PATCH`, `DELETE` responden `405 Method Not Allowed`).
2. **Optimización de Almacenamiento (Diff JSON)**: Se utiliza una estrategia eficiente que no clona ni duplica tablas completas en la base de datos, sino que registra únicamente los campos modificados en formato JSON (`changes: {"campo": [valor_anterior, valor_nuevo]}`).
3. **Soporte para Cambios No Autenticados / Anónimos**: Debido a que actualmente pueden no existir cuentas de usuario creadas o se pueden realizar operaciones abiertas sin autenticación, los cambios se auditan igualmente y la clave foránea del usuario se almacena como nula (`"actor": null`).
4. **Paginación Estándar de la Aplicación Core**: Los endpoints implementan `CustomPageNumberPagination` de la app `core`, conservando la estructura de paginación uniforme del backend con numeración secuencial de filas (`item_number`).

---

## 2. Acceso y Swagger

- **Ruta base de auditoría**: `/api/audit/`
- **Interfaz Swagger UI**: `http://localhost:8000/api/docs/`
- **Esquema OpenAPI**: `http://localhost:8000/api/schema/`

---

## 3. Endpoints Disponibles

| Método | Ruta | Descripción | Código Éxito |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/audit/logs/` | Listar el historial paginado de auditoría con filtros y búsqueda | `200 OK` |
| `GET` | `/api/audit/logs/{id}/` | Consultar el detalle completo de un registro de auditoría | `200 OK` |
| `GET` | `/api/audit/logs/resources/` | Listar todas las tablas y recursos auditados (para filtros y selects) | `200 OK` |
| `GET` | `/api/audit/logs/actions/` | Listar los tipos de acción disponibles (create, update, delete, access) | `200 OK` |
| `POST` | `/api/audit/logs/` | *No permitido* (inmutable) | `405 Method Not Allowed` |
| `PUT` | `/api/audit/logs/{id}/` | *No permitido* (inmutable) | `405 Method Not Allowed` |
| `PATCH` | `/api/audit/logs/{id}/` | *No permitido* (inmutable) | `405 Method Not Allowed` |
| `DELETE` | `/api/audit/logs/{id}/` | *No permitido* (inmutable) | `405 Method Not Allowed` |

---

## 4. Estructura de Respuestas

### 4.1 Listado Paginado (`GET /api/audit/logs/`)

```json
{
  "current_page": 1,
  "total_pages": 4,
  "page_size": 10,
  "total_items": 38,
  "next": "http://localhost:8000/api/audit/logs/?page=2",
  "previous": null,
  "results": [
    {
      "item_number": 1,
      "id": 152,
      "timestamp": "2026-10-08T20:45:12.312984Z",
      "action": 1,
      "action_name": "update",
      "action_display": "Actualización",
      "resource": "platform",
      "resource_display": "platform",
      "content_type": 18,
      "object_id": "4",
      "object_repr": "SciELO Colombia",
      "actor": 1,
      "actor_name": "Administrador Principal",
      "remote_addr": "192.168.1.50",
      "is_soft_delete": false,
      "is_restore": false,
      "changes": {
        "status": ["borrador", "publicado"]
      }
    },
    {
      "item_number": 2,
      "id": 151,
      "timestamp": "2026-10-08T20:30:01.120511Z",
      "action": 0,
      "action_name": "create",
      "action_display": "Creación",
      "resource": "country",
      "resource_display": "country",
      "content_type": 12,
      "object_id": "7",
      "object_repr": "🇨🇴 Colombia",
      "actor": null,
      "actor_name": null,
      "remote_addr": null,
      "is_soft_delete": false,
      "is_restore": false,
      "changes": {
        "name": ["", "colombia"],
        "abbreviation": ["", "CO"],
        "emoji_flag": ["", "🇨🇴"]
      }
    }
  ]
}
```

### 4.2 Detalle Individual (`GET /api/audit/logs/{id}/`)

Incluye toda la información del listado más el desglose del usuario (`actor_detail`), datos adicionales de contexto (`additional_data`) y texto plano de cambios (`changes_text`):

```json
{
  "id": 152,
  "timestamp": "2026-10-08T20:45:12.312984Z",
  "action": 1,
  "action_name": "update",
  "action_display": "Actualización",
  "resource": "platform",
  "resource_display": "platform",
  "content_type": 18,
  "object_id": "4",
  "object_repr": "SciELO Colombia",
  "actor": 1,
  "actor_name": "Administrador Principal",
  "remote_addr": "192.168.1.50",
  "is_soft_delete": false,
  "is_restore": false,
  "changes": {
    "status": ["borrador", "publicado"]
  },
  "actor_detail": {
    "id": 1,
    "code": 1001,
    "full_name": "Administrador Principal",
    "email": "admin@ufps.edu.co"
  },
  "additional_data": null,
  "changes_text": "status: borrador -> publicado"
}
```

Si el cambio se realizó sin usuario (`actor = null`):
```json
{
  "id": 151,
  "actor": null,
  "actor_name": null,
  "actor_detail": null,
  "..." : "..."
}
```

---

## 5. Interpretación del Campo `changes` (JSON Diff)

El campo `changes` es un diccionario JSON donde cada llave representa el nombre del campo modificado y su valor es un arreglo de dos posiciones `[valor_anterior, valor_nuevo]`:

| Tipo de Acción | Estructura en `changes` | Significado para UI |
| :--- | :--- | :--- |
| **Creación (`create`)** | `{"campo": ["", "valor_inicial"]}` | El campo fue creado con dicho valor inicial. |
| **Actualización (`update`)** | `{"campo": ["valor_viejo", "valor_nuevo"]}` | El campo cambió de `valor_viejo` a `valor_nuevo`. |
| **Eliminación (`delete`)** | `{"campo": ["valor_final", ""]}` | El registro fue eliminado físicamente teniendo `valor_final`. |

### Banderas Auxiliares para la UI:
- **`is_soft_delete` (`true`/`false`)**: Indica si la actualización correspondió a un borrado lógico (se estableció la fecha `deleted_at`).
- **`is_restore` (`true`/`false`)**: Indica si la actualización correspondió a la restauración de un registro previamente archivado (se limpió `deleted_at`).

---

## 6. Parámetros de Filtro, Búsqueda y Paginación

Puedes combinar múltiples parámetros en la query string de `GET /api/audit/logs/`:

| Parámetro | Tipo | Descripción | Ejemplo |
| :--- | :--- | :--- | :--- |
| `resource` | String | Nombre del modelo/tabla a filtrar | `?resource=platform` |
| `action` | Integer | Código numérico de acción (`0`=create, `1`=update, `2`=delete, `3`=access) | `?action=0` |
| `action_name` | String | Nombre textual de la acción (`create`, `update`, `delete`, `access`) | `?action_name=update` |
| `object_id` | String | ID de la entidad afectada | `?object_id=14` |
| `actor` | Integer | ID del usuario responsable | `?actor=1` |
| `is_anonymous` | Boolean | `true`: cambios sin usuario / `false`: cambios con usuario autenticado | `?is_anonymous=true` |
| `from_date` | ISO-8601 | Fecha/hora mínima del evento | `?from_date=2026-10-01T00:00:00Z` |
| `to_date` | ISO-8601 | Fecha/hora máxima del evento | `?to_date=2026-10-31T23:59:59Z` |
| `search` | String | Búsqueda por texto en representación de objeto, ID, usuario o cambios | `?search=scielo` |
| `ordering` | String | Ordenamiento (`timestamp`, `-timestamp`, `action`, `-action`, `id`, `-id`) | `?ordering=-timestamp` |
| `page` | Integer | Número de página actual | `?page=2` |
| `page_size` | Integer | Tamaño de página (por defecto 10, máximo 100) | `?page_size=20` |

---

## 7. Catálogos para Componentes Frontend

Para facilitar la construcción de filtros y selectores en el frontend sin tener que quemar valores fijos en el código, se disponen de dos endpoints auxiliares:

### 7.1 Catálogo de Recursos (`GET /api/audit/logs/resources/`)

Retorna la lista de todas las tablas y modelos de base de datos que se encuentran auditados en el backend:

```json
[
  {
    "resource": "academicprogram",
    "label": "academic program",
    "app": "catalog",
    "content_type_id": 14
  },
  {
    "resource": "country",
    "label": "country",
    "app": "catalog",
    "content_type_id": 12
  },
  {
    "resource": "harvest",
    "label": "harvest",
    "app": "harvesting",
    "content_type_id": 26
  },
  {
    "resource": "institution",
    "label": "institution",
    "app": "catalog",
    "content_type_id": 10
  },
  {
    "resource": "journal",
    "label": "journal",
    "app": "journal",
    "content_type_id": 21
  },
  {
    "resource": "platform",
    "label": "platform",
    "app": "platforms",
    "content_type_id": 18
  },
  {
    "resource": "schedule",
    "label": "schedule",
    "app": "harvesting",
    "content_type_id": 24
  },
  {
    "resource": "user",
    "label": "user",
    "app": "account",
    "content_type_id": 8
  }
]
```

### 7.2 Catálogo de Acciones (`GET /api/audit/logs/actions/`)

Retorna el catálogo de acciones posibles:

```json
[
  {"action": 0, "name": "create", "label": "Creación"},
  {"action": 1, "name": "update", "label": "Actualización"},
  {"action": 2, "name": "delete", "label": "Eliminación"},
  {"action": 3, "name": "access", "label": "Acceso"}
]
```

---

## 8. Ejemplos con `curl`

### 8.1 Consultar los últimos cambios de auditoría
```bash
curl http://localhost:8000/api/audit/logs/
```

### 8.2 Filtrar modificaciones realizadas sobre una plataforma específica
```bash
curl "http://localhost:8000/api/audit/logs/?resource=platform&object_id=5"
```

### 8.3 Filtrar cambios anónimos (sin usuario autenticado)
```bash
curl "http://localhost:8000/api/audit/logs/?is_anonymous=true"
```

### 8.4 Filtrar creaciones en un rango de fechas
```bash
curl "http://localhost:8000/api/audit/logs/?action_name=create&from_date=2026-10-01T00:00:00Z&to_date=2026-10-09T00:00:00Z"
```

### 8.5 Búsqueda libre por palabra clave
```bash
curl "http://localhost:8000/api/audit/logs/?search=ingenieria"
```

### 8.6 Consultar detalle de un registro de auditoría
```bash
curl http://localhost:8000/api/audit/logs/42/
```
