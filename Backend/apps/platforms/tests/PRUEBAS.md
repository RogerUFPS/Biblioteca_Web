# Pruebas de la Aplicación `platforms`

Estas pruebas documentan y validan el comportamiento integral del módulo `platforms` sin autenticación obligatoria del cliente, utilizando el usuario del sistema con `code=0`.

La cobertura se distribuye entre modelos, filtros, serializadores, servicios,
clasificación y API. La cantidad exacta se obtiene al ejecutar la suite, para
evitar mantener un contador manual desactualizado.

---

## 1. Reglas funcionales verificadas

Durante la evolución del módulo se ajustaron varias reglas de negocio importantes de `platforms`. Las pruebas actuales deben interpretarse bajo estas reglas:

### 1.1. API Key y `base_api_url`

- La `api_key` es **opcional**.
- `base_api_url` es **opcional**.
- `is_harvestable` es `False` por defecto y solo se habilita mediante un valor
  `true` explícito con una configuración válida.
- Una plataforma puede existir únicamente como referencia pública, sin mecanismos de cosecha.
- Una plataforma puede tener `base_api_url` sin `api_key`, por ejemplo cuando la API no requiere autenticación.
- No se permite configurar una `api_key` cuando no existe `base_api_url`, porque la clave quedaría asociada a una API inexistente.
- `base_api_url` corresponde exclusivamente a la API utilizada para procesos de cosecha; **no representa la URL pública de la plataforma**.

### 1.2. URL pública de la plataforma

La URL pública que permite al usuario acceder a la plataforma **no corresponde a un campo de `Platform`**.

La URL pública se registra mediante:

```text
Platform
    │
    └── LinkCheckLog
            └── url
```

Por tanto:

- `base_api_url` y `LinkCheckLog.url` tienen propósitos diferentes.
- `LinkCheckLog.url` es la URL pública que se presenta/verifica para acceso a la plataforma.
- Una plataforma debe tener una URL pública registrada, comprobada y disponible
  en `LinkCheckLog` para poder pasar a `PUBLICADO`.
- La verificación de enlaces utiliza la URL pública registrada y no `base_api_url`.
- `fail_count` se controla por URL y se reinicia cuando una verificación resulta exitosa.
- Todo registro nuevo nace con `is_active=False` y `last_check=null`. El estado
  se interpreta como `unverified`, `available` o `unavailable` combinando ambos
  campos.

### 1.3. Programas académicos y áreas del conocimiento

`academic_programs` y `knowledge_areas` son relaciones derivadas y de solo
lectura en Platform. No deben ser introducidas manualmente por el usuario.

La clasificación se obtiene mediante:

```text
Journal elegible → SharedJournalAcademicProgram → AcademicProgram
                                                   │
                                                   ▼
                              SharedAcademicProgramKnowledgeArea
                                                   │
                                                   ▼
                                             KnowledgeArea

Platform → SharedPlatformAcademicProgram / SharedPlatformKnowledgeArea
```

Los `academic_programs` se obtienen de las Journals elegibles asociadas y las
`knowledge_areas` se derivan de esos programas.

Esto permite:

- Evitar inconsistencias entre programas académicos y áreas del conocimiento.
- Evitar que el usuario asigne manualmente programas o áreas a Platform.
- Consolidar áreas repetidas cuando varios programas comparten la misma área.
- Mantener la clasificación de la plataforma sincronizada con la relación académica existente.

### 1.4. Publicación de plataformas

Una plataforma únicamente puede pasar a `PUBLICADO` cuando cumple las condiciones definidas por la lógica de negocio.

Entre ellas:

- Tener una URL pública registrada en `LinkCheckLog`.
- Tener el período de cobertura requerido.
- Tener una `ValidSintaxis` asociada.
- Tener las relaciones de catálogo requeridas activas.
- Si tiene `api_key`, debe tener también `base_api_url`.
- La plataforma debe encontrarse en estado `BORRADOR`.

