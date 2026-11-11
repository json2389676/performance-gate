# Paso a paso: Performance Quality Gate

Esta guía propone una forma práctica de desarrollar el reto y demostrarlo en una entrevista. El objetivo es comparar una prueba de carga nueva con producción, explicar cualquier regresión y hacer que el pipeline falle cuando la versión no cumpla los límites.

## Qué se entrega y qué pasos lo producen

| Entregable del reto | Qué es | Pasos de esta guía |
|---|---|---|
| 1. El repositorio | El código de la herramienta en GitHub (público, o uno que los evaluadores puedan ver) | 1, 4, 5 |
| 2. Las ejecuciones del pipeline | El link (o capturas) de la ejecución con la versión A y la de la versión B, en rojo si no pasan | 6 |
| 3. El README | Cómo usar la herramienta y la respuesta a "¿cuál versión reemplaza a producción y por qué?" | 7, 8 |

El paso 1 solo pide una cuenta de GitHub, que ya tiene. Lo que falta de ese paso es crear el repositorio y subir el código.

## ¿Qué pide el reto?

Una **herramienta automática** (una *action* de GitHub o una *task* de Azure DevOps) que reciba dos resultados de pruebas de carga:

- los de **producción**, que sirven de referencia;
- los de una **versión nueva** (A o B).

La herramienta compara ambos y responde:

1. ¿La versión nueva pasa o no?
2. ¿Por qué? Por ejemplo: "pagos tarda el doble que en producción".
3. Si no pasa, deja el pipeline en **rojo**.
4. Cada equipo puede ajustar sus **límites**, incluso uno distinto por endpoint.

## Conceptos clave

- **Endpoint:** cada "acción" de la aplicación, como `POST /pagos` o `GET /clientes`. Se compara cada uno por separado.
- **elapsed:** los milisegundos que tardó cada petición.
- **p95:** el valor bajo el cual quedó el 95 % de las peticiones. Si el p95 es 570 ms, el 95 % de los usuarios esperó 570 ms o menos. Es mejor que el promedio, porque el promedio oculta las peticiones muy lentas.
- **Tasa de errores:** el porcentaje de peticiones con `success=false` (códigos 500).
- **Límite o umbral:** hasta cuánto empeoramiento se tolera. Por ejemplo, "máximo 10 % más lento que producción".

## La lógica en 4 pasos

1. **Leer** los dos CSV y agrupar las filas por endpoint.
2. **Calcular** el p95 y la tasa de errores de cada endpoint, en producción y en la versión nueva.
3. **Comparar** con la regla: "¿el p95 nuevo supera al de producción en más del límite?" y "¿hay más errores de los permitidos?".
4. **Decidir:** si algún endpoint incumple, la versión falla y el programa termina con código de error. Eso pone el pipeline en rojo.

### Ejemplo con los datos del reto

| Endpoint | p95 producción | p95 versión A | Veredicto |
|---|---:|---:|---|
| POST /pagos | 570 ms | 1.302 ms | **Falla** (+128 %) |
| GET /clientes | 272 ms | 272 ms | Pasa |

La versión A es igual a producción en casi todo, pero **pagos** se volvió mucho más lento y tiene más errores (2,8 % frente a 0,3 %). Por eso A no pasa. La versión B es más lenta en casi todos los endpoints, así que tampoco pasa.

## Decisiones iniciales sugeridas

- **Plataforma:** GitHub Actions, por ser rápida de configurar y fácil de mostrar. Los mismos pasos se pueden adaptar a Azure DevOps.
- **Lenguaje:** Python con la biblioteca estándar para leer los CSV sin agregar dependencias.
- **Métrica principal:** percentil 95 (`p95`) de `elapsed`, comparado por endpoint. Complementarlo con la tasa de errores.
- **Formato interno:** convertir los datos de JMeter a una estructura común por endpoint. Así, más adelante se puede agregar un lector de k6 sin cambiar las reglas de comparación.
- **Configuración:** límites globales con posibilidad de sobrescribirlos por endpoint.

## Paso 1. Preparar el repositorio y el entorno

1. Crea un repositorio en GitHub y copia los tres archivos de `resultados/`.
2. Crea una cuenta gratuita de GitHub si aún no tienes una.
3. Define la estructura inicial, por ejemplo:

   ```text
   performance-gate/
   ├── resultados/
   ├── config/
   │   └── performance-gate.json
   ├── src/
   │   └── performance_gate.py
   ├── tests/
   ├── .github/workflows/
   └── README.md
   ```

4. Mantén las pruebas pequeñas y ejecutables localmente; no dependas de credenciales ni de servicios de una empresa.

## Paso 2. Entender y perfilar los datos

