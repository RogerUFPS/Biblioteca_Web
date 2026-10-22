# Endpoints de cuentas y permisos

Base URL: `/api/accounts/`. Los cuerpos y respuestas usan JSON. Las sesiones se
mantienen en la cookie `sessionid`; el cliente debe enviar cookies con las
solicitudes (`credentials: "include"` o equivalente). Para solicitudes
protegidas contra CSRF, obtener primero `/auth/csrf/` y enviar el valor de la
cookie `csrftoken` en la cabecera `X-CSRFToken`.

Los endpoints de registro, inicio de sesión, CSRF y recuperación de contraseña
son públicos. Las cuentas registradas no reciben permisos automáticamente. La
contraseña no se incluye en ninguna respuesta.

## Sesión y perfil

### `GET /auth/csrf/`

Genera/renueva la cookie CSRF.

Respuesta `200`:

```json
{"detail": "Token CSRF disponible en la cookie csrftoken."}
```

### `POST /auth/login/`

Requiere CSRF.

```json
{
  "email": "ana@example.org",
  "password": "contraseña"
}
```

Ambos atributos son obligatorios. Respuesta `200`:

```json
{
  "user": {
    "id": 12,
    "email": "ana@example.org",
    "collegue_code": "A-100",
    "full_name": "Ana Pérez",
    "is_active": true,
    "is_superadmin": false,
    "force_password_change": false,
    "permissions": {},
    "effective_permissions": {},
    "presets": [],
    "created_at": "2026-10-10T20:00:00Z",
    "updated_at": null
  },
  "must_change_password": false,
  "previous_session_terminated": false
}
```

`previous_session_terminated` indica que la sesión previa de esta cuenta fue
desconectada. Un usuario con una contraseña provisional recibe
`must_change_password: true` y debe cambiarla antes de utilizar otros endpoints.
Credenciales incorrectas responden `401`; una solicitud sin CSRF responde `403`.

### `POST /auth/logout/`

Requiere sesión y CSRF. No recibe cuerpo.

Respuesta `200`:

```json
{"detail": "Sesión cerrada."}
```

### `GET /auth/me/` y `PATCH /auth/me/`

Requieren sesión. GET retorna el objeto de usuario descrito en la respuesta de
inicio de sesión. PATCH permite editar el perfil propio; todos sus campos son
opcionales:

```json
{
  "email": "ana.nueva@example.org",
  "full_name": "Ana Pérez López",
  "collegue_code": "A-101"
}
```

Respuesta `200`: perfil actualizado. El correo debe ser único.

### `POST /password/change/`

Requiere sesión y CSRF. Obligatorio:

```json
{
  "current_password": "contraseña actual",
  "new_password": "Una-clave-larga-2026"
}
```

La clave nueva debe tener al menos 12 caracteres, no ser común ni totalmente
numérica y no ser similar a los datos de la cuenta.

Respuesta `200`:

```json
{"detail": "La contraseña se cambió correctamente."}
```

Contraseña actual incorrecta o clave nueva inválida responde `400`.

### `POST /password/forgot/`

Público y protegido por CSRF. Atributo obligatorio:

```json
{"email": "ana@example.org"}
```

Respuesta `200` (tanto si el correo existe como si no):

```json
{
  "detail": "Si el correo está registrado, recibirás una contraseña provisional."
}
```

Si el correo corresponde a una cuenta activa, se envía una clave provisional y
se exige cambiarla al iniciar sesión. Si el envío de correo falla, responde
`503` con `detail`.

### `POST /register/`

Público y protegido por CSRF. Obligatorios: `email`, `password`. Opcionales:
`full_name`, `collegue_code`.

```json
{
  "email": "ana@example.org",
  "password": "Una-clave-larga-2026",
  "full_name": "Ana Pérez",
  "collegue_code": "A-100"
}
```

Respuesta `201`: objeto de usuario. La cuenta inicia sin permisos y sin presets.
Correo duplicado o clave no válida responde `400`.

## Administración de cuentas

Las rutas de esta sección requieren el permiso `accounts.users` que corresponda.
Sólo el superadmin o una cuenta con permiso explícito puede administrar otras
cuentas.

### `GET /users/`

Permiso `view`. Sin cuerpo. Respuesta `200`: lista de objetos de usuario.

### `GET /users/archived/`

Permiso `view`. Sin cuerpo. Respuesta `200`: lista de cuentas eliminadas
lógicamente. El `id` de cada cuenta se usa para recuperarla con
`POST /users/{id}/restore/`.

### `POST /users/invite/`

Permiso `invite`. Requeridos: `email`. Opcionales: `full_name`,
`collegue_code`.

```json
{
  "email": "pedro@example.org",
  "full_name": "Pedro Gómez",
  "collegue_code": "P-12"
}
```

Respuesta `201`: objeto de usuario sin credenciales; se envía al correo una
contraseña provisional y se exige cambiarla al iniciar sesión. La cuenta queda
sin presets y sin permisos. Error de envío responde `503`; correo duplicado
responde `400`.

### `GET /users/{id}/`

Permiso `view`. Sin cuerpo. Respuesta `200`: objeto de usuario; inexistente
responde `404`.

### `PATCH /users/{id}/`

Permiso `update`. Los campos son opcionales:

```json
{
  "full_name": "Pedro Gómez",
  "collegue_code": "P-13",
  "is_active": true
}
```

Respuesta `200`: usuario actualizado. No se permite editar al superadmin por
esta ruta.

