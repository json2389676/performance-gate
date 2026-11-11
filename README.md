# Performance Quality Gate

Action de GitHub que compara los resultados de una prueba de carga (JMeter) contra los de producción y **deja el pipeline en rojo si la versión nueva es más lenta o falla más**. Explica qué endpoint incumple, por cuánto y qué debería mejorar el equipo.

## ¿Cuál versión reemplaza a producción y por qué?

**La versión B reemplaza a producción. La versión A no.**

Todas las pruebas arrancan lentas (calentamiento). Si se mide el archivo completo, A y B parecen peores que producción. Pero el gate compara el rendimiento ya estabilizado (se ignoran los primeros 60 s), y ahí se ve la diferencia real:

| Endpoint (p95, desde el seg. 60) | Producción | Versión A | Versión B |
|---|---:|---:|---:|
| Consultar saldo, cuenta ahorros | 206 ms | 206 ms | 207 ms |
| GET /clientes | 162 ms | 162 ms | 162 ms |
| POST /pagos | 353 ms | **767 ms (+117 %)** | 353 ms |
| Errores en POST /pagos | 0,25 % | **3,33 %** | 0,08 % |
| POST /transferencias (nuevo) | no existe | 266 ms | 265 ms |

- **A no pasa:** `POST /pagos` queda más del doble de lento que producción y con 13 veces más errores, de forma sostenida durante toda la prueba. Debe bajar el p95 de pagos a 371 ms o menos y la tasa de errores a 0,75 % o menos.
- **B pasa:** una vez estabilizada, es indistinguible de producción en todos los endpoints comparables y agrega `POST /transferencias` con buen rendimiento.

**Lo que el equipo de B debe vigilar (no bloquea, pero queda como advertencia):**
1. **Arranque más lento.** B tarda cerca de 60 s en estabilizarse; producción, unos 20-30 s. En el primer minuto el p95 de pagos es 1.221 ms frente a 742 ms en producción. Si en un despliegue real hay tráfico durante el arranque, los usuarios lo notarán. Se puede comprobar con `warmupSeconds: 0`: en ese caso B no pasa.
2. **`GET /reportes`** tiene solo 4 peticiones por prueba (3 tras el calentamiento) y en B una de ellas tardó 2.600 ms (las demás, ~800 ms). Con tan pocas muestras no se puede concluir nada: hay que repetir la prueba con más tráfico a ese endpoint.

> **Decisión que conviene defender:** ignorar 60 s de calentamiento es un límite configurable, no una verdad universal. Con 60 s B pasa; con 0 s no. El valor por defecto se eligió porque en estos datos producción y A se estabilizan alrededor de los 30 s y B cerca del minuto 1, y 60 s es un 20 % de una prueba de 5 minutos. Cada equipo debe ajustarlo a su caso.

## Cómo usarla

En el workflow de tu repositorio:

```yaml
- uses: actions/checkout@v4

- name: Performance Quality Gate
  uses: json2389676/performance-gate@main
  with:
    baseline: resultados/produccion-actual.csv   # prueba de producción
    candidate: resultados/mi-version.csv         # prueba de la versión nueva
    config: config/performance-gate.json         # opcional
```

| Input | Obligatorio | Descripción |
|---|---|---|
| `baseline` | sí | CSV de JMeter de producción |
| `candidate` | sí | CSV de JMeter de la versión nueva |
| `config` | no | JSON con los límites; si se omite se usan los de por defecto |
| `format` | no | Formato de los resultados (por ahora solo `jmeter`) |
| `title` | no | Título del reporte |
| `report-dir` | no | Carpeta de salida de `report.md` y `report.json` (por defecto `performance-gate-report`) |

El resultado se escribe en el **resumen de la ejecución** (tabla por endpoint, motivos y mejoras) y el step termina en error si la versión no pasa, lo que pone el job en rojo.

También se puede ejecutar localmente, sin dependencias (Python 3):

```bash
python3 src/gate.py --baseline resultados/produccion-actual.csv \
  --candidate resultados/version-a.csv --config config/performance-gate.json
python3 -m unittest discover -s tests
```

Códigos de salida: `0` pasa, `1` no pasa, `2` error en datos o configuración (nunca se aprueba por error). Opciones útiles: `--warmup-seconds N`, `--report-md RUTA`, `--report-json RUTA`.

## Configuración y límites

Archivo de ejemplo: [config/performance-gate.json](config/performance-gate.json). Todo es opcional; lo que no se defina usa el valor por defecto.

