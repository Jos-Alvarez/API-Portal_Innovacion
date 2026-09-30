import pandas as pd
from datetime import datetime
import os
import glob

# Configuraciones centralizadas
CONFIGURACIONES = {
    'AMEX': {
        'COMISION': {'linea2_campo14': 1106012033, 'linea3_campo13': 50, 'linea3_campo14': 1101020065},
        'COMPENSACION': {'linea2_campo14': 1101020064, 'linea3_campo13': 11, 'linea3_campo14': 1001420},
        'AJUSTE': {'campo14': 1001420}
    },
    'DINNERS': {
        'COMISION': {'linea2_campo14': 1106012034, 'linea3_campo13': 50, 'linea3_campo14': 1101020065},
        'COMPENSACION': {'linea2_campo14': 1101020064, 'linea3_campo13': 11, 'linea3_campo14': 1001418},
        'AJUSTE': {'campo14': 1001418}
    },
    'MASTERCARD': {
        'COMISION': {'linea2_campo14': 1106012032, 'linea3_campo13': 50, 'linea3_campo14': 1101020065},
        'COMPENSACION': {'linea2_campo14': 1101020064, 'linea3_campo13': 11, 'linea3_campo14': 1001417},
        'AJUSTE': {'campo14': 1001417}
    },
    'SAFETYPAY': {
        'COMISION': {'linea2_campo14': 1106012031, 'linea3_campo13': 50, 'linea3_campo14': 1101020065},
        'COMPENSACION': {'linea2_campo14': 1101020064, 'linea3_campo13': 11, 'linea3_campo14': 1001419},
        'AJUSTE': {'campo14': 1001419}
    },
    'VISA': {
        'COMISION': {'linea2_campo14': 1106012030, 'linea3_campo13': 50, 'linea3_campo14': 1101020065},
        'COMPENSACION': {'linea2_campo14': 1101020064, 'linea3_campo13': 11, 'linea3_campo14': 1001416},
        'AJUSTE': {'campo14': 1001416}
    },
    'EFECTIVO': {
        'COMPENSACION': {'linea2_campo14': 1101020064, 'linea3_campo13': 11, 'linea3_campo14': 1001415},
        'AJUSTE': {'campo14': 1001415}
    }
}

CODIGO_CATEGORIAS_IZIPAY = {
    "MC/VISA": 1106012032,
    "Diners": 1106012034,
    "Amex": 1106012033
}

CODIGO_COMPENSACION_IZIPAY = {
    "VISA": 1001416,
    "DINERS": 1001418,
    "AMEX": 1001420,
    "MASTERCARD+IZIPAY": 1001417  # Caso especial: agrupa MASTERCARD e IZIPAY
}


def buscar_archivos(carpeta_entrada):
    """Busca archivos Excel por tipo de tarjeta."""
    # Verificar que la carpeta existe
    if not os.path.exists(carpeta_entrada):
        print(f"❌ La carpeta no existe: {carpeta_entrada}")
        return {}

    # Mostrar todos los archivos en la carpeta para debug
    todos_archivos = os.listdir(carpeta_entrada)
    archivos_excel = [f for f in todos_archivos if f.endswith(('.xlsx', '.xls'))]
    print(f"📂 Archivos Excel encontrados en la carpeta ({len(archivos_excel)}):")
    for archivo in archivos_excel:
        print(f"   - {archivo}")

    tipos = ['AMEX', 'DINNERS', 'MASTERCARD', 'SAFETYPAY', 'VISA', 'IZIPAY', 'EFECTIVO']
    archivos = {}

    for tipo in tipos:
        # Buscar archivos .xlsx y .xls
        patron_xlsx = os.path.join(carpeta_entrada, f"*{tipo}*.xlsx")
        patron_xls = os.path.join(carpeta_entrada, f"*{tipo}*.xls")

        encontrados = glob.glob(patron_xlsx) + glob.glob(patron_xls)

        if encontrados:
            archivos[tipo] = encontrados[0]
            print(f"✓ Archivo {tipo}: {os.path.basename(encontrados[0])}")
        else:
            print(f"✗ No encontrado: {tipo}")

    return archivos


def limpiar_montos(serie):
    """Limpia y convierte montos a float."""
    return pd.to_numeric(
        serie.astype(str).str.replace(",", "").str.strip().replace(["", "-"], "0"),
        errors='coerce'
    ).fillna(0)