Una plataforma que no tenga API de cosecha puede publicarse siempre que cumpla las demás condiciones; **la ausencia de `base_api_url` no es por sí sola un impedimento para publicar**.

---

## 2. Casos Cubiertos por Capas

### 2.1. Modelos (`apps/platforms/tests/test_models.py`)

| Prueba | Resultado Esperado |
| --- | --- |
| `test_platform_encryption_and_decryption` | La API Key se almacena cifrada (`encrypted_api_key`) mediante Fernet y se descifra correctamente en memoria. |
| `test_platform_name_normalized_to_lowercase` | El nombre se normaliza a minúsculas y se eliminan espacios redundantes mediante `AuditableModel`. |
| `test_platform_name_case_insensitive_unique_constraint` | La base de datos rechaza nombres duplicados sin importar mayúsculas/minúsculas mediante la restricción de unicidad correspondiente. |
| `test_valid_sintaxis_creation_and_soft_delete` | Se validan los campos JSON de `ValidSintaxis` y su ciclo de Soft Delete, conservando el registro en `all_objects`. |
| `test_link_check_log_fail_count_and_ordering` | `LinkCheckLog` registra las verificaciones y mantiene un orden determinista por creación e identificador. |
| `test_link_check_log_cannot_be_active_without_check` | Impide representar una URL como disponible cuando nunca ha sido comprobada. |
| `test_shared_platform_unique_constraint` | Se valida la unicidad compuesta de las relaciones intermedias, evitando asociaciones duplicadas. |

### 2.2. Serializadores (`apps/platforms/tests/test_serializers.py`)

| Prueba | Resultado Esperado |
| --- | --- |
| `test_platform_serializer_create_with_api_key_and_relations` | Crea una Platform cosechable, cifra la clave y sincroniza las relaciones administrables. |
| `test_platform_serializer_ignores_manual_academic_classification` | Ignora intentos de escribir la clasificación académica derivada. |
| `test_platform_serializer_does_not_accept_knowledge_areas_as_input` | Mantiene `knowledge_areas` como relación derivada y de solo lectura. |
| `test_platform_serializer_allows_null_api_key_without_base_api_url` | Permite una Platform no cosechable sin URL técnica ni credencial. |
| `test_platform_serializer_allows_base_api_url_without_api_key` | Permite cosecha mediante una API que no necesita autenticación. |
| `test_platform_serializer_rejects_api_key_without_base_api_url` | Rechaza una credencial sin URL técnica asociada. |
| `test_platform_serializer_clears_api_key_when_sent_as_null` | Elimina la credencial cuando `api_key` se envía como `null`. |
| `test_platform_serializer_rejects_removing_base_api_url_with_existing_api_key` | Impide retirar la URL técnica mientras se conserva una credencial. |
| `test_platform_serializer_allows_removing_base_api_url_and_api_key_together` | Permite retirar conjuntamente la URL técnica y la credencial. |
| `test_platform_serializer_patch_cannot_create_academic_relations` | Un `PATCH` no puede crear manualmente clasificación académica de Platform. |
| `test_platform_serializer_empty_academic_programs_is_read_only` | Una lista vacía tampoco modifica los programas derivados. |
| `test_sync_relations_deduplicates_repeated_ids` | Deduplica IDs en las relaciones administrables. |
| `test_archived_platform_restored_via_serializer_resets_to_draft` | Restaura una Platform archivada en `BORRADOR` y limpia su validación. |
| `test_public_serializer_excludes_sensitive_and_audit_fields` | La respuesta pública no expone credenciales, campos cifrados ni auditoría interna. |
| `test_platform_urls_use_latest_non_deleted_general_log` | Obtiene `public_url` del último log general no eliminado. |
| `test_public_url_is_a_virtual_writable_field` | Trata `public_url` como campo virtual escribible sin persistirlo en Platform. |
| `test_harvestable_platform_requires_base_api_url` | Exige URL técnica cuando `is_harvestable=true`. |
| `test_non_harvestable_platform_rejects_harvesting_configuration` | Rechaza URL técnica o credencial en una Platform no cosechable. |
| `test_disabling_harvesting_clears_api_url_and_key` | Deshabilitar cosecha limpia la URL técnica y la credencial cifrada. |
| `test_public_url_patch_preserves_history_without_duplicates` | Conserva el historial y evita duplicar la URL pública vigente. |
| `test_platform_creation_rolls_back_if_public_url_log_fails` | Revierte la creación si no puede registrarse de forma segura la URL pública. |

