import streamlit as st
import pandas as pd
import requests
import json
import base64
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
import re

# ==========================================
# ⚙️ 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Taller Pro - v31 Cálculo Pro", page_icon="🔧", layout="wide")

if 'batch' not in st.session_state:
    st.session_state.batch = pd.DataFrame()

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    st.error("❌ Error: API Key no configurada.")
    st.stop()

# ==========================================
# ☁️ 2. CONEXIÓN Y GESTIÓN DE HOJAS
# ==========================================
def conectar_sheets():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gc = gspread.authorize(creds)
        return gc.open("BaseDatos_Taller")
    except: return None

def obtener_o_crear_pestana(sh, nombre_usuario):
    nombre_hoja = f"Gasto-{nombre_usuario}"
    columnas = ["Fecha", "Proveedor", "Factura", "Producto", "Cantidad", "Medida", "Unitario", "Total", "Usuario", "ID_Unico", "Timestamp"]
    try:
        ws = sh.worksheet(nombre_hoja)
        headers = ws.row_values(1)
        if not headers or "ID_Unico" not in headers:
            ws.insert_row(columnas, 1)
        return ws
    except:
        ws = sh.add_worksheet(title=nombre_hoja, rows="3000", cols="20")
        ws.insert_row(columnas, 1)
        return ws

def limpiar_monto_py(valor, es_cantidad=False):
    if valor is None or str(valor).strip() == "": return 0.0
    s = str(valor).upper().replace('GS', '').replace('$', '').replace(' ', '').strip()
    try:
        if es_cantidad:
            # Reemplaza coma por punto para decimales (ej: 1,5 -> 1.5)
            s = s.replace(',', '.')
            if s.count('.') > 1:
                partes = s.split('.')
                s = "".join(partes[:-1]) + "." + partes[-1]
            return float(s)
        else:
            # Moneda: Solo números enteros (10.000 -> 10000)
            s_solo_numeros = re.sub(r'\D', '', s)
            return int(s_solo_numeros) if s_solo_numeros else 0
    except: return 0.0

def analizar_factura_v1(archivo_bytes, mime_type):
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={API_KEY}"
    archivo_b64 = base64.b64encode(archivo_bytes).decode('utf-8')
    payload = {
        "contents": [{
            "parts": [
                {"text": "Analiza esta factura. Extrae JSON: fecha (YYYY-MM-DD), proveedor, nro_factura, e items (producto, cantidad, unitario, total)."},
                {"inline_data": {"mime_type": mime_type, "data": archivo_b64}}
            ]
        }]
    }
    try:
        response = requests.post(url, json=payload, timeout=40)
        texto_ia = response.json()['candidates'][0]['content']['parts'][0]['text']
        return json.loads(texto_ia.replace("```json", "").replace("```", "").strip())
    except: return None

# ==========================================
# 🖥️ 4. INTERFAZ
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso Sistema Taller")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Entrar"):
        st.session_state.auth, st.session_state.user = True, u
        st.rerun()