1. Lee el CSV usando sus encabezados; no dependas del orden de las columnas.
2. Agrupa las solicitudes por `label` (endpoint).
3. Para cada endpoint calcula, como mínimo:
   - cantidad de solicitudes;
   - promedio y `p95` de `elapsed`;
   - solicitudes fallidas y tasa de errores;
   - códigos HTTP observados.
4. Usa `success` y los códigos de respuesta para detectar errores. Trata `true`/`false` sin distinguir mayúsculas y minúsculas.
5. Valida columnas y valores: duración no numérica, endpoint vacío o archivo sin filas deben producir un error claro, no un resultado aprobado.
6. No emparejes filas por `timeStamp` ni por usuario virtual: las muestras no son solicitudes equivalentes. Compara agregados por endpoint.
7. Registra las anomalías en el reporte. En estos archivos:
   - `GET /reportes` solo tiene **4 solicitudes** en cada ejecución; su percentil no es representativo. Márcalo como **inconcluso** o aplica un mínimo de muestras configurable.
   - `POST /transferencias` aparece en A y B, pero no en producción. No hay línea base con la cual comparar su rendimiento.
   - La cantidad de solicitudes por endpoint cambia entre archivos; compara cada endpoint por separado, no el total de filas.
   - El endpoint `Consultar saldo, cuenta ahorros` tiene un nombre distinto a los demás y contiene una coma, por lo que el lector de CSV debe respetar las comillas.

## Paso 3. Definir la regla de aprobación

Empieza con reglas simples, visibles y configurables. Por ejemplo:

1. Compara el `p95` de cada endpoint presente en producción y en la versión nueva.
2. Rechaza si el `p95` nuevo supera en más de **10 %** el de producción.
3. Rechaza si la tasa de errores supera la de producción en más de **0,5 puntos porcentuales**.
4. Define un mínimo de muestras por endpoint (por ejemplo, **100**). Si no se alcanza, informa “inconcluso”; no lo presentes como una aprobación confiable.
5. Permite límites globales y excepciones por endpoint, por ejemplo:

   ```json
   {
     "defaults": {
       "p95RegressionPercent": 10,
       "p95RegressionMinMs": 20,
       "errorRateIncreasePercentagePoints": 0.5,
       "minimumSamples": 100
     },
     "endpoints": {
       "POST /pagos": {
         "p95RegressionPercent": 5
       }
     },
     "onNewEndpoint": "warn",
     "onMissingEndpoint": "fail",
     "onInconclusive": "warn"
   }
   ```

   Los valores son un punto de partida, no una regla universal. `p95RegressionMinMs` evita falsos rechazos en endpoints muy rápidos: el p95 solo falla si sube más del porcentaje **y** más de esos milisegundos. Las claves `on...` definen qué pasa (`fail` o `warn`) con un endpoint nuevo sin línea base, con uno que desapareció de la prueba, o con uno con pocas muestras (inconcluso). Un endpoint nuevo es normal en una versión nueva, por eso por defecto solo advierte; uno que desaparece sí hace fallar.

   La implementación está en `src/` (`jmeter.py`, `config.py`, `gate.py`) y se ejecuta así:

   ```bash
   python3 src/gate.py --baseline resultados/produccion-actual.csv \
     --candidate resultados/version-a.csv --config config/performance-gate.json
   ```

   Códigos de salida: `0` pasa, `1` no pasa, `2` error de datos o configuración.

## Paso 4. Implementar el analizador

1. Separa el programa en funciones pequeñas:
   - lectura y validación del CSV;
   - cálculo de métricas por endpoint;
   - lectura y validación de configuración;
   - comparación y clasificación de resultados;
   - generación del reporte y código de salida.
2. Calcula el `p95` con un método consistente (por ejemplo, rango más cercano) y documenta el método.
3. Compara solo endpoints comunes a la línea base y a la versión candidata. Reporta aparte endpoints nuevos o ausentes.
4. Produce una explicación específica, por ejemplo: “No pasa: `POST /pagos` tiene un p95 de 1.302 ms frente a 570 ms en producción (+128 %), por encima del límite de 10 %”.
5. Devuelve código de salida `0` si pasa y distinto de `0` si falla o no se pueden procesar los datos. El pipeline debe usar ese resultado para quedar rojo.

## Paso 5. Agregar pruebas automatizadas

Incluye pruebas que comprueben, al menos:

- cálculo del promedio, `p95` y tasa de errores;
- aprobación cuando los valores están dentro de los límites;
- rechazo por degradación de latencia y por aumento de errores;
- umbral personalizado para un endpoint;
- endpoint nuevo sin línea base y endpoint con pocas muestras;
- CSV vacío, encabezados faltantes y valores inválidos;
- código de salida correcto para aprobación y rechazo.