### `DELETE /users/{id}/`

Permiso `delete`. Sin cuerpo. Desactiva la cuenta e invalida su sesión.
Respuesta `204`; cuenta inexistente responde `404`. No se puede desactivar al
superadmin.

### `POST /users/{id}/restore/`

Permiso `restore`. Sin cuerpo. Restaura una cuenta eliminada lógicamente y la
deja activa. Respuesta `200`: objeto de usuario actualizado. Si la cuenta ya
está activa responde `400`; si no existe responde `404`. No se puede restaurar
al superadmin mediante esta ruta.

### `PUT /users/{id}/permissions/`

Permiso `manage_permissions`. Reemplaza los permisos directos (no los recibidos
por presets). Las secciones, recursos y acciones válidas se consultan en
`GET /permissions/`.

```json
{
  "permissions": {
    "catalog": {
      "knowledge-areas": {
        "view": false,
        "update": true
      }
    }
  }
}
```

Cada permiso enviado debe ser booleano. Si `create`, `update`, `delete`,
`restore` u otra acción se activa, `view` también queda activado
automáticamente. Respuesta `200`: usuario actualizado con permisos directos y
efectivos. Un recurso o una acción desconocidos responden `400`.

### `PUT /users/{id}/presets/`

Permiso `manage_permissions`. Reemplaza los presets asignados; la lista puede
estar vacía.

```json
{"preset_ids": [2, 5]}
```

`preset_ids` es obligatorio; cada elemento es el ID de un preset existente y no
se permiten duplicados. Respuesta `200`: usuario actualizado con presets y
permisos efectivos. IDs inexistentes responden `400`.

## Presets de permisos

Los endpoints de presets requieren los permisos de `accounts.presets`.

### `GET /presets/`

Permiso `view`. Sin cuerpo. Respuesta `200`: lista de presets.

### `POST /presets/`

Permiso `create`. Requeridos: `name`. Opcionales: `description`,
`permissions` (por defecto `{}`).

```json
{
  "name": "Administrador de revistas",
  "description": "Gestiona el ciclo de vida de revistas",
  "permissions": {
    "journals": {
      "journals": {
        "create": true,
        "update": true,
        "delete": true,
        "publish": true,
        "deactivate": true,
        "restore": true
      }
    }
  }
}
```

Respuesta `201`: preset creado. La asignación se realiza mediante
`PUT /users/{id}/presets/`. Las modificaciones a un preset se reflejan en las
cuentas que lo tienen asignado.

### `GET /presets/{id}/`

Permiso `view`. Sin cuerpo. Respuesta `200`: preset; si no existe, `404`.

### `PATCH /presets/{id}/`

Permiso `update`. Campos opcionales: `name`, `description`, `permissions`.
`permissions` reemplaza toda la configuración de permisos del preset.
Respuesta `200`: preset actualizado.

### `DELETE /presets/{id}/`

Permiso `delete`. Sin cuerpo. Respuesta `204`.

## Catálogo de permisos disponibles

### `GET /permissions/`

Requiere sesión. Sin cuerpo. Respuesta `200`: cada recurso incluye una lista de
acciones permitidas. Para activar una acción, el objeto de configuración debe
usar su nombre como clave y un booleano como valor.

- `audit.logs`: `view`
- `catalog.institutions`, `languages`, `countries`, `material-types`,
  `editorials`, `knowledge-areas`, `academic-programs`: `view`, `create`,
  `update`, `delete`, `restore`
- `journals.journals`: `view`, `create`, `update`, `delete`, `publish`,
  `deactivate`, `restore`
- `platforms.platforms`: `view`, `create`, `update`, `delete`, `publish`,
  `mark_obsolete`, `reactivate`, `check_link`, `restore`
- `platforms.valid-sintaxis`: `view`, `create`, `update`, `delete`, `restore`
- `platforms.link-check-logs`: `view`
- `harvesting.schedules`: `view`, `create`, `update`, `delete`, `restore`,
  `run_due`
- `harvesting.events`: `view`
- `harvesting.harvests`: `view`, `pause`, `resume`
- `accounts.users`: `view`, `update`, `delete`, `restore`, `invite`,
  `manage_permissions`
- `accounts.presets`: `view`, `create`, `update`, `delete`
- `accounts.permissions`: `view`

El superadmin tiene todas las acciones activas. Además de los endpoints públicos
de cuenta descritos arriba, todos los GET de `catalog` son públicos y sólo de
lectura; los GET bajo `/api/journals/public/` y `/api/platforms/public/` también
son públicos. Las demás rutas de negocio exigen autenticación y el permiso
correspondiente.

## Configuración de correo y creación del superadmin

Configurar `RESEND_API_KEY` y `DEFAULT_FROM_EMAIL` con el remitente verificado
en Resend. Si `DEFAULT_FROM_EMAIL` no está definido, también se acepta
`RESEND_FROM_EMAIL`; su valor local predeterminado es `onboarding@resend.dev`.
Los correos de invitación y recuperación incluyen un enlace a la página de
inicio de sesión; su URL puede cambiarse con `FRONTEND_LOGIN_URL` (por defecto,
`https://repositorio-biblioteca-frontend.vercel.app/admin/login`).
Después de aplicar migraciones:

```bash
python manage.py migrate
python manage.py create_superadmin \
  --email admin@example.org \
  --full-name "Administración del sistema"
```

El comando solicita la contraseña dos veces sin mostrarla ni incluirla en el
historial de la terminal.
