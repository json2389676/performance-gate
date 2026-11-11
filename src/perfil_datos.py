"""Perfila un CSV de JMeter: muestras, promedio, p95 y errores por endpoint.

Uso: python3 src/perfil_datos.py resultados/version-a.csv
"""
import sys

from jmeter import leer_jmeter


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
        imprimir(leer_jmeter(sys.argv[1]))
    except (OSError, ValueError) as error:
        sys.exit(f"Error: {error}")
