"""Lector de resultados de JMeter (CSV) y cálculo de métricas por endpoint.

Cualquier lector nuevo (por ejemplo k6) solo debe devolver el mismo diccionario:
{endpoint: {"muestras": int, "promedio": float, "p95": float, "tasa_errores": float}}
"""
import csv
import math
from collections import defaultdict

COLUMNAS_REQUERIDAS = {"label", "elapsed", "success"}


def percentil(valores, p):
    # Método del "rango más cercano": el valor en la posición ceil(p/100 * n).
    ordenados = sorted(valores)
    posicion = math.ceil(p / 100 * len(ordenados))
    return ordenados[max(posicion, 1) - 1]


def leer_jmeter(ruta, warmup_segundos=0):
    """Lee el CSV. Ignora las peticiones de los primeros `warmup_segundos` de la prueba,
    medidos desde la primera petición del archivo (las filas no vienen ordenadas)."""
    requeridas = COLUMNAS_REQUERIDAS | ({"timeStamp"} if warmup_segundos > 0 else set())
    filas = []
    with open(ruta, newline="", encoding="utf-8-sig") as archivo:
        lector = csv.DictReader(archivo)
        faltantes = requeridas - set(lector.fieldnames or [])
        if faltantes:
            raise ValueError(f"Faltan columnas en {ruta}: {sorted(faltantes)}")

        for numero, fila in enumerate(lector, start=2):
            etiqueta = (fila["label"] or "").strip()
            if not etiqueta:
                raise ValueError(f"{ruta}, línea {numero}: endpoint vacío")
            try:
                elapsed = float(fila["elapsed"])
            except (TypeError, ValueError):
                raise ValueError(
                    f"{ruta}, línea {numero}: elapsed inválido: {fila['elapsed']!r}"
                )
            if elapsed < 0 or math.isnan(elapsed) or math.isinf(elapsed):
                raise ValueError(f"{ruta}, línea {numero}: elapsed fuera de rango: {elapsed}")
            inicio = 0.0
            if warmup_segundos > 0:
                try:
                    inicio = float(fila["timeStamp"])
                except (TypeError, ValueError):
                    raise ValueError(
                        f"{ruta}, línea {numero}: timeStamp inválido: {fila['timeStamp']!r}"
                    )
            exito = (fila["success"] or "").strip().lower() == "true"
            filas.append((etiqueta, elapsed, exito, inicio))

    if not filas:
        raise ValueError(f"{ruta} no tiene filas de datos")

    if warmup_segundos > 0:
        t0 = min(f[3] for f in filas)
        filas = [f for f in filas if f[3] - t0 >= warmup_segundos * 1000]
        if not filas:
            raise ValueError(
                f"{ruta}: no quedan peticiones después de ignorar los primeros {warmup_segundos} s"
            )

    endpoints = defaultdict(lambda: {"tiempos": [], "errores": 0})
    for etiqueta, elapsed, exito, _ in filas:
        endpoints[etiqueta]["tiempos"].append(elapsed)
        if not exito:
            endpoints[etiqueta]["errores"] += 1

    metricas = {}
    for etiqueta, datos in endpoints.items():
        tiempos = datos["tiempos"]
        total = len(tiempos)
        metricas[etiqueta] = {
            "muestras": total,
            "promedio": sum(tiempos) / total,
            "p95": percentil(tiempos, 95),
            "tasa_errores": datos["errores"] / total * 100,
        }
    return metricas


LECTORES = {"jmeter": leer_jmeter}
