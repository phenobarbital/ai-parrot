# Síntesis por Consenso - Autor: Claude

**Consenso alcanzado con confianza del 90%**. La síntesis de Claude fue seleccionada por proporcionar una visión clara, concisa y bien estructurada de la interfaz DocumentDB, con todas las secciones clave, ejemplos de código relevantes y explicaciones precisas. El uso de tablas y viñetas mejora significativamente la legibilidad y comprensión del contenido.

---

# Síntesis: Guía de la Interfaz DocumentDB

## Descripción General

La interfaz `DocumentDb` permite interactuar con AWS DocumentDB o bases de datos compatibles con MongoDB. Las credenciales se cargan automáticamente desde `navconfig` (variables de entorno).

---

## Inicialización

```python
from parrot.interfaces.documentdb import DocumentDb

db = DocumentDb()
await db.documentdb_connect()  # Conexión explícita (opcional, es lazy)
```

---

## Creación de Colecciones y Buckets

En DocumentDB/MongoDB, las bases de datos y colecciones se crean típicamente en la primera escritura. Sin embargo, es posible crearlas explícitamente para configurar opciones o garantizar su existencia.

| Método | Descripción |
|--------|-------------|
| `create_collection("nombre")` | Crea una colección con opciones específicas |
| `create_bucket("nombre")` | Crea un bucket GridFS o agrupación lógica |

---

## Indexación

Para mejorar el rendimiento de las consultas, se pueden crear índices en campos específicos.

**Ejemplo de índice compuesto:**

```python
keys = [
    ("session_id", 1),   # 1 = Ascendente
    ("turn_id", 1)       # -1 = Descendente
]
await db.create_indexes("conversations", keys)
```

---

## Streaming de Datos

Para manejar grandes volúmenes de datos sin cargar todo en memoria, se ofrecen dos métodos de streaming:

### Iteración Individual (`iterate`)
Procesa documentos uno por uno desde el cursor de la base de datos:

```python
async for turn in db.iterate(collection, query):
    print(f"Processing turn {turn['turn_id']}")
```

### Procesamiento por Lotes (`read_chunks`)
Procesa documentos en listas de tamaño específico, útil para procesamiento masivo:

```python
async for batch in db.read_chunks(collection, query, chunk_size=50):
    print(f"Batch de {len(batch)} documentos")
```

---

## Guardado en Segundo Plano

El método `save_background` permite escribir datos sin bloquear el flujo principal de ejecución. La operación se ejecuta como una tarea asyncio en segundo plano (fire-and-forget).

```python
db.save_background("conversations", data)
# Retorna inmediatamente; el guardado ocurre en background
```

---

## Ejemplo Completo

El flujo típico de uso incluye:

1. **Configuración inicial**: Crear colección e índices
2. **Escritura asíncrona**: Guardar datos en segundo plano
3. **Lectura por streaming**: Recuperar datos iterativamente

```python
async def main():
    db = DocumentDb()
    
    await db.create_collection("conversations")
    await db.create_indexes("conversations", [("session_id", 1), ("turn_id", 1)])
    
    db.save_background("conversations", turn_data)
    
    async for turn in db.iterate("conversations", {"session_id": "sess-01"}):
        print("Read turn:", turn)
```

---

## Características Clave

- **Conexión lazy**: Se conecta solo cuando es necesario
- **Compatibilidad**: AWS DocumentDB y MongoDB
- **Operaciones asíncronas**: Soporte completo para `async/await`
- **Eficiencia de memoria**: Streaming para grandes datasets
- **No bloqueante**: Guardado en segundo plano para mejor rendimiento
