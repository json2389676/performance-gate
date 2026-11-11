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


def leer_jmeter(ruta):
    endpoints = defaultdict(lambda: {"tiempos": [], "errores": 0})
    with open(ruta, newline="", encoding="utf-8-sig") as archivo:
        lector = csv.DictReader(archivo)
        faltantes = COLUMNAS_REQUERIDAS - set(lector.fieldnames or [])
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
            datos = endpoints[etiqueta]
            datos["tiempos"].append(elapsed)
            if (fila["success"] or "").strip().lower() != "true":
                datos["errores"] += 1

    if not endpoints:
        raise ValueError(f"{ruta} no tiene filas de datos")

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