def crear_linea_base(tipo, pex="PEXP", año=None, codigo="AB", fecha="", fecha2="", mes="",
                     descripcion="", archivo="", moneda="PEN"):
    """Crea una línea base con estructura común."""
    linea = [""] * 26
    linea[0] = tipo
    if tipo == 1:  # Línea tipo 1
        linea[2] = pex
        linea[4] = año or datetime.now().year
        linea[5] = codigo
        linea[6] = fecha
        linea[7] = fecha2
        linea[8] = mes
        linea[9] = descripcion
        linea[10] = archivo
        linea[11] = moneda
    return linea


def crear_linea_detalle(campo13, campo14, monto, archivo):
    """Crea una línea de detalle (tipo 2)."""
    linea = [""] * 26
    linea[0] = 2
    linea[12] = campo13
    linea[13] = campo14
    linea[17] = monto
    linea[25] = archivo
    return linea


def procesar_por_fecha(df, col_fecha, col_monto, filtro_func=None):
    """Procesa datos agrupados por fecha."""
    if filtro_func:
        df = df[filtro_func(df)]

    if df.empty:
        return pd.DataFrame()

    df['fecha_limpia'] = pd.to_datetime(df[col_fecha], dayfirst=True, errors='coerce')
    df['monto_limpio'] = limpiar_montos(df[col_monto])

    return df.groupby('fecha_limpia')['monto_limpio'].sum().reset_index()


def procesar_hoja_comision(df, nombre_archivo, tipo_archivo):
    """Procesa comisiones y extornos."""
    print(f"\n=== PROCESANDO {tipo_archivo} - COMISIÓN ===")

    if len(df.columns) < 5:
        print("⚠️ Columnas insuficientes")
        return []

    # Filtrar comisiones y extornos
    filtro = df.iloc[:, 3].astype(str).str.contains('Comisión|Extorno', case=False, na=False)
    df_filtrado = df[filtro].copy()

    if df_filtrado.empty:
        print("⚠️ Sin información de comisiones/extornos")
        return []

    config = CONFIGURACIONES.get(tipo_archivo, {}).get('COMISION', {})
    filas = []

    # Procesar por fecha
    df_filtrado['fecha'] = pd.to_datetime(df_filtrado.iloc[:, 0], dayfirst=True, errors='coerce')
    df_filtrado['monto'] = limpiar_montos(df_filtrado.iloc[:, 2])
    df_filtrado['fecha_cierre'] = pd.to_datetime(df_filtrado.iloc[:, 4], dayfirst=True, errors='coerce')

    for fecha, grupo in df_filtrado.groupby('fecha'):
        fecha_cierre = grupo['fecha_cierre'].dropna().iloc[0] if not grupo[
            'fecha_cierre'].dropna().empty else datetime.now()

        # Línea 1 - YA USABA FECHA DE CIERRE CORRECTAMENTE
        linea1 = crear_linea_base(1, año=fecha_cierre.year,
                                  fecha=fecha.strftime("%Y%m%d"),
                                  fecha2=fecha_cierre.strftime("%Y%m%d"),
                                  mes=fecha_cierre.strftime("%m"),  # ← YA CORRECTO
                                  descripcion="COMISION", archivo=nombre_archivo)
        filas.append(linea1)

        suma_comisiones = 0
        # Procesar comisiones
        for _, fila in grupo.iterrows():
            categoria = str(fila.iloc[3])
            monto_original = fila['monto']

            if "Comisión" in categoria and monto_original != 0:
                monto = abs(monto_original)
                linea2 = crear_linea_detalle(40, config.get('linea2_campo14', 0), monto, nombre_archivo)
                filas.append(linea2)
                suma_comisiones += monto

        # Línea suma total de comisiones
        if suma_comisiones > 0:
            linea3 = crear_linea_detalle(config.get('linea3_campo13', 0),
                                         config.get('linea3_campo14', 0), suma_comisiones, nombre_archivo)
            filas.append(linea3)

        # Procesar extornos
        for _, fila in grupo.iterrows():
            monto_original = fila['monto']
            categoria = str(fila.iloc[3])

            if "Extorno" in categoria and monto_original != 0:
                monto = abs(monto_original)
                if monto_original > 0:
                    filas.extend([
                        crear_linea_detalle(40, 1101020064, monto, nombre_archivo),
                        crear_linea_detalle(50, 2107808010, monto, nombre_archivo)
                    ])
                else:
                    filas.extend([
                        crear_linea_detalle(40, 2107808010, monto, nombre_archivo),
                        crear_linea_detalle(50, 1101020065, monto, nombre_archivo)
                    ])

        filas.append([""] * 26)

    total_procesado = df_filtrado['monto'].abs().sum()
    print(f"✓ Procesadas {len(df_filtrado.groupby('fecha'))} fechas con monto total: {total_procesado:.2f}")
    return filas