else:
    menu = st.sidebar.radio("Menú", ["📥 Carga Masiva", "📊 Dashboard", "📅 Historial", "🚀 Salir"])
    sh = conectar_sheets()

    if menu == "📥 Carga Masiva":
        st.title(f"📥 Carga Masiva")
        files = st.file_uploader("Subir archivos", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
        
        if files and st.button(f"Procesar {len(files)} archivos"):
            all_items = []
            bar = st.progress(0)
            for idx, f in enumerate(files):
                d = analizar_factura_v1(f.getvalue(), f.type)
                if d:
                    for it in d.get('items', []):
                        cant = limpiar_monto_py(it.get('cantidad'), True)
                        unit = limpiar_monto_py(it.get('unitario'))
                        all_items.append({
                            'Fecha': d.get('fecha', ""), 'Proveedor': d.get('proveedor', ""),
                            'Factura': d.get('nro_factura', ""), 'Producto': it.get('producto', ""),
                            'Cantidad': cant, 'Unitario': unit, 'Total': int(cant * unit)
                        })
                bar.progress((idx + 1) / len(files))
            st.session_state.batch = pd.DataFrame(all_items)

        if not st.session_state.batch.empty:
            st.info("💡 Al modificar Cantidad o Unitario, el Total se recalculará al guardar.")
            # Configuración de columnas para permitir decimales en Cantidad
            edited = st.data_editor(
                st.session_state.batch, 
                use_container_width=True,
                column_config={
                    "Cantidad": st.column_config.NumberColumn(format="%.2f"),
                    "Total": st.column_config.NumberColumn(disabled=True) # Bloqueado porque es calculado
                }
            )
            
            if st.button("Guardar en la Nube", type="primary"):
                ws = obtener_o_crear_pestana(sh, st.session_state.user)
                df_actual = pd.DataFrame(ws.get_all_records())
                
                with st.spinner("Guardando..."):
                    for _, r in edited.iterrows():
                        # RECALCULO ANTES DE GUARDAR
                        final_total = int(float(r['Cantidad']) * int(r['Unitario']))
                        id_u = f"{r['Proveedor']}_{r['Fecha']}_{r['Factura']}_{r['Producto']}".upper().replace(" ", "")
                        
                        if not df_actual.empty and 'ID_Unico' in df_actual.columns:
                            if id_u in df_actual['ID_Unico'].astype(str).values: continue
                        
                        ws.append_row([
                            str(r['Fecha']), str(r['Proveedor']), str(r['Factura']), 
                            str(r['Producto']), r['Cantidad'], "u", 
                            int(r['Unitario']), final_total, 
                            st.session_state.user, id_u, str(datetime.datetime.now())
                        ])
                st.success("✅ Guardado con totales recalculados.")
                st.session_state.batch = pd.DataFrame()
                st.balloons()

    # --- MÓDULO 2: DASHBOARD ---
    elif menu == "📊 Dashboard":
        st.title("📊 Indicadores")
        dfs = []
        for h in sh.worksheets():
            if h.title.startswith("Gasto-"):
                data = h.get_all_records()
                if data: dfs.append(pd.DataFrame(data))
        df = pd.concat(dfs) if dfs else pd.DataFrame()
        if not df.empty:
            df['Total'] = pd.to_numeric(df['Total'], errors='coerce').fillna(0)
            st.metric("Inversión Total", f"{df['Total'].sum():,.0f} Gs.")
            st.plotly_chart(px.pie(df, values='Total', names='Proveedor', hole=.4), use_container_width=True)
        else: st.info("Sin datos.")

    # --- MÓDULO 3: HISTORIAL (CON CÁLCULO Y ELIMINACIÓN) ---
    elif menu == "📅 Historial":
        st.title("📅 Gestión del Historial")
        ws = obtener_o_crear_pestana(sh, st.session_state.user)
        df_full = pd.DataFrame(ws.get_all_records())
        
        if not df_full.empty:
            col1, col2 = st.columns([2, 2])
            with col1: search = st.text_input("🔍 Buscar por Producto", "")
            with col2: fecha_rango = st.date_input("📅 Rango", [])

            df_display = df_full.copy()
            df_display.insert(0, "Eliminar", False)
            df_display['Cantidad'] = pd.to_numeric(df_display['Cantidad'], errors='coerce')
            df_display['Unitario'] = pd.to_numeric(df_display['Unitario'], errors='coerce')
            df_display['Total'] = pd.to_numeric(df_display['Total'], errors='coerce')
            
            if search:
                df_display = df_display[df_display['Producto'].astype(str).str.contains(search, case=False, na=False)]
            if len(fecha_rango) == 2:
                start, end = fecha_rango
                df_display['Fecha_dt'] = pd.to_datetime(df_display['Fecha'], errors='coerce').dt.date
                df_display = df_display[(df_display['Fecha_dt'] >= start) & (df_display['Fecha_dt'] <= end)]
                df_display.drop(columns=['Fecha_dt'], inplace=True)
            
            st.info("✍️ Al editar Cantidad o Unitario, el Total se actualizará al presionar 'Aplicar Cambios'.")
            
            df_edited = st.data_editor(
                df_display.sort_values(by="Timestamp", ascending=False),
                use_container_width=True,
                disabled=["ID_Unico", "Usuario", "Timestamp", "Total"], # Total bloqueado para asegurar cálculo
                hide_index=True,
                column_config={"Cantidad": st.column_config.NumberColumn(format="%.2f")}
            )
            
            if st.button("💾 Aplicar Cambios y Eliminaciones", type="primary"):
                with st.spinner("Sincronizando..."):
                    # RECALCULAR TOTALES EN EL DATAFRAME EDITADO
                    df_edited['Total'] = df_edited['Cantidad'] * df_edited['Unitario']
                    df_edited['Total'] = df_edited['Total'].apply(lambda x: int(round(x)))
                    
                    ids_a_eliminar = df_edited[df_edited['Eliminar'] == True]['ID_Unico'].values
                    df_full.set_index('ID_Unico', inplace=True)
                    df_edited_clean = df_edited[df_edited['Eliminar'] == False].drop(columns=['Eliminar'])
                    df_edited_clean.set_index('ID_Unico', inplace=True)
                    
                    df_full.update(df_edited_clean)
                    df_full.reset_index(inplace=True)
                    df_final = df_full[~df_full['ID_Unico'].isin(ids_a_eliminar)]
                    
                    ws.clear()
                    columnas = ["Fecha", "Proveedor", "Factura", "Producto", "Cantidad", "Medida", "Unitario", "Total", "Usuario", "ID_Unico", "Timestamp"]
                    datos_a_subir = [columnas] + df_final[columnas].values.tolist()
                    ws.update('A1', datos_a_subir)
                    
                st.success("✅ Cambios aplicados y totales recalculados.")
                st.rerun()
        else: st.info("No hay registros.")

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
