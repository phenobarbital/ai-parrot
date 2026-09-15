# ArangoDB local para AI-Parrot

Este stack levanta ArangoDB en `127.0.0.1:8529`, que coincide con los
valores por defecto usados por AI-Parrot:

```text
ARANGODB_HOST=127.0.0.1
ARANGODB_PORT=8529
ARANGODB_PROTOCOL=http
ARANGODB_USERNAME=root
ARANGODB_PASSWORD=
```

## Arranque

Desde este directorio:

```bash
docker compose up -d --build
docker compose ps
```

La interfaz web queda disponible en <http://127.0.0.1:8529>.

Para conectar una aplicación que use la configuración de Parrot:

```bash
export ARANGODB_HOST=127.0.0.1
export ARANGODB_PORT=8529
export ARANGODB_PROTOCOL=http
export ARANGODB_USERNAME=root
export ARANGODB_PASSWORD=
```

Los datos se guardan en los volúmenes Docker `parrot-arangodb-data` y
`parrot-arangodb-apps`. Para detener el servicio conservando los datos:

```bash
docker compose down
```

## Activar autenticación

Para usar una contraseña, crea un fichero `.env` en este directorio o exporta
las variables antes de arrancar:

```bash
export ARANGO_NO_AUTH=0
export ARANGODB_PASSWORD=change-me
docker compose up -d --build
```

En ese caso, configura el mismo valor en `ARANGODB_PASSWORD` para Parrot.