def procesar_hoja_compensacion(df, nombre_archivo, tipo_archivo):
    """Procesa compensaciones DZ."""
    print(f"\n=== PROCESANDO {tipo_archivo} - COBRANZA ===")

    if len(df.columns) < 4:
        print("⚠️ Columnas insuficientes")
        return []

    # Filtrar registros DZ
    df_dz = df[df.iloc[:, 1].astype(str).str.contains('DZ', case=False, na=False)].copy()

    if df_dz.empty:
        print("⚠️ Sin información de compensaciones DZ")
        return []

    config = CONFIGURACIONES.get(tipo_archivo, {}).get('COMPENSACION', {})
    filas = []

    df_dz['fecha'] = pd.to_datetime(df_dz.iloc[:, 2], dayfirst=True, errors='coerce')
    df_dz['monto'] = limpiar_montos(df_dz.iloc[:, 3]).abs()

    # CORRECCIÓN: Para archivos estándar, fecha de cierre está en columna 6 (campo 7)
    if len(df_dz.columns) >= 7:
        df_dz['fecha_cierre'] = pd.to_datetime(df_dz.iloc[:, 6], dayfirst=True, errors='coerce')
    else:
        df_dz['fecha_cierre'] = datetime.now()

    resumen = df_dz.groupby('fecha')['monto'].sum().reset_index()

    for _, row in resumen.iterrows():
        fecha = row['fecha']
        monto = row['monto']

        # Usar fecha de cierre para el mes
        fecha_cierre_grupo = df_dz[df_dz['fecha'] == fecha]['fecha_cierre'].dropna()
        if not fecha_cierre_grupo.empty:
            fecha_cierre = fecha_cierre_grupo.iloc[0]
        else:
            fecha_cierre = datetime.now()

        # Líneas - USAR MES DE FECHA DE CIERRE
        linea1 = crear_linea_base(1, año=fecha_cierre.year, codigo="DZ",
                                  fecha=fecha.strftime("%Y%m%d"),
                                  fecha2=fecha_cierre.strftime("%Y%m%d"),
                                  mes=fecha_cierre.strftime("%m"),
                                  descripcion="COBRANZA", archivo=nombre_archivo)

        linea2 = crear_linea_detalle(40, config.get('linea2_campo14', 0), monto, nombre_archivo)
        linea3 = crear_linea_detalle(config.get('linea3_campo13', 0),
                                     config.get('linea3_campo14', 0), monto, nombre_archivo)
        linea3[20] = "Z001"

        filas.extend([linea1, linea2, linea3, [""] * 26])

    print(f"✓ Procesadas {len(resumen)} fechas con monto total: {resumen['monto'].sum():.2f}")
    return filas


