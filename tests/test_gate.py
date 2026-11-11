import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "src"))

import gate  # noqa: E402
from config import cargar_config  # noqa: E402
from jmeter import leer_jmeter, percentil  # noqa: E402

ENCABEZADO = "timeStamp,elapsed,label,responseCode,responseMessage,threadName,success,bytes,Latency,allThreads\n"


def fila(label, elapsed, ok=True):
    etiqueta = f'"{label}"' if "," in label else label
    return f"1,{elapsed},{etiqueta},{200 if ok else 500},OK,Usuarios 1-1,{'true' if ok else 'false'},1,1,50\n"


class BaseConArchivos(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def csv(self, nombre, contenido):
        ruta = os.path.join(self.dir.name, nombre)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(contenido)
        return ruta

    def csv_endpoint(self, nombre, label, tiempos, errores=0):
        filas = [fila(label, t, ok=i >= errores) for i, t in enumerate(tiempos)]
        return self.csv(nombre, ENCABEZADO + "".join(filas))

    def config(self, datos):
        return cargar_config(self.csv("config.json", json.dumps(datos)))


class PruebasPercentil(unittest.TestCase):
    def test_p95_rango_mas_cercano(self):
        self.assertEqual(percentil(list(range(1, 101)), 95), 95)

    def test_un_solo_valor(self):
        self.assertEqual(percentil([7], 95), 7)

    def test_no_depende_del_orden(self):
        self.assertEqual(percentil([5, 1, 3], 50), 3)


class PruebasLectorJMeter(BaseConArchivos):
    def test_metricas_por_endpoint(self):
        ruta = self.csv_endpoint("a.csv", "GET /x", [100] * 18 + [500, 900], errores=2)
        m = leer_jmeter(ruta)["GET /x"]
        self.assertEqual(m["muestras"], 20)
        self.assertAlmostEqual(m["promedio"], 160)
        self.assertEqual(m["p95"], 500)
        self.assertAlmostEqual(m["tasa_errores"], 10)

    def test_label_con_coma_entre_comillas(self):
        ruta = self.csv_endpoint("a.csv", "Consultar saldo, cuenta ahorros", [10, 20])
        self.assertIn("Consultar saldo, cuenta ahorros", leer_jmeter(ruta))

    def test_columnas_en_otro_orden(self):
        ruta = self.csv("a.csv", "success,label,elapsed\ntrue,GET /x,120\nFALSE,GET /x,80\n")
        m = leer_jmeter(ruta)["GET /x"]
        self.assertEqual(m["muestras"], 2)
        self.assertAlmostEqual(m["tasa_errores"], 50)

    def test_archivo_vacio(self):
        with self.assertRaises(ValueError):
            leer_jmeter(self.csv("a.csv", ENCABEZADO))

    def test_faltan_columnas(self):
        with self.assertRaises(ValueError):
            leer_jmeter(self.csv("a.csv", "label,elapsed\nGET /x,10\n"))

    def test_elapsed_invalido(self):
        with self.assertRaises(ValueError):
            leer_jmeter(self.csv("a.csv", ENCABEZADO + fila("GET /x", "abc")))

    def test_elapsed_negativo(self):
        with self.assertRaises(ValueError):
            leer_jmeter(self.csv("a.csv", ENCABEZADO + fila("GET /x", -5)))

    def test_endpoint_vacio(self):
        with self.assertRaises(ValueError):
            leer_jmeter(self.csv("a.csv", ENCABEZADO + fila("", 10)))


class PruebasConfig(BaseConArchivos):
    def test_defaults_sin_archivo(self):
        c = cargar_config()
        self.assertEqual(c["defaults"]["p95RegressionPercent"], 10)
        self.assertEqual(c["politicas"]["onNewEndpoint"], "warn")

    def test_override_por_endpoint(self):
        c = self.config({"endpoints": {"POST /pagos": {"p95RegressionPercent": 3}}})
        self.assertEqual(gate.limites_para(c, "POST /pagos")["p95RegressionPercent"], 3)
        self.assertEqual(gate.limites_para(c, "GET /x")["p95RegressionPercent"], 10)

    def test_clave_desconocida(self):
        with self.assertRaises(ValueError):
            self.config({"defaults": {"p95RegressionPrecent": 5}})

    def test_valor_negativo_o_no_numerico(self):
        for valor in (-1, "10", True):
            with self.assertRaises(ValueError):
                self.config({"defaults": {"p95RegressionPercent": valor}})

    def test_politica_invalida(self):
        with self.assertRaises(ValueError):
            self.config({"onNewEndpoint": "ignorar"})

    def test_json_invalido(self):
        with self.assertRaises(ValueError):
            cargar_config(self.csv("mala.json", "{no es json"))


def metricas(p95, muestras=1000, errores=0.0):
    return {"muestras": muestras, "promedio": p95 / 2, "p95": p95, "tasa_errores": errores}


class PruebasEvaluar(unittest.TestCase):
    def setUp(self):
        self.config = cargar_config()

    def evaluar(self, base, cand, config=None):
        return gate.evaluar(base, cand, config or self.config)

    def test_dentro_de_limites_pasa(self):
        r = self.evaluar({"GET /x": metricas(200)}, {"GET /x": metricas(215, errores=0.3)})
        self.assertEqual(r["veredicto"], "pass")

    def test_degradacion_de_latencia_falla(self):
        r = self.evaluar({"POST /pagos": metricas(500)}, {"POST /pagos": metricas(1000)})
        self.assertEqual(r["veredicto"], "fail")
        h = r["endpoints"][0]["hallazgos"][0]
        self.assertEqual(h["tipo"], "latencia")
        self.assertIn("POST /pagos", h["mensaje"])
        self.assertIn("+100,0 %", h["mensaje"])

    def test_mejora_de_latencia_pasa(self):
        r = self.evaluar({"GET /x": metricas(500)}, {"GET /x": metricas(200)})
        self.assertEqual(r["veredicto"], "pass")

    def test_aumento_de_errores_falla(self):
        r = self.evaluar({"GET /x": metricas(200, errores=0.2)}, {"GET /x": metricas(200, errores=3.0)})
        self.assertEqual(r["veredicto"], "fail")
        self.assertEqual(r["endpoints"][0]["hallazgos"][0]["tipo"], "errores")

    def test_limite_por_endpoint(self):
        base, cand = {"A": metricas(500), "B": metricas(500)}, {"A": metricas(540), "B": metricas(540)}
        self.assertEqual(self.evaluar(base, cand)["veredicto"], "pass")
        estricto = cargar_config_dict({"endpoints": {"A": {"p95RegressionPercent": 5}}})
        r = self.evaluar(base, cand, estricto)
        estados = {e["endpoint"]: e["estado"] for e in r["endpoints"]}
        self.assertEqual(estados, {"A": "fail", "B": "pass"})

    def test_aumento_pequeno_en_ms_no_falla(self):
        r = self.evaluar({"GET /x": metricas(10)}, {"GET /x": metricas(15)})
        self.assertEqual(r["veredicto"], "pass")

    def test_endpoint_nuevo_advierte_por_defecto(self):
        r = self.evaluar({}, {"GET /nuevo": metricas(300)})
        self.assertEqual(r["veredicto"], "pass")
        self.assertEqual(r["endpoints"][0]["estado"], "warn")

    def test_endpoint_nuevo_puede_fallar(self):
        cfg = cargar_config_dict({"onNewEndpoint": "fail"})
        self.assertEqual(self.evaluar({}, {"GET /nuevo": metricas(300)}, cfg)["veredicto"], "fail")

    def test_endpoint_ausente_falla_por_defecto(self):
        r = self.evaluar({"GET /x": metricas(200)}, {})
        self.assertEqual(r["veredicto"], "fail")
        self.assertEqual(r["endpoints"][0]["hallazgos"][0]["tipo"], "endpoint_ausente")

    def test_pocas_muestras_es_inconcluso(self):
        r = self.evaluar({"GET /x": metricas(200, muestras=4)}, {"GET /x": metricas(2000, muestras=4)})
        self.assertEqual(r["veredicto"], "pass")
        self.assertEqual(r["endpoints"][0]["hallazgos"][0]["tipo"], "muestras_insuficientes")

    def test_pocas_muestras_puede_fallar(self):
        cfg = cargar_config_dict({"onInconclusive": "fail"})
        r = self.evaluar({"GET /x": metricas(200, muestras=4)}, {"GET /x": metricas(200, muestras=4)}, cfg)
        self.assertEqual(r["veredicto"], "fail")

    def test_minimo_de_muestras_configurable(self):
        cfg = cargar_config_dict({"defaults": {"minimumSamples": 1}})
        r = self.evaluar({"GET /x": metricas(200, muestras=4)}, {"GET /x": metricas(2000, muestras=4)}, cfg)
        self.assertEqual(r["veredicto"], "fail")

    def test_reportes_se_generan(self):
        r = self.evaluar({"POST /pagos": metricas(500)}, {"POST /pagos": metricas(1000)})
        self.assertIn("RESULTADO: LA VERSIÓN NO PASA", gate.texto_consola(r))
        self.assertIn("La versión NO pasa", gate.markdown(r, "Titulo"))


def cargar_config_dict(datos):
    with tempfile.TemporaryDirectory() as d:
        ruta = os.path.join(d, "c.json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(datos, f)
        return cargar_config(ruta)


class PruebasCLI(BaseConArchivos):
    def ejecutar(self, *args):
        salida, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(error):
            codigo = gate.main(list(args))
        return codigo, salida.getvalue(), error.getvalue()

    def test_codigo_0_si_pasa(self):
        base = self.csv_endpoint("b.csv", "GET /x", [100] * 200)
        cand = self.csv_endpoint("c.csv", "GET /x", [100] * 200)
        self.assertEqual(self.ejecutar("--baseline", base, "--candidate", cand)[0], 0)

    def test_codigo_1_si_no_pasa(self):
        base = self.csv_endpoint("b.csv", "GET /x", [100] * 200)
        cand = self.csv_endpoint("c.csv", "GET /x", [300] * 200)
        codigo, salida, _ = self.ejecutar("--baseline", base, "--candidate", cand)
        self.assertEqual(codigo, 1)
        self.assertIn("GET /x", salida)

    def test_codigo_2_si_hay_error_de_datos(self):
        base = self.csv_endpoint("b.csv", "GET /x", [100] * 200)
        codigo, _, error = self.ejecutar("--baseline", base, "--candidate", "no-existe.csv")
        self.assertEqual(codigo, 2)
        self.assertIn("ERROR", error)

    def test_codigo_2_si_la_config_es_invalida(self):
        base = self.csv_endpoint("b.csv", "GET /x", [100] * 200)
        mala = self.csv("m.json", '{"defaults": {"minimumSamples": -1}}')
        self.assertEqual(self.ejecutar("--baseline", base, "--candidate", base, "--config", mala)[0], 2)

    def test_escribe_reportes(self):
        base = self.csv_endpoint("b.csv", "GET /x", [100] * 200)
        md, js = os.path.join(self.dir.name, "r.md"), os.path.join(self.dir.name, "r.json")
        self.ejecutar("--baseline", base, "--candidate", base, "--report-md", md, "--report-json", js)
        with open(js, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["veredicto"], "pass")
        self.assertTrue(os.path.getsize(md) > 0)


class PruebasConDatosDelReto(unittest.TestCase):
    def ejecutar(self, version):
        res = os.path.join(RAIZ, "resultados")
        with contextlib.redirect_stdout(io.StringIO()):
            return gate.main([
                "--baseline", os.path.join(res, "produccion-actual.csv"),
                "--candidate", os.path.join(res, f"{version}.csv"),
                "--config", os.path.join(RAIZ, "config", "performance-gate.json"),
            ])

    def test_version_a_no_pasa(self):
        self.assertEqual(self.ejecutar("version-a"), 1)

    def test_version_b_no_pasa(self):
        self.assertEqual(self.ejecutar("version-b"), 1)

    def test_produccion_contra_si_misma_pasa(self):
        self.assertEqual(self.ejecutar("produccion-actual"), 0)


if __name__ == "__main__":
    unittest.main()
