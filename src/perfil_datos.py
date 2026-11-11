"""Paso 1: lee un CSV de JMeter y calcula métricas por endpoint.

Uso: python3 src/perfil_datos.py resultados/version-a.csv
"""
import csv
import math
import sys
from collections import defaultdict

COLUMNAS_REQUERIDAS = {"label", "elapsed", "success"}


def percentil(valores, p):
    # Método del "rango más cercano": el valor en la posición ceil(p/100 * n).
    ordenados = sorted(valores)
    posicion = math.ceil(p / 100 * len(ordenados))
    return ordenados[max(posicion, 1) - 1]


def leer_csv(ruta):
    """Devuelve {endpoint: {"tiempos": [...], "errores": n}}."""
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
            except ValueError:
                raise ValueError(
                    f"{ruta}, línea {numero}: elapsed inválido: {fila['elapsed']!r}"
                )
            datos = endpoints[etiqueta]
            datos["tiempos"].append(elapsed)
            if fila["success"].strip().lower() != "true":
                datos["errores"] += 1

    if not endpoints:
        raise ValueError(f"{ruta} no tiene filas de datos")
    return endpoints


def calcular_metricas(endpoints):
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


def imprimir(metricas):
    print(f"{'Endpoint':<36}{'Muestras':>9}{'Prom ms':>9}{'p95 ms':>8}{'Err %':>7}")
    for etiqueta, m in sorted(metricas.items()):
        print(
            f"{etiqueta:<36}{m['muestras']:>9}{m['promedio']:>9.1f}"
            f"{m['p95']:>8.0f}{m['tasa_errores']:>7.2f}"
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: python3 src/perfil_datos.py <archivo.csv>")
    try:
        imprimir(calcular_metricas(leer_csv(sys.argv[1])))
    except (OSError, ValueError) as error:
        sys.exit(f"Error: {error}")
