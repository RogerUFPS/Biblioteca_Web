# API de Harvesting

Harvesting administra las programaciones de cosecha y expone los eventos y
ejecuciones generados por el sistema. Cada evento programado crea un Harvest por
cada plataforma asociada al Schedule. Los clientes pueden administrar
programaciones y consultar eventos/Harvest; los registros de ejecución no se
crean ni actualizan directamente.

Todas las rutas tienen el prefijo `/api/harvesting`.

## Convenciones de consulta

Los listados paginados aceptan `page` y `page_size` (`page_size` máximo: 100) y
responden con `current_page`, `total_pages`, `page_size`, `total_items`,
`next`, `previous` y `results`. Cada elemento de `results` incluye
`item_number`.

Los listados admiten los parámetros de filtro indicados en cada sección.
También admiten `search` cuando se documenta como búsqueda, y `ordering` para
los campos de ordenamiento disponibles.

## Programaciones (`/schedules/`)

| Método | Ruta | Request body | Respuesta |
| --- | --- | --- | --- |
| `GET` | `/` | Ninguno. Acepta filtros y paginación. | `200`: lista paginada de programaciones activas. |
| `POST` | `/` | Requerido: objeto `Schedule`. | `201`: programación creada. |
| `GET` | `/{id}/` | Ninguno. | `200`: detalle de la programación. |
| `PUT` | `/{id}/` | Requerido: objeto `Schedule` completo. | `200`: programación actualizada. |
| `PATCH` | `/{id}/` | Opcional: objeto con los campos a actualizar. | `200`: programación actualizada. |
| `DELETE` | `/{id}/` | Normalmente ninguno. Si hay registros dependientes, enviar `delete_explanation`. | `204` si se elimina físicamente; `200` si se archiva lógicamente. |
| `GET` | `/archived/` | Ninguno. Acepta filtros y paginación. | `200`: lista paginada de programaciones archivadas. |
| `POST` | `/{id}/restore/` | Ninguno. | `200`: programación restaurada; `404` si no existe archivada. |
| `POST` | `/run-due/` | Ninguno. | `202`: cosechas encoladas; `200`: no había trabajo pendiente; `503`: no se pudo encolar el trabajo. |

### Crear o actualizar un Schedule

El body admite estos campos:

| Campo | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| `platforms` | `integer[]` | Sí al crear; opcional en `PATCH` | IDs de plataformas cosechables. Lista no vacía. |
| `frequency` | `string` | No | `once`, `daily`, `weekly` o `monthly`. |
| `start_date` | `datetime` | Sí al crear | Fecha y hora ISO-8601 de la primera ejecución. |
| `max_quantity` | `integer` | Debe enviarse este o `stop_after_minutes` | Límite de registros por Harvest; debe ser mayor que cero. |
| `stop_after_minutes` | `integer` | Debe enviarse este o `max_quantity` | Límite de duración por Harvest; debe ser mayor que cero. |

Si se envían ambos límites, la cosecha se detiene al alcanzar primero cualquiera
de ellos. Solo se aceptan plataformas con `is_harvestable=true`; si una
plataforma asociada se deshabilita posteriormente, su Harvest se registra como
fallido y no inicia la cosecha.

Ejemplo de `POST /schedules/`:

```json
{
  "platforms": [1, 2],
  "frequency": "weekly",
  "start_date": "2026-10-15T02:00:00Z",
  "max_quantity": 500,
  "stop_after_minutes": 120
}
```

La respuesta incluye los campos enviados, auditoría y `platform_names`:

```json
{
  "id": 12,
  "platforms": [1, 2],
  "platform_names": ["Plataforma A", "Plataforma B"],
  "frequency": "weekly",
  "start_date": "2026-10-15T02:00:00Z",
  "max_quantity": 500,
  "stop_after_minutes": 120
}
```

### Filtrar y ordenar programaciones

`GET /schedules/` y `GET /schedules/archived/` aceptan:

| Parámetro | Descripción |
| --- | --- |
| `platform` | ID de una plataforma asociada. |
| `frequency` | Frecuencia (`once`, `daily`, `weekly`, `monthly`). |
| `start_date_after` | `start_date` mayor o igual a la fecha ISO-8601 indicada. |
| `start_date_before` | `start_date` menor o igual a la fecha ISO-8601 indicada. |
| `search` | Busca por nombre de plataforma. |
| `ordering` | `created_at` o `start_date`; prefijo `-` para descendente. |
| `page`, `page_size` | Paginación. |

### Eliminación de una programación

Si la programación tiene registros dependientes, enviar un body como:

```json
{
  "delete_explanation": "Motivo de la desactivación"
}
```

La explicación debe ser una cadena no vacía de hasta 500 caracteres. Cuando no
hay dependencias, no se requiere body y el registro se elimina físicamente.

### Ejecutar programaciones vencidas (`run-due`)

`POST /schedules/run-due/` evalúa las programaciones vencidas y encola los
Harvest correspondientes en la cola Celery de RabbitMQ. No
requiere body ni parámetros. Es idempotente por ocurrencia del Schedule:
llamadas repetidas no crean eventos ni Harvest duplicados. Los Harvest
pendientes o sin progreso reciente se vuelven a despachar usando el checkpoint
guardado.

Responde con un arreglo de objetos `Harvest`: `202 Accepted` cuando encoló
trabajo y `200 OK` con `[]` cuando no había trabajo pendiente. Si falla la
comunicación con el productor, responde `503`; la programación y su Harvest
permanecen guardados para que el siguiente cron pueda reintentar.