### 2.3. Servicios y Lógica de Negocio (`apps/platforms/tests/test_services.py`)

| Prueba | Resultado Esperado |
| --- | --- |
| `test_publish_platform_succeeds_when_complete` | Una plataforma completa, incluida su URL pública en `LinkCheckLog`, pasa a `PUBLICADO` y registra `validated_by` y `validated_at`. |
| `test_non_harvestable_platform_can_be_published_without_api_url` | Una Platform no cosechable puede publicarse sin `base_api_url`. |
| `test_harvestable_platform_cannot_be_published_without_api_url` | Una Platform cosechable no puede publicarse sin URL técnica. |
| `test_publish_platform_fails_when_incomplete` | Lanza `ValidationError` detallando los campos o relaciones obligatorias que faltan. La ausencia de `base_api_url` por sí sola no genera error cuando no existe API Key. |
| `test_publish_requires_public_url_to_be_verified` | Rechaza la publicación cuando la URL vigente todavía no ha sido comprobada. |
| `test_publish_rejects_unavailable_public_url` | Rechaza la publicación con un mensaje distinto cuando el último chequeo falló. |
| `test_registered_url_starts_unverified` | Registra una URL nueva con `is_active=False` y `last_check=null`. |
| `test_lifecycle_transitions_obsolete_and_reactivate` | Transición controlada `BORRADOR` → `PUBLICADO` → `OBSOLETO` → `BORRADOR`, limpiando la validación al reactivar. |
| `test_validate_safe_http_url_blocks_internal_and_private_ips` | Protección preventiva contra SSRF bloqueando `localhost`, `127.0.0.1` y rangos privados. |
| `test_check_platform_link_records_consecutive_fail_count` | Registra la URL pública en `LinkCheckLog`, incrementa `fail_count` ante fallos consecutivos y lo reinicia a `0` ante una respuesta exitosa. |

### 2.4. Endpoints y API (`apps/platforms/tests/test_api.py`)

| Prueba | Resultado Esperado |
| --- | --- |
| `test_create_platform_endpoint` | `POST /api/platforms/` crea la plataforma en estado `BORRADOR`, retorna HTTP 201 y no expone la clave cifrada. |
| `test_publish_action_endpoint` | `POST /api/platforms/{id}/publish/` ejecuta las validaciones de negocio y publica la plataforma cuando la ficha está completa. |
| `test_restore_action_resets_status_to_draft` | `POST /api/platforms/{id}/restore/` restaura una plataforma desde la papelera y fuerza `status = BORRADOR`, limpiando la validación previa. |
| `test_public_endpoint_only_lists_published_platforms` | `GET /api/platforms/public/` solo expone plataformas con `status = PUBLICADO` e incluye el correlativo `item_number`. |
| `test_public_filter_by_catalog_relations` | Se validan los filtros relacionales en singular, por ejemplo `?country=...`, respetando el estado activo de la relación y del catálogo. |
| `test_create_platform_defaults_to_not_harvestable` | Un POST que omite `is_harvestable` persiste y devuelve `false`. |
| `test_create_platform_accepts_explicit_not_harvestable` | Un POST con `is_harvestable=false` conserva explícitamente ese valor. |
| `test_link_history_orders_checks_newest_first_and_pending_last` | El historial pagina después de ordenar las verificaciones más recientes y deja los registros sin verificar al final. |
| `test_link_history_uses_created_at_and_id_as_tiebreakers` | Los empates de `last_check` se resuelven de forma determinística con `created_at` e identificador descendentes. |
| `test_successful_check_is_consistent_with_history` | Un chequeo HTTP 200 coincide en la respuesta de la acción, el historial y `link_status`. |
| `test_link_history_can_exclude_journal_urls` | El filtro `journal_platform__isnull=true` separa el historial general de las URLs contextuales de Journals. |
| `test_link_history_filters_by_verification_status` | Distingue en el historial URLs sin verificar, disponibles y no disponibles. |

