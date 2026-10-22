# Pruebas de la Fase A

Estas pruebas documentan el comportamiento implementado sin autenticación,
usando el usuario sistema con `code=0`.

Estado de validación: las pruebas se ejecutaron correctamente con Docker
Desktop usando una base SQLite aislada para pruebas.

```text
Found 5 test(s).
Ran 5 tests in 0.096s
OK
```

## Casos cubiertos

| Prueba | Resultado esperado |
| --- | --- |
| Crear un idioma desde la API | HTTP 201 y `created_by` asignado al usuario sistema |
| Actualizar un idioma | HTTP 200 y `updated_by`/`updated_at` asignados |
| Borrar una editorial | HTTP 204, sin eliminar físicamente la fila |
| Restaurar una editorial | HTTP 200 y registro visible nuevamente |
| Reutilizar el nombre de un registro eliminado | HTTP 400 |
| Borrar sin explicación | HTTP 400 |

## Ejecutar

```bash
docker compose -f docker/docker-compose.yml run --rm -e DJANGO_TESTING=true web python manage.py test apps.catalog.test
```

Estas pruebas no cubren autenticación JWT ni autorización por permisos; esas
funcionalidades pertenecen a la Fase B.