def procesar_hoja_ajuste(df, nombre_archivo, tipo_archivo):
    """Procesa ajustes RG."""
    print(f"\n=== PROCESANDO {tipo_archivo} - RECARGA ===")

    if len(df.columns) < 6:
        print("⚠️ Columnas insuficientes")
        return []

    # Filtrar RG + AJUSTE
    filtro_rg = df.iloc[:, 1].astype(str).str.contains('RG', case=False, na=False)
    filtro_ajuste = df.iloc[:, 5].astype(str).str.contains('AJUSTE', case=False, na=False)
    df_ajustes = df[filtro_rg & filtro_ajuste].copy()

    if df_ajustes.empty:
        print("⚠️ Sin información de ajustes")
        return []

    config = CONFIGURACIONES.get(tipo_archivo, {}).get('AJUSTE', {})
    filas = []

    df_ajustes['fecha'] = pd.to_datetime(df_ajustes.iloc[:, 2], dayfirst=True, errors='coerce')
    df_ajustes['monto_original'] = limpiar_montos(df_ajustes.iloc[:, 3])

    # CORRECCIÓN: Para archivos estándar, fecha de cierre está en columna 6 (campo 7)
    if len(df_ajustes.columns) >= 7:
        df_ajustes['fecha_cierre'] = pd.to_datetime(df_ajustes.iloc[:, 6], dayfirst=True, errors='coerce')
    else:
        df_ajustes['fecha_cierre'] = datetime.now()

    for _, row in df_ajustes.iterrows():
        fecha = row['fecha']
        monto_original = row['monto_original']
        monto_abs = abs(monto_original)
        es_positivo = monto_original >= 0

        # Usar fecha de cierre
        fecha_cierre = row['fecha_cierre'] if pd.notna(row['fecha_cierre']) else datetime.now()

        # Línea 1 - USAR MES DE FECHA DE CIERRE
        descripcion = "RECARGA POSITIVO" if es_positivo else "RECARGA NEGATIVO"
        linea1 = crear_linea_base(1, año=fecha_cierre.year, codigo="RG",
                                  fecha=fecha.strftime("%Y%m%d"),
                                  fecha2=fecha_cierre.strftime("%Y%m%d"),
                                  mes=fecha_cierre.strftime("%m"),
                                  descripcion=descripcion, archivo=nombre_archivo)

        # Líneas según signo
        if es_positivo:
            linea2 = crear_linea_detalle("01", config.get('campo14', 0), monto_abs, nombre_archivo)
            linea3 = crear_linea_detalle(31, 3000013956, monto_abs, nombre_archivo)
        else:
            linea2 = crear_linea_detalle(11, config.get('campo14', 0), monto_abs, nombre_archivo)
            linea3 = crear_linea_detalle(21, 3000013956, monto_abs, nombre_archivo)
            # NUEVO: Agregar Z001 cuando el código de la cuenta (posición 13) sea 11
            linea2[20] = "Z001"

        filas.extend([linea1, linea2, linea3, [""] * 26])

    print(f"✓ Procesados {len(df_ajustes)} recarga con monto total: {df_ajustes['monto_original'].sum():.2f}")
    return filas

def procesar_izipay_comision(df, nombre_archivo):
    """Procesa comisiones IZIPAY."""
    print(f"\n=== PROCESANDO IZIPAY - COMISIÓN ===")

    # Limpiar montos usando la función centralizada
    df = df.copy()
    df['monto_limpio'] = limpiar_montos(df.iloc[:, 2])
    filas = []

    for fecha, grupo in df.groupby(df.iloc[:, 0]):
        fecha_dt = pd.to_datetime(fecha)
        fecha_cierre = pd.to_datetime(grupo.iloc[0, 4]) if pd.notna(grupo.iloc[0, 4]) else datetime.now()

        # Línea 1 - YA USABA FECHA DE CIERRE CORRECTAMENTE
        linea1 = crear_linea_base(1, año=fecha_cierre.year,
                                  fecha=fecha_dt.strftime("%Y%m%d"),
                                  fecha2=fecha_cierre.strftime("%Y%m%d"),
                                  mes=fecha_cierre.strftime("%m"),
                                  descripcion="COMISION", archivo=nombre_archivo)
        filas.append(linea1)

        suma_montos = 0
        # Procesar comisiones
        for _, fila in grupo.iterrows():
            monto = abs(fila['monto_limpio']) if fila['monto_limpio'] != 0 else 0
            categoria = str(fila.iloc[3])

            if "Comisión" in categoria and monto > 0:
                codigo = next((v for k, v in CODIGO_CATEGORIAS_IZIPAY.items() if k in categoria), 0)
                linea = crear_linea_detalle(40, codigo, monto, nombre_archivo)
                filas.append(linea)
                suma_montos += monto

        # Línea suma total
        if suma_montos > 0:
            filas.append(crear_linea_detalle(50, 1101020065, suma_montos, nombre_archivo))

        # Procesar extornos
        for _, fila in grupo.iterrows():
            monto_original = fila['monto_limpio']
            categoria = str(fila.iloc[3])

            if "Extorno" in categoria and monto_original != 0:
                monto = abs(monto_original)
                if monto_original > 0:
                    filas.extend([
                        crear_linea_detalle(40, 1101020064, monto, nombre_archivo),
                        crear_linea_detalle(50, 2107808010, monto, nombre_archivo)
                    ])
                else:
                    filas.extend([
                        crear_linea_detalle(40, 2107808010, monto, nombre_archivo),
                        crear_linea_detalle(50, 1101020065, monto, nombre_archivo)
                    ])

        filas.append([""] * 26)

    print(f"✓ Información de comisiones procesada")
    return filas