Usa CSV pequeños creados para las pruebas. Luego ejecuta también el analizador con los archivos del reto.

## Paso 6. Conectar el analizador a GitHub Actions

1. Crea un workflow en `.github/workflows/` que se ejecute al hacer `push` o manualmente.
2. Instala/selecciona Python, ejecuta las pruebas y llama al analizador con:
   - `resultados/produccion-actual.csv` como línea base;
   - el archivo candidato como entrada;
   - el archivo de configuración.
3. Ejecuta el workflow una vez para `version-a.csv` y otra para `version-b.csv`. Puedes usar dos jobs o dos ejecuciones manuales con un parámetro de entrada.
4. Asegúrate de que un código de salida distinto de cero haga fallar el job. No ocultes el error con una opción que permita continuar.
5. Publica el reporte como resumen de la ejecución o artefacto para que los resultados se vean durante la presentación.

**Ya implementado en este repositorio:**

- [action.yml](./action.yml): la action reutilizable. Otros equipos la usan con `uses: json2389676/performance-gate@main`.
- `.github/workflows/ci.yml`: ejecuta las pruebas unitarias en cada `push`.
- `.github/workflows/performance-gate.yml`: usa la action con la versión A y con la B (un job por versión). Se ejecuta en cada `push` a `main` y también manualmente (*Actions → Run workflow*). Ambos jobs deben quedar en **rojo**, y el resumen de cada ejecución muestra la tabla por endpoint y lo que debe mejorar el equipo.

Ejemplo de uso desde el pipeline de otro equipo:

```yaml
- uses: json2389676/performance-gate@main
  with:
    baseline: resultados/produccion-actual.csv
    candidate: resultados/mi-version.csv
    config: config/performance-gate.json   # opcional
```

## Paso 7. Analizar los resultados de este reto

Con los datos incluidos, estos son algunos resultados para validar la herramienta:

| Endpoint | Producción (p95) | Versión A (p95) | Versión B (p95) |
|---|---:|---:|---:|
| Consultar saldo, cuenta ahorros | 341 ms | 342 ms | 647 ms |
| GET /clientes | 272 ms | 272 ms | 492 ms |
| GET /reportes | 820 ms | 815 ms | 2.600 ms |
| POST /pagos | 570 ms | 1.302 ms | 1.142 ms |

- **A debe fallar** con el límite de latencia sugerido: `POST /pagos` tiene un p95 aproximadamente **128 %** mayor que producción. También registra 42 respuestas fallidas de 1.493 solicitudes (aprox. **2,8 %**), frente a 6 de 1.985 (aprox. **0,3 %**) en producción.
- **B debe fallar**: el p95 empeora en saldo, clientes y pagos; `GET /reportes` empeora mucho, pero tiene solo cuatro muestras y debe señalarse como inconcluso. Además, `POST /transferencias` es nuevo y no tiene línea base.
- Con los límites propuestos, **ninguna versión reemplaza a producción automáticamente**. A tiene regresión grave en pagos; B presenta regresiones en varios endpoints. No afirmes que una versión pasa solo porque su promedio global sea menor.

Los valores de arriba sirven como comprobación inicial. El reporte generado por tu programa debe ser la fuente final, calculada a partir de los CSV y de la configuración seleccionada.

## Paso 8. Preparar el README y la demostración

En el `README.md` documenta:

1. propósito de la herramienta y requisitos;
2. cómo ejecutarla localmente;
3. parámetros de entrada y formato de configuración;
4. significado de los límites, el `p95`, las tasas de error y los resultados inconclusos;
5. cómo interpretar el código de salida y el estado del pipeline;
6. ejecuciones de A y B, con enlaces o capturas;
7. respuesta a “¿cuál versión reemplaza a producción y por qué?”: con las reglas sugeridas, **ninguna pasa**;
8. alcance actual (CSV de JMeter) y cómo se podría agregar un lector de k6.

Para la entrevista, prepara un recorrido breve: mostrar la configuración, ejecutar A y B, abrir los reportes, explicar por qué fallan y modificar un límite por endpoint para demostrar que los equipos pueden adaptarlo.

## Lista final de verificación

- [ ] El analizador acepta producción, candidato y configuración como entradas.
- [ ] Los límites globales y los específicos por endpoint funcionan.
- [ ] El reporte explica qué pasó y qué debe mejorar el equipo.
- [ ] Los errores de datos no se convierten en aprobaciones.
- [ ] Una versión que no pasa deja el pipeline en rojo.
- [ ] Las ejecuciones de A y B quedan disponibles para la presentación.
- [ ] El README responde cuál versión reemplaza a producción y por qué.
