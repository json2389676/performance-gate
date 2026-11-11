"""Lectura y validación de la configuración de límites."""
import json

UMBRALES = {
    "p95RegressionPercent": 10,
    "p95RegressionMinMs": 20,
    "errorRateIncreasePercentagePoints": 0.5,
    "minimumSamples": 100,
}
POLITICAS = {
    "onNewEndpoint": "warn",
    "onMissingEndpoint": "fail",
    "onInconclusive": "warn",
}
ACCIONES = {"fail", "warn"}


def _validar_umbrales(valores, donde):
    for clave, valor in valores.items():
        if clave not in UMBRALES:
            raise ValueError(f"Configuración: clave desconocida {clave!r} en {donde}")
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or valor < 0:
            raise ValueError(
                f"Configuración: {clave!r} en {donde} debe ser un número >= 0, recibió {valor!r}"
            )


def cargar_config(ruta=None):
    """Devuelve {"defaults": {...}, "endpoints": {...}, "politicas": {...}}."""
    crudo = {}
    if ruta:
        with open(ruta, encoding="utf-8") as archivo:
            try:
                crudo = json.load(archivo)
            except json.JSONDecodeError as error:
                raise ValueError(f"Configuración: JSON inválido en {ruta}: {error}")
        if not isinstance(crudo, dict):
            raise ValueError("Configuración: el archivo debe contener un objeto JSON")

    permitidas = {"defaults", "endpoints", *POLITICAS}
    desconocidas = set(crudo) - permitidas
    if desconocidas:
        raise ValueError(f"Configuración: claves desconocidas {sorted(desconocidas)}")

    defaults = crudo.get("defaults", {})
    _validar_umbrales(defaults, "defaults")

    endpoints = crudo.get("endpoints", {})
    if not isinstance(endpoints, dict):
        raise ValueError("Configuración: 'endpoints' debe ser un objeto")
    for nombre, valores in endpoints.items():
        if not isinstance(valores, dict):
            raise ValueError(f"Configuración: el endpoint {nombre!r} debe ser un objeto")
        _validar_umbrales(valores, f"endpoints[{nombre!r}]")

    politicas = {}
    for clave, por_defecto in POLITICAS.items():
        valor = crudo.get(clave, por_defecto)
        if valor not in ACCIONES:
            raise ValueError(f"Configuración: {clave!r} debe ser 'fail' o 'warn', recibió {valor!r}")
        politicas[clave] = valor

    return {
        "defaults": {**UMBRALES, **defaults},
        "endpoints": endpoints,
        "politicas": politicas,
    }


def limites_para(config, endpoint):
    return {**config["defaults"], **config["endpoints"].get(endpoint, {})}