def procesar_izipay_compensacion(df, nombre_archivo):
    """Procesa compensaciones IZIPAY."""
    print(f"\n=== PROCESANDO IZIPAY - COBRANZA ===")

    df['importe'] = limpiar_montos(df.iloc[:, 3])
    filas = []

    # CORRECCIÓN: Para IZIPAY, fecha de cierre está en columna 7 (campo 8)
    if len(df.columns) >= 8:
        df['fecha_cierre'] = pd.to_datetime(df.iloc[:, 7], dayfirst=True, errors='coerce')
    else:
        df['fecha_cierre'] = datetime.now()

    for fecha, grupo in df.groupby(df.iloc[:, 6]):  # Agrupar por fecha doc
        fecha_dt = pd.to_datetime(fecha)

        # Usar fecha de cierre para el mes
        fecha_cierre_grupo = grupo['fecha_cierre'].dropna()
        if not fecha_cierre_grupo.empty:
            fecha_cierre = fecha_cierre_grupo.iloc[0]
        else:
            fecha_cierre = datetime.now()

        # Línea 1 - USAR MES DE FECHA DE CIERRE
        linea1 = crear_linea_base(1, año=fecha_cierre.year, codigo="DZ",
                                  fecha=fecha_dt.strftime("%Y%m%d"),
                                  fecha2=fecha_cierre.strftime("%Y%m%d"),
                                  mes=fecha_cierre.strftime("%m"),
                                  descripcion="COBRANZA", archivo=nombre_archivo)
        filas.append(linea1)

        # Segunda línea si clase_doc = "DZ"
        grupo_dz = grupo[grupo.iloc[:, 1] == "DZ"]
        if not grupo_dz.empty:
            linea2 = crear_linea_detalle(40, 1101020064, abs(grupo_dz['importe'].sum()), nombre_archivo)
            filas.append(linea2)

        # Líneas por categorías
        for cat, codigo in CODIGO_COMPENSACION_IZIPAY.items():
            if cat == "MASTERCARD+IZIPAY":
                # Caso especial: agrupa MASTERCARD e IZIPAY
                grupo_cat = grupo[grupo.iloc[:, 4].isin(["MASTERCARD", "IZIPAY"])]
            else:
                # Casos normales: VISA, DINERS, AMEX
                grupo_cat = grupo[grupo.iloc[:, 4] == cat]

            if not grupo_cat.empty:
                suma_categoria = grupo_cat['importe'].sum()
                monto_abs = abs(suma_categoria)

                if cat == "MASTERCARD+IZIPAY":
                    # Lógica especial para MASTERCARD+IZIPAY
                    if suma_categoria < 0:
                        # Si es negativo, usar código "01"
                        codigo_linea = "01"
                    else:
                        # Si es positivo, usar código "11"
                        codigo_linea = 11
                else:
                    # Para las demás categorías, siempre usar código 11
                    codigo_linea = 11

                linea_cat = crear_linea_detalle(codigo_linea, codigo, monto_abs, nombre_archivo)

                # Solo agregar Z001 si el código no es "01"
                if codigo_linea != "01":
                    linea_cat[20] = "Z001"

                filas.append(linea_cat)

        filas.append([""] * 26)

    print(f"✓ Información de compensaciones procesada")
    return filas