### 2.5. Clasificación derivada (`apps/platforms/tests/test_classification.py`)

| Prueba | Resultado Esperado |
| --- | --- |
| `test_uses_only_eligible_journals` | Solo las Journals activas, validadas, no eliminadas y con relación activa aportan clasificación. |
| `test_incomplete_eligible_classification_moves_published_to_draft` | Una clasificación elegible incompleta devuelve una Platform publicada a `BORRADOR` y limpia su validación. |
| `test_effective_manual_journal_area_is_derived_in_platform` | Un área manual efectiva de Journal se propaga como derivada al nivel Platform. |

---

## 3. Comportamiento de `LinkCheckLog`

`LinkCheckLog` es el componente encargado de mantener el historial de verificación de las URLs públicas de las plataformas.

Un log con `journal_platform=null` pertenece a la URL pública general de la
Platform. Un log con `journal_platform` pertenece a la URL de una Journal
dentro de esa Platform; en ese caso ambos FKs deben señalar la misma Platform.

Cada verificación registra, entre otros datos:

- Plataforma asociada.
- URL pública verificada.
- Código HTTP obtenido.
- Estado de disponibilidad.
- Cantidad de fallos consecutivos.
- Fecha de la última comprobación.
- Información de auditoría.

La URL registrada en `LinkCheckLog` es independiente de `Platform.base_api_url`.

Esto permite que una plataforma tenga, por ejemplo:

```json
{
    "base_api_url": null,
    "api_key": null
}
```

y aun así pueda tener:

```text
LinkCheckLog.url
    ↓
https://www.plataforma.edu.co
```

y ser publicada como plataforma de referencia.

---

## 4. Ciclo de vida de una plataforma

El ciclo de vida validado actualmente es:

```text
BORRADOR
    │
    │ publicar
    ▼
PUBLICADO
    │
    │ marcar obsoleta
    ▼
OBSOLETO
    │
    │ reactivar
    ▼
BORRADOR
```

Adicionalmente, el sistema maneja eliminación lógica mediante Soft Delete.

Cuando una plataforma es restaurada desde la papelera:

- Se elimina el estado de eliminación.
- Se fuerza el estado `BORRADOR`.
- Se limpia `validated_by`.
- Se limpia `validated_at`.
- Debe pasar nuevamente por el proceso de validación antes de publicarse.

---

## 5. Seguridad

Las pruebas incluyen validaciones relacionadas con:

### API Key

La API Key:

- Se recibe únicamente como campo de escritura.
- Se almacena cifrada.
- No se retorna en texto plano.
- No puede existir lógicamente sin una `base_api_url`.

### Verificación de enlaces

La verificación de URLs incorpora protección contra destinos internos o privados, evitando consultar directamente:

```text
localhost
127.0.0.1
192.168.x.x
```

y otros destinos no públicamente enrutables.

### Información pública

Los serializers públicos no deben exponer:

- API Keys.
- Campos cifrados.
- Información interna de auditoría.
- Datos administrativos que no correspondan al consumidor público.

---

## 6. Estado actual de las pruebas

La suite cubre modelos, filtros, serializadores, servicios, clasificación y
API. El runner de Django informa el total vigente al inicio de cada ejecución.

