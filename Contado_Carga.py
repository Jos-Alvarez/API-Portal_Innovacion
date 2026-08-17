import pandas as pd
from datetime import datetime
import os
import glob

# Mapeo de plazas a cuentas contables (por texto completo)
MAPEO_PLAZAS = {
    "PROSEGUR - P1 - Monterrico Entrada": 1101017004,
    "PROSEGUR - P2 - Monterrico Salida": 1101017004,
    "PROSEGUR - P3 - Separadora Entrada": 1101017004,
    "PROSEGUR - P4 - Santa Anita": 1101017004,
    "PROSEGUR - P5 - El Pino": 1101017094,
    "PROSEGUR - P6 - Prialé Entrada": 1101017094,
    "PROSEGUR - P7 - Prialé Salida": 1101017094,
    "PROSEGUR - P8 - Huanuco": 1101017104,
    "PROSEGUR - P9 - Puente Ejercito": 1101017104,
    "PROSEGUR - P10 - Estadio": 1101017104
}


def buscar_archivo_contado(carpeta_entrada):
    """Busca el archivo que contenga 'Contado' en su nombre."""
    if not os.path.exists(carpeta_entrada):
        print(f"❌ La carpeta no existe: {carpeta_entrada}")
        return None

    # Mostrar todos los archivos en la carpeta
    todos_archivos = os.listdir(carpeta_entrada)
    archivos_excel = [f for f in todos_archivos if f.endswith(('.xlsx', '.xls'))]
    print(f"📂 Archivos Excel encontrados en la carpeta ({len(archivos_excel)}):")
    for archivo in archivos_excel:
        print(f"   - {archivo}")

    # Buscar archivos que contengan "Contado"
    patron_xlsx = os.path.join(carpeta_entrada, "*Contado*.xlsx")
    patron_xls = os.path.join(carpeta_entrada, "*Contado*.xls")

    encontrados = glob.glob(patron_xlsx) + glob.glob(patron_xls)

    if encontrados:
        print(f"✓ Archivo Contado encontrado: {os.path.basename(encontrados[0])}")
        return encontrados[0]
    else:
        print(f"✗ No se encontró archivo con 'Contado' en el nombre")
        return None


def extraer_plaza(texto):
    """Busca el texto completo de la plaza en el mapeo."""
    if pd.isna(texto):
        return None

    texto_str = str(texto).strip()

    # Buscar coincidencia exacta en el mapeo
    if texto_str in MAPEO_PLAZAS:
        return texto_str

    return None


def limpiar_montos(serie):
    """Limpia y convierte montos a float."""
    return pd.to_numeric(
        serie.astype(str).str.replace(",", "").str.strip().replace(["", "-"], "0"),
        errors='coerce'
    ).fillna(0)


def crear_linea_base(tipo, año=None, fecha_documento="", fecha_entrada="", mes="",
                     referencia="", texto=""):
    """Crea una línea base con estructura común."""
    linea = [""] * 26
    linea[0] = tipo
    if tipo == 1:  # Línea tipo 1
        linea[1] = "1"
        linea[2] = ""
        linea[3] = "VPR1"
        linea[4] = ""
        linea[5] = año or datetime.now().year
        linea[6] = "DZ"
        linea[7] = fecha_documento
        linea[8] = fecha_entrada
        linea[9] = mes
        linea[10] = referencia
        linea[11] = texto
        linea[12] = "PEN"
    return linea