def procesar_izipay_ajustes(df, nombre_archivo):
    """Procesa ajustes IZIPAY."""
    print(f"\n=== PROCESANDO IZIPAY - RECARGA ===")

    df_ajustes = df[df.iloc[:, 5] == "AJUSTE"].copy()
    if df_ajustes.empty:
        print("⚠️ Sin información de ajustes")
        return []

    df_ajustes['importe'] = limpiar_montos(df_ajustes.iloc[:, 3])
    filas = []

    for _, fila in df_ajustes.iterrows():
        fecha = pd.to_datetime(fila.iloc[2])
        importe = fila['importe']
        monto_abs = abs(importe)
        es_positivo = importe > 0

        # CORRECCIÓN: Para IZIPAY, fecha de cierre está en columna 7 (campo 8)
        fecha_cierre = pd.to_datetime(fila.iloc[7]) if len(fila) > 7 and pd.notna(fila.iloc[7]) else datetime.now()

        # Línea 1 - USA MES DE FECHA DE CIERRE
        descripcion = "RECARGA POSITIVO" if es_positivo else "RECARGA NEGATIVO"
        linea1 = crear_linea_base(1, año=fecha_cierre.year, codigo="RG",
                                  fecha=fecha.strftime("%Y%m%d"),
                                  fecha2=fecha_cierre.strftime("%Y%m%d"),
                                  mes=fecha_cierre.strftime("%m"),
                                  descripcion=descripcion, archivo=nombre_archivo)

        # Líneas según signo
        if es_positivo:
            linea2 = crear_linea_detalle("01", 1001417, monto_abs, nombre_archivo)
            linea3 = crear_linea_detalle(31, 3000013956, monto_abs, nombre_archivo)
        else:
            linea2 = crear_linea_detalle(11, 1001417, monto_abs, nombre_archivo)
            linea3 = crear_linea_detalle(21, 3000013956, monto_abs, nombre_archivo)
            # NUEVO: Agregar Z001 cuando el código de la cuenta (posición 13) sea 11
            linea2[20] = "Z001"

        filas.extend([linea1, linea2, linea3, [""] * 26])

    print(f"✓ Información de ajustes procesada")
    return filas


def procesar_hoja_ajuste(df, nombre_archivo, tipo_archivo):
    """Procesa ajustes RG."""
    print(f"\n=== PROCESANDO {tipo_archivo} - RECARGA ===")

    if len(df.columns) < 6:
        print("⚠️ Columnas insuficientes")
        return []

    # Filtrar RG + AJUSTE
    filtro_rg = df.iloc[:, 1].astype(str).str.contains('RG', case=False, na=False)
    filtro_ajuste = df.iloc[:, 5].astype(str).str.contains('AJUSTE', case=False, na=False)
    df_ajustes = df[filtro_rg & filtro_ajuste].copy()

    if df_ajustes.empty:
        print("⚠️ Sin información de ajustes")
        return []

    config = CONFIGURACIONES.get(tipo_archivo, {}).get('AJUSTE', {})
    filas = []

    df_ajustes['fecha'] = pd.to_datetime(df_ajustes.iloc[:, 2], dayfirst=True, errors='coerce')
    df_ajustes['monto_original'] = limpiar_montos(df_ajustes.iloc[:, 3])

    # CORRECCIÓN: Para archivos estándar, fecha de cierre está en columna 6 (campo 7)
    if len(df_ajustes.columns) >= 7:
        df_ajustes['fecha_cierre'] = pd.to_datetime(df_ajustes.iloc[:, 6], dayfirst=True, errors='coerce')
    else:
        df_ajustes['fecha_cierre'] = datetime.now()

    for _, row in df_ajustes.iterrows():
        fecha = row['fecha']
        monto_original = row['monto_original']
        monto_abs = abs(monto_original)
        es_positivo = monto_original >= 0

        # Usar fecha de cierre
        fecha_cierre = row['fecha_cierre'] if pd.notna(row['fecha_cierre']) else datetime.now()

        # Línea 1 - USAR MES DE FECHA DE CIERRE
        descripcion = "RECARGA POSITIVO" if es_positivo else "RECARGA NEGATIVO"
        linea1 = crear_linea_base(1, año=fecha_cierre.year, codigo="RG",
                                  fecha=fecha.strftime("%Y%m%d"),
                                  fecha2=fecha_cierre.strftime("%Y%m%d"),
                                  mes=fecha_cierre.strftime("%m"),
                                  descripcion=descripcion, archivo=nombre_archivo)

        # Líneas según signo
        if es_positivo:
            linea2 = crear_linea_detalle("01", config.get('campo14', 0), monto_abs, nombre_archivo)
            linea3 = crear_linea_detalle(31, 3000013956, monto_abs, nombre_archivo)
        else:
            linea2 = crear_linea_detalle(11, config.get('campo14', 0), monto_abs, nombre_archivo)
            linea3 = crear_linea_detalle(21, 3000013956, monto_abs, nombre_archivo)
            # NUEVO: Agregar Z001 cuando el código de la cuenta (posición 13) sea 11
            linea2[20] = "Z001"

        filas.extend([linea1, linea2, linea3, [""] * 26])

    print(f"✓ Procesados {len(df_ajustes)} recarga con monto total: {df_ajustes['monto_original'].sum():.2f}")
    return filas


