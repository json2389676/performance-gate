"""Performance Quality Gate: compara una prueba de carga contra producción.

Códigos de salida: 0 = pasa, 1 = no pasa, 2 = error en datos o configuración.
"""
import argparse
import json
import sys

from config import cargar_config, limites_para
from jmeter import LECTORES


def num(valor, decimales=0):
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


def _hallazgo(tipo, severidad, mensaje, recomendacion):
    return {
        "tipo": tipo,
        "severidad": severidad,
        "mensaje": mensaje,
        "recomendacion": recomendacion,
    }


def _evaluar_endpoint(nombre, base, cand, limites, politicas):
    hallazgos = []

    if base is None:
        sev = politicas["onNewEndpoint"]
        hallazgos.append(_hallazgo(
            "endpoint_nuevo", sev,
            f"{nombre} no existe en producción; no hay línea base para compararlo "
            f"(p95 {num(cand['p95'])} ms, errores {num(cand['tasa_errores'], 2)} %).",
            f"Incluir {nombre} en la prueba de producción para tener una línea base, "
            "o definir límites propios para él en la configuración.",
        ))
        return hallazgos

    if cand is None:
        hallazgos.append(_hallazgo(
            "endpoint_ausente", politicas["onMissingEndpoint"],
            f"{nombre} está en producción pero no aparece en la prueba de la versión nueva.",
            "Asegurar que la prueba de carga cubra este endpoint, o confirmar que se eliminó a propósito.",
        ))
        return hallazgos

    minimo = limites["minimumSamples"]
    if base["muestras"] < minimo or cand["muestras"] < minimo:
        hallazgos.append(_hallazgo(
            "muestras_insuficientes", politicas["onInconclusive"],
            f"{nombre}: resultado inconcluso, pocas muestras (producción {base['muestras']}, "
            f"versión nueva {cand['muestras']}; mínimo {num(minimo)}). "
            f"Observado: p95 {num(base['p95'])} ms -> {num(cand['p95'])} ms.",
            f"Aumentar la cantidad de peticiones a {nombre} en la prueba de carga "
            f"(mínimo {num(minimo)}) para poder evaluarlo.",
        ))
        return hallazgos

    aumento_ms = cand["p95"] - base["p95"]
    aumento_pct = aumento_ms / base["p95"] * 100 if base["p95"] > 0 else float("inf")
    if aumento_pct > limites["p95RegressionPercent"] and aumento_ms > limites["p95RegressionMinMs"]:
        tope = base["p95"] * (1 + limites["p95RegressionPercent"] / 100)
        hallazgos.append(_hallazgo(
            "latencia", "fail",
            f"{nombre}: el p95 pasó de {num(base['p95'])} ms en producción a {num(cand['p95'])} ms "
            f"(+{num(aumento_pct, 1)} %); el límite es +{num(limites['p95RegressionPercent'], 1)} %.",
            f"Bajar el p95 de {nombre} a {num(tope)} ms o menos "
            f"(hoy {num(cand['p95'] - tope)} ms por encima).",
        ))

    aumento_err = cand["tasa_errores"] - base["tasa_errores"]
    if aumento_err > limites["errorRateIncreasePercentagePoints"]:
        tope = base["tasa_errores"] + limites["errorRateIncreasePercentagePoints"]
        hallazgos.append(_hallazgo(
            "errores", "fail",
            f"{nombre}: la tasa de errores pasó de {num(base['tasa_errores'], 2)} % en producción a "
            f"{num(cand['tasa_errores'], 2)} % (+{num(aumento_err, 2)} puntos); "
            f"el límite es +{num(limites['errorRateIncreasePercentagePoints'], 2)} puntos.",
            f"Investigar los errores de {nombre} y bajar la tasa a {num(tope, 2)} % o menos.",
        ))
    return hallazgos


def evaluar(base, cand, config):
    endpoints = []
    for nombre in sorted(set(base) | set(cand)):
        b, c = base.get(nombre), cand.get(nombre)
        limites = limites_para(config, nombre)
        hallazgos = _evaluar_endpoint(nombre, b, c, limites, config["politicas"])
        severidades = {h["severidad"] for h in hallazgos}
        estado = "fail" if "fail" in severidades else "warn" if "warn" in severidades else "pass"
        endpoints.append({
            "endpoint": nombre,
            "estado": estado,
            "produccion": b,
            "candidato": c,
            "limites": limites,
            "hallazgos": hallazgos,
        })
    estados = {e["estado"] for e in endpoints}
    return {
        "veredicto": "fail" if "fail" in estados else "pass",
        "endpoints": endpoints,
    }


ETIQUETA = {"pass": "PASA", "warn": "ADVERTENCIA", "fail": "FALLA"}
ICONO = {"pass": "✅", "warn": "⚠️", "fail": "❌"}