def procesar_contado(df, nombre_archivo):
    """Procesa el archivo Contado y genera las filas de salida."""

    # Hacer una copia completa del dataframe para evitar warnings
    df = df.copy()

    # Filtrar solo las filas que tienen valor en la columna B (índice 1)
    df_filtrado = df[df.iloc[:, 1].notna() & (df.iloc[:, 1] != "")].copy()

    total_registros = len(df_filtrado)
    print(f"📊 Total de registros con datos en columna B: {total_registros}")

    if df_filtrado.empty:
        print("⚠️ No hay registros con datos en la columna B")
        return []

    filas = []
    registros_procesados = 0
    registros_sin_plaza = 0

    # Limpiar montos
    df_filtrado['importe_limpio'] = limpiar_montos(df_filtrado.iloc[:, 8])  # Columna I "Importe en moneda doc"

    for idx, fila in df_filtrado.iterrows():
        try:
            # Extraer datos de las columnas
            fecha_contabilizacion = pd.to_datetime(fila.iloc[1], dayfirst=True, errors='coerce')  # Columna B "Fe.contabilización"
            fecha_documento = pd.to_datetime(fila.iloc[2], dayfirst=True, errors='coerce')  # Columna C
            fecha_entrada = pd.to_datetime(fila.iloc[14], dayfirst=True, errors='coerce')  # Columna O

            # Obtener referencia y convertir a string limpio
            ref_valor = fila.iloc[4]
            if pd.notna(ref_valor):
                # Si es número, convertir a int primero para quitar decimales
                if isinstance(ref_valor, (int, float)):
                    referencia = str(int(ref_valor))
                else:
                    referencia = str(ref_valor)
            else:
                referencia = ""

            texto = str(fila.iloc[13]) if pd.notna(fila.iloc[13]) else ""  # Columna N "Texto"
            importe = fila['importe_limpio']

            # Validar fechas - omitir sin mostrar advertencia
            if pd.isna(fecha_contabilizacion) or pd.isna(fecha_documento) or pd.isna(fecha_entrada):
                continue

            # Extraer plaza del texto
            plaza = extraer_plaza(texto)

            if plaza is None:
                registros_sin_plaza += 1
                continue

            # Obtener cuenta contable según la plaza
            cuenta_contable = MAPEO_PLAZAS.get(plaza)

            if cuenta_contable is None:
                continue

            # Formatear fechas
            fecha_contab_str = fecha_contabilizacion.strftime("%Y%m%d")  # Columna 8 de fila 1
            mes_contab_str = fecha_contabilizacion.strftime("%m")  # Columna 9 de fila 1
            fecha_doc_str = fecha_documento.strftime("%Y%m%d")
            fecha_ent_str = fecha_entrada.strftime("%Y%m%d")
            mes_str = fecha_entrada.strftime("%m")
            año = fecha_contabilizacion.year  # CAMBIO: Ahora extrae el año de Fe.contabilización (columna B)

            # Crear las tres filas para este registro
            # Primera fila (sin columna 2, todo corre una posición)
            linea1 = [""] * 26
            linea1[0] = 1
            linea1[1] = ""
            linea1[2] = "VPR1"
            linea1[3] = ""
            linea1[4] = año
            linea1[5] = "DZ"
            linea1[6] = fecha_doc_str
            linea1[7] = fecha_contab_str
            linea1[8] = mes_contab_str
            linea1[9] = referencia
            linea1[10] = texto
            linea1[11] = "PEN"

            # Segunda fila (incluye importe con 2 decimales)
            linea2 = [""] * 26
            linea2[0] = 2
            linea2[12] = 15
            linea2[13] = 1001530
            linea2[17] = round(abs(importe), 2)
            linea2[25] = texto

            # Tercera fila (varía según la plaza, con 2 decimales)
            linea3 = [""] * 26
            linea3[0] = 2
            linea3[12] = 40
            linea3[13] = cuenta_contable
            linea3[17] = round(abs(importe), 2)
            linea3[25] = texto

            filas.extend([linea1, linea2, linea3, [""] * 26])  # Línea en blanco separadora
            registros_procesados += 1

        except Exception as e:
            print(f"❌ Error procesando fila {idx + 2}: {e}")
            continue

    print(f"✓ Procesados {registros_procesados} registros correctamente")
    if registros_sin_plaza > 0:
        print(f"⚠️ {registros_sin_plaza} registros sin plaza identificable en el mapeo")

    return filas


def procesar_archivo_contado(archivo_entrada, archivo_salida):
    """Procesa el archivo Contado y genera el resultado."""
    try:
        print(f"\n{'=' * 50}")
        print(f"PROCESANDO ARCHIVO CONTADO")
        print(f"{'=' * 50}")

        # Leer el archivo Excel
        df = pd.read_excel(archivo_entrada)

        # Procesar los datos
        filas_resultado = procesar_contado(df, "Contado")

        if not filas_resultado:
            print("⚠️ No se generaron registros de salida")
            return

        # Crear carpeta de salida si no existe
        os.makedirs(os.path.dirname(archivo_salida), exist_ok=True)

        # Guardar archivo Excel con la hoja "Contado Lima Expresa"
        df_resultado = pd.DataFrame(filas_resultado)

        with pd.ExcelWriter(archivo_salida, engine='openpyxl') as writer:
            df_resultado.to_excel(writer, index=False, header=False, sheet_name="Contado Lima Expresa")

        print(f"\n🎉 COMPLETADO: {archivo_salida}")
        print(f"📄 Hoja creada: Contado Lima Expresa")

        # Generar archivo TXT con el mismo contenido
        archivo_txt = archivo_salida.replace('.xlsx', '.txt')

        with open(archivo_txt, 'w', encoding='utf-8') as f:
            for fila in filas_resultado:
                # Convertir cada celda a string, evitando .0 en números que son texto
                linea_procesada = []
                for celda in fila:
                    if celda == "":
                        linea_procesada.append("")
                    elif isinstance(celda, float):
                        # Si es float y termina en .0, quitarlo si parece un ID
                        if celda == int(celda) and celda > 1000000000:  # IDs grandes
                            linea_procesada.append(str(int(celda)))
                        else:
                            linea_procesada.append(str(celda))
                    else:
                        linea_procesada.append(str(celda))

                linea_txt = '\t'.join(linea_procesada)
                f.write(linea_txt + '\n')

        print(f"📄 Archivo TXT creado: {archivo_txt}")

    except Exception as e:
        print(f"❌ Error procesando archivo: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Función principal."""
    carpeta_entrada = r'C:\Automatizacion\Contado\Entrada'
    carpeta_salida = r'C:\Automatizacion\Contado\Salida'

    print("🚀 INICIANDO PROCESAMIENTO DE ARCHIVO CONTADO")
    print(f"📁 Entrada: {carpeta_entrada}")
    print(f"📁 Salida: {carpeta_salida}")

    # Buscar archivo Contado
    archivo_entrada = buscar_archivo_contado(carpeta_entrada)

    if archivo_entrada and os.path.exists(archivo_entrada):
        archivo_salida = os.path.join(carpeta_salida, 'resultado_contado_procesado.xlsx')
        procesar_archivo_contado(archivo_entrada, archivo_salida)
    else:
        print("⚠️ No se encontró archivo Contado para procesar")

    input("\n✅ Proceso finalizado. Presiona Enter para cerrar la ventana...")


if __name__ == "__main__":
    main()