---

## 7. Ejecutar Pruebas

Para ejecutar la suite completa de `platforms` dentro del contenedor Docker:

```bash
docker compose -f docker/docker-compose.yml run --rm -e DJANGO_TESTING=true web python manage.py test apps.platforms --keepdb
```

Para ejecutar únicamente los tests de servicios:

```bash
docker compose -f docker/docker-compose.yml run --rm -e DJANGO_TESTING=true web python manage.py test apps.platforms.tests.test_services --keepdb
```

Para ejecutar únicamente los tests de API:

```bash
docker compose -f docker/docker-compose.yml run --rm -e DJANGO_TESTING=true web python manage.py test apps.platforms.tests.test_api --keepdb
```

Para ejecutar únicamente los tests de serializers:

```bash
docker compose -f docker/docker-compose.yml run --rm -e DJANGO_TESTING=true web python manage.py test apps.platforms.tests.test_serializers --keepdb
```

La bandera `--keepdb` permite reutilizar la base de datos temporal de pruebas y evitar la recreación completa en cada ejecución, especialmente útil en el entorno PostgreSQL utilizado por el proyecto.

---

## 8. Resultado de las pruebas

La aplicación `platforms` queda validada para continuar con la siguiente fase de desarrollo.

Las reglas principales verificadas son:

- Gestión segura y opcional de API Key.
- Separación entre API de cosecha y URL pública.
- URL pública gestionada mediante `LinkCheckLog`.
- Validación de enlaces.
- Control de fallos consecutivos.
- Clasificación derivada de Journals elegibles mediante programas académicos.
- Derivación automática de áreas del conocimiento.
- Control del ciclo de vida de plataformas.
- Publicación condicionada al cumplimiento de los requisitos.
- Restauración mediante Soft Delete.
- Protección de información sensible.
- Filtros y endpoints públicos.
- Documentación de la API mediante Swagger/OpenAPI.

La cobertura documentada corresponde al comportamiento vigente de `platforms`.
## Fase estructural: URLs obligatorias y chequeo por Platform

La creación administrativa exige `public_url` y comprueba que su registro sea
atómico mediante `LinkCheckLog`. El endpoint `check-links` cubre la URL general
y las URLs contextuales vigentes, ignora relaciones eliminadas y conserva los
resultados independientes ante fallos parciales.
# Fechas automáticas del ciclo de vida

- `start_period` se asigna con la fecha local al crear la plataforma.
- `finish_period` queda en `null` hasta `mark-obsolete`.
- `reactivate` y restore limpian `finish_period` sin cambiar `start_period`.
- POST, PUT y PATCH rechazan valores manuales para ambas fechas.
- Publish no modifica ninguna de las dos fechas.

## Revisión de filtros — 14 de octubre de 2026

`tests/test_filters.py` cubre los FilterSets administrativos y públicos:

- los tres valores reales de `status`: `borrador`, `publicado`, `obsoleto`;
- booleanos de cosecha, registro y acceso a texto;
- sintaxis e instituciones, países, idiomas, áreas, materiales y programas;
- filtros combinados, `search`, `ordering`, `page` y `page_size`;
- exclusión de relaciones eliminadas y ausencia de duplicados por joins;
- rechazo de estados inválidos;
- garantía de que `/public/` nunca devuelve Platforms no publicadas aunque
  coincidan los demás filtros.

El endpoint público no incorpora `status`, porque su queryset ya restringe el
resultado a `PUBLICADO`.
# Cobertura de la ampliación de reglas

La fase incluye ahora escenarios para creación incompleta en borrador,
publicación con secciones efectivas, procedencia manual/derivada, recálculo
desde Journals elegibles, sintaxis similares y verificación global de enlaces.
También deben comprobarse los filtros contextuales de catálogos y los bloqueos
de eliminación de Platform y ValidSintaxis en uso.