Cada elemento usa la representación de Harvest descrita en la sección
[Ejecuciones](#ejecuciones-harvests). La ejecución continúa de forma asíncrona;
consulta `GET /harvests/` o `GET /events/` para conocer el progreso y el
resultado final.

## Eventos (`/events/`)

Los eventos son registros generados por el sistema y son de solo lectura.

| Método | Ruta | Request body | Respuesta |
| --- | --- | --- | --- |
| `GET` | `/` | Ninguno. Acepta filtros y paginación. | `200`: lista paginada de eventos. |
| `GET` | `/{id}/` | Ninguno. | `200`: detalle del evento y los IDs de sus Harvest. |

Filtros para `GET /events/`:

| Parámetro | Descripción |
| --- | --- |
| `schedule` | ID de la programación asociada. |
| `state` | Estado: `pending`, `running`, `completed` o `failed`. |
| `ordering` | `scheduled_for`, `started_at` o `finished_at`; prefijo `-` para descendente. |
| `page`, `page_size` | Paginación. |

El detalle contiene `schedule`, `scheduled_for`, `state`, `started_at`,
`finished_at`, `error_message` y `harvests`.

## Ejecuciones (`/harvests/`)

Los Harvest son registros administrados por el sistema: no se pueden crear,
editar ni eliminar directamente.

Al cosechar desde OpenAlex, cada Source se envía a `create_journal()` con el ID
de la plataforma del Harvest como `platform_id` y `homepage_url` como
`journal_url`. La URL es obligatoria en Journal; si OpenAlex no la entrega o no
pasa su validación, el Source se contabiliza en `records_failed`. No se envían
los campos `active` ni `license`: el estado de publicación/validación se
gestiona desde Journal y las licencias no se importan en este flujo; sus
asociaciones se administran mediante el catálogo de licencias.
OpenAlex exige una API key para paginar mediante cursor. Debe configurarse en
la plataforma como `api_key`; el backend la envía en el encabezado de
autorización. Si falta, la cosecha puede fallar al solicitar la siguiente
página con un error `401`.

| Método | Ruta | Request body | Respuesta |
| --- | --- | --- | --- |
| `GET` | `/` | Ninguno. Acepta filtros, búsqueda y paginación. | `200`: lista paginada de Harvest. |
| `GET` | `/{id}/` | Ninguno. | `200`: detalle del Harvest. |
| `GET` | `/{id}/journals/` | Ninguno. Acepta paginación. | `200`: revistas nuevas agregadas por ese Harvest. |
| `POST` | `/{id}/pause/` | Ninguno. | `200`: pausado; `202`: pausa solicitada mientras termina el paso worker actual; `400`: estado incompatible. |
| `POST` | `/{id}/resume/` | Ninguno. | `202`: continuación encolada; `400`: no estaba pausado; `503`: no se pudo encolar. |

Filtros para `GET /harvests/`:

| Parámetro | Descripción |
| --- | --- |
| `platform` | ID de la plataforma cosechada. |
| `schedule` | ID de la programación asociada. |
| `state` | `pending`, `running`, `pausing`, `completed`, `failed`, `cancelled` o `paused`. |
| `created_at_after`, `created_at_before` | Rango de creación (ISO-8601). |
| `started_at_after`, `started_at_before` | Rango de inicio (ISO-8601). |
| `finished_at_after`, `finished_at_before` | Rango de finalización (ISO-8601). |
| `search` | Busca por nombre de plataforma. |
| `ordering` | `created_at`, `started_at`, `finished_at` o `records_added`; prefijo `-` para descendente. |
| `page`, `page_size` | Paginación. |

El serializer de Harvest incluye `platform`, `platform_name`, `schedule`,
`event`, `schedule_frequency`, límites, `api_cursor`, estado, contadores,
tiempos, `duration` y `error_message`. Todos sus campos son de solo lectura.

`GET /harvests/{id}/journals/` entrega una lista paginada con la representación
administrativa de Journal para cada registro cuyo resultado fue `added`.
Registros que se actualizaron en esa ejecución no se incluyen. La relación se
registra desde que esta función se despliega; cosechas históricas no tienen
detalle de revistas asociado. Responde `404` si no existe el Harvest.

La pausa de una cosecha en ejecución es cooperativa: responde `202 Accepted`
con estado `pausing`; al llegar el siguiente paso worker, el Harvest pasa a
`paused`. Las cosechas `pending` se pausan inmediatamente con `200 OK`.
Reanudar solo es posible desde `paused`, encola el trabajo y continúa desde el
cursor/checkpoint guardado. El límite de tiempo acumula el tiempo activo de
procesamiento, excluyendo el tiempo de espera entre mensajes.

## Procesamiento con Celery y RabbitMQ

El backend procesa cada Harvest mediante tareas Celery en la cola `harvesting`
de RabbitMQ. Cada tarea procesa como máximo un registro, guarda el resultado y
el checkpoint en la misma transacción y encola el siguiente checkpoint cuando
queda trabajo. Los mensajes duplicados o con checkpoint antiguo no vuelven a
procesar registros. Los errores transitorios de red se reintentan con espera
exponencial; el despachador de programaciones recupera tareas que no avanzan.

Desde la carpeta principal del proyecto, configura las variables de RabbitMQ
`RABBITMQ_DEFAULT_USER` y `RABBITMQ_DEFAULT_PASS` en el entorno y ejecuta:

```sh
docker compose up --build
```

Compose inicia el backend, el worker Celery, RabbitMQ y el Cron_Service. El
cron llama automáticamente a `/api/harvesting/schedules/run-due/` cada minuto.
El backend conserva su configuración de base de datos y demás variables en
`Backend_Service/.env`. Para aplicar cambios de esquema, ejecuta dentro del
contenedor del backend `python manage.py migrate`.
