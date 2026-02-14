import streamlit as st
import pandas as pd
import requests
import json
import base64
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
import time
import re

# ==========================================
# ⚙️ 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Taller Pro - v26 Escudo", page_icon="🚀", layout="wide")

# Inicializamos el estado de la batería de datos si no existe
if 'batch' not in st.session_state:
    st.session_state.batch = pd.DataFrame() 

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    st.error("❌ Falta la API Key en los Secrets.")
    st.stop()

# ==========================================
# ☁️ 2. CONEXIÓN SEGURA
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
        if not ws.row_values(1): ws.insert_row(columnas, 1)
        return ws
    except:
        ws = sh.add_worksheet(title=nombre_hoja, rows="2000", cols="20")
        ws.insert_row(columnas, 1)
        return ws

# ==========================================
# 🧠 3. MOTOR PARAGUAYO (ANTI-CEROS PERDIDOS)
# ==========================================
def limpiar_monto_py(valor, es_cantidad=False):
    if valor is None or valor == "": return 0
    s = str(valor).upper().replace('GS', '').replace('$', '').replace(' ', '').strip()
    try:
        if es_cantidad:
            s = s.replace(',', '.')
            if s.count('.') > 1:
                partes = s.split('.')
                s = "".join(partes[:-1]) + "." + partes[-1]
            return float(s)
        else:
            # Blindaje Guaraní: Solo números. 10.000 -> 10000
            s_limpio = re.sub(r'[^\d]', '', s) 
            return int(s_limpio) if s_limpio else 0
    except: return 0

def analizar_factura_v1(archivo_bytes, mime_type):
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={API_KEY}"
    archivo_b64 = base64.b64encode(archivo_bytes).decode('utf-8')
    payload = {
        "contents": [{
            "parts": [
                {"text": "Analiza esta factura. Devuelve JSON: fecha (YYYY-MM-DD), proveedor, nro_factura, e items (producto, cantidad, unitario, total)."},
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
    st.title("🔐 Acceso Taller Pro")
    u = st.text_input("Usuario")
    p = st.text_input("Pass", type="password")
    if st.button("Entrar"):
        st.session_state.auth, st.session_state.user, st.session_state.rol = True, u, 'admin'
        st.rerun()
else:
    menu = st.sidebar.radio("Menú", ["📥 Carga Masiva", "📊 Dashboard", "📅 Historial", "🚀 Salir"])
    sh = conectar_sheets()

    if menu == "📥 Carga Masiva":
        st.title(f"📥 Carga Masiva para: {st.session_state.user}")
        files = st.file_uploader("Sube hasta 20 facturas", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
        
        if files and st.button(f"Procesar {len(files)} archivos"):
            all_items = []
            bar = st.progress(0)
            for idx, f in enumerate(files):
                st.write(f"⏳ Analizando: {f.name}...")
                d = analizar_factura_v1(f.getvalue(), f.type)
                if d:
                    for it in d.get('items', []):
                        all_items.append({
                            'Fecha': d.get('fecha', ""), 'Proveedor': d.get('proveedor', ""),
                            'Factura': d.get('nro_factura', ""), 'Producto': it.get('producto', ""),
                            'Cantidad': limpiar_monto_py(it.get('cantidad'), True),
                            'Unitario': limpiar_monto_py(it.get('unitario')),
                            'Total': limpiar_monto_py(it.get('total'))
                        })
                bar.progress((idx + 1) / len(files))
            # Guardamos como DataFrame real
            st.session_state.batch = pd.DataFrame(all_items)
            st.success("✅ Análisis finalizado.")

        # FIX DEL ERROR: Verificamos que sea DataFrame y no esté vacío
        if isinstance(st.session_state.batch, pd.DataFrame):
            if not st.session_state.batch.empty:
                st.markdown("---")
                st.subheader("📝 Revisión de Datos")
                
                # Editor de datos
                edited = st.data_editor(st.session_state.batch, use_container_width=True)
                
                col1, col2 = st.columns([1, 4])
                if col1.button("Guardar Todo", type="primary"):
                    ws = obtener_o_crear_pestana(sh, st.session_state.user)
                    try:
                        existentes = pd.DataFrame(ws.get_all_records())
                    except: existentes = pd.DataFrame()
                    
                    with st.spinner("Guardando en Sheets..."):
                        for _, r in edited.iterrows():
                            id_u = f"{r['Proveedor']}_{r['Fecha']}_{r['Factura']}_{r['Producto']}".upper().replace(" ","")
                            if not existentes.empty and 'ID_Unico' in existentes.columns:
                                if id_u in existentes['ID_Unico'].values: continue
                            
                            ws.append_row([
                                str(r['Fecha']), str(r['Proveedor']), str(r['Factura']),
                                r['Producto'], r['Cantidad'], "u", r['Unitario'], r['Total'],
                                st.session_state.user, id_u, str(datetime.datetime.now())
                            ])
                    st.success("✅ ¡Guardado con éxito!")
                    st.session_state.batch = pd.DataFrame() # Reseteamos a DataFrame vacío
                    st.balloons()
                
                if col2.button("Cancelar Carga"):
                    st.session_state.batch = pd.DataFrame()
                    st.rerun()

    elif menu == "📊 Dashboard":
        st.title("📊 Resumen de Gastos")
        # Lógica de dashboard similar a la anterior...
        st.info("Sube datos para ver los gráficos.")

    elif menu == "📅 Historial":
        st.title("📅 Historial")
        ws = obtener_o_crear_pestana(sh, st.session_state.user)
        try:
            df_hist = pd.DataFrame(ws.get_all_records())
            st.dataframe(df_hist, use_container_width=True)
        except:
            st.warning("No hay registros aún.")

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