def _celda(metricas, clave, decimales=0, sufijo=""):
    return "-" if metricas is None else num(metricas[clave], decimales) + sufijo


def _cambio(e):
    b, c = e["produccion"], e["candidato"]
    if b is None or c is None or b["p95"] <= 0:
        return "-"
    return f"{(c['p95'] - b['p95']) / b['p95'] * 100:+.1f} %".replace(".", ",")


def texto_consola(resultado):
    lineas = []
    for e in resultado["endpoints"]:
        lineas.append(
            f"[{ETIQUETA[e['estado']]:<11}] {e['endpoint']:<34} "
            f"p95 {_celda(e['produccion'], 'p95'):>6} -> {_celda(e['candidato'], 'p95'):>6} ms "
            f"({_cambio(e)})  errores {_celda(e['produccion'], 'tasa_errores', 2, ' %')} -> "
            f"{_celda(e['candidato'], 'tasa_errores', 2, ' %')}"
        )
    lineas.append("")
    hallazgos = [(e, h) for e in resultado["endpoints"] for h in e["hallazgos"]]
    for severidad, titulo in (("fail", "Por qué no pasa"), ("warn", "Advertencias")):
        items = [h for _, h in hallazgos if h["severidad"] == severidad]
        if items:
            lineas.append(f"{titulo}:")
            lineas.extend(f"  - {h['mensaje']}" for h in items)
            lineas.append("")
    mejoras = [h["recomendacion"] for _, h in hallazgos]
    if mejoras:
        lineas.append("Qué debería mejorar el equipo:")
        lineas.extend(f"  - {m}" for m in mejoras)
        lineas.append("")
    lineas.append(
        "RESULTADO: LA VERSIÓN PASA" if resultado["veredicto"] == "pass"
        else "RESULTADO: LA VERSIÓN NO PASA"
    )
    return "\n".join(lineas)


def markdown(resultado, titulo):
    veredicto = resultado["veredicto"]
    out = [f"# {titulo}", ""]
    out.append(
        "## ✅ La versión pasa" if veredicto == "pass" else "## ❌ La versión NO pasa"
    )
    out += ["", "| Estado | Endpoint | p95 prod (ms) | p95 nueva (ms) | Cambio | Errores prod | Errores nueva | Muestras (prod / nueva) |",
            "|---|---|---:|---:|---:|---:|---:|---:|"]
    for e in resultado["endpoints"]:
        b, c = e["produccion"], e["candidato"]
        out.append(
            f"| {ICONO[e['estado']]} {ETIQUETA[e['estado']]} | `{e['endpoint']}` | "
            f"{_celda(b, 'p95')} | {_celda(c, 'p95')} | {_cambio(e)} | "
            f"{_celda(b, 'tasa_errores', 2, ' %')} | {_celda(c, 'tasa_errores', 2, ' %')} | "
            f"{_celda(b, 'muestras')} / {_celda(c, 'muestras')} |"
        )
    hallazgos = [h for e in resultado["endpoints"] for h in e["hallazgos"]]
    for severidad, encabezado in (("fail", "### Por qué no pasa"), ("warn", "### Advertencias")):
        items = [h for h in hallazgos if h["severidad"] == severidad]
        if items:
            out += ["", encabezado, ""] + [f"- {h['mensaje']}" for h in items]
    if hallazgos:
        out += ["", "### Qué debería mejorar el equipo", ""]
        out += [f"- {h['recomendacion']}" for h in hallazgos]
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Performance Quality Gate")
    parser.add_argument("--baseline", required=True, help="Resultados de producción")
    parser.add_argument("--candidate", required=True, help="Resultados de la versión nueva")
    parser.add_argument("--config", help="Archivo JSON con los límites (opcional)")
    parser.add_argument("--format", default="jmeter", choices=sorted(LECTORES),
                        help="Formato de los resultados (por defecto: jmeter)")
    parser.add_argument("--title", default="Performance Quality Gate")
    parser.add_argument("--report-md", help="Ruta donde escribir el reporte en Markdown")
    parser.add_argument("--report-json", help="Ruta donde escribir el resultado en JSON")
    args = parser.parse_args(argv)

    try:
        config = cargar_config(args.config)
        leer = LECTORES[args.format]
        base = leer(args.baseline)
        cand = leer(args.candidate)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    resultado = evaluar(base, cand, config)
    print(texto_consola(resultado))

    if args.report_md:
        with open(args.report_md, "w", encoding="utf-8") as f:
            f.write(markdown(resultado, args.title))
    if args.report_json:
        with open(args.report_json, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)

    return 0 if resultado["veredicto"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