def procesar_archivo(archivo_entrada, archivo_salida, tipo_archivo):
    """Procesa archivos Excel y genera las hojas requeridas."""
    try:
        nombre_archivo = tipo_archivo
        print(f"\n{'=' * 50}")
        print(f"PROCESANDO: {nombre_archivo}")
        print(f"{'=' * 50}")

        hojas_datos = {}

        if tipo_archivo == 'IZIPAY':
            # Procesamiento especial para IZIPAY
            try:
                df_izipay = pd.read_excel(archivo_entrada, sheet_name='IZIPAY')
                hojas_datos['COMISION'] = procesar_izipay_comision(df_izipay, nombre_archivo)
            except Exception as e:
                print(f"⚠️ Error en hoja IZIPAY: {e}")

            try:
                df_comp = pd.read_excel(archivo_entrada, sheet_name='COMPENSACION')
                hojas_datos['COBRANZA'] = procesar_izipay_compensacion(df_comp, nombre_archivo)
                hojas_datos['RECARGA'] = procesar_izipay_ajustes(df_comp, nombre_archivo)
            except Exception as e:
                print(f"⚠️ Error en hoja COMPENSACION: {e}")

        elif tipo_archivo == 'EFECTIVO':
            # Procesamiento especial para EFECTIVO - Solo COBRANZA y RECARGA
            try:
                df_compensacion = pd.read_excel(archivo_entrada, sheet_name='COMPENSACION')
                hojas_datos['COBRANZA'] = procesar_hoja_compensacion(df_compensacion, nombre_archivo, tipo_archivo)
                hojas_datos['RECARGA'] = procesar_hoja_ajuste(df_compensacion, nombre_archivo, tipo_archivo)
            except Exception as e:
                print(f"⚠️ Error en hoja COMPENSACION para EFECTIVO: {e}")

        else:
            # Procesamiento estándar
            try:
                df_principal = pd.read_excel(archivo_entrada, sheet_name=tipo_archivo)
                hojas_datos['COMISION'] = procesar_hoja_comision(df_principal, nombre_archivo, tipo_archivo)
            except Exception as e:
                print(f"⚠️ Error en hoja {tipo_archivo}: {e}")

            try:
                df_comp = pd.read_excel(archivo_entrada, sheet_name='COMPENSACION')
                hojas_datos['COBRANZA'] = procesar_hoja_compensacion(df_comp, nombre_archivo, tipo_archivo)
                hojas_datos['RECARGA'] = procesar_hoja_ajuste(df_comp, nombre_archivo, tipo_archivo)
            except Exception as e:
                print(f"⚠️ Error en hoja COMPENSACION: {e}")

        # Guardar archivo
        if any(hojas_datos.values()):
            os.makedirs(os.path.dirname(archivo_salida), exist_ok=True)

            with pd.ExcelWriter(archivo_salida, engine='openpyxl') as writer:
                for nombre_hoja, datos in hojas_datos.items():
                    if datos:
                        df = pd.DataFrame(datos)
                        df.to_excel(writer, index=False, header=False, sheet_name=nombre_hoja)

            print(f"\n🎉 COMPLETADO: {archivo_salida}")
        else:
            print("⚠️ No se generaron hojas")

    except Exception as e:
        print(f"❌ Error procesando {tipo_archivo}: {e}")


def main():
    """Función principal."""
    carpeta_entrada = r'C:\Automatizacion\Asientos conciliacion\Entrada'
    carpeta_salida = r'C:\Automatizacion\Asientos conciliacion\Salida'

    print("🚀 INICIANDO PROCESAMIENTO DE ARCHIVOS")
    print(f"📁 Entrada: {carpeta_entrada}")
    print(f"📁 Salida: {carpeta_salida}")

    archivos_encontrados = buscar_archivos(carpeta_entrada)

    for tipo_archivo, archivo_entrada in archivos_encontrados.items():
        if archivo_entrada and os.path.exists(archivo_entrada):
            archivo_salida = os.path.join(carpeta_salida, f'resultado_{tipo_archivo.lower()}_procesado.xlsx')
            procesar_archivo(archivo_entrada, archivo_salida, tipo_archivo)
        else:
            print(f"⚠️ Archivo no encontrado: {tipo_archivo}")

    input("\n✅ Proceso finalizado correctamente. Presiona Enter para cerrar la ventana...")


if __name__ == "__main__":
    main()