```json
{
  "warmupSeconds": 60,
  "defaults": {
    "p95RegressionPercent": 10,
    "p95RegressionMinMs": 20,
    "errorRateIncreasePercentagePoints": 0.5,
    "minimumSamples": 100
  },
  "endpoints": {
    "POST /pagos": { "p95RegressionPercent": 5 }
  },
  "onNewEndpoint": "warn",
  "onMissingEndpoint": "fail",
  "onInconclusive": "warn"
}
```

| Clave | Por defecto | Significado |
|---|---:|---|
| `warmupSeconds` | 60 | Segundos iniciales de cada prueba que se ignoran (calentamiento). `0` mide todo |
| `p95RegressionPercent` | 10 | Cuánto puede subir el p95 respecto a producción (%) |
| `p95RegressionMinMs` | 20 | El p95 solo falla si además sube más de estos ms (evita falsos rechazos en endpoints muy rápidos) |
| `errorRateIncreasePercentagePoints` | 0,5 | Cuánto puede subir la tasa de errores, en puntos porcentuales |
| `minimumSamples` | 100 | Mínimo de peticiones por endpoint para poder concluir algo |
| `endpoints.<nombre>` | – | Sobrescribe cualquiera de los tres límites anteriores para un endpoint |
| `onNewEndpoint` | `warn` | Endpoint que no existe en producción (no hay línea base) |
| `onMissingEndpoint` | `fail` | Endpoint de producción que no aparece en la versión nueva |
| `onInconclusive` | `warn` | Endpoint con menos de `minimumSamples` |

Las claves desconocidas o los valores inválidos dan error (código 2) en vez de ignorarse.

**Por qué estos valores:** el **p95** representa lo que vive casi todo usuario y no se distorsiona con un valor extremo como lo hace el promedio. Un 10 % de margen absorbe el ruido normal entre pruebas (en estos datos, el p95 de producción varía cerca de un 2 % entre ventanas de tiempo); pagos es más estricto por ser crítico. Un endpoint nuevo es normal en una versión nueva, así que advierte; uno que desaparece sí hace fallar.

## Cómo se manejaron las rarezas de los datos

- **Calentamiento:** las tres pruebas arrancan lentas (de 2 a 3 veces el promedio normal: producción y A en los primeros 20-30 s, B hasta cerca del minuto 1). Se ignoran los primeros `warmupSeconds`, medidos desde la primera petición del archivo.
- **Filas desordenadas:** las filas no vienen ordenadas por `timeStamp`, por eso el calentamiento se calcula con el mínimo del archivo y no con la posición de la fila.
- **Distinta cantidad de filas** (6.083 / 6.047 / 6.059): con usuarios fijos, una versión más lenta hace menos peticiones. Se comparan p95 y porcentajes, nunca totales.
- **`GET /reportes`:** solo 4 peticiones por prueba. Se marca como inconcluso (advertencia) en lugar de aprobarlo o reprobarlo.
- **`POST /transferencias`:** existe en A y B pero no en producción. Se informa como endpoint nuevo sin línea base.
- **Nombre con coma:** `"Consultar saldo, cuenta ahorros"` viene entre comillas; se lee con un parser CSV estándar.
- Se verificó que no hay filas duplicadas, que `success` es coherente con `responseCode` y que `Latency` nunca supera a `elapsed`.

## Alcance y cómo agregar k6

Hoy solo se leen CSV de JMeter. El resto del gate trabaja con una estructura neutra por endpoint (`muestras`, `promedio`, `p95`, `tasa_errores`), así que soportar k6 es agregar un lector en `src/` que devuelva esa estructura y registrarlo en `LECTORES` (`src/jmeter.py`); no cambian las reglas ni los reportes.

Limitaciones conocidas: es una action de GitHub (no hay task de Azure DevOps) y el reporte es el resumen de la ejecución, sin página visual aparte.

## Ejecuciones del pipeline

Workflow [`performance-gate.yml`](.github/workflows/performance-gate.yml): un job por versión, con la misma configuración. Resultado esperado: **Gate versión A en rojo, Gate versión B en verde**. Las ejecuciones están en la pestaña [Actions](https://github.com/json2389676/performance-gate/actions).

## Estructura

```
action.yml                       Action reutilizable
src/jmeter.py                    Lector de JMeter y métricas
src/config.py                    Lectura y validación de límites
src/gate.py                      Comparación, reportes y código de salida
config/performance-gate.json     Límites de ejemplo
tests/test_gate.py               Pruebas unitarias
resultados/                      Datos del reto
.github/workflows/               CI y pipeline para las versiones A y B
```
